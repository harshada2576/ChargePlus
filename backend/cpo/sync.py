"""ChargePlus — CPO Partner Synchronization.

Pulls partner inventory (OCPI Locations / OICP EVSE data) through the
existing canonical pipeline — validation → resolution → deduplication →
persistence — by delegating to IngestionRunner with an injected scoped
adapter. The sync layer adds only what the runner cannot know:

  - Partner credential gating (fail fast when NOT_CONFIGURED/expired).
  - Protocol-specific pull (versions negotiation, incremental date_from).
  - Partner-scope pre-filtering (unpublished locations, foreign parties).
  - Per-location incremental cursors (out-of-order + resume without re-pull).
  - Consecutive-failure accounting and unexpected-zero-result warnings.
  - Run audit rows under the partner source_id (ocpi:<p>:<env>).

Sync cursors live in a SyncState object (JSON-serializable). Operators persist
it via state_path; without one, state is in-memory (single manual run).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from backend.cpo.ocpi import (
    OcpiLocationsAdapter,
    fetch_version_detail,
    fetch_versions,
    find_module_url,
    pull_locations,
    select_version_url,
)
from backend.cpo.oicp import OicpEvseAdapter, pull_evse_data
from backend.cpo.partners import PartnerConfig, PartnerCredentialError
from backend.ingestion.runner import IngestionRunner

logger = logging.getLogger("chargeplus.cpo.sync")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SyncState:
    """Incremental sync cursors + health for one partner source."""
    source_id: str
    last_sync_at: Optional[str] = None  # ISO-8601 of last completed pull
    last_success_at: Optional[str] = None
    consecutive_failures: int = 0
    last_result_count: int = 0
    # Per-location last_updated cursor: station_id -> ISO timestamp.
    location_cursors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "last_sync_at": self.last_sync_at,
            "last_success_at": self.last_success_at,
            "consecutive_failures": self.consecutive_failures,
            "last_result_count": self.last_result_count,
            "location_cursors": self.location_cursors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyncState":
        return cls(
            source_id=str(data.get("source_id", "unknown")),
            last_sync_at=data.get("last_sync_at"),
            last_success_at=data.get("last_success_at"),
            consecutive_failures=int(data.get("consecutive_failures") or 0),
            last_result_count=int(data.get("last_result_count") or 0),
            location_cursors=dict(data.get("location_cursors") or {}),
        )

    @classmethod
    def load(cls, source_id: str, state_path: Optional[str]) -> "SyncState":
        if not state_path:
            return cls(source_id=source_id)
        path = Path(state_path)
        if not path.is_file():
            return cls(source_id=source_id)
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            logger.warning("Unreadable sync state %s: %s — starting fresh", state_path, exc)
            return cls(source_id=source_id)

    def save(self, state_path: Optional[str]) -> None:
        if not state_path:
            return
        path = Path(state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


@dataclass
class PartnerSyncReport:
    """Outcome of one partner sync run (JSON-serializable, secret-free)."""
    source_id: str
    dry_run: bool
    run_id: Optional[str]
    records_pulled: int = 0
    records_skipped_unpublished: int = 0
    records_skipped_stale_cursor: int = 0
    records_fetched: int = 0
    records_accepted: int = 0
    records_rejected: int = 0
    stations_persisted: int = 0
    stations_updated: int = 0
    observations_persisted: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class PartnerSync:
    """Synchronizes one partner's inventory through the canonical pipeline."""

    def __init__(self, runner: Optional[IngestionRunner] = None) -> None:
        self._runner = runner or IngestionRunner()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync(
        self,
        config: PartnerConfig,
        *,
        dry_run: bool = True,
        limit: int = 1000,
        full: bool = False,
        state_path: Optional[str] = None,
        provider_id: Optional[str] = None,
        send: Optional[Callable] = None,
        timeout_seconds: Optional[float] = None,
    ) -> PartnerSyncReport:
        """Runs one pull → canonical-persist cycle for a partner.

        Args:
            config: partner configuration (credentials from env).
            dry_run: zero database writes when True (default: safe manual runs).
            limit: maximum partner records to process this run.
            full: ignore the incremental cursor and re-pull everything.
            state_path: JSON file for cursor/health persistence (None = memory).
            provider_id: OICP provider identifier (required for oicp).
            send: transport override for the deterministic simulator.
            timeout_seconds: currently informational (pulls use 30s); kept for
                CLI parity with the ingestion runner.
        """
        started = time.time()
        report = PartnerSyncReport(
            source_id=config.source_id, dry_run=dry_run, run_id=str(uuid.uuid4())
        )
        state = SyncState.load(config.source_id, state_path)

        try:
            config.require_usable()
        except PartnerCredentialError as exc:
            report.errors.append(str(exc))
            state.consecutive_failures += 1
            state.save(state_path)
            report.duration_seconds = time.time() - started
            return report

        try:
            if config.protocol == "ocpi":
                payloads = self._pull_ocpi(config, state, report, full, limit, send)
                adapter: Any = OcpiLocationsAdapter(
                    config.partner_name,
                    environment=config.environment,
                    expected_country_code=config.country_code,
                    expected_party_id=config.party_id,
                )
            elif config.protocol == "oicp":
                if not provider_id:
                    raise ValueError(
                        "OICP sync requires provider_id (the eRoaming provider identifier)"
                    )
                payloads = self._pull_oicp(
                    config, state, report, full, limit, provider_id, send
                )
                adapter = OicpEvseAdapter(
                    config.partner_name,
                    environment=config.environment,
                    expected_operator_id=config.party_id or provider_id,
                )
            else:  # pragma: no cover — guarded by PartnerConfig.from_env
                raise ValueError(f"Unsupported protocol {config.protocol!r}")

            report.records_pulled = len(payloads)
            if not payloads:
                if state.last_result_count > 0:
                    report.warnings.append(
                        f"Unexpected zero-result pull (previous run returned "
                        f"{state.last_result_count} records). Check partner status "
                        "before treating this as truth."
                    )
            else:
                if state.last_result_count == 0 and state.last_sync_at is not None:
                    report.warnings.append("Partner returned records after a zero-result run.")

            # Incremental cursor filter: skip records no newer than what this
            # partner already contributed (out-of-order/replay protection).
            # Records without timestamps always flow (validated downstream).
            fresh = self._apply_cursor(payloads, state, report, full)

            summary = self._runner.run(
                dry_run=dry_run,
                limit=max(limit, len(fresh)),
                mumbai_only=False,
                fixtures_data=fresh,
                source=config.source_id,
                adapter=adapter,
                run_id=report.run_id,
            )
            report.records_fetched = summary.records_fetched
            report.records_accepted = (
                summary.records_accepted + summary.records_accepted_with_warnings
            )
            report.records_rejected = summary.records_rejected
            report.stations_persisted = summary.stations_persisted
            report.stations_updated = summary.stations_updated
            report.observations_persisted = summary.observations_persisted

            self._advance_cursors(fresh, state)
            state.last_sync_at = _utcnow().isoformat()
            state.last_success_at = state.last_sync_at
            state.last_result_count = len(payloads)
            state.consecutive_failures = 0
        except Exception as exc:  # fail-closed: state records the failure
            message = str(exc)
            logger.warning("Partner sync %s failed: %s", config.safe_summary()["source_id"], message)
            report.errors.append(message)
            state.consecutive_failures += 1
        finally:
            state.save(state_path)

        report.duration_seconds = time.time() - started
        return report

    # ------------------------------------------------------------------
    # Protocol pulls
    # ------------------------------------------------------------------

    def _pull_ocpi(
        self, config: PartnerConfig, state: SyncState,
        report: PartnerSyncReport, full: bool, limit: int,
        send: Optional[Callable],
    ) -> list[dict[str, Any]]:
        versions = fetch_versions(config, send=send)
        version_url = select_version_url(versions)
        detail = fetch_version_detail(config, version_url, send=send)
        locations_url = find_module_url(detail, "locations")
        date_from: Optional[datetime] = None
        if not full and state.last_sync_at:
            try:
                date_from = datetime.fromisoformat(state.last_sync_at)
            except ValueError:
                date_from = None
        locations, meta = pull_locations(
            config, locations_url, date_from=date_from,
            max_records=limit, send=send,
        )
        logger.info(
            "OCPI pull %s: %d locations (%s)",
            config.source_id, len(locations), meta,
        )
        # Partner-scope pre-filter: unpublished locations are the partner's
        # "not for public use" set — skipped with a count, never ingested.
        # (The adapter also refuses them as defense-in-depth.)
        fresh: list[dict[str, Any]] = []
        for loc in locations:
            if isinstance(loc, dict) and loc.get("publish") is False:
                report.records_skipped_unpublished += 1
                continue
            fresh.append(loc)
        return fresh

    def _pull_oicp(
        self, config: PartnerConfig, state: SyncState,
        report: PartnerSyncReport, full: bool, limit: int,
        provider_id: str, send: Optional[Callable],
    ) -> list[dict[str, Any]]:
        last_update: Optional[datetime] = None
        if not full and state.last_sync_at:
            try:
                last_update = datetime.fromisoformat(state.last_sync_at)
            except ValueError:
                last_update = None
        records = pull_evse_data(
            config, provider_id, last_update=last_update, send=send
        )
        return records[:limit]

    # ------------------------------------------------------------------
    # Cursor helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_timestamp(payload: Any) -> Optional[datetime]:
        """Newest source timestamp on a pulled record (None when absent)."""
        candidates: list[str] = []
        if isinstance(payload, dict):
            for key in ("last_updated", "last_update"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    candidates.append(value)
            evses = payload.get("evses")
            if isinstance(evses, list):
                for evse in evses:
                    if isinstance(evse, dict) and isinstance(evse.get("last_updated"), str):
                        candidates.append(evse["last_updated"])
        newest: Optional[datetime] = None
        for raw in candidates:
            try:
                ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if newest is None or ts > newest:
                newest = ts
        return newest

    def _apply_cursor(
        self, payloads: list[dict[str, Any]], state: SyncState,
        report: PartnerSyncReport, full: bool,
    ) -> list[dict[str, Any]]:
        if full:
            return payloads
        fresh: list[dict[str, Any]] = []
        for payload in payloads:
            key = self._cursor_key(payload)
            ts = self._record_timestamp(payload)
            cursor_raw = state.location_cursors.get(key) if key else None
            if key and ts is not None and cursor_raw:
                try:
                    cursor = datetime.fromisoformat(cursor_raw)
                except ValueError:
                    cursor = None
                if cursor is not None and ts <= cursor:
                    report.records_skipped_stale_cursor += 1
                    continue
            fresh.append(payload)
        return fresh

    @staticmethod
    def _cursor_key(payload: Any) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        if payload.get("id") and payload.get("party_id"):
            return f"{payload.get('country_code')}/{payload.get('party_id')}/{payload.get('id')}"
        if payload.get("evse_id"):
            return f"oicp/{payload.get('operator_id')}/{payload.get('evse_id')}"
        return None

    def _advance_cursors(
        self, payloads: list[dict[str, Any]], state: SyncState
    ) -> None:
        for payload in payloads:
            key = self._cursor_key(payload)
            ts = self._record_timestamp(payload)
            if key and ts is not None:
                state.location_cursors[key] = ts.isoformat()
