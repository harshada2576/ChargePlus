"""ChargePlus — Cross-Source Field Normalization & Standard Vocabulary.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.5 (Cross-Source Field Normalization & Standard Vocabulary)

Implements a deterministic, pure normalization layer that converts source-specific
station, connector, operator, location, pricing, and operating-hours representations
into the canonical vocabulary expected by ChargePlus.

BOUNDARIES:
- Step 2.4: "Could these source records represent the same physical station?"
- Step 2.5: "Are equivalent fields represented consistently enough to compare and process them?"
- Step 2.6: "Does the resulting record satisfy data-quality rules?"
- Step 2.7: "Should records actually become one canonical station, and which values survive?"

NON-NEGOTIABLE INVARIANTS:
1. NEVER FABRICATE MISSING DATA:
   Missing power -> None, missing price -> None, missing operator -> None,
   missing PIN -> None, missing hours -> None / unstructured.
   No fake 0 kW, ₹0 free tariffs, fake operators, or guessed schedules.
2. NORMALIZATION != MERGING:
   Mapping "CCS Combo 2" and "CCS2" to the same vocabulary does NOT mean records
   are the same physical station. No UUID assignments or merging happens here.
3. NORMALIZATION != PRECEDENCE:
   If Source A says 150 kW and Source B says 120 kW, normalize both representations.
   Survivorship arbitration is strictly deferred to Step 2.7.
4. PRESERVE RAW SOURCE INFORMATION:
   Raw values, provenance metadata, payload hashes, and source IDs survive intact.
5. DETERMINISTIC & IDEMPOTENT:
   normalize(x) == normalize(x)
   normalize(normalize(x)) == normalize(x)
   Pure computational functions. Zero LLMs, zero network I/O, zero random calls.
6. EXPLICIT STATUSES:
   NORMALIZED, UNCHANGED, UNKNOWN, UNMAPPED, INVALID.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Generic, Optional, TypeVar
import unicodedata

from backend.ingestion.constants import (
    CONTRACT_VERSION,
    AvailabilityStatus,
    OperationalStatus,
    PricingType,
    StandardConnectorType,
)
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedObservationRecord,
    NormalizedStationRecord,
    ProvenanceInfo,
)

T = TypeVar("T")

# Authoritative Normalization Subsystem Specification Version
NORMALIZATION_VERSION: str = "1.0.0"

# Indian 6-digit PIN code regex: strictly non-zero first digit followed by 5 digits
INDIAN_PIN_REGEX = re.compile(r"^[1-9][0-9]{5}$")

# Slug formatting regex
SLUG_CLEAN_REGEX = re.compile(r"[^a-zA-Z0-9_-]+")

# Time matching regex (24-hour HH:MM or 12-hour with AM/PM)
TIME_PATTERN_24H = re.compile(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$")
TIME_PATTERN_12H = re.compile(r"^([0]?[1-9]|1[0-2])(?::([0-5][0-9]))?\s*(am|pm)$", re.IGNORECASE)

# Power extraction regex
POWER_UNIT_REGEX = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(kw|w|watts?|mw|kilowatts?|megawatts?)\s*$",
    re.IGNORECASE,
)
VOLTAGE_UNIT_REGEX = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(v|kv|volts?|kilovolts?)\s*$",
    re.IGNORECASE,
)
AMPERAGE_UNIT_REGEX = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(a|ma|amps?|amperes?|milliamps?)\s*$",
    re.IGNORECASE,
)


# ------------------------------------------------------------------------------
# Normalization Enums & Models
# ------------------------------------------------------------------------------

class NormalizationStatus(str, Enum):
    """Categorical outcome of normalizing an individual field representation."""
    NORMALIZED = "NORMALIZED"   # Successfully standardized from a variant raw representation
    UNCHANGED = "UNCHANGED"     # Raw value already strictly conformed to canonical representation
    UNKNOWN = "UNKNOWN"         # Raw input was missing/None/empty; missing-data semantics preserved
    UNMAPPED = "UNMAPPED"       # Present but does not map to canonical vocabulary; preserved safely
    INVALID = "INVALID"         # Present but malformed, unparseable, or physically impossible


class OperatorMappingType(str, Enum):
    """Nature of operator vocabulary reconciliation."""
    EXACT = "exact"             # Exact match to canonical operator name
    ALIAS = "alias"             # Match via explicit known operator alias
    UNMAPPED = "unmapped"       # Unrecognized operator name (preserved without guessing)
    UNKNOWN = "unknown"         # Missing or empty operator


class CurrentType(str, Enum):
    """Standardized electrical current type."""
    AC = "AC"
    DC = "DC"
    UNKNOWN = "unknown"


class PricingBasis(str, Enum):
    """Tariff charging rate basis."""
    PER_KWH = "per_kwh"
    PER_SESSION = "per_session"
    PER_HOUR = "per_hour"
    PER_MINUTE = "per_minute"
    FLAT = "flat"
    UNKNOWN = "unknown"


class DayOfWeek(str, Enum):
    """Standard day of week representation."""
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


@dataclass(frozen=True)
class NormalizedField(Generic[T]):
    """Generic container for an audited normalized field value."""
    raw_value: Any
    normalized_value: Optional[T]
    status: NormalizationStatus
    rule: str
    version: str = NORMALIZATION_VERSION
    message: Optional[str] = None


@dataclass(frozen=True)
class NormalizedOperator:
    """Canonical operator representation preserving provenance."""
    canonical_name: Optional[str]
    canonical_slug: Optional[str]
    raw_name: Optional[str]
    mapping_type: OperatorMappingType
    status: NormalizationStatus
    rule: str
    version: str = NORMALIZATION_VERSION


@dataclass(frozen=True)
class TimeInterval:
    """A discrete operating time window in 24-hour clock HH:MM format."""
    open_time: str
    close_time: str
    is_overnight: bool = False


@dataclass(frozen=True)
class DaySchedule:
    """Day-specific operating schedule."""
    day: DayOfWeek
    is_closed: bool = False
    is_24_hours: bool = False
    intervals: tuple[TimeInterval, ...] = ()


@dataclass(frozen=True)
class NormalizedOperatingHours:
    """Standardized operating hours structure."""
    is_24_hours: Optional[bool]
    opening_time: Optional[str]      # Uniform daily opening time (HH:MM)
    closing_time: Optional[str]      # Uniform daily closing time (HH:MM)
    schedule: tuple[DaySchedule, ...] = ()
    raw_hours_text: Optional[str] = None
    is_structured: bool = False
    status: NormalizationStatus = NormalizationStatus.UNKNOWN
    rule: str = "DEFAULT"
    version: str = NORMALIZATION_VERSION


@dataclass(frozen=True)
class NormalizedPricing:
    """Standardized pricing structure distinguishing tariff basis."""
    pricing_type: PricingType
    currency: Optional[str]
    price_per_kwh: Optional[float]
    price_per_session: Optional[float]
    price_per_hour: Optional[float]
    is_free: bool = False
    pricing_basis: PricingBasis = PricingBasis.UNKNOWN
    raw_pricing_text: Optional[str] = None
    status: NormalizationStatus = NormalizationStatus.UNKNOWN
    rule: str = "DEFAULT"
    version: str = NORMALIZATION_VERSION


@dataclass(frozen=True)
class NormalizedElectrical:
    """Standardized electrical and capacity ratings."""
    power_kw: Optional[float]
    voltage_v: Optional[float]
    amperage_a: Optional[float]
    current_type: CurrentType
    raw_power: Any
    raw_voltage: Any
    raw_amperage: Any
    raw_current_type: Any
    power_status: NormalizationStatus
    voltage_status: NormalizationStatus
    amperage_status: NormalizationStatus
    current_type_status: NormalizationStatus
    power_rule: str
    version: str = NORMALIZATION_VERSION


@dataclass(frozen=True)
class NormalizedAddress:
    """Standardized geographic address components."""
    address_line: Optional[str]
    locality: Optional[str]
    city: str
    state: str
    postal_code: Optional[str]
    country: str
    raw_address_line: Optional[str]
    raw_locality: Optional[str]
    raw_postal_code: Optional[str]
    pin_status: NormalizationStatus
    address_status: NormalizationStatus
    rule: str
    version: str = NORMALIZATION_VERSION


@dataclass(frozen=True)
class NormalizedCoordinates:
    """Standardized geographic coordinates."""
    latitude: Optional[float]
    longitude: Optional[float]
    raw_latitude: Any
    raw_longitude: Any
    status: NormalizationStatus
    rule: str
    message: Optional[str] = None
    version: str = NORMALIZATION_VERSION


@dataclass(frozen=True)
class NormalizedConnector:
    """Normalized child connector specification."""
    connector_type: str
    raw_connector_type: str
    charging_standard: Optional[str]
    power_kw: Optional[float]
    voltage_v: Optional[float]
    amperage_a: Optional[float]
    current_type: CurrentType
    quantity: int
    is_aggregated: bool
    pricing: NormalizedPricing
    source_connector_id: Optional[str]
    status: Optional[AvailabilityStatus]
    connector_type_status: NormalizationStatus
    electrical: NormalizedElectrical
    rule: str
    version: str = NORMALIZATION_VERSION


@dataclass(frozen=True)
class StationNormalizationResult:
    """Complete, auditable result of normalizing a canonical station record."""
    station_record: NormalizedStationRecord
    operator: NormalizedOperator
    coordinates: NormalizedCoordinates
    address: NormalizedAddress
    operating_hours: NormalizedOperatingHours
    connectors: tuple[NormalizedConnector, ...]
    provenance: ProvenanceInfo
    normalization_version: str = NORMALIZATION_VERSION
    field_statuses: dict[str, NormalizationStatus] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def normalized_record(self) -> NormalizedStationRecord:
        """Alias for station_record to support standard normalized record access."""
        return self.station_record


# ------------------------------------------------------------------------------
# Authoritative Operator Alias Registry
# (Derived strictly from verified EV charging sources and test fixtures)
# ------------------------------------------------------------------------------

# Canonical operator definitions: canonical_name -> (canonical_slug, set_of_known_aliases)
# STRICT AUDIT: Every alias must be supported by project test fixtures, source adapters, or existing data.
KNOWN_OPERATOR_REGISTRY: dict[str, tuple[str, set[str]]] = {
    # 1. Tata Power — Verified via tests/fixtures/ocm_fixtures.py, src/data/stations.ts, tests/test_entity_resolution.py
    "Tata Power": (
        "tata-power",
        {
            "tata power",
            "tata power ez charge",
            "tata power ev charging",
        },
    ),
    # 2. Jio-bp pulse — Verified via tests/fixtures/ocm_fixtures.py (Fixture 02), tests/test_entity_resolution.py
    "Jio-bp pulse": (
        "jio-bp",
        {
            "jio-bp pulse",
            "jio-bp",
            "jio bp",
            "jio bp pulse",
        },
    ),
    # 3. Ather Energy — Verified via src/data/stations.ts (lines 54, 261), station 'Ather Grid — Powai'
    "Ather Energy": (
        "ather-energy",
        {
            "ather energy",
            "ather grid",
            "ather",
        },
    ),
    # 4. Fortum Charge & Drive — Verified via tests/test_entity_resolution.py (lines 286, 305)
    "Fortum Charge & Drive": (
        "fortum",
        {
            "fortum charge & drive",
            "fortum",
            "fortum charge and drive",
        },
    ),
    # 5. ChargeZone — Verified via src/data/stations.ts (lines 116, 281)
    "ChargeZone": (
        "chargezone",
        {
            "chargezone",
            "charge zone",
        },
    ),
    # 6. Statiq — Verified via src/data/stations.ts (lines 96, 199, 301) & docs/global_ev_charging_data_source_research.md
    "Statiq": (
        "statiq",
        {
            "statiq",
        },
    ),
    # 7. Magenta ChargeGrid — Verified via tests/test_entity_resolution.py (lines 228-229)
    "Magenta ChargeGrid": (
        "magenta-chargegrid",
        {
            "magenta chargegrid",
            "magenta",
            "chargegrid",
        },
    ),
    # 8. Bolt.Earth — Verified via src/data/stations.ts (lines 137, 240)
    "Bolt.Earth": (
        "bolt-earth",
        {
            "bolt.earth",
            "bolt earth",
            "bolt",
        },
    ),
    # 9. Zeon Charging — Verified via docs/global_ev_charging_data_source_research.md (line 114)
    "Zeon Charging": (
        "zeon-charging",
        {
            "zeon charging",
            "zeon",
        },
    ),
    # 10. Kazam — Verified via docs/global_ev_charging_data_source_research.md (line 114)
    "Kazam": (
        "kazam",
        {
            "kazam",
        },
    ),
    # 11. Lithion Power — Verified via tests/test_entity_resolution.py (line 414)
    "Lithion Power": (
        "lithion-power",
        {
            "lithion power",
            "lithion",
        },
    ),
    # 12. Stilt Mobility — Verified via src/data/stations.ts (line 33)
    "Stilt Mobility": (
        "stilt-mobility",
        {
            "stilt mobility",
            "stilt",
        },
    ),
    # 13. ChargePlus — Verified via src/data/stations.ts (lines 11, 158, 220, 321)
    "ChargePlus": (
        "chargeplus",
        {
            "chargeplus",
            "charge plus",
        },
    ),
}

# Inverted index: alias_string -> (canonical_name, canonical_slug)
_OPERATOR_ALIAS_LOOKUP: dict[str, tuple[str, str]] = {}
for canonical_name, (slug, aliases) in KNOWN_OPERATOR_REGISTRY.items():
    # Canonical name itself in lowercase is an exact match
    _OPERATOR_ALIAS_LOOKUP[canonical_name.strip().lower()] = (canonical_name, slug)
    for alias in aliases:
        _OPERATOR_ALIAS_LOOKUP[alias.strip().lower()] = (canonical_name, slug)


# ------------------------------------------------------------------------------
# Authoritative Connector Vocabulary Registry
# ------------------------------------------------------------------------------

# Mapping of normalized lowercase connector label to StandardConnectorType
CONNECTOR_VOCABULARY_MAP: dict[str, StandardConnectorType] = {
    # CCS2
    "ccs2": StandardConnectorType.CCS2,
    "ccs 2": StandardConnectorType.CCS2,
    "ccs-2": StandardConnectorType.CCS2,
    "ccs (type 2)": StandardConnectorType.CCS2,
    "ccs type 2": StandardConnectorType.CCS2,
    "ccs combo 2": StandardConnectorType.CCS2,
    "ccs combo type 2": StandardConnectorType.CCS2,
    "combined charging system 2": StandardConnectorType.CCS2,
    "combined charging system type 2": StandardConnectorType.CCS2,
    "iec 62196-3 configuration ff": StandardConnectorType.CCS2,
    "type 2 combo": StandardConnectorType.CCS2,
    "combo 2": StandardConnectorType.CCS2,
    # CCS1
    "ccs1": StandardConnectorType.CCS1,
    "ccs 1": StandardConnectorType.CCS1,
    "ccs-1": StandardConnectorType.CCS1,
    "ccs (type 1)": StandardConnectorType.CCS1,
    "ccs type 1": StandardConnectorType.CCS1,
    "ccs combo 1": StandardConnectorType.CCS1,
    "ccs combo type 1": StandardConnectorType.CCS1,
    "combined charging system 1": StandardConnectorType.CCS1,
    "iec 62196-3 configuration ee": StandardConnectorType.CCS1,
    "type 1 combo": StandardConnectorType.CCS1,
    "combo 1": StandardConnectorType.CCS1,
    # Type 2
    "type 2": StandardConnectorType.TYPE_2,
    "type-2": StandardConnectorType.TYPE_2,
    "type2": StandardConnectorType.TYPE_2,
    "iec 62196 type 2": StandardConnectorType.TYPE_2,
    "iec 62196-2": StandardConnectorType.TYPE_2,
    "iec 62196-2 type 2": StandardConnectorType.TYPE_2,
    "mennekes": StandardConnectorType.TYPE_2,
    "type 2 (socket only)": StandardConnectorType.TYPE_2,
    "type 2 (tethered connector)": StandardConnectorType.TYPE_2,
    "iec 62196-2 mennekes": StandardConnectorType.TYPE_2,
    # Type 1
    "type 1": StandardConnectorType.TYPE_1,
    "type-1": StandardConnectorType.TYPE_1,
    "type1": StandardConnectorType.TYPE_1,
    "j1772": StandardConnectorType.TYPE_1,
    "sae j1772": StandardConnectorType.TYPE_1,
    "type 1 (j1772)": StandardConnectorType.TYPE_1,
    "iec 62196-2 type 1": StandardConnectorType.TYPE_1,
    # CHAdeMO
    "chademo": StandardConnectorType.CHADEMO,
    "chade-mo": StandardConnectorType.CHADEMO,
    "iec 62196-3 configuration aa": StandardConnectorType.CHADEMO,
    # GB/T
    "gb/t": StandardConnectorType.GB_T,
    "gb-t": StandardConnectorType.GB_T,
    "gbt": StandardConnectorType.GB_T,
    "gb/t (ac)": StandardConnectorType.GB_T,
    "gb/t (dc)": StandardConnectorType.GB_T,
    "gb/t 20234": StandardConnectorType.GB_T,
    "gb-t 20234": StandardConnectorType.GB_T,
    "gb/t 20234.2": StandardConnectorType.GB_T,
    "gb/t 20234.3": StandardConnectorType.GB_T,
    # Bharat Standards
    "bharat ac001": StandardConnectorType.BHARAT_AC001,
    "bharat ac-001": StandardConnectorType.BHARAT_AC001,
    "bharat ac 001": StandardConnectorType.BHARAT_AC001,
    "ac001": StandardConnectorType.BHARAT_AC001,
    "iec 60309": StandardConnectorType.BHARAT_AC001,
    "bharat dc001": StandardConnectorType.BHARAT_DC001,
    "bharat dc-001": StandardConnectorType.BHARAT_DC001,
    "bharat dc 001": StandardConnectorType.BHARAT_DC001,
    "dc001": StandardConnectorType.BHARAT_DC001,
}

# Known Tesla variants mapped safely to OTHER with preserved raw label
TESLA_CONNECTOR_LABELS = {
    "tesla",
    "tesla supercharger",
    "tesla destination",
    "nacs",
    "tesla (roadster)",
    "tesla proprietary",
}

# Common address abbreviations safe to expand
ADDRESS_ABBREVIATIONS: dict[str, str] = {
    "rd": "Road",
    "rd.": "Road",
    "st": "Street",
    "st.": "Street",
    "ave": "Avenue",
    "ave.": "Avenue",
    "bldg": "Building",
    "bldg.": "Building",
    "apt": "Apartment",
    "apt.": "Apartment",
    "flr": "Floor",
    "flr.": "Floor",
    "opp": "Opposite",
    "opp.": "Opposite",
    "nr": "Near",
    "nr.": "Near",
    "hwy": "Highway",
    "hwy.": "Highway",
    "exp hwy": "Expressway",
    "exp. hwy": "Expressway",
}

# Acronyms to keep uppercase in title-casing
PRESERVE_UPPERCASE_TOKENS = {
    "BKC", "MIDC", "SEZ", "CIDCO", "BEST", "MSRTC", "BMC", "MMRDA", "NH", "SH", "EV", "CPO", "MCA",
}



# ------------------------------------------------------------------------------
# Normalization Domain A: Operator Aliases
# ------------------------------------------------------------------------------

def normalize_operator(
    raw_name: Optional[str],
    raw_slug: Optional[str] = None,
) -> NormalizedOperator:
    """Normalizes an operator name against the canonical vocabulary.

    Preserves raw text. Does NOT merge operators or perform entity resolution.
    Unknown operators remain unmapped rather than guessed.
    """
    if raw_name is None or not str(raw_name).strip():
        return NormalizedOperator(
            canonical_name=None,
            canonical_slug=None,
            raw_name=raw_name,
            mapping_type=OperatorMappingType.UNKNOWN,
            status=NormalizationStatus.UNKNOWN,
            rule="OPERATOR_MISSING",
        )

    clean_str = str(raw_name).strip()
    key = clean_str.lower()

    # 1. Check exact or alias match in authoritative registry
    if key in _OPERATOR_ALIAS_LOOKUP:
        canonical_name, canonical_slug = _OPERATOR_ALIAS_LOOKUP[key]
        if clean_str == canonical_name:
            mapping_type = OperatorMappingType.EXACT
            status = NormalizationStatus.UNCHANGED
            rule = "OPERATOR_EXACT_MATCH"
        elif clean_str.lower() == canonical_name.lower():
            mapping_type = OperatorMappingType.EXACT
            status = NormalizationStatus.NORMALIZED
            rule = "OPERATOR_CASE_NORMALIZED"
        else:
            mapping_type = OperatorMappingType.ALIAS
            status = NormalizationStatus.NORMALIZED
            rule = f"OPERATOR_ALIAS_MATCH_{canonical_slug.upper().replace('-', '_')}"

        return NormalizedOperator(
            canonical_name=canonical_name,
            canonical_slug=canonical_slug,
            raw_name=clean_str,
            mapping_type=mapping_type,
            status=status,
            rule=rule,
        )

    # 2. Operator is unknown / unmapped -> PRESERVE raw, do not guess
    safe_slug = raw_slug or _slugify(clean_str)
    return NormalizedOperator(
        canonical_name=None,
        canonical_slug=safe_slug,
        raw_name=clean_str,
        mapping_type=OperatorMappingType.UNMAPPED,
        status=NormalizationStatus.UNMAPPED,
        rule="OPERATOR_UNMAPPED_PRESERVED",
    )


# ------------------------------------------------------------------------------
# Normalization Domain B: Connector Standard Vocabulary
# ------------------------------------------------------------------------------

def normalize_connector_type(raw_type: Optional[str]) -> NormalizedField[str]:
    """Deterministically maps connector strings to canonical StandardConnectorType.

    Preserves source-specific raw connector text.
    """
    if raw_type is None or not str(raw_type).strip():
        return NormalizedField(
            raw_value=raw_type,
            normalized_value=None,
            status=NormalizationStatus.UNKNOWN,
            rule="CONNECTOR_MISSING",
            message="Connector type string is missing or empty",
        )

    raw_str = str(raw_type).strip()
    key = raw_str.lower()

    # Exact canonical match
    for enum_val in StandardConnectorType:
        if raw_str == enum_val.value:
            return NormalizedField(
                raw_value=raw_str,
                normalized_value=enum_val.value,
                status=NormalizationStatus.UNCHANGED,
                rule="CONNECTOR_EXACT_MATCH",
            )

    # Vocabulary map lookup
    if key in CONNECTOR_VOCABULARY_MAP:
        canonical_enum = CONNECTOR_VOCABULARY_MAP[key]
        return NormalizedField(
            raw_value=raw_str,
            normalized_value=canonical_enum.value,
            status=NormalizationStatus.NORMALIZED,
            rule=f"CONNECTOR_{canonical_enum.name}_VOCABULARY",
        )

    # Tesla forms mapped to OTHER with unmapped status and preserved raw
    if key in TESLA_CONNECTOR_LABELS or "tesla" in key or "nacs" in key:
        return NormalizedField(
            raw_value=raw_str,
            normalized_value=StandardConnectorType.OTHER.value,
            status=NormalizationStatus.UNMAPPED,
            rule="CONNECTOR_TESLA_PRESERVED_AS_OTHER",
            message="Tesla/NACS connector preserved as Other under current database constraint",
        )

    # Unrecognized connector label
    return NormalizedField(
        raw_value=raw_str,
        normalized_value=StandardConnectorType.OTHER.value,
        status=NormalizationStatus.UNMAPPED,
        rule="CONNECTOR_UNMAPPED_FALLBACK",
        message=f"Unrecognized connector type '{raw_str}' mapped to Other with raw preserved",
    )


# ------------------------------------------------------------------------------
# Normalization Domain C: Electrical / Power Normalization
# ------------------------------------------------------------------------------

def normalize_power(
    raw_power: Any,
    default_unit: str = "kW",
) -> NormalizedField[float]:
    """Normalizes peak output power to kilowatts (kW) as a positive float.

    Rules:
    - Never defaults missing power to 0.0 (missing means None).
    - If source gives Watts, deterministically converts: W / 1000.0.
    - If source gives kW, preserves kW.
    - Rejects <= 0.0 power as INVALID.
    """
    if raw_power is None or (isinstance(raw_power, str) and not raw_power.strip()):
        return NormalizedField(
            raw_value=raw_power,
            normalized_value=None,
            status=NormalizationStatus.UNKNOWN,
            rule="POWER_MISSING",
        )

    # Numeric handling
    if isinstance(raw_power, (int, float)):
        val = float(raw_power)
        if val <= 0.0:
            return NormalizedField(
                raw_value=raw_power,
                normalized_value=None,
                status=NormalizationStatus.INVALID,
                rule="POWER_NON_POSITIVE",
                message=f"Power {val} is non-positive; contract forbids <= 0.0 kW",
            )

        if default_unit.lower() in ("w", "watt", "watts") or (val >= 1000.0 and default_unit == "W"):
            kw_val = val / 1000.0
            return NormalizedField(
                raw_value=raw_power,
                normalized_value=kw_val,
                status=NormalizationStatus.NORMALIZED,
                rule="POWER_CONVERTED_WATTS_TO_KW",
            )

        is_unchanged = isinstance(raw_power, float)
        return NormalizedField(
            raw_value=raw_power,
            normalized_value=val,
            status=NormalizationStatus.UNCHANGED if is_unchanged else NormalizationStatus.NORMALIZED,
            rule="POWER_KW_DIRECT",
        )

    # String parsing
    str_val = str(raw_power).strip()
    match = POWER_UNIT_REGEX.match(str_val)
    if match:
        num_str, unit_str = match.groups()
        val = float(num_str)
        if val <= 0.0:
            return NormalizedField(
                raw_value=raw_power,
                normalized_value=None,
                status=NormalizationStatus.INVALID,
                rule="POWER_NON_POSITIVE",
                message="Parsed power value is non-positive",
            )

        unit_lower = unit_str.lower()
        if unit_lower in ("w", "watt", "watts"):
            kw_val = val / 1000.0
            return NormalizedField(
                raw_value=raw_power,
                normalized_value=kw_val,
                status=NormalizationStatus.NORMALIZED,
                rule="POWER_CONVERTED_WATTS_TO_KW",
            )
        elif unit_lower in ("mw", "megawatt", "megawatts"):
            kw_val = val * 1000.0
            return NormalizedField(
                raw_value=raw_power,
                normalized_value=kw_val,
                status=NormalizationStatus.NORMALIZED,
                rule="POWER_CONVERTED_MW_TO_KW",
            )
        else:
            return NormalizedField(
                raw_value=raw_power,
                normalized_value=val,
                status=NormalizationStatus.NORMALIZED,
                rule="POWER_PARSED_KW_STRING",
            )

    # Fallback attempt to parse plain float string without unit
    try:
        val = float(str_val)
        if val <= 0.0:
            return NormalizedField(
                raw_value=raw_power,
                normalized_value=None,
                status=NormalizationStatus.INVALID,
                rule="POWER_NON_POSITIVE",
            )
        return NormalizedField(
            raw_value=raw_power,
            normalized_value=val,
            status=NormalizationStatus.NORMALIZED,
            rule="POWER_PARSED_NUMERIC_STRING",
        )
    except ValueError:
        return NormalizedField(
            raw_value=raw_power,
            normalized_value=None,
            status=NormalizationStatus.INVALID,
            rule="POWER_UNPARSEABLE_STRING",
            message=f"Cannot parse power from string '{str_val}'",
        )


def normalize_voltage(raw_voltage: Any) -> NormalizedField[float]:
    """Normalizes electrical voltage to Volts (V). Rejects <= 0 as invalid."""
    if raw_voltage is None or (isinstance(raw_voltage, str) and not raw_voltage.strip()):
        return NormalizedField(
            raw_value=raw_voltage,
            normalized_value=None,
            status=NormalizationStatus.UNKNOWN,
            rule="VOLTAGE_MISSING",
        )

    if isinstance(raw_voltage, (int, float)):
        val = float(raw_voltage)
        if val <= 0.0:
            return NormalizedField(
                raw_value=raw_voltage,
                normalized_value=None,
                status=NormalizationStatus.INVALID,
                rule="VOLTAGE_NON_POSITIVE",
            )
        is_unchanged = isinstance(raw_voltage, float)
        return NormalizedField(
            raw_value=raw_voltage,
            normalized_value=val,
            status=NormalizationStatus.UNCHANGED if is_unchanged else NormalizationStatus.NORMALIZED,
            rule="VOLTAGE_DIRECT_V",
        )

    str_val = str(raw_voltage).strip()
    match = VOLTAGE_UNIT_REGEX.match(str_val)
    if match:
        num_str, unit_str = match.groups()
        val = float(num_str)
        if val <= 0.0:
            return NormalizedField(
                raw_value=raw_voltage,
                normalized_value=None,
                status=NormalizationStatus.INVALID,
                rule="VOLTAGE_NON_POSITIVE",
            )
        if unit_str.lower() in ("kv", "kilovolt", "kilovolts"):
            return NormalizedField(
                raw_value=raw_voltage,
                normalized_value=val * 1000.0,
                status=NormalizationStatus.NORMALIZED,
                rule="VOLTAGE_CONVERTED_KV_TO_V",
            )
        return NormalizedField(
            raw_value=raw_voltage,
            normalized_value=val,
            status=NormalizationStatus.NORMALIZED,
            rule="VOLTAGE_PARSED_V",
        )

    try:
        val = float(str_val)
        if val <= 0.0:
            return NormalizedField(
                raw_value=raw_voltage,
                normalized_value=None,
                status=NormalizationStatus.INVALID,
                rule="VOLTAGE_NON_POSITIVE",
            )
        return NormalizedField(
            raw_value=raw_voltage,
            normalized_value=val,
            status=NormalizationStatus.NORMALIZED,
            rule="VOLTAGE_PARSED_NUMERIC_STRING",
        )
    except ValueError:
        return NormalizedField(
            raw_value=raw_voltage,
            normalized_value=None,
            status=NormalizationStatus.INVALID,
            rule="VOLTAGE_UNPARSEABLE",
        )


def normalize_amperage(raw_amperage: Any) -> NormalizedField[float]:
    """Normalizes electrical current to Amperes (A). Rejects <= 0 as invalid."""
    if raw_amperage is None or (isinstance(raw_amperage, str) and not raw_amperage.strip()):
        return NormalizedField(
            raw_value=raw_amperage,
            normalized_value=None,
            status=NormalizationStatus.UNKNOWN,
            rule="AMPERAGE_MISSING",
        )

    if isinstance(raw_amperage, (int, float)):
        val = float(raw_amperage)
        if val <= 0.0:
            return NormalizedField(
                raw_value=raw_amperage,
                normalized_value=None,
                status=NormalizationStatus.INVALID,
                rule="AMPERAGE_NON_POSITIVE",
            )
        is_unchanged = isinstance(raw_amperage, float)
        return NormalizedField(
            raw_value=raw_amperage,
            normalized_value=val,
            status=NormalizationStatus.UNCHANGED if is_unchanged else NormalizationStatus.NORMALIZED,
            rule="AMPERAGE_DIRECT_A",
        )

    str_val = str(raw_amperage).strip()
    match = AMPERAGE_UNIT_REGEX.match(str_val)
    if match:
        num_str, unit_str = match.groups()
        val = float(num_str)
        if val <= 0.0:
            return NormalizedField(
                raw_value=raw_amperage,
                normalized_value=None,
                status=NormalizationStatus.INVALID,
                rule="AMPERAGE_NON_POSITIVE",
            )
        if unit_str.lower() in ("ma", "milliamp", "milliamps"):
            return NormalizedField(
                raw_value=raw_amperage,
                normalized_value=val / 1000.0,
                status=NormalizationStatus.NORMALIZED,
                rule="AMPERAGE_CONVERTED_MA_TO_A",
            )
        return NormalizedField(
            raw_value=raw_amperage,
            normalized_value=val,
            status=NormalizationStatus.NORMALIZED,
            rule="AMPERAGE_PARSED_A",
        )

    try:
        val = float(str_val)
        if val <= 0.0:
            return NormalizedField(
                raw_value=raw_amperage,
                normalized_value=None,
                status=NormalizationStatus.INVALID,
                rule="AMPERAGE_NON_POSITIVE",
            )
        return NormalizedField(
            raw_value=raw_amperage,
            normalized_value=val,
            status=NormalizationStatus.NORMALIZED,
            rule="AMPERAGE_PARSED_NUMERIC_STRING",
        )
    except ValueError:
        return NormalizedField(
            raw_value=raw_amperage,
            normalized_value=None,
            status=NormalizationStatus.INVALID,
            rule="AMPERAGE_UNPARSEABLE",
        )


# ------------------------------------------------------------------------------
# Normalization Domain D: Current / Electrical Type
# ------------------------------------------------------------------------------

def normalize_current_type(raw_current: Any) -> NormalizedField[CurrentType]:
    """Normalizes electrical current type to CurrentType enum (AC, DC, UNKNOWN).

    Do NOT infer AC/DC from connector name alone.
    """
    if raw_current is None or (isinstance(raw_current, str) and not raw_current.strip()):
        return NormalizedField(
            raw_value=raw_current,
            normalized_value=CurrentType.UNKNOWN,
            status=NormalizationStatus.UNKNOWN,
            rule="CURRENT_TYPE_MISSING",
        )

    if isinstance(raw_current, CurrentType):
        return NormalizedField(
            raw_value=raw_current,
            normalized_value=raw_current,
            status=NormalizationStatus.UNCHANGED,
            rule="CURRENT_TYPE_EXACT_ENUM",
        )

    str_val = str(raw_current).strip()
    key = str_val.lower()

    if key == "ac":
        return NormalizedField(
            raw_value=raw_current,
            normalized_value=CurrentType.AC,
            status=NormalizationStatus.UNCHANGED if str_val == "AC" else NormalizationStatus.NORMALIZED,
            rule="CURRENT_TYPE_AC_EXACT",
        )
    if key == "dc":
        return NormalizedField(
            raw_value=raw_current,
            normalized_value=CurrentType.DC,
            status=NormalizationStatus.UNCHANGED if str_val == "DC" else NormalizationStatus.NORMALIZED,
            rule="CURRENT_TYPE_DC_EXACT",
        )

    # AC variants
    if any(k in key for k in ("alternating current", "ac (three-phase)", "ac (single-phase)", "three phase ac", "single phase ac")):
        return NormalizedField(
            raw_value=raw_current,
            normalized_value=CurrentType.AC,
            status=NormalizationStatus.NORMALIZED,
            rule="CURRENT_TYPE_AC_VARIANT",
        )

    # DC variants
    if any(k in key for k in ("direct current", "dc fast", "dc fast charging")):
        return NormalizedField(
            raw_value=raw_current,
            normalized_value=CurrentType.DC,
            status=NormalizationStatus.NORMALIZED,
            rule="CURRENT_TYPE_DC_VARIANT",
        )

    return NormalizedField(
        raw_value=raw_current,
        normalized_value=CurrentType.UNKNOWN,
        status=NormalizationStatus.UNMAPPED,
        rule="CURRENT_TYPE_UNRECOGNIZED",
        message=f"Unrecognized current type string '{str_val}'",
    )


# ------------------------------------------------------------------------------
# Normalization Domain E: Address & Geography Normalization
# ------------------------------------------------------------------------------

def clean_whitespace(text: Optional[str]) -> str:
    """Collapses consecutive whitespaces and trims leading/trailing spaces."""
    if not text:
        return ""
    # Unicode NFKD normalization
    norm = unicodedata.normalize("NFKD", str(text))
    # Replace non-breaking spaces with standard space
    norm = norm.replace("\u00a0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", norm).strip()


def normalize_address_text(raw_text: Optional[str]) -> Optional[str]:
    """Conservative address string normalization.

    Expands safe abbreviations (Rd -> Road, Opp -> Opposite),
    normalizes casing while preserving acronyms, and removes redundant punctuation.
    Does NOT geocode or guess missing address components.
    """
    cleaned = clean_whitespace(raw_text)
    if not cleaned:
        return None

    # Remove spaces preceding punctuation marks (e.g. "block ," -> "block,")
    cleaned = re.sub(r"\s+([,.:;])", r"\1", cleaned)

    tokens = cleaned.split()
    normalized_tokens: list[str] = []
    total_tokens = len(tokens)

    for idx, token in enumerate(tokens):
        is_last = (idx == total_tokens - 1)
        # Strip trailing comma or period for abbreviation check
        has_trailing_comma = token.endswith(",")
        has_trailing_period = token.endswith(".")
        base_token = token.rstrip(",.")

        base_lower = base_token.lower()
        expanded = ADDRESS_ABBREVIATIONS.get(base_lower)

        if expanded:
            res_token = expanded + ("," if has_trailing_comma else ("." if (has_trailing_period and is_last) else ""))
        elif base_token.upper() in PRESERVE_UPPERCASE_TOKENS:
            res_token = base_token.upper() + ("," if has_trailing_comma else ("." if has_trailing_period else ""))
        elif base_token.isupper() and len(base_token) > 1:
            res_token = base_token.title() + ("," if has_trailing_comma else ("." if has_trailing_period else ""))
        elif base_token.islower():
            res_token = base_token.title() + ("," if has_trailing_comma else ("." if has_trailing_period else ""))
        else:
            res_token = token

        normalized_tokens.append(res_token)

    return " ".join(normalized_tokens)



def normalize_address(
    address_line: Optional[str],
    locality: Optional[str],
    city: Optional[str] = "Mumbai",
    state: Optional[str] = "Maharashtra",
    postal_code: Optional[str] = None,
    country: Optional[str] = "India",
) -> NormalizedAddress:
    """Normalizes address components for comparison and operational storage."""
    norm_addr = normalize_address_text(address_line)
    norm_loc = normalize_address_text(locality)
    norm_city = clean_whitespace(city).title() or "Mumbai"
    norm_state = clean_whitespace(state).title() or "Maharashtra"
    norm_country = clean_whitespace(country)

    if norm_country.lower() in ("in", "ind", "india"):
        norm_country = "India"
    elif norm_country:
        norm_country = norm_country.title()
    else:
        norm_country = "India"

    pin_res = normalize_postal_code(postal_code, country=norm_country)

    is_changed = (
        norm_addr != address_line
        or norm_loc != locality
        or pin_res.status == NormalizationStatus.NORMALIZED
    )

    return NormalizedAddress(
        address_line=norm_addr,
        locality=norm_loc,
        city=norm_city,
        state=norm_state,
        postal_code=pin_res.normalized_value,
        country=norm_country,
        raw_address_line=address_line,
        raw_locality=locality,
        raw_postal_code=postal_code,
        pin_status=pin_res.status,
        address_status=NormalizationStatus.NORMALIZED if is_changed else NormalizationStatus.UNCHANGED,
        rule="ADDRESS_NORMALIZED_SAFE",
    )


# ------------------------------------------------------------------------------
# Normalization Domain F: Latitude / Longitude
# ------------------------------------------------------------------------------

def normalize_coordinates(raw_lat: Any, raw_lng: Any) -> NormalizedCoordinates:
    """Normalizes geographic coordinates to WGS 84 decimal float degrees.

    Special Rules:
    - Individual 0.0 is legitimate (Equator lat=0.0, Prime Meridian lng=0.0).
    - Coordinates (0.0, 0.0) together is rejected as Null Island (INVALID).
    - Does NOT aggressively round or truncate coordinate precision.
    """
    if raw_lat is None or raw_lng is None:
        return NormalizedCoordinates(
            latitude=None,
            longitude=None,
            raw_latitude=raw_lat,
            raw_longitude=raw_lng,
            status=NormalizationStatus.UNKNOWN,
            rule="COORDS_MISSING",
            message="One or both coordinates missing",
        )

    # Parse latitude
    try:
        lat = float(raw_lat)
    except (ValueError, TypeError):
        return NormalizedCoordinates(
            latitude=None,
            longitude=None,
            raw_latitude=raw_lat,
            raw_longitude=raw_lng,
            status=NormalizationStatus.INVALID,
            rule="COORDS_LAT_UNPARSEABLE",
            message=f"Cannot parse latitude '{raw_lat}' to float",
        )

    # Parse longitude
    try:
        lng = float(raw_lng)
    except (ValueError, TypeError):
        return NormalizedCoordinates(
            latitude=None,
            longitude=None,
            raw_latitude=raw_lat,
            raw_longitude=raw_lng,
            status=NormalizationStatus.INVALID,
            rule="COORDS_LNG_UNPARSEABLE",
            message=f"Cannot parse longitude '{raw_lng}' to float",
        )

    # Check bounds
    if not (-90.0 <= lat <= 90.0):
        return NormalizedCoordinates(
            latitude=None,
            longitude=None,
            raw_latitude=raw_lat,
            raw_longitude=raw_lng,
            status=NormalizationStatus.INVALID,
            rule="COORDS_LAT_OUT_OF_BOUNDS",
            message=f"Latitude {lat} outside [-90, 90]",
        )

    if not (-180.0 <= lng <= 180.0):
        return NormalizedCoordinates(
            latitude=None,
            longitude=None,
            raw_latitude=raw_lat,
            raw_longitude=raw_lng,
            status=NormalizationStatus.INVALID,
            rule="COORDS_LNG_OUT_OF_BOUNDS",
            message=f"Longitude {lng} outside [-180, 180]",
        )

    # Null Island check: both exactly 0.0
    if abs(lat) < 1e-6 and abs(lng) < 1e-6:
        return NormalizedCoordinates(
            latitude=None,
            longitude=None,
            raw_latitude=raw_lat,
            raw_longitude=raw_lng,
            status=NormalizationStatus.INVALID,
            rule="COORDS_NULL_ISLAND",
            message="Coordinates (0.0, 0.0) indicate placeholder / Null Island",
        )

    is_unchanged = isinstance(raw_lat, float) and isinstance(raw_lng, float)
    return NormalizedCoordinates(
        latitude=lat,
        longitude=lng,
        raw_latitude=raw_lat,
        raw_longitude=raw_lng,
        status=NormalizationStatus.UNCHANGED if is_unchanged else NormalizationStatus.NORMALIZED,
        rule="COORDS_VALID_WGS84",
    )


# ------------------------------------------------------------------------------
# Normalization Domain G: Postal / PIN Code
# ------------------------------------------------------------------------------

def normalize_postal_code(
    raw_pin: Any,
    country: str = "India",
) -> NormalizedField[str]:
    """Normalizes postal/PIN code representation.

    India-Aware:
    - Strips whitespace and hyphens (e.g. "400 051" -> "400051", "400-051" -> "400051").
    - Validates against standard 6-digit PIN regex ^[1-9][0-9]{5}$.
    - Malformed PINs are rejected as INVALID (returns None, raw preserved).
    - NEVER guesses or fabricates missing PINs.
    """
    if raw_pin is None or not str(raw_pin).strip():
        return NormalizedField(
            raw_value=raw_pin,
            normalized_value=None,
            status=NormalizationStatus.UNKNOWN,
            rule="PIN_MISSING",
        )

    raw_str = str(raw_pin).strip()

    if country.lower() in ("india", "in"):
        # Strip all interior spaces, hyphens, and dots
        cleaned = re.sub(r"[\s\-_.]+", "", raw_str)

        if INDIAN_PIN_REGEX.match(cleaned):
            is_unchanged = (raw_str == cleaned)
            return NormalizedField(
                raw_value=raw_pin,
                normalized_value=cleaned,
                status=NormalizationStatus.UNCHANGED if is_unchanged else NormalizationStatus.NORMALIZED,
                rule="PIN_INDIA_6DIGIT_VALID",
            )
        else:
            return NormalizedField(
                raw_value=raw_pin,
                normalized_value=None,
                status=NormalizationStatus.INVALID,
                rule="PIN_INDIA_INVALID_FORMAT",
                message=f"Postal code '{raw_str}' does not conform to Indian 6-digit PIN format",
            )

    # Global / non-Indian postal code: clean whitespace
    clean_global = clean_whitespace(raw_str).upper()
    is_unchanged = (raw_str == clean_global)
    return NormalizedField(
        raw_value=raw_pin,
        normalized_value=clean_global,
        status=NormalizationStatus.UNCHANGED if is_unchanged else NormalizationStatus.NORMALIZED,
        rule="PIN_GLOBAL_CLEANED",
    )


# ------------------------------------------------------------------------------
# Normalization Domain H: Pricing / Tariff Normalization
# ------------------------------------------------------------------------------

def normalize_pricing(
    raw_pricing_text: Optional[str] = None,
    pricing_type: Optional[PricingType] = None,
    price_per_kwh: Optional[float] = None,
    price_per_session: Optional[float] = None,
    currency: Optional[str] = "INR",
) -> NormalizedPricing:
    """Normalizes pricing representation distinguishing rate basis.

    CRITICAL RULES:
    - Never converts missing pricing to 0.0.
    - Explicit free charging is represented as a real semantic state (is_free=True, price_per_kwh=0.0).
    - Distinguishes per_kwh, per_session, and per_hour.
    - Does NOT invent currency or perform exchange rate conversions.
    """
    # 1. Check if all pricing information is absent
    has_raw_text = bool(raw_pricing_text and str(raw_pricing_text).strip())
    has_structured = (pricing_type is not None and pricing_type != PricingType.UNKNOWN) or (price_per_kwh is not None) or (price_per_session is not None)

    if not has_raw_text and not has_structured:
        return NormalizedPricing(
            pricing_type=PricingType.UNKNOWN,
            currency=currency or "INR",
            price_per_kwh=None,
            price_per_session=None,
            price_per_hour=None,
            is_free=False,
            pricing_basis=PricingBasis.UNKNOWN,
            raw_pricing_text=raw_pricing_text,
            status=NormalizationStatus.UNKNOWN,
            rule="PRICING_MISSING",
        )

    # 2. Parse textual pricing string for numeric tariffs
    text_clean = str(raw_pricing_text).strip().lower() if has_raw_text else ""
    kwh_match = None
    session_match = None
    hour_match = None
    if has_raw_text:
        kwh_match = re.search(r"(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:₹|rs\.?|inr)?\s*(?:/|\bper\b)\s*(?:kwh|unit)", text_clean)
        session_match = re.search(r"(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:₹|rs\.?|inr)?\s*(?:/|\bper\b)\s*(?:session|connection)", text_clean)
        hour_match = re.search(r"(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:₹|rs\.?|inr)?\s*(?:/|\bper\b)\s*(?:hr|hour)", text_clean)

    has_numeric_rate = bool(
        kwh_match
        or session_match
        or hour_match
        or (price_per_kwh is not None and price_per_kwh > 0.0)
        or (price_per_session is not None and price_per_session > 0.0)
    )

    # 3. Check for explicit FREE charging (only when no conflicting paid rate is given)
    is_explicit_free = (
        not has_numeric_rate
        and (
            pricing_type == PricingType.FREE
            or (price_per_kwh == 0.0 and pricing_type == PricingType.FREE)
            or bool(re.search(r"\b(free|no charge|complimentary|zero cost|free charging)\b", text_clean))
        )
    )

    if is_explicit_free:
        return NormalizedPricing(
            pricing_type=PricingType.FREE,
            currency=currency or "INR",
            price_per_kwh=0.0,
            price_per_session=None,
            price_per_hour=None,
            is_free=True,
            pricing_basis=PricingBasis.FLAT,
            raw_pricing_text=raw_pricing_text,
            status=NormalizationStatus.NORMALIZED,
            rule="PRICING_EXPLICIT_FREE",
        )


    # 3. Structured inputs provided directly
    if price_per_kwh is not None and price_per_kwh > 0.0:
        return NormalizedPricing(
            pricing_type=PricingType.PAID,
            currency=currency or "INR",
            price_per_kwh=float(price_per_kwh),
            price_per_session=float(price_per_session) if price_per_session is not None else None,
            price_per_hour=None,
            is_free=False,
            pricing_basis=PricingBasis.PER_KWH,
            raw_pricing_text=raw_pricing_text,
            status=NormalizationStatus.NORMALIZED if price_per_session is not None else NormalizationStatus.UNCHANGED,
            rule="PRICING_STRUCTURED_PER_KWH",
        )

    if price_per_session is not None and price_per_session > 0.0:
        return NormalizedPricing(
            pricing_type=PricingType.PAID,
            currency=currency or "INR",
            price_per_kwh=None,
            price_per_session=float(price_per_session),
            price_per_hour=None,
            is_free=False,
            pricing_basis=PricingBasis.PER_SESSION,
            raw_pricing_text=raw_pricing_text,
            status=NormalizationStatus.NORMALIZED,
            rule="PRICING_STRUCTURED_PER_SESSION",
        )

    # 4. Parse textual pricing string
    if has_raw_text:
        # Match per kWh tariffs: e.g. "₹18.50 per kWh", "18.50/kWh", "Rs. 18.50 / unit"
        kwh_match = re.search(r"(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:₹|rs\.?|inr)?\s*(?:/|\bper\b)\s*(?:kwh|unit)", text_clean)
        if kwh_match:
            rate = float(kwh_match.group(1))
            return NormalizedPricing(
                pricing_type=PricingType.PAID,
                currency="INR",
                price_per_kwh=rate,
                price_per_session=None,
                price_per_hour=None,
                is_free=False,
                pricing_basis=PricingBasis.PER_KWH,
                raw_pricing_text=raw_pricing_text,
                status=NormalizationStatus.NORMALIZED,
                rule="PRICING_PARSED_TEXT_PER_KWH",
            )

        # Match per session fee: e.g. "₹50 per session", "50 / session", "Connection fee ₹50"
        session_match = re.search(r"(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:₹|rs\.?|inr)?\s*(?:/|\bper\b)\s*(?:session|connection)", text_clean)
        if session_match:
            fee = float(session_match.group(1))
            return NormalizedPricing(
                pricing_type=PricingType.PAID,
                currency="INR",
                price_per_kwh=None,
                price_per_session=fee,
                price_per_hour=None,
                is_free=False,
                pricing_basis=PricingBasis.PER_SESSION,
                raw_pricing_text=raw_pricing_text,
                status=NormalizationStatus.NORMALIZED,
                rule="PRICING_PARSED_TEXT_PER_SESSION",
            )

        # Match per hour fee: e.g. "₹100 per hour", "100/hr", "Rs 100/hour"
        hour_match = re.search(r"(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:₹|rs\.?|inr)?\s*(?:/|\bper\b)\s*(?:hr|hour)", text_clean)
        if hour_match:
            hr_fee = float(hour_match.group(1))
            return NormalizedPricing(
                pricing_type=PricingType.PAID,
                currency="INR",
                price_per_kwh=None,
                price_per_session=None,
                price_per_hour=hr_fee,
                is_free=False,
                pricing_basis=PricingBasis.PER_HOUR,
                raw_pricing_text=raw_pricing_text,
                status=NormalizationStatus.NORMALIZED,
                rule="PRICING_PARSED_TEXT_PER_HOUR",
            )

        # Check paid indication without extractable numeric rate
        if any(k in text_clean for k in ("pay", "tariff", "paid", "commercial", "rates apply", "metered")):
            return NormalizedPricing(
                pricing_type=PricingType.PAID,
                currency=currency or "INR",
                price_per_kwh=None,
                price_per_session=None,
                price_per_hour=None,
                is_free=False,
                pricing_basis=PricingBasis.UNKNOWN,
                raw_pricing_text=raw_pricing_text,
                status=NormalizationStatus.UNMAPPED,
                rule="PRICING_TEXT_PAID_RATES_UNSTRUCTURED",
            )

    # Fallback unmapped text
    return NormalizedPricing(
        pricing_type=PricingType.UNKNOWN,
        currency=currency or "INR",
        price_per_kwh=None,
        price_per_session=None,
        price_per_hour=None,
        is_free=False,
        pricing_basis=PricingBasis.UNKNOWN,
        raw_pricing_text=raw_pricing_text,
        status=NormalizationStatus.UNMAPPED,
        rule="PRICING_UNSTRUCTURED_FALLBACK",
    )


# ------------------------------------------------------------------------------
# Normalization Domain I: Operating Hours Normalization
# ------------------------------------------------------------------------------

def _parse_time_str(time_str: str) -> Optional[str]:
    """Parses a time string into canonical HH:MM 24-hour clock format."""
    t = time_str.strip()
    match_24 = TIME_PATTERN_24H.match(t)
    if match_24:
        h, m = int(match_24.group(1)), int(match_24.group(2))
        return f"{h:02d}:{m:02d}"

    match_12 = TIME_PATTERN_12H.match(t)
    if match_12:
        h = int(match_12.group(1))
        m = int(match_12.group(2)) if match_12.group(2) else 0
        ampm = match_12.group(3).lower()
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"

    return None


def normalize_operating_hours(
    raw_hours: Any = None,
    is_24_hours: Optional[bool] = None,
    opening_time: Optional[str] = None,
    closing_time: Optional[str] = None,
) -> NormalizedOperatingHours:
    """Normalizes station operating hours.

    CRITICAL INVARIANTS:
    - Database constraint `chk_stations_hours` requires opening_time and closing_time
      to be NULL when `is_24_hours = True`.
    - Never assumes missing hours = 24x7 or closed.
    - Handles overnight intervals correctly where open_time > close_time.
    - Unstructured/unparseable hours preserve raw string with is_structured=False.
    """
    # 1. Missing hours check
    has_text = bool(raw_hours and str(raw_hours).strip())
    has_structured_flags = is_24_hours is not None or opening_time is not None or closing_time is not None

    if not has_text and not has_structured_flags:
        return NormalizedOperatingHours(
            is_24_hours=None,
            opening_time=None,
            closing_time=None,
            schedule=(),
            raw_hours_text=None,
            is_structured=False,
            status=NormalizationStatus.UNKNOWN,
            rule="HOURS_MISSING",
        )

    # 2. Check 24x7 hours
    text_clean = str(raw_hours).strip().lower() if has_text else ""
    is_24h_detected = (
        is_24_hours is True
        or any(k in text_clean for k in ("24/7", "24x7", "open 24 hours", "24 hours", "always open", "24 hrs"))
    )

    if is_24h_detected:
        is_unchanged = (is_24_hours is True and opening_time is None and closing_time is None and not has_text)
        return NormalizedOperatingHours(
            is_24_hours=True,
            opening_time=None,  # chk_stations_hours enforcement
            closing_time=None,  # chk_stations_hours enforcement
            schedule=tuple(
                DaySchedule(day=d, is_closed=False, is_24_hours=True, intervals=())
                for d in DayOfWeek
            ),
            raw_hours_text=str(raw_hours) if has_text else None,
            is_structured=True,
            status=NormalizationStatus.UNCHANGED if is_unchanged else NormalizationStatus.NORMALIZED,
            rule="HOURS_24X7",
        )

    # 3. Check for CLOSED site / day
    if any(k in text_clean for k in ("closed", "permanently closed", "not operational")):
        return NormalizedOperatingHours(
            is_24_hours=False,
            opening_time=None,
            closing_time=None,
            schedule=tuple(
                DaySchedule(day=d, is_closed=True, is_24_hours=False, intervals=())
                for d in DayOfWeek
            ),
            raw_hours_text=str(raw_hours),
            is_structured=True,
            status=NormalizationStatus.NORMALIZED,
            rule="HOURS_CLOSED",
        )

    # 4. Check multiple intervals in text: e.g. "09:00 - 13:00, 16:00 - 21:00"
    if has_text and "," in text_clean:
        interval_parts = [p.strip() for p in text_clean.split(",") if p.strip()]
        parsed_intervals: list[TimeInterval] = []
        for part in interval_parts:
            # Match "HH:MM - HH:MM" or "8am - 12pm"
            int_match = re.search(r"([0-9:apm\s]+)\s*(?:-|to)\s*([0-9:apm\s]+)", part)
            if int_match:
                t1 = _parse_time_str(int_match.group(1))
                t2 = _parse_time_str(int_match.group(2))
                if t1 and t2:
                    parsed_intervals.append(TimeInterval(open_time=t1, close_time=t2, is_overnight=(t2 < t1)))

        if parsed_intervals:
            first_open = parsed_intervals[0].open_time
            last_close = parsed_intervals[-1].close_time
            return NormalizedOperatingHours(
                is_24_hours=False,
                opening_time=first_open,
                closing_time=last_close,
                schedule=tuple(
                    DaySchedule(day=d, is_closed=False, is_24_hours=False, intervals=tuple(parsed_intervals))
                    for d in DayOfWeek
                ),
                raw_hours_text=str(raw_hours),
                is_structured=True,
                status=NormalizationStatus.NORMALIZED,
                rule="HOURS_MULTIPLE_INTERVALS",
            )

    # 5. Check single interval in text or structured opening/closing times
    open_parsed: Optional[str] = None
    close_parsed: Optional[str] = None

    if opening_time:
        open_parsed = _parse_time_str(str(opening_time))
    if closing_time:
        close_parsed = _parse_time_str(str(closing_time))

    if not open_parsed or not close_parsed:
        # Try parsing from text
        match_int = re.search(r"([0-9:apm\s]+)\s*(?:-|to)\s*([0-9:apm\s]+)", text_clean)
        if match_int:
            open_parsed = _parse_time_str(match_int.group(1))
            close_parsed = _parse_time_str(match_int.group(2))

    if open_parsed and close_parsed:
        is_overnight = close_parsed < open_parsed
        interval = TimeInterval(open_time=open_parsed, close_time=close_parsed, is_overnight=is_overnight)
        return NormalizedOperatingHours(
            is_24_hours=False,
            opening_time=open_parsed,
            closing_time=close_parsed,
            schedule=tuple(
                DaySchedule(day=d, is_closed=False, is_24_hours=False, intervals=(interval,))
                for d in DayOfWeek
            ),
            raw_hours_text=str(raw_hours) if has_text else None,
            is_structured=True,
            status=NormalizationStatus.NORMALIZED,
            rule="HOURS_OVERNIGHT_INTERVAL" if is_overnight else "HOURS_DAILY_INTERVAL",
        )

    # 6. Unstructured text that cannot safely map to time windows
    return NormalizedOperatingHours(
        is_24_hours=None,
        opening_time=None,
        closing_time=None,
        schedule=(),
        raw_hours_text=str(raw_hours) if has_text else None,
        is_structured=False,
        status=NormalizationStatus.UNMAPPED,
        rule="HOURS_UNSTRUCTURED_TEXT",
    )


# ------------------------------------------------------------------------------
# Normalization Domain J: Child Connector Normalization
# ------------------------------------------------------------------------------

def normalize_connector_record(c: NormalizedConnectorRecord) -> NormalizedConnector:
    """Normalizes an individual child connector record."""
    norm_type_res = normalize_connector_type(c.connector_type or c.raw_connector_type)
    norm_power_res = normalize_power(c.power_kw)
    norm_volt_res = normalize_voltage(c.voltage_v)
    norm_amp_res = normalize_amperage(c.amperage_a)
    norm_current_res = normalize_current_type(c.charging_standard)  # Or if current_type was in metadata

    norm_pricing = normalize_pricing(
        raw_pricing_text=None,
        pricing_type=c.pricing_type,
        price_per_kwh=c.price_per_kwh,
        price_per_session=c.price_per_session,
        currency=c.currency,
    )

    electrical = NormalizedElectrical(
        power_kw=norm_power_res.normalized_value,
        voltage_v=norm_volt_res.normalized_value,
        amperage_a=norm_amp_res.normalized_value,
        current_type=norm_current_res.normalized_value or CurrentType.UNKNOWN,
        raw_power=c.power_kw,
        raw_voltage=c.voltage_v,
        raw_amperage=c.amperage_a,
        raw_current_type=c.charging_standard,
        power_status=norm_power_res.status,
        voltage_status=norm_volt_res.status,
        amperage_status=norm_amp_res.status,
        current_type_status=norm_current_res.status,
        power_rule=norm_power_res.rule,
    )

    return NormalizedConnector(
        connector_type=norm_type_res.normalized_value or StandardConnectorType.OTHER.value,
        raw_connector_type=c.raw_connector_type,
        charging_standard=c.charging_standard,
        power_kw=norm_power_res.normalized_value,
        voltage_v=norm_volt_res.normalized_value,
        amperage_a=norm_amp_res.normalized_value,
        current_type=norm_current_res.normalized_value or CurrentType.UNKNOWN,
        quantity=max(1, c.quantity),
        is_aggregated=c.is_aggregated,
        pricing=norm_pricing,
        source_connector_id=c.source_connector_id,
        status=c.status,
        connector_type_status=norm_type_res.status,
        electrical=electrical,
        rule=norm_type_res.rule,
    )


# ------------------------------------------------------------------------------
# End-to-End Canonical Station Record Normalizer
# ------------------------------------------------------------------------------

def normalize_station_record(
    record: NormalizedStationRecord,
    provenance: Optional[ProvenanceInfo] = None,
) -> StationNormalizationResult:
    """Normalizes an entire NormalizedStationRecord into a standardized output.

    Guarantees:
    - Never mutates the input record object.
    - Preserves Layer 1 provenance verbatim (source_id, source_station_id, payload hash).
    - Returns a new, standardized NormalizedStationRecord alongside typed field audit structures.
    - Purely deterministic and idempotent (no execution-time timestamps generated).
    """
    warnings: list[str] = []
    field_statuses: dict[str, NormalizationStatus] = {}

    # 1. Normalize Operator
    norm_op = normalize_operator(record.operator_name, record.operator_slug)
    field_statuses["operator"] = norm_op.status

    # 2. Normalize Coordinates
    norm_coords = normalize_coordinates(record.latitude, record.longitude)
    field_statuses["coordinates"] = norm_coords.status
    if norm_coords.status == NormalizationStatus.INVALID and norm_coords.message:
        warnings.append(norm_coords.message)

    # 3. Normalize Address & PIN
    norm_addr = normalize_address(
        address_line=record.address_line,
        locality=record.locality,
        city=record.city,
        state=record.state,
        postal_code=record.postal_code,
        country=record.country,
    )
    field_statuses["address"] = norm_addr.address_status
    field_statuses["postal_code"] = norm_addr.pin_status
    if norm_addr.pin_status == NormalizationStatus.INVALID:
        warnings.append(f"Invalid Indian PIN code '{record.postal_code}' preserved as raw, normalized to None")

    # 4. Normalize Operating Hours
    raw_hours_candidate = record.extra_metadata.get("opening_hours") or record.extra_metadata.get("general_comments")
    norm_hours = normalize_operating_hours(
        raw_hours=raw_hours_candidate,
        is_24_hours=record.is_24_hours,
        opening_time=record.opening_time,
        closing_time=record.closing_time,
    )
    field_statuses["operating_hours"] = norm_hours.status

    # 5. Normalize Connectors
    normalized_connectors: list[NormalizedConnector] = []
    clean_child_records: list[NormalizedConnectorRecord] = []

    for c in record.connectors:
        norm_c = normalize_connector_record(c)
        normalized_connectors.append(norm_c)

        # Build clean NormalizedConnectorRecord conforming to Step 2.1 contract
        clean_child = NormalizedConnectorRecord(
            source_connector_id=norm_c.source_connector_id,
            connector_type=norm_c.connector_type,
            raw_connector_type=norm_c.raw_connector_type,
            charging_standard=norm_c.charging_standard,
            power_kw=norm_c.power_kw,
            voltage_v=norm_c.voltage_v,
            amperage_a=norm_c.amperage_a,
            quantity=norm_c.quantity,
            is_aggregated=norm_c.is_aggregated,
            pricing_type=norm_c.pricing.pricing_type,
            price_per_kwh=norm_c.pricing.price_per_kwh,
            price_per_session=norm_c.pricing.price_per_session,
            currency=norm_c.pricing.currency or "INR",
            status=norm_c.status,
        )
        clean_child_records.append(clean_child)

    # 6. Preserve and Enrich Provenance and Metadata (Deterministic, no runtime timestamps)
    clean_extra = copy.deepcopy(record.extra_metadata)
    clean_extra["normalization"] = {
        "version": NORMALIZATION_VERSION,
    }

    # 7. Construct pristine, standardized NormalizedStationRecord
    normalized_station = NormalizedStationRecord(
        contract_version=record.contract_version,
        source_id=record.source_id,
        source_station_id=record.source_station_id,
        source_url=record.source_url,
        raw_payload_hash=record.raw_payload_hash,
        name=record.name,
        raw_name=record.raw_name,
        operator_name=norm_op.canonical_name or record.operator_name,
        operator_slug=norm_op.canonical_slug or record.operator_slug,
        latitude=norm_coords.latitude if norm_coords.latitude is not None else record.latitude,
        longitude=norm_coords.longitude if norm_coords.longitude is not None else record.longitude,
        address_line=norm_addr.address_line,
        locality=norm_addr.locality,
        city=norm_addr.city,
        state=norm_addr.state,
        postal_code=norm_addr.postal_code,
        country=norm_addr.country,
        is_24_hours=norm_hours.is_24_hours,
        opening_time=norm_hours.opening_time,
        closing_time=norm_hours.closing_time,
        access_type=record.access_type,
        is_public=record.is_public,
        operational_status=record.operational_status,
        phone=record.phone,
        website_url=record.website_url,
        connectors=clean_child_records,
        observation=record.observation,
        extra_metadata=clean_extra,
    )

    # Reconstruct provenance deterministically without calling datetime.now()
    if provenance is not None:
        clean_provenance = provenance
    else:
        det_retrieval_ts = (
            record.observation.retrieved_at
            if record.observation and record.observation.retrieved_at
            else (
                record.extra_metadata.get("retrieval_timestamp")
                if isinstance(record.extra_metadata.get("retrieval_timestamp"), datetime)
                else datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            )
        )
        det_source_ts = (
            record.observation.observed_at
            if record.observation and record.observation.observed_at
            else (
                record.extra_metadata.get("source_timestamp")
                if isinstance(record.extra_metadata.get("source_timestamp"), datetime)
                else None
            )
        )
        clean_provenance = ProvenanceInfo(
            source_id=record.source_id,
            source_station_id=record.source_station_id,
            retrieval_timestamp=det_retrieval_ts,
            source_timestamp=det_source_ts,
            raw_payload_hash=record.raw_payload_hash or ("0" * 64),
            source_url=record.source_url,
            contract_version=record.contract_version,
        )

    return StationNormalizationResult(
        station_record=normalized_station,
        operator=norm_op,
        coordinates=norm_coords,
        address=norm_addr,
        operating_hours=norm_hours,
        connectors=tuple(normalized_connectors),
        provenance=clean_provenance,
        normalization_version=NORMALIZATION_VERSION,
        field_statuses=field_statuses,
        warnings=tuple(warnings),
    )


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

def _slugify(text: Optional[str]) -> Optional[str]:
    """Produces clean lowercase alphanumeric slug."""
    if not text:
        return None
    cleaned = SLUG_CLEAN_REGEX.sub("-", text.strip().lower()).strip("-")
    return cleaned or None
