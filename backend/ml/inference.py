"""ChargePlus — Product inference contracts (Phase 5/6, Step 5.10).

Predictions are unavailable until a validated model exists. This module
defines the ONLY shape predictions may take when they arrive, plus the
explicit unavailability states used today. Unavailable NEVER becomes 0,
and prediction-unavailable NEVER becomes station-unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Valid prediction states. Only VALUE carries a prediction.
STATUS_VALUE = "VALUE"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUS_STALE = "STALE"
STATUS_NO_MODEL = "NO_MODEL"


@dataclass(frozen=True)
class Prediction:
    kind: str  # e.g. "availability", "queue", "demand"
    station_id: str
    status: str
    value: Optional[Any] = None
    explanation: tuple = ()
    model_version: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status == STATUS_VALUE and self.value is None:
            raise ValueError("VALUE predictions must carry a value")
        if self.status != STATUS_VALUE and self.value is not None:
            raise ValueError("non-VALUE predictions must not carry a value")


def unavailable(kind: str, station_id: str, reason: str = STATUS_NO_MODEL) -> Prediction:
    """The honest answer while no validated model exists."""
    if reason not in (STATUS_NOT_AVAILABLE, STATUS_INSUFFICIENT_DATA, STATUS_STALE, STATUS_NO_MODEL):
        raise ValueError(f"unknown prediction status '{reason}'")
    return Prediction(kind=kind, station_id=str(station_id), status=reason,
                      explanation=("No validated model serves this prediction yet.",))


def resolve_availability(station_id: str, model: Optional[Any] = None) -> Prediction:
    """Availability prediction entry point. No model -> NO_MODEL (never a guess)."""
    if model is None:
        return unavailable("availability", station_id, STATUS_NO_MODEL)
    raise NotImplementedError("model-backed inference unlocks with the first validated model")


def resolve_queue(station_id: str, model: Optional[Any] = None) -> Prediction:
    if model is None:
        return unavailable("queue", station_id, STATUS_NO_MODEL)
    raise NotImplementedError("model-backed inference unlocks with the first validated model")


def to_product_claim(pred: Prediction) -> dict[str, Any]:
    """Maps a Prediction to product-safe language. Never invents certainty."""
    if pred.status != STATUS_VALUE:
        return {"state": "unknown", "detail": "Prediction unavailable",
                "reasons": list(pred.explanation)}
    return {"state": pred.value, "detail": "Model prediction",
            "reasons": list(pred.explanation),
            "model_version": pred.model_version}
