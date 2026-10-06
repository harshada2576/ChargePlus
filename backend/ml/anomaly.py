"""ChargePlus — Anomaly detection primitives (Phase 5/6, Step 5.7).

Anomalies require a reference distribution: a minimum history length is
enforced before any point can be flagged. A single static record is never
an anomaly. All detectors are deterministic and fixture-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Any, Optional, Sequence

# Minimum reference-distribution size before flagging anything.
MIN_REFERENCE_POINTS = 10


@dataclass
class AnomalyResult:
    index: int
    value: float
    score: float
    method: str


def _reference(values: Sequence[float], min_points: int = MIN_REFERENCE_POINTS
               ) -> Optional[list[float]]:
    if len(values) < min_points:
        return None  # insufficient reference: nothing flaggable
    return list(values)


def zscore_anomalies(values: Sequence[float], threshold: float = 3.0,
                     min_points: int = MIN_REFERENCE_POINTS) -> list[AnomalyResult]:
    """Flags points > threshold population-std from the mean (two-sided)."""
    ref = _reference(values, min_points)
    if ref is None:
        return []
    mu, sigma = mean(ref), pstdev(ref)
    if sigma == 0:
        return []
    return [AnomalyResult(i, v, abs(v - mu) / sigma, "zscore")
            for i, v in enumerate(ref) if abs(v - mu) / sigma > threshold]


def iqr_anomalies(values: Sequence[float], k: float = 1.5,
                  min_points: int = MIN_REFERENCE_POINTS) -> list[AnomalyResult]:
    """Tukey fences: outside [Q1 - k*IQR, Q3 + k*IQR]."""
    ref = _reference(values, min_points)
    if ref is None:
        return []
    ordered = sorted(ref)
    n = len(ordered)
    q1 = ordered[n // 4]
    q3 = ordered[(3 * n) // 4]
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    out = []
    for i, v in enumerate(ref):
        if v < lo or v > hi:
            score = (lo - v) / iqr if v < lo and iqr else ((v - hi) / iqr if iqr else 0.0)
            out.append(AnomalyResult(i, v, score, "iqr"))
    return out


def sudden_state_changes(states: Sequence[str], min_points: int = MIN_REFERENCE_POINTS
                         ) -> list[dict[str, Any]]:
    """Flags transitions preceded by a stable run (reference distribution =
    the stable run itself). Single records never qualify."""
    if len(states) < min_points + 1:
        return []
    changes = []
    run_value, run_len = states[0], 1
    for i in range(1, len(states)):
        if states[i] == run_value:
            run_len += 1
        else:
            if run_len >= min_points:
                changes.append({"index": i, "from": run_value, "to": states[i],
                                "stable_run": run_len})
            run_value, run_len = states[i], 1
    return changes
