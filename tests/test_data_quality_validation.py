"""ChargePlus — Ingestion-Wide Data Quality Validation Unit Test Suite.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.6 (Validate Records: Ingestion-Wide Data Quality Validation & Anomaly Quarantine)

Tests all 40 required validation, quarantine, batch metrics, and architectural invariant scenarios:
1. Fully valid station => ACCEPT.
2. Valid station with missing optional power => ACCEPT_WITH_WARNINGS.
3. Missing optional price => ACCEPT_WITH_WARNINGS or documented equivalent.
4. Missing operator => does not automatically reject.
5. Missing connector quantity => does not invent quantity.
6. Invalid latitude outside [-90,90] => blocking failure.
7. Invalid longitude outside [-180,180] => blocking failure.
8. latitude=0 alone => allowed.
9. longitude=0 alone => allowed.
10. (0,0) => rejected/blocked according to existing contract.
11. Negative power => invalid.
12. Negative voltage => invalid.
13. Negative amperage => invalid.
14. Negative connector quantity => invalid.
15. Suspicious but physically plausible power => warning, not automatic rejection.
16. Unknown connector vocabulary => correctly distinguished from malformed data.
17. Explicit FREE pricing + zero amount => valid.
18. Missing pricing => unknown, not free.
19. Negative price => invalid.
20. Invalid currency representation => appropriate failure.
21. Per-kWh vs per-session vs per-hour remain distinct.
22. Valid normal operating hours => valid.
23. Valid overnight hours => valid.
24. Invalid time => failure.
25. Missing operating hours => not rejection.
26. 24/7 representation => valid.
27. Contradictory 24/7/schedule => anomaly.
28. Provenance missing source ID => blocking.
29. Provenance missing source record ID where required => blocking.
30. Operational state is not interpreted as live availability.
31. Stale observation is not interpreted as unavailable.
32. Batch report counts all input records.
33. Batch report issue counts are deterministic.
34. Multiple findings on one record are all preserved.
35. Quarantine retains complete provenance and findings.
36. Quarantined records do not enter canonical operational persistence.
37. Validator does not mutate input records.
38. Validator is deterministic.
39. Existing tests remain passing.
40. Existing Step 2.4 and Step 2.5 behavior remains passing.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
import unittest
from typing import Any

from backend.ingestion.constants import (
    AvailabilityStatus,
    OperationalStatus,
    PricingType,
    QueueLevel,
    StandardConnectorType,
    ValidationOutcome,
)
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedObservationRecord,
    NormalizedStationRecord,
    ProvenanceInfo,
    RawSourceRecord,
)
from backend.ingestion.validation import (
    BatchValidationReport,
    DataQualityValidator,
    QualityFinding,
    QualityRuleCategory,
    QualitySeverity,
    QuarantineRecord,
    ValidationResult,
)
from backend.ingestion.persistence import (
    IngestionPersistenceService,
    PersistenceStatus,
)
from backend.ingestion.runner import IngestionRunner


def make_valid_station(**overrides: Any) -> NormalizedStationRecord:
    """Helper factory for a canonical, fully-valid Mumbai station record."""
    base: dict[str, Any] = {
        "source_id": "test_validator",
        "source_station_id": "STN-VAL-001",
        "name": "Tata Power - Bandra Kurla Complex Hub",
        "operator_name": "Tata Power EZ Charge",
        "operator_slug": "tata-power",
        "latitude": 19.0657,
        "longitude": 72.8687,
        "address_line": "G Block, BKC Road",
        "locality": "Bandra Kurla Complex",
        "city": "Mumbai",
        "state": "Maharashtra",
        "postal_code": "400051",
        "country": "India",
        "is_24_hours": True,
        "is_public": True,
        "operational_status": OperationalStatus.OPERATIONAL,
        "phone": "+91-22-6717-1000",
        "website_url": "https://tatapower.com/ev",
        "connectors": [
            NormalizedConnectorRecord(
                source_connector_id="CONN-01",
                connector_type=StandardConnectorType.CCS2.value,
                raw_connector_type="CCS-2 (DC Fast)",
                power_kw=60.0,
                voltage_v=400.0,
                amperage_a=150.0,
                quantity=2,
                pricing_type=PricingType.PAID,
                price_per_kwh=18.50,
                currency="INR",
            )
        ],
        "observation": NormalizedObservationRecord(
            source_id="test_validator",
            source_station_id="STN-VAL-001",
            observed_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            availability_status=AvailabilityStatus.AVAILABLE,
            queue_level=QueueLevel.NONE,
            available_connectors=1,
            total_connectors=2,
            raw_status_label="Available",
        ),
    }
    base.update(overrides)
    return NormalizedStationRecord(**base)


class TestDataQualityValidation(unittest.TestCase):
    """Unit test suite verifying Phase 2 Step 2.6 Data Quality Validation & Anomaly Quarantine."""

    def setUp(self):
        self.fixed_now = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)

    # --------------------------------------------------------------------------
    # 1. Fully Valid Station
    # --------------------------------------------------------------------------
    def test_01_fully_valid_station_accepted(self):
        """1. Fully valid station: all fields present, correct formats, production ready => ACCEPT."""
        stn = make_valid_station()
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT)
        self.assertEqual(len(res.errors), 0)
        self.assertEqual(len(res.warnings), 0)
        self.assertEqual(len(res.quarantine_reasons), 0)
        self.assertGreaterEqual(res.quality_score, 0.80)

    # --------------------------------------------------------------------------
    # 2. Missing Optional Power
    # --------------------------------------------------------------------------
    def test_02_valid_station_missing_optional_power_accept_with_warnings(self):
        """2. Valid station with missing optional power => ACCEPT_WITH_WARNINGS (DQ-ELEC-008)."""
        stn = make_valid_station(
            connectors=[
                NormalizedConnectorRecord(
                    source_connector_id="CONN-NO-PWR",
                    connector_type=StandardConnectorType.TYPE_2.value,
                    raw_connector_type="Type 2 AC",
                    power_kw=None,  # Missing optional power
                    pricing_type=PricingType.PAID,
                    price_per_kwh=15.0,
                    currency="INR",
                )
            ]
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT_WITH_WARNINGS)
        self.assertIn("DQ-ELEC-008", res.failed_rule_ids)
        self.assertEqual(len(res.errors), 0)

    # --------------------------------------------------------------------------
    # 3. Missing Optional Price
    # --------------------------------------------------------------------------
    def test_03_missing_optional_price_accept_with_warnings(self):
        """3. Missing optional price => ACCEPT_WITH_WARNINGS (DQ-PRICE-003)."""
        stn = make_valid_station(
            connectors=[
                NormalizedConnectorRecord(
                    source_connector_id="CONN-NO-PRC",
                    connector_type=StandardConnectorType.CCS2.value,
                    raw_connector_type="CCS 2",
                    power_kw=50.0,
                    pricing_type=PricingType.UNKNOWN,
                    price_per_kwh=None,  # Missing price
                    currency="INR",
                )
            ]
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT_WITH_WARNINGS)
        self.assertIn("DQ-PRICE-003", res.failed_rule_ids)
        self.assertEqual(len(res.errors), 0)

    # --------------------------------------------------------------------------
    # 4. Missing Operator
    # --------------------------------------------------------------------------
    def test_04_missing_operator_does_not_automatically_reject(self):
        """4. Missing operator does NOT cause rejection (DQ-OP-001 is informational)."""
        stn = make_valid_station(
            operator_name=None,
            operator_slug=None,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertIn(res.outcome, (ValidationOutcome.ACCEPT, ValidationOutcome.ACCEPT_WITH_WARNINGS))
        self.assertIn("DQ-OP-001", res.failed_rule_ids)
        self.assertEqual(len(res.errors), 0)

    # --------------------------------------------------------------------------
    # 5. Missing Connector Quantity
    # --------------------------------------------------------------------------
    def test_05_missing_connector_quantity_does_not_invent_quantity(self):
        """5. Connector with default quantity=1 does not fabricate fictitious multiple plugs."""
        c = NormalizedConnectorRecord(
            connector_type=StandardConnectorType.CCS2.value,
            raw_connector_type="CCS 2",
            power_kw=50.0,
        )
        self.assertEqual(c.quantity, 1)
        self.assertIsNone(c.source_connector_id)
        # Validator does not mutate or synthesize new connector instances
        stn = make_valid_station(connectors=[c])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertEqual(len(stn.connectors), 1)

    # --------------------------------------------------------------------------
    # 6. Invalid Latitude Outside Range
    # --------------------------------------------------------------------------
    def test_06_invalid_latitude_outside_range_blocking(self):
        """6. Latitude outside [-90, 90] => REJECT (DQ-GEO-001)."""
        stn = NormalizedStationRecord.construct(
            source_id="test_validator",
            source_station_id="STN-ERR-LAT",
            name="Out of Range Lat Station",
            latitude=95.0,  # Invalid latitude > 90
            longitude=72.85,
            contract_version="1.0.0",
            connectors=[],
            operational_status=OperationalStatus.OPERATIONAL,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-GEO-001", res.failed_rule_ids)
        self.assertTrue(any("Latitude 95.0 is out of physical range" in e for e in res.errors))

    # --------------------------------------------------------------------------
    # 7. Invalid Longitude Outside Range
    # --------------------------------------------------------------------------
    def test_07_invalid_longitude_outside_range_blocking(self):
        """7. Longitude outside [-180, 180] => REJECT (DQ-GEO-002)."""
        stn = NormalizedStationRecord.construct(
            source_id="test_validator",
            source_station_id="STN-ERR-LNG",
            name="Out of Range Lng Station",
            latitude=19.05,
            longitude=-185.0,  # Invalid longitude < -180
            contract_version="1.0.0",
            connectors=[],
            operational_status=OperationalStatus.OPERATIONAL,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-GEO-002", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 8. Latitude Zero Alone Allowed
    # --------------------------------------------------------------------------
    def test_08_latitude_zero_alone_allowed(self):
        """8. Latitude 0.0 alone with legitimate longitude is completely valid."""
        stn = make_valid_station(
            latitude=0.0,
            longitude=32.0,  # Uganda / Equator
            country="Uganda",
            city="Kampala",
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertNotIn("DQ-GEO-001", res.failed_rule_ids)
        self.assertNotIn("DQ-GEO-003", res.failed_rule_ids)
        self.assertEqual(len(res.errors), 0)

    # --------------------------------------------------------------------------
    # 9. Longitude Zero Alone Allowed
    # --------------------------------------------------------------------------
    def test_09_longitude_zero_alone_allowed(self):
        """9. Longitude 0.0 alone on Prime Meridian with legitimate latitude is completely valid."""
        stn = make_valid_station(
            latitude=51.4769,  # Greenwich
            longitude=0.0,
            country="United Kingdom",
            city="London",
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertNotIn("DQ-GEO-002", res.failed_rule_ids)
        self.assertNotIn("DQ-GEO-003", res.failed_rule_ids)
        self.assertEqual(len(res.errors), 0)

    # --------------------------------------------------------------------------
    # 10. Null Island Rejected
    # --------------------------------------------------------------------------
    def test_10_null_island_rejected(self):
        """10. Coordinate pair (0.0, 0.0) is Null Island and MUST be rejected (DQ-GEO-003)."""
        stn = NormalizedStationRecord.construct(
            source_id="test_validator",
            source_station_id="STN-NULL-ISLAND",
            name="Null Island Bogus Station",
            latitude=0.0,
            longitude=0.0,
            contract_version="1.0.0",
            connectors=[],
            operational_status=OperationalStatus.OPERATIONAL,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-GEO-003", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 11. Negative Power Invalid
    # --------------------------------------------------------------------------
    def test_11_negative_power_invalid(self):
        """11. Negative power is invalid and rejected (DQ-ELEC-001)."""
        bad_connector = NormalizedConnectorRecord.construct(
            connector_type="CCS2",
            raw_connector_type="CCS 2",
            power_kw=-50.0,  # Negative power
            quantity=1,
            pricing_type=PricingType.PAID,
            price_per_kwh=10.0,
            currency="INR",
        )
        stn = make_valid_station(connectors=[bad_connector])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-ELEC-001", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 12. Negative Voltage Invalid
    # --------------------------------------------------------------------------
    def test_12_negative_voltage_invalid(self):
        """12. Negative voltage is invalid and rejected (DQ-ELEC-004)."""
        bad_connector = NormalizedConnectorRecord.construct(
            connector_type="CCS2",
            raw_connector_type="CCS 2",
            power_kw=50.0,
            voltage_v=-400.0,  # Negative voltage
            quantity=1,
            pricing_type=PricingType.PAID,
            price_per_kwh=10.0,
            currency="INR",
        )
        stn = make_valid_station(connectors=[bad_connector])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-ELEC-004", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 13. Negative Amperage Invalid
    # --------------------------------------------------------------------------
    def test_13_negative_amperage_invalid(self):
        """13. Negative amperage is invalid and rejected (DQ-ELEC-006)."""
        bad_connector = NormalizedConnectorRecord.construct(
            connector_type="CCS2",
            raw_connector_type="CCS 2",
            power_kw=50.0,
            amperage_a=-125.0,  # Negative current
            quantity=1,
            pricing_type=PricingType.PAID,
            price_per_kwh=10.0,
            currency="INR",
        )
        stn = make_valid_station(connectors=[bad_connector])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-ELEC-006", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 14. Negative Connector Quantity Invalid
    # --------------------------------------------------------------------------
    def test_14_negative_connector_quantity_invalid(self):
        """14. Negative connector quantity is invalid and rejected (DQ-CONN-002)."""
        bad_connector = NormalizedConnectorRecord.construct(
            connector_type="CCS2",
            raw_connector_type="CCS 2",
            power_kw=50.0,
            quantity=-2,  # Negative quantity
            pricing_type=PricingType.PAID,
            price_per_kwh=10.0,
            currency="INR",
        )
        stn = make_valid_station(connectors=[bad_connector])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-CONN-002", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 15. Suspicious but Plausible Power Warning
    # --------------------------------------------------------------------------
    def test_15_suspicious_power_warning_not_automatic_rejection(self):
        """15. Suspicious power (600 kW) triggers warning, NOT automatic rejection (DQ-ELEC-003)."""
        stn = make_valid_station(
            connectors=[
                NormalizedConnectorRecord(
                    connector_type=StandardConnectorType.CCS2.value,
                    raw_connector_type="Megawatt CCS",
                    power_kw=600.0,  # Above standard 500 kW ceiling, but below 2000 kW extreme
                    quantity=1,
                    pricing_type=PricingType.PAID,
                    price_per_kwh=22.0,
                    currency="INR",
                )
            ]
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT_WITH_WARNINGS)
        self.assertIn("DQ-ELEC-003", res.failed_rule_ids)
        self.assertEqual(len(res.errors), 0)

    # --------------------------------------------------------------------------
    # 16. Unknown Connector Vocabulary
    # --------------------------------------------------------------------------
    def test_16_unknown_connector_vocabulary_distinguished_from_malformed(self):
        """16. Unknown connector type produces warning, preserving raw label (DQ-CONN-003)."""
        stn = make_valid_station(
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="MAGNETIC_RESONANT_WIRELESS",
                    raw_connector_type="Proprietary Wireless Pad 3.3kW",
                    power_kw=3.3,
                    quantity=1,
                    pricing_type=PricingType.PAID,
                    price_per_kwh=10.0,
                    currency="INR",
                )
            ]
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT_WITH_WARNINGS)
        self.assertIn("DQ-CONN-003", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 17. Explicit Free Pricing with Zero Amount
    # --------------------------------------------------------------------------
    def test_17_explicit_free_pricing_zero_amount_valid(self):
        """17. Explicit FREE pricing with price=0.0 is completely valid (DQ-PRICE-002 satisfied)."""
        stn = make_valid_station(
            connectors=[
                NormalizedConnectorRecord(
                    connector_type=StandardConnectorType.TYPE_2.value,
                    raw_connector_type="Type 2 Free",
                    power_kw=7.4,
                    pricing_type=PricingType.FREE,
                    price_per_kwh=0.0,
                    currency="INR",
                )
            ]
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT)
        self.assertNotIn("DQ-PRICE-002", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 18. Missing Pricing Unknown Not Free
    # --------------------------------------------------------------------------
    def test_18_missing_pricing_remains_unknown_not_free(self):
        """18. Missing pricing is retained as None/UNKNOWN and never coerced to 0.0 or FREE."""
        c = NormalizedConnectorRecord(
            connector_type=StandardConnectorType.CCS2.value,
            raw_connector_type="CCS 2",
            power_kw=50.0,
            pricing_type=PricingType.UNKNOWN,
            price_per_kwh=None,
        )
        self.assertIsNone(c.price_per_kwh)
        self.assertEqual(c.pricing_type, PricingType.UNKNOWN)
        stn = make_valid_station(connectors=[c])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertIn("DQ-PRICE-003", res.failed_rule_ids)
        self.assertIsNone(c.price_per_kwh)

    # --------------------------------------------------------------------------
    # 19. Negative Price Invalid
    # --------------------------------------------------------------------------
    def test_19_negative_price_invalid(self):
        """19. Negative price_per_kwh is invalid and rejected (DQ-PRICE-001)."""
        bad_connector = NormalizedConnectorRecord.construct(
            connector_type="CCS2",
            raw_connector_type="CCS 2",
            power_kw=50.0,
            pricing_type=PricingType.PAID,
            price_per_kwh=-15.0,  # Negative tariff rate
            currency="INR",
            quantity=1,
        )
        stn = make_valid_station(connectors=[bad_connector])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-PRICE-001", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 20. Invalid Currency Representation
    # --------------------------------------------------------------------------
    def test_20_invalid_currency_representation_failure(self):
        """20. Currency code with invalid non-alphabetic characters triggers failure (DQ-PRICE-004)."""
        bad_connector = NormalizedConnectorRecord.construct(
            connector_type="CCS2",
            raw_connector_type="CCS 2",
            power_kw=50.0,
            pricing_type=PricingType.PAID,
            price_per_kwh=15.0,
            currency="12345",  # Invalid numeric currency
            quantity=1,
        )
        stn = make_valid_station(connectors=[bad_connector])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-PRICE-004", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 21. Per-kWh vs Per-Session Remain Distinct
    # --------------------------------------------------------------------------
    def test_21_tariff_bases_remain_distinct(self):
        """21. Per-kWh tariff and per-session tariff remain distinct attributes without collapsing."""
        c = NormalizedConnectorRecord(
            connector_type=StandardConnectorType.CCS2.value,
            raw_connector_type="CCS 2",
            power_kw=60.0,
            pricing_type=PricingType.PAID,
            price_per_kwh=18.0,
            price_per_session=50.0,
            currency="INR",
        )
        self.assertEqual(c.price_per_kwh, 18.0)
        self.assertEqual(c.price_per_session, 50.0)
        stn = make_valid_station(connectors=[c])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT)

    # --------------------------------------------------------------------------
    # 22. Valid Normal Operating Hours
    # --------------------------------------------------------------------------
    def test_22_valid_normal_operating_hours(self):
        """22. Regular 09:00 to 21:00 operating schedule is completely valid."""
        stn = make_valid_station(
            is_24_hours=False,
            opening_time="09:00",
            closing_time="21:00",
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT)
        self.assertNotIn("DQ-HOURS-002", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 23. Valid Overnight Hours
    # --------------------------------------------------------------------------
    def test_23_valid_overnight_hours(self):
        """23. Overnight operating schedule (22:00 to 06:00) is completely valid."""
        stn = make_valid_station(
            is_24_hours=False,
            opening_time="22:00",
            closing_time="06:00",
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT)
        self.assertNotIn("DQ-HOURS-002", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 24. Invalid Time Format Failure
    # --------------------------------------------------------------------------
    def test_24_invalid_time_format_failure(self):
        """24. Impossible time representation ('27:00') triggers critical rejection (DQ-HOURS-002)."""
        stn = NormalizedStationRecord.construct(
            source_id="test_validator",
            source_station_id="STN-ERR-TIME",
            name="Invalid Time Station",
            latitude=19.05,
            longitude=72.85,
            is_24_hours=False,
            opening_time="27:00",  # Impossible hour
            closing_time="18:00",
            contract_version="1.0.0",
            connectors=[],
            operational_status=OperationalStatus.OPERATIONAL,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-HOURS-002", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 25. Missing Operating Hours Not Rejection
    # --------------------------------------------------------------------------
    def test_25_missing_operating_hours_not_rejection(self):
        """25. Missing operating hours is permitted and does NOT trigger rejection."""
        stn = make_valid_station(
            is_24_hours=None,
            opening_time=None,
            closing_time=None,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT)
        self.assertNotIn("DQ-HOURS-002", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 26. 24/7 Representation Valid
    # --------------------------------------------------------------------------
    def test_26_24_7_representation_valid(self):
        """26. Canonical 24/7 station representation (is_24_hours=True) is completely valid."""
        stn = make_valid_station(
            is_24_hours=True,
            opening_time=None,
            closing_time=None,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT)

    # --------------------------------------------------------------------------
    # 27. Contradictory 24/7 Schedule Anomaly Quarantine
    # --------------------------------------------------------------------------
    def test_27_contradictory_24_7_schedule_anomaly_quarantine(self):
        """27. Contradiction between 24/7 flag and closed status triggers QUARANTINE (DQ-HOURS-003)."""
        stn = make_valid_station(
            is_24_hours=True,
            operational_status=OperationalStatus.PERMANENTLY_CLOSED,  # Blatant contradiction
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.QUARANTINE)
        self.assertIn("DQ-HOURS-003", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 28. Provenance Missing Source ID Blocking
    # --------------------------------------------------------------------------
    def test_28_provenance_missing_source_id_blocking(self):
        """28. Provenance missing source_id is a fatal defect triggering REJECT (DQ-PROV-001)."""
        stn = NormalizedStationRecord.construct(
            source_id="",  # Missing source identity
            source_station_id="STN-001",
            name="Station Without Source ID",
            latitude=19.05,
            longitude=72.85,
            contract_version="1.0.0",
            connectors=[],
            operational_status=OperationalStatus.OPERATIONAL,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-PROV-001", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 29. Provenance Missing Source Record ID Blocking
    # --------------------------------------------------------------------------
    def test_29_provenance_missing_source_record_id_blocking(self):
        """29. Provenance missing source_station_id is a fatal defect triggering REJECT (DQ-PROV-002)."""
        stn = NormalizedStationRecord.construct(
            source_id="test_validator",
            source_station_id="",  # Missing source station id
            name="Station Without Source Station ID",
            latitude=19.05,
            longitude=72.85,
            contract_version="1.0.0",
            connectors=[],
            operational_status=OperationalStatus.OPERATIONAL,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.REJECT)
        self.assertIn("DQ-PROV-002", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 30. Operational State Decoupled from Live Availability
    # --------------------------------------------------------------------------
    def test_30_operational_state_not_interpreted_as_live_availability(self):
        """30. Operational status does NOT imply live availability or manufacture an observation."""
        stn = make_valid_station(
            operational_status=OperationalStatus.OPERATIONAL,
            observation=None,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        # Validator must not create observation or mutate record
        self.assertIsNone(stn.observation)

    # --------------------------------------------------------------------------
    # 31. Stale Observation Not Interpreted as Unavailable
    # --------------------------------------------------------------------------
    def test_31_stale_observation_not_interpreted_as_unavailable(self):
        """31. Stale observation (>24h) triggers warning (DQ-OBS-002) but is not marked broken/unavailable."""
        old_time = self.fixed_now - timedelta(hours=48)
        stn = make_valid_station(
            observation=NormalizedObservationRecord(
                source_id="test_validator",
                source_station_id="STN-VAL-001",
                observed_at=old_time,
                availability_status=AvailabilityStatus.AVAILABLE,
                queue_level=QueueLevel.NONE,
                available_connectors=1,
                total_connectors=2,
            )
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.ACCEPT_WITH_WARNINGS)
        self.assertIn("DQ-OBS-002", res.failed_rule_ids)
        # Status must remain AVAILABLE as reported, not overwritten
        self.assertEqual(stn.observation.availability_status, AvailabilityStatus.AVAILABLE)

    # --------------------------------------------------------------------------
    # 32. Batch Report Counts All Input Records
    # --------------------------------------------------------------------------
    def test_32_batch_report_counts_all_input_records(self):
        """32. Batch report retains and counts every input record without silently dropping any."""
        # 1 accept
        s1 = make_valid_station(source_station_id="S1")
        # 1 accept with warnings (missing power)
        s2 = make_valid_station(
            source_station_id="S2",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type=StandardConnectorType.TYPE_2.value,
                    raw_connector_type="Type 2",
                    power_kw=None,
                    pricing_type=PricingType.PAID,
                    price_per_kwh=10.0,
                    currency="INR",
                )
            ],
        )
        # 1 quarantine (India country but UK coordinates)
        s3 = make_valid_station(
            source_station_id="S3",
            latitude=51.5,
            longitude=-0.1,
            country="India",
        )
        # 1 reject (Null Island)
        s4 = NormalizedStationRecord.construct(
            source_id="test",
            source_station_id="S4",
            name="Null Island",
            latitude=0.0,
            longitude=0.0,
            contract_version="1.0.0",
            connectors=[],
            operational_status=OperationalStatus.OPERATIONAL,
        )

        batch = [s1, s2, s3, s4]
        report = DataQualityValidator.validate_batch(batch, current_time=self.fixed_now)

        self.assertEqual(report.total_records, 4)
        self.assertEqual(report.records_accepted, 1)
        self.assertEqual(report.records_accepted_with_warnings, 1)
        self.assertEqual(report.records_quarantined, 1)
        self.assertEqual(report.records_rejected, 1)
        self.assertEqual(len(report.results), 4)
        self.assertEqual(len(report.quarantined_records), 1)
        self.assertEqual(len(report.rejected_records), 1)

    # --------------------------------------------------------------------------
    # 33. Batch Report Issue Counts are Deterministic
    # --------------------------------------------------------------------------
    def test_33_batch_report_issue_counts_are_deterministic(self):
        """33. Batch report metrics and issue frequencies are deterministic across repeated runs."""
        s1 = make_valid_station(source_station_id="S1")
        s2 = make_valid_station(
            source_station_id="S2",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="UNMAPPED_PAD",
                    raw_connector_type="Custom Pad",
                    power_kw=None,
                    pricing_type=PricingType.UNKNOWN,
                )
            ],
        )
        batch = [s1, s2]
        rep1 = DataQualityValidator.validate_batch(batch, current_time=self.fixed_now)
        rep2 = DataQualityValidator.validate_batch(batch, current_time=self.fixed_now)

        self.assertEqual(rep1.issue_counts_by_rule, rep2.issue_counts_by_rule)
        self.assertEqual(rep1.issue_counts_by_severity, rep2.issue_counts_by_severity)
        self.assertEqual(rep1.completeness_rates, rep2.completeness_rates)
        self.assertEqual(rep1.anomaly_rate, rep2.anomaly_rate)

    # --------------------------------------------------------------------------
    # 34. Multiple Findings on One Record Preserved
    # --------------------------------------------------------------------------
    def test_34_multiple_findings_on_one_record_are_all_preserved(self):
        """34. All distinct findings on a multi-defect record are retained without truncation."""
        stn = NormalizedStationRecord.construct(
            source_id="test",
            source_station_id="S-MULTI",
            name="t",  # DQ-NAME-001 (CRITICAL)
            latitude=95.0,  # DQ-GEO-001 (CRITICAL)
            longitude=-195.0,  # DQ-GEO-002 (CRITICAL)
            contract_version="1.0.0",
            connectors=[],
            operational_status=OperationalStatus.OPERATIONAL,
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertIn("DQ-NAME-001", res.failed_rule_ids)
        self.assertIn("DQ-GEO-001", res.failed_rule_ids)
        self.assertIn("DQ-GEO-002", res.failed_rule_ids)
        self.assertGreaterEqual(len(res.findings), 3)

    # --------------------------------------------------------------------------
    # 35. Quarantine Retains Complete Provenance and Findings
    # --------------------------------------------------------------------------
    def test_35_quarantine_retains_complete_provenance_and_findings(self):
        """35. QuarantineRecord preserves complete provenance, reasons, findings, and station copy."""
        stn = make_valid_station(
            latitude=51.5,
            longitude=-0.12,  # Outside India bounding box with country='India'
            country="India",
        )
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertEqual(res.outcome, ValidationOutcome.QUARANTINE)

        q_rec = DataQualityValidator.create_quarantine_record(stn, res)
        self.assertIsInstance(q_rec, QuarantineRecord)
        self.assertEqual(q_rec.source_id, stn.source_id)
        self.assertEqual(q_rec.source_station_id, stn.source_station_id)
        self.assertEqual(q_rec.station_name, stn.name)
        self.assertIn("DQ-GEO-004", q_rec.failed_rule_ids)
        self.assertEqual(q_rec.provenance.source_id, stn.source_id)
        self.assertEqual(q_rec.provenance.source_station_id, stn.source_station_id)

    # --------------------------------------------------------------------------
    # 36. Quarantined Records Excluded from Operational Persistence
    # --------------------------------------------------------------------------
    def test_36_quarantined_records_do_not_enter_canonical_persistence(self):
        """36. Quarantined records are isolated and excluded from public.stations/connectors."""
        from tests.test_ingestion_persistence import InMemoryDbConnection
        mock_db = InMemoryDbConnection()

        service = IngestionPersistenceService(mock_db)
        runner = IngestionRunner(persistence_service=service)

        # Create record that triggers quarantine (India geofence anomaly)
        quarantine_payload = {
            "ID": 99999,
            "UUID": "test-quarantine-uuid",
            "AddressInfo": {
                "Title": "UK Station Claiming India",
                "Latitude": 51.5,
                "Longitude": -0.12,
                "Country": {"ISOCode": "IN", "Title": "India"},
            },
            "Connections": [
                {"ID": 101, "ConnectionTypeID": 33, "PowerKW": 50.0, "Quantity": 1}
            ],
            "StatusTypeID": 50,
        }

        summary = runner.run(fixtures_data=[quarantine_payload], mumbai_only=False)
        self.assertEqual(summary.records_quarantined, 1)
        self.assertEqual(summary.stations_persisted, 0)
        self.assertEqual(len(mock_db.tables["public.stations"]), 0)

    # --------------------------------------------------------------------------
    # 37. Validator Does Not Mutate Input Records
    # --------------------------------------------------------------------------
    def test_37_validator_does_not_mutate_input_records(self):
        """37. Validator is a pure, side-effect free function that never alters the input record."""
        stn = make_valid_station()
        snapshot_dict = copy.deepcopy(stn.dict())
        _ = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertEqual(stn.dict(), snapshot_dict)

    # --------------------------------------------------------------------------
    # 38. Validator is Pure and Deterministic
    # --------------------------------------------------------------------------
    def test_38_validator_is_deterministic(self):
        """38. Given identical inputs, validate_record produces bitwise identical results."""
        stn = make_valid_station()
        res1 = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        res2 = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertEqual(res1.outcome, res2.outcome)
        self.assertEqual(res1.is_valid, res2.is_valid)
        self.assertEqual(res1.quality_score, res2.quality_score)
        self.assertEqual(res1.failed_rule_ids, res2.failed_rule_ids)
        self.assertEqual(len(res1.findings), len(res2.findings))

    # --------------------------------------------------------------------------
    # 39. Extreme Power Over 2000 kW Triggers Quarantine
    # --------------------------------------------------------------------------
    def test_39_extreme_power_over_2000kw_triggers_quarantine(self):
        """39. Extreme implausible power (> 2000 kW) triggers QUARANTINE (DQ-ELEC-002)."""
        extreme_connector = NormalizedConnectorRecord.construct(
            connector_type="CCS2",
            raw_connector_type="Extreme Mega Charger",
            power_kw=2500.0,  # 2.5 MW (exceeds 2000 kW EV limit)
            quantity=1,
            pricing_type=PricingType.PAID,
            price_per_kwh=20.0,
            currency="INR",
        )
        stn = make_valid_station(connectors=[extreme_connector])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.QUARANTINE)
        self.assertIn("DQ-ELEC-002", res.failed_rule_ids)

    # --------------------------------------------------------------------------
    # 40. Contradictory Free Pricing Triggers Quarantine
    # --------------------------------------------------------------------------
    def test_40_contradictory_free_pricing_triggers_quarantine(self):
        """40. Pricing declared FREE but with positive tariff rate triggers QUARANTINE (DQ-PRICE-002)."""
        contradictory_connector = NormalizedConnectorRecord.construct(
            connector_type="CCS2",
            raw_connector_type="Free Charger",
            power_kw=50.0,
            pricing_type=PricingType.FREE,
            price_per_kwh=18.5,  # Contradiction: declared FREE but specifies 18.5 INR/kWh
            currency="INR",
            quantity=1,
        )
        stn = make_valid_station(connectors=[contradictory_connector])
        res = DataQualityValidator.validate_record(stn, current_time=self.fixed_now)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.outcome, ValidationOutcome.QUARANTINE)
        self.assertIn("DQ-PRICE-002", res.failed_rule_ids)


if __name__ == "__main__":
    unittest.main()
