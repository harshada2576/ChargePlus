"""ChargePlus — Phase 5 ML Data Maturity Gate.

Phase: 5/6 (Data Mining, Forecasting & Recommendations)
Step: 5.1 (Measure Data Maturity)

Defines the data maturity gate that must be satisfied before training
or inference is allowed. The gate is fail-closed: insufficient data
produces NO_MODEL, not fabricated predictions.

Maturity States:
  COLD     — Not enough real historical observations for ML. Return NO_MODEL.
  WARMING  — Some observations exist but prediction quality not established.
              Simple baseline may be computed; ML inference disabled.
  READY    — Sufficient validated historical data to support the ML feature.

Key invariants:
  - Synthetic data NEVER counts toward production maturity.
  - A prediction is not an observation.
  - Insufficient evidence → safe typed response, not a fabricated prediction.
  - Do not lower thresholds merely to make the gate pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("chargeplus.ml.gates")


# ---------------------------------------------------------------------------
# 1. Maturity State
# ---------------------------------------------------------------------------

class DataMaturityState(str, Enum):
    """Canonical data maturity classification for ML feature eligibility."""
    COLD = "COLD"          # Insufficient history — ML training and inference disabled
    WARMING = "WARMING"    # Some history — baseline only, ML inference not yet enabled
    READY = "READY"        # Sufficient history — ML training and inference enabled


# ---------------------------------------------------------------------------
# 2. Typed "no model" response states
# ---------------------------------------------------------------------------

class MLUnavailableReason(str, Enum):
    """Typed reason why ML inference is unavailable.

    Used in API responses so callers can distinguish the root cause
    without parsing free-text messages.
    """
    NO_MODEL = "NO_MODEL"                      # No accepted model artifact exists
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"  # Not enough real observations
    STALE_FEATURES = "STALE_FEATURES"          # Feature data too old to be reliable
    FEATURE_SCHEMA_MISMATCH = "FEATURE_SCHEMA_MISMATCH"  # Model expects different features
    MODEL_ARTIFACT_INVALID = "MODEL_ARTIFACT_INVALID"    # Checksum or schema failure
    DATA_MATURITY_COLD = "DATA_MATURITY_COLD"  # Global data maturity is COLD
    DATA_MATURITY_WARMING = "DATA_MATURITY_WARMING"  # Data exists but quality not established
    TRAINING_IN_PROGRESS = "TRAINING_IN_PROGRESS"  # A training run is currently active


# ---------------------------------------------------------------------------
# 3. Gate configuration (authoritative thresholds)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MLGateConfig:
    """Immutable configuration for the ML data maturity gate.

    Thresholds are set conservatively. Do not lower them to make the gate pass.
    """
    # Minimum number of distinct real observation rows across all stations
    min_total_observations: int = 500
    # Minimum number of distinct stations with observations
    min_stations_with_observations: int = 5
    # Minimum number of distinct calendar days covered by observations
    min_observation_days: int = 30
    # Minimum number of observations per station eligible for training
    min_observations_per_station: int = 50
    # Maximum age of the most recent observation for the data to be considered fresh
    max_feature_staleness_hours: float = 72.0
    # WARMING threshold (some data, not ready for production ML)
    warming_min_observations: int = 50
    warming_min_stations: int = 2
    warming_min_days: int = 7


# Default gate configuration (authoritative; matches Architecture.md §12)
DEFAULT_GATE_CONFIG = MLGateConfig()


# ---------------------------------------------------------------------------
# 4. Maturity evidence
# ---------------------------------------------------------------------------

@dataclass
class DataMaturityEvidence:
    """Measured evidence used by the gate to classify data maturity.

    All fields are measured from real data; None means not measured.
    Synthetic-data evidence must never be included here.
    """
    total_real_observations: int = 0
    stations_with_observations: int = 0
    observation_days_covered: int = 0
    observations_per_station_min: Optional[int] = None  # min across stations
    observations_per_station_max: Optional[int] = None
    observations_per_station_median: Optional[float] = None
    earliest_observation: Optional[datetime] = None
    latest_observation: Optional[datetime] = None
    feature_freshness_hours: Optional[float] = None  # age of most recent data
    measured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_ids_present: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def history_span_days(self) -> Optional[float]:
        """Total calendar span of recorded observations in days."""
        if self.earliest_observation and self.latest_observation:
            span = self.latest_observation - self.earliest_observation
            return span.total_seconds() / 86400.0
        return None


# ---------------------------------------------------------------------------
# 5. Gate result
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Structured result from the ML maturity gate evaluation."""
    state: DataMaturityState
    evidence: DataMaturityEvidence
    passed: bool  # True only when state == READY
    failed_criteria: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reason: Optional[MLUnavailableReason] = None
    message: str = ""
    config: MLGateConfig = field(default_factory=lambda: DEFAULT_GATE_CONFIG)

    @property
    def unavailable_reason(self) -> Optional[MLUnavailableReason]:
        """Typed unavailability reason for API responses."""
        if self.passed:
            return None
        if self.state == DataMaturityState.COLD:
            return MLUnavailableReason.DATA_MATURITY_COLD
        if self.state == DataMaturityState.WARMING:
            return MLUnavailableReason.DATA_MATURITY_WARMING
        return self.reason

    def to_dict(self) -> dict[str, Any]:
        """Serializable representation for logging and API responses."""
        return {
            "state": self.state.value,
            "passed": self.passed,
            "failed_criteria": self.failed_criteria,
            "warnings": self.warnings,
            "reason": self.reason.value if self.reason else None,
            "unavailable_reason": self.unavailable_reason.value if self.unavailable_reason else None,
            "message": self.message,
            "evidence": {
                "total_real_observations": self.evidence.total_real_observations,
                "stations_with_observations": self.evidence.stations_with_observations,
                "observation_days_covered": self.evidence.observation_days_covered,
                "observations_per_station_min": self.evidence.observations_per_station_min,
                "observations_per_station_median": self.evidence.observations_per_station_median,
                "earliest_observation": (
                    self.evidence.earliest_observation.isoformat()
                    if self.evidence.earliest_observation
                    else None
                ),
                "latest_observation": (
                    self.evidence.latest_observation.isoformat()
                    if self.evidence.latest_observation
                    else None
                ),
                "history_span_days": self.evidence.history_span_days,
                "feature_freshness_hours": self.evidence.feature_freshness_hours,
                "measured_at": self.evidence.measured_at.isoformat(),
                "source_ids_present": self.evidence.source_ids_present,
                "notes": self.evidence.notes,
            },
            "required": {
                "min_total_observations": self.config.min_total_observations,
                "min_stations_with_observations": self.config.min_stations_with_observations,
                "min_observation_days": self.config.min_observation_days,
                "min_observations_per_station": self.config.min_observations_per_station,
                "max_feature_staleness_hours": self.config.max_feature_staleness_hours,
            },
        }


