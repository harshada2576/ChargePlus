"""Agent 4 — offline unit checks for the pure ML library modules.

Covers backend/ml/{features, baselines, datasets, forecasting, anomaly}:
deterministic, stdlib-only logic with no DB, no network, no artifacts.
All fixtures are explicitly SYNTHETIC and inline; nothing here counts
toward production data maturity.

Supervised training/inference/registry/gates are covered by
tests/test_phase5.py; DBSCAN coverage gaps by test_spatial_clustering.py;
the synthetic demand-mining demo by test_demand_mining.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.ml import anomaly, baselines, datasets, features, forecasting

SYNTHETIC_TAG = "SYNTHETIC inline fixture — not real-world evidence"


def _aware(days_ago: float = 0.0, hour: int = 12) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


# ---------------------------------------------------------------------------
# features.py — Milestone B (feature pipeline)
# ---------------------------------------------------------------------------


def test_static_features_unknowns_stay_none():
    out = features.static_features({"latitude": 19.0, "longitude": 72.0}, [])
    assert out["connector_count"] is None
    assert out["max_power_kw"] is None
    assert out["has_known_power"] is False  # never silently zero-filled


def test_static_features_aggregates_known_values():
    out = features.static_features(
        {"latitude": 19.0, "longitude": 72.0, "operator_name": "Op",
         "is_24_hours": True},
        [{"power_kw": 60.0, "quantity": 2}, {"power_kw": None, "quantity": None}],
    )
    assert out["connector_count"] == 2
    assert out["max_power_kw"] == 60.0
    assert out["has_known_power"] is True


def test_temporal_features_empty_history_yields_nones():
    at = _aware()
    out = features.temporal_features([], at)
    assert out["recent_availability"] is None
    assert out["obs_count_7d"] is None
    assert out["hour_of_day"] == at.hour  # wall-clock of T only, never fabricated


def test_temporal_features_uses_only_events_at_or_before_t():
    at = _aware()
    events = [
        {"ts": at - timedelta(days=1), "availability_status": "available"},
        {"ts": at - timedelta(hours=1), "availability_status": "busy"},
        {"ts": at + timedelta(hours=1), "availability_status": "available"},  # future: ignored
    ]
    out = features.temporal_features(events, at)
    assert out["recent_availability"] == "busy"
    assert out["obs_count_7d"] == 2


def test_temporal_features_rejects_naive_t():
    with pytest.raises(ValueError):
        features.temporal_features([], datetime(2026, 1, 1))


def test_resolve_version_at_scd2_point_in_time():
    t0, t1 = _aware(days_ago=10), _aware(days_ago=5)
    versions = [
        {"station_key": "a", "effective_from": t0, "effective_to": t1},
        {"station_key": "b", "effective_from": t1, "effective_to": None},
    ]
    assert features.resolve_version_at(versions, t0)["station_key"] == "a"
    assert features.resolve_version_at(versions, _aware())["station_key"] == "b"
    with pytest.raises(ValueError):
        features.resolve_version_at(versions, datetime(2026, 1, 1))


def test_mean_imputer_unfitted_never_fills():
    imputer = features.MeanImputer()
    assert imputer.transform({"power_kw": None}) == {"power_kw": None}


def test_mean_imputer_fit_train_only_then_transform():
    imputer = features.MeanImputer().fit([{"p": 10.0}, {"p": 20.0}, {"p": None}], ["p"])
    assert imputer.transform({"p": None}) == {"p": 15.0}
    assert imputer.transform({"p": 5.0}) == {"p": 5.0}  # observed values untouched


# ---------------------------------------------------------------------------
# baselines.py — Milestone B (deterministic baselines) + E (comparison honesty)
# ---------------------------------------------------------------------------


def test_metric_functions_return_none_not_fake_numbers():
    assert baselines.accuracy([], []) is None
    assert baselines.accuracy([1], [1, 2]) is None  # length mismatch
    assert baselines.mae([1.0], [1.0, 2.0]) is None
    assert baselines.mape([0.0, 1.0], [0.0, 1.0]) is None  # zero actual: undefined
    assert baselines.accuracy(["a", "b"], ["a", "b"]) == 1.0
    assert baselines.mae([1.0, 2.0], [1.0, 2.0]) == 0.0


def test_macro_f1_and_rmse_sanity():
    assert baselines.macro_f1(["a", "b"], ["a", "b"]) == pytest.approx(1.0)
    assert baselines.rmse([0.0, 2.0], [0.0, 0.0]) == pytest.approx(2.0 ** 0.5)


def test_majority_baseline_deterministic_tie_break():
    base = baselines.MajorityBaseline().fit(["b", "a"])  # tie -> first seen
    assert base.label == "b"
    assert base.predict(2) == ["b", "b"]
    with pytest.raises(ValueError):
        baselines.MajorityBaseline().fit([])
    with pytest.raises(ValueError):
        baselines.MajorityBaseline().predict(1)


def test_median_and_last_known_baselines():
    assert baselines.MedianBaseline().fit([1.0, 2.0, 100.0]).predict(1) == [2.0]
    assert baselines.LastKnownBaseline().fit(["x", "y"]).predict(2) == ["y", "y"]
    with pytest.raises(ValueError):
        baselines.MedianBaseline().fit([])


def test_chronological_split_never_shuffles():
    train, valid, test = baselines.chronological_split(list(range(10)))
    assert (train, valid, test) == (list(range(6)), [6, 7], [8, 9])
    assert baselines.chronological_split([]) == ([], [], [])


def test_compare_against_baseline_honesty():
    assert baselines.compare_against_baseline(0.2, 0.5)["beats_baseline"] is True
    assert baselines.compare_against_baseline(0.8, 0.5)["beats_baseline"] is False
    undetermined = baselines.compare_against_baseline(None, 0.5)
    assert undetermined["beats_baseline"] is None  # missing metric: never a win claim


# ---------------------------------------------------------------------------
# datasets.py — Milestone B (gated dataset construction)
# ---------------------------------------------------------------------------


def _opportunity(day_offset: int, target) -> dict:
    return {
        "ts": _aware(days_ago=day_offset),
        "features": {"hour_of_day": 12},
        "target": target,
        "provenance": {"_synthetic": True},
    }


def test_build_dataset_blocked_without_enough_real_events():
    spec = datasets.DatasetSpec(name="t", version="v1", grain="station-hour",
                                target="is_busy")
    artifact = datasets.build_dataset(spec, [_opportunity(0, 1)])
    assert artifact.blocked is True
    assert artifact.rows == []
    assert "BLOCKED" in (artifact.blocked_reason or "")
    assert datasets.dataset_summary(artifact)["blocked"] is True


def test_build_dataset_none_targets_produce_no_rows():
    spec = datasets.DatasetSpec(name="t", version="v1", grain="station-hour",
                                target="is_busy")
    artifact = datasets.build_dataset(spec, [_opportunity(0, None)])
    assert artifact.blocked is True and artifact.rows == []


def test_build_dataset_rejects_naive_timestamps():
    spec = datasets.DatasetSpec(name="t", version="v1", grain="station-hour",
                                target="is_busy")
    bad = {"ts": datetime(2026, 1, 1), "features": {}, "target": 1,
           "provenance": {}}
    with pytest.raises(ValueError):
        datasets.build_dataset(spec, [bad] * 40)


def test_build_dataset_splits_chronologically_when_sufficient():
    spec = datasets.DatasetSpec(name="t", version="v1", grain="station-hour",
                                target="is_busy")
    opps = [_opportunity(d, d % 2) for d in range(30, 0, -1)]  # 30 events, 30 dates
    artifact = datasets.build_dataset(spec, opps)
    assert artifact.blocked is False
    assert (len(artifact.train_rows), len(artifact.valid_rows),
            len(artifact.test_rows)) == (18, 6, 6)
    assert artifact.train_rows[-1]["ts"] <= artifact.valid_rows[0]["ts"]
    assert artifact.valid_rows[-1]["ts"] <= artifact.test_rows[0]["ts"]


# ---------------------------------------------------------------------------
# forecasting.py — Milestone E (forecast contract; naive forecaster only)
# ---------------------------------------------------------------------------


def test_seasonal_naive_repeats_last_season():
    assert forecasting.seasonal_naive([1.0, 2.0, 3.0], seasonality=2, steps=3) == [2.0, 3.0, 2.0]


def test_seasonal_naive_refuses_without_history():
    assert forecasting.seasonal_naive([1.0], seasonality=2, steps=1) is None
    assert forecasting.seasonal_naive([1.0, 2.0], seasonality=0, steps=1) is None
    assert forecasting.seasonal_naive([1.0, 2.0], seasonality=1, steps=0) is None


def test_forecast_window_splits_history_and_target():
    cutoff = _aware()
    events = [{"ts": cutoff - timedelta(hours=1)}, {"ts": cutoff + timedelta(hours=1)}]
    history, (start, end) = forecasting.forecast_window(
        events, cutoff, timedelta(hours=2))
    assert len(history) == 1 and (start, end) == (cutoff, cutoff + timedelta(hours=2))
    with pytest.raises(ValueError):
        forecasting.forecast_window(events, datetime(2026, 1, 1), timedelta(hours=1))


# ---------------------------------------------------------------------------
# anomaly.py — Milestone D (deterministic validation first)
# ---------------------------------------------------------------------------


def test_anomaly_detectors_need_reference_distribution():
    assert anomaly.zscore_anomalies([1.0, 2.0]) == []  # <10 points: nothing flaggable
    assert anomaly.iqr_anomalies([1.0] * 5) == []
    assert anomaly.sudden_state_changes(["a", "b"]) == []  # single records never qualify


def test_zscore_flags_extreme_point():
    values = [0.0] * 10 + [100.0]
    hits = anomaly.zscore_anomalies(values)
    assert len(hits) == 1 and hits[0].index == 10 and hits[0].method == "zscore"
    assert anomaly.zscore_anomalies([5.0] * 11) == []  # zero variance: no flags


def test_iqr_flags_extreme_point():
    values = [float(i) for i in range(1, 11)] + [100.0]
    hits = anomaly.iqr_anomalies(values)
    assert any(h.index == 10 and h.method == "iqr" for h in hits)


def test_sudden_state_changes_requires_stable_run():
    states = ["available"] * 10 + ["broken"]
    changes = anomaly.sudden_state_changes(states)
    assert changes == [{"index": 10, "from": "available", "to": "broken",
                        "stable_run": 10}]
    assert anomaly.sudden_state_changes(["a", "b"] * 6) == []  # no stable run
