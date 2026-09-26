"""ChargePlus — Scheduled Ingestion Workflows, Polling Daemons & Retry Policies.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.10 (Scheduled Ingestion Workflows, Polling Daemons & Retry Policies)

Authoritative orchestration layer for recurring, scheduled, and manual EV data ingestion.
Coordinates:
- Run lifecycle state management (STARTED, RUNNING, SUCCEEDED, PARTIAL, FAILED, CANCELLED)
- Explicit retry classification (TRANSIENT vs PERMANENT)
- Bounded exponential backoff with configurable jitter and Retry-After support
- Concurrency protection via PostgreSQL session-level advisory locks
- Granular operational run accounting and metric tracking
- Safe exception sanitization (scrubbing database URLs, API keys, and authorization headers)
- Single canonical pipeline reuse: Step 2.10 controls WHEN and HOW OFTEN, never WHAT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
import os
import random
import re
import signal
import struct
import sys
import threading
import time
from typing import Any, Callable, Optional, Sequence

from backend.ingestion.persistence import IngestionPersistenceService, _scrub_secrets

logger = logging.getLogger("chargeplus.ingestion.scheduling")


# ==============================================================================
# 1. Run State & Failure Classification Enums
# ==============================================================================

class IngestionRunState(str, Enum):
    """Authoritative lifecycle states for an ingestion run."""
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FailureClassification(str, Enum):
    """Categorization of pipeline errors for retry policy decisions."""
    TRANSIENT = "TRANSIENT"      # Temporary network/server glitch; safe and appropriate to retry
    PERMANENT = "PERMANENT"      # Deterministic contract/auth/logic error; retry will never succeed
    UNKNOWN = "UNKNOWN"          # Unclassified error; treated conservatively as PERMANENT


# ==============================================================================
# 2. Concurrency Exception
# ==============================================================================

class ConcurrentRunError(RuntimeError):
    """Raised when an ingestion run is denied acquisition of the source lock."""
    pass


# ==============================================================================
# 3. Retry Policy
# ==============================================================================

@dataclass
class RetryPolicy:
    """Configurable, bounded retry policy with exponential backoff and jitter."""
    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    multiplier: float = 2.0
    max_delay_seconds: float = 30.0
    jitter: bool = True
    retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)

    def __post_init__(self) -> None:
        """Validates configuration bounds."""
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {self.max_attempts}")
        if self.initial_delay_seconds < 0:
            raise ValueError(f"initial_delay_seconds must be >= 0, got {self.initial_delay_seconds}")
        if self.multiplier < 1.0:
            raise ValueError(f"multiplier must be >= 1.0, got {self.multiplier}")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError(f"max_delay_seconds ({self.max_delay_seconds}) cannot be less than initial_delay_seconds ({self.initial_delay_seconds})")

    def classify_exception(self, exc: Exception) -> FailureClassification:
        """Determines whether an exception is transient (retryable) or permanent."""
        if exc is None:
            return FailureClassification.UNKNOWN

        # 1. Non-retryable / Permanent exceptions
        if isinstance(exc, (PermissionError, ValueError, KeyError, TypeError, json.JSONDecodeError)):
            return FailureClassification.PERMANENT

        # Check for authentication / permission keywords in message
        msg_lower = str(exc).lower()
        if any(term in msg_lower for term in ("unauthorized", "authentication failed", "forbidden", "invalid api key", "missing api key")):
            return FailureClassification.PERMANENT

        # 2. HTTP Status Code Checks
        status_code: Optional[int] = None
        if hasattr(exc, "response") and getattr(exc, "response") is not None:
            status_code = getattr(getattr(exc, "response"), "status_code", None)
        elif hasattr(exc, "status_code"):
            status_code = getattr(exc, "status_code", None)

        if status_code is not None:
            if status_code in self.retryable_status_codes:
                return FailureClassification.TRANSIENT
            if 400 <= status_code < 500:
                # 4xx client errors (400, 401, 403, 404, 422) are permanent
                return FailureClassification.PERMANENT
            if status_code >= 500:
                return FailureClassification.TRANSIENT

        # Check for explicit HTTP error numbers in message
        if "429" in msg_lower or "rate limit" in msg_lower:
            return FailureClassification.TRANSIENT
        if any(f"http {code}" in msg_lower or f"status {code}" in msg_lower for code in (500, 502, 503, 504)):
            return FailureClassification.TRANSIENT
        if any(f"http {code}" in msg_lower or f"status {code}" in msg_lower for code in (400, 401, 403, 404)):
            return FailureClassification.PERMANENT

        # 3. Network & Connection Timeouts (Transient)
        exc_type_name = type(exc).__name__
        if isinstance(exc, (TimeoutError, ConnectionError, ConnectionResetError)):
            return FailureClassification.TRANSIENT
        if "Timeout" in exc_type_name or "ConnectionError" in exc_type_name or "ConnectionReset" in exc_type_name:
            return FailureClassification.TRANSIENT

        # 4. Database Connectivity Glitches (Transient)
        if "OperationalError" in exc_type_name or "could not connect" in msg_lower or "connection closed" in msg_lower:
            return FailureClassification.TRANSIENT

        # 5. Database Constraints / Integrity Violations (Permanent)
        if "IntegrityError" in exc_type_name or "ProgrammingError" in exc_type_name:
            return FailureClassification.PERMANENT

        # Default fallback
        return FailureClassification.UNKNOWN

    def compute_delay(
        self,
        attempt: int,
        retry_after: Optional[float] = None,
        random_fn: Optional[Callable[[], float]] = None,
    ) -> float:
        """Computes bounded exponential backoff delay with jitter.
        
        Args:
            attempt: The current attempt number (1-indexed).
            retry_after: Explicit delay specified by upstream Retry-After header.
            random_fn: Optional custom uniform [0, 1) random generator for deterministic testing.
        """
        # Bounded exponential calculation: initial * (multiplier ^ (attempt - 1))
        exponent = max(0, attempt - 1)
        base_delay = min(self.max_delay_seconds, self.initial_delay_seconds * (self.multiplier ** exponent))

        # Respect upstream Retry-After if provided
        if retry_after is not None and retry_after > 0:
            delay = max(base_delay, retry_after)
        elif self.jitter and base_delay > 0:
            # Jitter variation within [0.8, 1.2] * base_delay
            rng = random_fn() if random_fn else random.random()
            jitter_scale = 0.8 + 0.4 * rng
            delay = base_delay * jitter_scale
        else:
            delay = base_delay

        return round(min(self.max_delay_seconds, max(0.0, delay)), 3)


# ==============================================================================
# 4. Schedule Configuration
# ==============================================================================

@dataclass
class ScheduleConfig:
    """Configuration contract for a scheduled or recurring ingestion feed."""
    source_id: str
    enabled: bool = True
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = None
    limit: int = 50
    scope: str = "mumbai"
    bounding_box: Optional[tuple[float, float, float, float]] = None
    timeout_seconds: float = 30.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    dry_run: bool = False

    def __post_init__(self) -> None:
        """Validates configuration sanity."""
        if not self.source_id or not self.source_id.strip():
            raise ValueError("source_id cannot be empty")
        if self.limit < 1:
            raise ValueError(f"limit must be >= 1, got {self.limit}")
        if self.timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be > 0, got {self.timeout_seconds}")
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise ValueError(f"interval_seconds must be > 0, got {self.interval_seconds}")


# ==============================================================================
# 5. Ingestion Run Accounting
# ==============================================================================

@dataclass
class IngestionRun:
    """Authoritative operational record and accounting of an ingestion run."""
    run_id: str
    source_id: str
    source_name: str
    scope: str
    state: IngestionRunState = IngestionRunState.STARTED
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    attempt_count: int = 0
    records_fetched: int = 0
    records_parsed: int = 0
    records_accepted: int = 0
    records_accepted_with_warnings: int = 0
    records_quarantined: int = 0
    records_rejected: int = 0
    stations_persisted: int = 0
    stations_updated: int = 0
    stations_unchanged: int = 0
    connectors_persisted: int = 0
    observations_persisted: int = 0
    persistence_errors: list[str] = field(default_factory=list)
    error_summary: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Converts run record to a JSON-serializable dictionary."""
        return {
            "run_id": self.run_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "scope": self.scope,
            "state": self.state.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": round(self.duration_seconds, 2),
            "attempt_count": self.attempt_count,
            "records_fetched": self.records_fetched,
            "records_parsed": self.records_parsed,
            "records_accepted": self.records_accepted,
            "records_accepted_with_warnings": self.records_accepted_with_warnings,
            "records_quarantined": self.records_quarantined,
            "records_rejected": self.records_rejected,
            "stations_persisted": self.stations_persisted,
            "stations_updated": self.stations_updated,
            "stations_unchanged": self.stations_unchanged,
            "connectors_persisted": self.connectors_persisted,
            "observations_persisted": self.observations_persisted,
            "persistence_errors_count": len(self.persistence_errors),
            "error_summary": self.error_summary,
            "metadata": self.metadata,
        }


