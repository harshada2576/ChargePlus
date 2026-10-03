"""ChargePlus — Ingestion-Wide Data Quality Validation & Anomaly Quarantine.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.6 (Validate Records: Ingestion-Wide Data Quality Validation & Anomaly Quarantine)

Applies a comprehensive, deterministic, multi-layered data-quality evaluation framework to
NormalizedStationRecord instances before downstream canonical merging and persistence.

Outcomes:
- ACCEPT: Fully compliant, production ready.
- ACCEPT_WITH_WARNINGS: Compliant for ingestion, but has non-blocking quality limitations.
- QUARANTINE: Plausible physical record containing a serious anomaly requiring operator review.
- REJECT: Fatal non-negotiable defect (unusable, corrupt, missing coordinates/identity).

Architectural Invariants:
1. No silent repair: Bad data is never secretly corrected or coerced into defaults.
2. Missing means missing: Missing power -> None, missing price -> None, missing PIN -> None.
3. Separation of states: Operational status != Real-time availability != Stale telemetry.
4. Pure and deterministic: Zero random numbers, zero network calls, zero LLMs.
5. In-memory anomaly quarantine: Quarantined records are isolated from canonical operational tables.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
from enum import Enum
import re
import time
from typing import Any, Optional
from pydantic import BaseModel, Field

from backend.ingestion.constants import (
    INDIA_LAT_MAX,
    INDIA_LAT_MIN,
    INDIA_LNG_MAX,
    INDIA_LNG_MIN,
    MAX_PLAUSIBLE_POWER_KW,
    MIN_PLAUSIBLE_POWER_KW,
    MUMBAI_LAT_MAX,
    MUMBAI_LAT_MIN,
    MUMBAI_LNG_MAX,
    MUMBAI_LNG_MIN,
    OperationalStatus,
    PricingType,
    StandardConnectorType,
    ValidationOutcome,
)
from backend.ingestion.contracts import (
    NormalizedStationRecord,
    ProvenanceInfo,
)


INDIAN_PINCODE_REGEX = re.compile(r"^[1-9][0-9]{5}$")
TIME_FORMAT_REGEX = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
SHA256_HEX_REGEX = re.compile(r"^[a-fA-F0-9]{64}$")

# Suspicious placeholder names to flag
SUSPICIOUS_PLACEHOLDER_NAMES = {
    "test",
    "test station",
    "demo",
    "demo station",
    "dummy",
    "unknown",
    "unknown station",
    "sample",
    "temp",
    "temporary",
}


# ------------------------------------------------------------------------------
# Data Quality Enums & Models
# ------------------------------------------------------------------------------

class QualitySeverity(str, Enum):
    """Categorical severity of a data-quality finding."""
    INFO = "INFO"          # Informational finding (e.g. missing optional fields), non-blocking
    WARNING = "WARNING"    # Quality limitation or suspicious commercial value, non-blocking
    HIGH = "HIGH"          # Serious anomaly or boundary conflict, triggers QUARANTINE
    CRITICAL = "CRITICAL"  # Fatal non-negotiable defect, triggers REJECT


class QualityRuleCategory(str, Enum):
    """Functional domain category of a data-quality rule."""
    SCHEMA = "SCHEMA"
    COMPLETENESS = "COMPLETENESS"
    FORMAT = "FORMAT"
    GEOGRAPHY = "GEOGRAPHY"
    ELECTRICAL = "ELECTRICAL"
    CONNECTOR = "CONNECTOR"
    OPERATIONAL = "OPERATIONAL"
    PRICING = "PRICING"
    HOURS = "HOURS"
    CONSISTENCY = "CONSISTENCY"
    PROVENANCE = "PROVENANCE"


class QualityFinding(BaseModel):
    """Structured representation of an individual data-quality check finding."""
    rule_id: str = Field(..., description="Stable rule identifier, e.g. DQ-GEO-001")
    category: QualityRuleCategory = Field(..., description="Domain category of the check")
    severity: QualitySeverity = Field(..., description="Severity level: INFO, WARNING, HIGH, CRITICAL")
    field_name: str = Field(..., description="Field or attribute inspected")
    observed_value: Any = Field(default=None, description="Observed value or summary")
    expected_constraint: Optional[str] = Field(default=None, description="Expected constraint expression")
    message: str = Field(..., description="Human-readable explanation of the finding")
    is_blocking: bool = Field(default=False, description="True if this finding prevents operational persistence")

    class Config:
        extra = "forbid"


class QuarantineRecord(BaseModel):
    """Encapsulates a station record quarantined due to high-severity quality anomalies."""
    source_id: str
    source_station_id: str
    station_name: str
    outcome: ValidationOutcome = ValidationOutcome.QUARANTINE
    severity: QualitySeverity = QualitySeverity.HIGH
    failed_rule_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    findings: list[QualityFinding] = Field(default_factory=list)
    record: NormalizedStationRecord
    quarantined_at: datetime = Field(default_factory=lambda: datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
    provenance: Optional[ProvenanceInfo] = None

    class Config:
        extra = "forbid"


class ValidationResult(BaseModel):
    """Encapsulates the comprehensive data quality assessment of an incoming station record."""
    outcome: ValidationOutcome
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    quarantine_reasons: list[str] = Field(default_factory=list)
    findings: list[QualityFinding] = Field(default_factory=list)
    failed_rule_ids: list[str] = Field(default_factory=list)
    quality_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Completeness and fidelity score between 0.0 (empty/invalid) and 1.0 (perfect)"
    )
    record: Optional[NormalizedStationRecord] = None

    class Config:
        extra = "forbid"

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    @property
    def has_quarantine(self) -> bool:
        return bool(self.quarantine_reasons)


class BatchValidationReport(BaseModel):
    """Deterministic batch-level data quality summary and metrics."""
    total_records: int = 0
    records_accepted: int = 0
    records_accepted_with_warnings: int = 0
    records_quarantined: int = 0
    records_rejected: int = 0
    quarantined_records: list[QuarantineRecord] = Field(default_factory=list)
    rejected_records: list[ValidationResult] = Field(default_factory=list)
    results: list[ValidationResult] = Field(default_factory=list)
    issue_counts_by_rule: dict[str, int] = Field(default_factory=dict)
    issue_counts_by_severity: dict[str, int] = Field(default_factory=dict)
    issue_counts_by_source: dict[str, int] = Field(default_factory=dict)
    completeness_rates: dict[str, float] = Field(default_factory=dict)
    anomaly_rate: float = 0.0
    duration_seconds: float = 0.0

    class Config:
        extra = "forbid"

    def to_dict(self) -> dict[str, Any]:
        """Converts summary report to dictionary."""
        return {
            "total_records": self.total_records,
            "records_accepted": self.records_accepted,
            "records_accepted_with_warnings": self.records_accepted_with_warnings,
            "records_quarantined": self.records_quarantined,
            "records_rejected": self.records_rejected,
            "quarantined_count": len(self.quarantined_records),
            "rejected_count": len(self.rejected_records),
            "issue_counts_by_rule": self.issue_counts_by_rule,
            "issue_counts_by_severity": self.issue_counts_by_severity,
            "issue_counts_by_source": self.issue_counts_by_source,
            "completeness_rates": self.completeness_rates,
            "anomaly_rate": self.anomaly_rate,
            "duration_seconds": round(self.duration_seconds, 4),
        }


# ------------------------------------------------------------------------------
# Data Quality Validator Engine
# ------------------------------------------------------------------------------

class DataQualityValidator:
    """Stateless, pure-function validator implementing the ChargePlus Step 2.6 quality contract."""

    @classmethod
    def validate_record(
        cls,
        record: NormalizedStationRecord,
        current_time: Optional[datetime] = None,
    ) -> ValidationResult:
        """Validates a NormalizedStationRecord against all canonical business, physical, and quality rules.

        Guarantees:
        - Never mutates the input record object.
        - Produces deterministic, structured QualityFinding objects with stable rule IDs.
        - Correctly categorizes outcomes: ACCEPT, ACCEPT_WITH_WARNINGS, QUARANTINE, REJECT.
        """
        findings: list[QualityFinding] = []
        errors: list[str] = []
        warnings: list[str] = []
        quarantine_reasons: list[str] = []
        failed_rule_ids: list[str] = []

        now_utc = current_time or datetime.now(timezone.utc)

        # ----------------------------------------------------------------------
        # Layer 1 & 11: Schema, Provenance & Contract Validation
        # ----------------------------------------------------------------------
        # DQ-PROV-001: Source ID must be present and non-empty
        if not record.source_id or not str(record.source_id).strip():
            f = QualityFinding(
                rule_id="DQ-PROV-001",
                category=QualityRuleCategory.PROVENANCE,
                severity=QualitySeverity.CRITICAL,
                field_name="source_id",
                observed_value=record.source_id,
                expected_constraint="non-empty string (length >= 1)",
                message="source_id cannot be empty (provenance requirement)",
                is_blocking=True,
            )
            findings.append(f)
            errors.append(f.message)
            failed_rule_ids.append(f.rule_id)

        # DQ-PROV-002: Source Station ID must be present and non-empty
        if not record.source_station_id or not str(record.source_station_id).strip():
            f = QualityFinding(
                rule_id="DQ-PROV-002",
                category=QualityRuleCategory.PROVENANCE,
                severity=QualitySeverity.CRITICAL,
                field_name="source_station_id",
                observed_value=record.source_station_id,
                expected_constraint="non-empty string (length >= 1)",
                message="source_station_id cannot be empty (source identity requirement)",
                is_blocking=True,
            )
            findings.append(f)
            errors.append(f.message)
            failed_rule_ids.append(f.rule_id)

        # DQ-PROV-003: Contract version compatibility check
        if not record.contract_version or not str(record.contract_version).startswith("1."):
            f = QualityFinding(
                rule_id="DQ-PROV-003",
                category=QualityRuleCategory.SCHEMA,
                severity=QualitySeverity.CRITICAL,
                field_name="contract_version",
                observed_value=record.contract_version,
                expected_constraint="version 1.x.x",
                message=f"Incompatible contract_version '{record.contract_version}' (expected 1.x.x)",
                is_blocking=True,
            )
            findings.append(f)
            errors.append(f.message)
            failed_rule_ids.append(f.rule_id)

        # DQ-PROV-004: Payload hash format validation
        if record.raw_payload_hash is not None and not SHA256_HEX_REGEX.match(record.raw_payload_hash):
            f = QualityFinding(
                rule_id="DQ-PROV-004",
                category=QualityRuleCategory.PROVENANCE,
                severity=QualitySeverity.WARNING,
                field_name="raw_payload_hash",
                observed_value=record.raw_payload_hash,
                expected_constraint="64-character SHA-256 hexadecimal string",
                message=f"raw_payload_hash '{record.raw_payload_hash}' is not a valid 64-character SHA-256 digest",
                is_blocking=False,
            )
            findings.append(f)
            warnings.append(f.message)
            failed_rule_ids.append(f.rule_id)

        # ----------------------------------------------------------------------
        # Layer 2: Station Identity & Naming Validation
        # ----------------------------------------------------------------------
        # DQ-NAME-001: Station name length
        if not record.name or len(str(record.name).strip()) < 2:
            f = QualityFinding(
                rule_id="DQ-NAME-001",
                category=QualityRuleCategory.COMPLETENESS,
                severity=QualitySeverity.CRITICAL,
                field_name="name",
                observed_value=record.name,
                expected_constraint="string length >= 2",
                message="Station name must be at least 2 characters long",
                is_blocking=True,
            )
            findings.append(f)
            errors.append(f.message)
            failed_rule_ids.append(f.rule_id)
        elif str(record.name).strip().lower() in SUSPICIOUS_PLACEHOLDER_NAMES:
            # DQ-NAME-002: Suspicious placeholder name
            f = QualityFinding(
                rule_id="DQ-NAME-002",
                category=QualityRuleCategory.FORMAT,
                severity=QualitySeverity.WARNING,
                field_name="name",
                observed_value=record.name,
                expected_constraint="authentic physical station name",
                message=f"Station name '{record.name}' appears to be a test/demo placeholder",
                is_blocking=False,
            )
            findings.append(f)
            warnings.append(f.message)
            failed_rule_ids.append(f.rule_id)

        # DQ-OP-001: Missing operator identity (Informational completeness finding, non-blocking)
        if not record.operator_name and not record.operator_slug:
            f = QualityFinding(
                rule_id="DQ-OP-001",
                category=QualityRuleCategory.COMPLETENESS,
                severity=QualitySeverity.INFO,
                field_name="operator_name",
                observed_value=None,
                expected_constraint="operator identity recommended",
                message="Station operator is unspecified/unbranded; station identity is unbranded",
                is_blocking=False,
            )
            findings.append(f)
            failed_rule_ids.append(f.rule_id)

        # ----------------------------------------------------------------------
        # Layer 4: Geographic Coordinates & Bounding Box Validation
        # ----------------------------------------------------------------------
        lat = record.latitude
        lng = record.longitude

        # DQ-GEO-001: Latitude physical range
        if not (-90.0 <= lat <= 90.0):
            f = QualityFinding(
                rule_id="DQ-GEO-001",
                category=QualityRuleCategory.GEOGRAPHY,
                severity=QualitySeverity.CRITICAL,
                field_name="latitude",
                observed_value=lat,
                expected_constraint="latitude in [-90.0, 90.0]",
                message=f"Latitude {lat} is out of physical range [-90, 90]",
                is_blocking=True,
            )
            findings.append(f)
            errors.append(f.message)
            failed_rule_ids.append(f.rule_id)

        # DQ-GEO-002: Longitude physical range
        if not (-180.0 <= lng <= 180.0):
            f = QualityFinding(
                rule_id="DQ-GEO-002",
                category=QualityRuleCategory.GEOGRAPHY,
                severity=QualitySeverity.CRITICAL,
                field_name="longitude",
                observed_value=lng,
                expected_constraint="longitude in [-180.0, 180.0]",
                message=f"Longitude {lng} is out of physical range [-180, 180]",
                is_blocking=True,
            )
            findings.append(f)
            errors.append(f.message)
            failed_rule_ids.append(f.rule_id)

        # DQ-GEO-003: Null Island Sentinel check (lat=0 AND lng=0)
        # Individual 0.0 coordinates (Equator or Prime Meridian) are valid.
        if abs(lat) < 1e-6 and abs(lng) < 1e-6:
            f = QualityFinding(
                rule_id="DQ-GEO-003",
                category=QualityRuleCategory.GEOGRAPHY,
                severity=QualitySeverity.CRITICAL,
                field_name="coordinates",
                observed_value=(lat, lng),
                expected_constraint="non-(0.0, 0.0) coordinates",
                message="Coordinates (0.0, 0.0) indicate placeholder/missing geolocation (Null Island)",
                is_blocking=True,
            )
            findings.append(f)
            errors.append(f.message)
            failed_rule_ids.append(f.rule_id)

        # DQ-GEO-004: Country Geofence Check (Quarantine Anomaly)
        country_clean = str(record.country).strip().lower()
        if country_clean in ("india", "ind", "in"):
            is_in_india = (
                INDIA_LAT_MIN <= lat <= INDIA_LAT_MAX and
                INDIA_LNG_MIN <= lng <= INDIA_LNG_MAX
            )
            if not is_in_india:
                f = QualityFinding(
                    rule_id="DQ-GEO-004",
                    category=QualityRuleCategory.GEOGRAPHY,
                    severity=QualitySeverity.HIGH,
                    field_name="coordinates",
                    observed_value=(lat, lng),
                    expected_constraint=f"India bounding box [{INDIA_LAT_MIN}, {INDIA_LAT_MAX}] N, [{INDIA_LNG_MIN}, {INDIA_LNG_MAX}] E",
                    message=f"Station country is India, but coordinates ({lat:.4f}, {lng:.4f}) fall outside India bounding box",
                    is_blocking=True,
                )
                findings.append(f)
                quarantine_reasons.append(f.message)
                failed_rule_ids.append(f.rule_id)

            # DQ-GEO-005: Pilot Mumbai MMR boundary check (Informational warning, non-fatal)
            city_clean = str(record.city).strip().lower()
            if city_clean in ("mumbai", "bombay", "navi mumbai", "thane"):
                is_in_mmr = (
                    MUMBAI_LAT_MIN <= lat <= MUMBAI_LAT_MAX and
                    MUMBAI_LNG_MIN <= lng <= MUMBAI_LNG_MAX
                )
                if not is_in_mmr:
                    f = QualityFinding(
                        rule_id="DQ-GEO-005",
                        category=QualityRuleCategory.GEOGRAPHY,
                        severity=QualitySeverity.WARNING,
                        field_name="coordinates",
                        observed_value=(lat, lng),
                        expected_constraint=f"MMR pilot bounding box [{MUMBAI_LAT_MIN}, {MUMBAI_LAT_MAX}] N, [{MUMBAI_LNG_MIN}, {MUMBAI_LNG_MAX}] E",
                        message=f"Station city is '{record.city}', but coordinates ({lat:.4f}, {lng:.4f}) fall outside Greater Mumbai MMR box",
                        is_blocking=False,
                    )
                    findings.append(f)
                    warnings.append(f.message)
                    failed_rule_ids.append(f.rule_id)

        # ----------------------------------------------------------------------
        # Layer 3 & 4: Address & Postal Code Validation
        # ----------------------------------------------------------------------
        # DQ-ADDR-001: Missing address lines
        if not record.address_line and not record.locality:
            f = QualityFinding(
                rule_id="DQ-ADDR-001",
                category=QualityRuleCategory.COMPLETENESS,
                severity=QualitySeverity.INFO,
                field_name="address_line",
                observed_value=None,
                expected_constraint="at least address_line or locality present",
                message="Both address_line and locality are missing; location precision is coordinate-only",
                is_blocking=False,
            )
            findings.append(f)
            warnings.append(f.message)
            failed_rule_ids.append(f.rule_id)

        # DQ-ADDR-002: Indian PIN Code Format
        if record.postal_code:
            clean_pin = str(record.postal_code).strip()
            if country_clean in ("india", "ind", "in"):
                if not INDIAN_PINCODE_REGEX.match(clean_pin):
                    f = QualityFinding(
                        rule_id="DQ-ADDR-002",
                        category=QualityRuleCategory.FORMAT,
                        severity=QualitySeverity.WARNING,
                        field_name="postal_code",
                        observed_value=clean_pin,
                        expected_constraint="6-digit Indian PIN (^[1-9][0-9]{5}$)",
                        message=f"Postal code '{clean_pin}' does not match standard Indian 6-digit PIN format",
                        is_blocking=False,
                    )
                    findings.append(f)
                    warnings.append(f.message)
                    failed_rule_ids.append(f.rule_id)

        # ----------------------------------------------------------------------
        # Layer 9: Operating Hours Validation
        # ----------------------------------------------------------------------
        if record.is_24_hours is True:
            # DQ-HOURS-001: 24/7 Hours constraint conflict
            if record.opening_time or record.closing_time:
                f = QualityFinding(
                    rule_id="DQ-HOURS-001",
                    category=QualityRuleCategory.CONSISTENCY,
                    severity=QualitySeverity.WARNING,
                    field_name="is_24_hours",
                    observed_value=(record.opening_time, record.closing_time),
                    expected_constraint="opening_time=None and closing_time=None when is_24_hours=True (chk_stations_hours)",
                    message="Station is marked 24-hours, but specific opening/closing times are also defined",
                    is_blocking=False,
                )
                findings.append(f)
                warnings.append(f.message)
                failed_rule_ids.append(f.rule_id)

            # DQ-HOURS-003: Schedule contradiction (24/7 flag vs closed schedule or status)
            comments = str(record.extra_metadata.get("general_comments", "")).lower()
            hours_text = str(record.extra_metadata.get("opening_hours", "")).lower()
            is_closed_status = record.operational_status in (
                OperationalStatus.PERMANENTLY_CLOSED,
                OperationalStatus.TEMPORARILY_UNAVAILABLE,
            )
            if "permanently closed" in comments or "closed all days" in hours_text or "shut down" in comments or is_closed_status:
                f = QualityFinding(
                    rule_id="DQ-HOURS-003",
                    category=QualityRuleCategory.HOURS,
                    severity=QualitySeverity.HIGH,
                    field_name="is_24_hours",
                    observed_value="24h marked but comments or status indicate station closed",
                    expected_constraint="consistent operational hours declaration",
                    message="Station is marked 24/7 but metadata or status indicates closed or contradictory operating schedule",
                    is_blocking=True,
                )
                findings.append(f)
                quarantine_reasons.append(f.message)
                failed_rule_ids.append(f.rule_id)

        elif record.is_24_hours is False:
            # DQ-HOURS-002: Invalid time formats
            if record.opening_time and not TIME_FORMAT_REGEX.match(record.opening_time):
                f = QualityFinding(
                    rule_id="DQ-HOURS-002",
                    category=QualityRuleCategory.FORMAT,
                    severity=QualitySeverity.CRITICAL,
                    field_name="opening_time",
                    observed_value=record.opening_time,
                    expected_constraint="HH:MM (24-hour clock)",
                    message=f"Invalid opening_time format: '{record.opening_time}' (expected HH:MM)",
                    is_blocking=True,
                )
                findings.append(f)
                errors.append(f.message)
                failed_rule_ids.append(f.rule_id)

            if record.closing_time and not TIME_FORMAT_REGEX.match(record.closing_time):
                f = QualityFinding(
                    rule_id="DQ-HOURS-002",
                    category=QualityRuleCategory.FORMAT,
                    severity=QualitySeverity.CRITICAL,
                    field_name="closing_time",
                    observed_value=record.closing_time,
                    expected_constraint="HH:MM (24-hour clock)",
                    message=f"Invalid closing_time format: '{record.closing_time}' (expected HH:MM)",
                    is_blocking=True,
                )
                findings.append(f)
                errors.append(f.message)
                failed_rule_ids.append(f.rule_id)

        # ----------------------------------------------------------------------
        # Layer 5, 6 & 8: Connectors, Electrical & Pricing Validation
        # ----------------------------------------------------------------------
        # DQ-CONN-001: Shell station with 0 connectors
        if not record.connectors:
            f = QualityFinding(
                rule_id="DQ-CONN-001",
                category=QualityRuleCategory.CONNECTOR,
                severity=QualitySeverity.INFO,
                field_name="connectors",
                observed_value=0,
                expected_constraint="at least 1 connector recommended",
                message="Station has 0 connectors reported by external source; stored as station shell",
                is_blocking=False,
            )
            findings.append(f)
            warnings.append(f.message)
            failed_rule_ids.append(f.rule_id)
        else:
            standard_enum_values = {e.value for e in StandardConnectorType}
            for idx, c in enumerate(record.connectors):
                # DQ-CONN-003: Connector Type Check
                if c.connector_type not in standard_enum_values:
                    f = QualityFinding(
                        rule_id="DQ-CONN-003",
                        category=QualityRuleCategory.CONNECTOR,
                        severity=QualitySeverity.WARNING,
                        field_name=f"connectors[{idx}].connector_type",
                        observed_value=c.connector_type,
                        expected_constraint="StandardConnectorType canonical vocabulary",
                        message=f"Connector [{idx}] has unmapped connector_type '{c.connector_type}'; raw label '{c.raw_connector_type}' preserved",
                        is_blocking=False,
                    )
                    findings.append(f)
                    warnings.append(f.message)
                    failed_rule_ids.append(f.rule_id)

                # DQ-CONN-002: Connector Quantity Validation
                if c.quantity < 1:
                    f = QualityFinding(
                        rule_id="DQ-CONN-002",
                        category=QualityRuleCategory.CONNECTOR,
                        severity=QualitySeverity.CRITICAL,
                        field_name=f"connectors[{idx}].quantity",
                        observed_value=c.quantity,
                        expected_constraint="quantity >= 1",
                        message=f"Connector [{idx}] quantity must be >= 1 (got {c.quantity})",
                        is_blocking=True,
                    )
                    findings.append(f)
                    errors.append(f.message)
                    failed_rule_ids.append(f.rule_id)
                elif c.quantity > 50:
                    # DQ-CONN-004: Suspicious connector quantity
                    f = QualityFinding(
                        rule_id="DQ-CONN-004",
                        category=QualityRuleCategory.CONNECTOR,
                        severity=QualitySeverity.WARNING,
                        field_name=f"connectors[{idx}].quantity",
                        observed_value=c.quantity,
                        expected_constraint="quantity <= 50",
                        message=f"Connector [{idx}] quantity ({c.quantity}) is unusually high for a single specification",
                        is_blocking=False,
                    )
                    findings.append(f)
                    warnings.append(f.message)
                    failed_rule_ids.append(f.rule_id)

                # Electrical Power Plausibility Validation
                if c.power_kw is not None:
                    # DQ-ELEC-001: Non-positive power
                    if c.power_kw <= 0.0:
                        f = QualityFinding(
                            rule_id="DQ-ELEC-001",
                            category=QualityRuleCategory.ELECTRICAL,
                            severity=QualitySeverity.CRITICAL,
                            field_name=f"connectors[{idx}].power_kw",
                            observed_value=c.power_kw,
                            expected_constraint="power_kw > 0.0",
                            message=f"Connector [{idx}] power_kw must be > 0 (got {c.power_kw})",
                            is_blocking=True,
                        )
                        findings.append(f)
                        errors.append(f.message)
                        failed_rule_ids.append(f.rule_id)
                    elif c.power_kw > 2000.0:
                        # DQ-ELEC-002: Extreme implausible power anomaly (Quarantine)
                        f = QualityFinding(
                            rule_id="DQ-ELEC-002",
                            category=QualityRuleCategory.ELECTRICAL,
                            severity=QualitySeverity.HIGH,
                            field_name=f"connectors[{idx}].power_kw",
                            observed_value=c.power_kw,
                            expected_constraint="power_kw <= 2000.0 kW",
                            message=f"Connector [{idx}] power_kw {c.power_kw}kW exceeds maximum physical EV limit (2000kW)",
                            is_blocking=True,
                        )
                        findings.append(f)
                        quarantine_reasons.append(f.message)
                        failed_rule_ids.append(f.rule_id)
                    elif c.power_kw < MIN_PLAUSIBLE_POWER_KW or c.power_kw > MAX_PLAUSIBLE_POWER_KW:
                        # DQ-ELEC-003: Suspicious commercial power warning
                        f = QualityFinding(
                            rule_id="DQ-ELEC-003",
                            category=QualityRuleCategory.ELECTRICAL,
                            severity=QualitySeverity.WARNING,
                            field_name=f"connectors[{idx}].power_kw",
                            observed_value=c.power_kw,
                            expected_constraint=f"[{MIN_PLAUSIBLE_POWER_KW}kW, {MAX_PLAUSIBLE_POWER_KW}kW]",
                            message=f"Connector [{idx}] power_kw {c.power_kw} is outside standard commercial range [{MIN_PLAUSIBLE_POWER_KW}kW, {MAX_PLAUSIBLE_POWER_KW}kW]",
                            is_blocking=False,
                        )
                        findings.append(f)
                        warnings.append(f.message)
                        failed_rule_ids.append(f.rule_id)
                else:
                    # DQ-ELEC-008: Missing power_kw recommendation
                    f = QualityFinding(
                        rule_id="DQ-ELEC-008",
                        category=QualityRuleCategory.ELECTRICAL,
                        severity=QualitySeverity.WARNING,
                        field_name=f"connectors[{idx}].power_kw",
                        observed_value=None,
                        expected_constraint="power_kw recommended for operational utility",
                        message=f"Connector [{idx}] is missing power_kw rating; power is unknown",
                        is_blocking=False,
                    )
                    findings.append(f)
                    warnings.append(f.message)
                    failed_rule_ids.append(f.rule_id)

                # Electrical Voltage Validation
                if c.voltage_v is not None:
                    if c.voltage_v <= 0.0:
                        # DQ-ELEC-004: Non-positive voltage
                        f = QualityFinding(
                            rule_id="DQ-ELEC-004",
                            category=QualityRuleCategory.ELECTRICAL,
                            severity=QualitySeverity.CRITICAL,
                            field_name=f"connectors[{idx}].voltage_v",
                            observed_value=c.voltage_v,
                            expected_constraint="voltage_v > 0.0",
                            message=f"Connector [{idx}] voltage_v must be > 0 (got {c.voltage_v})",
                            is_blocking=True,
                        )
                        findings.append(f)
                        errors.append(f.message)
                        failed_rule_ids.append(f.rule_id)
                    elif c.voltage_v > 1000.0:
                        # DQ-ELEC-005: Suspicious voltage
                        f = QualityFinding(
                            rule_id="DQ-ELEC-005",
                            category=QualityRuleCategory.ELECTRICAL,
                            severity=QualitySeverity.WARNING,
                            field_name=f"connectors[{idx}].voltage_v",
                            observed_value=c.voltage_v,
                            expected_constraint="voltage_v <= 1000.0 V",
                            message=f"Connector [{idx}] voltage_v {c.voltage_v}V exceeds standard commercial ceiling (1000V)",
                            is_blocking=False,
                        )
                        findings.append(f)
                        warnings.append(f.message)
                        failed_rule_ids.append(f.rule_id)

                # Electrical Amperage Validation
                if c.amperage_a is not None:
                    if c.amperage_a <= 0.0:
                        # DQ-ELEC-006: Non-positive amperage
                        f = QualityFinding(
                            rule_id="DQ-ELEC-006",
                            category=QualityRuleCategory.ELECTRICAL,
                            severity=QualitySeverity.CRITICAL,
                            field_name=f"connectors[{idx}].amperage_a",
                            observed_value=c.amperage_a,
                            expected_constraint="amperage_a > 0.0",
                            message=f"Connector [{idx}] amperage_a must be > 0 (got {c.amperage_a})",
                            is_blocking=True,
                        )
                        findings.append(f)
                        errors.append(f.message)
                        failed_rule_ids.append(f.rule_id)
                    elif c.amperage_a > 1000.0:
                        # DQ-ELEC-007: Suspicious amperage
                        f = QualityFinding(
                            rule_id="DQ-ELEC-007",
                            category=QualityRuleCategory.ELECTRICAL,
                            severity=QualitySeverity.WARNING,
                            field_name=f"connectors[{idx}].amperage_a",
                            observed_value=c.amperage_a,
                            expected_constraint="amperage_a <= 1000.0 A",
                            message=f"Connector [{idx}] amperage_a {c.amperage_a}A exceeds standard commercial ceiling (1000A)",
                            is_blocking=False,
                        )
                        findings.append(f)
                        warnings.append(f.message)
                        failed_rule_ids.append(f.rule_id)

                # Pricing / Tariff Validation
                # DQ-PRICE-001: Negative per-kWh tariff
                if c.price_per_kwh is not None and c.price_per_kwh < 0.0:
                    f = QualityFinding(
                        rule_id="DQ-PRICE-001",
                        category=QualityRuleCategory.PRICING,
                        severity=QualitySeverity.CRITICAL,
                        field_name=f"connectors[{idx}].price_per_kwh",
                        observed_value=c.price_per_kwh,
                        expected_constraint="price_per_kwh >= 0.0",
                        message=f"Connector [{idx}] price_per_kwh cannot be negative (got {c.price_per_kwh})",
                        is_blocking=True,
                    )
                    findings.append(f)
                    errors.append(f.message)
                    failed_rule_ids.append(f.rule_id)

                # DQ-PRICE-001b: Negative session tariff
                if c.price_per_session is not None and c.price_per_session < 0.0:
                    f = QualityFinding(
                        rule_id="DQ-PRICE-001",
                        category=QualityRuleCategory.PRICING,
                        severity=QualitySeverity.CRITICAL,
                        field_name=f"connectors[{idx}].price_per_session",
                        observed_value=c.price_per_session,
                        expected_constraint="price_per_session >= 0.0",
                        message=f"Connector [{idx}] price_per_session cannot be negative (got {c.price_per_session})",
                        is_blocking=True,
                    )
                    findings.append(f)
                    errors.append(f.message)
                    failed_rule_ids.append(f.rule_id)

                # DQ-PRICE-002: Contradictory free pricing
                if c.pricing_type == PricingType.FREE and c.price_per_kwh is not None and c.price_per_kwh > 0.0:
                    f = QualityFinding(
                        rule_id="DQ-PRICE-002",
                        category=QualityRuleCategory.PRICING,
                        severity=QualitySeverity.HIGH,
                        field_name=f"connectors[{idx}].price_per_kwh",
                        observed_value=c.price_per_kwh,
                        expected_constraint="price_per_kwh == 0.0 or None when pricing_type is FREE",
                        message=f"Connector [{idx}] marked as FREE charging but specifies paid tariff rate of {c.price_per_kwh} {c.currency}/kWh",
                        is_blocking=True,
                    )
                    findings.append(f)
                    quarantine_reasons.append(f.message)
                    failed_rule_ids.append(f.rule_id)

                # DQ-PRICE-003: Missing pricing information recommendation
                if c.price_per_kwh is None and c.price_per_session is None and (c.pricing_type is None or c.pricing_type == PricingType.UNKNOWN):
                    f = QualityFinding(
                        rule_id="DQ-PRICE-003",
                        category=QualityRuleCategory.PRICING,
                        severity=QualitySeverity.WARNING,
                        field_name=f"connectors[{idx}].pricing",
                        observed_value=None,
                        expected_constraint="pricing details recommended (pricing_type, price_per_kwh)",
                        message=f"Connector [{idx}] is missing pricing details; tariff is unknown (not assumed free)",
                        is_blocking=False,
                    )
                    findings.append(f)
                    warnings.append(f.message)
                    failed_rule_ids.append(f.rule_id)

                # DQ-PRICE-004: Currency code format & validity
                if c.currency:
                    curr_str = str(c.currency).strip()
                    if not curr_str.isalpha():
                        f = QualityFinding(
                            rule_id="DQ-PRICE-004",
                            category=QualityRuleCategory.FORMAT,
                            severity=QualitySeverity.CRITICAL,
                            field_name=f"connectors[{idx}].currency",
                            observed_value=c.currency,
                            expected_constraint="ISO alphabetic currency code (e.g. INR, USD)",
                            message=f"Connector [{idx}] currency code '{c.currency}' contains invalid non-alphabetic characters",
                            is_blocking=True,
                        )
                        findings.append(f)
                        errors.append(f.message)
                        failed_rule_ids.append(f.rule_id)
                    elif len(curr_str) > 10:
                        f = QualityFinding(
                            rule_id="DQ-PRICE-004",
                            category=QualityRuleCategory.FORMAT,
                            severity=QualitySeverity.WARNING,
                            field_name=f"connectors[{idx}].currency",
                            observed_value=c.currency,
                            expected_constraint="currency length <= 10",
                            message=f"Connector [{idx}] currency code '{c.currency}' exceeds 10 characters",
                            is_blocking=False,
                        )
                        findings.append(f)
                        warnings.append(f.message)
                        failed_rule_ids.append(f.rule_id)

        # ----------------------------------------------------------------------
        # Layer 7: Operational Semantic & Telemetry Observation Validation
        # ----------------------------------------------------------------------
        if record.observation:
            obs = record.observation
            obs_time = obs.observed_at if obs.observed_at.tzinfo else obs.observed_at.replace(tzinfo=timezone.utc)

            # DQ-OBS-001: Future timestamp check (5 min clock skew tolerance)
            if obs_time > now_utc + timedelta(minutes=5):
                f = QualityFinding(
                    rule_id="DQ-OBS-001",
                    category=QualityRuleCategory.OPERATIONAL,
                    severity=QualitySeverity.CRITICAL,
                    field_name="observation.observed_at",
                    observed_value=obs.observed_at.isoformat(),
                    expected_constraint=f"observed_at <= {now_utc.isoformat()} + 5m",
                    message=f"Observation timestamp {obs.observed_at} is in the future",
                    is_blocking=True,
                )
                findings.append(f)
                errors.append(f.message)
                failed_rule_ids.append(f.rule_id)

            # DQ-OBS-002: Stale telemetry warning (> 24 hours old)
            if now_utc - obs_time > timedelta(hours=24):
                age_hours = (now_utc - obs_time).total_seconds() / 3600.0
                f = QualityFinding(
                    rule_id="DQ-OBS-002",
                    category=QualityRuleCategory.OPERATIONAL,
                    severity=QualitySeverity.WARNING,
                    field_name="observation.observed_at",
                    observed_value=obs.observed_at.isoformat(),
                    expected_constraint="telemetry observed_at within last 24 hours for live status",
                    message=f"Observation timestamp is stale ({age_hours:.1f} hours old); cannot be treated as real-time availability",
                    is_blocking=False,
                )
                findings.append(f)
                warnings.append(f.message)
                failed_rule_ids.append(f.rule_id)

            # DQ-OBS-003: Connector availability consistency
            if obs.available_connectors is not None and obs.total_connectors is not None:
                if obs.available_connectors > obs.total_connectors:
                    f = QualityFinding(
                        rule_id="DQ-OBS-003",
                        category=QualityRuleCategory.CONSISTENCY,
                        severity=QualitySeverity.CRITICAL,
                        field_name="observation.available_connectors",
                        observed_value=f"available={obs.available_connectors}, total={obs.total_connectors}",
                        expected_constraint="available_connectors <= total_connectors",
                        message=f"Observation available_connectors ({obs.available_connectors}) exceeds total_connectors ({obs.total_connectors})",
                        is_blocking=True,
                    )
                    findings.append(f)
                    errors.append(f.message)
                    failed_rule_ids.append(f.rule_id)

        # ----------------------------------------------------------------------
        # Quality Score Calculation (0.0 to 1.0)
        # ----------------------------------------------------------------------
        quality_score = cls._compute_quality_score(record, errors, warnings)

        # ----------------------------------------------------------------------
        # Determine Outcome Category
        # ----------------------------------------------------------------------
        if errors:
            outcome = ValidationOutcome.REJECT
            is_valid = False
        elif quarantine_reasons:
            outcome = ValidationOutcome.QUARANTINE
            is_valid = False
        elif warnings:
            outcome = ValidationOutcome.ACCEPT_WITH_WARNINGS
            is_valid = True
        else:
            outcome = ValidationOutcome.ACCEPT
            is_valid = True

        return ValidationResult(
            outcome=outcome,
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            quarantine_reasons=quarantine_reasons,
            findings=findings,
            failed_rule_ids=failed_rule_ids,
            quality_score=quality_score,
            record=record if is_valid else None,
        )

    @classmethod
    def create_quarantine_record(
        cls,
        record: NormalizedStationRecord,
        validation_result: ValidationResult,
    ) -> QuarantineRecord:
        """Converts a quarantined station into a structured QuarantineRecord.

        Preserves full provenance, all validation findings, and reasons without mutating
        the source record.
        """
        provenance = (
            record.to_provenance()
            if hasattr(record, "to_provenance")
            else ProvenanceInfo(
                source_id=record.source_id,
                source_station_id=record.source_station_id,
                raw_payload_hash=record.raw_payload_hash or ("0" * 64),
                source_url=record.source_url,
                contract_version=record.contract_version,
            )
        )

        return QuarantineRecord(
            source_id=record.source_id,
            source_station_id=record.source_station_id,
            station_name=record.name,
            outcome=ValidationOutcome.QUARANTINE,
            severity=QualitySeverity.HIGH,
            failed_rule_ids=list(validation_result.failed_rule_ids),
            reasons=list(validation_result.quarantine_reasons),
            findings=list(validation_result.findings),
            record=copy.deepcopy(record),
            quarantined_at=datetime.now(timezone.utc),
            provenance=provenance,
        )

    @classmethod
    def validate_batch(
        cls,
        records: list[NormalizedStationRecord],
        current_time: Optional[datetime] = None,
    ) -> BatchValidationReport:
        """Validates an entire batch of NormalizedStationRecord instances.

        Produces comprehensive, deterministic metrics, issue frequency breakdowns,
        field completeness ratios, and an anomaly quarantine ledger without dropping
        any input records.
        """
        start_time = time.time()
        results: list[ValidationResult] = []
        quarantined_records: list[QuarantineRecord] = []
        rejected_records: list[ValidationResult] = []

        accepted_count = 0
        accepted_warnings_count = 0
        quarantined_count = 0
        rejected_count = 0

        rule_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}

        # Completeness counters
        op_count = 0
        addr_count = 0
        pin_count = 0
        power_count = 0
        hours_count = 0
        telemetry_count = 0

        for r in records:
            res = cls.validate_record(r, current_time=current_time)
            results.append(res)

            # Update outcomes
            if res.outcome == ValidationOutcome.ACCEPT:
                accepted_count += 1
            elif res.outcome == ValidationOutcome.ACCEPT_WITH_WARNINGS:
                accepted_warnings_count += 1
            elif res.outcome == ValidationOutcome.QUARANTINE:
                quarantined_count += 1
                q_rec = cls.create_quarantine_record(r, res)
                quarantined_records.append(q_rec)
            elif res.outcome == ValidationOutcome.REJECT:
                rejected_count += 1
                rejected_records.append(res)

            # Aggregate finding metrics
            for f in res.findings:
                rule_counts[f.rule_id] = rule_counts.get(f.rule_id, 0) + 1
                severity_counts[f.severity.value] = severity_counts.get(f.severity.value, 0) + 1

            if res.failed_rule_ids:
                source_counts[r.source_id] = source_counts.get(r.source_id, 0) + len(res.failed_rule_ids)

            # Completeness tracking
            if r.operator_name or r.operator_slug:
                op_count += 1
            if r.address_line or r.locality:
                addr_count += 1
            if r.postal_code:
                pin_count += 1
            if any(c.power_kw is not None for c in r.connectors):
                power_count += 1
            if r.is_24_hours is not None or (r.opening_time and r.closing_time):
                hours_count += 1
            if r.observation:
                telemetry_count += 1

        total = len(records)
        duration = time.time() - start_time

        completeness_rates = {
            "operator_completeness": round(op_count / total, 4) if total > 0 else 0.0,
            "address_completeness": round(addr_count / total, 4) if total > 0 else 0.0,
            "pin_completeness": round(pin_count / total, 4) if total > 0 else 0.0,
            "power_completeness": round(power_count / total, 4) if total > 0 else 0.0,
            "hours_completeness": round(hours_count / total, 4) if total > 0 else 0.0,
            "telemetry_completeness": round(telemetry_count / total, 4) if total > 0 else 0.0,
        }

        anomaly_rate = round((quarantined_count + rejected_count) / total, 4) if total > 0 else 0.0

        return BatchValidationReport(
            total_records=total,
            records_accepted=accepted_count,
            records_accepted_with_warnings=accepted_warnings_count,
            records_quarantined=quarantined_count,
            records_rejected=rejected_count,
            quarantined_records=quarantined_records,
            rejected_records=rejected_records,
            results=results,
            issue_counts_by_rule=rule_counts,
            issue_counts_by_severity=severity_counts,
            issue_counts_by_source=source_counts,
            completeness_rates=completeness_rates,
            anomaly_rate=anomaly_rate,
            duration_seconds=duration,
        )

    @classmethod
    def _compute_quality_score(
        cls,
        record: NormalizedStationRecord,
        errors: list[str],
        warnings: list[str],
    ) -> float:
        """Calculates completeness score based on presence of high-value operational attributes."""
        if errors:
            return 0.0

        score = 0.40  # Base score for valid coordinates and name

        # Operator identity (+0.10)
        if record.operator_name or record.operator_slug:
            score += 0.10

        # Locality / address richness (+0.10)
        if record.locality or record.address_line:
            score += 0.10
        if record.postal_code:
            score += 0.05

        # Connector details (+0.15)
        if record.connectors:
            score += 0.10
            if any(c.power_kw is not None for c in record.connectors):
                score += 0.05

        # Operating hours (+0.05)
        if record.is_24_hours is not None or (record.opening_time and record.closing_time):
            score += 0.05

        # Contact / website (+0.05)
        if record.phone or record.website_url:
            score += 0.05

        # Live telemetry present (+0.10)
        if record.observation:
            score += 0.10

        # Penalty for warnings
        penalty = min(0.20, len(warnings) * 0.04)
        return round(max(0.1, min(1.0, score - penalty)), 2)
