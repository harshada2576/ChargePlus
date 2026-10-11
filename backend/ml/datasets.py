"""ChargePlus — Gated training-dataset construction (Phase 5/6, Step 5.4).

A training row exists ONLY for a real prediction opportunity backed by a
real target event. No events -> no rows (with an explicit reason), never
placeholder rows. Chronological splits; full provenance recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from backend.ml.baselines import chronological_split


@dataclass
class DatasetSpec:
    name: str
    version: str
    grain: str
    target: str
    feature_names: list[str] = field(default_factory=list)
    min_events: int = 30
    min_dates: int = 14


@dataclass
class DatasetArtifact:
    name: str
    version: str
    grain: str
    rows: list[dict[str, Any]]
    train_rows: list[dict[str, Any]]
    valid_rows: list[dict[str, Any]]
    test_rows: list[dict[str, Any]]
    provenance: dict[str, Any]
    blocked_reason: Optional[str] = None

    @property
    def blocked(self) -> bool:
        return self.blocked_reason is not None


def build_dataset(
    spec: DatasetSpec,
    opportunities: list[dict[str, Any]],
    code_version: str = "uncommitted",
) -> DatasetArtifact:
    """Builds a dataset from real prediction opportunities.

    Each opportunity must carry {"ts": aware datetime, "features": {...},
    "target": value-or-None, "provenance": {...}}. Opportunities with a
    None target produce NO row. Fewer events than the gate -> blocked
    artifact with zero rows (never fabricated).
    """
    events = [o for o in opportunities if o.get("target") is not None]
    for o in events:
        ts = o.get("ts")
        if not isinstance(ts, datetime) or ts.tzinfo is None:
            raise ValueError("opportunity timestamps must be timezone-aware datetimes")
    dates = {o["ts"].astimezone(timezone.utc).date().isoformat() for o in events}
    if len(events) < spec.min_events or len(dates) < spec.min_dates:
        return DatasetArtifact(
            name=spec.name, version=spec.version, grain=spec.grain,
            rows=[], train_rows=[], valid_rows=[], test_rows=[],
            provenance={"spec": spec.__dict__, "events_seen": len(events),
                        "dates_seen": len(dates), "code_version": code_version},
            blocked_reason=(
                f"BLOCKED ON DATA MATURITY: {len(events)}/{spec.min_events} events, "
                f"{len(dates)}/{spec.min_dates} dates"),
        )
    ordered = sorted(events, key=lambda o: o["ts"])
    train, valid, test = chronological_split(ordered)
    return DatasetArtifact(
        name=spec.name, version=spec.version, grain=spec.grain,
        rows=ordered, train_rows=train, valid_rows=valid, test_rows=test,
        provenance={"spec": spec.__dict__, "events_seen": len(events),
                    "dates_seen": sorted(dates), "code_version": code_version,
                    "split": "chronological 60/20/20"},
    )


def dataset_summary(artifact: DatasetArtifact) -> dict[str, Any]:
    return {
        "name": artifact.name, "version": artifact.version,
        "blocked": artifact.blocked, "blocked_reason": artifact.blocked_reason,
        "rows": len(artifact.rows), "train": len(artifact.train_rows),
        "valid": len(artifact.valid_rows), "test": len(artifact.test_rows),
        "provenance": artifact.provenance,
    }