# ==============================================================================
# 6. Concurrency Protection (PostgreSQL Advisory Locks + In-Memory Fallback)
# ==============================================================================

# Global in-memory lock registry for dry-runs, tests, and offline execution
_LOCAL_LOCK_REGISTRY: set[str] = set()
_LOCAL_LOCK_MUTEX = threading.Lock()


class IngestionConcurrencyLock:
    """Manages mutual exclusion for source ingestion runs to prevent race conditions.
    
    Prefers PostgreSQL session-level advisory locks (`pg_try_advisory_lock`), which
    automatically release if the process crashes or disconnects.
    Falls back to a thread-safe in-memory registry when running offline or in mock modes.
    """

    def __init__(
        self,
        source_id: str,
        scope: str = "default",
        db_url: Optional[str] = None,
        persistence_service: Optional[IngestionPersistenceService] = None,
    ):
        self.source_id = source_id
        self.scope = scope
        self.db_url = db_url
        self.persistence_service = persistence_service
        self.lock_key = f"{source_id}:{scope}"
        self._numeric_key = self._generate_numeric_lock_key(self.lock_key)
        self._acquired = False
        self._conn: Any = None

    @staticmethod
    def _generate_numeric_lock_key(key_str: str) -> int:
        """Derives a stable signed 64-bit integer from a string for PostgreSQL advisory locks."""
        digest = hashlib.sha256(key_str.encode("utf-8")).digest()
        # Unpack first 8 bytes as signed 64-bit integer
        return struct.unpack(">q", digest[:8])[0]

    def acquire(self) -> bool:
        """Attempts to acquire the lock. Returns True if acquired, False otherwise."""
        if self._acquired:
            return True

        # 1. Attempt PostgreSQL advisory lock if connection available
        conn = self._get_connection()
        if conn is not None:
            try:
                cur = conn.cursor()
                cur.execute("SELECT pg_try_advisory_lock(%s);", (self._numeric_key,))
                row = cur.fetchone()
                cur.close()
                if row and row[0] is True:
                    self._acquired = True
                    logger.debug("Acquired PostgreSQL advisory lock for '%s' (key=%d)", self.lock_key, self._numeric_key)
                    return True
                else:
                    logger.warning("PostgreSQL advisory lock busy for '%s' (key=%d)", self.lock_key, self._numeric_key)
                    return False
            except Exception as ex:
                logger.warning("Failed executing pg_try_advisory_lock for '%s': %s. Falling back to local lock.", self.lock_key, ex)

        # 2. Fallback to in-memory lock
        with _LOCAL_LOCK_MUTEX:
            if self.lock_key in _LOCAL_LOCK_REGISTRY:
                logger.warning("Local concurrency lock busy for '%s'", self.lock_key)
                return False
            _LOCAL_LOCK_REGISTRY.add(self.lock_key)
            self._acquired = True
            logger.debug("Acquired local concurrency lock for '%s'", self.lock_key)
            return True

    def release(self) -> bool:
        """Releases the lock if held. Returns True if successfully released."""
        if not self._acquired:
            return False

        success = True
        conn = self._get_connection()
        if conn is not None:
            try:
                cur = conn.cursor()
                cur.execute("SELECT pg_advisory_unlock(%s);", (self._numeric_key,))
                cur.close()
                logger.debug("Released PostgreSQL advisory lock for '%s'", self.lock_key)
            except Exception as ex:
                logger.warning("Error releasing PostgreSQL advisory lock for '%s': %s", self.lock_key, ex)
                success = False

        with _LOCAL_LOCK_MUTEX:
            _LOCAL_LOCK_REGISTRY.discard(self.lock_key)
            logger.debug("Released local concurrency lock for '%s'", self.lock_key)

        self._acquired = False
        return success

    def _get_connection(self) -> Any:
        """Resolves active database connection if available."""
        if self._conn is not None:
            return self._conn
        if self.persistence_service and self.persistence_service.conn:
            return self.persistence_service.conn
        return None

    def __enter__(self) -> IngestionConcurrencyLock:
        if not self.acquire():
            raise ConcurrentRunError(
                f"Ingestion run for '{self.source_id}:{self.scope}' is already in progress. Skipping overlapping run."
            )
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


