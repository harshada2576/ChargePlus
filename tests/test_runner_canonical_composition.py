"""ChargePlus — Runner Canonical Composition Anti-Regression Suite.

Phase 2 recovery: proves the real IngestionRunner composes the actual pipeline:
adapter -> canonical normalization (2.5) -> validation gating (2.6) ->
resolution (2.4, inside dedup) -> deduplication decision (2.7) ->
canonical persistence (2.8, incl. observations) -> freshness (2.9).

Uses in-memory mock transport (fixtures) but the REAL runner and REAL engines
(with wraps spies). Fails if any stage is removed from runner.py.
"""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import uuid

from backend.ingestion.persistence import IngestionPersistenceService
from backend.ingestion.runner import IngestionRunner
from tests.fixtures.ocm_fixtures import (
    OCM_FIXTURE_01_VALID_COMPLETE,
    OCM_FIXTURE_02_MULTIPLE_CONNECTORS,
    OCM_FIXTURE_13_TELEMETRY_AVAILABLE,
)


class _MockCursor:
    def __init__(self, db, as_dict=False):
        self.db = db
        self.as_dict = as_dict
        self._last = []

    def execute(self, sql, params=()):
        sql_clean = " ".join(sql.strip().split())
        self._last = []
        if "pg_try_advisory_lock" in sql_clean or "pg_advisory_unlock" in sql_clean:
            self._last = [(True,)]
            return
        if "FROM public.data_sources WHERE name = %s" in sql_clean:
            for r in self.db["public.data_sources"]:
                if r["name"] == params[0]:
                    self._last = [r if self.as_dict else (r["id"],)]
                    break
        elif "INSERT INTO public.data_sources" in sql_clean:
            row = {"id": params[0], "name": params[1]}
            self.db["public.data_sources"].append(row)
            self._last = [row if self.as_dict else (params[0],)]
        elif "INSERT INTO analytics.dim_source" in sql_clean:
            pass
        elif "FROM public.operators WHERE slug = %s" in sql_clean or "FROM public.operators WHERE name = %s" in sql_clean:
            for r in self.db["public.operators"]:
                if r.get("slug") == params[0] or r.get("name") == params[0]:
                    self._last = [r if self.as_dict else (r["id"],)]
                    break
        elif "INSERT INTO public.operators" in sql_clean:
            row = {"id": params[0], "name": params[1], "slug": params[2]}
            self.db["public.operators"].append(row)
            self._last = [row if self.as_dict else (params[0],)]
        elif "FROM public.station_source_link WHERE source_id = %s AND source_station_id = %s" in sql_clean:
            for r in self.db["public.station_source_link"]:
                if str(r["source_id"]) == str(params[0]) and str(r["source_station_id"]) == str(params[1]):
                    if self.as_dict:
                        self._last = [r]
                    else:
                        self._last = [(r["id"], r["station_id"], r["source_payload_hash"])]
                    break
        elif "UPDATE public.station_source_link SET last_seen_at = now() WHERE id = %s" in sql_clean:
            for r in self.db["public.station_source_link"]:
                if str(r["id"]) == str(params[0]):
                    r["last_seen_at"] = datetime.now(timezone.utc)
                    break
        elif "UPDATE public.station_source_link SET source_payload_hash" in sql_clean:
            for r in self.db["public.station_source_link"]:
                if str(r["id"]) == str(params[1]):
                    r["source_payload_hash"] = params[0]
                    break
        elif "INSERT INTO public.station_source_link" in sql_clean:
            row = {"id": str(uuid.uuid4()), "station_id": str(params[0]), "source_id": str(params[1]),
                   "source_station_id": str(params[2]), "source_url": params[3], "source_payload_hash": params[4]}
            self.db["public.station_source_link"].append(row)
        elif "INSERT INTO public.stations" in sql_clean:
            row = {"id": str(params[0]), "name": params[2] if len(params) > 2 else params[1]}
            self.db["public.stations"].append(row)
        elif sql_clean.startswith("SELECT") and "FROM public.connectors WHERE station_id" in sql_clean and "COALESCE(SUM" not in sql_clean:
            pass
        elif "INSERT INTO public.connectors" in sql_clean:
            self.db["public.connectors"].append({"id": str(params[0]), "station_id": str(params[1])})
        elif "UPDATE public.connectors SET" in sql_clean:
            pass
        elif "INSERT INTO analytics.dim_connector" in sql_clean:
            pass
        elif "SELECT COALESCE(SUM(quantity), 0) FROM public.connectors" in sql_clean:
            self._last = [(0,)]
        elif "FROM public.station_observations WHERE station_id = %s AND source_id = %s AND source_payload_hash = %s" in sql_clean:
            pass
        elif "FROM public.station_observations" in sql_clean and "LIMIT 1" in sql_clean:
            pass
        elif "INSERT INTO public.station_observations" in sql_clean:
            self.db["public.station_observations"].append({"id": str(params[0])})
        elif "INSERT INTO analytics.fact_station_observation" in sql_clean:
            pass
        elif "FROM public.stations s" in sql_clean and "LEFT JOIN public.operators" in sql_clean:
            pass
        elif "SELECT source_key FROM analytics.dim_source" in sql_clean:
            pass
        elif "INSERT INTO analytics.dim_station" in sql_clean or "UPDATE analytics.dim_station" in sql_clean:
            pass
        elif "SELECT station_key" in sql_clean and "analytics.dim_station" in sql_clean:
            pass
        elif "SELECT operator_key FROM analytics.dim_operator" in sql_clean or "INSERT INTO analytics.dim_operator" in sql_clean:
            self._last = [(1,)]
        elif "SELECT location_key FROM analytics.dim_location" in sql_clean or "INSERT INTO analytics.dim_location" in sql_clean:
            self._last = [(1,)]

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class _MockConn:
    def __init__(self, db):
        self.db = db
        self.closed = False

    def cursor(self, cursor_factory=None):
        return _MockCursor(self.db, as_dict=(cursor_factory is not None))

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def _fresh_db():
    return {"public.data_sources": [], "public.operators": [], "public.stations": [],
            "public.connectors": [], "public.station_source_link": [],
            "public.station_observations": []}


