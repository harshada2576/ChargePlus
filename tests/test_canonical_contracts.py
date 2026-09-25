"""ChargePlus — Canonical Input Contract & Data Quality Unit Tests.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.1 (Define Canonical Station/Connector Input Contract)

Tests all 17 required contract scenarios:
1. Valid station
2. Missing optional field
3. Missing required field
4. Invalid latitude
5. Invalid longitude
6. Invalid power
7. Unknown connector type
8. Multiple connectors
9. Aggregated connector count
10. Missing availability
11. Stale timestamp
12. Invalid timestamp
13. Duplicate source record
14. Source-specific extra fields
15. Provenance missing
16. Null/unknown values
17. Contract version
"""

import unittest
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError

from backend.ingestion.constants import (
    CONTRACT_VERSION,
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
    RawSourceRecord,
)
from backend.ingestion.validation import DataQualityValidator


class TestCanonicalContracts(unittest.TestCase):
    """Unit test suite for Phase 2 Step 2.1 Canonical Input Contracts."""

    def test_01_valid_station(self):
        """1. Valid station: fully compliant Mumbai station record."""
        station = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-MUM-001",
            name="Tata Power - Bandra Kurla Complex Hub",
            operator_name="Tata Power EZ Charge",
            operator_slug="tata-power",
            latitude=19.0657,
            longitude=72.8687,
            address_line="G Block, BKC Road",
            locality="Bandra Kurla Complex",
            city="Mumbai",
            state="Maharashtra",
            postal_code="400051",
            country="India",
            is_24_hours=True,
            is_public=True,
            operational_status=OperationalStatus.OPERATIONAL,
            phone="+91-22-6717-1000",
            website_url="https://tatapower.com/ev",
            connectors=[
                NormalizedConnectorRecord(
                    source_connector_id="CONN-01",
                    connector_type=StandardConnectorType.CCS2.value,
                    raw_connector_type="CCS-2 (DC Fast)",
                    power_kw=60.0,
                    quantity=2,
                    pricing_type=PricingType.PAID,
                    price_per_kwh=18.50,
                    currency="INR",
                )
            ],
            observation=NormalizedObservationRecord(
                source_id="test_adapter",
                source_station_id="STN-MUM-001",
                observed_at=datetime.now(timezone.utc) - timedelta(minutes=10),
                availability_status=AvailabilityStatus.AVAILABLE,
                queue_level=QueueLevel.NONE,
                available_connectors=1,
                total_connectors=2,
                raw_status_label="Available",
            ),
        )
        result = DataQualityValidator.validate_record(station)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.outcome, ValidationOutcome.ACCEPT)
        self.assertEqual(len(result.errors), 0)
        self.assertGreaterEqual(result.quality_score, 0.70)

    def test_02_missing_optional_field(self):
        """2. Missing optional field: phone, website, hours missing does NOT cause rejection."""
        station = NormalizedStationRecord(
            source_id="open_charge_map",
            source_station_id="OCM-99120",
            name="Jio-bp pulse Charging Station",
            latitude=19.1136,
            longitude=72.8697,
            locality="Andheri East",
            city="Mumbai",
            state="Maharashtra",
            country="India",
            # phone, website_url, opening_time, is_24_hours are omitted/None
            connectors=[
                NormalizedConnectorRecord(
                    connector_type=StandardConnectorType.TYPE_2.value,
                    raw_connector_type="Type 2 (AC)",
                    power_kw=22.0,
                    quantity=1,
                )
            ],
        )
        result = DataQualityValidator.validate_record(station)
        self.assertTrue(result.is_valid)
        self.assertIn(result.outcome, (ValidationOutcome.ACCEPT, ValidationOutcome.ACCEPT_WITH_WARNINGS))
        self.assertEqual(len(result.errors), 0)
        self.assertIsNone(station.phone)
        self.assertIsNone(station.website_url)

    def test_03_missing_required_field(self):
        """3. Missing required field: missing latitude or name raises ValidationError."""
        # Missing latitude
        with self.assertRaises(ValidationError):
            NormalizedStationRecord(
                source_id="test_adapter",
                source_station_id="STN-ERR-01",
                name="Station Without Coordinates",
                longitude=72.85,
                # latitude is omitted
            )

        # Missing station name
        with self.assertRaises(ValidationError):
            NormalizedStationRecord(
                source_id="test_adapter",
                source_station_id="STN-ERR-02",
                name="",  # Empty name
                latitude=19.05,
                longitude=72.85,
            )

    def test_04_invalid_latitude(self):
        """4. Invalid latitude: latitude > 90 or < -90 rejected, but 0.0 on Equator is valid."""
        # > 90 rejected
        with self.assertRaises(ValidationError):
            NormalizedStationRecord(
                source_id="test_adapter",
                source_station_id="STN-LAT-ERR-1",
                name="Invalid Lat Station High",
                latitude=95.1234,  # Out of bounds
                longitude=72.85,
            )

        # < -90 rejected
        with self.assertRaises(ValidationError):
            NormalizedStationRecord(
                source_id="test_adapter",
                source_station_id="STN-LAT-ERR-2",
                name="Invalid Lat Station Low",
                latitude=-91.0,  # Out of bounds
                longitude=72.85,
            )

        # 0.0 on Equator with non-zero longitude is VALID
        equator_stn = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-EQUATOR-01",
            name="Equator Research Station",
            latitude=0.0,  # Exactly on the Equator
            longitude=30.0,
            city="Equatoria",
            state="Central",
            country="Uganda",
        )
        self.assertEqual(equator_stn.latitude, 0.0)

    def test_05_invalid_longitude(self):
        """5. Invalid longitude: longitude > 180 or < -180 rejected, but 0.0 on Prime Meridian is valid. (0,0) Null Island rejected."""
        # > 180 rejected
        with self.assertRaises(ValidationError):
            NormalizedStationRecord(
                source_id="test_adapter",
                source_station_id="STN-LNG-ERR-1",
                name="Invalid Lng Station High",
                latitude=19.05,
                longitude=185.0,  # Out of bounds
            )

        # < -180 rejected
        with self.assertRaises(ValidationError):
            NormalizedStationRecord(
                source_id="test_adapter",
                source_station_id="STN-LNG-ERR-2",
                name="Invalid Lng Station Low",
                latitude=19.05,
                longitude=-185.0,  # Out of bounds
            )

        # 0.0 on Prime Meridian with non-zero latitude is VALID
        meridian_stn = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-MERIDIAN-01",
            name="Greenwich Observatory Charger",
            latitude=51.4769,
            longitude=0.0,  # Exactly on the Prime Meridian
            city="London",
            state="Greater London",
            country="United Kingdom",
        )
        self.assertEqual(meridian_stn.longitude, 0.0)

        # BOTH (0.0, 0.0) together is Null Island -> REJECTED
        with self.assertRaises(ValidationError):
            NormalizedStationRecord(
                source_id="test_adapter",
                source_station_id="STN-NULL-ISLAND",
                name="Null Island Bogus Station",
                latitude=0.0,
                longitude=0.0,
            )

    def test_06_invalid_power(self):
        """6. Invalid power: power <= 0 kW rejected; never silently converted to 0 kW."""
        with self.assertRaises(ValidationError):
            NormalizedConnectorRecord(
                connector_type="CCS2",
                raw_connector_type="CCS 2",
                power_kw=0.0,  # Invalid zero power
            )

        with self.assertRaises(ValidationError):
            NormalizedConnectorRecord(
                connector_type="CCS2",
                raw_connector_type="CCS 2",
                power_kw=-25.0,  # Negative power
            )

    def test_07_unknown_connector_type(self):
        """7. Unknown connector type: preserves raw label and accepts with warning."""
        connector = NormalizedConnectorRecord(
            connector_type="Proprietary-Plug-X",
            raw_connector_type="Tesla Supercharger V4 (Proprietary)",
            power_kw=250.0,
            quantity=1,
        )
        station = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-CUSTOM-01",
            name="Supercharger Station",
            latitude=19.05,
            longitude=72.85,
            connectors=[connector],
        )
        result = DataQualityValidator.validate_record(station)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.outcome, ValidationOutcome.ACCEPT_WITH_WARNINGS)
        self.assertTrue(any("unmapped connector_type" in w for w in result.warnings))
        self.assertEqual(connector.raw_connector_type, "Tesla Supercharger V4 (Proprietary)")

    def test_08_multiple_connectors(self):
        """8. Multiple connectors: supports multiple distinct connector standards per station."""
        connectors = [
            NormalizedConnectorRecord(
                source_connector_id="C1",
                connector_type=StandardConnectorType.CCS2.value,
                raw_connector_type="CCS-2",
                power_kw=120.0,
                quantity=2,
            ),
            NormalizedConnectorRecord(
                source_connector_id="C2",
                connector_type=StandardConnectorType.CHADEMO.value,
                raw_connector_type="CHAdeMO",
                power_kw=50.0,
                quantity=1,
            ),
            NormalizedConnectorRecord(
                source_connector_id="C3",
                connector_type=StandardConnectorType.TYPE_2.value,
                raw_connector_type="Type 2 AC",
                power_kw=22.0,
                quantity=2,
            ),
        ]
        station = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-MULTI-01",
            name="Multi-Plug BKC Charging Hub",
            latitude=19.06,
            longitude=72.86,
            connectors=connectors,
        )
        result = DataQualityValidator.validate_record(station)
        self.assertTrue(result.is_valid)
        self.assertEqual(len(station.connectors), 3)

    def test_09_aggregated_connector_count(self):
        """9. Aggregated connector count: quantity=4 preserved without synthesizing fake plug IDs."""
        connector = NormalizedConnectorRecord(
            source_connector_id=None,  # No individual plug ID
            connector_type=StandardConnectorType.CCS2.value,
            raw_connector_type="4x CCS 60kW",
            power_kw=60.0,
            quantity=4,
            is_aggregated=True,
        )
        self.assertEqual(connector.quantity, 4)
        self.assertTrue(connector.is_aggregated)
        self.assertIsNone(connector.source_connector_id)

    def test_10_missing_availability(self):
        """10. Missing availability: missing availability is stored as None/UNKNOWN, not assumed available."""
        station = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-NO-OBS-01",
            name="Static Station Directory Entry",
            latitude=19.10,
            longitude=72.85,
            observation=None,  # No observation stream
            connectors=[
                NormalizedConnectorRecord(
                    connector_type=StandardConnectorType.CCS2.value,
                    raw_connector_type="CCS2",
                    power_kw=50.0,
                    status=None,  # No connector status
                )
            ],
        )
        self.assertIsNone(station.observation)
        self.assertIsNone(station.connectors[0].status)
        result = DataQualityValidator.validate_record(station)
        self.assertTrue(result.is_valid)

    def test_11_stale_timestamp(self):
        """11. Stale timestamp: observation from 36 hours ago generates stale warning."""
        stale_time = datetime.now(timezone.utc) - timedelta(hours=36)
        obs = NormalizedObservationRecord(
            source_id="test_adapter",
            source_station_id="STN-STALE-01",
            observed_at=stale_time,
            availability_status=AvailabilityStatus.AVAILABLE,
        )
        station = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-STALE-01",
            name="Stale Observation Station",
            latitude=19.10,
            longitude=72.85,
            observation=obs,
        )
        result = DataQualityValidator.validate_record(station)
        self.assertTrue(result.is_valid)
        self.assertTrue(any("stale" in w.lower() for w in result.warnings))

    def test_12_invalid_timestamp(self):
        """12. Invalid timestamp: observation 2 hours in the future is rejected."""
        future_time = datetime.now(timezone.utc) + timedelta(hours=2)
        obs = NormalizedObservationRecord(
            source_id="test_adapter",
            source_station_id="STN-FUT-01",
            observed_at=future_time,
            availability_status=AvailabilityStatus.AVAILABLE,
        )
        station = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-FUT-01",
            name="Future Station",
            latitude=19.10,
            longitude=72.85,
            observation=obs,
        )
        result = DataQualityValidator.validate_record(station)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.outcome, ValidationOutcome.REJECT)
        self.assertTrue(any("in the future" in e for e in result.errors))

    def test_13_duplicate_source_record(self):
        """13. Duplicate source record: identical raw payloads generate identical SHA-256 hashes."""
        payload = {"id": 12345, "name": "BKC Charger", "status": "Available"}
        rec1 = RawSourceRecord(
            source_id="ocm",
            source_station_id="12345",
            raw_payload=payload,
        )
        rec2 = RawSourceRecord(
            source_id="ocm",
            source_station_id="12345",
            raw_payload=payload,
        )
        self.assertEqual(rec1.payload_hash, rec2.payload_hash)

    def test_14_source_specific_extra_fields(self):
        """14. Source-specific extra fields: preserved in extra_metadata without schema distortion."""
        extra = {
            "network_sub_code": "MH-MUM-44",
            "amenities": ["WiFi", "Washroom", "Cafe"],
            "parking_fee_inr": 50,
            "raw_provider_rating": 4.6,
        }
        station = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-EXTRA-01",
            name="Station with Amenities",
            latitude=19.05,
            longitude=72.85,
            extra_metadata=extra,
        )
        self.assertEqual(station.extra_metadata["amenities"], ["WiFi", "Washroom", "Cafe"])
        self.assertEqual(station.extra_metadata["parking_fee_inr"], 50)

    def test_15_provenance_missing(self):
        """15. Provenance missing: empty source_id or source_station_id raises ValidationError."""
        with self.assertRaises(ValidationError):
            NormalizedStationRecord(
                source_id="",  # Empty source ID
                source_station_id="STN-01",
                name="Test Station",
                latitude=19.05,
                longitude=72.85,
            )

        with self.assertRaises(ValidationError):
            RawSourceRecord(
                source_id="",
                source_station_id="123",
                raw_payload={},
            )

    def test_16_null_unknown_values(self):
        """16. Null/unknown values: missing values remain None, never fabricated."""
        station = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-NULLS-01",
            name="Minimal Station",
            latitude=19.05,
            longitude=72.85,
            address_line=None,
            locality=None,
            postal_code=None,
            is_24_hours=None,
            phone=None,
            website_url=None,
            connectors=[
                NormalizedConnectorRecord(
                    connector_type=StandardConnectorType.CCS2.value,
                    raw_connector_type="CCS2",
                    power_kw=None,  # Unknown power
                    price_per_kwh=None,  # Unknown price
                    pricing_type=PricingType.UNKNOWN,
                )
            ],
        )
        self.assertIsNone(station.postal_code)
        self.assertIsNone(station.phone)
        self.assertIsNone(station.connectors[0].power_kw)
        self.assertIsNone(station.connectors[0].price_per_kwh)
        self.assertEqual(station.connectors[0].pricing_type, PricingType.UNKNOWN)

    def test_17_contract_version(self):
        """17. Contract version: version is exposed and defaults to '1.0.0'."""
        self.assertEqual(CONTRACT_VERSION, "1.0.0")
        station = NormalizedStationRecord(
            source_id="test_adapter",
            source_station_id="STN-VER-01",
            name="Versioned Station",
            latitude=19.05,
            longitude=72.85,
        )
        self.assertEqual(station.contract_version, "1.0.0")


if __name__ == "__main__":
    unittest.main()
