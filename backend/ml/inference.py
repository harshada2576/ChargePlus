"""ChargePlus — Phase 5 ML Inference.

Phase: 5/6 (Data Mining, Forecasting & Recommendations)
Step: 5.6 (Inference & Application Integration)

Serves busy-probability predictions from the registry-approved model.
Fail-closed: without an approved model, fresh features, and a compatible
feature schema, inference returns a typed unavailable result (NO_MODEL,
STALE_FEATURES, FEATURE_SCHEMA_MISMATCH, MODEL_ARTIFACT_INVALID, …) —
never a fabricated prediction.

For every prediction the result carries model version, prediction timestamp,
input data cutoff, and horizon. Predictions are returned, not stored:
predicted values must NEVER be written to tables that represent observed
station activity (see ml.prediction_runs — metadata only).

Station discovery works without ML: callers treat unavailable results as
"no prediction", never as errors.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from backend.ml.gates import (
    DEFAULT_GATE_CONFIG,
    MLGateConfig,
    MLUnavailableReason,
    build_evidence_from_records,
    evaluate_gate,
)
from backend.ml.registry import ModelRegistry, RegistryError
from backend.ml.training import FEATURE_NAMES

logger = logging.getLogger("chargeplus.ml.inference")

# What "current busy probability" means: likelihood the station is busy at the
# requested time point given historical time-of-week patterns. Not a forecast
# of exact queue length, not live telemetry.
PREDICTION_HORIZON = "current"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


@dataclass
class PredictionResult:
    """Typed inference outcome: either a prediction or a safe refusal."""
    success: bool
    probability: Optional[float] = None  # P(busy) in [0, 1] when success
    model_version: Optional[str] = None
    predicted_at: Optional[datetime] = None
    input_cutoff: Optional[datetime] = None  # newest real data behind the features
    horizon: str = PREDICTION_HORIZON
    reason: Optional[MLUnavailableReason] = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "probability": self.probability,
            "model_version": self.model_version,
            "predicted_at": self.predicted_at.isoformat() if self.predicted_at else None,
            "input_cutoff": self.input_cutoff.isoformat() if self.input_cutoff else None,
            "horizon": self.horizon,
            "reason": self.reason.value if self.reason else None,
            "message": self.message,
        }


class InferenceService:
    """Serves predictions from the registry-approved model.

    Usage:
        service = InferenceService(ModelRegistry("backend/ml/artifacts"))
        result = service.predict(
            {"hour_of_day": 18, "day_of_week": 4, "is_weekend": 0,
             "month": 10, "station_connector_count": 4},
            latest_observation_at=datetime.now(timezone.utc),
        )
    """

    def __init__(
        self,
        registry: ModelRegistry,
        gate_config: MLGateConfig = DEFAULT_GATE_CONFIG,
    ) -> None:
        self._registry = registry
        self._gate_config = gate_config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict(
        self,
        features: dict[str, Any],
        *,
        latest_observation_at: Optional[datetime] = None,
        as_of: Optional[datetime] = None,
    ) -> PredictionResult:
        """Predicts P(busy) for one station-time feature vector."""
        as_of = as_of or _utcnow()

        # 1. An approved model must exist.
        active = self._registry.get_active()
        if active is None:
            return PredictionResult(
                success=False,
                reason=MLUnavailableReason.NO_MODEL,
                message=(
                    "No approved model available. Predictions are disabled until a "
                    "model is trained on sufficient real observations and approved. "
                    "Station discovery is unaffected."
                ),
            )
        model_version = str(active.get("model_version"))

        # 2. Feature freshness must be verifiable and within bounds.
        cutoff = self._coerce_cutoff(latest_observation_at)
        if cutoff is None:
            return PredictionResult(
                success=False,
                reason=MLUnavailableReason.STALE_FEATURES,
                message=(
                    "Feature freshness cannot be verified (no observation timestamp "
                    "supplied). Refusing to predict on unknown data age."
                ),
            )
        age_hours = (as_of - cutoff).total_seconds() / 3600.0
        if age_hours < 0:
            return PredictionResult(
                success=False,
                reason=MLUnavailableReason.STALE_FEATURES,
                message="Observation timestamp is in the future; refusing to predict.",
            )
        if age_hours > self._gate_config.max_feature_staleness_hours:
            return PredictionResult(
                success=False,
                reason=MLUnavailableReason.STALE_FEATURES,
                message=(
                    f"Features are stale: newest observation is {age_hours:.1f}h old "
                    f"(max {self._gate_config.max_feature_staleness_hours}h). "
                    "Ingest fresh observations before requesting predictions."
                ),
            )

        # 3. Input feature schema must match the locked training schema.
        vector, schema_error = self._build_vector(features)
        if schema_error is not None:
            return PredictionResult(success=False, reason=MLUnavailableReason.FEATURE_SCHEMA_MISMATCH, message=schema_error)

        # 4. Load the verified bundle (checksum + containment enforced inside).
        try:
            bundle = self._registry.load_model_bundle(model_version)
        except RegistryError as exc:
            return PredictionResult(
                success=False,
                reason=MLUnavailableReason.MODEL_ARTIFACT_INVALID,
                message=f"Approved model failed verification at load time: {exc}",
            )

        # 5. Impute missing numerics exactly as training did (stored medians).
        medians = bundle.get("col_medians") or []
        row = self._impute(vector, medians)

        # 6. Score and validate the numeric output.
        try:
            probability = self._score(bundle.get("model"), row)
        except Exception as exc:
            return PredictionResult(
                success=False,
                reason=MLUnavailableReason.MODEL_ARTIFACT_INVALID,
                message=f"Model scoring failed: {exc}",
            )
        if probability is None or not math.isfinite(probability):
            return PredictionResult(
                success=False,
                reason=MLUnavailableReason.MODEL_ARTIFACT_INVALID,
                message="Model emitted a non-finite prediction (NaN/inf); refusing to serve it.",
            )
        if not -1e-9 <= probability <= 1.0 + 1e-9:
            return PredictionResult(
                success=False,
                reason=MLUnavailableReason.MODEL_ARTIFACT_INVALID,
                message=f"Model emitted out-of-range probability {probability}; refusing to serve it.",
            )
        probability = min(1.0, max(0.0, probability))

        logger.info("Inference served: model=%s p(busy)=%.3f", model_version, probability)
        return PredictionResult(
            success=True,
            probability=probability,
            model_version=model_version,
            predicted_at=as_of,
            input_cutoff=cutoff,
        )

    def status(
        self,
        observations: list[dict[str, Any]],
        *,
        as_of: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Reports gate state + active model for status surfaces and APIs."""
        as_of = as_of or _utcnow()
        evidence = build_evidence_from_records(observations, as_of=as_of)
        gate = evaluate_gate(evidence, config=self._gate_config, as_of=as_of)
        active = self._registry.get_active()
        available = gate.passed and active is not None
        if not gate.passed:
            reason = gate.unavailable_reason
        elif active is None:
            reason = MLUnavailableReason.NO_MODEL
        else:
            reason = None
        return {
            "gate": gate.to_dict(),
            "active_model": (
                {
                    "model_version": active.get("model_version"),
                    "model_id": active.get("model_id"),
                    "feature_schema_version": active.get("feature_schema_version"),
                    "training_completed_at": active.get("training_completed_at"),
                    "model_mae": active.get("model_mae"),
                    "baseline_mae": active.get("baseline_mae"),
                    "model_beats_baseline": active.get("model_beats_baseline"),
                    "approved_at": active.get("approved_at"),
                    "approved_by": active.get("approved_by"),
                }
                if active
                else None
            ),
            "inference_available": available,
            "reason": reason.value if reason else None,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_cutoff(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            ts = value
        elif isinstance(value, str):
            try:
                ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    @staticmethod
    def _build_vector(features: dict[str, Any]) -> tuple[Optional[list[Optional[float]]], Optional[str]]:
        """Validates the locked feature schema. Returns (vector, error)."""
        if not isinstance(features, dict):
            return None, "Features must be an object with the locked feature fields."
        vector: list[Optional[float]] = []
        for name in FEATURE_NAMES:
            raw = features.get(name, None)
            value = _as_float(raw)
            if value is None:
                if name == "station_connector_count" and raw is None:
                    vector.append(None)  # missing count → training-median imputation
                    continue
                return None, (
                    f"Feature {name!r} is missing or not numeric. "
                    f"Required schema: {FEATURE_NAMES}"
                )
            if name == "hour_of_day" and not (0 <= value <= 23):
                return None, "hour_of_day must be in [0, 23]"
            if name == "day_of_week" and not (0 <= value <= 6):
                return None, "day_of_week must be in [0, 6]"
            if name == "is_weekend" and value not in (0.0, 1.0):
                return None, "is_weekend must be 0 or 1"
            if name == "month" and not (1 <= value <= 12):
                return None, "month must be in [1, 12]"
            if name == "station_connector_count" and value < 0:
                return None, "station_connector_count must be >= 0"
            vector.append(value)
        return vector, None

    @staticmethod
    def _impute(vector: list[Optional[float]], medians: list[Any]) -> list[float]:
        """Fills None entries with the training column medians (documented)."""
        row: list[float] = []
        for idx, value in enumerate(vector):
            if value is None or (isinstance(value, float) and math.isnan(value)):
                try:
                    fill = float(medians[idx])
                except (IndexError, TypeError, ValueError):
                    fill = 0.0
                if not math.isfinite(fill):
                    fill = 0.0
                row.append(fill)
            else:
                row.append(value)
        return row

    @staticmethod
    def _score(model: Any, row: list[float]) -> Optional[float]:
        """Scores one row. Prefers predict_proba (calibrated-ish 0..1)."""
        if model is None:
            raise ValueError("Model bundle has no model object")
        try:
            import numpy as np

            X = np.array([row], dtype=float)
        except ImportError as exc:
            raise RuntimeError("numpy is required for inference") from exc
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X)
            return float(proba[0][1] if len(proba.shape) > 1 and proba.shape[1] > 1 else proba[0])
        return float(model.predict(X)[0])
