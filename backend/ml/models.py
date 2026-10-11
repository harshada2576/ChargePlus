"""ChargePlus — Gated model training & evaluation (Phase 5/6, Step 5.5).

Training is refused unless evidence gates pass (DO NOT TRAIN otherwise).
Available now: leakage-safe evaluation harness + baseline comparison on
any dataset artifact. Simple models first (majority/median fitting);
no heavyweight dependencies introduced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from backend.ml.baselines import (
    MajorityBaseline,
    MedianBaseline,
    accuracy,
    compare_against_baseline,
    macro_f1,
    mae,
    rmse,
)
from backend.ml.datasets import DatasetArtifact
from backend.ml.gates import TASK_SPECS, TaskGateVerdict, evaluate_gates


@dataclass
class TrainingRequest:
    task_key: str  # key into TASK_SPECS
    dataset: DatasetArtifact
    model_name: str
    maturity: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrainingOutcome:
    trained: bool
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)
    baseline_comparison: dict[str, Any] = field(default_factory=dict)


def train_gated(request: TrainingRequest,
                fit: Optional[Callable[[list], Callable[[int], list]]] = None
                ) -> TrainingOutcome:
    """Trains only if gates pass AND the dataset is unblocked.

    fit: optional trainer mapping train targets -> predict(n) callable.
    Default fits a majority (classification) / median (numeric) simple model.
    """
    spec = TASK_SPECS.get(request.task_key)
    if spec is None:
        return TrainingOutcome(trained=False, reason=f"unknown task '{request.task_key}'")
    verdict: TaskGateVerdict = evaluate_gates(request.maturity, spec)
    if not verdict.train:
        failed = [g.gate for g in verdict.gates if g.passed is False
                  and g.gate in ("A-target-exists", "B-depth", "C-coverage",
                                 "D-entities", "F-split")]
        return TrainingOutcome(
            trained=False,
            reason=f"BLOCKED ON DATA MATURITY: gates failed: {failed or 'usefulness'}")
    if request.dataset.blocked:
        return TrainingOutcome(trained=False, reason=request.dataset.blocked_reason or "blocked dataset")
    train_targets = [r["target"] for r in request.dataset.train_rows]
    if fit is None:
        numeric = all(isinstance(t, (int, float)) for t in train_targets)
        model = MedianBaseline().fit(train_targets) if numeric else MajorityBaseline().fit(train_targets)
        predict = model.predict
    else:
        predict = fit(train_targets)

    results: dict[str, Any] = {}
    for split_name, rows in (("train", request.dataset.train_rows),
                             ("valid", request.dataset.valid_rows),
                             ("test", request.dataset.test_rows)):
        y_true = [r["target"] for r in rows]
        y_pred = predict(len(y_true))
        numeric = all(isinstance(t, (int, float)) for t in y_true)
        if numeric:
            results[split_name] = {"mae": mae(y_true, y_pred), "rmse": rmse(y_true, y_pred)}
        else:
            results[split_name] = {"accuracy": accuracy(y_true, y_pred),
                                   "macro_f1": macro_f1(y_true, y_pred)}
    # Baseline for comparison: last-known on train, evaluated on test.
    from backend.ml.baselines import LastKnownBaseline
    base = LastKnownBaseline().fit(train_targets)
    base_pred = base.predict(len(request.dataset.test_rows))
    y_test = [r["target"] for r in request.dataset.test_rows]
    numeric = all(isinstance(t, (int, float)) for t in y_test)
    if numeric:
        comparison = compare_against_baseline(results["test"]["mae"], mae(y_test, base_pred))
    else:
        comparison = compare_against_baseline(results["test"]["macro_f1"],
                                             macro_f1(y_test, base_pred),
                                             higher_is_better=True)
    return TrainingOutcome(trained=True, reason="gates passed; simple model fitted",
                           metrics=results, baseline_comparison=comparison)
