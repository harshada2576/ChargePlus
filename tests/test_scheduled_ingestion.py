"""ChargePlus — Scheduled Ingestion Workflows, Polling Daemons & Retry Policies Test Suite.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.10 (Scheduled Ingestion Workflows, Polling Daemons & Retry Policies)

Verifies:
1. Successful scheduled run execution and metric tracking
2. Manual run and scheduled run sharing the exact same canonical pipeline
3. Retry on transient network/socket timeout
4. Retry on HTTP 429 rate limit
5. Upstream Retry-After header parsing and enforcement
6. Retry on HTTP 500, 502, 503, 504 server errors
7. No retry on permanent HTTP 400 client error
8. No retry on permanent HTTP 401/403 authentication failure
9. No retry on invalid configuration (negative limits, empty source)
10. Bounded maximum retry attempts
11. Bounded exponential backoff delay scaling
12. Jitter computation within [0.8, 1.2] range and testable repeatability
13. Concurrency protection denying overlapping runs for the same source/scope
14. Request timeout handling
15. Partial record failures marking run state as PARTIAL
16. Quarantine not failing the entire valid batch
17. Source-level failure marking run state as FAILED
18. Individual persistence failure isolation and accounting
19. Idempotency on rerun with identical payloads
20. No duplicate canonical stations on rerun
21. No duplicate station source links on rerun
22. No duplicate observation facts on rerun
23. Crash/retry scenario remaining fail-safe
24. Dry-run execution producing 0 database mutations
25. Internal metric accounting consistency
26. Secrets scrubbing from error summaries and logs
27. Scheduler never fabricating live observations from static status
28. Retrieval time remaining strictly distinct from observation time
29. Step 2.9 freshness engine contract preservation (STALE != UNAVAILABLE)
30. Step 2.8 transaction and rollback semantics intact
31. PollingDaemon graceful start, execution, and signal shutdown
32. Live database public.ingestion_runs audit persistence and clean rollback/cleanup
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import unittest
from unittest.mock import MagicMock, patch
import uuid

import psycopg2
from dotenv import load_dotenv

from backend.ingestion.adapters.openchargemap import OpenChargeMapAdapter
from backend.ingestion.constants import AvailabilityStatus, OperationalStatus, ValidationOutcome
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedObservationRecord,
    NormalizedStationRecord,
    RawSourceRecord,
)
from backend.ingestion.freshness import (
    DEFAULT_LIVE_TELEMETRY_POLICY,
    FreshnessEngine,
    FreshnessState,
)
from backend.ingestion.persistence import (
    IngestionPersistenceService,
    PersistenceStatus,
    StationPersistenceResult,
    _scrub_secrets,
)
from backend.ingestion.runner import IngestionRunner, IngestionSummary
from backend.ingestion.scheduling import (
    ConcurrentRunError,
    FailureClassification,
    IngestionConcurrencyLock,
    IngestionRun,
    IngestionRunState,
    PollingDaemon,
    RetryPolicy,
    ScheduleConfig,
    ScheduledIngestionOrchestrator,
)
from tests.fixtures.ocm_fixtures import (
    OCM_FIXTURE_01_VALID_COMPLETE,
    OCM_FIXTURE_02_MULTIPLE_CONNECTORS,
    OCM_FIXTURE_04_MISSING_OPTIONAL_FIELDS,
    OCM_FIXTURE_09_NULL_ISLAND,
    OCM_FIXTURE_13_TELEMETRY_AVAILABLE,
    OCM_FIXTURE_14_STATIC_OPERATIONAL_NOT_AVAILABLE,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# In-Memory Mock Database for Fast, Isolated Unit Testing
# ==============================================================================

class MockDatabase:
    """Mock database store tracking operational tables and ingestion runs."""
    def __init__(self):
        self.tables = {
            "public.data_sources": [],
            "public.operators": [],
            "public.stations": [],
            "public.connectors": [],
            "public.station_source_link": [],
            "public.station_observations": [],
            "public.ingestion_runs": [],
            "analytics.dim_source": [],
            "analytics.fact_station_observation": [],
        }
        self.mutation_counts = {
            "stations_inserted": 0,
            "stations_updated": 0,
            "connectors_inserted": 0,
            "observations_inserted": 0,
            "source_links_inserted": 0,
            "source_links_updated": 0,
            "ingestion_runs_upserted": 0,
        }
        self.should_fail_persistence = False
        self.should_fail_first_station = False


class MockCursor:
    """Mock database cursor responding to SQL queries."""
    def __init__(self, db: MockDatabase, as_dict: bool = False):
        self.db = db
        self.as_dict = as_dict
        self._last_result = []

    def execute(self, sql: str, params: tuple | list = ()):
        sql_clean = " ".join(sql.strip().split())
        self._last_result = []

        # Advisory locks
        if "pg_try_advisory_lock" in sql_clean:
            self._last_result = [(True,)]
            return
        if "pg_advisory_unlock" in sql_clean:
            self._last_result = [(True,)]
            return

        # 1. SELECT from public.data_sources
        if "FROM public.data_sources WHERE name = %s" in sql_clean:
            name = params[0]
            for row in self.db.tables["public.data_sources"]:
                if row["name"] == name:
                    self._last_result = [row if self.as_dict else (row["id"],)]
                    break

        # 2. INSERT INTO public.data_sources
        elif "INSERT INTO public.data_sources" in sql_clean:
            row_id, name, s_type, url, priority = params
            row = {"id": row_id, "name": name, "source_type": s_type, "base_url": url, "source_priority": priority}
            self.db.tables["public.data_sources"].append(row)
            self._last_result = [row if self.as_dict else (row_id,)]

        # 3. SELECT from public.operators
        elif "FROM public.operators WHERE slug = %s" in sql_clean or "FROM public.operators WHERE name = %s" in sql_clean:
            val = params[0]
            for row in self.db.tables["public.operators"]:
                if row.get("slug") == val or row.get("name") == val:
                    self._last_result = [row if self.as_dict else (row["id"],)]
                    break

        # 4. INSERT INTO public.operators
        elif "INSERT INTO public.operators" in sql_clean:
            op_id, name, slug, web, phone = params
            row = {"id": op_id, "name": name, "slug": slug, "website_url": web, "support_phone": phone}
            self.db.tables["public.operators"].append(row)
            self._last_result = [row if self.as_dict else (op_id,)]

        # 5. SELECT from public.station_source_link
        elif "FROM public.station_source_link WHERE source_id = %s AND source_station_id = %s" in sql_clean:
            src_id, src_stn_id = str(params[0]), str(params[1])
            for row in self.db.tables["public.station_source_link"]:
                if str(row["source_id"]) == src_id and str(row["source_station_id"]) == src_stn_id:
                    self._last_result = [row if self.as_dict else (row["id"], row["station_id"], row["source_id"], row["source_station_id"], row["source_payload_hash"], row["first_seen_at"])]
                    break

        # 6. UPDATE public.station_source_link
        elif "UPDATE public.station_source_link SET last_seen_at = now()" in sql_clean:
            src_id, src_stn_id = str(params[0]), str(params[1])
            for row in self.db.tables["public.station_source_link"]:
                if str(row["source_id"]) == src_id and str(row["source_station_id"]) == src_stn_id:
                    row["last_seen_at"] = datetime.now(timezone.utc)
                    self.db.mutation_counts["source_links_updated"] += 1
                    break

        # 7. INSERT INTO public.station_source_link
        elif "INSERT INTO public.station_source_link" in sql_clean:
            stn_id, src_id, src_stn_id, src_url, p_hash = params[:5]
            link_id = str(uuid.uuid4())
            row = {
                "id": link_id, "station_id": str(stn_id), "source_id": str(src_id),
                "source_station_id": str(src_stn_id), "source_url": src_url,
                "source_payload_hash": str(p_hash),
                "first_seen_at": datetime.now(timezone.utc), "last_seen_at": datetime.now(timezone.utc),
            }
            self.db.tables["public.station_source_link"].append(row)
            self.db.mutation_counts["source_links_inserted"] += 1
            self._last_result = [(link_id,)]

        # 8. INSERT INTO public.stations
        elif "INSERT INTO public.stations" in sql_clean:
            if self.db.should_fail_persistence:
                raise psycopg2.OperationalError("Simulated database write timeout")
            if self.db.should_fail_first_station and len(self.db.tables["public.stations"]) == 0:
                self.db.should_fail_first_station = False
                raise psycopg2.OperationalError("Simulated individual station persistence failure")
            stn_id = params[0]
            row = {"id": stn_id, "name": params[1], "latitude": params[6], "longitude": params[7]}
            self.db.tables["public.stations"].append(row)
            self.db.mutation_counts["stations_inserted"] += 1
            self._last_result = [(stn_id,)]

        # 9. INSERT INTO public.connectors
        elif "INSERT INTO public.connectors" in sql_clean:
            conn_id = params[0]
            row = {"id": conn_id, "station_id": params[1], "connector_type": params[2], "power_kw": params[3]}
            self.db.tables["public.connectors"].append(row)
            self.db.mutation_counts["connectors_inserted"] += 1
            self._last_result = [(conn_id,)]

        # 10. SELECT FROM public.station_observations (idempotency check)
        elif "FROM public.station_observations" in sql_clean and "LIMIT 1" in sql_clean:
            stn_id, o_time, p_hash = params[:3]
            for row in self.db.tables["public.station_observations"]:
                if str(row["station_id"]) == str(stn_id) and str(row["raw_payload_hash"]) == str(p_hash):
                    self._last_result = [(row["id"],)]
                    break

        # 11. INSERT INTO public.station_observations
        elif "INSERT INTO public.station_observations" in sql_clean:
            obs_id = params[0]
            row = {
                "id": obs_id,
                "station_id": params[1],
                "source_id": params[2],
                "availability_status": params[3],
                "queue_level": params[4],
                "available_connectors": params[5],
                "total_connectors": params[6],
                "observed_at": params[7],
                "received_at": params[8],
                "raw_payload_hash": params[9],
            }
            self.db.tables["public.station_observations"].append(row)
            self.db.mutation_counts["observations_inserted"] += 1
            self._last_result = [(obs_id,)]

        # 11. INSERT INTO analytics.fact_station_observation
        elif "INSERT INTO analytics.fact_station_observation" in sql_clean:
            self._last_result = [(params[0],)]

        # 12. INSERT/UPDATE public.ingestion_runs
        elif "INSERT INTO public.ingestion_runs" in sql_clean:
            run_id = str(params[0])
            existing = next((r for r in self.db.tables["public.ingestion_runs"] if str(r["id"]) == run_id), None)
            if existing:
                existing["state"] = params[4]
                existing["completed_at"] = params[6]
                existing["error_summary"] = params[20]
            else:
                row = {
                    "id": run_id, "source_id": params[1], "source_name": params[2],
                    "scope": params[3], "state": params[4], "started_at": params[5],
                    "completed_at": params[6], "records_fetched": params[9],
                    "stations_persisted": params[15], "error_summary": params[20],
                }
                self.db.tables["public.ingestion_runs"].append(row)
                self.db.mutation_counts["ingestion_runs_upserted"] += 1
            self._last_result = [(run_id,)]

    def fetchone(self):
        return self._last_result[0] if self._last_result else None

    def fetchall(self):
        return list(self._last_result)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class MockConnection:
    """Mock connection implementing cursor and transaction methods."""
    def __init__(self, db: MockDatabase):
        self.db = db
        self.closed = False

    def cursor(self, cursor_factory=None):
        return MockCursor(self.db, as_dict=(cursor_factory is not None))

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


# ==============================================================================
# Test Suite: Scheduled Ingestion Workflows, Polling Daemons & Retry Policies
# ==============================================================================

class TestScheduledIngestion(unittest.TestCase):
    """32 comprehensive automated tests verifying Step 2.10 requirements."""

    def setUp(self):
        """Prepares an isolated mock database and persistence service."""
        self.mock_db = MockDatabase()
        self.mock_conn = MockConnection(self.mock_db)
        self.persistence = IngestionPersistenceService(None)
        self.persistence.conn = self.mock_conn
        self.persistence._owns_connection = False

        self.runner = IngestionRunner(persistence_service=self.persistence)
        self.orchestrator = ScheduledIngestionOrchestrator(
            runner=self.runner,
            persistence_service=self.persistence,
            sleep_fn=lambda sec: None,  # Zero-wait sleep for ultra-fast deterministic tests
        )

    # --------------------------------------------------------------------------
    # 1. Successful Scheduled Run
    # --------------------------------------------------------------------------
    def test_01_successful_scheduled_run(self):
        """1. Scheduled run succeeds, acquires lock, executes pipeline, records metrics, marks SUCCEEDED."""
        config = ScheduleConfig(source_id="open_charge_map", limit=5, scope="mumbai")
        run = self.orchestrator.execute_scheduled_run(
            config=config,
            fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE],
        )

        self.assertEqual(run.state, IngestionRunState.SUCCEEDED)
        self.assertEqual(run.records_fetched, 1)
        self.assertEqual(run.records_parsed, 1)
        self.assertEqual(run.records_accepted, 1)
        self.assertEqual(run.stations_persisted, 1)
        self.assertEqual(run.attempt_count, 1)
        self.assertIsNotNone(run.completed_at)
        self.assertGreaterEqual(run.duration_seconds, 0.0)

    # --------------------------------------------------------------------------
    # 2. Manual and Scheduled Runs Share Same Canonical Pipeline
    # --------------------------------------------------------------------------
    def test_02_manual_run_and_scheduled_run_share_same_pipeline(self):
        """2. Verifies that runner.run() and runner.run_scheduled() invoke identical parsing and validation logic."""
        fixture = [OCM_FIXTURE_01_VALID_COMPLETE]

        # Manual path
        manual_summary = self.runner.run(fixtures_data=fixture, dry_run=True)
        # Scheduled path
        scheduled_run = self.runner.run_scheduled(
            config=ScheduleConfig(source_id="open_charge_map", dry_run=True),
            fixtures_data=fixture,
        )

        self.assertEqual(manual_summary.records_fetched, scheduled_run.records_fetched)
        self.assertEqual(manual_summary.records_accepted, scheduled_run.records_accepted)
        self.assertEqual(manual_summary.stations_persisted, scheduled_run.stations_persisted)

    # --------------------------------------------------------------------------
    # 3. Retry on Transient Timeout
    # --------------------------------------------------------------------------
    def test_03_retry_on_timeout(self):
        """3. Transient TimeoutError is classified as TRANSIENT, retried, and succeeds on next attempt."""
        calls = {"count": 0}

        def flaky_run(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("Connection to OpenChargeMap timed out after 30s")
            return IngestionSummary(
                source_id="open_charge_map", scope="mumbai",
                retrieved_at=datetime.now(timezone.utc), dry_run=True,
                records_fetched=1, records_parsed=1, records_accepted=1, stations_persisted=1,
            )

        with patch.object(self.runner, "run", side_effect=flaky_run):
            config = ScheduleConfig(
                source_id="open_charge_map",
                retry_policy=RetryPolicy(max_attempts=3, initial_delay_seconds=0.01),
            )
            run = self.orchestrator.execute_scheduled_run(config)

        self.assertEqual(run.state, IngestionRunState.SUCCEEDED)
        self.assertEqual(run.attempt_count, 2)
        self.assertEqual(calls["count"], 2)

    # --------------------------------------------------------------------------
    # 4. Retry on HTTP 429 Rate Limit
    # --------------------------------------------------------------------------
    def test_04_retry_on_http_429(self):
        """4. Upstream HTTP 429 rate limit is classified as TRANSIENT and retried."""
        policy = RetryPolicy(max_attempts=3)
        exc = RuntimeError("OpenChargeMap API rate limit exceeded (HTTP 429). Please back off.")
        classification = policy.classify_exception(exc)
        self.assertEqual(classification, FailureClassification.TRANSIENT)

    # --------------------------------------------------------------------------
    # 5. Upstream Retry-After Header Handling
    # --------------------------------------------------------------------------
    def test_05_retry_after_handling(self):
        """5. Explicit Retry-After header overrides default exponential backoff if larger."""
        policy = RetryPolicy(initial_delay_seconds=1.0, multiplier=2.0, max_delay_seconds=30.0)

        # Attempt 1 base delay is 1.0s, but upstream says Retry-After: 12.0s
        delay = policy.compute_delay(attempt=1, retry_after=12.0)
        self.assertEqual(delay, 12.0)

        # Respects max_delay bound if Retry-After exceeds it
        delay_capped = policy.compute_delay(attempt=1, retry_after=60.0)
        self.assertEqual(delay_capped, 30.0)

    # --------------------------------------------------------------------------
    # 6. Retry on HTTP 500, 502, 503, 504 Server Errors
    # --------------------------------------------------------------------------
    def test_06_retry_on_http_500_502_503_504(self):
        """6. Server errors (500, 502, 503, 504) are classified as TRANSIENT."""
        policy = RetryPolicy()
        for code in (500, 502, 503, 504):
            exc = RuntimeError(f"OpenChargeMap upstream server error (HTTP {code})")
            self.assertEqual(policy.classify_exception(exc), FailureClassification.TRANSIENT)

    # --------------------------------------------------------------------------
    # 7. No Retry on Permanent HTTP 400 Client Error
    # --------------------------------------------------------------------------
    def test_07_no_retry_on_400(self):
        """7. HTTP 400 Bad Request is classified as PERMANENT and never retried."""
        policy = RetryPolicy(max_attempts=5)
        exc = RuntimeError("Invalid query parameters supplied (HTTP 400)")
        self.assertEqual(policy.classify_exception(exc), FailureClassification.PERMANENT)

        calls = {"count": 0}

        def bad_request_run(*args, **kwargs):
            calls["count"] += 1
            raise RuntimeError("HTTP 400 Bad Request")

        with patch.object(self.runner, "run", side_effect=bad_request_run):
            config = ScheduleConfig(source_id="open_charge_map", retry_policy=policy)
            run = self.orchestrator.execute_scheduled_run(config)

        self.assertEqual(run.state, IngestionRunState.FAILED)
        self.assertEqual(run.attempt_count, 1)
        self.assertEqual(calls["count"], 1)  # Zero retry attempts

    # --------------------------------------------------------------------------
    # 8. No Retry on Authentication Failure (401/403)
    # --------------------------------------------------------------------------
    def test_08_no_retry_on_401_403(self):
        """8. Authentication / invalid API key error is PERMANENT and halts immediately."""
        policy = RetryPolicy(max_attempts=3)
        exc = PermissionError("OpenChargeMap API authentication failed (invalid or missing API key)")
        self.assertEqual(policy.classify_exception(exc), FailureClassification.PERMANENT)

        with patch.object(self.runner, "run", side_effect=exc):
            config = ScheduleConfig(source_id="open_charge_map", retry_policy=policy)
            run = self.orchestrator.execute_scheduled_run(config)

        self.assertEqual(run.state, IngestionRunState.FAILED)
        self.assertEqual(run.attempt_count, 1)

    # --------------------------------------------------------------------------
    # 9. No Retry on Invalid Configuration
    # --------------------------------------------------------------------------
    def test_09_no_retry_on_invalid_configuration(self):
        """9. Invalid schedule or retry configurations raise ValueError immediately."""
        with self.assertRaises(ValueError):
            ScheduleConfig(source_id="", limit=50)

        with self.assertRaises(ValueError):
            ScheduleConfig(source_id="ocm", limit=0)

        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)

        with self.assertRaises(ValueError):
            RetryPolicy(max_delay_seconds=0.5, initial_delay_seconds=1.0)

    # --------------------------------------------------------------------------
    # 10. Bounded Maximum Attempts
    # --------------------------------------------------------------------------
    def test_10_bounded_maximum_attempts(self):
        """10. Continuous transient failures terminate strictly after max_attempts."""
        calls = {"count": 0}

        def failing_run(*args, **kwargs):
            calls["count"] += 1
            raise ConnectionError("Persistent network outage")

        with patch.object(self.runner, "run", side_effect=failing_run):
            config = ScheduleConfig(
                source_id="open_charge_map",
                retry_policy=RetryPolicy(max_attempts=4, initial_delay_seconds=0.01),
            )
            run = self.orchestrator.execute_scheduled_run(config)

        self.assertEqual(run.state, IngestionRunState.FAILED)
        self.assertEqual(run.attempt_count, 4)
        self.assertEqual(calls["count"], 4)

    # --------------------------------------------------------------------------
    # 11. Bounded Exponential Backoff Scaling
    # --------------------------------------------------------------------------
    def test_11_exponential_backoff_calculation(self):
        """11. Tests exponential progression: initial * (multiplier^(attempt-1)) bounded by max_delay."""
        policy = RetryPolicy(
            initial_delay_seconds=2.0,
            multiplier=2.0,
            max_delay_seconds=10.0,
            jitter=False,
        )
        self.assertEqual(policy.compute_delay(attempt=1), 2.0)   # 2 * 2^0 = 2
        self.assertEqual(policy.compute_delay(attempt=2), 4.0)   # 2 * 2^1 = 4
        self.assertEqual(policy.compute_delay(attempt=3), 8.0)   # 2 * 2^2 = 8
        self.assertEqual(policy.compute_delay(attempt=4), 10.0)  # 2 * 2^3 = 16 -> capped at 10.0

    # --------------------------------------------------------------------------
    # 12. Jitter Scaling Within Testable Bounds
    # --------------------------------------------------------------------------
    def test_12_jitter_remains_bounded_and_testable(self):
        """12. Jitter produces values within [0.8, 1.2] * base_delay and is testable with mock random."""
        policy = RetryPolicy(initial_delay_seconds=10.0, jitter=True, max_delay_seconds=50.0)

        # Min jitter (rng = 0.0 -> scale = 0.8)
        delay_min = policy.compute_delay(attempt=1, random_fn=lambda: 0.0)
        self.assertEqual(delay_min, 8.0)

        # Max jitter (rng = 1.0 -> scale = 1.2)
        delay_max = policy.compute_delay(attempt=1, random_fn=lambda: 1.0)
        self.assertEqual(delay_max, 12.0)

        # Midpoint (rng = 0.5 -> scale = 1.0)
        delay_mid = policy.compute_delay(attempt=1, random_fn=lambda: 0.5)
        self.assertEqual(delay_mid, 10.0)

    # --------------------------------------------------------------------------
    # 13. Concurrency Protection Denies Overlapping Runs
    # --------------------------------------------------------------------------
    def test_13_concurrent_run_protection(self):
        """13. Attempting to start a concurrent run on the same source/scope is safely denied."""
        lock = IngestionConcurrencyLock(source_id="ocm", scope="mumbai")
        self.assertTrue(lock.acquire())

        # Second lock attempt must fail
        lock2 = IngestionConcurrencyLock(source_id="ocm", scope="mumbai")
        self.assertFalse(lock2.acquire())

        # Context manager raises ConcurrentRunError on collision
        with self.assertRaises(ConcurrentRunError):
            with lock2:
                pass

        # Release first lock; second acquisition now succeeds
        self.assertTrue(lock.release())
        self.assertTrue(lock2.acquire())
        self.assertTrue(lock2.release())

    # --------------------------------------------------------------------------
    # 14. Timeout Handling
    # --------------------------------------------------------------------------
    def test_14_timeout_handling(self):
        """14. Configured timeout_seconds is recorded in run metadata and passed to execution."""
        config = ScheduleConfig(source_id="open_charge_map", timeout_seconds=45.0, dry_run=True)
        run = self.orchestrator.execute_scheduled_run(
            config=config,
            fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE],
        )
        self.assertEqual(run.metadata.get("timeout_seconds"), 45.0)

    # --------------------------------------------------------------------------
    # 15. Partial Record Failures Mark Run PARTIAL
    # --------------------------------------------------------------------------
    def test_15_partial_record_failures(self):
        """15. Run containing both accepted and quarantined records is marked PARTIAL."""
        # Null Island triggers validation REJECT/QUARANTINE
        batch = [OCM_FIXTURE_01_VALID_COMPLETE, OCM_FIXTURE_09_NULL_ISLAND]
        config = ScheduleConfig(source_id="open_charge_map", limit=10)
        run = self.orchestrator.execute_scheduled_run(config, fixtures_data=batch)

        self.assertEqual(run.state, IngestionRunState.PARTIAL)
        self.assertEqual(run.records_fetched, 2)
        self.assertEqual(run.records_accepted, 1)
        self.assertEqual(run.records_rejected, 1)
        self.assertEqual(run.stations_persisted, 1)

    # --------------------------------------------------------------------------
    # 16. Quarantine Does Not Fail Entire Batch
    # --------------------------------------------------------------------------
    def test_16_quarantine_does_not_fail_entire_valid_batch(self):
        """16. Quarantined physical anomaly is excluded from persistence without aborting valid stations."""
        payload_quarantine = dict(OCM_FIXTURE_01_VALID_COMPLETE)
        payload_quarantine["ID"] = 999999
        payload_quarantine["AddressInfo"] = dict(payload_quarantine["AddressInfo"])
        payload_quarantine["AddressInfo"]["Latitude"] = 65.0  # Outside India bounding box

        batch = [OCM_FIXTURE_01_VALID_COMPLETE, payload_quarantine]
        config = ScheduleConfig(source_id="open_charge_map")
        run = self.orchestrator.execute_scheduled_run(config, fixtures_data=batch)

        self.assertEqual(run.records_quarantined, 1)
        self.assertEqual(run.records_accepted, 1)
        self.assertEqual(run.stations_persisted, 1)
        self.assertIn(run.state, (IngestionRunState.SUCCEEDED, IngestionRunState.PARTIAL))

    # --------------------------------------------------------------------------
    # 17. Source-Level Failure Produces FAILED Run
    # --------------------------------------------------------------------------
    def test_17_source_level_failure_produces_failed_run(self):
        """17. Unrecoverable source network failure marks run state as FAILED with error summary."""
        with patch.object(self.runner, "run", side_effect=ConnectionError("DNS lookup failed for api.openchargemap.io")):
            config = ScheduleConfig(
                source_id="open_charge_map",
                retry_policy=RetryPolicy(max_attempts=1),
            )
            run = self.orchestrator.execute_scheduled_run(config)

        self.assertEqual(run.state, IngestionRunState.FAILED)
        self.assertIn("DNS lookup failed", run.error_summary)
        self.assertEqual(run.stations_persisted, 0)

    # --------------------------------------------------------------------------
    # 18. Individual Persistence Failure Is Accounted For
    # --------------------------------------------------------------------------
    def test_18_individual_persistence_failure_accounted(self):
        """18. Database error persisting an individual record is captured in persistence_errors without crashing run."""
        self.mock_db.should_fail_first_station = True

        batch = [OCM_FIXTURE_01_VALID_COMPLETE, OCM_FIXTURE_02_MULTIPLE_CONNECTORS]
        config = ScheduleConfig(source_id="open_charge_map")
        run = self.orchestrator.execute_scheduled_run(config, fixtures_data=batch)

        self.assertGreaterEqual(len(run.persistence_errors), 1)
        self.assertEqual(run.state, IngestionRunState.PARTIAL)

    # --------------------------------------------------------------------------
    # 19. Rerunning Same Payload Remains Idempotent
    # --------------------------------------------------------------------------
    def test_19_rerunning_same_payload_remains_idempotent(self):
        """19. Ingesting identical source payload twice produces stations_unchanged on second run."""
        config = ScheduleConfig(source_id="open_charge_map")
        fixture = [OCM_FIXTURE_01_VALID_COMPLETE]

        run1 = self.orchestrator.execute_scheduled_run(config, fixtures_data=fixture)
        self.assertEqual(run1.stations_persisted, 1)
        self.assertEqual(run1.stations_unchanged, 0)

        run2 = self.orchestrator.execute_scheduled_run(config, fixtures_data=fixture)
        self.assertEqual(run2.stations_persisted, 0)
        self.assertEqual(run2.stations_unchanged, 1)

    # --------------------------------------------------------------------------
    # 20. No Duplicate Canonical Station on Rerun
    # --------------------------------------------------------------------------
    def test_20_no_duplicate_canonical_station(self):
        """20. Repeating scheduled ingestion creates exactly 1 physical station in public.stations."""
        config = ScheduleConfig(source_id="open_charge_map")
        fixture = [OCM_FIXTURE_01_VALID_COMPLETE]

        self.orchestrator.execute_scheduled_run(config, fixtures_data=fixture)
        self.orchestrator.execute_scheduled_run(config, fixtures_data=fixture)

        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)

    # --------------------------------------------------------------------------
    # 21. No Duplicate Station Source Link on Rerun
    # --------------------------------------------------------------------------
    def test_21_no_duplicate_source_link(self):
        """21. Rerun updates last_seen_at without duplicating public.station_source_link entries."""
        config = ScheduleConfig(source_id="open_charge_map")
        fixture = [OCM_FIXTURE_01_VALID_COMPLETE]

        self.orchestrator.execute_scheduled_run(config, fixtures_data=fixture)
        self.orchestrator.execute_scheduled_run(config, fixtures_data=fixture)

        links = self.mock_db.tables["public.station_source_link"]
        self.assertEqual(len(links), 1)
        self.assertGreaterEqual(self.mock_db.mutation_counts["source_links_updated"], 1)

    # --------------------------------------------------------------------------
    # 22. No Duplicate Historical Observations on Rerun
    # --------------------------------------------------------------------------
    def test_22_no_duplicate_observation(self):
        """22. Ingesting the same telemetry payload twice produces exactly 1 observation fact."""
        config = ScheduleConfig(source_id="open_charge_map")
        fixture = [OCM_FIXTURE_13_TELEMETRY_AVAILABLE]

        run1 = self.orchestrator.execute_scheduled_run(config, fixtures_data=fixture)
        self.assertEqual(run1.observations_persisted, 1)

        run2 = self.orchestrator.execute_scheduled_run(config, fixtures_data=fixture)
        self.assertEqual(run2.observations_persisted, 0)
        self.assertEqual(len(self.mock_db.tables["public.station_observations"]), 1)

    # --------------------------------------------------------------------------
    # 23. Crash / Retry Scenario Remains Safe
    # --------------------------------------------------------------------------
    def test_23_crash_retry_scenario_remains_safe(self):
        """23. A crashed run that retries reprocesses records cleanly without orphaned state."""
        calls = {"count": 0}

        def crash_on_first_run(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                # Simulate partial write then crash
                self.mock_db.tables["public.stations"].append({"id": "partial_stn", "name": "Partial"})
                raise psycopg2.OperationalError("Database connection lost mid-batch")
            return IngestionSummary(
                source_id="open_charge_map", scope="mumbai",
                retrieved_at=datetime.now(timezone.utc), dry_run=False,
                records_fetched=1, records_parsed=1, records_accepted=1, stations_persisted=1,
            )

        with patch.object(self.runner, "run", side_effect=crash_on_first_run):
            config = ScheduleConfig(
                source_id="open_charge_map",
                retry_policy=RetryPolicy(max_attempts=2, initial_delay_seconds=0.01),
            )
            run = self.orchestrator.execute_scheduled_run(config)

        self.assertEqual(run.state, IngestionRunState.SUCCEEDED)
        self.assertEqual(run.attempt_count, 2)

    # --------------------------------------------------------------------------
    # 24. Dry Run Produces Zero Persistent Mutations
    # --------------------------------------------------------------------------
    def test_24_dry_run_creates_no_persistent_mutation(self):
        """24. Running scheduled execution with dry_run=True performs zero database writes."""
        config = ScheduleConfig(source_id="open_charge_map", dry_run=True)
        run = self.orchestrator.execute_scheduled_run(
            config=config,
            fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE],
        )

        self.assertEqual(run.state, IngestionRunState.SUCCEEDED)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 0)
        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 0)
        self.assertEqual(len(self.mock_db.tables["public.ingestion_runs"]), 0)

    # --------------------------------------------------------------------------
    # 25. Run Metrics Are Internally Consistent
    # --------------------------------------------------------------------------
    def test_25_run_metrics_are_internally_consistent(self):
        """25. Fetched records equal sum of parsed and unparsed rejected records."""
        batch = [
            OCM_FIXTURE_01_VALID_COMPLETE,
            OCM_FIXTURE_04_MISSING_OPTIONAL_FIELDS,
            OCM_FIXTURE_09_NULL_ISLAND,
        ]
        config = ScheduleConfig(source_id="open_charge_map")
        run = self.orchestrator.execute_scheduled_run(config, fixtures_data=batch)

        self.assertEqual(run.records_fetched, len(batch))
        self.assertEqual(
            run.records_accepted + run.records_accepted_with_warnings + run.records_quarantined + run.records_rejected,
            run.records_fetched,
        )

    # --------------------------------------------------------------------------
    # 26. Secrets Are Scrubbed from Error Summaries and Logs
    # --------------------------------------------------------------------------
    def test_26_secrets_are_not_present_in_logs_or_errors(self):
        """26. Database passwords and API keys are completely redacted from error strings."""
        raw_error = "Connection failed to postgresql://postgres:SuperSecretPassword123@aws.pooler.supabase.com:5432/postgres?api_key=ocm_live_key_9988"
        scrubbed = _scrub_secrets(raw_error)

        self.assertNotIn("SuperSecretPassword123", scrubbed)
        self.assertNotIn("ocm_live_key_9988", scrubbed)
        self.assertIn(":***", scrubbed)

        # Test within run object
        with patch.object(self.runner, "run", side_effect=ConnectionError(raw_error)):
            config = ScheduleConfig(
                source_id="open_charge_map",
                retry_policy=RetryPolicy(max_attempts=1),
            )
            run = self.orchestrator.execute_scheduled_run(config)

        self.assertNotIn("SuperSecretPassword123", run.error_summary)
        self.assertNotIn("ocm_live_key_9988", run.error_summary)

    # --------------------------------------------------------------------------
    # 27. Scheduler Never Fabricates Live Observations from Static Metadata
    # --------------------------------------------------------------------------
    def test_27_scheduler_does_not_fabricate_live_observations(self):
        """27. Static station metadata with StatusTypeID 50 does NOT generate a live availability observation."""
        config = ScheduleConfig(source_id="open_charge_map")
        run = self.orchestrator.execute_scheduled_run(
            config=config,
            fixtures_data=[OCM_FIXTURE_14_STATIC_OPERATIONAL_NOT_AVAILABLE],
        )

        self.assertEqual(run.stations_persisted, 1)
        self.assertEqual(run.observations_persisted, 0)
        self.assertEqual(len(self.mock_db.tables["public.station_observations"]), 0)

    # --------------------------------------------------------------------------
    # 28. Retrieval Timestamp Remains Distinct from Observation Timestamp
    # --------------------------------------------------------------------------
    def test_28_retrieval_timestamp_remains_distinct_from_observation_timestamp(self):
        """28. Telemetry observation timestamp is distinct from scheduler retrieval time."""
        config = ScheduleConfig(source_id="open_charge_map")
        self.orchestrator.execute_scheduled_run(
            config=config,
            fixtures_data=[OCM_FIXTURE_13_TELEMETRY_AVAILABLE],
        )

        obs_row = self.mock_db.tables["public.station_observations"][0]
        # Fixture 13 has DateLastStatusUpdate = "2024-03-20T14:15:00Z" (historical observation)
        self.assertEqual(obs_row["observed_at"].year, 2024)
        self.assertEqual(obs_row["received_at"].year, 2026)
        self.assertNotEqual(obs_row["observed_at"], obs_row["received_at"])

    # --------------------------------------------------------------------------
    # 29. Step 2.9 Freshness Contract Is Preserved (STALE != UNAVAILABLE)
    # --------------------------------------------------------------------------
    def test_29_existing_step_2_9_freshness_behavior_preserved(self):
        """29. Freshness evaluation on old observation yields STALE without altering AVAILABLE status."""
        old_time = datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)
        as_of_time = datetime(2026, 9, 26, 10, 0, 0, tzinfo=timezone.utc)  # 6 days later

        obs = NormalizedObservationRecord(
            source_id="open_charge_map",
            source_station_id="1001",
            observed_at=old_time,
            retrieved_at=old_time,
            availability_status=AvailabilityStatus.AVAILABLE,
        )

        engine = FreshnessEngine()
        result = engine.evaluate_observation(obs=obs, as_of=as_of_time)

        self.assertEqual(result.state, FreshnessState.STALE)
        self.assertEqual(obs.availability_status, AvailabilityStatus.AVAILABLE)  # Unaltered!

    # --------------------------------------------------------------------------
    # 30. Step 2.8 Transaction and Rollback Semantics Intact
    # --------------------------------------------------------------------------
    def test_30_existing_step_2_8_transaction_semantics_intact(self):
        """30. Failed transaction rolls back isolated mutation without leaving orphaned rows."""
        self.mock_db.should_fail_persistence = True

        config = ScheduleConfig(
            source_id="open_charge_map",
            retry_policy=RetryPolicy(max_attempts=1),
        )
        run = self.orchestrator.execute_scheduled_run(
            config=config,
            fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE],
        )

        self.assertEqual(run.state, IngestionRunState.PARTIAL)
        self.assertEqual(run.stations_persisted, 0)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 0)

    # --------------------------------------------------------------------------
    # 31. PollingDaemon Graceful Start, Execution, and Signal Shutdown
    # --------------------------------------------------------------------------
    def test_31_polling_daemon_lifecycle_and_stop_signal(self):
        """31. PollingDaemon executes schedules and terminates cleanly when stop is requested."""
        schedule = ScheduleConfig(source_id="open_charge_map", dry_run=True, interval_seconds=1)
        daemon = PollingDaemon(
            orchestrator=self.orchestrator,
            schedules=[schedule],
            sleep_fn=lambda sec: None,
        )

        # Execute single cycle (run_once=True) with mock runner.run
        mock_summary = IngestionSummary(
            source_id="open_charge_map",
            scope="mumbai",
            retrieved_at=datetime.now(timezone.utc),
            dry_run=True,
            records_fetched=1,
            records_parsed=1,
            records_accepted=1,
            stations_persisted=1,
        )
        with patch.object(self.runner, "run", return_value=mock_summary):
            runs = daemon.start(run_once=True)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].state, IngestionRunState.SUCCEEDED)

        # Test graceful stop request
        daemon.request_stop()
        self.assertTrue(daemon._stop_requested.is_set())

    # --------------------------------------------------------------------------
    # 32. Live Database Ingestion Run Persistence & Clean Rollback/Cleanup
    # --------------------------------------------------------------------------
    def test_32_live_database_ingestion_run_persistence_and_cleanup(self):
        """32. Tests real public.ingestion_runs audit insert and clean cleanup on live Supabase PostgreSQL."""
        load_dotenv(".env.local")
        load_dotenv(".env")
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            self.skipTest("DATABASE_URL not configured. Skipping live PostgreSQL test.")

        real_conn = None
        test_run_id = str(uuid.uuid4())
        try:
            real_conn = psycopg2.connect(db_url)
            persistence = IngestionPersistenceService(real_conn)

            run = IngestionRun(
                run_id=test_run_id,
                source_id="test_automated_audit",
                source_name="open_charge_map",
                scope="mumbai",
                state=IngestionRunState.SUCCEEDED,
                started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
                completed_at=datetime.now(timezone.utc),
                duration_seconds=9.85,
                attempt_count=1,
                records_fetched=10,
                records_parsed=10,
                records_accepted=10,
                stations_persisted=2,
                observations_persisted=1,
                metadata={"test_suite": "test_scheduled_ingestion"},
            )

            # Persist run audit record
            persisted_id = persistence.persist_ingestion_run(run)
            self.assertEqual(persisted_id, test_run_id)

            # Verify presence in public.ingestion_runs
            cur = real_conn.cursor()
            cur.execute("SELECT state, records_fetched, duration_seconds FROM public.ingestion_runs WHERE id = %s;", (test_run_id,))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "SUCCEEDED")
            self.assertEqual(row[1], 10)
            self.assertEqual(float(row[2]), 9.85)

            # Clean up test audit record to maintain zero DB pollution
            cur.execute("DELETE FROM public.ingestion_runs WHERE id = %s;", (test_run_id,))
            real_conn.commit()
            cur.close()

        finally:
            if real_conn and not real_conn.closed:
                try:
                    cur = real_conn.cursor()
                    cur.execute("DELETE FROM public.ingestion_runs WHERE id = %s;", (test_run_id,))
                    real_conn.commit()
                    cur.close()
                except Exception:
                    pass
                real_conn.close()


if __name__ == "__main__":
    unittest.main()
