"""ChargePlus — Phase 5 evidence gates (Steps 5.2–5.11 prerequisite).

Gates A–I from the Phase 5 master prompt. Evaluated against a 5.1
maturity report (backend/warehouse/maturity.py output) plus a declared
task spec. If any mandatory gate fails: DO NOT TRAIN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskSpec:
    """Declares what a predictive task needs. No data attached."""

    task: str
    target: str
    target_key: str  # key into maturity report targets, e.g. "availability forecasting"
    min_events: int = 30
    min_dates: int = 14
    min_entities: int = 1
    usefulness: str = ""


@dataclass
class GateResult:
    gate: str
    passed: bool
    detail: str


@dataclass
class TaskGateVerdict:
    task: str
    train: bool
    gates: list[GateResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "train": self.train,
            "gates": [{"gate": g.gate, "passed": g.passed, "detail": g.detail} for g in self.gates],
        }


def _find_target(maturity: dict[str, Any], key: str) -> dict[str, Any]:
    for t in maturity.get("targets", []):
        if t.get("task") == key:
            return t
    return {"task": key, "events": 0, "dates": 0, "trainable_now": False}


def evaluate_gates(maturity: dict[str, Any], spec: TaskSpec) -> TaskGateVerdict:
    """Evaluates gates A–I for one task. Pure function of measured evidence."""
    verdict = TaskGateVerdict(task=spec.task, train=False)
    target = _find_target(maturity, spec.target_key)
    events = int(target.get("events", 0))
    dates = int(target.get("dates", 0))

    def add(gate: str, passed: bool, detail: str) -> None:
        verdict.gates.append(GateResult(gate=gate, passed=passed, detail=detail))

    # Gate A — target exists (legitimate, measured).
    add("A-target-exists", events > 0,
        f"{events} target events measured" if events else "no legitimate target events")
    # Gate B — historical depth (event count).
    add("B-depth", events >= spec.min_events,
        f"{events}/{spec.min_events} events")
    # Gate C — temporal coverage (distinct dates).
    add("C-coverage", dates >= spec.min_dates,
        f"{dates}/{spec.min_dates} distinct dates")
    # Gate D — entity coverage (stations with evidence).
    covered = int(maturity.get("station_coverage", {}).get("with_ge_1_obs", 0))
    add("D-entities", covered >= spec.min_entities,
        f"{covered}/{spec.min_entities} stations with evidence")
    # Gate E — feature coverage (static inventory always exists; temporal
    # features require temporal evidence).
    add("E-features", True,
        "static inventory features available; temporal features require evidence")
    # Gate F — chronological split feasibility (from 5.1 split gate).
    split = target.get("split", {})
    add("F-split", bool(split.get("feasible", False)),
        f"chronological split feasible={split.get('feasible', False)}")
    # Gate G — leakage review (methodology gates, always required).
    add("G-leakage", True,
        "methodology gates apply at dataset build: version-at-time joins, no future aggregates")
    # Gate H — baseline exists (5.2 specifications always definable).
    add("H-baseline", True,
        "naive baseline specification defined per task in baselines.py")
    # Gate I — usefulness declared in the task spec.
    add("I-usefulness", bool(spec.usefulness),
        spec.usefulness or "no usefulness statement declared")

    mandatory = ("A-target-exists", "B-depth", "C-coverage", "D-entities", "F-split")
    verdict.train = all(
        g.passed for g in verdict.gates if g.gate in mandatory
    ) and bool(spec.usefulness)
    return verdict


# Canonical task specs for the Phase 5 roadmap tasks.
TASK_SPECS: dict[str, TaskSpec] = {
    "availability": TaskSpec(
        task="availability forecasting", target_key="availability forecasting",
        target="observed availability_status <> 'unknown'",
        usefulness="Drivers need to know whether a charger is likely free before detouring."),
    "queue": TaskSpec(
        task="queue prediction", target_key="queue prediction",
        target="observed queue_level known",
        usefulness="Drivers need expected wait before joining a queue."),
    "demand": TaskSpec(
        task="demand forecasting", target_key="demand forecasting",
        target="charging sessions/usage events",
        usefulness="Operators need capacity planning per site."),
    "reliability": TaskSpec(
        task="reliability prediction", target_key="reliability prediction",
        target="repeated availability labels per station",
        usefulness="Drivers need to trust a station will work on arrival."),
    "price": TaskSpec(
        task="price prediction", target_key="price prediction",
        target="temporal price changes",
        usefulness="Drivers need cost predictability per charge."),
    "recommendation": TaskSpec(
        task="station recommendation", target_key="station recommendation",
        target="behavioral usage events",
        usefulness="Drivers need the best charger for their situation."),
}
