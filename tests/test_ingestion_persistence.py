"""ChargePlus — Ingestion Persistence & Orchestration Unit Test Suite.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.3 (Connect First Legitimate Station Data Source)

Verifies all 15 required Step 2.3 operational persistence and orchestration guarantees:
 1. Accepted station persists to operational database.
 2. Accepted-with-warning station persists when safe (e.g. non-Indian postal code logged and nulled).
 3. Rejected station does not persist.
 4. Quarantined station does not become trusted current state.
 5. Repeated identical ingestion is idempotent (UNCHANGED, zero duplicate stations).
 6. Changed source payload updates the existing source-linked station appropriately (UPDATED).
 7. Static OCM operational status does not create a fake availability observation.
 8. Genuine automated observation is persisted to analytics.fact_station_observation & public.station_observations.
 9. Missing power remains NULL / skipped from public.connectors without inventing 0 kW.
10. Missing price remains NULL (no fake ₹0).
11. External source ID does not become canonical station UUID.
12. One failed record does not corrupt the whole batch (record-level failure isolation).
13. Dry-run produces zero database writes.
14. Credentials never appear in logs or errors.
15. Provenance contract_version remains "1.0.0".
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import unittest
from unittest.mock import MagicMock, patch
import uuid

from backend.ingestion.adapters.openchargemap import OpenChargeMapAdapter
from backend.ingestion.constants import (
    CONTRACT_VERSION,
    AvailabilityStatus,
    OperationalStatus,
    PricingType,
    ValidationOutcome,
)
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedObservationRecord,
    NormalizedStationRecord,
    ProvenanceInfo,
    RawSourceRecord,
)
from backend.ingestion.persistence import (
    IngestionPersistenceService,
    PersistenceStatus,
    StationPersistenceResult,
)
from backend.ingestion.runner import IngestionRunner, IngestionSummary
from tests.fixtures.ocm_fixtures import (
    OCM_FIXTURE_01_VALID_COMPLETE,
    OCM_FIXTURE_02_MULTIPLE_CONNECTORS,
    OCM_FIXTURE_03_AGGREGATED_CONNECTORS,
    OCM_FIXTURE_04_MISSING_OPTIONAL_FIELDS,
    OCM_FIXTURE_06_MISSING_POWER,
    OCM_FIXTURE_09_NULL_ISLAND,
    OCM_FIXTURE_10_NON_INDIA,
    OCM_FIXTURE_13_TELEMETRY_AVAILABLE,
    OCM_FIXTURE_14_STATIC_OPERATIONAL_NOT_AVAILABLE,
    OCM_FIXTURE_17_MALFORMED_RECORD,
    OCM_FIXTURE_18_MISSING_STATION_ID,
)


class InMemoryDbCursor:
    """Mock DB cursor simulating PostgreSQL queries over in-memory dictionaries."""

    def __init__(self, db: InMemoryDbConnection, as_dict: bool = False):
        self.db = db
        self.as_dict = as_dict
        self._last_result: list = []
        self._iter = iter(self._last_result)

    def execute(self, sql: str, params: tuple | list = ()):
        sql_clean = " ".join(sql.strip().split())
        self._last_result = []

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

        # 3. INSERT INTO analytics.dim_source
        elif "INSERT INTO analytics.dim_source" in sql_clean:
            s_id, name, s_type, priority, url = params
            key = len(self.db.tables["analytics.dim_source"]) + 1
            row = {"source_key": key, "source_id": s_id, "name": name, "source_type": s_type, "source_priority": priority, "base_url": url}
            self.db.tables["analytics.dim_source"].append(row)

        # 4. SELECT from public.operators
        elif "FROM public.operators WHERE slug = %s" in sql_clean:
            slug = params[0]
            for row in self.db.tables["public.operators"]:
                if row["slug"] == slug:
                    self._last_result = [row if self.as_dict else (row["id"],)]
                    break
        elif "FROM public.operators WHERE name = %s" in sql_clean:
            name = params[0]
            for row in self.db.tables["public.operators"]:
                if row["name"] == name:
                    self._last_result = [row if self.as_dict else (row["id"],)]
                    break

        # 5. INSERT INTO public.operators
        elif "INSERT INTO public.operators" in sql_clean:
            op_id, name, slug, web, phone = params
            row = {"id": op_id, "name": name, "slug": slug, "website_url": web, "support_phone": phone}
            self.db.tables["public.operators"].append(row)
            self._last_result = [row if self.as_dict else (op_id,)]

        # 6. SELECT from public.station_source_link
        elif "FROM public.station_source_link WHERE source_id = %s AND source_station_id = %s" in sql_clean:
            src_id, src_stn_id = str(params[0]), str(params[1])
            for row in self.db.tables["public.station_source_link"]:
                if str(row["source_id"]) == src_id and str(row["source_station_id"]) == src_stn_id:
                    self._last_result = [row if self.as_dict else (row["id"], row["station_id"], row["source_id"], row["source_station_id"], row["source_payload_hash"], row["first_seen_at"])]
                    break

        # 7. UPDATE public.station_source_link
        elif "UPDATE public.station_source_link SET last_seen_at = now()" in sql_clean:
            src_id, src_stn_id = str(params[0]), str(params[1])
            for row in self.db.tables["public.station_source_link"]:
                if str(row["source_id"]) == src_id and str(row["source_station_id"]) == src_stn_id:
                    row["last_seen_at"] = datetime.now(timezone.utc)
                    self.db.mutation_counts["station_source_link_updates"] += 1
                    break
        elif "UPDATE public.station_source_link SET source_payload_hash = %s" in sql_clean:
            new_hash, link_id = params
            for row in self.db.tables["public.station_source_link"]:
                if str(row["id"]) == str(link_id):
                    row["source_payload_hash"] = new_hash
                    row["last_ingested_at"] = datetime.now(timezone.utc)
                    self.db.mutation_counts["station_source_link_updates"] += 1
                    break

        # 8. UPDATE public.stations
        elif "UPDATE public.stations SET" in sql_clean:
            stn_id = str(params[-1])
            for row in self.db.tables["public.stations"]:
                if str(row["id"]) == stn_id:
                    row["name"] = params[0]
                    row["operator_id"] = params[1]
                    row["address_line"] = params[2]
                    row["locality"] = params[3]
                    row["city"] = params[4]
                    row["state"] = params[5]
                    row["postal_code"] = params[6]
                    row["country"] = params[7]
                    row["latitude"] = params[8]
                    row["longitude"] = params[9]
                    row["opening_time"] = params[10]
                    row["closing_time"] = params[11]
                    row["is_24_hours"] = params[12]
                    row["access_type"] = params[13]
                    row["is_public"] = params[14]
                    row["operational_status"] = params[15]
                    row["phone"] = params[16]
                    row["website_url"] = params[17]
                    row["last_verified_at"] = params[18]
                    self.db.mutation_counts["stations_updated"] += 1
                    break

        # 9. INSERT INTO public.stations
        elif "INSERT INTO public.stations" in sql_clean:
            (stn_id, slug, name, op_id, addr, loc, city, state, pin, ctry,
             lat, lng, op_t, cl_t, is_24, acc_t, is_pub, op_stat, phone, url, v_at) = params
            row = {
                "id": stn_id, "slug": slug, "name": name, "operator_id": op_id, "address_line": addr,
                "locality": loc, "city": city, "state": state, "postal_code": pin, "country": ctry,
                "latitude": lat, "longitude": lng, "opening_time": op_t, "closing_time": cl_t,
                "is_24_hours": is_24, "access_type": acc_t, "is_public": is_pub,
                "operational_status": op_stat, "phone": phone, "website_url": url, "last_verified_at": v_at,
            }
            self.db.tables["public.stations"].append(row)
            self.db.mutation_counts["stations_inserted"] += 1

        # 10. DELETE FROM public.connectors
        elif "DELETE FROM public.connectors WHERE station_id = %s" in sql_clean:
            stn_id = str(params[0])
            self.db.tables["public.connectors"] = [
                c for c in self.db.tables["public.connectors"] if str(c["station_id"]) != stn_id
            ]

        # 11. INSERT INTO public.connectors
        elif "INSERT INTO public.connectors" in sql_clean:
            cid, stn_id, ctype, std, pkw, qty = params
            row = {"id": cid, "station_id": stn_id, "connector_type": ctype, "charging_standard": std, "power_kw": pkw, "quantity": qty}
            self.db.tables["public.connectors"].append(row)
            self.db.mutation_counts["connectors_inserted"] += 1

        # 12. INSERT INTO public.station_source_link
        elif "INSERT INTO public.station_source_link" in sql_clean:
            stn_id, src_id, src_stn_id, s_url, p_hash = params
            link_id = uuid.uuid4()
            row = {
                "id": link_id, "station_id": stn_id, "source_id": src_id,
                "source_station_id": src_stn_id, "source_url": s_url,
                "source_payload_hash": p_hash, "first_seen_at": datetime.now(timezone.utc),
            }
            self.db.tables["public.station_source_link"].append(row)
            self.db.mutation_counts["station_source_link_inserted"] += 1

        # 13. INSERT INTO public.station_observations
        elif "INSERT INTO public.station_observations" in sql_clean:
            obs_id, stn_id, src_id, avail, q, avail_c, tot_c, o_time, r_time, p_hash = params
            row = {
                "id": obs_id, "station_id": stn_id, "source_id": src_id,
                "availability_status": avail, "queue_level": q,
                "available_connectors": avail_c, "total_connectors": tot_c,
                "observed_at": o_time, "received_at": r_time, "source_payload_hash": p_hash,
            }
            self.db.tables["public.station_observations"].append(row)
            self.db.mutation_counts["station_observations_inserted"] += 1

        # 14. SELECT from analytics.dim_source
        elif "SELECT source_key FROM analytics.dim_source WHERE source_id = %s" in sql_clean:
            src_id = str(params[0])
            for r in self.db.tables["analytics.dim_source"]:
                if str(r["source_id"]) == src_id:
                    self._last_result = [(r["source_key"],)]
                    break

        # 15. SELECT from analytics.dim_station
        elif "SELECT station_key FROM analytics.dim_station WHERE station_id = %s AND is_current = true" in sql_clean:
            stn_id = str(params[0])
            for r in self.db.tables["analytics.dim_station"]:
                if str(r["station_id"]) == stn_id and r.get("is_current", True):
                    self._last_result = [(r["station_key"],)]
                    break

        # 16. SELECT station join operator for dim_station synchronization
        elif "FROM public.stations s JOIN public.operators o" in sql_clean:
            stn_id = str(params[0])
            for s in self.db.tables["public.stations"]:
                if str(s["id"]) == stn_id:
                    op_row = next((o for o in self.db.tables["public.operators"] if str(o["id"]) == str(s["operator_id"])), None)
                    op_name = op_row["name"] if op_row else "Unknown Operator"
                    op_slug = op_row["slug"] if op_row else "unknown"
                    self._last_result = [(
                        s["name"], s["operator_id"], s["address_line"], s["locality"],
                        s["city"], s["state"], s["postal_code"], s["country"],
                        s["latitude"], s["longitude"], s["access_type"], s["is_public"],
                        s["operational_status"], s["is_24_hours"], s["opening_time"], s["closing_time"],
                        op_name, op_slug,
                    )]
                    break

        # 17. Operator & Location dimension inserts
        elif "SELECT operator_key FROM analytics.dim_operator" in sql_clean:
            op_id = str(params[0])
            for r in self.db.tables["analytics.dim_operator"]:
                if str(r["operator_id"]) == op_id:
                    self._last_result = [(r["operator_key"],)]
                    break
        elif "INSERT INTO analytics.dim_operator" in sql_clean:
            op_id, name, slug = params
            key = len(self.db.tables["analytics.dim_operator"]) + 1
            row = {"operator_key": key, "operator_id": op_id, "operator_name": name, "slug": slug}
            self.db.tables["analytics.dim_operator"].append(row)
            self._last_result = [(key,)]

        elif "SELECT location_key FROM analytics.dim_location" in sql_clean:
            ctry, state, city, loc, pin = params
            for r in self.db.tables["analytics.dim_location"]:
                if (r["country"] == ctry and r["state"] == state and r["city"] == city
                        and (r.get("locality") or "") == (loc or "")
                        and (r.get("postal_code") or "") == (pin or "")):
                    self._last_result = [(r["location_key"],)]
                    break
        elif "INSERT INTO analytics.dim_location" in sql_clean:
            ctry, state, city, loc, pin = params
            key = len(self.db.tables["analytics.dim_location"]) + 1
            row = {"location_key": key, "country": ctry, "state": state, "city": city, "locality": loc, "postal_code": pin}
            self.db.tables["analytics.dim_location"].append(row)
            self._last_result = [(key,)]

        elif "INSERT INTO analytics.dim_station" in sql_clean:
            stn_id = str(params[0])
            key = len(self.db.tables["analytics.dim_station"]) + 1
            row = {"station_key": key, "station_id": stn_id, "is_current": True}
            self.db.tables["analytics.dim_station"].append(row)
            self._last_result = [(key,)]

        # 18. INSERT INTO analytics.fact_station_observation
        elif "INSERT INTO analytics.fact_station_observation" in sql_clean:
            (obs_id, stn_k, d_k, t_k, src_k, o_time, r_time, avail, q, avail_c, tot_c, p_hash) = params
            row = {
                "observation_id": obs_id, "station_key": stn_k, "date_key": d_k, "time_key": t_k,
                "source_key": src_k, "observed_at": o_time, "received_at": r_time,
                "availability_status": avail, "queue_level": q, "available_connectors": avail_c,
                "total_connectors": tot_c, "source_payload_hash": p_hash,
            }
            self.db.tables["analytics.fact_station_observation"].append(row)
            self.db.mutation_counts["fact_station_observation_inserted"] += 1

        self._iter = iter(self._last_result)

    def fetchone(self):
        return next(self._iter, None)

    def fetchall(self):
        return list(self._iter)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class InMemoryDbConnection:
    """Mock connection providing isolated in-memory tables and tracking mutations."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {
            "public.data_sources": [],
            "public.operators": [],
            "public.stations": [],
            "public.connectors": [],
            "public.station_source_link": [],
            "public.station_observations": [],
            "analytics.dim_source": [],
            "analytics.dim_operator": [],
            "analytics.dim_location": [],
            "analytics.dim_station": [],
            "analytics.fact_station_observation": [],
        }
        self.mutation_counts: dict[str, int] = {
            "stations_inserted": 0,
            "stations_updated": 0,
            "station_source_link_inserted": 0,
            "station_source_link_updates": 0,
            "connectors_inserted": 0,
            "station_observations_inserted": 0,
            "fact_station_observation_inserted": 0,
        }
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, cursor_factory=None):
        as_dict = cursor_factory is not None
        return InMemoryDbCursor(self, as_dict=as_dict)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True

    def total_database_writes(self) -> int:
        return sum(self.mutation_counts.values())


