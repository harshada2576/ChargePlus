"""ChargePlus — Base Source Adapter Architecture.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.2 (Build Source-Specific Adapters)

Defines the abstract BaseSourceAdapter and result container models that all
external data source adapters must implement.

Key Architectural Guarantees:
- Strict Layer Separation: Source Adapter produces canonical Step 2.1 contracts.
- Boundary Lock: Adapters NEVER write to Supabase or mutate operational tables.
- Record-Level Error Isolation: One malformed record in a batch of 1,000 does NOT
  crash the batch; 999 records parse and normalize, 1 record produces an explicit failure.
- Provenance Preserved: Every record retains verbatim raw payload and SHA-256 hash.
- Missing means Missing: Adapters never fabricate default values.
"""

from __future__ import annotations

import abc
import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlsplit
from pydantic import BaseModel, Field

import requests

from backend.ingestion.contracts import (
    NormalizedStationRecord,
    ProvenanceInfo,
    RawSourceRecord,
)
from backend.ingestion.validation import DataQualityValidator, ValidationResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared upstream-transport helpers (used by every source adapter).
#
# One implementation here beats one retry loop per adapter: timeouts, HTTP 429,
# HTTP 5xx, and connection errors all get bounded retries with exponential
# backoff, jitter, and Retry-After support, and every adapter inherits the
# same failure vocabulary that ScheduledIngestionOrchestrator classifies.
# ---------------------------------------------------------------------------

# Nominal retry budget for a single upstream HTTP request. Whole-run retries
# remain the orchestrator's job; this only absorbs transient per-request
# failures so one blip does not fail an entire source poll.
DEFAULT_REQUEST_MAX_ATTEMPTS = 3
DEFAULT_REQUEST_BASE_DELAY_SEC = 0.5
DEFAULT_REQUEST_MAX_DELAY_SEC = 5.0

# Statuses worth retrying at the transport layer. Other 4xx (401/403/404) are
# returned untouched so callers can raise domain-specific errors (e.g. bad
# credentials, unknown dataset) instead of burning retries on them.
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def _default_sleep(seconds: float) -> None:
    """Module-level sleep indirection so tests can patch transport timing."""
    time.sleep(seconds)


def _parse_retry_after(headers: Any) -> Optional[float]:
    """Extracts Retry-After delay seconds from response headers, if present."""
    try:
        raw = None
        if headers is not None:
            getter = getattr(headers, "get", None)
            raw = getter("Retry-After", None) if callable(getter) else None
            if raw is None and isinstance(headers, dict):
                raw = headers.get("retry-after", headers.get("Retry-After"))
        if raw is None:
            return None
        return max(0.0, float(str(raw).strip()))
    except (ValueError, TypeError, AttributeError):
        return None


def validate_endpoint_url(url: str, *, caller: str = "adapter") -> str:
    """Validates a configurable upstream endpoint URL against SSRF risks.

    Rules (minimal, edge-case-correct):
      - Only http/https schemes. Anything else (file://, ftp://, ...) is
        rejected outright.
      - No URL-embedded credentials (user:pass@host) — secrets must travel in
        headers or env vars, never in the URL.
      - Plain http is allowed ONLY for loopback hosts (isolated simulator /
        local test doubles). Anything else must use https.
      - Empty or unparseable URLs are rejected.

    NOTE (known ceiling): this does not resolve DNS or block private ranges —
    endpoint URLs come from operator-controlled env config, never from end-user
    input, and adapters run server-side only. Revisit if endpoints ever become
    user-configurable.
    """
    if not url or not isinstance(url, str):
        raise ValueError(f"{caller}: endpoint URL must be a non-empty string")
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise ValueError(
            f"{caller}: endpoint URL must use http(s), got scheme {parts.scheme!r}"
        )
    if not parts.hostname:
        raise ValueError(f"{caller}: endpoint URL has no host: {url!r}")
    if parts.username or parts.password:
        raise ValueError(
            f"{caller}: endpoint URL must not embed credentials; "
            "pass secrets via headers or environment variables"
        )
    if parts.scheme == "http" and parts.hostname not in (
        "localhost", "127.0.0.1", "::1",
    ):
        raise ValueError(
            f"{caller}: plain http is only allowed for loopback test endpoints; "
            f"use https for {parts.hostname}"
        )
    return url.strip()