# ==============================================================================
# 7. Scheduled Ingestion Orchestrator
# ==============================================================================

class ScheduledIngestionOrchestrator:
    """Authoritative orchestrator for running scheduled, repeated, or manual ingestion workflows.
    
    Coordinates the single canonical ingestion pipeline:
    - Lock acquisition (prevents overlapping execution for same source/scope)
    - Retry management with exponential backoff and jitter
    - Accurate run metric aggregation
    - Operational database persistence into public.ingestion_runs
    """

    def __init__(
        self,
        runner: Any,
        persistence_service: Optional[IngestionPersistenceService] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ):
        self.runner = runner
        self.persistence_service = persistence_service or getattr(runner, "persistence_service", None)
        self._sleep_fn = sleep_fn or time.sleep

    def execute_scheduled_run(
        self,
        config: ScheduleConfig,
        fixtures_data: Optional[list[dict[str, Any]]] = None,
        run_id_override: Optional[str] = None,
    ) -> IngestionRun:
        """Executes a single scheduled ingestion run honoring concurrency and retry policies.
        
        Args:
            config: Operational schedule configuration.
            fixtures_data: Optional in-memory test fixture payloads.
            run_id_override: Optional explicit UUID for deterministic testing.
        """
        import uuid

        run_id = run_id_override or str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        start_mono = time.time()

        run = IngestionRun(
            run_id=run_id,
            source_id=config.source_id,
            source_name=config.source_id,
            scope=config.scope,
            state=IngestionRunState.STARTED,
            started_at=started_at,
            metadata={
                "dry_run": config.dry_run,
                "limit": config.limit,
                "timeout_seconds": config.timeout_seconds,
            },
        )

        # 1. Configuration Guard: Disabled Source
        if not config.enabled:
            logger.info("ScheduleConfig for '%s' is disabled. Skipping execution.", config.source_id)
            run.state = IngestionRunState.CANCELLED
            run.completed_at = datetime.now(timezone.utc)
            run.duration_seconds = time.time() - start_mono
            run.error_summary = "Skipped: source feed is disabled in schedule configuration."
            return run

        # 2. Concurrency Protection
        lock = IngestionConcurrencyLock(
            source_id=config.source_id,
            scope=config.scope,
            db_url=getattr(self.runner, "db_url", None),
            persistence_service=self.persistence_service,
        )

        acquired = lock.acquire()
        if not acquired:
            logger.warning(
                "Concurrent ingestion detected for source '%s' (scope '%s'). Denying run '%s'.",
                config.source_id,
                config.scope,
                run.run_id,
            )
            run.state = IngestionRunState.CANCELLED
            run.completed_at = datetime.now(timezone.utc)
            run.duration_seconds = time.time() - start_mono
            run.error_summary = f"Skipped: concurrent ingestion run already active for '{config.source_id}:{config.scope}'."
            return run

        try:
            run.state = IngestionRunState.RUNNING
            retry_policy = config.retry_policy
            mumbai_only = (config.scope.lower() == "mumbai")

            # 3. Execution Retry Loop
            for attempt in range(1, retry_policy.max_attempts + 1):
                run.attempt_count = attempt
                logger.info(
                    "Executing ingestion run '%s' for '%s' (Attempt %d/%d)",
                    run.run_id,
                    config.source_id,
                    attempt,
                    retry_policy.max_attempts,
                )

                try:
                    # Invoke the canonical runner pipeline
                    summary = self.runner.run(
                        dry_run=config.dry_run,
                        limit=config.limit,
                        mumbai_only=mumbai_only,
                        bounding_box=config.bounding_box,
                        fixtures_data=fixtures_data,
                    )

                    # Transfer accounting metrics
                    run.records_fetched = summary.records_fetched
                    run.records_parsed = summary.records_parsed
                    run.records_accepted = summary.records_accepted
                    run.records_accepted_with_warnings = summary.records_accepted_with_warnings
                    run.records_quarantined = summary.records_quarantined
                    run.records_rejected = summary.records_rejected
                    run.stations_persisted = summary.stations_persisted
                    run.stations_updated = summary.stations_updated
                    run.stations_unchanged = summary.stations_unchanged
                    run.connectors_persisted = summary.connectors_persisted
                    run.observations_persisted = summary.observations_persisted
                    run.persistence_errors = list(summary.persistence_errors)

                    # Assess overall completion state
                    if run.records_rejected > 0 or len(run.persistence_errors) > 0 or run.records_quarantined > 0:
                        run.state = IngestionRunState.PARTIAL
                        if run.persistence_errors:
                            run.error_summary = _scrub_secrets("; ".join(run.persistence_errors[:3]))
                    else:
                        run.state = IngestionRunState.SUCCEEDED

                    logger.info(
                        "Ingestion run '%s' completed with state: %s (Fetched: %d, Persisted: %d)",
                        run.run_id,
                        run.state.value,
                        run.records_fetched,
                        run.stations_persisted,
                    )
                    break

                except Exception as ex:
                    classification = retry_policy.classify_exception(ex)
                    sanitized_msg = _scrub_secrets(str(ex))
                    logger.warning(
                        "Ingestion run '%s' attempt %d failed [%s]: %s",
                        run.run_id,
                        attempt,
                        classification.value,
                        sanitized_msg,
                    )

                    if classification == FailureClassification.TRANSIENT and attempt < retry_policy.max_attempts:
                        # Extract Retry-After if available
                        retry_after = self._extract_retry_after(ex)
                        delay = retry_policy.compute_delay(attempt, retry_after=retry_after)
                        logger.info("Retrying run '%s' in %.2f seconds (attempt %d)...", run.run_id, delay, attempt + 1)
                        self._sleep_fn(delay)
                    else:
                        # Non-retryable or max attempts exhausted
                        run.state = IngestionRunState.FAILED
                        run.error_summary = sanitized_msg
                        break

        finally:
            lock.release()
            run.completed_at = datetime.now(timezone.utc)
            run.duration_seconds = time.time() - start_mono

            # Persist run accounting to database if applicable
            self._persist_run_accounting(run, dry_run=config.dry_run)

        return run

    @staticmethod
    def _extract_retry_after(exc: Exception) -> Optional[float]:
        """Extracts seconds from Retry-After header if present on HTTP exception."""
        if hasattr(exc, "response") and getattr(exc, "response") is not None:
            resp = getattr(exc, "response")
            headers = getattr(resp, "headers", {})
            header_val = headers.get("Retry-After") or headers.get("retry-after")
            if header_val:
                try:
                    return float(header_val)
                except ValueError:
                    return None
        return None

    def _persist_run_accounting(self, run: IngestionRun, dry_run: bool = False) -> None:
        """Persists the IngestionRun record to public.ingestion_runs table."""
        if dry_run:
            logger.debug("Dry run active: Skipping database persistence for ingestion run '%s'", run.run_id)
            return

        service = self.persistence_service or getattr(self.runner, "persistence_service", None)
        if not service:
            return

        try:
            service.persist_ingestion_run(run)
        except Exception as ex:
            logger.error("Failed persisting ingestion run accounting to database: %s", _scrub_secrets(str(ex)))


