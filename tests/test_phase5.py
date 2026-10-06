"""ChargePlus — Phase 5 methodology tests (Steps 5.2–5.10).

All data is in-file fixtures. Nothing here touches production.
Proves: gates refuse without evidence, baselines/metrics are correct,
features preserve unknowns, datasets never fabricate rows, training is
gated, anomaly detectors need history, recommendations don't punish
missing data, registry respects vocab, inference never fakes predictions.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

DAY = timedelta(days=1)
T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def empty_maturity() -> dict:
    return {
        "targets": [
            {"task": t, "events": 0, "dates": 0, "trainable_now": False,
             "split": {"feasible": False}}
            for t in ("availability forecasting", "queue prediction",
                      "demand forecasting", "reliability prediction",
                      "price prediction", "station recommendation")
        ],
        "station_coverage": {"with_ge_1_obs": 0},
    }


def rich_maturity() -> dict:
    return {
        "targets": [
            {"task": "availability forecasting", "events": 40, "dates": 20,
             "trainable_now": True, "split": {"feasible": True}},
            {"task": "queue prediction", "events": 0, "dates": 0,
             "trainable_now": False, "split": {"feasible": False}},
            {"task": "demand forecasting", "events": 0, "dates": 0,
             "trainable_now": False, "split": {"feasible": False}},
            {"task": "reliability prediction", "events": 40, "dates": 20,
             "trainable_now": True, "split": {"feasible": False}},
            {"task": "price prediction", "events": 0, "dates": 0,
             "trainable_now": False, "split": {"feasible": False}},
            {"task": "station recommendation", "events": 0, "dates": 0,
             "trainable_now": False, "split": {"feasible": False}},
        ],
        "station_coverage": {"with_ge_1_obs": 3},
    }


class TestGates(unittest.TestCase):
    def test_01_empty_evidence_refuses_all_tasks(self):
        from backend.ml.gates import TASK_SPECS, evaluate_gates
        for key, spec in TASK_SPECS.items():
            verdict = evaluate_gates(empty_maturity(), spec)
            self.assertFalse(verdict.train, key)
            self.assertTrue(any(not g.passed for g in verdict.gates), key)

    def test_02_rich_evidence_passes_mandatory_gates(self):
        from backend.ml.gates import TASK_SPECS, evaluate_gates
        verdict = evaluate_gates(rich_maturity(), TASK_SPECS["availability"])
        self.assertTrue(verdict.train)
        verdict_q = evaluate_gates(rich_maturity(), TASK_SPECS["queue"])
        self.assertFalse(verdict_q.train)

    def test_03_usefulness_required(self):
        from backend.ml.gates import TaskSpec, evaluate_gates
        spec = TaskSpec(task="x", target_key="availability forecasting",
                        target="t", min_events=1, min_dates=1, usefulness="")
        m = rich_maturity()
        self.assertFalse(evaluate_gates(m, spec).train)


class TestBaselines(unittest.TestCase):
    def test_04_specs_cover_roadmap_tasks(self):
        from backend.ml.baselines import BASELINE_SPECS
        for task in ("availability", "demand", "queue", "reliability"):
            spec = BASELINE_SPECS[task]
            self.assertTrue(spec.target and spec.baseline and spec.metric)

    def test_05_metrics_correct_and_guarded(self):
        from backend.ml.baselines import accuracy, macro_f1, mae, mape, mase, median_ae, rmse
        self.assertEqual(accuracy(["a", "b", "a"], ["a", "a", "a"]), 2 / 3)
        self.assertIsNone(accuracy([], []))
        self.assertIsNone(accuracy(["a"], ["a", "b"]))
        self.assertAlmostEqual(macro_f1(["a", "b"], ["a", "a"]), (2 / 3 + 0) / 2)
        self.assertEqual(mae([1.0, 2.0], [1.5, 2.5]), 0.5)
        self.assertAlmostEqual(rmse([0.0, 2.0], [0.0, 0.0]), 2 ** 0.5)
        self.assertEqual(median_ae([1.0, 2.0, 9.0], [1.0, 2.0, 2.0]), 0.0)
        self.assertIsNone(mape([0.0, 1.0], [0.0, 1.0]))  # zeros: mathematically invalid
        self.assertAlmostEqual(mape([100.0], [110.0]), 10.0)
        self.assertIsNone(mase([1.0], [1.0], [1.0]))  # too short for seasonality
        self.assertAlmostEqual(mase([3.0, 3.0], [3.0, 3.0], [1.0, 2.0, 3.0, 4.0]), 0.0)

    def test_06_naive_predictors_fit_predict(self):
        from backend.ml.baselines import LastKnownBaseline, MajorityBaseline, MedianBaseline
        self.assertEqual(MajorityBaseline().fit(["b", "a", "b"]).predict(2), ["b", "b"])
        self.assertEqual(MedianBaseline().fit([1.0, 2.0, 9.0]).predict(1), [2.0])
        self.assertEqual(LastKnownBaseline().fit([1, 2, 3]).predict(2), [3, 3])
        with self.assertRaises(ValueError):
            MajorityBaseline().fit([])
        with self.assertRaises(ValueError):
            MajorityBaseline().predict(1)

    def test_07_chronological_split_and_comparison(self):
        from backend.ml.baselines import chronological_split, compare_against_baseline
        tr, va, te = chronological_split(list(range(10)))
        self.assertEqual((tr, va, te), (list(range(6)), [6, 7], [8, 9]))
        self.assertEqual(chronological_split([]), ([], [], []))
        c = compare_against_baseline(0.5, 0.8)
        self.assertTrue(c["beats_baseline"])
        c2 = compare_against_baseline(None, 0.8)
        self.assertIsNone(c2["beats_baseline"])


class TestFeatures(unittest.TestCase):
    def test_08_static_unknowns_stay_none(self):
        from backend.ml.features import static_features
        f = static_features({"latitude": 19.0, "longitude": None, "operator_name": "Unknown Operator"},
                            [{"power_kw": None, "quantity": None}])
        self.assertIsNone(f["max_power_kw"])
        self.assertIsNone(f["connector_count"])
        self.assertFalse(f["has_known_power"])
        self.assertEqual(f["operator_name"], "Unknown Operator")

    def test_09_temporal_empty_history_is_none(self):
        from backend.ml.features import temporal_features
        now = datetime.now(timezone.utc)
        f = temporal_features([], now)
        self.assertIsNone(f["recent_availability"])
        self.assertIsNone(f["obs_count_7d"])
        self.assertEqual(f["hour_of_day"], now.hour)
        with self.assertRaises(ValueError):
            temporal_features([], datetime(2026, 1, 1))

    def test_10_version_at_time_never_current(self):
        from backend.ml.features import resolve_version_at
        v1 = {"station_key": 1, "effective_from": T0, "effective_to": T0 + 10 * DAY}
        v2 = {"station_key": 2, "effective_from": T0 + 10 * DAY, "effective_to": None}
        self.assertEqual(resolve_version_at([v1, v2], T0 + 5 * DAY)["station_key"], 1)
        self.assertEqual(resolve_version_at([v1, v2], T0 + 11 * DAY)["station_key"], 2)
        self.assertIsNone(resolve_version_at([], T0))

    def test_11_imputer_no_silent_fill(self):
        from backend.ml.features import MeanImputer
        imp = MeanImputer()
        row = {"a": None}
        self.assertIsNone(imp.transform(row)["a"])  # unfitted: passthrough
        imp.fit([{"a": 2.0}, {"a": 4.0}], ["a"])
        self.assertEqual(imp.transform({"a": None})["a"], 3.0)
        self.assertIsNone(imp.transform({"b": None}).get("b"))  # unseen field untouched

    def test_12_feature_definitions_match_registry_vocab(self):
        from backend.ml.features import FEATURE_DEFINITIONS
        self.assertTrue(len(FEATURE_DEFINITIONS) >= 8)
        for d in FEATURE_DEFINITIONS:
            self.assertTrue(d.name and d.description)
        with self.assertRaises(ValueError):
            from backend.ml.features import FeatureDefinition
            FeatureDefinition("x", "nope", "general", "d")


class TestDatasets(unittest.TestCase):
    def _spec(self):
        from backend.ml.datasets import DatasetSpec
        return DatasetSpec(name="avail", version="v1",
                           grain="one row = one station prediction opportunity at T",
                           target="availability_status", min_events=30, min_dates=14)

    def test_13_empty_opportunities_blocked_with_reason(self):
        from backend.ml.datasets import build_dataset, dataset_summary
        art = self._spec() and build_dataset(self._spec(), [])
        self.assertTrue(art.blocked)
        self.assertEqual(len(art.rows), 0)
        self.assertIn("BLOCKED ON DATA MATURITY", art.blocked_reason)
        s = dataset_summary(art)
        self.assertTrue(s["blocked"])

    def test_14_none_targets_produce_no_rows(self):
        from backend.ml.datasets import build_dataset
        opps = [{"ts": T0 + i * DAY, "features": {}, "target": None, "provenance": {}} for i in range(40)]
        art = build_dataset(self._spec(), opps)
        self.assertTrue(art.blocked)
        self.assertEqual(len(art.rows), 0)

    def test_15_rich_dataset_splits_chronologically(self):
        from backend.ml.datasets import build_dataset
        opps = [{"ts": T0 + (i % 20) * DAY, "features": {"i": i},
                 "target": "available" if i % 2 == 0 else "busy",
                 "provenance": {"src": "test"}} for i in range(40)]
        art = build_dataset(self._spec(), opps, code_version="test-1")
        self.assertFalse(art.blocked)
        self.assertEqual(len(art.rows), 40)
        self.assertLessEqual(max(r["ts"] for r in art.train_rows),
                             min(r["ts"] for r in art.valid_rows))
        self.assertLessEqual(max(r["ts"] for r in art.valid_rows),
                             min(r["ts"] for r in art.test_rows))
        self.assertEqual(art.provenance["code_version"], "test-1")


class TestModels(unittest.TestCase):
    def test_16_training_refused_without_evidence(self):
        from backend.ml.datasets import DatasetSpec, build_dataset
        from backend.ml.models import TrainingRequest, train_gated
        spec = DatasetSpec(name="a", version="v1", grain="g", target="t")
        art = build_dataset(spec, [])
        out = train_gated(TrainingRequest(task_key="availability", dataset=art,
                                          model_name="m", maturity=empty_maturity()))
        self.assertFalse(out.trained)
        self.assertIn("BLOCKED", out.reason)

    def test_17_simple_model_trains_and_compares(self):
        from backend.ml.datasets import DatasetSpec, build_dataset
        from backend.ml.models import TrainingRequest, train_gated
        spec = DatasetSpec(name="a", version="v1", grain="g", target="t",
                           min_events=30, min_dates=14)
        opps = [{"ts": T0 + (i % 20) * DAY, "features": {},
                 "target": "available" if i % 3 else "busy",
                 "provenance": {}} for i in range(42)]
        art = build_dataset(spec, opps)
        out = train_gated(TrainingRequest(task_key="availability", dataset=art,
                                          model_name="m", maturity=rich_maturity()))
        self.assertTrue(out.trained)
        self.assertIn("test", out.metrics)
        self.assertIn("beats_baseline", out.baseline_comparison)

    def test_18_unknown_task_refused(self):
        from backend.ml.datasets import DatasetSpec, build_dataset
        from backend.ml.models import TrainingRequest, train_gated
        art = build_dataset(DatasetSpec(name="a", version="v", grain="g", target="t"), [])
        out = train_gated(TrainingRequest(task_key="nope", dataset=art, model_name="m"))
        self.assertFalse(out.trained)


class TestForecastingAnomaly(unittest.TestCase):
    def test_19_seasonal_naive_and_windows(self):
        from backend.ml.forecasting import FORECAST_SPECS, forecast_window, seasonal_naive
        self.assertIn("availability", FORECAST_SPECS)
        self.assertIsNone(seasonal_naive([1.0], 4, 2))  # too short: no forecast
        self.assertEqual(seasonal_naive([1.0, 2.0, 3.0, 4.0], 2, 3), [3.0, 4.0, 3.0])
        ev = [{"ts": T0 + i * DAY} for i in range(5)]
        hist, (cut, end) = forecast_window(ev, T0 + 2 * DAY, timedelta(days=2))
        self.assertEqual(len(hist), 3)
        self.assertEqual(len([e for e in ev if cut < e["ts"] <= end]), 2)
        with self.assertRaises(ValueError):
            forecast_window(ev, datetime(2026, 1, 1), timedelta(days=1))

    def test_20_anomaly_needs_history(self):
        from backend.ml.anomaly import iqr_anomalies, sudden_state_changes, zscore_anomalies
        self.assertEqual(zscore_anomalies([5.0]), [])
        self.assertEqual(zscore_anomalies([1.0] * 12), [])  # zero variance: nothing flaggable
        hits = zscore_anomalies([1.0] * 11 + [100.0])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].index, 11)
        self.assertEqual(iqr_anomalies([1.0] * 5), [])  # too few points
        self.assertEqual(sudden_state_changes(["a", "b"]), [])
        ch = sudden_state_changes(["a"] * 10 + ["b", "b"])
        self.assertEqual(len(ch), 1)
        self.assertEqual(ch[0]["to"], "b")


class TestRecommendations(unittest.TestCase):
    def _stations(self):
        return [
            {"id": "near-compat", "latitude": 19.076, "longitude": 72.877,
             "connector_types": ["CCS2"], "max_power_kw": 60.0},
            {"id": "near-unknown", "latitude": 19.077, "longitude": 72.878,
             "connector_types": [], "max_power_kw": None},
            {"id": "far-incompat", "latitude": 19.5, "longitude": 73.2,
             "connector_types": ["Type 1"], "max_power_kw": 7.0},
        ]

    def test_21_unknown_not_penalized(self):
        from backend.ml.recommendations import score_stations
        user = {"latitude": 19.076, "longitude": 72.877, "connector_type": "CCS2"}
        ranked = score_stations(self._stations(), user)
        order = [r.station_id for r in ranked]
        # compatible first; unknown-compat (neutral) above known-incompatible (penalized)
        self.assertEqual(order[0], "near-compat")
        self.assertLess(order.index("near-unknown"), order.index("far-incompat"))
        unk = next(r for r in ranked if r.station_id == "near-unknown")
        self.assertTrue(any("unknown" in u for u in unk.unknowns))
        self.assertTrue(all("NO_MODEL" in s for s in unk.unavailable_signals))

    def test_22_distance_exclusion_and_explanations(self):
        from backend.ml.recommendations import score_stations
        user = {"latitude": 19.076, "longitude": 72.877, "max_distance_km": 5.0}
        ranked = score_stations(self._stations(), user)
        self.assertTrue(all(r.station_id != "far-incompat" for r in ranked))
        self.assertTrue(all(r.reasons for r in ranked))


class MockCur:
    def __init__(self):
        self.statements: list[str] = []
        self._queue: list = []

    def execute(self, sql, params=()):
        cleaned = " ".join(sql.strip().split())
        self.statements.append(cleaned)
        if "RETURNING" in cleaned:
            self._queue.append([("00000000-0000-0000-0000-000000000001",)])
        elif cleaned.startswith("SELECT"):
            self._queue.append([("cold",)] if "data_maturity" in cleaned else [])

    def fetchone(self):
        return self._queue.pop(0)[0] if self._queue else None


class TestRegistry(unittest.TestCase):
    def test_23_writers_use_ml_tables_and_vocab(self):
        from backend.ml import registry
        cur = MockCur()
        k = registry.register_feature(cur, "max_power_kw", "numerical", "station_attributes", "d")
        self.assertTrue(k)
        d = registry.register_dataset(cur, "d", "v1", T0, T0, 0, 1, maturity="cold", role="training")
        self.assertTrue(d)
        e = registry.register_experiment(cur, "exp", d)
        m = registry.register_model_version(cur, e, "v1", "baseline", maturity="cold")
        registry.record_metric(cur, m, "mae", 1.5, "test")
        stmts = " ".join(cur.statements)
        for table in ("ml.features", "ml.datasets", "ml.experiments",
                      "ml.model_versions", "ml.metrics"):
            self.assertIn(table, stmts)
        for secret in ("password", "token", "secret"):
            self.assertNotIn(secret, stmts.lower())
        with self.assertRaises(ValueError):
            registry.set_model_status(cur, m, "bogus")
        with self.assertRaises(ValueError):
            # cold model must not become ready
            registry.set_model_status(cur, m, "ready")
        with self.assertRaises(ValueError):
            registry.register_dataset(cur, "d", "v2", T0, T0, 0, 0, role="nope")

    def test_24_experiment_lifecycle(self):
        from backend.ml import registry
        cur = MockCur()
        e = registry.register_experiment(cur, "exp2", "00000000-0000-0000-0000-000000000002")
        registry.set_experiment_status(cur, e, "running")
        registry.set_experiment_status(cur, e, "completed")
        with self.assertRaises(ValueError):
            registry.set_experiment_status(cur, e, "done")


class TestInference(unittest.TestCase):
    def test_25_unavailable_contracts_never_fake(self):
        from backend.ml.inference import (
            STATUS_NO_MODEL, resolve_availability, resolve_queue, to_product_claim, unavailable,
        )
        p = resolve_availability("s1")
        self.assertEqual(p.status, STATUS_NO_MODEL)
        self.assertIsNone(p.value)
        q = resolve_queue("s1")
        self.assertEqual(q.status, STATUS_NO_MODEL)
        claim = to_product_claim(p)
        self.assertEqual(claim["state"], "unknown")
        self.assertNotIn("available", claim["state"])
        custom = unavailable("demand", "s2", "INSUFFICIENT_DATA")
        self.assertEqual(custom.status, "INSUFFICIENT_DATA")
        with self.assertRaises(ValueError):
            unavailable("x", "s", "BOGUS")


if __name__ == "__main__":
    unittest.main()