# ---------------------------------------------------------------------------
# 6. Gate evaluation logic
# ---------------------------------------------------------------------------

def evaluate_gate(
    evidence: DataMaturityEvidence,
    config: MLGateConfig = DEFAULT_GATE_CONFIG,
    as_of: Optional[datetime] = None,
) -> GateResult:
    """Evaluates whether the data maturity gate is satisfied.

    All threshold checks apply to real observations only.
    Synthetic data evidence must not be passed to this function.

    Returns GateResult with state COLD, WARMING, or READY.
    Only READY allows ML training and production inference.

    This function is pure: no database access, no side effects,
    deterministic given the same evidence and config.
    """
    as_of = as_of or datetime.now(timezone.utc)
    failed: list[str] = []
    warnings: list[str] = []

    # --- Check 1: Total real observations ---
    if evidence.total_real_observations < config.min_total_observations:
        failed.append(
            f"Insufficient observations: {evidence.total_real_observations} "
            f"(required ≥ {config.min_total_observations}). "
            f"Need {config.min_total_observations - evidence.total_real_observations} more."
        )

    # --- Check 2: Station coverage ---
    if evidence.stations_with_observations < config.min_stations_with_observations:
        failed.append(
            f"Insufficient station coverage: {evidence.stations_with_observations} station(s) "
            f"with observations (required ≥ {config.min_stations_with_observations})."
        )

    # --- Check 3: Temporal coverage ---
    if evidence.observation_days_covered < config.min_observation_days:
        failed.append(
            f"Insufficient temporal coverage: {evidence.observation_days_covered} calendar days "
            f"(required ≥ {config.min_observation_days})."
        )

    # --- Check 4: Per-station observation density ---
    if (
        evidence.observations_per_station_min is not None
        and evidence.observations_per_station_min < config.min_observations_per_station
    ):
        failed.append(
            f"Insufficient per-station density: minimum {evidence.observations_per_station_min} "
            f"observations/station (required ≥ {config.min_observations_per_station})."
        )

    # --- Check 5: Feature freshness ---
    if evidence.latest_observation is not None:
        age_hours = (as_of - evidence.latest_observation).total_seconds() / 3600.0
        if age_hours > config.max_feature_staleness_hours:
            failed.append(
                f"Feature data stale: latest observation is {age_hours:.1f}h old "
                f"(max allowed: {config.max_feature_staleness_hours}h). "
                "Ingest fresh data before training."
            )
    else:
        failed.append(
            "No observations recorded. Run ingestion to collect real station observations."
        )

    # --- Duplicate / invalid timestamp check ---
    if (
        evidence.earliest_observation is not None
        and evidence.latest_observation is not None
        and evidence.earliest_observation > evidence.latest_observation
    ):
        failed.append(
            "Data integrity error: earliest_observation is after latest_observation. "
            "Check observation timestamps before training."
        )

    # --- Classify state ---
    if not failed:
        state = DataMaturityState.READY
        passed = True
        message = (
            f"Gate PASSED. "
            f"{evidence.total_real_observations} observations across "
            f"{evidence.stations_with_observations} stations over "
            f"{evidence.observation_days_covered} days. "
            f"ML training and inference enabled."
        )
        reason = None
    else:
        passed = False
        # WARMING: some data exists, but not enough for READY
        if (
            evidence.total_real_observations >= config.warming_min_observations
            and evidence.stations_with_observations >= config.warming_min_stations
            and evidence.observation_days_covered >= config.warming_min_days
        ):
            state = DataMaturityState.WARMING
            message = (
                f"Gate WARMING. Some observations exist but production ML is not enabled. "
                f"Current: {evidence.total_real_observations} observations across "
                f"{evidence.stations_with_observations} station(s). "
                f"Failed criteria: {'; '.join(failed)}"
            )
        else:
            state = DataMaturityState.COLD
            message = (
                f"Gate COLD. Insufficient real observation history. "
                f"Current: {evidence.total_real_observations} observations. "
                f"Failed criteria: {'; '.join(failed)}"
            )

    logger.info("ML gate evaluation: state=%s passed=%s", state.value, passed)
    if failed:
        for criterion in failed:
            logger.info("  FAILED: %s", criterion)

    return GateResult(
        state=state,
        evidence=evidence,
        passed=passed,
        failed_criteria=failed,
        warnings=warnings,
        reason=None,
        message=message,
        config=config,
    )