# ==============================================================================
# 8. Polling Daemon (For Containerized / Background Execution)
# ==============================================================================

class PollingDaemon:
    """Recurring polling daemon that manages periodic execution of configured schedules.
    
    Designed to run gracefully in containerized environments (Kubernetes/Docker/systemd)
    with clean handling of SIGINT and SIGTERM signals.
    """

    def __init__(
        self,
        orchestrator: ScheduledIngestionOrchestrator,
        schedules: Sequence[ScheduleConfig],
        sleep_fn: Optional[Callable[[float], None]] = None,
    ):
        self.orchestrator = orchestrator
        self.schedules = list(schedules)
        self._sleep_fn = sleep_fn or time.sleep
        self._stop_requested = threading.Event()

    def request_stop(self, *args: Any) -> None:
        """Signals the daemon to shut down gracefully after current flight completes."""
        logger.info("Shutdown requested for PollingDaemon. Completing in-flight jobs...")
        self._stop_requested.set()

    def start(self, run_once: bool = False) -> list[IngestionRun]:
        """Starts daemon execution.
        
        Args:
            run_once: If True, executes each schedule once and exits (cron style).
        """
        # Register signal handlers if running on main thread
        try:
            signal.signal(signal.SIGINT, self.request_stop)
            signal.signal(signal.SIGTERM, self.request_stop)
        except (ValueError, AttributeError):
            # Not in main thread (e.g. testing)
            pass

        runs: list[IngestionRun] = []
        logger.info("Starting PollingDaemon with %d configured schedule(s) (run_once=%s)", len(self.schedules), run_once)

        while not self._stop_requested.is_set():
            for schedule in self.schedules:
                if self._stop_requested.is_set():
                    break
                if not schedule.enabled:
                    continue

                try:
                    run = self.orchestrator.execute_scheduled_run(schedule)
                    runs.append(run)
                except Exception as ex:
                    logger.error("Unhandled exception in schedule loop for '%s': %s", schedule.source_id, _scrub_secrets(str(ex)))

            if run_once or self._stop_requested.is_set():
                break

            # Find minimum sleep interval among active schedules (default 300s)
            intervals = [s.interval_seconds for s in self.schedules if s.enabled and s.interval_seconds]
            sleep_sec = min(intervals) if intervals else 300
            logger.info("Daemon sleeping for %d seconds until next polling cycle...", sleep_sec)

            # Sleep in small slices to respond promptly to stop requests
            slice_time = 0.5
            elapsed = 0.0
            while elapsed < sleep_sec and not self._stop_requested.is_set():
                self._sleep_fn(min(slice_time, sleep_sec - elapsed))
                elapsed += slice_time

        logger.info("PollingDaemon terminated cleanly.")
        return runs
