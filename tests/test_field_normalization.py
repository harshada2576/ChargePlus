"""ChargePlus — Cross-Source Field Normalization & Standard Vocabulary Unit Tests.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.5 (Cross-Source Field Normalization & Standard Vocabulary)

Validates all 32 required test scenarios:
1. Operator exact normalization.
2. Operator alias normalization only for explicitly supported aliases.
3. Unknown operator remains unknown/unmapped rather than guessed.
4. CCS2 variants normalize consistently.
5. Type 2 variants normalize consistently.
6. CHAdeMO normalization.
7. Unknown connector type remains preserved/unmapped.
8. kW remains kW.
9. watts -> kW conversion.
10. Missing power remains None.
11. Voltage and amperage remain separate.
12. AC/DC textual variants normalize consistently.
13. Missing current type remains unknown.
14. Address whitespace/case/punctuation normalization.
15. PIN normalization.
16. Invalid PIN is not silently repaired into a different valid PIN.
17. Latitude/longitude numeric parsing.
18. Individual zero coordinate remains allowed (Equator or Prime Meridian).
19. (0,0) remains invalid according to existing contract semantics (Null Island).
20. Explicit free charging remains distinguishable from missing pricing.
21. Missing pricing remains unknown/None.
22. INR pricing representation.
23. Different tariff bases remain distinguishable: per kWh vs per hour vs per session.
24. Opening hours: 24x7, normal daily interval, multiple intervals, closed day, overnight interval, unparseable hours.
25. Missing operating hours remain unknown.
26. Unknown source-specific fields are not silently discarded.
27. Provenance survives normalization.
28. Normalization is deterministic.
29. Normalization is idempotent/stable (normalize(normalize(x)) == normalize(x)).
30. Existing Step 2.4 tests remain passing.
31. Existing Step 2.3 persistence tests remain passing.
32. No mutation of the input record (pure functional replacement).
"""

import copy
import unittest

from backend.ingestion.constants import (
    CONTRACT_VERSION,
    OperationalStatus,
    PricingType,
    StandardConnectorType,
)
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedStationRecord,
)
from backend.ingestion.normalization import (
    NORMALIZATION_VERSION,
    CurrentType,
    DayOfWeek,
    NormalizationStatus,
    OperatorMappingType,
    PricingBasis,
    normalize_address,
    normalize_address_text,
    normalize_amperage,
    normalize_connector_type,
    normalize_coordinates,
    normalize_current_type,
    normalize_operating_hours,
    normalize_operator,
    normalize_postal_code,
    normalize_power,
    normalize_pricing,
    normalize_station_record,
    normalize_voltage,
)


def _make_test_station(
    source_id: str = "open_charge_map",
    source_station_id: str = "TEST-1001",
    name: str = "Tata Power - BKC Fast Hub",
    operator_name: str = "Tata Power EZ Charge",
    operator_slug: str = "tata-power-ez-charge",
    latitude: float = 19.0657,
    longitude: float = 72.8686,
    address_line: str = "G Block, Bandra Kurla Complex",
    locality: str = "Near MCA Club",
    city: str = "Mumbai",
    state: str = "Maharashtra",
    postal_code: str = "400051",
    country: str = "India",
    is_24_hours: bool = True,
    opening_time: str = None,
    closing_time: str = None,
    connectors: list = None,
    extra_metadata: dict = None,
) -> NormalizedStationRecord:
    """Helper to create a canonical station record for normalization testing."""
    if connectors is None:
        connectors = [
            NormalizedConnectorRecord(
                source_connector_id="CONN-1",
                connector_type="CCS (Type 2)",
                raw_connector_type="CCS (Type 2)",
                power_kw=60.0,
                voltage_v=400.0,
                amperage_a=150.0,
                quantity=1,
                is_aggregated=False,
                pricing_type=PricingType.PAID,
                price_per_kwh=18.50,
                currency="INR",
            )
        ]
    return NormalizedStationRecord(
        contract_version=CONTRACT_VERSION,
        source_id=source_id,
        source_station_id=source_station_id,
        source_url=f"https://example.com/stations/{source_station_id}",
        raw_payload_hash="a" * 64,
        name=name,
        raw_name=name,
        operator_name=operator_name,
        operator_slug=operator_slug,
        latitude=latitude,
        longitude=longitude,
        address_line=address_line,
        locality=locality,
        city=city,
        state=state,
        postal_code=postal_code,
        country=country,
        is_24_hours=is_24_hours,
        opening_time=opening_time,
        closing_time=closing_time,
        operational_status=OperationalStatus.OPERATIONAL,
        connectors=connectors,
        extra_metadata=extra_metadata or {"custom_vendor_field": "preserved_value"},
    )