def request_with_retry(
    method: str,
    url: str,
    *,
    max_attempts: int = DEFAULT_REQUEST_MAX_ATTEMPTS,
    timeout_sec: float = 30.0,
    base_delay_sec: float = DEFAULT_REQUEST_BASE_DELAY_SEC,
    max_delay_sec: float = DEFAULT_REQUEST_MAX_DELAY_SEC,
    sleep_fn: Optional[Callable[[float], None]] = None,
    **request_kwargs: Any,
) -> "requests.Response":
    """Performs one upstream HTTP request with bounded retries.

    Retries (with exponential backoff, jitter, and Retry-After honoring, all
    capped at max_delay_sec):
      - requests Timeout / ConnectionError
      - HTTP 408 / 429 / 5xx

    Returns the response for every other status (including 401/403/404) so the
    caller can raise precise domain errors. Raises TimeoutError /
    ConnectionError (original type preserved) when transport retries are
    exhausted, or RuntimeError with a "rate limit" / "server error (HTTP …)"
    message when status retries are exhausted — the exact vocabulary the
    scheduled orchestrator classifies as TRANSIENT.
    """
    if method not in ("get", "post"):
        raise ValueError(f"request_with_retry supports 'get'/'post', got {method!r}")
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    validated_url = validate_endpoint_url(url)
    send = getattr(requests, method)  # resolved per call: mock-friendly
    sleeper = sleep_fn or _default_sleep  # module-global lookup: patchable

    last_status: Optional[int] = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = send(validated_url, timeout=timeout_sec, **request_kwargs)
        except (requests.exceptions.Timeout, TimeoutError) as exc:
            if attempt >= max_attempts:
                raise TimeoutError(
                    f"Upstream request timed out after {timeout_sec}s "
                    f"({max_attempts} attempts): {validated_url}"
                ) from exc
            _sleep_backoff(attempt, None, base_delay_sec, max_delay_sec, sleeper)
            continue
        except requests.exceptions.ConnectionError as exc:
            if attempt >= max_attempts:
                raise ConnectionError(
                    f"Failed to connect to upstream ({max_attempts} attempts): "
                    f"{type(exc).__name__}"
                ) from exc
            _sleep_backoff(attempt, None, base_delay_sec, max_delay_sec, sleeper)
            continue
        except requests.exceptions.RequestException as exc:
            # Non-transport request errors (bad URL, too many redirects, …)
            # will not heal on retry: fail fast without secret leakage.
            raise ConnectionError(f"Upstream request failed: {type(exc).__name__}") from exc

        status = getattr(response, "status_code", None)
        last_status = status
        if status in RETRYABLE_STATUS_CODES:
            retry_after = _parse_retry_after(getattr(response, "headers", None))
            if attempt >= max_attempts:
                if status == 429:
                    raise RuntimeError(
                        "Upstream rate limit exceeded "
                        f"(HTTP 429, {max_attempts} attempts). "
                        "Back off before retrying."
                    )
                raise RuntimeError(
                    f"Upstream server error (HTTP {status}, {max_attempts} attempts). "
                    "Retry with exponential backoff."
                )
            _sleep_backoff(attempt, retry_after, base_delay_sec, max_delay_sec, sleeper)
            continue
        return response

    # Unreachable: loop either returns or raises. Kept as a guard.
    raise RuntimeError(
        f"Upstream request failed after {max_attempts} attempts "
        f"(last status: {last_status})"
    )


def _sleep_backoff(
    attempt: int,
    retry_after: Optional[float],
    base_delay_sec: float,
    max_delay_sec: float,
    sleeper: Callable[[float], None],
) -> None:
    """Sleeps one bounded exponential-backoff-with-jitter step."""
    backoff = min(max_delay_sec, base_delay_sec * (2.0 ** (attempt - 1)))
    backoff *= 0.8 + 0.4 * random.random()  # ±20% jitter
    if retry_after is not None and retry_after > 0:
        backoff = min(max_delay_sec, max(backoff, min(retry_after, max_delay_sec)))
    else:
        backoff = min(max_delay_sec, backoff)
    logger.debug("Upstream retry %d: sleeping %.2fs", attempt, backoff)
    sleeper(max(0.0, backoff))


class AdapterResult(BaseModel):
    """Result of processing a single raw source payload through an adapter.
    
    Contains the verbatim Layer 1 raw record, the normalized Layer 2 station record,
    the data quality validation evaluation, and any record-level errors or warnings.
    """
    success: bool = Field(
        ...,
        description="True if record parsed and normalized without fatal schema or data errors"
    )
    source_id: str = Field(
        ...,
        description="Source identifier (e.g. 'open_charge_map')"
    )
    source_station_id: Optional[str] = Field(
        default=None,
        description="External source primary record identifier"
    )
    raw_record: Optional[RawSourceRecord] = Field(
        default=None,
        description="Layer 1 verbatim source record with SHA-256 payload hash"
    )
    station_record: Optional[NormalizedStationRecord] = Field(
        default=None,
        description="Layer 2 canonical normalized station record ready for validation"
    )
    validation_result: Optional[ValidationResult] = Field(
        default=None,
        description="Data quality evaluation result (ACCEPT, ACCEPT_WITH_WARNINGS, QUARANTINE, REJECT)"
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Fatal record-level parsing or schema normalization errors"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal data quality warnings emitted during parsing or normalization"
    )

    class Config:
        arbitrary_types_allowed = True
        extra = "forbid"

    @property
    def provenance(self) -> Optional[ProvenanceInfo]:
        """Convenience property to access provenance information."""
        if self.raw_record:
            return self.raw_record.to_provenance()
        return None


