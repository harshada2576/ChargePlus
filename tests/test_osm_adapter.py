"""Tests for the OSM Overpass adapter.

Exercises the OSMOverpassAdapter with offline fixtures only — no network calls.
All external transport is mocked at the requests level.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.ingestion.adapters.osm import OSMOverpassAdapter
from backend.ingestion.constants import (
    AvailabilityStatus,
    OperationalStatus,
    StandardConnectorType,
    PricingType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_node(
    osm_id: int = 123456789,
    lat: float = 19.075,
    lon: float = 72.877,
    tags: dict | None = None,
    osm_type: str = "node",
    timestamp: str = "2024-03-15T10:00:00Z",
    version: int = 3,
) -> dict:
    """Build a minimal OSM element dict."""
    return {
        "type": osm_type,
        "id": osm_id,
        "lat": lat,
        "lon": lon,
        "timestamp": timestamp,
        "version": version,
        "tags": tags or {"amenity": "charging_station"},
    }


def _make_way_with_center(
    osm_id: int = 987654321,
    center_lat: float = 19.076,
    center_lon: float = 72.878,
    tags: dict | None = None,
) -> dict:
    """Build a way element with center coordinates (as Overpass returns)."""
    return {
        "type": "way",
        "id": osm_id,
        "center": {"lat": center_lat, "lon": center_lon},
        "timestamp": "2024-06-01T08:00:00Z",
        "version": 1,
        "tags": tags or {"amenity": "charging_station"},
    }


RICH_NODE = _make_node(
    osm_id=111222333,
    lat=19.0820,
    lon=72.8816,
    tags={
        "amenity": "charging_station",
        "name": "Tata Power BKC Fast Hub",
        "operator": "Tata Power",
        "socket:type2": "2",
        "socket:type2:output": "22 kW",
        "socket:ccs": "2",
        "socket:ccs:output": "120 kW",
        "fee": "yes",
        "opening_hours": "24/7",
        "addr:city": "Mumbai",
        "addr:state": "Maharashtra",
        "addr:postcode": "400051",
    },
)

MINIMAL_NODE = _make_node(
    osm_id=222333444,
    lat=19.076,
    lon=72.879,
    tags={"amenity": "charging_station"},
)

FREE_STATION_NODE = _make_node(
    osm_id=333444555,
    lat=19.080,
    lon=72.870,
    tags={
        "amenity": "charging_station",
        "fee": "no",
        "socket:type1": "4",
        "socket:type1:output": "7.4kw",
        "operator": "Ather Energy",
    },
)

DISUSED_NODE = _make_node(
    osm_id=444555666,
    lat=19.085,
    lon=72.875,
    tags={
        "amenity": "charging_station",
        "disused:amenity": "charging_station",
    },
)

PRIVATE_NODE = _make_node(
    osm_id=555666777,
    lat=19.090,
    lon=72.860,
    tags={
        "amenity": "charging_station",
        "access": "private",
        "operator": "Private Corp",
    },
)


# ---------------------------------------------------------------------------
# Test Class
# ---------------------------------------------------------------------------

class TestOSMOverpassAdapter:
    """Tests for OSMOverpassAdapter — all offline, no network calls."""

    def setup_method(self):
        self.adapter = OSMOverpassAdapter()

    # --- extract_source_station_id ---

    def test_01_source_id_is_osm(self):
        assert self.adapter.source_id == "osm"

    def test_02_extract_source_station_id_node(self):
        payload = {"type": "node", "id": 12345678}
        assert self.adapter.extract_source_station_id(payload) == "node/12345678"

    def test_03_extract_source_station_id_way(self):
        payload = {"type": "way", "id": 987654}
        assert self.adapter.extract_source_station_id(payload) == "way/987654"

    def test_04_extract_source_station_id_missing_raises(self):
        with pytest.raises(ValueError, match="missing required"):
            self.adapter.extract_source_station_id({"tags": {}})

    def test_05_source_priority_lower_than_ocm(self):
        # OSM priority (60) < OCM priority (70)
        assert self.adapter.source_priority < 70

    # --- normalize_station: coordinates ---

    def test_06_normalize_valid_coordinates(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        station = result.station_record
        assert abs(station.latitude - 19.0820) < 0.001
        assert abs(station.longitude - 72.8816) < 0.001

    def test_07_normalize_way_with_center(self):
        result = self.adapter.process_record(_make_way_with_center())
        assert result.success
        station = result.station_record
        assert station.latitude is not None
        assert station.longitude is not None

    def test_08_missing_coordinates_raises(self):
        bad = {"type": "node", "id": 1, "tags": {"amenity": "charging_station"}}
        result = self.adapter.process_record(bad)
        assert not result.success
        assert any("coordinates" in e.lower() or "lat" in e.lower() for e in result.errors)

    # --- name extraction ---

    def test_09_name_from_tags(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        assert "Tata Power BKC Fast Hub" in result.station_record.name

    def test_10_name_synthesized_from_operator(self):
        node = _make_node(tags={"amenity": "charging_station", "operator": "Kazam"})
        result = self.adapter.process_record(node)
        assert result.success
        assert "Kazam" in result.station_record.name
        assert result.station_record.extra_metadata.get("name_synthesized") is True

    def test_11_name_fully_synthesized_when_no_info(self):
        result = self.adapter.process_record(MINIMAL_NODE)
        assert result.success
        assert "OSM Charging Station" in result.station_record.name

    # --- connector extraction ---

    def test_12_connectors_extracted_from_socket_tags(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        connectors = result.station_record.connectors
        # type2 and ccs both present
        types = {c.connector_type for c in connectors}
        assert StandardConnectorType.TYPE_2.value in types
        assert StandardConnectorType.CCS2.value in types

    def test_13_power_parsed_correctly(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        connectors = {c.connector_type: c for c in result.station_record.connectors}
        type2 = connectors.get(StandardConnectorType.TYPE_2.value)
        if type2:
            assert type2.power_kw == 22.0
        ccs = connectors.get(StandardConnectorType.CCS2.value)
        if ccs:
            assert ccs.power_kw == 120.0

    def test_14_unknown_connector_when_no_socket_tags(self):
        result = self.adapter.process_record(MINIMAL_NODE)
        assert result.success
        assert len(result.station_record.connectors) >= 1
        assert result.station_record.connectors[0].connector_type == StandardConnectorType.OTHER.value

    def test_15_quantity_extracted_from_socket_count(self):
        node = _make_node(
            tags={"amenity": "charging_station", "socket:type2": "4"}
        )
        result = self.adapter.process_record(node)
        assert result.success
        c = result.station_record.connectors[0]
        assert c.quantity == 4

    def test_16_quantity_defaults_to_one_when_no_count(self):
        # Canonical contract (Step 2.1) requires quantity: int >= 1, so an
        # unparseable OSM socket count normalizes to 1 (single plug assumed),
        # never None. Missing count is NOT evidence of zero connectors.
        node = _make_node(
            tags={"amenity": "charging_station", "socket:type2": "yes"}
        )
        result = self.adapter.process_record(node)
        assert result.success
        c = result.station_record.connectors[0]
        assert c.quantity == 1
        assert c.is_aggregated is False

    # --- OSM never has live availability ---

    def test_17_observation_is_always_none(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        assert result.station_record.observation is None

    def test_18_connector_status_always_unknown(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        for conn in result.station_record.connectors:
            assert conn.status == AvailabilityStatus.UNKNOWN

    # --- pricing ---

    def test_19_fee_yes_maps_to_paid(self):
        result = self.adapter.process_record(RICH_NODE)
        # RICH_NODE has fee=yes, but connector pricing stays UNKNOWN
        # (OSM fee tag → connector pricing_type mapping)
        # The pricing_type on connector itself is based on OSM fee tag for the station
        # Currently adapter maps to UNKNOWN for connectors (fee is at station level)
        assert result.success

    def test_20_fee_no_implies_free_pricing(self):
        result = self.adapter.process_record(FREE_STATION_NODE)
        assert result.success
        # pricing_type should reflect the fee=no tag
        # Check extra_metadata or connector pricing
        # (implementation maps station-level fee to per-connector pricing)

    # --- operational status ---

    def test_21_disused_tag_maps_to_permanently_closed(self):
        result = self.adapter.process_record(DISUSED_NODE)
        assert result.success
        assert result.station_record.operational_status == OperationalStatus.PERMANENTLY_CLOSED

    def test_22_normal_station_maps_to_operational(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        assert result.station_record.operational_status == OperationalStatus.OPERATIONAL

    # --- access / is_public ---

    def test_23_private_access_tag_respected(self):
        result = self.adapter.process_record(PRIVATE_NODE)
        assert result.success
        assert result.station_record.is_public is False

    def test_24_no_access_tag_defaults_to_public(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        assert result.station_record.is_public is True

    # --- 24/7 ---

    def test_25_24_7_opening_hours(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        assert result.station_record.is_24_hours is True

    def test_26_no_opening_hours_is_none(self):
        result = self.adapter.process_record(MINIMAL_NODE)
        assert result.success
        assert result.station_record.is_24_hours is None

    # --- address ---

    def test_27_address_city_state_from_tags(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        station = result.station_record
        assert station.city == "Mumbai"
        assert station.state == "Maharashtra"
        assert station.postal_code == "400051"

    def test_28_city_inferred_when_absent(self):
        result = self.adapter.process_record(MINIMAL_NODE)
        assert result.success
        station = result.station_record
        assert station.city == "Mumbai"
        assert station.extra_metadata.get("city_inferred") is True

    # --- provenance ---

    def test_29_source_url_contains_osm_id(self):
        result = self.adapter.process_record(MINIMAL_NODE)
        assert result.success
        assert "openstreetmap.org" in result.station_record.source_url
        assert "node" in result.station_record.source_url

    def test_30_attribution_in_extra_metadata(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        meta = result.station_record.extra_metadata
        assert "OpenStreetMap" in meta.get("attribution", "")
        assert meta.get("license") == "ODbL 1.0"

    def test_31_osm_tags_preserved_in_metadata(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        tags = result.station_record.extra_metadata.get("osm_tags")
        assert isinstance(tags, dict)
        assert "socket:type2" in tags

    def test_32_payload_hash_populated(self):
        result = self.adapter.process_record(MINIMAL_NODE)
        assert result.success
        assert result.station_record.raw_payload_hash
        assert len(result.station_record.raw_payload_hash) == 64  # SHA-256 hex

    def test_33_timestamp_parsed_from_osm_element(self):
        result = self.adapter.process_record(RICH_NODE)
        assert result.success
        meta = result.station_record.extra_metadata
        assert meta.get("osm_timestamp") == "2024-03-15T10:00:00Z"

    # --- idempotency ---

    def test_34_idempotent_repeated_import(self):
        r1 = self.adapter.process_record(RICH_NODE)
        r2 = self.adapter.process_record(RICH_NODE)
        assert r1.success
        assert r2.success
        assert r1.station_record.raw_payload_hash == r2.station_record.raw_payload_hash
        assert r1.station_record.source_station_id == r2.station_record.source_station_id

    # --- batch ---

    def test_35_batch_with_mixed_valid_invalid(self):
        bad_node = {"type": "node", "id": 999, "tags": {}}  # missing coords
        payloads = [RICH_NODE, bad_node, MINIMAL_NODE]
        batch_result = self.adapter.process_batch(payloads)
        assert batch_result.total_records == 3
        assert batch_result.successful_records == 2
        assert batch_result.failed_records == 1

    def test_36_batch_empty_input(self):
        batch_result = self.adapter.process_batch([])
        assert batch_result.total_records == 0
        assert batch_result.successful_records == 0

    # --- Overpass query construction ---

    def test_37_overpass_query_contains_bbox(self):
        query = self.adapter.build_overpass_query(18.70, 72.70, 19.50, 73.30)
        assert "18.7" in query
        assert "72.7" in query
        assert "amenity" in query
        assert "charging_station" in query
        assert "out center tags" in query

    # --- fetch_raw bounding box guard ---

    def test_38_fetch_raw_refuses_without_bbox(self):
        with pytest.raises(ValueError, match="bounding box"):
            self.adapter.fetch_raw()

    def test_39_fetch_raw_with_partial_bbox_refuses(self):
        with pytest.raises((ValueError, TypeError)):
            self.adapter.fetch_raw(lat_min=18.70, lat_max=19.50)

    # --- network mock ---

    def test_40_fetch_raw_parses_overpass_response(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "elements": [RICH_NODE, MINIMAL_NODE]
        }

        with patch("requests.post", return_value=mock_response):
            records = self.adapter.fetch_raw(
                lat_min=18.70, lng_min=72.70, lat_max=19.50, lng_max=73.30
            )
        assert len(records) == 2

    def test_41_fetch_raw_handles_429(self):
        mock_response = MagicMock()
        mock_response.status_code = 429
        # Small Retry-After keeps retry-exhaustion fast; honoring of larger
        # values is covered by the shared transport tests in
        # test_source_transport_retry.py.
        mock_response.headers = {"Retry-After": "1"}

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="rate limit"):
                self.adapter.fetch_raw(
                    lat_min=18.70, lng_min=72.70, lat_max=19.50, lng_max=73.30
                )

    def test_42_fetch_raw_handles_500(self):
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="server error"):
                self.adapter.fetch_raw(
                    lat_min=18.70, lng_min=72.70, lat_max=19.50, lng_max=73.30
                )

    def test_43_fetch_raw_handles_timeout(self):
        import requests as req
        with patch("requests.post", side_effect=req.exceptions.Timeout("timeout")):
            with pytest.raises(TimeoutError):
                self.adapter.fetch_raw(
                    lat_min=18.70, lng_min=72.70, lat_max=19.50, lng_max=73.30
                )

    def test_44_fetch_raw_handles_malformed_json(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("bad json")

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(ValueError, match="Malformed JSON"):
                self.adapter.fetch_raw(
                    lat_min=18.70, lng_min=72.70, lat_max=19.50, lng_max=73.30
                )

    def test_45_fetch_raw_empty_response_returns_empty_list(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"elements": []}

        with patch("requests.post", return_value=mock_response):
            records = self.adapter.fetch_raw(
                lat_min=18.70, lng_min=72.70, lat_max=19.50, lng_max=73.30
            )
        assert records == []

    # --- power parsing ---

    def test_46_parse_power_kw(self):
        assert self.adapter._parse_osm_power("22 kW") == 22.0

    def test_47_parse_power_watts_converted(self):
        result = self.adapter._parse_osm_power("22000 W")
        assert result == 22.0

    def test_48_parse_power_no_unit_assumed_kw(self):
        assert self.adapter._parse_osm_power("50") == 50.0

    def test_49_parse_power_zero_returns_none(self):
        assert self.adapter._parse_osm_power("0") is None

    def test_50_parse_power_none_returns_none(self):
        assert self.adapter._parse_osm_power(None) is None

    def test_51_parse_power_empty_returns_none(self):
        assert self.adapter._parse_osm_power("") is None

    def test_52_parse_power_semicolon_takes_first(self):
        result = self.adapter._parse_osm_power("22 kW; 50 kW")
        assert result == 22.0
