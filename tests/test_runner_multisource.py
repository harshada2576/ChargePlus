"""Multi-source runner tests: OSM + data.gov.in through the canonical pipeline.

All execution is offline (in-memory fixtures, dry-run, no database). Live
transport is mocked at the requests level where fetch paths are exercised.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.ingestion.adapters.datagovin import DataGovInCredentialError
from backend.ingestion.persistence import IngestionPersistenceService
from backend.ingestion.runner import (
    ADAPTER_FACTORIES,
    SCHEDULED_BY_DEFAULT,
    SUPPORTED_SOURCES,
    IngestionRunner,
)
from backend.ingestion.scheduling import (
    IngestionRunState,
    RetryPolicy,
    ScheduleConfig,
    ScheduledIngestionOrchestrator,
)


OSM_FIXTURES = [
    {
        "type": "node",
        "id": 9001,
        "lat": 19.076,
        "lon": 72.877,
        "timestamp": "2024-03-15T10:00:00Z",
        "version": 2,
        "tags": {
            "amenity": "charging_station",
            "name": "OSM Test Hub",
            "operator": "Test Operator",
            "socket:type2": "2",
            "socket:type2:output": "22 kW",
            "addr:city": "Mumbai",
        },
    },
    {
        "type": "node",
        "id": 9002,
        "lat": 19.080,
        "lon": 72.880,
        "timestamp": "2024-04-01T10:00:00Z",
        "version": 1,
        "tags": {"amenity": "charging_station", "name": "OSM Minimal Point"},
    },
]

DATAGOVIN_FIXTURES = [
    {
        "id": "BEE-MH-101",
        "station_name": "Gov Test Station",
        "latitude": "19.076",
        "longitude": "72.877",
        "city": "Mumbai",
        "state": "Maharashtra",
        "connector_type": "CCS2",
        "power_kw": "60",
        "status": "operational",
    },
    {
        "id": "BEE-MH-102",
        "station_name": "Gov Minimal Station",
        "latitude": "19.080",
        "longitude": "72.880",
    },
]


def _offline_runner() -> IngestionRunner:
    # conn=None service: fully offline; dry-run adds zero-write guarantee.
    return IngestionRunner(persistence_service=IngestionPersistenceService(None))


class TestSourceRegistry:
    def test_01_supported_sources_registered(self):
        assert set(SUPPORTED_SOURCES) == {"open_charge_map", "osm", "datagovin"}
        for source_id, factory in ADAPTER_FACTORIES.items():
            assert factory().source_id == source_id

    def test_02_only_ocm_scheduled_by_default(self):
        assert SCHEDULED_BY_DEFAULT == frozenset({"open_charge_map"})
        assert _offline_runner().scheduled_sources == SCHEDULED_BY_DEFAULT

    def test_03_unknown_source_rejected(self):
        runner = _offline_runner()
        with pytest.raises(ValueError, match="Unknown ingestion source"):
            runner.run(fixtures_data=[], dry_run=True, source="plugshare")


class TestOsmThroughRunner:
    def test_10_osm_fixtures_dry_run(self):
        runner = _offline_runner()
        summary = runner.run(fixtures_data=OSM_FIXTURES, dry_run=True, source="osm")
        assert summary.source_id == "osm"
        assert summary.dry_run is True
        assert summary.records_fetched == 2
        assert summary.records_parsed == 2
        assert summary.records_accepted + summary.records_accepted_with_warnings == 2
        assert summary.records_rejected == 0
        # Dry-run reports what WOULD be persisted (conn=None: zero writes by
        # construction) — 2 new stations would be inserted.
        assert summary.stations_persisted == 2
        assert summary.observations_persisted == 0  # OSM: no live telemetry, ever

    def test_11_osm_rerun_deterministic(self):
        runner = _offline_runner()
        first = runner.run(fixtures_data=OSM_FIXTURES, dry_run=True, source="osm")
        second = runner.run(fixtures_data=OSM_FIXTURES, dry_run=True, source="osm")
        assert first.to_dict()["records_accepted"] == second.to_dict()["records_accepted"]
        assert first.stations_persisted == second.stations_persisted == 2

    def test_12_osm_nationwide_refused_without_bbox(self):
        runner = _offline_runner()
        with pytest.raises(ValueError, match="bounding box"):
            runner.run(dry_run=True, source="osm", mumbai_only=False)


class TestDataGovInThroughRunner:
    def test_20_datagovin_fixtures_dry_run(self):
        runner = _offline_runner()
        summary = runner.run(
            fixtures_data=DATAGOVIN_FIXTURES, dry_run=True, source="datagovin"
        )
        assert summary.source_id == "datagovin"
        assert summary.records_fetched == 2
        assert summary.records_parsed == 2
        assert summary.records_accepted + summary.records_accepted_with_warnings == 2
        assert summary.observations_persisted == 0  # no live telemetry, ever

    def test_21_datagovin_missing_credentials_fail_closed(self):
        import os

        runner = _offline_runner()
        key_backup = os.environ.pop("DATAGOVIN_API_KEY", None)
        res_backup = os.environ.pop("DATAGOVIN_RESOURCE_ID", None)
        try:
            with pytest.raises(DataGovInCredentialError, match="API key required"):
                runner.run(dry_run=True, source="datagovin", limit=5)
        finally:
            if key_backup:
                os.environ["DATAGOVIN_API_KEY"] = key_backup
            if res_backup:
                os.environ["DATAGOVIN_RESOURCE_ID"] = res_backup


class TestUnattendedSchedulingGuard:
    def _config(self, source, dry_run=False, fixtures=None):
        return ScheduleConfig(
            source_id=source, enabled=True, limit=5,
            scope="mumbai", dry_run=dry_run,
        ), fixtures

    def test_30_secondary_source_unattended_run_cancelled(self):
        runner = _offline_runner()
        orchestrator = ScheduledIngestionOrchestrator(runner=runner)
        config, _ = self._config("osm", dry_run=False)
        run = orchestrator.execute_scheduled_run(config, fixtures_data=None)
        assert run.state == IngestionRunState.CANCELLED
        assert "not enabled for unattended scheduling" in (run.error_summary or "")

    def test_31_secondary_source_manual_dry_run_allowed(self):
        runner = _offline_runner()
        orchestrator = ScheduledIngestionOrchestrator(runner=runner)
        config, _ = self._config("osm", dry_run=True)
        run = orchestrator.execute_scheduled_run(config, fixtures_data=OSM_FIXTURES)
        assert run.state in (IngestionRunState.SUCCEEDED, IngestionRunState.PARTIAL)
        assert run.source_id == "osm"
        assert run.records_fetched == 2

    def test_32_ocm_unattended_unaffected(self):
        runner = MagicMock()
        # MagicMock auto-creates persistence_service/conn attributes that look
        # like a busy Postgres lock — neutralize them for a hermetic run.
        runner.persistence_service = None
        runner.db_url = None
        runner.scheduled_sources = ("open_charge_map",)
        summary = MagicMock()
        summary.run_id = "run-1"
        summary.records_fetched = 0
        summary.records_parsed = 0
        summary.records_accepted = 0
        summary.records_accepted_with_warnings = 0
        summary.records_quarantined = 0
        summary.records_rejected = 0
        summary.stations_persisted = 0
        summary.stations_updated = 0
        summary.stations_unchanged = 0
        summary.stations_linked = 0
        summary.connectors_persisted = 0
        summary.observations_persisted = 0
        summary.persistence_errors = []
        runner.run.return_value = summary
        orchestrator = ScheduledIngestionOrchestrator(runner=runner)
        config = ScheduleConfig(source_id="open_charge_map", enabled=True, limit=1)
        run = orchestrator.execute_scheduled_run(config, fixtures_data=[])
        # Zero fetched records are indistinguishable from a source outage, so
        # the orchestrator reports PARTIAL (never SUCCEEDED on empty).
        assert run.state == IngestionRunState.PARTIAL
        assert "zero records" in (run.error_summary or "")

    def test_33_orchestrator_forwards_source_id(self):
        runner = MagicMock()
        runner.persistence_service = None
        runner.db_url = None
        summary = MagicMock()
        summary.run_id = None
        for field in (
            "records_fetched", "records_parsed", "records_accepted",
            "records_accepted_with_warnings", "records_quarantined",
            "records_rejected", "stations_persisted", "stations_updated",
            "stations_unchanged", "stations_linked", "connectors_persisted",
            "observations_persisted",
        ):
            setattr(summary, field, 0)
        summary.persistence_errors = []
        runner.run.return_value = summary
        runner.scheduled_sources = ("open_charge_map", "osm")
        orchestrator = ScheduledIngestionOrchestrator(runner=runner)
        config = ScheduleConfig(source_id="osm", enabled=True, limit=1, dry_run=True)
        orchestrator.execute_scheduled_run(config, fixtures_data=[])
        _, kwargs = runner.run.call_args
        assert kwargs.get("source") == "osm"


class TestRetryClassification:
    def test_40_credential_error_is_permanent(self):
        policy = RetryPolicy()
        assert (
            policy.classify_exception(DataGovInCredentialError("no key")).value
            == "PERMANENT"
        )

    def test_41_rate_limit_message_is_transient(self):
        from backend.ingestion.scheduling import FailureClassification

        policy = RetryPolicy()
        assert (
            policy.classify_exception(RuntimeError("Upstream rate limit exceeded")).value
            == FailureClassification.TRANSIENT.value
        )


class TestDataGovInResume:
    def test_50_start_offset_resumes_pagination(self):
        from backend.ingestion.adapters.datagovin import DataGovInAdapter

        first = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"records": [DATAGOVIN_FIXTURES[0]]}),
        )
        second = MagicMock(
            status_code=200, json=MagicMock(return_value={"records": []})
        )
        adapter = DataGovInAdapter(api_key="k", resource_id="r")
        with patch("requests.get", side_effect=[first, second]) as mock_get:
            records = adapter.fetch_raw(page_size=1, max_records=5, start_offset=10)
        assert len(records) == 1
        _, first_kwargs = mock_get.call_args_list[0]
        assert first_kwargs["params"]["offset"] == 10