class BatchAdapterResult(BaseModel):
    """Aggregated result of processing a batch of external source payloads.
    
    Guarantees record-level error isolation: individual failures are captured
    in their respective AdapterResult without terminating the batch.
    """
    source_id: str = Field(
        ...,
        description="Source identifier"
    )
    total_records: int = Field(
        ...,
        ge=0,
        description="Total number of external payloads submitted to the batch"
    )
    successful_records: int = Field(
        ...,
        ge=0,
        description="Count of records that parsed and normalized successfully"
    )
    failed_records: int = Field(
        ...,
        ge=0,
        description="Count of records that encountered fatal parsing or schema errors"
    )
    results: list[AdapterResult] = Field(
        default_factory=list,
        description="Individual processing results for every record in the batch"
    )
    batch_errors: list[str] = Field(
        default_factory=list,
        description="Batch-level infrastructure or transport errors"
    )

    class Config:
        arbitrary_types_allowed = True
        extra = "forbid"

    @property
    def valid_stations(self) -> list[NormalizedStationRecord]:
        """Returns list of normalized stations whose data quality outcome is ACCEPT or ACCEPT_WITH_WARNINGS."""
        stations: list[NormalizedStationRecord] = []
        for r in self.results:
            if r.success and r.station_record and r.validation_result and r.validation_result.is_valid:
                stations.append(r.station_record)
        return stations

    @property
    def rejected_records(self) -> list[AdapterResult]:
        """Returns list of results that either failed parsing or were rejected by data quality rules."""
        rejected: list[AdapterResult] = []
        for r in self.results:
            if not r.success:
                rejected.append(r)
            elif r.validation_result and not r.validation_result.is_valid:
                rejected.append(r)
        return rejected

    @property
    def quarantined_records(self) -> list[AdapterResult]:
        """Returns list of results that produced a QUARANTINE validation outcome."""
        quarantined: list[AdapterResult] = []
        for r in self.results:
            if r.validation_result and r.validation_result.outcome.value == "QUARANTINE":
                quarantined.append(r)
        return quarantined


