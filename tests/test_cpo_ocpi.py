"""OCPI 2.2.1 conformance tests (isolated simulator — no network, no partner).

Exercises the real pull/mapping code via scripted requests behaviors. All
scenarios are labelled simulated: they prove adapter logic, never a
commercial connection.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests as req

from backend.cpo.ocpi import (
    OcpiClientError,
    OcpiLocationsAdapter,
    OcpiVersionError,
    build_credentials_registration,
    check_ocpi_response,
    fetch_version_detail,
    fetch_versions,
    find_module_url,
    map_connector_standard,
    map_connector_status,
    map_tariff,
    parse_link_header,
    pull_locations,
    select_version_url,
)
from backend.cpo.partners import PartnerConfig
from backend.cpo.simulator import (
    SimResponse,
    make_scripted_send,
    ocpi_envelope,
    ocpi_location,
    ocpi_locations_page,
    ocpi_version_detail,
    ocpi_versions_payload,
)
from backend.ingestion.constants import AvailabilityStatus, OperationalStatus, PricingType


TOKEN = "sim-token-abc"


def _config(**overrides):
    base = {
        "partner_name": "simco", "protocol": "ocpi", "environment": "sandbox",
        "env_prefix": "OCPI_SIMCO_SANDBOX",
        "endpoint": "https://cpo.example.com/ocpi",
        "token": TOKEN, "country_code": "IN", "party_id": "TAT",
    }
    base.update(overrides)
    return PartnerConfig(**base)


def _adapter(**kwargs):
    kwargs.setdefault("partner_name", "simco")
    return OcpiLocationsAdapter(**kwargs)


class TestVersionNegotiation:
    def test_01_selects_221_from_mixed_list(self):
        url = select_version_url([
            {"version": "2.1.1", "url": "https://x/2.1.1"},
            {"version": "2.2.1", "url": "https://x/2.2.1/details"},
        ])
        assert url == "https://x/2.2.1/details"

    def test_02_refuses_unsupported_version(self):
        with pytest.raises(OcpiVersionError, match="2.2.1"):
            select_version_url([{"version": "2.1.1", "url": "https://x/2.1.1"}])

    def test_03_non_list_refused(self):
        with pytest.raises(OcpiVersionError):
            select_version_url({"version": "2.2.1"})

    def test_04_find_locations_module(self):
        url = find_module_url(
            {"endpoints": [{"identifier": "locations", "url": "https://x/loc"}]},
            "locations",
        )
        assert url == "https://x/loc"

    def test_05_missing_module_lists_offers(self):
        with pytest.raises(OcpiClientError, match="tariffs"):
            find_module_url({"endpoints": []}, "tariffs")

    def test_06_credentials_registration_validated(self):
        body = build_credentials_registration(
            "TOKEN_A", "https://x/versions",
            [{"role": "CPO", "party_id": "TAT", "country_code": "IN"}],
        )
        assert body["token"] == "TOKEN_A"
        with pytest.raises(ValueError):
            build_credentials_registration("", "https://x/versions", [{"role": "CPO"}])

    def test_07_response_envelope_success(self):
        assert check_ocpi_response(ocpi_envelope([1, 2]), context="t") == [1, 2]

    def test_08_response_2xxx_is_permanent_client_error(self):
        with pytest.raises(OcpiClientError, match="2001"):
            check_ocpi_response(ocpi_envelope(None, code=2001, message="bad"), context="t")

    def test_09_response_3xxx_is_server_error(self):
        with pytest.raises(RuntimeError, match="server error"):
            check_ocpi_response(ocpi_envelope(None, code=3001, message="down"), context="t")

    def test_10_non_envelope_rejected(self):
        with pytest.raises(OcpiClientError):
            check_ocpi_response([1, 2, 3], context="t")

    def test_11_link_header_parsed(self):
        links = parse_link_header('<https://x/loc?offset=100>; rel="next", <https://x/loc?offset=0>; rel="prev"')
        assert links == {"next": "https://x/loc?offset=100", "prev": "https://x/loc?offset=0"}
        assert parse_link_header(None) == {}
        assert parse_link_header("") == {}


class TestLocationsPull:
    LOC_URL = "https://cpo.example.com/ocpi/2.2.1/locations"

    def test_20_versions_and_detail_flow(self):
        send = make_scripted_send({
            "versions": [SimResponse(200, json_body=ocpi_versions_payload())],
            "details": [SimResponse(200, json_body=ocpi_version_detail(self.LOC_URL))],
        }, expect_token=TOKEN)
        with patch("requests.get", side_effect=send):
            versions = fetch_versions(_config())
            url = select_version_url(versions)
            detail = fetch_version_detail(_config(), url)
            assert find_module_url(detail, "locations") == self.LOC_URL

    def test_21_pagination_follows_link(self):
        page1 = ocpi_locations_page(
            [ocpi_location("LOC1")], link_next=self.LOC_URL + "?offset=1", total=2
        )
        page2 = ocpi_locations_page([ocpi_location("LOC2")])
        send = make_scripted_send({self.LOC_URL: [page1, page2]}, expect_token=TOKEN)
        with patch("requests.get", side_effect=send):
            locations, meta = pull_locations(_config(), self.LOC_URL)
        assert [loc["id"] for loc in locations] == ["LOC1", "LOC2"]
        assert meta["pages_fetched"] == 2

    def test_22_offset_fallback_without_link(self):
        full = ocpi_locations_page([ocpi_location("LOC1"), ocpi_location("LOC2")])
        short = ocpi_locations_page([ocpi_location("LOC3")])
        send = make_scripted_send({self.LOC_URL: [full, short]}, expect_token=TOKEN)
        with patch("requests.get", side_effect=send):
            locations, _ = pull_locations(_config(), self.LOC_URL, page_size=2)
        assert len(locations) == 3

    def test_23_repeated_next_stops_loop(self):
        loop = ocpi_locations_page([ocpi_location("LOC1")], link_next=self.LOC_URL + "?offset=0")
        send = make_scripted_send({self.LOC_URL: [loop]}, expect_token=TOKEN)
        with patch("requests.get", side_effect=send):
            locations, meta = pull_locations(_config(), self.LOC_URL, max_records=50)
        assert len(locations) >= 1
        assert meta["pages_fetched"] < 50  # loop guard fired

    def test_24_max_records_cap(self):
        big = ocpi_locations_page(
            [ocpi_location(f"LOC{i}") for i in range(10)],
            link_next=self.LOC_URL + "?offset=10",
        )
        send = make_scripted_send({self.LOC_URL: [big, big]}, expect_token=TOKEN)
        with patch("requests.get", side_effect=send):
            locations, _ = pull_locations(_config(), self.LOC_URL, max_records=5)
        assert len(locations) == 5

    def test_25_date_from_sent_when_incremental(self):
        seen: list[dict] = []

        def capture(url, *args, **kwargs):
            seen.append(kwargs.get("params") or {})
            return ocpi_locations_page([])

        from datetime import datetime, timezone

        with patch("requests.get", side_effect=capture):
            pull_locations(
                _config(), self.LOC_URL,
                date_from=datetime(2026, 10, 1, tzinfo=timezone.utc),
            )
        assert seen and "date_from" in seen[0]

    def test_26_wrong_token_fails_authentication(self):
        send = make_scripted_send(
            {self.LOC_URL: [ocpi_locations_page([ocpi_location()])]},
            expect_token="other-token",
        )
        with patch("requests.get", side_effect=send):
            with pytest.raises(req.exceptions.HTTPError):
                pull_locations(_config(), self.LOC_URL)

    def test_27_429_recovers_through_real_retry(self):
        fail = SimResponse(429, json_body=ocpi_envelope(None, code=3001), headers={"Retry-After": "0"})
        ok = ocpi_locations_page([ocpi_location("LOC1")])
        send = make_scripted_send({self.LOC_URL: [fail, ok]}, expect_token=TOKEN)
        with patch("requests.get", side_effect=send), \
             patch("backend.ingestion.base._default_sleep") as mock_sleep:
            locations, _ = pull_locations(_config(), self.LOC_URL)
        assert [loc["id"] for loc in locations] == ["LOC1"]
        assert mock_sleep.call_count >= 1

    def test_28_persistent_500_exhausts_retries(self):
        send = make_scripted_send(
            {self.LOC_URL: [SimResponse(500, json_body={})]}, expect_token=TOKEN
        )
        with patch("requests.get", side_effect=send), \
             patch("backend.ingestion.base._default_sleep"):
            with pytest.raises(RuntimeError, match="server error"):
                pull_locations(_config(), self.LOC_URL)

    def test_29_timeout_propagates(self):
        def boom(url, *args, **kwargs):
            raise req.exceptions.Timeout("slow partner")

        with patch("requests.get", side_effect=boom), \
             patch("backend.ingestion.base._default_sleep"):
            with pytest.raises(TimeoutError):
                pull_locations(_config(), self.LOC_URL)

    def test_30_malformed_json_rejected(self):
        bad = SimResponse(200, json_body=ValueError("nope"))
        send = make_scripted_send({self.LOC_URL: [bad]}, expect_token=TOKEN)
        with patch("requests.get", side_effect=send):
            with pytest.raises(ValueError, match="malformed JSON"):
                pull_locations(_config(), self.LOC_URL)


class TestLocationMapping:
    def test_40_full_location_maps(self):
        result = _adapter().process_record(ocpi_location("LOC1"))
        assert result.success, result.errors
        station = result.station_record
        assert station.source_id == "ocpi:simco:sandbox"
        assert station.source_station_id == "IN/TAT/LOC1"
        assert station.latitude == pytest.approx(19.076)
        assert station.operator_name == "Sim Operator"
        assert len(station.connectors) == 1
        conn = station.connectors[0]
        assert conn.connector_type == "Type 2"
        assert conn.power_kw == 22.0
        assert conn.status == AvailabilityStatus.AVAILABLE
        # Live EVSE status becomes a genuine observation (not static state)
        assert station.observation is not None
        assert station.observation.availability_status == AvailabilityStatus.AVAILABLE
        assert station.observation.available_connectors == 1
        assert station.observation.total_connectors == 1

    def test_41_charging_aggregates_to_busy(self):
        result = _adapter().process_record(ocpi_location(status="CHARGING"))
        assert result.success
        assert result.station_record.observation.availability_status == AvailabilityStatus.BUSY

    def test_42_all_outoforder_marks_temporarily_unavailable(self):
        result = _adapter().process_record(ocpi_location(status="OUTOFORDER"))
        assert result.success
        assert result.station_record.operational_status == OperationalStatus.TEMPORARILY_UNAVAILABLE
        assert result.station_record.observation.availability_status == AvailabilityStatus.BROKEN

    def test_43_no_evses_means_no_observation(self):
        loc = ocpi_location()
        loc["evses"] = []
        result = _adapter().process_record(loc)
        assert result.success
        assert result.station_record.observation is None  # static only, never invented

    def test_44_missing_coordinates_fail_closed(self):
        loc = ocpi_location()
        loc["coordinates"] = {}
        result = _adapter().process_record(loc)
        assert not result.success

    def test_45_unpublished_refused(self):
        result = _adapter().process_record(ocpi_location(publish=False))
        assert not result.success
        assert any("publish=false" in e for e in result.errors)

    def test_46_partner_isolation_enforced(self):
        adapter = _adapter(expected_country_code="IN", expected_party_id="TAT")
        foreign = ocpi_location(party="JIO")
        result = adapter.process_record(foreign)
        assert not result.success
        assert any("isolation" in e for e in result.errors)

    def test_47_batch_isolates_bad_records(self):
        batch = _adapter().process_batch([ocpi_location("GOOD"), {"id": "BROKEN"}])
        assert batch.total_records == 2
        assert batch.successful_records == 1
        assert batch.failed_records == 1

    def test_48_replayed_payload_is_stable(self):
        adapter = _adapter()
        first = adapter.process_record(ocpi_location("LOC1"))
        second = adapter.process_record(ocpi_location("LOC1"))
        assert first.success and second.success
        assert first.raw_record.payload_hash == second.raw_record.payload_hash
        assert (first.station_record.source_station_id
                == second.station_record.source_station_id == "IN/TAT/LOC1")

    def test_49_connector_standard_matrix(self):
        assert map_connector_standard("IEC_62196_T2_COMBO") == "CCS2"
        assert map_connector_standard("CHADEMO") == "CHAdeMO"
        assert map_connector_standard("IEC_62196_T1") == "Type 1"
        assert map_connector_standard(" domestic_f ") == "Other"
        assert map_connector_standard("SOMETHING_NEW") == "Other"
        assert map_connector_standard(None) == "Other"

    def test_50_status_matrix(self):
        assert map_connector_status("AVAILABLE") == AvailabilityStatus.AVAILABLE
        assert map_connector_status("CHARGING") == AvailabilityStatus.BUSY
        assert map_connector_status("RESERVED") == AvailabilityStatus.BUSY
        assert map_connector_status("OUTOFORDER") == AvailabilityStatus.BROKEN
        assert map_connector_status("PLANNED") == AvailabilityStatus.UNKNOWN
        assert map_connector_status("WHATEVER") == AvailabilityStatus.UNKNOWN


class TestTariffMapping:
    def _tariff(self, components, currency="INR"):
        return {"currency": currency, "elements": [{"price_components": components}]}

    def test_60_single_energy_element_priced(self):
        pricing, price, currency = map_tariff(
            self._tariff([{"type": "ENERGY", "price": 18.5, "step_size": 1}])
        )
        assert pricing == PricingType.PAID
        assert price == 18.5
        assert currency == "INR"

    def test_61_zero_energy_is_free(self):
        pricing, price, _ = map_tariff(self._tariff([{"type": "ENERGY", "price": 0}]))
        assert pricing == PricingType.FREE
        assert price == 0.0

    def test_62_time_component_stays_unknown(self):
        pricing, price, _ = map_tariff(self._tariff([{"type": "TIME", "price": 2.0}]))
        assert pricing == PricingType.UNKNOWN
        assert price is None  # never guessed from a TIME component

    def test_63_multi_element_stays_unknown(self):
        pricing, price, _ = map_tariff(
            self._tariff([
                {"type": "ENERGY", "price": 18.0, "step_size": 1},
                {"type": "FLAT", "price": 10.0, "step_size": 1},
            ])
        )
        assert pricing == PricingType.UNKNOWN
        assert price is None

    def test_64_missing_tariff_stays_unknown(self):
        assert map_tariff(None)[0] == PricingType.UNKNOWN
        assert map_tariff({})[0] == PricingType.UNKNOWN
