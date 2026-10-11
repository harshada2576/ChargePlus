"""OICP 2.3 eRoaming-subset conformance tests (isolated — no network, no hub)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests as req

from backend.cpo.oicp import (
    OicpEvseAdapter,
    build_pull_evse_data_envelope,
    map_evse_status,
    parse_oicp_datetime,
    parse_pull_evse_data_response,
    pull_evse_data,
)
from backend.cpo.partners import PartnerConfig
from backend.cpo.simulator import SimResponse, make_scripted_send, oicp_pull_response_xml, oicp_record
from backend.ingestion.constants import AvailabilityStatus, OperationalStatus


def _config(**overrides):
    base = {
        "partner_name": "simhub", "protocol": "oicp", "environment": "sandbox",
        "env_prefix": "OICP_SIMHUB_SANDBOX",
        "endpoint": "https://hub.example.com/eRoamingPullEVSEData",
        "token": "hub-token", "party_id": "TAT",
    }
    base.update(overrides)
    return PartnerConfig(**base)


class TestEnvelope:
    def test_01_request_contains_provider(self):
        xml = build_pull_evse_data_envelope("IN-TAT")
        assert "IN-TAT" in xml
        assert "eRoamingPullEVSEData" in xml

    def test_02_request_carries_last_update(self):
        from datetime import datetime, timezone

        xml = build_pull_evse_data_envelope(
            "IN-TAT", last_update=datetime(2026, 10, 1, tzinfo=timezone.utc)
        )
        assert "2026-10-01" in xml

    def test_03_missing_provider_rejected(self):
        with pytest.raises(ValueError, match="provider_id"):
            build_pull_evse_data_envelope("  ")


class TestResponseParsing:
    def test_10_two_records_parsed(self):
        xml = oicp_pull_response_xml([
            oicp_record("IN*TAT*E*0001"),
            oicp_record("IN*TAT*E*0002", status="Occupied", power="60"),
        ])
        records = parse_pull_evse_data_response(xml)
        assert len(records) == 2
        assert records[0]["evse_id"] == "IN*TAT*E*0001"
        assert records[0]["status"] == "Available"
        assert records[0]["power_kw"] == 22.0
        assert records[0]["city"] == "Mumbai"
        assert records[1]["power_kw"] == 60.0

    def test_11_missing_power_stays_none(self):
        xml = oicp_pull_response_xml([oicp_record(power=None)])
        assert parse_pull_evse_data_response(xml)[0]["power_kw"] is None

    def test_12_soap_fault_raises(self):
        xml = (
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            "<soap:Body><soap:Fault><faultstring>auth denied</faultstring>"
            "</soap:Fault></soap:Body></soap:Envelope>"
        )
        with pytest.raises(RuntimeError, match="SOAP fault"):
            parse_pull_evse_data_response(xml)

    def test_13_malformed_xml_rejected(self):
        with pytest.raises(ValueError, match="Malformed"):
            parse_pull_evse_data_response("<not xml")

    def test_14_empty_rejected(self):
        with pytest.raises(ValueError, match="Empty"):
            parse_pull_evse_data_response("  ")

    def test_15_status_matrix(self):
        assert map_evse_status("Available") == AvailabilityStatus.AVAILABLE
        assert map_evse_status("Occupied") == AvailabilityStatus.BUSY
        assert map_evse_status("Reserved") == AvailabilityStatus.BUSY
        assert map_evse_status("OutOfService") == AvailabilityStatus.BROKEN
        assert map_evse_status("Unknown") == AvailabilityStatus.UNKNOWN
        assert map_evse_status("Bogus") == AvailabilityStatus.UNKNOWN
        assert map_evse_status(None) == AvailabilityStatus.UNKNOWN

    def test_16_datetime_parsing(self):
        assert parse_oicp_datetime("2026-10-11T10:00:00Z") is not None
        assert parse_oicp_datetime("garbage") is None
        assert parse_oicp_datetime(None) is None


class TestEvsePull:
    ENDPOINT = "https://hub.example.com/eRoamingPullEVSEData"

    def test_20_pull_returns_records(self):
        xml = oicp_pull_response_xml([oicp_record(), oicp_record("IN*TAT*E*0002")])
        send = make_scripted_send(
            {self.ENDPOINT: [SimResponse(200, text_body=xml)]}, expect_token="hub-token"
        )
        with patch("requests.post", side_effect=send):
            records = pull_evse_data(_config(), "IN-TAT")
        assert len(records) == 2

    def test_21_bearer_auth_header_sent(self):
        seen: list[dict] = []

        def capture(url, *args, **kwargs):
            seen.append(kwargs.get("headers") or {})
            return SimResponse(200, text_body=oicp_pull_response_xml([]))

        with patch("requests.post", side_effect=capture):
            pull_evse_data(_config(), "IN-TAT")
        assert seen and seen[0].get("Authorization") == "Bearer hub-token"
        assert "hub-token" not in str(seen[0].get("Content-Type"))

    def test_22_wrong_credential_fails(self):
        send = make_scripted_send(
            {self.ENDPOINT: [SimResponse(200, text_body=oicp_pull_response_xml([]))]},
            expect_token="other",
        )
        with patch("requests.post", side_effect=send):
            with pytest.raises(req.exceptions.HTTPError):
                pull_evse_data(_config(), "IN-TAT")

    def test_23_server_error_exhausts_retries(self):
        send = make_scripted_send(
            {self.ENDPOINT: [SimResponse(500, text_body="boom")]}, expect_token="hub-token"
        )
        with patch("requests.post", side_effect=send), \
             patch("backend.ingestion.base._default_sleep"):
            with pytest.raises(RuntimeError, match="server error"):
                pull_evse_data(_config(), "IN-TAT")


class TestEvseMapping:
    def _adapter(self, **kwargs):
        kwargs.setdefault("partner_name", "simhub")
        return OicpEvseAdapter(**kwargs)

    def test_30_record_maps_to_station(self):
        result = self._adapter().process_record(oicp_record())
        assert result.success, result.errors
        station = result.station_record
        assert station.source_id == "oicp:simhub:sandbox"
        assert station.source_station_id == "oicp/TAT/IN*TAT*E*0001"
        assert station.operator_name == "Sim Operator"
        assert station.connectors[0].power_kw == 22.0
        assert station.observation is not None
        assert station.observation.availability_status == AvailabilityStatus.AVAILABLE

    def test_31_occupied_is_busy(self):
        result = self._adapter().process_record(oicp_record(status="Occupied"))
        assert result.success
        assert result.station_record.observation.availability_status == AvailabilityStatus.BUSY

    def test_32_out_of_service_is_temporarily_unavailable(self):
        result = self._adapter().process_record(oicp_record(status="OutOfService"))
        assert result.success
        assert result.station_record.operational_status == OperationalStatus.TEMPORARILY_UNAVAILABLE

    def test_33_missing_coordinates_fail_closed(self):
        rec = oicp_record()
        rec["latitude"] = None
        assert not self._adapter().process_record(rec).success

    def test_34_operator_isolation_enforced(self):
        adapter = self._adapter(expected_operator_id="TAT")
        assert not adapter.process_record(oicp_record(operator="JIO")).success

    def test_35_missing_evse_id_rejected(self):
        rec = oicp_record()
        rec["evse_id"] = None
        assert not self._adapter().process_record(rec).success
