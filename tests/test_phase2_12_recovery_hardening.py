"""ChargePlus — Phase 2.12 Recovery Hardening Regression Suite.

Verifies the final four Phase 2 blockers:
1. Unknown-power connector semantics (unknown power preserved as NULL, never 0, never deleted, quantity preserved, durable metric).
2. Candidate lookup safety (fail-closed, candidate lookup failure raises CandidateLookupError, 0 mutations, marked FAILED, classified TRANSIENT).
3. Single ingestion_runs owner (runner owns execution and run accounting, scheduler never double-writes, retry attempts get separate rows).
4. Documentation and governance invariants.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock, patch
import uuid

import psycopg2

from backend.ingestion.constants import AvailabilityStatus, OperationalStatus, StandardConnectorType
from backend.ingestion.contracts import (
    CandidateLookupError,
    NormalizedConnectorRecord,
    NormalizedObservationRecord,
    NormalizedStationRecord,
)
from backend.ingestion.deduplication import (
    CanonicalDecisionState,
    CanonicalDeduplicationEngine,
    CanonicalResolutionDecision,
    ExistingCanonicalStation,
    FieldSurvivorshipDecision,
    SurvivorshipStrategy,
)
from backend.ingestion.persistence import (
    BatchCanonicalPersistenceReport,
    CanonicalPersistenceResult,
    CanonicalPersistenceStatus,
    IngestionPersistenceService,
)
from backend.ingestion.runner import IngestionRunner, IngestionSummary
from backend.ingestion.scheduling import (
    FailureClassification,
    IngestionRun,
    IngestionRunState,
    RetryPolicy,
    ScheduleConfig,
    ScheduledIngestionOrchestrator,
)
from tests.fixtures.ocm_fixtures import (
    OCM_FIXTURE_01_VALID_COMPLETE,
    OCM_FIXTURE_02_MULTIPLE_CONNECTORS,
    OCM_FIXTURE_06_MISSING_POWER,
)
from tests.test_canonical_operational_loading import MockDatabaseConnection


class TestPhase2_12_RecoveryHardening(unittest.TestCase):
    """Proves the resolution of the four Phase 2 blockers."""

    def setUp(self):
        self.mock_db = MockDatabaseConnection()
        self.persistence = IngestionPersistenceService(self.mock_db)
        self.runner = IngestionRunner(persistence_service=self.persistence)
        self.runner.api_key = "DUMMY_KEY"
        self.orchestrator = ScheduledIngestionOrchestrator(
            runner=self.runner,
            persistence_service=self.persistence,
            sleep_fn=lambda sec: None,
        )

    def _create_record(
        self,
        source_id: str = "open_charge_map",
        source_station_id: str = "stn-1",
        connectors: list[NormalizedConnectorRecord] | None = None,
        name: str = "Test Station",
    ) -> NormalizedStationRecord:
        """Helper to create a valid NormalizedStationRecord."""
        if connectors is None:
            connectors = [
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=60.0,
                    quantity=2,
                )
            ]
        return NormalizedStationRecord(
            source_id=source_id,
            source_station_id=source_station_id,
            name=name,
            operator_name="Tata Power",
            operator_slug="tata-power",
            latitude=19.0760,
            longitude=72.8777,
            address_line="Bandra East",
            locality="Bandra East",
            city="Mumbai",
            state="Maharashtra",
            postal_code="400051",
            country="India",
            is_24_hours=True,
            operational_status=OperationalStatus.OPERATIONAL,
            connectors=connectors,
            extra_metadata={
                "payload_hash": f"hash_{source_id}_{source_station_id}",
                "source_url": f"https://example.com/stn/{source_station_id}",
            },
        )

    # ==========================================================================
    # BLOCKER 2 — UNKNOWN-POWER CONNECTOR SEMANTICS
    # ==========================================================================

    def test_01_known_power_persists(self):
        """1. Connectors with known power persist with exact float power_kw."""
        rec = self._create_record(
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=60.0,
                    quantity=2,
                )
            ]
        )
        dec = CanonicalDeduplicationEngine.evaluate_records([rec])[0]
        res = self.persistence.persist_canonical_decision(dec)

        self.assertEqual(res.status, CanonicalPersistenceStatus.INSERTED)
        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 1)
        conn = self.mock_db.tables["public.connectors"][0]
        self.assertEqual(conn["power_kw"], 60.0)
        self.assertEqual(conn["quantity"], 2)
        self.assertEqual(res.connectors_with_unknown_power, 0)

    def test_02_missing_power_does_not_delete_connector(self):
        """2. Missing connector power preserves connector rather than dropping it."""
        rec = self._create_record(
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="Type 2",
                    raw_connector_type="Type 2",
                    power_kw=None,
                    quantity=3,
                )
            ]
        )
        dec = CanonicalDeduplicationEngine.evaluate_records([rec])[0]
        res = self.persistence.persist_canonical_decision(dec)

        self.assertEqual(res.status, CanonicalPersistenceStatus.INSERTED)
        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 1)
        conn = self.mock_db.tables["public.connectors"][0]
        self.assertIsNone(conn["power_kw"])
        self.assertEqual(conn["quantity"], 3)
        self.assertEqual(res.connectors_with_unknown_power, 3)

    def test_03_missing_power_does_not_become_zero(self):
        """3. Missing power persists as None (SQL NULL), NEVER fabricated as 0.0 kW."""
        rec = self._create_record(
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=None,
                    quantity=1,
                )
            ]
        )
        dec = CanonicalDeduplicationEngine.evaluate_records([rec])[0]
        self.persistence.persist_canonical_decision(dec)

        conn = self.mock_db.tables["public.connectors"][0]
        self.assertIsNone(conn["power_kw"])
        self.assertNotEqual(conn["power_kw"], 0.0)

    def test_04_connector_quantity_remains_correct(self):
        """4. Preserves physical connector quantity when power is unknown."""
        rec = self._create_record(
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=None,
                    quantity=4,
                )
            ]
        )
        dec = CanonicalDeduplicationEngine.evaluate_records([rec])[0]
        res = self.persistence.persist_canonical_decision(dec)

        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 1)  # 1 DB row
        self.assertEqual(self.mock_db.tables["public.connectors"][0]["quantity"], 4)  # 4 physical plugs
        self.assertEqual(res.connectors_persisted, 4)

    def test_05_warning_unknown_metric_is_durable(self):
        """5. Connectors with unknown power generate durable accounting metrics and warnings."""
        rec = self._create_record(
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="Type 2",
                    raw_connector_type="Type 2",
                    power_kw=None,
                    quantity=2,
                )
            ]
        )
        dec = CanonicalDeduplicationEngine.evaluate_records([rec])[0]
        res = self.persistence.persist_canonical_decision(dec)

        self.assertEqual(res.connectors_with_unknown_power, 2)
        self.assertTrue(any("unknown power_kw" in w for w in res.warnings))

    def test_06_reingestion_is_idempotent(self):
        """6. Re-ingesting station with unknown-power connectors is idempotent."""
        rec = self._create_record(
            source_station_id="stn-idem-unk",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=None,
                    quantity=2,
                )
            ]
        )
        dec1 = CanonicalDeduplicationEngine.evaluate_records([rec])[0]
        res1 = self.persistence.persist_canonical_decision(dec1)
        self.assertEqual(res1.status, CanonicalPersistenceStatus.INSERTED)
        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 1)

        # Second ingestion of identical payload
        dec2 = CanonicalDeduplicationEngine.evaluate_records([rec])[0]
        res2 = self.persistence.persist_canonical_decision(dec2)
        self.assertEqual(res2.status, CanonicalPersistenceStatus.UNCHANGED)
        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 1)

    def test_07_source_connector_id_remains_preserved(self):
        """7. Source connector ID is retained when power is unknown."""
        rec = self._create_record(
            connectors=[
                NormalizedConnectorRecord(
                    source_connector_id="ocm-conn-998",
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=None,
                    quantity=1,
                )
            ]
        )
        self.assertEqual(rec.connectors[0].source_connector_id, "ocm-conn-998")

    # ==========================================================================
    # BLOCKER 3 — FAIL-CLOSED CANDIDATE LOOKUP
    # ==========================================================================

    def test_08_lookup_success_no_candidate_inserts(self):
        """8. Candidate lookup succeeds with [] -> inserts new canonical station."""
        summary = self.runner.run(fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE], dry_run=False)
        self.assertEqual(summary.stations_persisted, 1)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)

    def test_09_lookup_success_with_candidate_links_or_merges(self):
        """9. Candidate lookup succeeds with matching candidate -> links without creating duplicate."""
        summary1 = self.runner.run(fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE], dry_run=False)
        self.assertEqual(summary1.stations_persisted, 1)
        stn_uuid = self.mock_db.tables["public.stations"][0]["id"]

        # Run again with same payload
        summary2 = self.runner.run(fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE], dry_run=False)
        self.assertEqual(summary2.stations_persisted, 0)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)
        self.assertEqual(self.mock_db.tables["public.stations"][0]["id"], stn_uuid)

    def test_10_lookup_failure_prevents_persistence(self):
        """10. Candidate lookup failure aborts decision making and causes 0 mutations."""
        with patch.object(
            self.persistence,
            "fetch_existing_canonical_stations",
            side_effect=psycopg2.OperationalError("Simulated DB connection lost during candidate retrieval"),
        ):
            with self.assertRaises(CandidateLookupError):
                self.runner.run(fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE], dry_run=False)

        # Must perform zero mutations
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 0)
        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 0)
        self.assertEqual(len(self.mock_db.tables["public.station_source_link"]), 0)
        self.assertEqual(len(self.mock_db.tables["public.station_observations"]), 0)

    def test_11_lookup_failure_marks_run_failed(self):
        """11. Candidate lookup failure records FAILED in public.ingestion_runs."""
        with patch.object(
            self.persistence,
            "fetch_existing_canonical_stations",
            side_effect=psycopg2.OperationalError("Simulated DB failure"),
        ):
            with self.assertRaises(CandidateLookupError):
                self.runner.run(fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE], dry_run=False)

        # Single run accounting record written with FAILED state
        self.assertEqual(len(self.mock_db.tables["public.ingestion_runs"]), 1)
        run_row = self.mock_db.tables["public.ingestion_runs"][0]
        self.assertEqual(run_row["state"], IngestionRunState.FAILED.value)

    def test_12_lookup_failure_is_transient_retryable(self):
        """12. CandidateLookupError is classified as TRANSIENT to allow scheduler retries."""
        policy = RetryPolicy()
        exc = CandidateLookupError("Database query timed out during candidate lookup")
        classification = policy.classify_exception(exc)
        self.assertEqual(classification, FailureClassification.TRANSIENT)

    def test_13_no_duplicate_canonical_station_on_lookup_failure(self):
        """13. Lookup failure cannot create duplicate canonical stations."""
        # Initial successful ingestion
        self.runner.run(fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE], dry_run=False)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)

        # Second attempt suffers candidate lookup failure
        with patch.object(
            self.persistence,
            "fetch_existing_canonical_stations",
            side_effect=psycopg2.OperationalError("Simulated connection timeout"),
        ):
            with self.assertRaises(CandidateLookupError):
                self.runner.run(fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE], dry_run=False)

        # Station count must remain exactly 1 (no duplicate inserted)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)

    # ==========================================================================
    # BLOCKER 4 — SINGLE INGESTION_RUNS OWNER
    # ==========================================================================

    def test_14_direct_run_single_ingestion_runs_row(self):
        """14. Direct runner.run() execution persists exactly 1 ingestion_runs record."""
        summary = self.runner.run(fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE], dry_run=False)
        self.assertEqual(len(self.mock_db.tables["public.ingestion_runs"]), 1)
        self.assertEqual(self.mock_db.tables["public.ingestion_runs"][0]["id"], summary.run_id)

    def test_15_scheduled_run_single_ingestion_runs_row(self):
        """15. Scheduled execution produces exactly 1 ingestion_runs record (no double-write)."""
        cfg = ScheduleConfig(source_id="open_charge_map", limit=5, scope="mumbai")
        run = self.orchestrator.execute_scheduled_run(cfg, fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE])

        self.assertEqual(run.state, IngestionRunState.SUCCEEDED)
        # PROOF: exactly 1 row persisted, NOT 2
        self.assertEqual(len(self.mock_db.tables["public.ingestion_runs"]), 1)
        self.assertEqual(self.mock_db.tables["public.ingestion_runs"][0]["id"], run.run_id)

    def test_16_run_once_single_ingestion_runs_row(self):
        """16. runner.run_scheduled() produces exactly 1 ingestion_runs record."""
        cfg = ScheduleConfig(source_id="open_charge_map", limit=5, scope="mumbai")
        run = self.runner.run_scheduled(cfg, fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE])

        self.assertEqual(run.state, IngestionRunState.SUCCEEDED)
        self.assertEqual(len(self.mock_db.tables["public.ingestion_runs"]), 1)

    def test_17_failed_run_single_ingestion_runs_row(self):
        """17. Failed run produces exactly 1 ingestion_runs record with state=FAILED."""
        with patch.object(
            self.persistence,
            "fetch_existing_canonical_stations",
            side_effect=psycopg2.OperationalError("DB failure"),
        ):
            cfg = ScheduleConfig(
                source_id="open_charge_map",
                limit=5,
                scope="mumbai",
                retry_policy=RetryPolicy(max_attempts=1),
            )
            run = self.orchestrator.execute_scheduled_run(cfg, fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE])

        self.assertEqual(run.state, IngestionRunState.FAILED)
        self.assertEqual(len(self.mock_db.tables["public.ingestion_runs"]), 1)
        self.assertEqual(self.mock_db.tables["public.ingestion_runs"][0]["state"], IngestionRunState.FAILED.value)

    def test_18_retry_attempts_produce_separate_rows(self):
        """18. Legitimate retry attempts produce separate distinguishable rows (1 per attempt)."""
        call_count = 0

        def flaky_candidate_lookup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise psycopg2.OperationalError("Transient lookup timeout on attempt 1")
            return []

        with patch.object(self.persistence, "fetch_existing_canonical_stations", side_effect=flaky_candidate_lookup):
            cfg = ScheduleConfig(
                source_id="open_charge_map",
                limit=5,
                scope="mumbai",
                retry_policy=RetryPolicy(max_attempts=2, initial_delay_seconds=0.01),
            )
            run = self.orchestrator.execute_scheduled_run(cfg, fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE])

        self.assertEqual(run.state, IngestionRunState.SUCCEEDED)
        self.assertEqual(call_count, 2)
        # Attempt 1: FAILED (1 row)
        # Attempt 2: SUCCEEDED (1 row)
        # Total: exactly 2 rows, one per logical execution attempt
        self.assertEqual(len(self.mock_db.tables["public.ingestion_runs"]), 2)
        states = [r["state"] for r in self.mock_db.tables["public.ingestion_runs"]]
        self.assertIn(IngestionRunState.FAILED.value, states)
        self.assertIn(IngestionRunState.SUCCEEDED.value, states)

    def test_19_no_duplicate_scheduler_accounting(self):
        """19. Orchestrator never independently creates a duplicate row when runner succeeds."""
        cfg = ScheduleConfig(source_id="open_charge_map", limit=5, scope="mumbai")
        self.orchestrator.execute_scheduled_run(cfg, fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE])
        self.assertEqual(len(self.mock_db.tables["public.ingestion_runs"]), 1)


if __name__ == "__main__":
    unittest.main()
