"""ChargePlus — Baseline methodology (Phase 5/6, Step 5.2).

Baselines are specified BEFORE sophisticated modeling so every future
model has something honest to beat. Specifications are data-independent;
evaluation functions operate on event sequences (fixture-testable).
No baseline value is computed from production until target history exists.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any, Optional, Sequence


# ----------------------------------------------------------------------
# Baseline specifications (per future predictive task)
# ----------------------------------------------------------------------
@dataclass
class BaselineSpec:
    task: str
    target: str
    baseline: str
    required_inputs: list[str] = field(default_factory=list)
    metric: str = ""
    split: str = "chronological 60/20/20 with documented cutoffs"
    min_evidence_gate: str = ""


BASELINE_SPECS: dict[str, BaselineSpec] = {
    "availability": BaselineSpec(
        task="availability forecasting", target="availability_status in {available, busy, broken}",
        baseline="persistence (last-known state); fallback station historical majority, then population majority",
        required_inputs=["ordered availability labels per station"],
        metric="macro-F1 (primary), accuracy reported with class balance",
        min_evidence_gate=">= 30 labels spanning >= 14 distinct dates"),
    "demand": BaselineSpec(
        task="demand forecasting", target="charging sessions per station-day",
        baseline="seasonal naive (same weekday, trailing 4 weeks); fallback trailing mean",
        required_inputs=["session counts per station-day"],
        metric="MAE (primary), RMSE; MAPE only if target has no zeros",
        min_evidence_gate=">= 8 full weeks of session history"),
    "queue": BaselineSpec(
        task="queue prediction", target="queue_level ordinal",
        baseline="last-known queue; fallback station historical median",
        required_inputs=["ordered queue labels per station"],
        metric="macro-F1 on ordinal buckets; MAE on queue scores as secondary",
        min_evidence_gate=">= 30 labels spanning >= 14 distinct dates"),
    "reliability": BaselineSpec(
        task="reliability prediction", target="P(available | station, time)",
        baseline="station historical available-rate; fallback population rate",
        required_inputs=["repeated availability labels per station"],
        metric="PR-AUC (primary under imbalance), ROC-AUC secondary",
        min_evidence_gate=">= 30 labels spanning >= 14 distinct dates"),
}


# ----------------------------------------------------------------------
# Metric functions (pure; undefined inputs yield None, never fake numbers)
# ----------------------------------------------------------------------
def accuracy(y_true: Sequence, y_pred: Sequence) -> Optional[float]:
    if not y_true or len(y_true) != len(y_pred):
        return None
    return sum(1 for a, b in zip(y_true, y_pred) if a == b) / len(y_true)


def _prf(y_true: Sequence, y_pred: Sequence, label: Any) -> tuple[float, float, float]:
    tp = sum(1 for a, b in zip(y_true, y_pred) if a == label and b == label)
    fp = sum(1 for a, b in zip(y_true, y_pred) if a != label and b == label)
    fn = sum(1 for a, b in zip(y_true, y_pred) if a == label and b != label)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def macro_f1(y_true: Sequence, y_pred: Sequence) -> Optional[float]:
    if not y_true or len(y_true) != len(y_pred):
        return None
    labels = sorted(set(y_true) | set(y_pred))
    return mean([_prf(y_true, y_pred, lab)[2] for lab in labels])


def mae(y_true: Sequence[float], y_pred: Sequence[float]) -> Optional[float]:
    if not y_true or len(y_true) != len(y_pred):
        return None
    return mean([abs(a - b) for a, b in zip(y_true, y_pred)])


def rmse(y_true: Sequence[float], y_pred: Sequence[float]) -> Optional[float]:
    if not y_true or len(y_true) != len(y_pred):
        return None
    return math.sqrt(mean([(a - b) ** 2 for a, b in zip(y_true, y_pred)]))


def median_ae(y_true: Sequence[float], y_pred: Sequence[float]) -> Optional[float]:
    if not y_true or len(y_true) != len(y_pred):
        return None
    return float(median([abs(a - b) for a, b in zip(y_true, y_pred)]))


def mape(y_true: Sequence[float], y_pred: Sequence[float]) -> Optional[float]:
    """Guarded: undefined when any actual is zero (mathematically invalid)."""
    if not y_true or len(y_true) != len(y_pred):
        return None
    if any(a == 0 for a in y_true):
        return None
    return mean([abs((a - b) / a) for a, b in zip(y_true, y_pred)]) * 100.0


def mase(y_true: Sequence[float], y_pred: Sequence[float],
         y_train: Sequence[float], seasonality: int = 1) -> Optional[float]:
    """Mean absolute scaled error vs seasonal-naive in-sample error."""
    if not y_true or len(y_true) != len(y_pred) or len(y_train) <= seasonality:
        return None
    naive_err = mean([abs(y_train[i] - y_train[i - seasonality])
                      for i in range(seasonality, len(y_train))])
    if naive_err == 0:
        return None
    model_err = mean([abs(a - b) for a, b in zip(y_true, y_pred)])
    return model_err / naive_err


# ----------------------------------------------------------------------
# Naive baseline predictors (fit on training split only)
# ----------------------------------------------------------------------
class MajorityBaseline:
    """Classification baseline: most frequent training label (ties -> first seen)."""

    def __init__(self) -> None:
        self.label: Any = None

    def fit(self, y_train: Sequence) -> "MajorityBaseline":
        if not y_train:
            raise ValueError("MajorityBaseline.fit requires non-empty training labels")
        counts = Counter(y_train)
        top = max(counts.values())
        for lab in y_train:  # deterministic tie-break: first seen
            if counts[lab] == top:
                self.label = lab
                break
        return self

    def predict(self, n: int) -> list:
        if self.label is None:
            raise ValueError("MajorityBaseline.predict before fit")
        return [self.label] * n


class MedianBaseline:
    """Regression baseline: training median (robust to outliers)."""

    def __init__(self) -> None:
        self.value: Optional[float] = None

    def fit(self, y_train: Sequence[float]) -> "MedianBaseline":
        if not y_train:
            raise ValueError("MedianBaseline.fit requires non-empty training values")
        self.value = float(median(y_train))
        return self

    def predict(self, n: int) -> list[float]:
        if self.value is None:
            raise ValueError("MedianBaseline.predict before fit")
        return [self.value] * n


class LastKnownBaseline:
    """Persistence baseline: carry the last training observation forward."""

    def __init__(self) -> None:
        self.last: Any = None

    def fit(self, y_train: Sequence) -> "LastKnownBaseline":
        if not y_train:
            raise ValueError("LastKnownBaseline.fit requires non-empty training values")
        self.last = y_train[-1]
        return self

    def predict(self, n: int) -> list:
        if self.last is None:
            raise ValueError("LastKnownBaseline.predict before fit")
        return [self.last] * n


# ----------------------------------------------------------------------
# Temporal splitting + model comparison
# ----------------------------------------------------------------------
def chronological_split(items: Sequence, train_frac: float = 0.6,
                        valid_frac: float = 0.2) -> tuple[list, list, list]:
    """Chronological 60/20/20 split of time-ordered items. No shuffling."""
    n = len(items)
    if n == 0:
        return [], [], []
    i = int(n * train_frac)
    j = int(n * (train_frac + valid_frac))
    return list(items[:i]), list(items[i:j]), list(items[j:])


def compare_against_baseline(model_metric: Optional[float],
                             baseline_metric: Optional[float],
                             higher_is_better: bool = False) -> dict[str, Any]:
    """Honest comparison: missing metrics yield undetermined, never a win claim."""
    if model_metric is None or baseline_metric is None:
        return {"model": model_metric, "baseline": baseline_metric,
                "beats_baseline": None, "delta": None,
                "note": "undetermined: metric unavailable"}
    delta = model_metric - baseline_metric
    beats = delta > 0 if higher_is_better else delta < 0
    return {"model": model_metric, "baseline": baseline_metric,
            "beats_baseline": beats, "delta": delta,
            "note": "beats" if beats else "does not beat"}
