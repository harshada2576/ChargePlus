"""ChargePlus — Feature engineering (Phase 5/6, Step 5.3).

Static features derive from real station/connector attributes; unknown
stays None (never 0/mean-imputed unless a documented, train-fit transform
says so). Temporal features return None when no history exists. For any
prediction time T, only information valid at or before T may be used —
SCD2 versions resolve by event timestamp, never is_current.

FEATURE_DEFINITIONS mirrors the ml.features registry vocabulary
(feature_type / feature_group CHECK sets) so definitions can be
registered verbatim when evidence arrives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# Registry vocabulary mirrors ml.features CHECK constraints.
FEATURE_TYPES = {"categorical", "numerical", "boolean", "temporal",
                 "station_id", "geospatial", "count", "ratio",
                 "aggregate", "composite"}
FEATURE_GROUPS = {"demand_estimation", "queue_congestion",
                  "recommendation", "station_attributes",
                  "temporal_pattern", "general"}


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    feature_type: str
    feature_group: str
    description: str
    source_column: Optional[str] = None
    formula: Optional[str] = None
    generated_by: str = "raw_attribute"  # raw_attribute | derived | engineered

    def __post_init__(self) -> None:
        if self.feature_type not in FEATURE_TYPES:
            raise ValueError(f"unknown feature_type '{self.feature_type}'")
        if self.feature_group not in FEATURE_GROUPS:
            raise ValueError(f"unknown feature_group '{self.feature_group}'")


FEATURE_DEFINITIONS: list[FeatureDefinition] = [
    FeatureDefinition("station_latitude", "geospatial", "station_attributes",
                      "Station latitude (WGS84).", source_column="stations.latitude"),
    FeatureDefinition("station_longitude", "geospatial", "station_attributes",
                      "Station longitude (WGS84).", source_column="stations.longitude"),
    FeatureDefinition("operator_name", "categorical", "station_attributes",
                      "Canonical operator; 'Unknown Operator' preserved as unknown.",
                      source_column="operators.name"),
    FeatureDefinition("connector_count", "count", "station_attributes",
                      "Number of connector capacity groups; NULL when unreported.",
                      source_column="connectors.quantity"),
    FeatureDefinition("max_power_kw", "numerical", "station_attributes",
                      "Strongest connector power; NULL when all unknown.",
                      source_column="connectors.power_kw"),
    FeatureDefinition("has_known_power", "boolean", "station_attributes",
                      "Whether any connector has known power.",
                      formula="any(power_kw is not null)", generated_by="derived"),
    FeatureDefinition("is_24_hours", "boolean", "station_attributes",
                      "Always-open flag.", source_column="stations.is_24_hours"),
    FeatureDefinition("hour_of_day", "temporal", "temporal_pattern",
                      "Prediction hour (UTC, 0-23); NULL without event time.",
                      generated_by="derived"),
    FeatureDefinition("day_of_week", "temporal", "temporal_pattern",
                      "ISO weekday of prediction time (UTC); NULL without event time.",
                      generated_by="derived"),
    FeatureDefinition("recent_availability", "categorical", "queue_congestion",
                      "Most recent observed status at/before T; NULL without history.",
                      source_column="station_observations.availability_status",
                      generated_by="engineered"),
    FeatureDefinition("obs_count_7d", "count", "temporal_pattern",
                      "Observation count in trailing 7 days; NULL without history.",
                      generated_by="engineered"),
]


def static_features(station: dict[str, Any],
                    connectors: list[dict[str, Any]]) -> dict[str, Any]:
    """Real static attributes; unknowns stay None."""
    powers = [c["power_kw"] for c in connectors if c.get("power_kw") is not None]
    quantities = [c.get("quantity") for c in connectors if c.get("quantity") is not None]
    return {
        "station_latitude": station.get("latitude"),
        "station_longitude": station.get("longitude"),
        "operator_name": station.get("operator_name"),
        "connector_count": sum(quantities) if quantities else None,
        "max_power_kw": max(powers) if powers else None,
        "has_known_power": bool(powers),
        "is_24_hours": station.get("is_24_hours"),
    }


def temporal_features(events: list[dict[str, Any]],
                      at: datetime) -> dict[str, Any]:
    """History-derived features using only events at/before T.

    events: [{"ts": aware datetime, "availability_status": str, ...}].
    Empty history -> all None (never fabricated).
    """
    if at.tzinfo is None:
        raise ValueError("prediction time T must be timezone-aware")
    past = [e for e in events
            if isinstance(e.get("ts"), datetime) and e["ts"] <= at]
    if not past:
        return {"hour_of_day": at.hour, "day_of_week": at.isoweekday(),
                "recent_availability": None, "obs_count_7d": None}
    past.sort(key=lambda e: e["ts"])
    week_ago = at.timestamp() - 7 * 86400
    recent = [e for e in past if e["ts"].timestamp() >= week_ago]
    return {
        "hour_of_day": at.hour,
        "day_of_week": at.isoweekday(),
        "recent_availability": past[-1].get("availability_status"),
        "obs_count_7d": len(recent),
    }


def resolve_version_at(versions: list[dict[str, Any]],
                       ts: datetime) -> Optional[dict[str, Any]]:
    """SCD2 point-in-time resolution: version valid at ts, never is_current.

    versions: [{"station_key","effective_from","effective_to" or None}...].
    """
    if ts.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    best = None
    for v in versions:
        ef, et = v["effective_from"], v.get("effective_to")
        if ef <= ts and (et is None or et > ts):
            if best is None or ef > best["effective_from"]:
                best = v
    return best


@dataclass
class MeanImputer:
    """Documented imputation: means fit on TRAINING data only, applied after.

    Unfitted transform of None yields None (never silent zero-fill).
    """

    means: dict[str, float] = field(default_factory=dict)
    fitted: bool = False

    def fit(self, rows: list[dict[str, Any]], fields: list[str]) -> "MeanImputer":
        for f in fields:
            vals = [r[f] for r in rows if isinstance(r.get(f), (int, float))]
            if vals:
                self.means[f] = sum(vals) / len(vals)
        self.fitted = True
        return self

    def transform(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        if not self.fitted:
            return out
        for f, m in self.means.items():
            if out.get(f) is None:
                out[f] = m
        return out
