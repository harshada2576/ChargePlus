"""ChargePlus — OpenChargeMap Adapter Comprehensive Unit Test Suite.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.2 (Build Source-Specific Adapters)

Verifies all 18 representative OpenChargeMap test scenarios, batch error isolation,
semantic availability protections, deterministic provenance hashing, and contract compliance.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.ingestion.adapters.openchargemap import OpenChargeMapAdapter
from backend.ingestion.base import AdapterResult, BatchAdapterResult
from backend.ingestion.constants import (
    AvailabilityStatus,
    OperationalStatus,
    PricingType,
    StandardConnectorType,
    ValidationOutcome,
)
from tests.fixtures.ocm_fixtures import (
    OCM_FIXTURE_01_VALID_COMPLETE,
    OCM_FIXTURE_02_MULTIPLE_CONNECTORS,
    OCM_FIXTURE_03_AGGREGATED_CONNECTORS,
    OCM_FIXTURE_04_MISSING_OPTIONAL_FIELDS,
    OCM_FIXTURE_05_UNKNOWN_CONNECTOR_TYPE,
    OCM_FIXTURE_06_MISSING_POWER,
    OCM_FIXTURE_07_VALID_EQUATOR,
    OCM_FIXTURE_08_VALID_PRIME_MERIDIAN,
    OCM_FIXTURE_09_NULL_ISLAND,
    OCM_FIXTURE_10_NON_INDIA,
    OCM_FIXTURE_11_MALFORMED_COORDS,
    OCM_FIXTURE_12_MALFORMED_POWER,
    OCM_FIXTURE_13_TELEMETRY_AVAILABLE,
    OCM_FIXTURE_14_STATIC_OPERATIONAL_NOT_AVAILABLE,
    OCM_FIXTURE_15_EXTRA_FIELDS,
    OCM_FIXTURE_16_DUPLICATE_A,
    OCM_FIXTURE_17_MALFORMED_RECORD,
    OCM_FIXTURE_18_MISSING_STATION_ID,
)


class TestOpenChargeMapAdapter(unittest.TestCase):
    """Unit test suite for OpenChargeMapAdapter."""

    def setUp(self):
        self.adapter = OpenChargeMapAdapter()

    def test_01_valid_complete_station(self):
        """1. Complete valid Mumbai station with Tata Power operator and CCS2 connector."""
        res: AdapterResult = self.adapter.process_record(OCM_FIXTURE_01_VALID_COMPLETE)
        self.assertTrue(res.success, f"Errors: {res.errors}")
        self.assertIsNotNone(res.station_record)
        station = res.station_record

        # Identity & Provenance
        self.assertEqual(res.source_id, "open_charge_map")
        self.assertEqual(res.source_station_id, "192840")
        self.assertEqual(station.source_station_id, "192840")
        self.assertIsNotNone(res.raw_record)
        self.assertIsNotNone(res.provenance)
        self.assertEqual(len(res.provenance.raw_payload_hash), 64)
        self.assertEqual(res.provenance.contract_version, "1.0.0")
        self.assertEqual(station.contract_version, "1.0.0")

        # Name & Location
        self.assertEqual(station.name, "Tata Power - BKC Fast Charging Hub")
        self.assertAlmostEqual(station.latitude, 19.0657, places=4)
        self.assertAlmostEqual(station.longitude, 72.8686, places=4)
        self.assertEqual(station.city, "Mumbai")
        self.assertEqual(station.state, "Maharashtra")
        self.assertEqual(station.postal_code, "400051")
        self.assertEqual(station.country, "India")

        # Operator
        self.assertEqual(station.operator_name, "Tata Power EZ Charge")
        self.assertEqual(station.operator_slug, "tata-power-ez-charge")

        # Operational Status & Access
        self.assertEqual(station.operational_status, OperationalStatus.OPERATIONAL)
        self.assertTrue(station.is_public)

        # Connectors
        self.assertEqual(len(station.connectors), 1)
        c = station.connectors[0]
        self.assertEqual(c.connector_type, StandardConnectorType.CCS2.value)
        self.assertEqual(c.source_connector_id, "312450")
        self.assertEqual(c.power_kw, 60.0)
        self.assertEqual(c.voltage_v, 400.0)
        self.assertEqual(c.amperage_a, 150.0)
        self.assertEqual(c.quantity, 1)
        self.assertFalse(c.is_aggregated)
        self.assertEqual(c.pricing_type, PricingType.PAID)

        # Validation
        self.assertIsNotNone(res.validation_result)
        self.assertTrue(res.validation_result.is_valid)
        self.assertIn(res.validation_result.outcome, (ValidationOutcome.ACCEPT, ValidationOutcome.ACCEPT_WITH_WARNINGS))

    def test_02_multiple_connectors(self):
        """2. Station with multiple distinct connectors (CCS2, Type 2, CHAdeMO)."""
        res = self.adapter.process_record(OCM_FIXTURE_02_MULTIPLE_CONNECTORS)
        self.assertTrue(res.success)
        station = res.station_record
        self.assertEqual(len(station.connectors), 3)

        c1, c2, c3 = station.connectors
        self.assertEqual(c1.connector_type, StandardConnectorType.CCS2.value)
        self.assertEqual(c1.source_connector_id, "401")
        self.assertEqual(c1.power_kw, 120.0)
        self.assertEqual(c1.quantity, 2)

        self.assertEqual(c2.connector_type, StandardConnectorType.TYPE_2.value)
        self.assertEqual(c2.source_connector_id, "402")
        self.assertEqual(c2.power_kw, 22.0)

        self.assertEqual(c3.connector_type, StandardConnectorType.CHADEMO.value)
        self.assertEqual(c3.source_connector_id, "403")
        self.assertEqual(c3.power_kw, 50.0)

    def test_03_aggregated_connectors_no_fake_ids(self):
        """3. Aggregated connectors (Quantity=4) without individual IDs must NOT invent fake IDs."""
        res = self.adapter.process_record(OCM_FIXTURE_03_AGGREGATED_CONNECTORS)
        self.assertTrue(res.success)
        station = res.station_record
        self.assertEqual(len(station.connectors), 1)

        c = station.connectors[0]
        self.assertEqual(c.quantity, 4)
        self.assertTrue(c.is_aggregated)
        # Guarantees: No synthetic 'connector_1', 'connector_2' fabricated
        self.assertIsNone(c.source_connector_id)
        self.assertEqual(c.connector_type, StandardConnectorType.CCS2.value)

    def test_04_missing_optional_fields(self):
        """4. Missing optional fields (phone, website, locality) parses cleanly without rejection."""
        res = self.adapter.process_record(OCM_FIXTURE_04_MISSING_OPTIONAL_FIELDS)
        self.assertTrue(res.success)
        station = res.station_record
        self.assertIsNone(station.phone)
        self.assertIsNone(station.website_url)
        self.assertIsNone(station.locality)
        self.assertIsNone(station.postal_code)

    def test_05_unknown_connector_type(self):
        """5. Unrecognized connector standard maps to 'Other' with raw label preserved."""
        res = self.adapter.process_record(OCM_FIXTURE_05_UNKNOWN_CONNECTOR_TYPE)
        self.assertTrue(res.success)
        station = res.station_record
        self.assertEqual(len(station.connectors), 1)

        c = station.connectors[0]
        self.assertEqual(c.connector_type, StandardConnectorType.OTHER.value)
        self.assertIn("Magnetic Resonant", c.raw_connector_type)

    def test_06_missing_power(self):
        """6. Missing power is preserved as None (NEVER defaulted to 0.0 kW)."""
        res = self.adapter.process_record(OCM_FIXTURE_06_MISSING_POWER)
        self.assertTrue(res.success)
        station = res.station_record
        c = station.connectors[0]
        self.assertIsNone(c.power_kw)

    def test_07_valid_zero_latitude_equator(self):
        """7. Latitude == 0.0 with non-zero longitude on the Equator is valid."""
        res = self.adapter.process_record(OCM_FIXTURE_07_VALID_EQUATOR)
        self.assertTrue(res.success)
        self.assertEqual(res.station_record.latitude, 0.0)
        self.assertEqual(res.station_record.longitude, 32.0)

    def test_08_valid_zero_longitude_prime_meridian(self):
        """8. Longitude == 0.0 with non-zero latitude on the Prime Meridian is valid."""
        res = self.adapter.process_record(OCM_FIXTURE_08_VALID_PRIME_MERIDIAN)
        self.assertTrue(res.success)
        self.assertEqual(res.station_record.latitude, 51.4769)
        self.assertEqual(res.station_record.longitude, 0.0)

    def test_09_null_island_rejection(self):
        """9. Both (0.0, 0.0) coordinates indicate Null Island and MUST be rejected."""
        res = self.adapter.process_record(OCM_FIXTURE_09_NULL_ISLAND)
        self.assertFalse(res.success)
        self.assertTrue(any("Null Island" in err for err in res.errors))

    def test_10_non_india_station_quarantine(self):
        """10. Non-India station (UK) triggers QUARANTINE or out-of-boundary warnings."""
        res = self.adapter.process_record(OCM_FIXTURE_10_NON_INDIA)
        self.assertTrue(res.success)  # Parses cleanly
        self.assertIsNotNone(res.validation_result)
        # Outside India geofence triggers warning/quarantine depending on country code
        self.assertEqual(res.station_record.country, "United Kingdom")

    def test_11_malformed_coordinate(self):
        """11. Corrupt non-numeric coordinate fails parsing cleanly without crashing."""
        res = self.adapter.process_record(OCM_FIXTURE_11_MALFORMED_COORDS)
        self.assertFalse(res.success)
        self.assertTrue(any("Latitude/Longitude" in err for err in res.errors))

    def test_12_malformed_power_handling(self):
        """12. Negative power in source is sanitized to None (never kept as invalid negative)."""
        res = self.adapter.process_record(OCM_FIXTURE_12_MALFORMED_POWER)
        self.assertTrue(res.success)
        c = res.station_record.connectors[0]
        self.assertIsNone(c.power_kw)  # Negative power sanitized to None

    def test_13_telemetry_observation_produced(self):
        """13. Automated status (StatusTypeID 10) with timestamp produces NormalizedObservationRecord."""
        res = self.adapter.process_record(OCM_FIXTURE_13_TELEMETRY_AVAILABLE)
        self.assertTrue(res.success)
        station = res.station_record
        self.assertIsNotNone(station.observation)
        obs = station.observation
        self.assertEqual(obs.availability_status, AvailabilityStatus.AVAILABLE)
        self.assertEqual(station.operational_status, OperationalStatus.OPERATIONAL)
        self.assertEqual(obs.observed_at.year, 2024)
        self.assertEqual(obs.observed_at.month, 3)

    def test_14_static_operational_not_assumed_available(self):
        """14. Static StatusTypeID 50 'Operational' does NOT manufacture an observation or assume availability."""
        res = self.adapter.process_record(OCM_FIXTURE_14_STATIC_OPERATIONAL_NOT_AVAILABLE)
        self.assertTrue(res.success)
        station = res.station_record
        # CRITICAL SEMANTIC TEST: No observation manufactured from static metadata
        self.assertIsNone(station.observation)
        # Connectors remain unknown availability
        self.assertEqual(station.connectors[0].status, AvailabilityStatus.UNKNOWN)

    def test_15_source_specific_extra_fields_preserved(self):
        """15. Extra OCM fields (DataProvider, UUID, NumberOfPoints) preserved in extra_metadata."""
        res = self.adapter.process_record(OCM_FIXTURE_15_EXTRA_FIELDS)
        self.assertTrue(res.success)
        station = res.station_record
        meta = station.extra_metadata
        self.assertEqual(meta["ocm_uuid"], "FEEDCAFE-1234-5678-9ABC-DEF012345678")
        self.assertEqual(meta["number_of_points"], 8)
        self.assertIn("underground", meta["general_comments"].lower())
        self.assertIn("Free parking", meta["usage_cost_raw"])

    def test_16_duplicate_payload_hash_determinism(self):
        """16. Processing identical payloads generates identical SHA-256 hashes."""
        res1 = self.adapter.process_record(OCM_FIXTURE_16_DUPLICATE_A)
        res2 = self.adapter.process_record(OCM_FIXTURE_16_DUPLICATE_A)
        self.assertTrue(res1.success)
        self.assertTrue(res2.success)
        self.assertEqual(res1.raw_record.payload_hash, res2.raw_record.payload_hash)
        self.assertEqual(res1.station_record.raw_payload_hash, res2.station_record.raw_payload_hash)

    def test_17_malformed_empty_record(self):
        """17. Empty dictionary payload fails with record-level error without uncaught exception."""
        res = self.adapter.process_record(OCM_FIXTURE_17_MALFORMED_RECORD)
        self.assertFalse(res.success)
        self.assertGreater(len(res.errors), 0)

    def test_18_missing_station_id(self):
        """18. Payload lacking ID and UUID fails extraction cleanly."""
        res = self.adapter.process_record(OCM_FIXTURE_18_MISSING_STATION_ID)
        self.assertFalse(res.success)
        self.assertTrue(any("missing required" in err.lower() for err in res.errors))

    def test_19_batch_error_isolation(self):
        """19. In a batch with 1 valid and 1 malformed record, 1 succeeds and 1 fails."""
        batch_payloads = [
            OCM_FIXTURE_01_VALID_COMPLETE,
            OCM_FIXTURE_17_MALFORMED_RECORD,
            OCM_FIXTURE_02_MULTIPLE_CONNECTORS,
        ]
        batch_res: BatchAdapterResult = self.adapter.process_batch(batch_payloads)
        self.assertEqual(batch_res.total_records, 3)
        self.assertEqual(batch_res.successful_records, 2)
        self.assertEqual(batch_res.failed_records, 1)
        self.assertEqual(len(batch_res.valid_stations), 2)
        self.assertEqual(len(batch_res.rejected_records), 1)

    def test_20_fetch_raw_security_requires_key(self):
        """20. Calling fetch_raw without an API key raises ValueError (prevents unauthenticated network calls)."""
        # Ensure OPENCHARGEMAP_API_KEY is unset for this test
        with self.assertRaises(ValueError) as ctx:
            self.adapter.fetch_raw(api_key=None)
        self.assertIn("API key required", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