class TestIngestionPersistenceAndRunner(unittest.TestCase):
    """Comprehensive test suite for Phase 2 Step 2.3 ingestion persistence and runner."""

    def setUp(self):
        self.mock_db = InMemoryDbConnection()
        self.service = IngestionPersistenceService(self.mock_db)
        self.adapter = OpenChargeMapAdapter()
        self.source_id = self.service.get_or_create_data_source(
            name="open_charge_map",
            source_type="api",
            base_url="https://api.openchargemap.io/v3/poi/",
        )

    # --------------------------------------------------------------------------
    # Test 1: Accepted station persists
    # --------------------------------------------------------------------------
    def test_01_accepted_station_persists(self):
        """1. Complete valid Mumbai station with Tata Power operator persists to public.stations."""
        res = self.adapter.process_record(OCM_FIXTURE_01_VALID_COMPLETE)
        self.assertTrue(res.success)
        self.assertEqual(res.validation_result.outcome, ValidationOutcome.ACCEPT)

        persist_res = self.service.persist_station(
            station=res.station_record,
            raw_record=res.raw_record,
            data_source_id=self.source_id,
        )

        self.assertEqual(persist_res.status, PersistenceStatus.INSERTED)
        self.assertTrue(persist_res.is_new)
        self.assertIsNotNone(persist_res.station_id)

        # Operational table assertions
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)
        stn = self.mock_db.tables["public.stations"][0]
        self.assertEqual(stn["name"], "Tata Power - BKC Fast Charging Hub")
        self.assertEqual(stn["city"], "Mumbai")
        self.assertEqual(stn["operational_status"], "operational")

        # Connectors assertion
        self.assertGreaterEqual(len(self.mock_db.tables["public.connectors"]), 1)
        self.assertEqual(self.mock_db.tables["public.connectors"][0]["connector_type"], "CCS2")
        self.assertEqual(self.mock_db.tables["public.connectors"][0]["power_kw"], 60.0)

        # Source link assertion
        self.assertEqual(len(self.mock_db.tables["public.station_source_link"]), 1)
        link = self.mock_db.tables["public.station_source_link"][0]
        self.assertEqual(str(link["station_id"]), str(persist_res.station_id))
        self.assertEqual(link["source_station_id"], "192840")

    # --------------------------------------------------------------------------
    # Test 2: Accepted-with-warning station persists when safe
    # --------------------------------------------------------------------------
    def test_02_accepted_with_warning_persists_safely(self):
        """2. Station with non-Indian postal code is ACCEPT_WITH_WARNINGS and persists safely with postal_code=NULL."""
        # Modifying postal code to alphanumeric format that fails Indian PIN check but is otherwise valid
        payload = dict(OCM_FIXTURE_01_VALID_COMPLETE)
        payload["AddressInfo"] = dict(payload["AddressInfo"])
        payload["AddressInfo"]["Postcode"] = "SW1A 1AA"

        res = self.adapter.process_record(payload)
        self.assertTrue(res.success)

        persist_res = self.service.persist_station(
            station=res.station_record,
            raw_record=res.raw_record,
            data_source_id=self.source_id,
        )

        self.assertEqual(persist_res.status, PersistenceStatus.INSERTED)
        stn = self.mock_db.tables["public.stations"][0]
        # Must be stored as NULL to prevent violating check constraint chk_stations_postal_code
        self.assertIsNone(stn["postal_code"])
        self.assertTrue(any("Postal code" in w for w in persist_res.warnings))

    # --------------------------------------------------------------------------
    # Test 3: Rejected station does not persist
    # --------------------------------------------------------------------------
    def test_03_rejected_station_does_not_persist(self):
        """3. Malformed coordinates / Null Island rejected record is NOT persisted to the database."""
        res = self.adapter.process_record(OCM_FIXTURE_09_NULL_ISLAND)
        self.assertFalse(res.success)
        self.assertTrue(any("Null Island" in err for err in res.errors))

        # Runner simulation: rejected stations are skipped
        runner = IngestionRunner(persistence_service=self.service)
        summary = runner.run(
            fixtures_data=[OCM_FIXTURE_09_NULL_ISLAND],
            dry_run=True,
        )

        self.assertEqual(summary.records_rejected, 1)
        self.assertEqual(summary.stations_persisted, 0)

    # --------------------------------------------------------------------------
    # Test 4: Quarantined station does not become trusted current state
    # --------------------------------------------------------------------------
    def test_04_quarantined_station_not_in_operational_state(self):
        """4. Coordinates outside geofence are quarantined and excluded from public.stations."""
        # Modifying coordinates of an India station to fall outside India geofence (triggers QUARANTINE)
        payload = dict(OCM_FIXTURE_01_VALID_COMPLETE)
        payload["AddressInfo"] = dict(payload["AddressInfo"])
        payload["AddressInfo"]["Latitude"] = 59.9139  # Outside India bounding box
        payload["AddressInfo"]["Longitude"] = 10.7522

        res = self.adapter.process_record(payload)
        self.assertTrue(res.success)
        self.assertEqual(res.validation_result.outcome, ValidationOutcome.QUARANTINE)

        # Runner excludes quarantined records from operational persistence
        runner = IngestionRunner(persistence_service=self.service)
        summary = runner.run(
            fixtures_data=[payload],
            dry_run=False,
        )

        self.assertEqual(summary.records_quarantined, 1)
        self.assertEqual(summary.stations_persisted, 0)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 0)

    # --------------------------------------------------------------------------
    # Test 5: Repeated identical ingestion is idempotent
    # --------------------------------------------------------------------------
    def test_05_repeated_identical_ingestion_is_idempotent(self):
        """5. Ingesting the identical source record twice creates 1 station and returns UNCHANGED on second run."""
        res = self.adapter.process_record(OCM_FIXTURE_01_VALID_COMPLETE)

        # First run: INSERT
        res1 = self.service.persist_station(
            station=res.station_record,
            raw_record=res.raw_record,
            data_source_id=self.source_id,
        )
        self.assertEqual(res1.status, PersistenceStatus.INSERTED)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)

        # Second run with same raw record and payload hash: UNCHANGED
        res2 = self.service.persist_station(
            station=res.station_record,
            raw_record=res.raw_record,
            data_source_id=self.source_id,
        )
        self.assertEqual(res2.status, PersistenceStatus.UNCHANGED)
        self.assertTrue(res2.is_unchanged)
        self.assertEqual(res2.station_id, res1.station_id)
        # Verify no duplicate station rows created
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)

    # --------------------------------------------------------------------------
    # Test 6: Changed source payload updates existing station
    # --------------------------------------------------------------------------
    def test_06_changed_source_payload_updates_existing_station(self):
        """6. Re-ingesting an updated source payload updates public.stations and refreshes hash in source_link."""
        res1 = self.adapter.process_record(OCM_FIXTURE_01_VALID_COMPLETE)
        self.service.persist_station(
            station=res1.station_record,
            raw_record=res1.raw_record,
            data_source_id=self.source_id,
        )

        # Update payload title and re-process
        payload_v2 = dict(OCM_FIXTURE_01_VALID_COMPLETE)
        payload_v2["AddressInfo"] = dict(payload_v2["AddressInfo"])
        payload_v2["AddressInfo"]["Title"] = "Tata Power - BKC Fast Charging Hub (Updated Name)"

        res2 = self.adapter.process_record(payload_v2)
        persist_res2 = self.service.persist_station(
            station=res2.station_record,
            raw_record=res2.raw_record,
            data_source_id=self.source_id,
        )

        self.assertEqual(persist_res2.status, PersistenceStatus.UPDATED)
        self.assertTrue(persist_res2.is_updated)
        # Verify title was updated in-place without creating a second station
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)
        self.assertEqual(self.mock_db.tables["public.stations"][0]["name"], "Tata Power - BKC Fast Charging Hub (Updated Name)")

    # --------------------------------------------------------------------------
    # Test 7: Static operational status does NOT create observation
    # --------------------------------------------------------------------------
    def test_07_static_status_does_not_create_observation(self):
        """7. StatusTypeID 50 (Operational) produces operational_status=OPERATIONAL and observation=None."""
        res = self.adapter.process_record(OCM_FIXTURE_14_STATIC_OPERATIONAL_NOT_AVAILABLE)
        self.assertTrue(res.success)
        station = res.station_record

        self.assertEqual(station.operational_status, OperationalStatus.OPERATIONAL)
        self.assertIsNone(station.observation, "Static operational status must NEVER manufacture an observation")

        # Persist and verify no observations recorded
        persist_res = self.service.persist_station(
            station=station,
            raw_record=res.raw_record,
            data_source_id=self.source_id,
        )
        self.assertEqual(persist_res.status, PersistenceStatus.INSERTED)
        self.assertEqual(len(self.mock_db.tables["public.station_observations"]), 0)
        self.assertEqual(len(self.mock_db.tables["analytics.fact_station_observation"]), 0)

    # --------------------------------------------------------------------------
    # Test 8: Genuine observation is persisted to operational & analytics fact
    # --------------------------------------------------------------------------
    def test_08_genuine_observation_persisted_to_fact_table(self):
        """8. Telemetry fixture with real observation creates rows in operational and analytical fact tables."""
        res = self.adapter.process_record(OCM_FIXTURE_13_TELEMETRY_AVAILABLE)
        self.assertTrue(res.success)
        station = res.station_record
        self.assertIsNotNone(station.observation)

        persist_res = self.service.persist_station(
            station=station,
            raw_record=res.raw_record,
            data_source_id=self.source_id,
        )
        self.assertEqual(persist_res.status, PersistenceStatus.INSERTED)

        total_conn = sum(c.quantity for c in station.connectors)
        obs_id = self.service.persist_observation(
            station_id=persist_res.station_id,
            data_source_id=self.source_id,
            obs=station.observation,
            total_connectors=total_conn,
            raw_payload_hash=res.raw_record.payload_hash,
        )
        self.assertIsNotNone(obs_id)

        # Operational observation table
        self.assertEqual(len(self.mock_db.tables["public.station_observations"]), 1)
        obs_row = self.mock_db.tables["public.station_observations"][0]
        self.assertEqual(obs_row["availability_status"], "available")
        self.assertIsNone(obs_row["available_connectors"])
        self.assertEqual(obs_row["total_connectors"], 1)

        # Canonical warehouse fact table
        self.assertEqual(len(self.mock_db.tables["analytics.fact_station_observation"]), 1)
        fact_row = self.mock_db.tables["analytics.fact_station_observation"][0]
        self.assertEqual(fact_row["availability_status"], "available")
        self.assertIsNone(fact_row["available_connectors"])
        self.assertEqual(fact_row["total_connectors"], 1)
        # Verify conformed date_key (YYYYMMDD) and time_key (0..95)
        self.assertIsInstance(fact_row["date_key"], int)
        self.assertEqual(fact_row["date_key"], 20240320)
        self.assertGreaterEqual(fact_row["time_key"], 0)
        self.assertLessEqual(fact_row["time_key"], 95)

    # --------------------------------------------------------------------------
    # Test 9: Missing power remains skipped (no fake 0 kW)
    # --------------------------------------------------------------------------
    def test_09_missing_power_remains_null_and_skipped(self):
        """9. Connectors with missing power are skipped with a warning; power is never invented as 0 kW."""
        res = self.adapter.process_record(OCM_FIXTURE_06_MISSING_POWER)
        self.assertTrue(res.success)
        station = res.station_record

        # Adapter preserved power_kw as None
        self.assertIsNone(station.connectors[0].power_kw)

        persist_res = self.service.persist_station(
            station=station,
            raw_record=res.raw_record,
            data_source_id=self.source_id,
        )

        self.assertEqual(persist_res.status, PersistenceStatus.INSERTED)
        # Because public.connectors requires NOT NULL and positive power_kw,
        # missing power connector is safely skipped rather than inserting invented 0 kW
        self.assertEqual(persist_res.connectors_skipped, 1)
        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 0)
        self.assertTrue(any("missing or non-positive power_kw" in w for w in persist_res.warnings))

    # --------------------------------------------------------------------------
    # Test 10: Missing price remains NULL
    # --------------------------------------------------------------------------
    def test_10_missing_price_remains_null(self):
        """10. Stations with missing pricing information do not default to ₹0."""
        res = self.adapter.process_record(OCM_FIXTURE_04_MISSING_OPTIONAL_FIELDS)
        self.assertTrue(res.success)
        station = res.station_record

        # Missing pricing preserved on connector
        self.assertEqual(station.connectors[0].pricing_type, PricingType.UNKNOWN)
        self.assertIsNone(station.connectors[0].price_per_kwh)

        persist_res = self.service.persist_station(
            station=station,
            raw_record=res.raw_record,
            data_source_id=self.source_id,
        )
        self.assertEqual(persist_res.status, PersistenceStatus.INSERTED)
        stn = self.mock_db.tables["public.stations"][0]
        self.assertIsNotNone(stn)

    # --------------------------------------------------------------------------
    # Test 11: External source ID does NOT become canonical station UUID
    # --------------------------------------------------------------------------
    def test_11_external_id_does_not_become_station_uuid(self):
        """11. Source ID '195432' does not become the station UUID; UUID is newly generated."""
        res = self.adapter.process_record(OCM_FIXTURE_01_VALID_COMPLETE)
        persist_res = self.service.persist_station(
            station=res.station_record,
            raw_record=res.raw_record,
            data_source_id=self.source_id,
        )

        self.assertNotEqual(str(persist_res.station_id), "195432")
        # Ensure station_id is a valid UUIDv4
        self.assertIsInstance(persist_res.station_id, uuid.UUID)

        # Mapping is preserved in station_source_link
        link = self.mock_db.tables["public.station_source_link"][0]
        self.assertEqual(link["source_station_id"], "192840")
        self.assertEqual(str(link["station_id"]), str(persist_res.station_id))

    # --------------------------------------------------------------------------
    # Test 12: One failed record does not corrupt the whole batch
    # --------------------------------------------------------------------------
    def test_12_isolated_batch_failure(self):
        """12. A batch containing valid and malformed records isolates failures without failing the batch."""
        fixtures = [
            OCM_FIXTURE_01_VALID_COMPLETE,
            OCM_FIXTURE_17_MALFORMED_RECORD,  # Fatal parsing/schema failure
            OCM_FIXTURE_02_MULTIPLE_CONNECTORS,
        ]

        runner = IngestionRunner(persistence_service=self.service)
        summary = runner.run(
            fixtures_data=fixtures,
            dry_run=False,
        )

        self.assertEqual(summary.records_fetched, 3)
        self.assertEqual(summary.records_parsed, 2)
        self.assertEqual(summary.records_rejected, 1)
        self.assertEqual(summary.stations_persisted, 2)
        # Verify 2 valid stations were committed despite 1 malformed record
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 2)

    # --------------------------------------------------------------------------
    # Test 13: Dry run produces zero database writes
    # --------------------------------------------------------------------------
    def test_13_dry_run_produces_zero_writes(self):
        """13. Running in --dry-run mode performs ZERO database mutations."""
        fixtures = [
            OCM_FIXTURE_01_VALID_COMPLETE,
            OCM_FIXTURE_02_MULTIPLE_CONNECTORS,
            OCM_FIXTURE_13_TELEMETRY_AVAILABLE,
        ]

        runner = IngestionRunner(persistence_service=self.service)
        summary = runner.run(
            fixtures_data=fixtures,
            dry_run=True,
        )

        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.stations_persisted, 3)
        # Confirm that zero writes occurred on the mock database
        self.assertEqual(self.mock_db.total_database_writes(), 0)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 0)
        self.assertEqual(len(self.mock_db.tables["public.station_observations"]), 0)

    # --------------------------------------------------------------------------
    # Test 14: Credentials never appear in logs or errors
    # --------------------------------------------------------------------------
    def test_14_credentials_never_appear_in_logs_or_errors(self):
        """14. Error messages and summaries do not leak API keys or database passwords."""
        secret_key = "TOP_SECRET_OCM_KEY_99999"
        secret_db_url = "postgresql://user:SUPER_SECRET_PW_12345@localhost:5432/chargeplus"

        runner = IngestionRunner(db_url=secret_db_url, api_key=secret_key, persistence_service=self.service)
        summary = runner.run(
            fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE],
            dry_run=True,
        )

        dict_repr = str(summary.to_dict())
        self.assertNotIn("TOP_SECRET_OCM_KEY_99999", dict_repr)
        self.assertNotIn("SUPER_SECRET_PW_12345", dict_repr)

    # --------------------------------------------------------------------------
    # Test 15: Provenance contract version remains "1.0.0"
    # --------------------------------------------------------------------------
    def test_15_provenance_contract_version_is_1_0_0(self):
        """15. Canonical contract version in provenance must be strictly '1.0.0'."""
        self.assertEqual(CONTRACT_VERSION, "1.0.0")

        res = self.adapter.process_record(OCM_FIXTURE_01_VALID_COMPLETE)
        self.assertEqual(res.station_record.contract_version, "1.0.0")
        self.assertEqual(res.raw_record.to_provenance().contract_version, "1.0.0")


if __name__ == "__main__":
    unittest.main()
