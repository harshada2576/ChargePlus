"""ChargePlus — Pre-Phase-4 gate regression tests.

R4 (connector vocabulary):
1. OCM connection type 32 normalizes to canonical 'CCS1'.
2. A CCS1 connector persists (no longer skipped by the DB-enum guard).
3. An 'Other' connector is still skipped + counted (no honest DB
   representation exists), while the station shell is preserved.
4. The persistence allow-list matches the migrated database CHECK
   vocabulary exactly (CCS1 added, Other excluded).

Run-state alignment (targeted audit):
5. A direct runner.run() batch with validation rejections records
   PARTIAL (not FAILED) in public.ingestion_runs — FAILED is reserved
   for runs that raised. Matches orchestrator semantics.
"""

from __future__ import annotations

import copy
import unittest
import uuid

from backend.ingestion.adapters.openchargemap import OpenChargeMapAdapter
from backend.ingestion.constants import StandardConnectorType
from backend.ingestion.runner import IngestionRunner
from backend.ingestion.scheduling import IngestionConcurrencyLock, IngestionRunState
from backend.ingestion.persistence import (
    ALLOWED_DB_CONNECTOR_TYPES,
    IngestionPersistenceService,
)
from tests.fixtures.ocm_fixtures import (
    OCM_FIXTURE_01_VALID_COMPLETE,
    OCM_FIXTURE_09_NULL_ISLAND,
)
from tests.test_canonical_operational_loading import MockDatabaseConnection
from tests.test_ingestion_persistence import InMemoryDbConnection

# Migrated database vocabulary (chk_connectors_connector_type /
# chk_dim_connector_type after pre-Phase-4 R4).
DB_CONNECTOR_VOCABULARY = {
    "CCS2",
    "CCS1",
    "CHAdeMO",
    "Type 2",
    "Type 1",
    "GB/T",
    "Bharat AC001",
    "Bharat DC001",
}


def _ccs1_plus_other_payload() -> dict:
    payload = copy.deepcopy(OCM_FIXTURE_01_VALID_COMPLETE)
    payload["ID"] = 770001
    payload["Connections"] = [
        {
            "ID": 770101,
            "ConnectionTypeID": 32,  # CCS (Type 1)
            "ConnectionType": {"ID": 32, "Title": "CCS (Type 1)"},
            "Quantity": 1,
            "PowerKW": 50.0,
            "StatusTypeID": 50,
        },
        {
            "ID": 770102,
            "ConnectionTypeID": 9999,  # unknown to the OCM map
            "ConnectionType": {"ID": 9999, "Title": "Flux Capacitor Port"},
            "Quantity": 1,
            "PowerKW": 22.0,
            "StatusTypeID": 50,
        },
    ]
    return payload


class TestPrePhase4ConnectorVocabulary(unittest.TestCase):
    def setUp(self):
        self.mock_db = InMemoryDbConnection()
        self.service = IngestionPersistenceService(self.mock_db)
        self.adapter = OpenChargeMapAdapter()

    def test_01_ocm_type_32_normalizes_to_ccs1(self):
        res = self.adapter.process_record(_ccs1_plus_other_payload())
        self.assertIsNotNone(res.station_record)
        types = [c.connector_type for c in res.station_record.connectors]
        self.assertIn(StandardConnectorType.CCS1.value, types)
        self.assertIn(StandardConnectorType.OTHER.value, types)

    def test_02_ccs1_persists_other_skipped(self):
        res = self.adapter.process_record(_ccs1_plus_other_payload())
        station = res.station_record
        warnings: list[str] = []
        with self.mock_db.cursor() as cur:
            persisted, skipped = self.service._sync_connectors(
                cur, uuid.uuid4(), station.connectors, warnings
            )
        stored_types = [c["connector_type"] for c in self.mock_db.tables["public.connectors"]]
        self.assertIn("CCS1", stored_types)
        self.assertNotIn("Other", stored_types)
        self.assertEqual(persisted, 1)
        self.assertEqual(skipped, 1)
        self.assertTrue(any("Other" in w for w in warnings))

    def test_03_allow_list_matches_migrated_db_vocabulary(self):
        self.assertEqual(ALLOWED_DB_CONNECTOR_TYPES, DB_CONNECTOR_VOCABULARY)


class TestPrePhase4RunStateAlignment(unittest.TestCase):
    """Direct runner.run() records PARTIAL (not FAILED) for batches with
    validation rejections. FAILED is reserved for runs that raised."""

    def test_04_rejections_record_partial_not_failed(self):
        mock_db = MockDatabaseConnection()
        persistence = IngestionPersistenceService(mock_db)
        runner = IngestionRunner(persistence_service=persistence)
        runner.api_key = "DUMMY_KEY"

        summary = runner.run(
            dry_run=False,
            fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE, OCM_FIXTURE_09_NULL_ISLAND],
        )
        self.assertEqual(summary.records_rejected, 1)

        rows = mock_db.tables["public.ingestion_runs"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], IngestionRunState.PARTIAL.value)


class _FailingPgCursor:
    def execute(self, *args, **kwargs):
        raise ConnectionError("simulated advisory-lock outage")

    def close(self):
        pass


class _FailingPgConn:
    def cursor(self):
        return _FailingPgCursor()


class _ConnHolder:
    def __init__(self, conn):
        self.conn = conn


class TestPrePhase4LockFailClosed(unittest.TestCase):
    """A live connection that cannot execute pg_try_advisory_lock must
    deny (fail-closed) rather than downgrade to a process-local lock."""

    def test_05_pg_lock_error_denies_without_local_fallback(self):
        lock = IngestionConcurrencyLock(
            source_id="open_charge_map",
            scope="mumbai",
            persistence_service=_ConnHolder(_FailingPgConn()),
        )
        self.assertFalse(lock.acquire())

    def test_06_offline_mode_still_uses_local_lock(self):
        lock = IngestionConcurrencyLock(source_id="open_charge_map", scope="mumbai")
        self.assertTrue(lock.acquire())
        self.assertTrue(lock.release())


if __name__ == "__main__":
    unittest.main()
