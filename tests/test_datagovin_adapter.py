"""Tests for the data.gov.in adapter.

All tests use offline fixtures only. Network calls are mocked at the requests level.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.ingestion.adapters.datagovin import (
    DataGovInAdapter,
    DataGovInCredentialError,
)
from backend.ingestion.constants import (
    AvailabilityStatus,
    OperationalStatus,
    StandardConnectorType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FULL_STATION = {
    "id": "BEE-MH-001",
    "station_name": "MSEDCL BKC Charging Hub",
    "operator": "MSEDCL",
    "latitude": "19.0651",
    "longitude": "72.8680",
    "address": "BKC, Bandra East",
    "city": "Mumbai",
    "state": "Maharashtra",
    "pincode": "400051",
    "connector_type": "CCS2",
    "power_kw": "120",
    "number_of_connectors": "4",
    "status": "operational",
}

MINIMAL_STATION = {
    "_id": "abc-123",
    "latitude": "19.076",
    "longitude": "72.879",
}

STATION_WITH_TYPE2 = {
    "id": "BEE-MH-002",
    "station_name": "Type 2 Hub",
    "operator": "Tata Power",
    "latitude": "19.080",
    "longitude": "72.870",
    "connector_type": "Type 2",
    "power_kw": "22",
    "status": "active",
}

STATION_NO_COORDS = {
    "id": "BEE-MH-003",
    "station_name": "No Coords Station",
    "city": "Mumbai",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDataGovInAdapter:

    def setup_method(self):
        self.adapter = DataGovInAdapter(
            api_key="test-api-key-placeholder",
            resource_id="test-resource-id",
        )

    # --- basic properties ---

    def test_01_source_id_is_datagovin(self):
        assert self.adapter.source_id == "datagovin"

    def test_02_source_priority_set(self):
        assert isinstance(self.adapter.source_priority, int)
        assert 1 <= self.adapter.source_priority <= 100

    # --- extract_source_station_id ---

    def test_03_extract_id_from_id_field(self):
        sid = self.adapter.extract_source_station_id({"id": "BEE-MH-001"})
        assert "BEE-MH-001" in sid

    def test_04_extract_id_from_underscore_id(self):
        sid = self.adapter.extract_source_station_id({"_id": "abc-123"})
        assert "abc-123" in sid

    def test_05_extract_id_fallback_to_geo(self):
        sid = self.adapter.extract_source_station_id({"latitude": "19.076", "longitude": "72.879"})
        assert "geo" in sid.lower()

    def test_06_extract_id_raises_when_no_id_no_coords(self):
        with pytest.raises(ValueError, match="no identifiable ID"):
            self.adapter.extract_source_station_id({"station_name": "Test"})

    # --- normalize_station ---

    def test_07_normalize_full_station(self):
        result = self.adapter.process_record(FULL_STATION)
        assert result.success, result.errors
        station = result.station_record
        assert "MSEDCL BKC Charging Hub" in station.name
        assert abs(station.latitude - 19.0651) < 0.001
        assert abs(station.longitude - 72.8680) < 0.001

    def test_08_normalize_preserves_city_state(self):
        result = self.adapter.process_record(FULL_STATION)
        assert result.success
        assert result.station_record.city == "Mumbai"
        assert result.station_record.state == "Maharashtra"

    def test_09_normalize_infers_city_when_missing(self):
        result = self.adapter.process_record(MINIMAL_STATION)
        assert result.success
        assert result.station_record.city == "Mumbai"
        assert result.station_record.extra_metadata.get("city_inferred") is True

    def test_10_connector_type_ccs2_mapped(self):
        result = self.adapter.process_record(FULL_STATION)
        assert result.success
        conn = result.station_record.connectors[0]
        assert conn.connector_type == StandardConnectorType.CCS2.value

    def test_11_connector_type_type2_mapped(self):
        result = self.adapter.process_record(STATION_WITH_TYPE2)
        assert result.success
        conn = result.station_record.connectors[0]
        assert conn.connector_type == StandardConnectorType.TYPE_2.value

    def test_12_power_extracted(self):
        result = self.adapter.process_record(FULL_STATION)
        assert result.success
        conn = result.station_record.connectors[0]
        assert conn.power_kw == 120.0

    def test_13_connector_count_extracted(self):
        result = self.adapter.process_record(FULL_STATION)
        assert result.success
        conn = result.station_record.connectors[0]
        assert conn.quantity == 4

    def test_14_no_live_telemetry(self):
        result = self.adapter.process_record(FULL_STATION)
        assert result.success
        assert result.station_record.observation is None

    def test_15_connector_status_always_unknown(self):
        result = self.adapter.process_record(FULL_STATION)
        assert result.success
        for c in result.station_record.connectors:
            assert c.status == AvailabilityStatus.UNKNOWN

    def test_16_operational_status_from_status_field(self):
        result = self.adapter.process_record(FULL_STATION)
        assert result.success
        assert result.station_record.operational_status == OperationalStatus.OPERATIONAL

    def test_17_permanently_closed_status(self):
        station = dict(FULL_STATION, status="closed")
        result = self.adapter.process_record(station)
        assert result.success
        assert result.station_record.operational_status == OperationalStatus.PERMANENTLY_CLOSED

    def test_18_unknown_status_when_field_absent(self):
        result = self.adapter.process_record(MINIMAL_STATION)
        assert result.success
        assert result.station_record.operational_status == OperationalStatus.UNKNOWN

    def test_19_missing_coords_causes_failure(self):
        result = self.adapter.process_record(STATION_NO_COORDS)
        assert not result.success
        assert any("coordinates" in e.lower() or "lat" in e.lower() for e in result.errors)

    def test_20_payload_hash_populated(self):
        result = self.adapter.process_record(FULL_STATION)
        assert result.success
        assert result.station_record.raw_payload_hash
        assert len(result.station_record.raw_payload_hash) == 64

    def test_21_idempotent_repeated_import(self):
        r1 = self.adapter.process_record(FULL_STATION)
        r2 = self.adapter.process_record(FULL_STATION)
        assert r1.success and r2.success
        assert r1.station_record.raw_payload_hash == r2.station_record.raw_payload_hash

    def test_22_attribution_in_metadata(self):
        result = self.adapter.process_record(FULL_STATION)
        assert result.success
        meta = result.station_record.extra_metadata
        assert "data.gov.in" in meta.get("attribution", "")

    # --- credential errors ---

    def test_23_fetch_raw_without_api_key_raises_credential_error(self):
        # Remove env var influence BEFORE constructing: __init__ captures
        # DATAGOVIN_API_KEY at construction time (and IngestionRunner
        # load_dotenv(".env.local") may have injected a placeholder value
        # when other test files ran first in the same process).
        import os
        env_backup = os.environ.pop("DATAGOVIN_API_KEY", None)
        try:
            adapter_no_key = DataGovInAdapter(api_key=None, resource_id="r1")
            with pytest.raises(DataGovInCredentialError, match="API key required"):
                adapter_no_key.fetch_raw()
        finally:
            if env_backup:
                os.environ["DATAGOVIN_API_KEY"] = env_backup

    def test_24_fetch_raw_without_resource_id_raises_credential_error(self):
        # Same construction-before-pop ordering guard as test_23.
        import os
        env_backup = os.environ.pop("DATAGOVIN_RESOURCE_ID", None)
        try:
            adapter_no_res = DataGovInAdapter(api_key="key", resource_id=None)
            with pytest.raises(DataGovInCredentialError, match="resource_id not configured"):
                adapter_no_res.fetch_raw()
        finally:
            if env_backup:
                os.environ["DATAGOVIN_RESOURCE_ID"] = env_backup

    # --- network mocking ---

    def test_25_fetch_raw_parses_records_field(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": [FULL_STATION, STATION_WITH_TYPE2],
            "total": 2,
        }

        with patch("requests.get", return_value=mock_response):
            records = self.adapter.fetch_raw()
        assert len(records) == 2

    def test_26_fetch_raw_handles_401(self):
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(DataGovInCredentialError, match="authentication failed"):
                self.adapter.fetch_raw()

    def test_27_fetch_raw_handles_404(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(DataGovInCredentialError, match="not found"):
                self.adapter.fetch_raw()

    def test_28_fetch_raw_handles_429(self):
        mock_response = MagicMock()
        mock_response.status_code = 429
        # Small Retry-After keeps retry-exhaustion fast; honoring of larger
        # values is covered by the shared transport tests in
        # test_source_transport_retry.py.
        mock_response.headers = {"Retry-After": "1"}

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(RuntimeError, match="rate limit"):
                self.adapter.fetch_raw()

    def test_29_fetch_raw_handles_500(self):
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(RuntimeError, match="server error"):
                self.adapter.fetch_raw()

    def test_30_fetch_raw_handles_timeout(self):
        import requests as req
        with patch("requests.get", side_effect=req.exceptions.Timeout("timeout")):
            with pytest.raises(TimeoutError):
                self.adapter.fetch_raw()

    def test_31_fetch_raw_pagination_stops_on_empty_page(self):
        responses = [
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={"records": [FULL_STATION]}),
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={"records": []}),
            ),
        ]

        with patch("requests.get", side_effect=responses):
            records = self.adapter.fetch_raw(page_size=1)
        assert len(records) == 1

    def test_32_fetch_raw_geo_filter_excludes_out_of_bbox(self):
        in_bbox = dict(FULL_STATION, latitude="19.076", longitude="72.879")
        out_bbox = dict(FULL_STATION, id="out", latitude="13.0", longitude="80.0")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"records": [in_bbox, out_bbox]}

        with patch("requests.get", return_value=mock_response):
            records = self.adapter.fetch_raw(
                lat_min=18.70, lng_min=72.70, lat_max=19.50, lng_max=73.30
            )
        # Only the in-bbox record should be returned
        lats = [float(r.get("latitude", 0)) for r in records]
        assert all(18.70 <= lat <= 19.50 for lat in lats)

    def test_33_batch_processing(self):
        payloads = [FULL_STATION, STATION_WITH_TYPE2, STATION_NO_COORDS]
        result = self.adapter.process_batch(payloads)
        assert result.total_records == 3
        assert result.successful_records == 2
        assert result.failed_records == 1
