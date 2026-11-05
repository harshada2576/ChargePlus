"""Focused offline tests for the separate, unverified price-estimate path."""

import unittest

from backend.ingestion.constants import PricingType
from backend.ingestion.contracts import NormalizedConnectorRecord, NormalizedStationRecord
from backend.ingestion.normalization import normalize_station_record, parse_price_estimate


class TestParsePriceEstimate(unittest.TestCase):
    def test_accepts_unambiguous_inr_per_kwh(self):
        self.assertEqual(parse_price_estimate("₹18.50 per kWh + GST"), 18.50)
        self.assertEqual(parse_price_estimate("INR 21/kWh"), 21.00)
        self.assertEqual(parse_price_estimate("Rs. 15.25 per kWh"), 15.25)
        self.assertEqual(parse_price_estimate("18/kWh"), 18.00)

    def test_rejects_missing_or_ambiguous_text(self):
        for text in (
            None, "", "   ", "Contact operator", "Price on request", "₹15-₹20/kWh",
            "between ₹15 and ₹20 per kWh", "₹2/min", "₹10 per minute", "₹5/min",
            "₹50 per session", "₹100 parking charges",
            "Free parking for first 2 hours, then ₹50/hr",
            "₹18/kWh and ₹30/session", "USD 0.25/kWh", "€0.25/kWh", "£18/kWh",
            "AED 20/kWh", "₹501/kWh", "₹0/kWh", "0/kWh", "-₹18/kWh",
            "₹18/kWh + ₹2 fee", "₹18/kWh + 18% GST", "₹18/kWh; 20/kWh",
            "₹18/kWh, ₹20/kWh", "₹ab/kWh", "₹/kWh", "Free charging ₹18/kWh",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_price_estimate(text))

    def test_rejects_non_string_and_oversized_text(self):
        for text in (18.5, 18, 0, ["₹18/kWh"], {"rate": "₹18/kWh"}, "₹18/kWh" * 200):
            with self.subTest(text=text):
                self.assertIsNone(parse_price_estimate(text))

    def test_accepts_supported_inr_variants(self):
        self.assertEqual(parse_price_estimate("RS 20 PER KWH"), 20.00)
        self.assertEqual(parse_price_estimate("INR 18.50/kWh (incl. taxes)"), 18.50)
        self.assertEqual(parse_price_estimate("₹500/kWh"), 500.00)

    def test_normalization_keeps_estimate_out_of_verified_tariff_fields(self):
        record = NormalizedStationRecord(
            source_id="open_charge_map",
            source_station_id="estimate-test-1",
            name="Estimate Test Station",
            latitude=19.05,
            longitude=72.85,
            connectors=[NormalizedConnectorRecord(
                connector_type="CCS2",
                raw_connector_type="CCS Type 2",
                power_kw=60,
                pricing_type=PricingType.PAID,
            )],
            extra_metadata={"usage_cost_raw": "₹18.50 per kWh + GST"},
        )
        result = normalize_station_record(record)
        connector = result.station_record.connectors[0]
        self.assertIsNone(connector.price_per_kwh)
        self.assertEqual(connector.pricing_type, PricingType.PAID)
        self.assertEqual(connector.price_estimate_per_kwh, 18.50)
        self.assertEqual(connector.price_estimate_raw, "₹18.50 per kWh + GST")
        self.assertEqual(connector.price_estimate_source, "ocm_usage_cost")

    def test_explicit_free_text_does_not_create_estimate(self):
        record = NormalizedStationRecord(
            source_id="open_charge_map",
            source_station_id="estimate-test-free",
            name="Free Test Station",
            latitude=19.05,
            longitude=72.85,
            connectors=[NormalizedConnectorRecord(
                connector_type="CCS2",
                raw_connector_type="CCS Type 2",
                power_kw=60,
                pricing_type=PricingType.FREE,
                price_per_kwh=0,
            )],
            extra_metadata={"usage_cost_raw": "Free charging"},
        )
        result = normalize_station_record(record)
        connector = result.station_record.connectors[0]
        self.assertEqual(connector.price_per_kwh, 0)
        self.assertIsNone(connector.price_estimate_per_kwh)


class TestEstimateNormalizationGating(unittest.TestCase):
    """Station-level OCM UsageCost is stamped per connector with provenance."""

    def _record(self, **kwargs):
        defaults = dict(
            source_id="open_charge_map",
            source_station_id="estimate-gate-1",
            name="Gating Test Station",
            latitude=19.05,
            longitude=72.85,
        )
        defaults.update(kwargs)
        return NormalizedStationRecord(**defaults)

    def _connector(self, **kwargs):
        defaults = dict(
            connector_type="CCS2",
            raw_connector_type="CCS Type 2",
            power_kw=60,
        )
        defaults.update(kwargs)
        return NormalizedConnectorRecord(**defaults)

    def test_station_level_cost_stamped_on_every_connector(self):
        record = self._record(
            connectors=[self._connector(), self._connector(connector_type="Type 2")],
            extra_metadata={"usage_cost_raw": "₹18.50 per kWh + GST"},
        )
        result = normalize_station_record(record)
        self.assertEqual(len(result.station_record.connectors), 2)
        for connector in result.station_record.connectors:
            with self.subTest(connector=connector.connector_type):
                self.assertEqual(connector.price_estimate_per_kwh, 18.50)
                self.assertEqual(connector.price_estimate_raw, "₹18.50 per kWh + GST")
                self.assertEqual(connector.price_estimate_source, "ocm_usage_cost")
                self.assertIsNone(connector.price_per_kwh)

    def test_non_ocm_source_never_receives_ocm_estimate(self):
        record = self._record(
            source_id="other_source",
            connectors=[self._connector()],
            extra_metadata={"usage_cost_raw": "₹18.50 per kWh + GST"},
        )
        result = normalize_station_record(record)
        connector = result.station_record.connectors[0]
        self.assertIsNone(connector.price_estimate_per_kwh)
        self.assertIsNone(connector.price_estimate_raw)
        self.assertIsNone(connector.price_estimate_source)

    def test_existing_verified_tariff_suppresses_estimate(self):
        record = self._record(
            connectors=[self._connector(
                pricing_type=PricingType.PAID, price_per_kwh=22.00)],
            extra_metadata={"usage_cost_raw": "₹18.50 per kWh + GST"},
        )
        result = normalize_station_record(record)
        connector = result.station_record.connectors[0]
        self.assertEqual(connector.price_per_kwh, 22.00)
        self.assertIsNone(connector.price_estimate_per_kwh)

    def test_free_connector_suppresses_paid_estimate(self):
        record = self._record(
            connectors=[self._connector(
                pricing_type=PricingType.FREE, price_per_kwh=0)],
            extra_metadata={"usage_cost_raw": "₹18.50 per kWh + GST"},
        )
        result = normalize_station_record(record)
        connector = result.station_record.connectors[0]
        self.assertEqual(connector.price_per_kwh, 0)
        self.assertIsNone(connector.price_estimate_per_kwh)

    def test_unparseable_ocm_text_retains_source_marker_for_clearing(self):
        # (None, raw, ocm_usage_cost) lets an OCM refresh clear a stale
        # estimate at persistence instead of preserving it.
        record = self._record(
            connectors=[self._connector(pricing_type=PricingType.PAID)],
            extra_metadata={"usage_cost_raw": "Contact operator"},
        )
        result = normalize_station_record(record)
        connector = result.station_record.connectors[0]
        self.assertIsNone(connector.price_estimate_per_kwh)
        self.assertEqual(connector.price_estimate_source, "ocm_usage_cost")


if __name__ == "__main__":
    unittest.main()