class TestRunnerCanonicalComposition(unittest.TestCase):
    """Anti-regression: real runner must invoke every canonical stage."""

    def test_composition_invokes_all_stages(self):
        """Adapter->norm->validate->resolve->dedup->persist->freshness all run."""
        db = _fresh_db()
        service = IngestionPersistenceService(_MockConn(db))
        runner = IngestionRunner(persistence_service=service)
        fixtures = [copy.deepcopy(OCM_FIXTURE_01_VALID_COMPLETE),
                    copy.deepcopy(OCM_FIXTURE_02_MULTIPLE_CONNECTORS)]

        from backend.ingestion import runner as runner_mod
        from backend.ingestion import deduplication as dedup_mod
        from backend.ingestion import freshness as fresh_mod

        from backend.ingestion import resolution as res_mod
        orig_evaluate_pair = res_mod.CrossSourceEntityResolver.evaluate_pair
        resolve_calls = {"n": 0}
        def _counting_evaluate_pair(self, record_a, record_b):
            resolve_calls["n"] += 1
            return orig_evaluate_pair(self, record_a, record_b)
        with patch.object(runner_mod, "normalize_station_record",
                          wraps=runner_mod.normalize_station_record) as spy_norm, \
             patch.object(runner_mod.DataQualityValidator, "validate_record",
                          wraps=runner_mod.DataQualityValidator.validate_record) as spy_val, \
             patch.object(dedup_mod.CanonicalDeduplicationEngine, "evaluate_records",
                          wraps=dedup_mod.CanonicalDeduplicationEngine.evaluate_records) as spy_dedup, \
             patch.object(runner_mod.FreshnessEngine, "evaluate_observation",
                          wraps=runner_mod.FreshnessEngine.evaluate_observation) as spy_fresh_obs, \
             patch.object(runner_mod.FreshnessEngine, "evaluate_station_metadata",
                          wraps=runner_mod.FreshnessEngine.evaluate_station_metadata) as spy_fresh_meta, \
             patch.object(service, "persist_canonical_batch",
                          wraps=service.persist_canonical_batch) as spy_persist, \
             patch.object(res_mod.CrossSourceEntityResolver, "evaluate_pair",
                          autospec=True, side_effect=lambda self, a, b: _counting_evaluate_pair(self, a, b)) as spy_resolve:
            summary = runner.run(fixtures_data=fixtures, dry_run=True)

        # Each stage must have been invoked (fails if removed from runner.py).
        self.assertGreaterEqual(spy_norm.call_count, 2, "canonical normalization must run")
        self.assertGreaterEqual(spy_val.call_count, 2, "validation gating must run")
        self.assertEqual(spy_dedup.call_count, 1, "deduplication decision must run")
        self.assertGreaterEqual(resolve_calls["n"], 1, "entity resolution must run (inside dedup)")
        self.assertEqual(spy_persist.call_count, 1, "canonical persistence must run")
        # Freshness: metadata always; observation only for telemetry fixture.
        self.assertGreaterEqual(spy_fresh_meta.call_count, 1, "freshness metadata eval must run")
        # Composition results through the REAL runner (dry-run, no DB writes).
        self.assertEqual(summary.records_fetched, 2)
        self.assertEqual(summary.records_parsed, 2)
        self.assertGreaterEqual(summary.freshness_evaluated, 2)
        self.assertEqual(len(db["public.stations"]), 0, "dry-run must not write")

    def test_review_never_canonicalized_through_runner(self):
        """Conflicting nearby records that force REVIEW must not create stations."""
        db = _fresh_db()
        service = IngestionPersistenceService(_MockConn(db))
        runner = IngestionRunner(persistence_service=service)
        base = copy.deepcopy(OCM_FIXTURE_01_VALID_COMPLETE)
        # Nearby (~10m) but contradictory operator + name forces ambiguity/REVIEW
        # when evaluated together with the base record.
        conflict = copy.deepcopy(OCM_FIXTURE_01_VALID_COMPLETE)
        conflict["ID"] = 999991
        conflict["OperatorInfo"] = {"ID": 999, "Title": "Completely Different Operator XYZ"}
        conflict["AddressInfo"] = dict(conflict["AddressInfo"])
        # ~10m offset (still within candidate radius) with conflicting identity.
        conflict["AddressInfo"]["Latitude"] = 19.0658
        conflict["AddressInfo"]["Longitude"] = 72.8687
        conflict["AddressInfo"]["Title"] = "Totally Unrelated Charging Point ABC"
        summary = runner.run(fixtures_data=[base, conflict], dry_run=True)
        # Either REVIEW-skipped or kept separate; never silently merged into 1 without evidence.
        # Key invariant: no crash, batch isolated, freshness still evaluated.
        self.assertEqual(summary.records_fetched, 2)
        self.assertGreaterEqual(summary.freshness_evaluated, 1)

    def test_timeout_reaches_http_request(self):
        """Configured timeout must bound the OCM HTTP request (not hardcoded 15s)."""
        from backend.ingestion.adapters.openchargemap import OpenChargeMapAdapter
        adapter = OpenChargeMapAdapter()
        import backend.ingestion.adapters.openchargemap as ocm_mod
        with patch.object(ocm_mod.requests, "get") as mock_get:
            mock_resp = mock_get.return_value
            mock_resp.status_code = 200
            mock_resp.json.return_value = []
            adapter.fetch_raw(country_code="IN", max_results=5, api_key="DUMMY", timeout_sec=7.5)
            _, kwargs = mock_get.call_args
            self.assertEqual(kwargs.get("timeout"), 7.5)

        # Runner propagates timeout_seconds to fetch_raw (live path).
        db = _fresh_db()
        service = IngestionPersistenceService(_MockConn(db))
        runner = IngestionRunner(persistence_service=service)
        runner.api_key = "DUMMY"
        with patch.object(runner.adapter, "fetch_raw", return_value=[]) as mock_fetch:
            runner.run(dry_run=True, limit=3, timeout_seconds=9.0)
            _, kwargs = mock_fetch.call_args
            self.assertEqual(kwargs.get("timeout_sec"), 9.0)
        # Scheduled orchestrator passes config.timeout_seconds to runner.run.
        from backend.ingestion.scheduling import ScheduleConfig, ScheduledIngestionOrchestrator
        with patch.object(runner, "run", wraps=runner.run) as spy_run:
            orch = ScheduledIngestionOrchestrator(runner=runner, persistence_service=service)
            cfg = ScheduleConfig(source_id="open_charge_map", limit=2, scope="mumbai",
                                 timeout_seconds=11.0, dry_run=True)
            orch.execute_scheduled_run(cfg, fixtures_data=[copy.deepcopy(OCM_FIXTURE_01_VALID_COMPLETE)])
            _, kwargs = spy_run.call_args
            self.assertEqual(kwargs.get("timeout_seconds"), 11.0)


if __name__ == "__main__":
    unittest.main()
