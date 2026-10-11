"""Phase 5 ML tests: gates, training, registry, inference, CLI contracts.

All training data here is explicitly SYNTHETIC (deterministic fixtures for
algorithmic unit tests only). Synthetic data never counts toward production
maturity: registry approval refuses synthetic artifacts by default, and no
test writes to production tables.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.ml.gates import (
    DEFAULT_GATE_CONFIG,
    DataMaturityEvidence,
    DataMaturityState,
    MLUnavailableReason,
    build_evidence_from_records,
    evaluate_gate,
)
from backend.ml.inference import InferenceService
from backend.ml.registry import ModelRegistry, RegistryError
from backend.ml.training import FEATURE_NAMES, MLTrainingPipeline


# ---------------------------------------------------------------------------
# Deterministic SYNTHETIC observation fixtures (clearly labelled)
# ---------------------------------------------------------------------------

SYNTHETIC_TAG = "SYNTHETIC unit-test fixture — not real-world evidence"


def make_synthetic_observations(
    *,
    stations: int = 6,
    days: int = 40,
    per_day: int = 24,
    end_at: datetime | None = None,
    busy_when=None,
    connector_count: int | None | str = "auto",
) -> list[dict]:
    """Builds deterministic synthetic observations ending at end_at (default now).

    busy_when(hour, day_index, station_index, rng) -> bool selects the label.
    The default is a connector-count signal with seeded noise: small stations
    (2 connectors, even index) are usually busy, large ones (6 connectors)
    usually free — a pattern the model can learn from its count feature but
    the per-(hour, weekday) baseline cannot, so a sound model beats baseline.

    connector_count="auto" alternates 2/6 by station; an int fixes all
    stations; None omits the field (all-missing imputation path).

    Timestamps are unique per (station, time). Seeded RNG: deterministic.
    """
    import random

    end_at = end_at or datetime.now(timezone.utc)
    start = end_at - timedelta(days=days)
    rng = random.Random(20261011)
    if busy_when is None:
        def busy_when(hour, _day, station, rng):
            return rng.random() < (0.8 if station % 2 == 0 else 0.1)
    obs: list[dict] = []
    for s in range(stations):
        count = (2 if s % 2 == 0 else 6) if connector_count == "auto" else connector_count
        for d in range(days):
            for h in range(per_day):
                ts = (start + timedelta(days=d, hours=h)).replace(
                    minute=0, second=0, microsecond=0
                )
                entry: dict = {
                    "station_id": f"synth-station-{s}",
                    "observed_at": ts.isoformat(),
                    "availability_status": "busy" if busy_when(h, d, s, rng) else "available",
                    "_synthetic": True,
                }
                if count is not None:
                    entry["connector_count"] = count
                obs.append(entry)
    return obs


@pytest.fixture()
def synth_ready():
    return make_synthetic_observations()


@pytest.fixture()
def artifact_dir(tmp_path):
    d = tmp_path / "artifacts"
    d.mkdir()
    return str(d)


def _train_synthetic(artifact_dir, observations, **kwargs):
    pipeline = MLTrainingPipeline(artifact_dir=artifact_dir)
    return pipeline.train(observations, is_synthetic_test=True, **kwargs)


# ---------------------------------------------------------------------------
# A. Maturity gate
# ---------------------------------------------------------------------------

class TestMaturityGate:
    def test_01_cold_on_zero_observations(self):
        evidence = build_evidence_from_records([])
        result = evaluate_gate(evidence)
        assert result.state == DataMaturityState.COLD
        assert result.passed is False
        assert result.unavailable_reason == MLUnavailableReason.DATA_MATURITY_COLD

    def test_02_warming_on_partial_history(self):
        obs = make_synthetic_observations(stations=2, days=8, per_day=4)
        evidence = build_evidence_from_records(obs)
        result = evaluate_gate(evidence)
        assert result.state == DataMaturityState.WARMING
        assert result.passed is False
        assert result.unavailable_reason == MLUnavailableReason.DATA_MATURITY_WARMING

    def test_03_ready_on_sufficient_synthetic_history(self, synth_ready):
        evidence = build_evidence_from_records(synth_ready)
        assert evidence.total_real_observations == 6 * 40 * 24
        assert evidence.stations_with_observations == 6
        assert evidence.observation_days_covered >= 30
        result = evaluate_gate(evidence)
        assert result.state == DataMaturityState.READY
        assert result.passed is True
        assert result.unavailable_reason is None

    def test_04_invalid_timestamps_skipped_not_counted(self):
        obs = make_synthetic_observations(stations=6, days=40, per_day=1)[:10]
        obs = list(obs) + [
            {"station_id": "s", "observed_at": "not-a-timestamp"},
            {"station_id": None, "observed_at": "2026-01-01T00:00:00Z"},
            {"station_id": "s"},
        ]
        evidence = build_evidence_from_records(obs)
        assert evidence.total_real_observations == 10
        assert any("skipped" in note for note in evidence.notes)

    def test_05_exact_duplicates_deduplicated(self, synth_ready):
        doubled = list(synth_ready) + list(synth_ready)
        evidence = build_evidence_from_records(doubled)
        single = build_evidence_from_records(synth_ready)
        assert evidence.total_real_observations == single.total_real_observations
        assert any("deduplicated" in note for note in evidence.notes)

    def test_06_stale_latest_fails_freshness(self, synth_ready):
        old = make_synthetic_observations(
            end_at=datetime.now(timezone.utc) - timedelta(days=30)
        )
        evidence = build_evidence_from_records(old)
        result = evaluate_gate(evidence)
        assert result.passed is False
        assert any("stale" in criterion.lower() for criterion in result.failed_criteria)

    def test_07_inverted_timestamps_flagged(self):
        now = datetime.now(timezone.utc)
        evidence = DataMaturityEvidence(
            total_real_observations=1000,
            stations_with_observations=6,
            observation_days_covered=40,
            observations_per_station_min=100,
            earliest_observation=now,
            latest_observation=now - timedelta(days=1),
        )
        result = evaluate_gate(evidence, as_of=now)
        assert result.passed is False
        assert any("integrity" in criterion.lower() for criterion in result.failed_criteria)

    def test_08_result_serializes_to_json(self, synth_ready):
        evidence = build_evidence_from_records(synth_ready)
        result = evaluate_gate(evidence)
        json.dumps(result.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# B. Training pipeline
# ---------------------------------------------------------------------------

class TestTrainingPipeline:
    def test_10_gate_refusal_on_empty(self, artifact_dir):
        pipeline = MLTrainingPipeline(artifact_dir=artifact_dir)
        result = pipeline.train([])
        assert result.success is False
        assert result.artifact is None
        assert result.unavailable_reason == MLUnavailableReason.DATA_MATURITY_COLD
        assert list(Path(artifact_dir).glob("model_*.pkl")) == []

    def test_11_synthetic_success_marks_test_only(self, artifact_dir, synth_ready):
        result = _train_synthetic(artifact_dir, synth_ready)
        assert result.success is True, result.errors
        artifact = result.artifact
        assert artifact is not None
        assert artifact.is_synthetic_test is True
        assert artifact.approved is False  # never auto-approved
        assert artifact.train_rows + artifact.val_rows + artifact.test_rows == artifact.dataset_row_count
        # Artifact bytes + sidecar metadata exist
        pkl = Path(artifact.artifact_path)
        assert pkl.is_file()
        assert pkl.with_suffix(".json").is_file()
        # Checksum matches recomputation
        assert hashlib.sha256(pkl.read_bytes()).hexdigest() == artifact.artifact_checksum
        # Chronological split bounds (no shuffling across time)
        bounds = artifact.split_bounds
        assert bounds["train"]["end"] <= bounds["validation"]["start"]
        assert bounds["validation"]["end"] <= bounds["test"]["start"]

    def test_12_deterministic_metrics(self, artifact_dir, synth_ready):
        first = _train_synthetic(artifact_dir, synth_ready)
        second = _train_synthetic(artifact_dir, synth_ready)
        assert first.success and second.success
        assert first.artifact.model_mae == second.artifact.model_mae

    def test_13_no_temporal_leakage(self, artifact_dir):
        # Peak pattern in the past, all-busy in the last 12 days. Train keeps
        # both classes; a chronological model predicts the past pattern on the
        # all-busy test split (high MAE), while a leaking random-split model
        # would score ~0. Threshold 0.7 separates the two decisively.
        peak = {8, 9, 18, 19, 20}
        obs = make_synthetic_observations(
            busy_when=lambda h, d, _s, _rng: True if d >= 28 else h in peak
        )
        result = _train_synthetic(artifact_dir, obs)
        assert result.success is True, result.errors
        assert result.artifact.model_mae_test is not None
        assert result.artifact.model_mae_test >= 0.7

    def test_14_all_missing_counts_documented_fallback(self, artifact_dir):
        obs = make_synthetic_observations(connector_count=None)
        result = _train_synthetic(artifact_dir, obs)
        assert result.success is True, result.errors
        assert any("entirely missing" in w for w in result.warnings)

    def test_15_overlapping_training_refused(self, artifact_dir, synth_ready):
        pipeline = MLTrainingPipeline(artifact_dir=artifact_dir)
        lock = Path(artifact_dir) / "training.lock"
        lock.write_text("other-pid")
        result = pipeline.train(synth_ready, is_synthetic_test=True)
        assert result.success is False
        assert result.unavailable_reason == MLUnavailableReason.TRAINING_IN_PROGRESS

    def test_16_record_to_db_uses_parameterized_sql(self, artifact_dir, synth_ready):
        result = _train_synthetic(artifact_dir, synth_ready)
        assert result.success

        calls: list[tuple] = []

        class FakeCursor:
            def execute(self, query, params=None):
                calls.append((query, params))

            def fetchone(self):
                return ["00000000-0000-0000-0000-000000000000"]

            def close(self):
                pass

        class FakeConn:
            committed = False

            def cursor(self):
                return FakeCursor()

            def commit(self):
                self.committed = True

            def rollback(self):
                pass

        conn = FakeConn()
        pipeline = MLTrainingPipeline(artifact_dir=artifact_dir)
        summary = pipeline.record_to_db(
            conn, result, experiment_name="test-exp", dataset_name="test-ds",
        )
        assert summary["ok"] is True
        assert conn.committed is True
        queries = [q for q, _ in calls]
        assert any("INSERT INTO ml.model_versions" in q for q in queries)
        assert any("INSERT INTO ml.metrics" in q for q in queries)
        assert any("INSERT INTO ml.experiments" in q for q in queries)
        for query, params in calls:
            # No value interpolation: placeholders + separate params, and model
            # bytes are never stored in the DB.
            assert "%s" in query
            for value in params or ():
                assert not isinstance(value, (bytes, bytearray))


# ---------------------------------------------------------------------------
# C. Registry lifecycle
# ---------------------------------------------------------------------------

class TestModelRegistry:
    def _approved_synthetic_registry(self, artifact_dir, synth_ready):
        result = _train_synthetic(artifact_dir, synth_ready)
        assert result.success
        registry = ModelRegistry(artifact_dir, allow_synthetic_promotion=True)
        version = result.artifact.model_version
        registry.approve(version, approver="test-operator")
        return registry, version

    def test_20_no_active_model_initially(self, artifact_dir):
        assert ModelRegistry(artifact_dir).get_active() is None

    def test_21_synthetic_approval_refused_by_default(self, artifact_dir, synth_ready):
        result = _train_synthetic(artifact_dir, synth_ready)
        registry = ModelRegistry(artifact_dir)  # production default
        with pytest.raises(RegistryError, match="synthetic"):
            registry.approve(result.artifact.model_version, approver="op")

    def test_22_approve_and_serve_active(self, artifact_dir, synth_ready):
        registry, version = self._approved_synthetic_registry(artifact_dir, synth_ready)
        active = registry.get_active()
        assert active is not None
        assert active["model_version"] == version
        bundle = registry.load_model_bundle(version)
        assert bundle["model_version"] == version
        assert bundle["feature_names"] == FEATURE_NAMES

    def test_23_non_beating_model_needs_recorded_override(self, artifact_dir):
        peak = {8, 9, 18, 19, 20}
        obs = make_synthetic_observations(
            busy_when=lambda h, d, _s, _rng: True if d >= 28 else h in peak
        )
        result = _train_synthetic(artifact_dir, obs)
        assert result.success is True
        assert result.artifact.model_beats_baseline is False
        registry = ModelRegistry(artifact_dir, allow_synthetic_promotion=True)
        with pytest.raises(RegistryError, match="baseline"):
            registry.approve(result.artifact.model_version, approver="op")
        with pytest.raises(RegistryError, match="override_reason"):
            registry.approve(
                result.artifact.model_version, approver="op",
                allow_non_baseline_beating=True,
            )
        meta = registry.approve(
            result.artifact.model_version, approver="op",
            allow_non_baseline_beating=True, override_reason="test override",
        )
        assert meta["approval_override_reason"] == "test override"

    def test_24_checksum_tamper_invalidates(self, artifact_dir, synth_ready):
        registry, version = self._approved_synthetic_registry(artifact_dir, synth_ready)
        pkl = Path(artifact_dir) / f"model_{version}.pkl"
        with open(pkl, "ab") as fh:
            fh.write(b"\x00")
        assert registry.verify(version).ok is False
        # Stale pointer degrades to NO_MODEL instead of serving bad bytes
        assert registry.get_active() is None
        with pytest.raises(RegistryError, match="unverified"):
            registry.load_model_bundle(version)

    def test_25_path_traversal_refused(self, artifact_dir):
        registry = ModelRegistry(artifact_dir)
        # verify() reports failure as a result; approve()/load refuse loudly.
        assert registry.verify("../../etc/passwd").ok is False
        with pytest.raises(RegistryError):
            registry.approve("/abs/path", approver="op")

    def test_26_rollback_to_previous(self, artifact_dir, synth_ready):
        registry, v1 = self._approved_synthetic_registry(artifact_dir, synth_ready)
        time.sleep(1.1)  # version names carry 1s resolution
        result2 = _train_synthetic(artifact_dir, synth_ready)
        v2 = result2.artifact.model_version
        assert v2 != v1
        registry.approve(v2, approver="op")
        assert registry.get_active()["model_version"] == v2
        rolled = registry.rollback(approver="op")
        assert rolled["model_version"] == v1
        assert registry.get_active()["model_version"] == v1

    def test_27_rollback_without_history_refused(self, artifact_dir, synth_ready):
        registry, _v1 = self._approved_synthetic_registry(artifact_dir, synth_ready)
        with pytest.raises(RegistryError, match="No previously approved"):
            registry.rollback(approver="op")

    def test_28_list_versions(self, artifact_dir, synth_ready):
        result = _train_synthetic(artifact_dir, synth_ready)
        versions = [m["model_version"] for m in ModelRegistry(artifact_dir).list_versions()]
        assert result.artifact.model_version in versions


# ---------------------------------------------------------------------------
# D. Inference
# ---------------------------------------------------------------------------

def _features(**overrides):
    base = {
        "hour_of_day": 18,
        "day_of_week": 4,
        "is_weekend": 0,
        "month": 10,
        "station_connector_count": 4,
    }
    base.update(overrides)
    return base


class TestInference:
    def test_30_no_model_without_approval(self, artifact_dir, synth_ready):
        _train_synthetic(artifact_dir, synth_ready)  # trained but NOT approved
        service = InferenceService(ModelRegistry(artifact_dir))
        result = service.predict(
            _features(), latest_observation_at=datetime.now(timezone.utc)
        )
        assert result.success is False
        assert result.reason == MLUnavailableReason.NO_MODEL
        assert result.probability is None

    def test_31_success_with_approved_model(self, artifact_dir, synth_ready):
        registry = ModelRegistry(artifact_dir, allow_synthetic_promotion=True)
        result = _train_synthetic(artifact_dir, synth_ready)
        registry.approve(result.artifact.model_version, approver="op")
        service = InferenceService(registry)
        now = datetime.now(timezone.utc)
        out = service.predict(_features(), latest_observation_at=now)
        assert out.success is True, out.message
        assert 0.0 <= out.probability <= 1.0
        assert out.model_version == result.artifact.model_version
        assert out.input_cutoff == now
        assert out.horizon == "current"
        json.dumps(out.to_dict())

    def test_32_schema_mismatch_missing_feature(self, artifact_dir, synth_ready):
        registry = ModelRegistry(artifact_dir, allow_synthetic_promotion=True)
        result = _train_synthetic(artifact_dir, synth_ready)
        registry.approve(result.artifact.model_version, approver="op")
        service = InferenceService(registry)
        features = _features()
        del features["hour_of_day"]
        out = service.predict(features, latest_observation_at=datetime.now(timezone.utc))
        assert out.success is False
        assert out.reason == MLUnavailableReason.FEATURE_SCHEMA_MISMATCH

    def test_33_schema_mismatch_bad_range(self, artifact_dir, synth_ready):
        registry = ModelRegistry(artifact_dir, allow_synthetic_promotion=True)
        result = _train_synthetic(artifact_dir, synth_ready)
        registry.approve(result.artifact.model_version, approver="op")
        service = InferenceService(registry)
        out = service.predict(
            _features(hour_of_day=25),
            latest_observation_at=datetime.now(timezone.utc),
        )
        assert out.success is False
        assert out.reason == MLUnavailableReason.FEATURE_SCHEMA_MISMATCH

    def test_34_stale_features_refused(self, artifact_dir, synth_ready):
        registry = ModelRegistry(artifact_dir, allow_synthetic_promotion=True)
        result = _train_synthetic(artifact_dir, synth_ready)
        registry.approve(result.artifact.model_version, approver="op")
        service = InferenceService(registry)
        stale = datetime.now(timezone.utc) - timedelta(days=10)
        out = service.predict(_features(), latest_observation_at=stale)
        assert out.success is False
        assert out.reason == MLUnavailableReason.STALE_FEATURES

    def test_35_unverifiable_freshness_refused(self, artifact_dir, synth_ready):
        registry = ModelRegistry(artifact_dir, allow_synthetic_promotion=True)
        result = _train_synthetic(artifact_dir, synth_ready)
        registry.approve(result.artifact.model_version, approver="op")
        service = InferenceService(registry)
        out = service.predict(_features(), latest_observation_at=None)
        assert out.success is False
        assert out.reason == MLUnavailableReason.STALE_FEATURES

    def test_36_tampered_model_refused_at_serve_time(self, artifact_dir, synth_ready):
        registry = ModelRegistry(artifact_dir, allow_synthetic_promotion=True)
        result = _train_synthetic(artifact_dir, synth_ready)
        registry.approve(result.artifact.model_version, approver="op")
        pkl = Path(artifact_dir) / f"model_{result.artifact.model_version}.pkl"
        with open(pkl, "ab") as fh:
            fh.write(b"\x00")
        service = InferenceService(registry)
        out = service.predict(_features(), latest_observation_at=datetime.now(timezone.utc))
        # Pointer is stale → NO_MODEL (never serves unverified bytes)
        assert out.success is False
        assert out.reason in (MLUnavailableReason.NO_MODEL, MLUnavailableReason.MODEL_ARTIFACT_INVALID)

    def test_37_nan_output_rejected(self, artifact_dir, synth_ready):
        registry = ModelRegistry(artifact_dir, allow_synthetic_promotion=True)
        result = _train_synthetic(artifact_dir, synth_ready)
        registry.approve(result.artifact.model_version, approver="op")

        class NanModel:
            def predict_proba(self, X):
                import numpy as np

                return np.array([[float("nan"), float("nan")]])

        registry.load_model_bundle = lambda _v: {"model": NanModel(), "col_medians": [12.0] * 5}  # type: ignore
        service = InferenceService(registry)
        out = service.predict(_features(), latest_observation_at=datetime.now(timezone.utc))
        assert out.success is False
        assert out.reason == MLUnavailableReason.MODEL_ARTIFACT_INVALID

    def test_38_status_reports_gate_and_model(self, artifact_dir, synth_ready):
        registry = ModelRegistry(artifact_dir, allow_synthetic_promotion=True)
        result = _train_synthetic(artifact_dir, synth_ready)
        registry.approve(result.artifact.model_version, approver="op")
        service = InferenceService(registry)
        status = service.status(synth_ready)
        assert status["inference_available"] is True
        assert status["reason"] is None
        assert status["active_model"]["model_version"] == result.artifact.model_version
        assert status["gate"]["passed"] is True

    def test_39_status_cold_without_observations(self, artifact_dir):
        service = InferenceService(ModelRegistry(artifact_dir))
        status = service.status([])
        assert status["inference_available"] is False
        assert status["reason"] == MLUnavailableReason.DATA_MATURITY_COLD.value


# ---------------------------------------------------------------------------
# E. CLI integration contracts (the surface the app API routes consume)
# ---------------------------------------------------------------------------

class TestMlCliContracts:
    def _run_cli(self, *args):
        proc = subprocess.run(
            [sys.executable, "-m", "backend.ml.cli", *args],
            capture_output=True, text=True, timeout=300,
        )
        return proc

    def test_40_status_cold_no_model(self, artifact_dir):
        proc = self._run_cli("status", "--artifact-dir", artifact_dir)
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["inference_available"] is False
        assert payload["active_model"] is None
        assert payload["gate"]["passed"] is False

    def test_41_train_predict_roundtrip(self, artifact_dir, synth_ready, tmp_path):
        obs_path = tmp_path / "synth.json"
        obs_path.write_text(json.dumps(synth_ready))
        train = self._run_cli(
            "train", "--artifact-dir", artifact_dir,
            "--observations-json", str(obs_path), "--data-kind", "synthetic",
        )
        assert train.returncode == 0, train.stdout[-2000:]
        trained = json.loads(train.stdout)
        assert trained["success"] is True
        assert trained["artifact"]["is_synthetic_test"] is True
        version = trained["artifact"]["model_version"]

        # CLI predict before approval → NO_MODEL (fail-closed end to end)
        predict = self._run_cli(
            "predict", "--artifact-dir", artifact_dir,
            "--features", json.dumps(_features()),
            "--latest-observation-at", datetime.now(timezone.utc).isoformat(),
        )
        assert predict.returncode == 0
        assert json.loads(predict.stdout)["reason"] == "NO_MODEL"

        # Approve (test seam) then predict succeeds
        ModelRegistry(artifact_dir, allow_synthetic_promotion=True).approve(
            version, approver="cli-test"
        )
        predict2 = self._run_cli(
            "predict", "--artifact-dir", artifact_dir,
            "--features", json.dumps(_features()),
            "--latest-observation-at", datetime.now(timezone.utc).isoformat(),
        )
        assert predict2.returncode == 0
        payload = json.loads(predict2.stdout)
        assert payload["success"] is True
        assert 0.0 <= payload["probability"] <= 1.0
        assert payload["model_version"] == version

    def test_42_train_requires_data_kind(self, artifact_dir, tmp_path):
        obs_path = tmp_path / "synth.json"
        obs_path.write_text(json.dumps(make_synthetic_observations(days=1, per_day=1)))
        proc = self._run_cli(
            "train", "--artifact-dir", artifact_dir,
            "--observations-json", str(obs_path),
        )
        assert proc.returncode == 2  # argparse: --data-kind is required