# ---------------------------------------------------------------------------
# 7. Convenience: build evidence from a list of observation records
# ---------------------------------------------------------------------------

def build_evidence_from_records(
    observations: list[dict[str, Any]],
    as_of: Optional[datetime] = None,
) -> DataMaturityEvidence:
    """Builds DataMaturityEvidence from a list of observation dicts.

    Each dict must have at minimum:
      - 'station_id': str
      - 'observed_at': datetime or ISO 8601 string

    This is a pure helper for use in tests and ETL pipelines.
    Never call this with synthetic data intending to unlock production ML.
    """
    if not observations:
        return DataMaturityEvidence(
            notes=["No observations provided — COLD state."]
        )

    station_obs: dict[str, list[datetime]] = {}
    all_times: list[datetime] = []
    skipped_invalid = 0
    duplicate_exact = 0
    seen: set[tuple[str, str]] = set()

    for obs in observations:
        station_id = obs.get("station_id")
        raw_ts = obs.get("observed_at")

        if not station_id or raw_ts is None:
            skipped_invalid += 1
            continue

        # Parse timestamp
        if isinstance(raw_ts, datetime):
            ts = raw_ts
        elif isinstance(raw_ts, str):
            try:
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                skipped_invalid += 1
                continue
        else:
            skipped_invalid += 1
            continue

        # Ensure timezone-aware
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Exact (station_id, observed_at) duplicates indicate double-ingest,
        # not two independent observations: count once, report the rest.
        dup_key = (str(station_id), ts.isoformat())
        if dup_key in seen:
            duplicate_exact += 1
            continue
        seen.add(dup_key)

        station_obs.setdefault(station_id, []).append(ts)
        all_times.append(ts)

    if not all_times:
        notes = [f"All {skipped_invalid} observations skipped due to invalid timestamps or missing IDs."]
        return DataMaturityEvidence(notes=notes)

    all_times.sort()
    earliest = all_times[0]
    latest = all_times[-1]

    # Observation days: distinct UTC calendar days
    days_set: set[tuple[int, int, int]] = set()
    for ts in all_times:
        days_set.add((ts.year, ts.month, ts.day))

    # Per-station counts
    per_station_counts = [len(v) for v in station_obs.values()]
    per_station_counts.sort()
    n = len(per_station_counts)
    median_count: Optional[float] = None
    if n > 0:
        if n % 2 == 1:
            median_count = float(per_station_counts[n // 2])
        else:
            median_count = (per_station_counts[n // 2 - 1] + per_station_counts[n // 2]) / 2.0

    as_of = as_of or datetime.now(timezone.utc)
    freshness_hours = (as_of - latest).total_seconds() / 3600.0

    notes: list[str] = []
    if skipped_invalid > 0:
        notes.append(f"{skipped_invalid} observations skipped (invalid timestamp or missing station_id).")
    if duplicate_exact > 0:
        notes.append(
            f"{duplicate_exact} exact (station_id, observed_at) duplicates deduplicated "
            "(double-ingest evidence counts once toward maturity)."
        )

    return DataMaturityEvidence(
        total_real_observations=len(all_times),
        stations_with_observations=len(station_obs),
        observation_days_covered=len(days_set),
        observations_per_station_min=min(per_station_counts) if per_station_counts else None,
        observations_per_station_max=max(per_station_counts) if per_station_counts else None,
        observations_per_station_median=median_count,
        earliest_observation=earliest,
        latest_observation=latest,
        feature_freshness_hours=freshness_hours,
        measured_at=as_of,
        notes=notes,
    )