class BaseSourceAdapter(abc.ABC):
    """Abstract base class for all external EV charging station source adapters.
    
    Each external provider (OpenChargeMap, CPO APIs, government registries) must
    subclass BaseSourceAdapter and implement source-specific parsing and normalization.
    
    The adapter pipeline is cleanly decomposed into:
      1. fetch_raw()         -> Network transport (isolated for testability)
      2. parse_raw()         -> Wraps raw dictionary into Layer 1 RawSourceRecord
      3. normalize_station() -> Transforms provider schema into Layer 2 NormalizedStationRecord
      4. validate_record()   -> Evaluates against DataQualityValidator rules
      5. process_record()    -> End-to-end single record orchestration with error isolation
      6. process_batch()     -> End-to-end batch orchestration
    """

    @property
    @abc.abstractmethod
    def source_id(self) -> str:
        """Unique identifier slug for this data source (e.g. 'open_charge_map')."""
        pass

    @property
    def source_priority(self) -> int:
        """Default priority score for multi-source conflict resolution (1-100)."""
        return 100

    @abc.abstractmethod
    def extract_source_station_id(self, payload: dict[str, Any]) -> str:
        """Extracts the unique external station identifier from the raw payload.
        
        Raises ValueError if the identifier is missing or invalid.
        """
        pass

    def parse_raw(
        self,
        payload: dict[str, Any] | str,
        retrieved_at: Optional[datetime] = None,
        source_url: Optional[str] = None,
    ) -> RawSourceRecord:
        """Converts raw input into a Layer 1 RawSourceRecord.
        
        Computes deterministic SHA-256 hash over raw payload. Never mutates payload.
        """
        if isinstance(payload, str):
            try:
                dict_payload = json.loads(payload)
            except Exception as e:
                raise ValueError(f"Malformed raw JSON payload string: {e}") from e
        elif isinstance(payload, dict):
            dict_payload = payload
        else:
            raise TypeError(f"Expected dict or JSON string for payload, got {type(payload).__name__}")

        station_id = self.extract_source_station_id(dict_payload)
        now_utc = retrieved_at or datetime.now(timezone.utc)

        return RawSourceRecord(
            source_id=self.source_id,
            source_station_id=station_id,
            retrieval_timestamp=now_utc,
            source_url=source_url,
            raw_payload=dict_payload,
            source_priority=self.source_priority,
        )

    @abc.abstractmethod
    def normalize_station(self, raw: RawSourceRecord) -> NormalizedStationRecord:
        """Transforms a Layer 1 RawSourceRecord into a Layer 2 NormalizedStationRecord.
        
        Must preserve:
        - Source identity and provenance hash
        - Unmapped vendor fields in extra_metadata
        - Connector capacity and specifications (individual or aggregated)
        - Telemetry observation if and only if legitimately reported by source
        
        Must NOT:
        - Invent missing prices, power, availability, or coordinates
        - Fabricate synthetic physical connector IDs for aggregated groups
        """
        pass

    def validate_record(self, record: NormalizedStationRecord) -> ValidationResult:
        """Validates a normalized station record against canonical ChargePlus physical and business rules."""
        return DataQualityValidator.validate_record(record)

    def process_record(
        self,
        payload: dict[str, Any] | str,
        retrieved_at: Optional[datetime] = None,
        source_url: Optional[str] = None,
    ) -> AdapterResult:
        """Orchestrates parsing, normalization, and validation for a single raw source payload.
        
        Isolates record-level errors: if parsing fails, returns AdapterResult with success=False
        and detailed error list without raising exceptions to the caller.
        """
        errors: list[str] = []
        warnings: list[str] = []
        raw_record: Optional[RawSourceRecord] = None
        station_record: Optional[NormalizedStationRecord] = None
        validation_result: Optional[ValidationResult] = None
        station_id: Optional[str] = None

        # Step 1: Parse Raw Payload
        try:
            raw_record = self.parse_raw(payload, retrieved_at=retrieved_at, source_url=source_url)
            station_id = raw_record.source_station_id
        except Exception as e:
            errors.append(f"Failed to parse raw payload into RawSourceRecord: {str(e)}")
            return AdapterResult(
                success=False,
                source_id=self.source_id,
                source_station_id=station_id,
                raw_record=None,
                station_record=None,
                validation_result=None,
                errors=errors,
                warnings=warnings,
            )

        # Step 2: Normalize Record
        try:
            station_record = self.normalize_station(raw_record)
        except Exception as e:
            errors.append(f"Failed to normalize source record: {str(e)}")
            return AdapterResult(
                success=False,
                source_id=self.source_id,
                source_station_id=station_id,
                raw_record=raw_record,
                station_record=None,
                validation_result=None,
                errors=errors,
                warnings=warnings,
            )

        # Step 3: Validate Record
        try:
            validation_result = self.validate_record(station_record)
            warnings.extend(validation_result.warnings)
            if not validation_result.is_valid:
                errors.extend(validation_result.errors)
        except Exception as e:
            errors.append(f"Validation engine error: {str(e)}")

        is_success = len(errors) == 0

        return AdapterResult(
            success=is_success,
            source_id=self.source_id,
            source_station_id=station_id,
            raw_record=raw_record,
            station_record=station_record,
            validation_result=validation_result,
            errors=errors,
            warnings=warnings,
        )

    def process_batch(
        self,
        payloads: list[dict[str, Any] | str],
        retrieved_at: Optional[datetime] = None,
    ) -> BatchAdapterResult:
        """Processes a batch of external source payloads with record-level error isolation.
        
        A single malformed record will NOT terminate or fail the batch.
        """
        results: list[AdapterResult] = []
        successful_count = 0
        failed_count = 0
        now_utc = retrieved_at or datetime.now(timezone.utc)

        for idx, payload in enumerate(payloads):
            try:
                res = self.process_record(payload, retrieved_at=now_utc)
                if res.success:
                    successful_count += 1
                else:
                    failed_count += 1
                results.append(res)
            except Exception as e:
                # Catch unexpected top-level worker exceptions
                failed_count += 1
                results.append(
                    AdapterResult(
                        success=False,
                        source_id=self.source_id,
                        source_station_id=None,
                        raw_record=None,
                        station_record=None,
                        validation_result=None,
                        errors=[f"Unexpected batch worker exception at index {idx}: {str(e)}"],
                        warnings=[],
                    )
                )

        return BatchAdapterResult(
            source_id=self.source_id,
            total_records=len(payloads),
            successful_records=successful_count,
            failed_records=failed_count,
            results=results,
            batch_errors=[],
        )

    def fetch_raw(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Optional network fetch hook for live source polling.
        
        Subclasses may implement this using requests or standard libraries.
        Unit tests should avoid calling fetch_raw and instead use test fixtures.
        """
        raise NotImplementedError(f"fetch_raw not implemented for {self.__class__.__name__}")
