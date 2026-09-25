"""ChargePlus — Data Quality Validation Engine.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.1 (Define Canonical Station/Connector Input Contract)

Applies rigorous data quality rules to NormalizedStationRecord instances.
Categorizes validation outcomes into:
- ACCEPT: Fully compliant, production ready.
- ACCEPT_WITH_WARNINGS: Compliant for ingestion, but missing optional attributes or has non-fatal warnings.
- QUARANTINE: Plausible physical record that requires operator review (e.g. geographic boundary anomaly).
- REJECT: Fatal non-negotiable defect (missing coordinates, invalid bounds, missing identity).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Optional
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
    StandardConnectorType,
    ValidationOutcome,
)
from backend.ingestion.contracts import NormalizedStationRecord


INDIAN_PINCODE_REGEX = re.compile(r"^[1-9][0-9]{5}$")
TIME_FORMAT_REGEX = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class ValidationResult(BaseModel):
    """Encapsulates the comprehensive data quality assessment of an incoming station record."""
    outcome: ValidationOutcome
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    quarantine_reasons: list[str] = Field(default_factory=list)
    quality_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Completeness and fidelity score between 0.0 (empty/invalid) and 1.0 (perfect)"
    )
    record: Optional[NormalizedStationRecord] = None

    class Config:
        extra = "forbid"


class DataQualityValidator:
    """Stateless validator implementing the ChargePlus Step 2.1 data quality contract."""

    @classmethod
    def validate_record(cls, record: NormalizedStationRecord) -> ValidationResult:
        """Validates a NormalizedStationRecord against all canonical business and physical rules."""
        errors: list[str] = []
        warnings: list[str] = []
        quarantine_reasons: list[str] = []

        # ----------------------------------------------------------------------
        # 1. Geographic & Coordinate Validation
        # ----------------------------------------------------------------------
        lat = record.latitude
        lng = record.longitude

        if not (-90.0 <= lat <= 90.0):
            errors.append(f"Latitude {lat} is out of physical range [-90, 90]")
        if not (-180.0 <= lng <= 180.0):
            errors.append(f"Longitude {lng} is out of physical range [-180, 180]")

        # Null Island check
        if abs(lat) < 1e-6 and abs(lng) < 1e-6:
            errors.append("Coordinates (0.0, 0.0) indicate placeholder/missing geolocation (Null Island)")

        # Country Geofence Check
        if record.country.lower() in ("india", "ind", "in"):
            is_in_india = (
                INDIA_LAT_MIN <= lat <= INDIA_LAT_MAX and
                INDIA_LNG_MIN <= lng <= INDIA_LNG_MAX
            )
            if not is_in_india:
                quarantine_reasons.append(
                    f"Station country is India, but coordinates ({lat:.4f}, {lng:.4f}) fall outside India bounding box"
                )

            # Pilot Mumbai boundary check (informational warning, not fatal)
            if record.city.lower() in ("mumbai", "bombay", "navi mumbai", "thane"):
                is_in_mmr = (
                    MUMBAI_LAT_MIN <= lat <= MUMBAI_LAT_MAX and
                    MUMBAI_LNG_MIN <= lng <= MUMBAI_LNG_MAX
                )
                if not is_in_mmr:
                    warnings.append(
                        f"Station city is '{record.city}', but coordinates ({lat:.4f}, {lng:.4f}) fall outside Greater Mumbai MMR box"
                    )

        # ----------------------------------------------------------------------
        # 2. Identity & Naming Validation
        # ----------------------------------------------------------------------
        if not record.source_id or not record.source_id.strip():
            errors.append("source_id cannot be empty (provenance requirement)")
        if not record.source_station_id or not record.source_station_id.strip():
            errors.append("source_station_id cannot be empty (source identity requirement)")
        if not record.name or len(record.name.strip()) < 2:
            errors.append("Station name must be at least 2 characters long")

        # ----------------------------------------------------------------------
        # 3. Address & Postal Code Validation
        # ----------------------------------------------------------------------
        if not record.address_line and not record.locality:
            warnings.append("Both address_line and locality are missing; location precision is coordinate-only")

        if record.postal_code:
            clean_pin = record.postal_code.strip()
            if record.country.lower() in ("india", "ind", "in"):
                if not INDIAN_PINCODE_REGEX.match(clean_pin):
                    warnings.append(f"Postal code '{clean_pin}' does not match standard Indian 6-digit PIN format")

        # ----------------------------------------------------------------------
        # 4. Operating Hours Validation
        # ----------------------------------------------------------------------
        if record.is_24_hours is True:
            if record.opening_time or record.closing_time:
                warnings.append("Station is marked 24-hours, but specific opening/closing times are also defined")
        elif record.is_24_hours is False:
            if record.opening_time and not TIME_FORMAT_REGEX.match(record.opening_time):
                warnings.append(f"Invalid opening_time format: '{record.opening_time}' (expected HH:MM)")
            if record.closing_time and not TIME_FORMAT_REGEX.match(record.closing_time):
                warnings.append(f"Invalid closing_time format: '{record.closing_time}' (expected HH:MM)")

        # ----------------------------------------------------------------------
        # 5. Connector Validation
        # ----------------------------------------------------------------------
        if not record.connectors:
            warnings.append("Station has 0 connectors reported by external source; stored as station shell")
        else:
            standard_enum_values = {e.value for e in StandardConnectorType}
            for idx, c in enumerate(record.connectors):
                # Connector Type Check
                if c.connector_type not in standard_enum_values:
                    warnings.append(
                        f"Connector [{idx}] has unmapped connector_type '{c.connector_type}'; raw label '{c.raw_connector_type}' preserved"
                    )

                # Power Validation
                if c.power_kw is not None:
                    if c.power_kw <= 0.0:
                        errors.append(f"Connector [{idx}] power_kw must be > 0 (got {c.power_kw})")
                    elif c.power_kw < MIN_PLAUSIBLE_POWER_KW or c.power_kw > MAX_PLAUSIBLE_POWER_KW:
                        warnings.append(
                            f"Connector [{idx}] power_kw {c.power_kw} is outside standard commercial range [{MIN_PLAUSIBLE_POWER_KW}kW, {MAX_PLAUSIBLE_POWER_KW}kW]"
                        )

                # Quantity Validation
                if c.quantity < 1:
                    errors.append(f"Connector [{idx}] quantity must be >= 1 (got {c.quantity})")

                # Tariff validation
                if c.price_per_kwh is not None and c.price_per_kwh < 0.0:
                    errors.append(f"Connector [{idx}] price_per_kwh cannot be negative (got {c.price_per_kwh})")

        # ----------------------------------------------------------------------
        # 6. Observation Validation
        # ----------------------------------------------------------------------
        if record.observation:
            obs = record.observation
            now_utc = datetime.now(timezone.utc)
            # Ensure observed_at has timezone
            obs_time = obs.observed_at if obs.observed_at.tzinfo else obs.observed_at.replace(tzinfo=timezone.utc)

            # Future timestamp check (5 min clock skew tolerance)
            if obs_time > now_utc + timedelta(minutes=5):
                errors.append(f"Observation timestamp {obs.observed_at} is in the future")

            # Stale telemetry warning (> 24 hours old)
            if now_utc - obs_time > timedelta(hours=24):
                age_hours = (now_utc - obs_time).total_seconds() / 3600.0
                warnings.append(f"Observation timestamp is stale ({age_hours:.1f} hours old); cannot be treated as real-time availability")

            # Connector availability consistency
            if obs.available_connectors is not None and obs.total_connectors is not None:
                if obs.available_connectors > obs.total_connectors:
                    errors.append(
                        f"Observation available_connectors ({obs.available_connectors}) exceeds total_connectors ({obs.total_connectors})"
                    )

        # ----------------------------------------------------------------------
        # 7. Quality Score Calculation (0.0 to 1.0)
        # ----------------------------------------------------------------------
        quality_score = cls._compute_quality_score(record, errors, warnings)

        # ----------------------------------------------------------------------
        # 8. Determine Outcome Category
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
            quality_score=quality_score,
            record=record if is_valid else None
        )

    @classmethod
    def _compute_quality_score(
        cls,
        record: NormalizedStationRecord,
        errors: list[str],
        warnings: list[str]
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
