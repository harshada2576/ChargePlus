"""Tests — Step 2.11: Mumbai Pilot Geographic Coverage & Data Quality Audit.

Covers all 22 testing requirements from Step 2.11 specification:
1.  Mumbai inclusion/exclusion using authoritative geography
2.  Outside-pilot records
3.  Invalid coordinates
4.  Missing coordinates
5.  Connector completeness
6.  Pricing completeness
7.  Operator completeness
8.  Live observation distinction
9.  Static operational status NOT counted as live telemetry
10. Freshness state calculation using Step 2.9
11. Stale != unavailable
12. Source coverage aggregation
13. Multiple source links
14. Entity-resolution outcome aggregation
15. DQ outcome aggregation
16. Deterministic audit results
17. Explicit as_of behaviour
18. Empty dataset behaviour
19. Partial dataset behaviour
20. Temporal observation coverage
21. ML readiness measurements
22. No database mutation from audit execution
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from backend.ingestion.audit import (
    AuditConfig,
    MumbaiCoverageAuditor,
    format_report,
)
from backend.ingestion.constants import (
    MUMBAI_LAT_MAX,
    MUMBAI_LAT_MIN,
    MUMBAI_LNG_MAX,
    MUMBAI_LNG_MIN,
)
from backend.ingestion.freshness import FreshnessState


# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────

AS_OF = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
CFG = AuditConfig(scope="mumbai", as_of=AS_OF)

INSIDE_LAT = (MUMBAI_LAT_MIN + MUMBAI_LAT_MAX) / 2          # 19.10
INSIDE_LNG = (MUMBAI_LNG_MIN + MUMBAI_LNG_MAX) / 2          # 73.00
OUTSIDE_LAT = MUMBAI_LAT_MAX + 1.0                           # 20.50 — north of MMR
OUTSIDE_LNG = MUMBAI_LNG_MIN                                 # 72.70


def _station(
    id: str = "s1",
    lat: Any = INSIDE_LAT,
    lng: Any = INSIDE_LNG,
    operator_id: str = "op1",
    operational_status: str = "operational",
    city: str = "Mumbai",
    locality: str = "Andheri",
    postal_code: str = "400053",
) -> dict[str, Any]:
    return {
        "id": id,
        "slug": id,
        "name": f"Station {id}",
        "operator_id": operator_id,
        "address_line": "Some Road",
        "locality": locality,
        "city": city,
        "state": "Maharashtra",
        "postal_code": postal_code,
        "country": "IN",
        "latitude": lat,
        "longitude": lng,
        "opening_time": None,
        "closing_time": None,
        "is_24_hours": False,
        "access_type": "public",
        "is_public": True,
        "operational_status": operational_status,
        "website_url": None,
        "created_at": None,
        "updated_at": None,
    }


def _connector(
    id: str = "c1",
    station_id: str = "s1",
    connector_type: str = "CCS2",
    power_kw: Any = 60.0,
    quantity: int = 2,
    price_per_kwh: Any = None,
    pricing_type: Any = None,
    currency: Any = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "station_id": station_id,
        "connector_type": connector_type,
        "charging_standard": "IEC_62196",
        "power_kw": power_kw,
        "quantity": quantity,
        "pricing_type": pricing_type,
        "price_per_kwh": price_per_kwh,
        "price_per_session": None,
        "currency": currency,
        "created_at": None,
    }


def _observation(
    id: str = "o1",
    station_id: str = "s1",
    availability_status: str = "available",
    observed_at: Any = None,
    source_id: str = "src1",
) -> dict[str, Any]:
    if observed_at is None:
        observed_at = (AS_OF - timedelta(hours=1)).isoformat()
    return {
        "id": id,
        "station_id": station_id,
        "connector_id": None,
        "source_id": source_id,
        "availability_status": availability_status,
        "queue_level": None,
        "available_connectors": None,
        "total_connectors": None,
        "observed_at": observed_at,
        "received_at": None,
        "source_payload_hash": "abc123",
        "created_at": None,
    }


def _link(
    id: str = "l1",
    station_id: str = "s1",
    source_id: str = "src1",
    source_station_id: str = "EXT-001",
) -> dict[str, Any]:
    return {
        "id": id,
        "station_id": station_id,
        "source_id": source_id,
        "source_station_id": source_station_id,
        "source_url": "https://example.com/station/EXT-001",
        "first_seen_at": AS_OF.isoformat(),
        "last_seen_at": AS_OF.isoformat(),
        "last_ingested_at": AS_OF.isoformat(),
        "source_payload_hash": "abc123",
        "is_active": True,
        "created_at": None,
    }


def _source(id: str = "src1", name: str = "OpenChargeMap") -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "source_type": "api",
        "is_active": True,
        "base_url": "https://api.openchargemap.io",
    }


def _run(**overrides) -> dict[str, Any]:
    base = {
        "id": "run1",
        "source_id": "src1",
        "geographic_scope": "mumbai",
        "state": "succeeded",
        "attempt_count": 1,
        "records_fetched": 10,
        "records_parsed": 10,
        "records_accepted": 8,
        "records_accepted_with_warnings": 1,
        "records_quarantined": 1,
        "records_rejected": 0,
        "stations_persisted": 8,
        "observations_persisted": 1,
        "started_at": None,
        "completed_at": None,
    }
    base.update(overrides)
    return base


def _audit(
    stations=None,
    connectors=None,
    observations=None,
    source_links=None,
    operators=None,
    data_sources=None,
    ingestion_runs=None,
    cfg: AuditConfig = CFG,
):
    auditor = MumbaiCoverageAuditor(cfg)
    return auditor.audit_in_memory(
        stations=stations or [],
        connectors=connectors or [],
        observations=observations or [],
        source_links=source_links or [],
        operators=operators or [],
        data_sources=data_sources or [_source()],
        ingestion_runs=ingestion_runs or [],
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. Mumbai inclusion/exclusion using authoritative geography
# ──────────────────────────────────────────────────────────────────────────────

class TestGeographicClassification:
    def test_station_inside_pilot_area_counted(self):
        r = _audit(stations=[_station(lat=INSIDE_LAT, lng=INSIDE_LNG)])
        assert r.geo.in_pilot == 1
        assert r.geo.outside_pilot == 0

    def test_station_at_exact_boundary_included(self):
        # Boundary points must be included (≤)
        r = _audit(stations=[_station(lat=MUMBAI_LAT_MIN, lng=MUMBAI_LNG_MIN)])
        assert r.geo.in_pilot == 1

    def test_station_at_max_boundary_included(self):
        r = _audit(stations=[_station(lat=MUMBAI_LAT_MAX, lng=MUMBAI_LNG_MAX)])
        assert r.geo.in_pilot == 1


# ──────────────────────────────────────────────────────────────────────────────
# 2. Outside-pilot records
# ──────────────────────────────────────────────────────────────────────────────

class TestOutsidePilot:
    def test_station_outside_pilot_not_counted_as_inside(self):
        r = _audit(stations=[_station(lat=OUTSIDE_LAT, lng=OUTSIDE_LNG)])
        assert r.geo.in_pilot == 0
        assert r.geo.outside_pilot == 1

    def test_mixed_in_out(self):
        r = _audit(stations=[
            _station(id="s1", lat=INSIDE_LAT, lng=INSIDE_LNG),
            _station(id="s2", lat=OUTSIDE_LAT, lng=OUTSIDE_LNG),
        ])
        assert r.geo.in_pilot == 1
        assert r.geo.outside_pilot == 1
        assert r.geo.total == 2


# ──────────────────────────────────────────────────────────────────────────────
# 3. Invalid coordinates
# ──────────────────────────────────────────────────────────────────────────────

class TestInvalidCoordinates:
    def test_lat_out_of_range_counted_as_invalid(self):
        r = _audit(stations=[_station(lat=91.0, lng=73.0)])
        assert r.geo.invalid_coords == 1
        assert r.geo.in_pilot == 0

    def test_lng_out_of_range_counted_as_invalid(self):
        r = _audit(stations=[_station(lat=19.0, lng=181.0)])
        assert r.geo.invalid_coords == 1

    def test_string_garbage_counted_as_invalid(self):
        r = _audit(stations=[_station(lat="not_a_float", lng="?")])
        assert r.geo.invalid_coords == 1


# ──────────────────────────────────────────────────────────────────────────────
# 4. Missing coordinates
# ──────────────────────────────────────────────────────────────────────────────

class TestMissingCoordinates:
    def test_null_lat_counted_as_missing(self):
        r = _audit(stations=[_station(lat=None, lng=73.0)])
        assert r.geo.missing_coords == 1
        assert r.geo.in_pilot == 0

    def test_null_lng_counted_as_missing(self):
        r = _audit(stations=[_station(lat=19.0, lng=None)])
        assert r.geo.missing_coords == 1

    def test_both_null_counted_as_missing(self):
        r = _audit(stations=[_station(lat=None, lng=None)])
        assert r.geo.missing_coords == 1


# ──────────────────────────────────────────────────────────────────────────────
# 5. Connector completeness
# ──────────────────────────────────────────────────────────────────────────────

class TestConnectorCompleteness:
    def test_station_with_connector_counted(self):
        r = _audit(
            stations=[_station("s1")],
            connectors=[_connector("c1", "s1")],
        )
        assert r.connectors.stations_with_connectors == 1
        assert r.connectors.stations_no_connectors == 0

    def test_station_without_connector_counted_as_no_connector(self):
        r = _audit(
            stations=[_station("s1"), _station("s2")],
            connectors=[_connector("c1", "s1")],
        )
        assert r.connectors.stations_with_connectors == 1
        assert r.connectors.stations_no_connectors == 1

    def test_connector_type_distribution(self):
        r = _audit(
            stations=[_station("s1")],
            connectors=[
                _connector("c1", "s1", connector_type="CCS2"),
                _connector("c2", "s1", connector_type="Type2"),
            ],
        )
        assert r.connectors.by_type.get("CCS2", 0) == 1
        assert r.connectors.by_type.get("Type2", 0) == 1

    def test_missing_power_counted_separately_from_present(self):
        r = _audit(
            stations=[_station("s1")],
            connectors=[
                _connector("c1", "s1", power_kw=60.0),
                _connector("c2", "s1", power_kw=None),
            ],
        )
        assert r.connectors.power_present == 1
        assert r.connectors.power_missing == 1

    def test_missing_connector_power_not_treated_as_zero_kw(self):
        """INVARIANT: missing power != 0 kW."""
        r = _audit(
            stations=[_station("s1")],
            connectors=[_connector("c1", "s1", power_kw=None)],
        )
        # No power bracket for 0 kW should appear
        assert r.connectors.power_present == 0
        assert "≤22 kW (AC Slow)" not in r.connectors.power_by_bracket or r.connectors.power_by_bracket.get("≤22 kW (AC Slow)", 0) == 0


# ──────────────────────────────────────────────────────────────────────────────
# 6. Pricing completeness
# ──────────────────────────────────────────────────────────────────────────────

class TestPricingCompleteness:
    def test_station_with_no_price_counted_as_missing(self):
        r = _audit(
            stations=[_station("s1")],
            connectors=[_connector("c1", "s1", price_per_kwh=None, pricing_type=None)],
        )
        assert r.pricing.connectors_missing_pricing == 1
        assert r.pricing.stations_missing_pricing == 1

    def test_missing_pricing_not_treated_as_free(self):
        """INVARIANT: missing pricing != free."""
        r = _audit(
            stations=[_station("s1")],
            connectors=[_connector("c1", "s1", price_per_kwh=None, pricing_type=None)],
        )
        assert r.pricing.explicit_free == 0

    def test_explicit_free_pricing_counted_correctly(self):
        r = _audit(
            stations=[_station("s1")],
            connectors=[_connector("c1", "s1", pricing_type="free")],
        )
        assert r.pricing.explicit_free == 1

    def test_explicit_paid_counted_correctly(self):
        r = _audit(
            stations=[_station("s1")],
            connectors=[_connector("c1", "s1", price_per_kwh=10.5, currency="INR")],
        )
        assert r.pricing.explicit_paid == 1
        assert "INR" in r.pricing.currencies


# ──────────────────────────────────────────────────────────────────────────────
# 7. Operator completeness
# ──────────────────────────────────────────────────────────────────────────────

class TestOperatorCompleteness:
    def test_station_with_operator_id_counted(self):
        r = _audit(stations=[_station("s1", operator_id="op1")])
        assert r.completeness.fields["operator_linked"]["present"] == 1

    def test_station_without_operator_id_not_counted(self):
        r = _audit(stations=[_station("s1", operator_id=None)])
        assert r.completeness.fields["operator_linked"]["present"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 8. Live observation distinction (obs exists vs does not)
# ──────────────────────────────────────────────────────────────────────────────

class TestLiveObservationDistinction:
    def test_station_with_observation_counted(self):
        r = _audit(
            stations=[_station("s1")],
            observations=[_observation("o1", "s1")],
        )
        assert r.observations.stations_with_obs == 1

    def test_station_without_observation_counted(self):
        r = _audit(stations=[_station("s1")])
        assert r.observations.stations_without_obs == 1
        assert r.observations.stations_with_obs == 0


# ──────────────────────────────────────────────────────────────────────────────
# 9. Static operational status NOT counted as live telemetry
# ──────────────────────────────────────────────────────────────────────────────

class TestStaticVsLiveTelemetry:
    def test_operational_status_does_not_contribute_to_observation_count(self):
        """A station with operational_status='operational' and no observation row
        must yield 0 genuine observations."""
        r = _audit(stations=[_station("s1", operational_status="operational")])
        assert r.observations.total == 0
        assert r.observations.stations_with_obs == 0

    def test_static_status_contributes_only_to_op_status_metric(self):
        r = _audit(stations=[_station("s1", operational_status="operational")])
        assert r.op_status.by_status.get("operational", 0) == 1

    def test_live_observation_is_separate_from_static_status(self):
        r = _audit(
            stations=[_station("s1", operational_status="operational")],
            observations=[_observation("o1", "s1", availability_status="available")],
        )
        # Operational status = 1 in static metric
        assert r.op_status.by_status.get("operational", 0) == 1
        # Genuine observation = 1 in observation metric
        assert r.observations.total == 1


# ──────────────────────────────────────────────────────────────────────────────
# 10. Freshness state calculation using Step 2.9 (FreshnessEngine)
# ──────────────────────────────────────────────────────────────────────────────

class TestFreshnessStateCalculation:
    def test_fresh_observation_classified_fresh(self):
        observed_at = AS_OF - timedelta(minutes=2)
        r = _audit(
            stations=[_station("s1")],
            observations=[_observation("o1", "s1", observed_at=observed_at.isoformat())],
        )
        assert r.observations.by_freshness.get(FreshnessState.FRESH.value, 0) == 1

    def test_aging_observation_classified_aging(self):
        observed_at = AS_OF - timedelta(minutes=10)
        r = _audit(
            stations=[_station("s1")],
            observations=[_observation("o1", "s1", observed_at=observed_at.isoformat())],
        )
        assert r.observations.by_freshness.get(FreshnessState.AGING.value, 0) == 1

    def test_stale_observation_classified_stale(self):
        observed_at = AS_OF - timedelta(hours=1)
        r = _audit(
            stations=[_station("s1")],
            observations=[_observation("o1", "s1", observed_at=observed_at.isoformat())],
        )
        assert r.observations.by_freshness.get(FreshnessState.STALE.value, 0) == 1

    def test_missing_timestamp_classified_unknown(self):
        obs = _observation("o1", "s1")
        obs["observed_at"] = None
        r = _audit(
            stations=[_station("s1")],
            observations=[obs],
        )
        assert r.observations.by_freshness.get(FreshnessState.UNKNOWN.value, 0) == 1


# ──────────────────────────────────────────────────────────────────────────────
# 11. Stale != unavailable
# ──────────────────────────────────────────────────────────────────────────────

class TestStaleIsNotUnavailable:
    def test_stale_available_observation_retained_as_available(self):
        """A STALE observation must NOT be rewritten to 'unavailable'."""
        old = AS_OF - timedelta(days=30)
        r = _audit(
            stations=[_station("s1")],
            observations=[_observation("o1", "s1", availability_status="available", observed_at=old.isoformat())],
        )
        # Freshness must be STALE
        assert r.observations.by_freshness.get(FreshnessState.STALE.value, 0) == 1
        # Availability must remain "available" (not "unavailable")
        assert r.observations.by_availability.get("available", 0) == 1
        assert r.observations.by_availability.get("unavailable", 0) == 0


# ──────────────────────────────────────────────────────────────────────────────
# 12. Source coverage aggregation
# ──────────────────────────────────────────────────────────────────────────────

class TestSourceCoverageAggregation:
    def test_two_sources_counted(self):
        r = _audit(
            stations=[_station("s1"), _station("s2")],
            source_links=[
                _link("l1", "s1", "src1"),
                _link("l2", "s2", "src2"),
            ],
            data_sources=[_source("src1", "OpenChargeMap"), _source("src2", "EVSE")],
        )
        assert r.source.registered_sources == 2
        assert r.source.total_links == 2

    def test_links_per_source_counted_correctly(self):
        r = _audit(
            stations=[_station("s1"), _station("s2")],
            source_links=[
                _link("l1", "s1", "src1"),
                _link("l2", "s2", "src1"),
            ],
            data_sources=[_source("src1", "OpenChargeMap")],
        )
        assert r.source.links_per_source.get("OpenChargeMap", 0) == 2


# ──────────────────────────────────────────────────────────────────────────────
# 13. Multiple source links (MERGE detection)
# ──────────────────────────────────────────────────────────────────────────────

class TestMultipleSourceLinks:
    def test_station_with_two_sources_counted_as_multi_source(self):
        r = _audit(
            stations=[_station("s1")],
            source_links=[
                _link("l1", "s1", "src1"),
                _link("l2", "s1", "src2"),
            ],
            data_sources=[_source("src1", "OCM"), _source("src2", "EVSE")],
        )
        assert r.source.stations_with_multiple_sources == 1

    def test_station_with_one_source_not_counted_as_multi(self):
        r = _audit(
            stations=[_station("s1")],
            source_links=[_link("l1", "s1", "src1")],
            data_sources=[_source("src1", "OCM")],
        )
        assert r.source.stations_with_multiple_sources == 0

    def test_entity_resolution_multi_source_counted(self):
        r = _audit(
            stations=[_station("s1"), _station("s2")],
            source_links=[
                _link("l1", "s1", "src1"),
                _link("l2", "s1", "src2"),
                _link("l3", "s2", "src1"),
            ],
            data_sources=[_source("src1"), _source("src2")],
        )
        assert r.entity_resolution.multi_source_stations == 1
        assert r.entity_resolution.single_source_stations == 1


# ──────────────────────────────────────────────────────────────────────────────
# 14. Entity-resolution outcome aggregation
# ──────────────────────────────────────────────────────────────────────────────

class TestEntityResolutionAggregation:
    def test_canonical_count_matches_stations(self):
        r = _audit(stations=[_station("s1"), _station("s2")])
        assert r.entity_resolution.canonical_stations == 2

    def test_unresolved_is_zero_by_fk_invariant(self):
        """All persisted links reference a canonical station by FK — unresolved must be 0."""
        r = _audit(
            stations=[_station("s1")],
            source_links=[_link("l1", "s1")],
        )
        assert r.entity_resolution.unresolved == 0


# ──────────────────────────────────────────────────────────────────────────────
# 15. DQ outcome aggregation
# ──────────────────────────────────────────────────────────────────────────────

class TestDQOutcomeAggregation:
    def test_dq_metrics_summed_from_runs(self):
        runs = [
            _run(records_accepted=5, records_quarantined=1, records_rejected=0),
            _run(records_accepted=3, records_quarantined=0, records_rejected=2),
        ]
        r = _audit(ingestion_runs=runs)
        assert r.dq.run_count == 2
        assert r.dq.accepted == 8
        assert r.dq.quarantined == 1
        assert r.dq.rejected == 2

    def test_zero_runs_yields_note(self):
        r = _audit(ingestion_runs=[])
        assert r.dq.run_count == 0
        assert len(r.dq.note) > 0


# ──────────────────────────────────────────────────────────────────────────────
# 16. Deterministic audit results
# ──────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_output(self):
        stations = [_station("s1"), _station("s2")]
        observations = [
            _observation("o1", "s1"),
            _observation("o2", "s2"),
        ]
        r1 = _audit(stations=stations, observations=observations)
        r2 = _audit(stations=stations, observations=observations)
        assert r1.geo.in_pilot == r2.geo.in_pilot
        assert r1.observations.total == r2.observations.total
        assert r1.observations.by_freshness == r2.observations.by_freshness

    def test_input_order_does_not_affect_result(self):
        s1 = _station("s1")
        s2 = _station("s2")
        r1 = _audit(stations=[s1, s2])
        r2 = _audit(stations=[s2, s1])
        assert r1.geo.total == r2.geo.total
        assert r1.geo.in_pilot == r2.geo.in_pilot


# ──────────────────────────────────────────────────────────────────────────────
# 17. Explicit as_of behaviour
# ──────────────────────────────────────────────────────────────────────────────

class TestAsOfBehaviour:
    def test_fresh_at_one_as_of_stale_at_another(self):
        observed_at = datetime(2026, 9, 26, 11, 55, 0, tzinfo=timezone.utc)  # 5 min before as_of

        cfg_fresh = AuditConfig(as_of=datetime(2026, 9, 26, 11, 57, 0, tzinfo=timezone.utc))
        cfg_stale = AuditConfig(as_of=datetime(2026, 9, 26, 13, 0, 0, tzinfo=timezone.utc))

        s = [_station("s1")]
        obs = [_observation("o1", "s1", observed_at=observed_at.isoformat())]

        r_fresh = MumbaiCoverageAuditor(cfg_fresh).audit_in_memory(s, [], obs, [], [], [_source()])
        r_stale = MumbaiCoverageAuditor(cfg_stale).audit_in_memory(s, [], obs, [], [], [_source()])

        assert r_fresh.observations.by_freshness.get(FreshnessState.FRESH.value, 0) == 1
        assert r_stale.observations.by_freshness.get(FreshnessState.STALE.value, 0) == 1

    def test_as_of_appears_in_report(self):
        as_of = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        cfg = AuditConfig(as_of=as_of)
        r = MumbaiCoverageAuditor(cfg).audit_in_memory([], [], [], [], [], [_source()])
        assert "2026-01-01T00:00:00+00:00" in r.as_of


# ──────────────────────────────────────────────────────────────────────────────
# 18. Empty dataset behaviour
# ──────────────────────────────────────────────────────────────────────────────

class TestEmptyDataset:
    def test_empty_dataset_produces_zero_counts(self):
        r = _audit()
        assert r.geo.total == 0
        assert r.geo.in_pilot == 0
        assert r.connectors.total_connector_records == 0
        assert r.observations.total == 0

    def test_empty_dataset_completeness_fields_zero(self):
        r = _audit()
        for attr, info in r.completeness.fields.items():
            assert info["present"] == 0, f"Expected 0 for {attr}"

    def test_empty_dataset_ml_readiness_cold(self):
        r = _audit()
        assert r.ml.maturity_stage == "COLD"
        assert r.ml.is_ready_for_queue_prediction is False


# ──────────────────────────────────────────────────────────────────────────────
# 19. Partial dataset behaviour
# ──────────────────────────────────────────────────────────────────────────────

class TestPartialDataset:
    def test_one_station_no_connectors(self):
        r = _audit(stations=[_station("s1")])
        assert r.geo.total == 1
        assert r.connectors.stations_with_connectors == 0
        assert r.connectors.stations_no_connectors == 1

    def test_connectors_without_stations_no_crash(self):
        """Connectors referencing non-listed stations should be counted
        in connector totals but no station in geo.total."""
        r = _audit(
            stations=[],
            connectors=[_connector("c1", "s_orphan")],
        )
        assert r.connectors.total_connector_records == 1
        assert r.geo.total == 0


# ──────────────────────────────────────────────────────────────────────────────
# 20. Temporal observation coverage
# ──────────────────────────────────────────────────────────────────────────────

class TestTemporalCoverage:
    def test_temporal_span_calculated_correctly(self):
        t1 = AS_OF - timedelta(days=10)
        t2 = AS_OF - timedelta(hours=1)
        r = _audit(
            stations=[_station("s1")],
            observations=[
                _observation("o1", "s1", observed_at=t1.isoformat()),
                _observation("o2", "s1", observed_at=t2.isoformat()),
            ],
        )
        # Span should be ~10 days minus 1 hour (~239 hours)
        assert r.observations.temporal_span_hours is not None
        assert r.observations.temporal_span_hours > 230

    def test_single_observation_span_is_zero(self):
        r = _audit(
            stations=[_station("s1")],
            observations=[_observation("o1", "s1")],
        )
        assert r.observations.temporal_span_hours == 0.0

    def test_no_observations_temporal_span_none(self):
        r = _audit(stations=[_station("s1")])
        assert r.observations.temporal_span_hours is None

    def test_earliest_latest_timestamps_sorted(self):
        t1 = AS_OF - timedelta(days=5)
        t2 = AS_OF - timedelta(days=1)
        r = _audit(
            stations=[_station("s1")],
            observations=[
                _observation("o2", "s1", observed_at=t2.isoformat()),
                _observation("o1", "s1", observed_at=t1.isoformat()),
            ],
        )
        assert r.observations.earliest_observed_at is not None
        assert r.observations.latest_observed_at is not None
        # Earliest must be before latest
        dt_earliest = datetime.fromisoformat(r.observations.earliest_observed_at)
        dt_latest = datetime.fromisoformat(r.observations.latest_observed_at)
        assert dt_earliest < dt_latest


# ──────────────────────────────────────────────────────────────────────────────
# 21. ML readiness measurements
# ──────────────────────────────────────────────────────────────────────────────

class TestMLReadiness:
    def test_zero_observations_cold_start(self):
        r = _audit()
        assert r.ml.is_ready_for_queue_prediction is False
        assert r.ml.maturity_stage == "COLD"

    def test_single_observation_still_cold(self):
        r = _audit(
            stations=[_station("s1")],
            observations=[_observation("o1", "s1")],
        )
        assert r.ml.is_ready_for_queue_prediction is False
        assert r.ml.observation_volume == 1

    def test_repeated_observation_stations_counted(self):
        """Two observations for the same station must yield 1 station with repeated snapshots."""
        r = _audit(
            stations=[_station("s1")],
            observations=[
                _observation("o1", "s1"),
                _observation("o2", "s1"),
            ],
        )
        # Both the observations and the ML metric should agree
        assert r.observations.stations_with_repeated_obs == 1
        assert r.ml.repeated_observation_stations == 1


# ──────────────────────────────────────────────────────────────────────────────
# 22. No database mutation from audit execution
# ──────────────────────────────────────────────────────────────────────────────

class TestNoDatabaseMutation:
    def test_audit_does_not_modify_input_stations(self):
        stations = [_station("s1")]
        original = copy.deepcopy(stations)
        _audit(stations=stations)
        assert stations == original

    def test_audit_does_not_modify_input_connectors(self):
        connectors = [_connector("c1")]
        original = copy.deepcopy(connectors)
        _audit(connectors=connectors)
        assert connectors == original

    def test_audit_does_not_modify_input_observations(self):
        observations = [_observation("o1", "s1")]
        original = copy.deepcopy(observations)
        _audit(observations=observations)
        assert observations == original

    def test_audit_does_not_add_sources_to_input(self):
        sources = [_source()]
        original_len = len(sources)
        _audit(data_sources=sources)
        assert len(sources) == original_len


# ──────────────────────────────────────────────────────────────────────────────
# Markdown format smoke test
# ──────────────────────────────────────────────────────────────────────────────

class TestMarkdownFormat:
    def test_format_report_contains_key_sections(self):
        r = _audit(
            stations=[_station("s1")],
            connectors=[_connector("c1", "s1")],
        )
        md = format_report(r)
        assert "## 1. Audit Configuration" in md
        assert "## 2. Geographic Coverage" in md
        assert "## 3. Source Coverage" in md
        assert "## 5. Connector, Power & Pricing" in md
        assert "## 6. Operational Status vs Live Telemetry" in md
        assert "## 10. Product Capability Matrix" in md
        assert "## 13. Phase 2 Closure Verdict" in md

    def test_format_report_contains_closure_verdict(self):
        r = _audit()
        md = format_report(r)
        assert "PHASE 2 COMPLETE — READY FOR PHASE 3" in md

    def test_invariant_statements_present(self):
        r = _audit()
        md = format_report(r)
        assert "STALE != UNAVAILABLE" in md
        assert "Missing pricing is classified UNKNOWN" in md or "missing pricing" in md.lower()