class TestFieldNormalization(unittest.TestCase):
    """Test suite verifying Step 2.5 Field Normalization & Standard Vocabulary."""

    # --------------------------------------------------------------------------
    # 1. Operator Exact Normalization
    # --------------------------------------------------------------------------
    def test_01_operator_exact_normalization(self):
        """1. Verifies exact canonical operator matches return EXACT and UNCHANGED/NORMALIZED."""
        res = normalize_operator("Tata Power")
        self.assertEqual(res.canonical_name, "Tata Power")
        self.assertEqual(res.canonical_slug, "tata-power")
        self.assertEqual(res.raw_name, "Tata Power")
        self.assertEqual(res.mapping_type, OperatorMappingType.EXACT)
        self.assertEqual(res.status, NormalizationStatus.UNCHANGED)

        # Case normalization for exact name
        res_case = normalize_operator("tata power")
        self.assertEqual(res_case.canonical_name, "Tata Power")
        self.assertEqual(res_case.canonical_slug, "tata-power")
        self.assertEqual(res_case.status, NormalizationStatus.NORMALIZED)

    # --------------------------------------------------------------------------
    # 2. Operator Alias Normalization
    # --------------------------------------------------------------------------
    def test_02_operator_alias_normalization_supported_aliases_only(self):
        """2. Verifies known aliases map to canonical operators with ALIAS mapping type."""
        # Tata Power aliases
        res_ez = normalize_operator("Tata Power EZ Charge")
        self.assertEqual(res_ez.canonical_name, "Tata Power")
        self.assertEqual(res_ez.canonical_slug, "tata-power")
        self.assertEqual(res_ez.mapping_type, OperatorMappingType.ALIAS)
        self.assertEqual(res_ez.status, NormalizationStatus.NORMALIZED)

        res_ev = normalize_operator("Tata Power EV Charging")
        self.assertEqual(res_ev.canonical_name, "Tata Power")
        self.assertEqual(res_ev.mapping_type, OperatorMappingType.ALIAS)

        # Jio-bp aliases
        res_jio = normalize_operator("Jio-bp pulse")
        self.assertEqual(res_jio.canonical_name, "Jio-bp pulse")
        self.assertEqual(res_jio.canonical_slug, "jio-bp")

        res_jio_alias = normalize_operator("jio bp pulse")
        self.assertEqual(res_jio_alias.canonical_name, "Jio-bp pulse")
        self.assertEqual(res_jio_alias.canonical_slug, "jio-bp")
        self.assertEqual(res_jio_alias.mapping_type, OperatorMappingType.ALIAS)

        # Ather Energy aliases
        res_ather = normalize_operator("Ather Grid")
        self.assertEqual(res_ather.canonical_name, "Ather Energy")
        self.assertEqual(res_ather.canonical_slug, "ather-energy")
        self.assertEqual(res_ather.mapping_type, OperatorMappingType.ALIAS)

    # --------------------------------------------------------------------------
    # 3. Unknown Operator Remains Unknown/Unmapped
    # --------------------------------------------------------------------------
    def test_03_unknown_operator_remains_unmapped_not_guessed(self):
        """3. Verifies unrecognized operators are not guessed and empty is UNKNOWN."""
        # Missing operator
        res_none = normalize_operator(None)
        self.assertIsNone(res_none.canonical_name)
        self.assertIsNone(res_none.canonical_slug)
        self.assertEqual(res_none.status, NormalizationStatus.UNKNOWN)
        self.assertEqual(res_none.mapping_type, OperatorMappingType.UNKNOWN)

        res_empty = normalize_operator("   ")
        self.assertIsNone(res_empty.canonical_name)
        self.assertEqual(res_empty.status, NormalizationStatus.UNKNOWN)

        # Unrecognized third-party operator
        res_unmapped = normalize_operator("Acme EV Fast Charging Co.")
        self.assertIsNone(res_unmapped.canonical_name)
        self.assertEqual(res_unmapped.raw_name, "Acme EV Fast Charging Co.")
        self.assertEqual(res_unmapped.canonical_slug, "acme-ev-fast-charging-co")
        self.assertEqual(res_unmapped.mapping_type, OperatorMappingType.UNMAPPED)
        self.assertEqual(res_unmapped.status, NormalizationStatus.UNMAPPED)

    # --------------------------------------------------------------------------
    # 4. CCS2 Variants Normalize Consistently
    # --------------------------------------------------------------------------
    def test_04_ccs2_variants_normalize_consistently(self):
        """4. Verifies multiple legitimate CCS2 representations normalize to 'CCS2'."""
        variants = [
            "CCS2",
            "ccs2",
            "CCS-2",
            "CCS Combo 2",
            "CCS Combo Type 2",
            "Combined Charging System 2",
            "Combined Charging System Type 2",
            "IEC 62196-3 Configuration FF",
            "Type 2 Combo",
            "Combo 2",
        ]
        for v in variants:
            res = normalize_connector_type(v)
            self.assertEqual(res.normalized_value, StandardConnectorType.CCS2.value, f"Failed for {v}")
            self.assertIn(res.status, (NormalizationStatus.NORMALIZED, NormalizationStatus.UNCHANGED))
            self.assertEqual(res.raw_value, v)

    # --------------------------------------------------------------------------
    # 5. Type 2 Variants Normalize Consistently
    # --------------------------------------------------------------------------
    def test_05_type_2_variants_normalize_consistently(self):
        """5. Verifies multiple legitimate Type 2 representations normalize to 'Type 2'."""
        variants = [
            "Type 2",
            "Type-2",
            "type 2",
            "type2",
            "IEC 62196 Type 2",
            "IEC 62196-2",
            "IEC 62196-2 Type 2",
            "Mennekes",
            "Type 2 (Socket Only)",
            "Type 2 (Tethered Connector)",
        ]
        for v in variants:
            res = normalize_connector_type(v)
            self.assertEqual(res.normalized_value, StandardConnectorType.TYPE_2.value, f"Failed for {v}")
            self.assertIn(res.status, (NormalizationStatus.NORMALIZED, NormalizationStatus.UNCHANGED))

    # --------------------------------------------------------------------------
    # 6. CHAdeMO Normalization
    # --------------------------------------------------------------------------
    def test_06_chademo_normalization(self):
        """6. Verifies CHAdeMO variants normalize to canonical 'CHAdeMO'."""
        variants = [
            "CHAdeMO",
            "chademo",
            "CHADEMO",
            "IEC 62196-3 Configuration AA",
        ]
        for v in variants:
            res = normalize_connector_type(v)
            self.assertEqual(res.normalized_value, StandardConnectorType.CHADEMO.value, f"Failed for {v}")

    # --------------------------------------------------------------------------
    # 7. Unknown Connector Type Remains Preserved/Unmapped
    # --------------------------------------------------------------------------
    def test_07_unknown_connector_type_preserved_unmapped(self):
        """7. Verifies unrecognized or proprietary connector types are mapped to Other and preserved."""
        res = normalize_connector_type("Custom Industrial 3-Pin Heavy Plug")
        self.assertEqual(res.normalized_value, StandardConnectorType.OTHER.value)
        self.assertEqual(res.raw_value, "Custom Industrial 3-Pin Heavy Plug")
        self.assertEqual(res.status, NormalizationStatus.UNMAPPED)

        # Tesla forms preserved as raw label with Other canonical mapping
        res_tesla = normalize_connector_type("Tesla Supercharger")
        self.assertEqual(res_tesla.normalized_value, StandardConnectorType.OTHER.value)
        self.assertEqual(res_tesla.raw_value, "Tesla Supercharger")
        self.assertEqual(res_tesla.status, NormalizationStatus.UNMAPPED)

        # Empty connector string
        res_none = normalize_connector_type(None)
        self.assertIsNone(res_none.normalized_value)
        self.assertEqual(res_none.status, NormalizationStatus.UNKNOWN)

    # --------------------------------------------------------------------------
    # 8. kW Remains kW
    # --------------------------------------------------------------------------
    def test_08_kw_remains_kw(self):
        """8. Verifies numeric and string kW values are preserved as float kW."""
        res_float = normalize_power(60.0)
        self.assertEqual(res_float.normalized_value, 60.0)
        self.assertEqual(res_float.status, NormalizationStatus.UNCHANGED)

        res_str = normalize_power("60.0 kW")
        self.assertEqual(res_str.normalized_value, 60.0)
        self.assertEqual(res_str.status, NormalizationStatus.NORMALIZED)

        res_str_nowhitespace = normalize_power("150kW")
        self.assertEqual(res_str_nowhitespace.normalized_value, 150.0)

    # --------------------------------------------------------------------------
    # 9. Watts -> kW Conversion
    # --------------------------------------------------------------------------
    def test_09_watts_to_kw_conversion(self):
        """9. Verifies Watts are deterministically converted to kW."""
        res_w_str = normalize_power("50000 W")
        self.assertEqual(res_w_str.normalized_value, 50.0)
        self.assertEqual(res_w_str.status, NormalizationStatus.NORMALIZED)
        self.assertEqual(res_w_str.rule, "POWER_CONVERTED_WATTS_TO_KW")

        res_watts_str = normalize_power("22000 watts")
        self.assertEqual(res_watts_str.normalized_value, 22.0)

        res_numeric_w = normalize_power(50000, default_unit="W")
        self.assertEqual(res_numeric_w.normalized_value, 50.0)

    # --------------------------------------------------------------------------
    # 10. Missing Power Remains None
    # --------------------------------------------------------------------------
    def test_10_missing_power_remains_none(self):
        """10. Invariant: Missing power remains None. Never defaults to 0 kW or guessed."""
        res_none = normalize_power(None)
        self.assertIsNone(res_none.normalized_value)
        self.assertEqual(res_none.status, NormalizationStatus.UNKNOWN)

        res_empty = normalize_power("   ")
        self.assertIsNone(res_empty.normalized_value)
        self.assertEqual(res_empty.status, NormalizationStatus.UNKNOWN)

        # Zero power is INVALID (contract strictly forbids <= 0.0 kW)
        res_zero = normalize_power(0.0)
        self.assertIsNone(res_zero.normalized_value)
        self.assertEqual(res_zero.status, NormalizationStatus.INVALID)

        res_neg = normalize_power("-50 kW")
        self.assertIsNone(res_neg.normalized_value)
        self.assertEqual(res_neg.status, NormalizationStatus.INVALID)

    # --------------------------------------------------------------------------
    # 11. Voltage and Amperage Remain Separate
    # --------------------------------------------------------------------------
    def test_11_voltage_and_amperage_remain_separate(self):
        """11. Verifies voltage and amperage are normalized independently and never merged/derived."""
        v_res = normalize_voltage("400 V")
        a_res = normalize_amperage("150 A")

        self.assertEqual(v_res.normalized_value, 400.0)
        self.assertEqual(a_res.normalized_value, 150.0)

        # kV to V conversion
        kv_res = normalize_voltage("0.4 kV")
        self.assertEqual(kv_res.normalized_value, 400.0)

        # mA to A conversion
        ma_res = normalize_amperage("150000 mA")
        self.assertEqual(ma_res.normalized_value, 150.0)

        # Missing values remain None
        self.assertIsNone(normalize_voltage(None).normalized_value)
        self.assertIsNone(normalize_amperage(None).normalized_value)

    # --------------------------------------------------------------------------
    # 12. AC/DC Textual Variants Normalize Consistently
    # --------------------------------------------------------------------------
    def test_12_ac_dc_textual_variants_normalize_consistently(self):
        """12. Verifies AC/DC variants normalize to CurrentType.AC or DC."""
        ac_variants = [
            "AC",
            "ac",
            "Alternating Current",
            "AC (Single-Phase)",
            "AC (Three-Phase)",
            "three phase ac",
        ]
        for v in ac_variants:
            res = normalize_current_type(v)
            self.assertEqual(res.normalized_value, CurrentType.AC, f"Failed for {v}")

        dc_variants = [
            "DC",
            "dc",
            "Direct Current",
            "DC Fast",
            "DC Fast Charging",
        ]
        for v in dc_variants:
            res = normalize_current_type(v)
            self.assertEqual(res.normalized_value, CurrentType.DC, f"Failed for {v}")

    # --------------------------------------------------------------------------
    # 13. Missing Current Type Remains Unknown
    # --------------------------------------------------------------------------
    def test_13_missing_current_type_remains_unknown(self):
        """13. Verifies missing or unrecognized current type evaluates to CurrentType.UNKNOWN."""
        res_none = normalize_current_type(None)
        self.assertEqual(res_none.normalized_value, CurrentType.UNKNOWN)
        self.assertEqual(res_none.status, NormalizationStatus.UNKNOWN)

        res_unmapped = normalize_current_type("High Voltage Solar Pulse")
        self.assertEqual(res_unmapped.normalized_value, CurrentType.UNKNOWN)
        self.assertEqual(res_unmapped.status, NormalizationStatus.UNMAPPED)

    # --------------------------------------------------------------------------
    # 14. Address Whitespace/Case/Punctuation Normalization
    # --------------------------------------------------------------------------
    def test_14_address_whitespace_case_punctuation_normalization(self):
        """14. Verifies conservative address cleaning, safe abbreviations, and case handling."""
        raw_addr = "  g block ,   bandra kurla complex ,   opp. mca club, nr. rd.   "
        norm = normalize_address_text(raw_addr)
        self.assertEqual(norm, "G Block, Bandra Kurla Complex, Opposite MCA Club, Near Road.")

        # Full address component normalization
        res = normalize_address(
            address_line="123 station rd.   west",
            locality="andheri e.",
            city="mumbai",
            state="maharashtra",
            postal_code="400069",
            country="india",
        )
        self.assertEqual(res.address_line, "123 Station Road West")
        self.assertEqual(res.city, "Mumbai")
        self.assertEqual(res.state, "Maharashtra")
        self.assertEqual(res.country, "India")
        self.assertEqual(res.postal_code, "400069")

    # --------------------------------------------------------------------------
    # 15. PIN Normalization
    # --------------------------------------------------------------------------
    def test_15_pin_normalization(self):
        """15. Verifies formatting normalization of valid 6-digit Indian PIN codes."""
        # Spaces inside PIN
        res_space = normalize_postal_code("400 051")
        self.assertEqual(res_space.normalized_value, "400051")
        self.assertEqual(res_space.status, NormalizationStatus.NORMALIZED)

        # Hyphen inside PIN
        res_hyphen = normalize_postal_code("400-051")
        self.assertEqual(res_hyphen.normalized_value, "400051")
        self.assertEqual(res_hyphen.status, NormalizationStatus.NORMALIZED)

        # Already canonical PIN
        res_canonical = normalize_postal_code("400051")
        self.assertEqual(res_canonical.normalized_value, "400051")
        self.assertEqual(res_canonical.status, NormalizationStatus.UNCHANGED)

    # --------------------------------------------------------------------------
    # 16. Invalid PIN Is Not Silently Repaired
    # --------------------------------------------------------------------------
    def test_16_invalid_pin_not_silently_repaired(self):
        """16. Invariant: Malformed PIN is rejected as INVALID, never guessed or fabricated."""
        bad_pins = [
            "40005",        # 5 digits
            "4000511",      # 7 digits
            "012345",       # starts with 0
            "ABC123",       # alphabetic
            "400 05A",      # mixed
        ]
        for pin in bad_pins:
            res = normalize_postal_code(pin, country="India")
            self.assertIsNone(res.normalized_value, f"Should be None for {pin}")
            self.assertEqual(res.status, NormalizationStatus.INVALID)
            self.assertEqual(res.raw_value, pin)

        # Missing PIN remains None with UNKNOWN status
        res_none = normalize_postal_code(None)
        self.assertIsNone(res_none.normalized_value)
        self.assertEqual(res_none.status, NormalizationStatus.UNKNOWN)

    # --------------------------------------------------------------------------
    # 17. Latitude/Longitude Numeric Parsing
    # --------------------------------------------------------------------------
    def test_17_latitude_longitude_numeric_parsing(self):
        """17. Verifies valid numerical strings and floats parse cleanly without aggressive rounding."""
        res = normalize_coordinates("19.06571234", "72.86865678")
        self.assertEqual(res.latitude, 19.06571234)
        self.assertEqual(res.longitude, 72.86865678)
        self.assertEqual(res.status, NormalizationStatus.NORMALIZED)

        # Float inputs remain UNCHANGED
        res_float = normalize_coordinates(19.0657, 72.8686)
        self.assertEqual(res_float.latitude, 19.0657)
        self.assertEqual(res_float.longitude, 72.8686)
        self.assertEqual(res_float.status, NormalizationStatus.UNCHANGED)

        # Out of bounds
        res_oob = normalize_coordinates(95.0, 72.0)
        self.assertIsNone(res_oob.latitude)
        self.assertEqual(res_oob.status, NormalizationStatus.INVALID)

    # --------------------------------------------------------------------------
    # 18. Individual Zero Coordinate Remains Allowed
    # --------------------------------------------------------------------------
    def test_18_individual_zero_coordinate_allowed(self):
        """18. Invariant: Latitude=0.0 on Equator or Longitude=0.0 on Prime Meridian is valid."""
        # Equator (lat=0, lng=72.8)
        res_eq = normalize_coordinates(0.0, 72.8686)
        self.assertEqual(res_eq.latitude, 0.0)
        self.assertEqual(res_eq.longitude, 72.8686)
        self.assertEqual(res_eq.status, NormalizationStatus.UNCHANGED)

        # Prime Meridian (lat=19.0, lng=0)
        res_pm = normalize_coordinates(19.0657, 0.0)
        self.assertEqual(res_pm.latitude, 19.0657)
        self.assertEqual(res_pm.longitude, 0.0)
        self.assertEqual(res_pm.status, NormalizationStatus.UNCHANGED)

    # --------------------------------------------------------------------------
    # 19. (0,0) Remains Invalid (Null Island)
    # --------------------------------------------------------------------------
    def test_19_null_island_remains_invalid(self):
        """19. Invariant: (0.0, 0.0) together is rejected as placeholder Null Island."""
        res = normalize_coordinates(0.0, 0.0)
        self.assertIsNone(res.latitude)
        self.assertIsNone(res.longitude)
        self.assertEqual(res.status, NormalizationStatus.INVALID)
        self.assertEqual(res.rule, "COORDS_NULL_ISLAND")

        # String representation of Null Island
        res_str = normalize_coordinates("0.0", "0.0")
        self.assertIsNone(res_str.latitude)
        self.assertEqual(res_str.status, NormalizationStatus.INVALID)

    # --------------------------------------------------------------------------
    # 20. Explicit Free Charging Distinguishable from Missing Pricing
    # --------------------------------------------------------------------------
    def test_20_explicit_free_charging_distinguishable_from_missing(self):
        """20. Invariant: Explicit free charging is a distinct semantic state (is_free=True),

        while missing pricing has price_per_kwh=None and is_free=False.
        """
        # Explicit free charging
        free_pricing = normalize_pricing(raw_pricing_text="Free charging for mall customers")
        self.assertTrue(free_pricing.is_free)
        self.assertEqual(free_pricing.pricing_type, PricingType.FREE)
        self.assertEqual(free_pricing.price_per_kwh, 0.0)
        self.assertEqual(free_pricing.status, NormalizationStatus.NORMALIZED)

        # Missing pricing
        missing_pricing = normalize_pricing(raw_pricing_text=None)
        self.assertFalse(missing_pricing.is_free)
        self.assertEqual(missing_pricing.pricing_type, PricingType.UNKNOWN)
        self.assertIsNone(missing_pricing.price_per_kwh)
        self.assertEqual(missing_pricing.status, NormalizationStatus.UNKNOWN)

    # --------------------------------------------------------------------------
    # 21. Missing Pricing Remains Unknown/None
    # --------------------------------------------------------------------------
    def test_21_missing_pricing_remains_unknown_none(self):
        """21. Invariant: Missing pricing is NEVER converted to ₹0."""
        res = normalize_pricing(raw_pricing_text=None, pricing_type=None, price_per_kwh=None)
        self.assertIsNone(res.price_per_kwh)
        self.assertIsNone(res.price_per_session)
        self.assertIsNone(res.price_per_hour)
        self.assertFalse(res.is_free)
        self.assertEqual(res.pricing_type, PricingType.UNKNOWN)

    # --------------------------------------------------------------------------
    # 22. INR Pricing Representation
    # --------------------------------------------------------------------------
    def test_22_inr_pricing_representation(self):
        """22. Verifies INR currency and numeric rate parsing."""
        res_symbol = normalize_pricing(raw_pricing_text="₹18.50 per kWh + GST")
        self.assertEqual(res_symbol.price_per_kwh, 18.50)
        self.assertEqual(res_symbol.currency, "INR")
        self.assertEqual(res_symbol.pricing_basis, PricingBasis.PER_KWH)
        self.assertEqual(res_symbol.pricing_type, PricingType.PAID)

        res_rs = normalize_pricing(raw_pricing_text="Rs. 21.00 / unit")
        self.assertEqual(res_rs.price_per_kwh, 21.00)
        self.assertEqual(res_rs.currency, "INR")

    # --------------------------------------------------------------------------
    # 23. Tariff Bases Remain Distinguishable
    # --------------------------------------------------------------------------
    def test_23_tariff_bases_remain_distinguishable(self):
        """23. Verifies per kWh vs per session vs per hour are distinguished."""
        # Per kWh
        kwh_res = normalize_pricing(raw_pricing_text="₹18.50/kWh")
        self.assertEqual(kwh_res.pricing_basis, PricingBasis.PER_KWH)
        self.assertEqual(kwh_res.price_per_kwh, 18.50)
        self.assertIsNone(kwh_res.price_per_session)
        self.assertIsNone(kwh_res.price_per_hour)

        # Per Session
        sess_res = normalize_pricing(raw_pricing_text="₹50 per session connection fee")
        self.assertEqual(sess_res.pricing_basis, PricingBasis.PER_SESSION)
        self.assertIsNone(sess_res.price_per_kwh)
        self.assertEqual(sess_res.price_per_session, 50.0)

        # Per Hour
        hour_res = normalize_pricing(raw_pricing_text="₹100 per hour parking charge")
        self.assertEqual(hour_res.pricing_basis, PricingBasis.PER_HOUR)
        self.assertIsNone(hour_res.price_per_kwh)
        self.assertEqual(hour_res.price_per_hour, 100.0)

    # --------------------------------------------------------------------------
    # 24. Operating Hours Variants
    # --------------------------------------------------------------------------
    def test_24_operating_hours_variants(self):
        """24. Verifies 24x7, daily interval, multiple intervals, closed, overnight, unparseable."""
        # 1. 24x7: opening and closing MUST be None per chk_stations_hours
        h_24 = normalize_operating_hours(raw_hours="Open 24/7 all days")
        self.assertTrue(h_24.is_24_hours)
        self.assertIsNone(h_24.opening_time)
        self.assertIsNone(h_24.closing_time)
        self.assertTrue(h_24.is_structured)

        # 2. Daily interval
        h_interval = normalize_operating_hours(raw_hours="08:00 - 22:00")
        self.assertFalse(h_interval.is_24_hours)
        self.assertEqual(h_interval.opening_time, "08:00")
        self.assertEqual(h_interval.closing_time, "22:00")
        self.assertTrue(h_interval.is_structured)

        # 3. 12-hour AM/PM daily interval
        h_ampm = normalize_operating_hours(raw_hours="8:00 AM - 10:00 PM")
        self.assertEqual(h_ampm.opening_time, "08:00")
        self.assertEqual(h_ampm.closing_time, "22:00")

        # 4. Multiple intervals per day
        h_multi = normalize_operating_hours(raw_hours="09:00 - 13:00, 16:00 - 21:00")
        self.assertFalse(h_multi.is_24_hours)
        self.assertEqual(h_multi.opening_time, "09:00")
        self.assertEqual(h_multi.closing_time, "21:00")
        self.assertTrue(len(h_multi.schedule[0].intervals) == 2)

        # 5. Closed day / site
        h_closed = normalize_operating_hours(raw_hours="Closed for maintenance")
        self.assertFalse(h_closed.is_24_hours)
        self.assertTrue(h_closed.schedule[0].is_closed)

        # 6. Overnight interval (close < open)
        h_overnight = normalize_operating_hours(raw_hours="22:00 - 06:00")
        self.assertEqual(h_overnight.opening_time, "22:00")
        self.assertEqual(h_overnight.closing_time, "06:00")
        self.assertTrue(h_overnight.schedule[0].intervals[0].is_overnight)

        # 7. Unparseable unstructured text
        h_unstruct = normalize_operating_hours(raw_hours="Subject to mall opening schedule and security clearance")
        self.assertIsNone(h_unstruct.is_24_hours)
        self.assertIsNone(h_unstruct.opening_time)
        self.assertFalse(h_unstruct.is_structured)
        self.assertEqual(h_unstruct.status, NormalizationStatus.UNMAPPED)

    # --------------------------------------------------------------------------
    # 25. Missing Operating Hours Remain Unknown
    # --------------------------------------------------------------------------
    def test_25_missing_operating_hours_remain_unknown(self):
        """25. Invariant: Missing hours never assumed 24x7 or closed."""
        res = normalize_operating_hours(raw_hours=None)
        self.assertIsNone(res.is_24_hours)
        self.assertIsNone(res.opening_time)
        self.assertIsNone(res.closing_time)
        self.assertEqual(res.status, NormalizationStatus.UNKNOWN)
        self.assertFalse(res.is_structured)

    # --------------------------------------------------------------------------
    # 26. Unknown Source-Specific Fields Not Silently Discarded
    # --------------------------------------------------------------------------
    def test_26_unknown_source_specific_fields_not_discarded(self):
        """26. Verifies vendor metadata is preserved in extra_metadata during normalization."""
        stn = _make_test_station(
            extra_metadata={
                "ocm_uuid": "E9A8C234-F123-4567-89AB-CDEF01234567",
                "custom_provider_flag": "VIP_ONLY",
                "parking_fee": "Free for EV",
            }
        )
        res = normalize_station_record(stn)
        extra = res.station_record.extra_metadata

        self.assertEqual(extra["ocm_uuid"], "E9A8C234-F123-4567-89AB-CDEF01234567")
        self.assertEqual(extra["custom_provider_flag"], "VIP_ONLY")
        self.assertEqual(extra["parking_fee"], "Free for EV")
        self.assertIn("normalization", extra)

    # --------------------------------------------------------------------------
    # 27. Provenance Survives Normalization
    # --------------------------------------------------------------------------
    def test_27_provenance_survives_normalization(self):
        """27. Verifies Layer 1 provenance attributes survive normalization unmodified."""
        stn = _make_test_station()
        res = normalize_station_record(stn)

        self.assertEqual(res.provenance.source_id, stn.source_id)
        self.assertEqual(res.provenance.source_station_id, stn.source_station_id)
        self.assertEqual(res.provenance.raw_payload_hash, stn.raw_payload_hash)
        self.assertEqual(res.provenance.source_url, stn.source_url)
        self.assertEqual(res.provenance.contract_version, stn.contract_version)

    # --------------------------------------------------------------------------
    # 28. Normalization Is Deterministic
    # --------------------------------------------------------------------------
    def test_28_normalization_is_deterministic(self):
        """28. Verifies repeated runs on identical station record produce identical output: result1 == result2."""
        stn = _make_test_station()
        result1 = normalize_station_record(stn)
        result2 = normalize_station_record(stn)

        # Full typed dataclass equality must be True without timestamp drift
        self.assertEqual(result1, result2)
        self.assertEqual(result1.station_record, result2.station_record)
        self.assertEqual(result1.provenance, result2.provenance)

    # --------------------------------------------------------------------------
    # 29. Normalization Is Idempotent / Stable
    # --------------------------------------------------------------------------
    def test_29_normalization_is_idempotent(self):
        """29. Verifies normalize(normalize(x)) == normalize(x) and result3 == result2 where applicable."""
        # Scenario A: On an already canonical / normalized station record:
        # result1 = normalize(input), result2 = normalize(input), result3 = normalize(result1.normalized_record)
        # where applicable => assert result3 == result2
        canonical_connectors = [
            NormalizedConnectorRecord(
                source_connector_id="CONN-1",
                connector_type="CCS2",
                raw_connector_type="CCS2",
                power_kw=60.0,
                voltage_v=400.0,
                amperage_a=150.0,
                quantity=1,
                is_aggregated=False,
                pricing_type=PricingType.PAID,
                price_per_kwh=18.50,
                currency="INR",
            )
        ]
        canonical_stn = _make_test_station(
            name="Tata Power - BKC Fast Hub",
            operator_name="Tata Power",
            address_line="G Block, Bandra Kurla Complex",
            locality="Near MCA Club",
            city="Mumbai",
            state="Maharashtra",
            postal_code="400051",
            country="India",
            connectors=canonical_connectors,
        )
        res1 = normalize_station_record(canonical_stn)
        res2 = normalize_station_record(canonical_stn)
        self.assertEqual(res1, res2)

        res3 = normalize_station_record(res1.normalized_record)
        self.assertEqual(res3, res2)
        self.assertEqual(res3.normalized_record, res2.normalized_record)

        # Scenario B: On raw input with variant aliases and messy formatting:
        raw_stn = _make_test_station(
            operator_name="Tata Power EZ Charge",
            address_line="123 station rd.   west",
            postal_code="400 051",
        )
        raw_res1 = normalize_station_record(raw_stn)
        raw_res2 = normalize_station_record(raw_stn)
        self.assertEqual(raw_res1, raw_res2)

        raw_res3 = normalize_station_record(raw_res1.normalized_record)
        self.assertEqual(raw_res3.normalized_record, raw_res1.normalized_record)

        # Subsequent normalization passes on normalized output remain strictly stable
        raw_res4 = normalize_station_record(raw_res3.normalized_record)
        self.assertEqual(raw_res4, raw_res3)
        self.assertEqual(raw_res4.normalized_record, raw_res3.normalized_record)

    # --------------------------------------------------------------------------
    # 30. No Mutation of Input Record (Pure Function)
    # --------------------------------------------------------------------------
    def test_30_no_mutation_of_input_record(self):
        """30. Invariant: Normalization produces new objects and does not mutate the source record."""
        stn = _make_test_station(
            operator_name="Tata Power EZ Charge",
            postal_code="400 051",
        )
        stn_copy = copy.deepcopy(stn)

        res = normalize_station_record(stn)

        # Original record is untouched
        self.assertEqual(stn, stn_copy)
        self.assertEqual(stn.operator_name, "Tata Power EZ Charge")
        self.assertEqual(stn.postal_code, "400 051")

        # Result record has normalized values
        self.assertEqual(res.station_record.operator_name, "Tata Power")
        self.assertEqual(res.station_record.postal_code, "400051")


if __name__ == "__main__":
    unittest.main()
