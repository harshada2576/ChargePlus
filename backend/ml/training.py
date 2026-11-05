"""ChargePlus — Phase 5 ML Training Pipeline.

Phase: 5/6 (Data Mining, Forecasting & Recommendations)
Steps: 5.2–5.6 (Baseline, Feature Engineering, Training, Evaluation)

Implements the busy-time forecasting model for EV charging stations.

Architecture:
  - Dataset extraction from approved real analytics observations
  - Time-aware feature engineering (no future leakage)
  - Baseline: median per (hour, weekday) — always computed first
  - Time-based train/validation/test splits (chronological, no random splits)
  - Simple model: gradient-boosted or random forest (scikit-learn)
  - Evaluation: MAE, RMSE vs baseline — if model doesn't beat baseline, documented
  - Artifact: versioned pickle with checksum + metadata; NOT loaded from user paths
  - Gate: checks DataMaturityGate before extracting any data

Key invariants:
  - Synthetic data may only be used for algorithmic unit tests (labelled SYNTHETIC).
  - Never report training success unless a genuine training run completed.
  - Never lower maturity thresholds to make training pass.
  - Time-based splits only for any time-series evaluation.
  - Missing features propagate as NaN (not imputed to 0 or median without documenting).

CURRENT STATE (2026-10):
  Production database contains 0 real station observations (COLD maturity state).
  This module correctly refuses training when the gate fails.
  The infrastructure is complete and will activate automatically once
  sufficient real observations are collected through ingestion.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("chargeplus.ml.training")

# Only import ML libs inside methods to avoid hard dependency when gate is COLD
try:
    import numpy as np
    import pandas as pd
    _ML_LIBS_AVAILABLE = True
except ImportError:
    _ML_LIBS_AVAILABLE = False
    logger.warning(
        "numpy/pandas not available. Install with: pip install numpy pandas scikit-learn"
    )

from backend.ml.gates import (
    DEFAULT_GATE_CONFIG,
    DataMaturityEvidence,
    DataMaturityState,
    GateResult,
    MLGateConfig,
    MLUnavailableReason,
    build_evidence_from_records,
    evaluate_gate,
)


# ---------------------------------------------------------------------------
# Feature schema — locked at training and validated at inference
# ---------------------------------------------------------------------------

# V1 feature schema: must match at inference time
FEATURE_SCHEMA_VERSION = "v1"
FEATURE_NAMES = [
    "hour_of_day",         # 0–23
    "day_of_week",         # 0=Mon … 6=Sun
    "is_weekend",          # 0 or 1
    "month",               # 1–12
    "station_connector_count",  # total connectors at station (can be NaN)
]

TARGET_COLUMN = "is_busy"  # 1 if availability_status == 'busy', else 0
PREDICTION_HORIZON_DESCRIPTION = "Current busy probability for a station at a given time"


def _safe_count(value: Any) -> float:
    """Coerces an optional connector count to float, NaN when unusable."""
    import math

    if value is None:
        return float("nan")
    try:
        parsed = float(value)
    except (ValueError, TypeError):
        return float("nan")
    return parsed if math.isfinite(parsed) and parsed >= 0 else float("nan")


# ---------------------------------------------------------------------------
# Model artifact
# ---------------------------------------------------------------------------

@dataclass
class ModelArtifact:
    """Versioned, checksummed model artifact metadata."""
    model_id: str
    model_version: str
    feature_schema_version: str
    feature_names: list[str]
    target_column: str
    training_started_at: datetime
    training_completed_at: Optional[datetime]
    dataset_row_count: int
    dataset_station_count: int
    dataset_earliest: Optional[str]
    dataset_latest: Optional[str]
    train_rows: int
    val_rows: int
    test_rows: int
    # Inclusive ISO time bounds per chronological split (lineage for ml.datasets).
    split_bounds: Optional[dict[str, Any]]
    baseline_mae: Optional[float]
    baseline_rmse: Optional[float]
    model_mae: Optional[float]
    model_rmse: Optional[float]
    model_mae_test: Optional[float]  # held-out test MAE (never tuned on)
    model_beats_baseline: Optional[bool]
    artifact_path: Optional[str]
    artifact_checksum: Optional[str]
    approved: bool = False
    approved_at: Optional[datetime] = None
    notes: list[str] = field(default_factory=list)
    is_synthetic_test: bool = False  # Must be True for any test-only artifacts

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()}
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d


# ---------------------------------------------------------------------------
# Training result
# ---------------------------------------------------------------------------

@dataclass
class TrainingResult:
    """Result returned by the training pipeline."""
    success: bool
    gate_result: GateResult
    artifact: Optional[ModelArtifact] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reason: Optional[MLUnavailableReason] = None

    @property
    def unavailable_reason(self) -> Optional[MLUnavailableReason]:
        if self.success:
            return None
        if self.reason is not None:
            return self.reason
        if not self.gate_result.passed:
            return self.gate_result.unavailable_reason
        return MLUnavailableReason.NO_MODEL


# ---------------------------------------------------------------------------
# Training pipeline
# ---------------------------------------------------------------------------

class MLTrainingPipeline:
    """Orchestrates Phase 5 ML training.

    Usage:
        pipeline = MLTrainingPipeline(artifact_dir="backend/ml/artifacts")
        result = pipeline.train(observations=real_obs_list)
    """

    def __init__(
        self,
        artifact_dir: str = "backend/ml/artifacts",
        gate_config: MLGateConfig = DEFAULT_GATE_CONFIG,
    ) -> None:
        self._artifact_dir = Path(artifact_dir)
        self._gate_config = gate_config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_gate(
        self,
        observations: list[dict[str, Any]],
        as_of: Optional[datetime] = None,
    ) -> GateResult:
        """Checks data maturity without attempting training."""
        as_of = as_of or datetime.now(timezone.utc)
        evidence = build_evidence_from_records(observations, as_of=as_of)
        return evaluate_gate(evidence, config=self._gate_config, as_of=as_of)

    def train(
        self,
        observations: list[dict[str, Any]],
        as_of: Optional[datetime] = None,
        is_synthetic_test: bool = False,
    ) -> TrainingResult:
        """Runs the full training pipeline.

        REQUIRES: gate_result.passed == True (READY state).

        If gate fails → returns TrainingResult(success=False, gate_result=...).
        If gate passes → extracts features, trains, evaluates, saves artifact.

        is_synthetic_test=True marks the artifact as test-only; such artifacts
        are NEVER approved for production inference.
        """
        if not _ML_LIBS_AVAILABLE:
            gate_result = self.check_gate(observations, as_of=as_of)
            return TrainingResult(
                success=False,
                gate_result=gate_result,
                errors=[
                    "numpy/pandas/scikit-learn not installed. "
                    "Run: pip install numpy pandas scikit-learn"
                ],
            )

        as_of = as_of or datetime.now(timezone.utc)
        gate_result = self.check_gate(observations, as_of=as_of)

        if not gate_result.passed:
            logger.info(
                "Training aborted: gate %s — %s",
                gate_result.state.value, gate_result.message
            )
            return TrainingResult(
                success=False,
                gate_result=gate_result,
                errors=[f"Data maturity gate not satisfied: {gate_result.message}"],
            )

        logger.info(
            "Gate READY — proceeding with training on %d observations",
            gate_result.evidence.total_real_observations,
        )

        # Overlap guard: one training run per artifact directory. Stale locks
        # (older than 2h, e.g. from a crashed run) are reclaimed; fresh locks
        # fail closed with TRAINING_IN_PROGRESS instead of partial promotion.
        lock_path = self._artifact_dir / "training.lock"
        try:
            self._acquire_training_lock(lock_path)
        except RuntimeError as exc:
            return TrainingResult(
                success=False,
                gate_result=gate_result,
                errors=[str(exc)],
                reason=MLUnavailableReason.TRAINING_IN_PROGRESS,
            )

        try:
            return self._run_training(
                observations=observations,
                gate_result=gate_result,
                as_of=as_of,
                is_synthetic_test=is_synthetic_test,
            )
        except Exception as exc:
            logger.exception("Training pipeline failed: %s", exc)
            return TrainingResult(
                success=False,
                gate_result=gate_result,
                errors=[f"Training pipeline error: {exc}"],
            )
        finally:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _acquire_training_lock(lock_path: Path) -> None:
        """Creates an exclusive training lock, reclaiming it only when stale."""
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age_hours = (
                    datetime.now(timezone.utc)
                    - datetime.fromtimestamp(lock_path.stat().st_mtime, tz=timezone.utc)
                ).total_seconds() / 3600.0
            except OSError:
                age_hours = 0.0
            if age_hours < 2.0:
                raise RuntimeError(
                    "Another training run is already in progress "
                    f"(lock {lock_path}, age {age_hours:.1f}h). "
                    "Refusing overlapping training."
                )
            logger.warning(
                "Reclaiming stale training lock (age %.1fh)", age_hours
            )
            try:
                lock_path.unlink()
            except OSError:
                pass
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}".encode())
        finally:
            os.close(fd)

    # ------------------------------------------------------------------
    # Internal pipeline steps
    # ------------------------------------------------------------------

    def _run_training(
        self,
        observations: list[dict[str, Any]],
        gate_result: GateResult,
        as_of: datetime,
        is_synthetic_test: bool,
    ) -> TrainingResult:
        """Core training logic. Only called when gate.passed == True."""
        import numpy as np
        import pandas as pd

        started_at = datetime.now(timezone.utc)
        model_id = str(uuid.uuid4())
        model_version = f"v1-{started_at.strftime('%Y%m%d-%H%M%S')}"
        warnings: list[str] = []

        # 1. Build DataFrame
        df = self._build_dataframe(observations, warnings)
        if df is None or len(df) == 0:
            return TrainingResult(
                success=False,
                gate_result=gate_result,
                errors=["Feature extraction produced empty DataFrame."],
            )

        # 2. Time-based splits (NEVER random for time series)
        df = df.sort_values("observed_at").reset_index(drop=True)
        n = len(df)
        train_end = int(n * 0.70)
        val_end = int(n * 0.85)

        df_train = df.iloc[:train_end]
        df_val = df.iloc[train_end:val_end]
        df_test = df.iloc[val_end:]

        if len(df_train) < 10 or len(df_val) < 5:
            return TrainingResult(
                success=False,
                gate_result=gate_result,
                errors=[
                    f"Insufficient data for train/val split: "
                    f"train={len(df_train)}, val={len(df_val)}, test={len(df_test)}"
                ],
            )

        X_train = df_train[FEATURE_NAMES].values
        y_train = df_train[TARGET_COLUMN].values
        X_val = df_val[FEATURE_NAMES].values
        y_val = df_val[TARGET_COLUMN].values
        X_test = df_test[FEATURE_NAMES].values
        y_test = df_test[TARGET_COLUMN].values

        # Handle NaN: impute with training column medians. A feature that is
        # entirely missing in training has no median: fall back to 0.0 and say
        # so loudly. This is a documented model-input fallback, never a stored
        # fact — missing stays missing everywhere else in the system.
        col_medians = np.array([
            float(np.median(col[~np.isnan(col)]))
            if np.any(~np.isnan(col)) else float("nan")
            for col in X_train.T
        ], dtype=float)
        for col_idx, median in enumerate(col_medians):
            if not np.isfinite(median):
                col_medians[col_idx] = 0.0
                warnings.append(
                    f"Feature '{FEATURE_NAMES[col_idx]}' entirely missing in training data; "
                    "imputing 0.0 as a documented model-input fallback (not a stored fact)."
                )
                median = 0.0
            for arr in (X_train, X_val, X_test):
                mask = np.isnan(arr[:, col_idx])
                if mask.any():
                    arr[mask, col_idx] = median
                    warnings.append(
                        f"Imputed {mask.sum()} NaN values in feature "
                        f"'{FEATURE_NAMES[col_idx]}' with training median {median:.2f}"
                    )

        # 3. Baseline: median per (hour, weekday) from training data
        baseline_preds_val, baseline_preds_test = self._compute_baseline(
            df_train, df_val, df_test, TARGET_COLUMN
        )
        baseline_mae_val = float(np.mean(np.abs(baseline_preds_val - y_val)))
        baseline_mae_test = float(np.mean(np.abs(baseline_preds_test - y_test)))
        baseline_rmse_val = float(np.sqrt(np.mean((baseline_preds_val - y_val) ** 2)))

        logger.info(
            "Baseline MAE (val): %.4f, RMSE (val): %.4f",
            baseline_mae_val, baseline_rmse_val
        )

        # 4. Train model (Random Forest or GBM, whichever is available)
        model = self._fit_model(X_train, y_train)
        if model is None:
            return TrainingResult(
                success=False,
                gate_result=gate_result,
                errors=["scikit-learn not available. Install with: pip install scikit-learn"],
            )

        # 5. Evaluate
        val_preds = model.predict(X_val)
        model_mae_val = float(np.mean(np.abs(val_preds - y_val)))
        model_rmse_val = float(np.sqrt(np.mean((val_preds - y_val) ** 2)))
        model_beats_baseline = model_mae_val < baseline_mae_val

        test_preds = model.predict(X_test)
        model_mae_test = float(np.mean(np.abs(test_preds - y_test)))

        logger.info(
            "Model MAE (val): %.4f, RMSE (val): %.4f, beats baseline: %s",
            model_mae_val, model_rmse_val, model_beats_baseline
        )

        if not model_beats_baseline:
            warnings.append(
                f"Model (MAE {model_mae_val:.4f}) does NOT beat baseline "
                f"(MAE {baseline_mae_val:.4f}) on validation set. "
                "Results documented as-is; model NOT approved for production."
            )

        # 6. Save artifact
        artifact_path, checksum = self._save_artifact(
            model=model,
            model_id=model_id,
            model_version=model_version,
            col_medians=col_medians,
        )

        # 7. Build metadata
        evidence = gate_result.evidence
        completed_at = datetime.now(timezone.utc)
        split_bounds = {
            "train": {
                "start": df_train["observed_at"].min().isoformat(),
                "end": df_train["observed_at"].max().isoformat(),
            },
            "validation": {
                "start": df_val["observed_at"].min().isoformat(),
                "end": df_val["observed_at"].max().isoformat(),
            },
            "test": {
                "start": df_test["observed_at"].min().isoformat(),
                "end": df_test["observed_at"].max().isoformat(),
            },
        }
        artifact = ModelArtifact(
            model_id=model_id,
            model_version=model_version,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            feature_names=list(FEATURE_NAMES),
            target_column=TARGET_COLUMN,
            training_started_at=started_at,
            training_completed_at=completed_at,
            dataset_row_count=len(df),
            dataset_station_count=evidence.stations_with_observations,
            dataset_earliest=(
                evidence.earliest_observation.isoformat()
                if evidence.earliest_observation else None
            ),
            dataset_latest=(
                evidence.latest_observation.isoformat()
                if evidence.latest_observation else None
            ),
            train_rows=len(df_train),
            val_rows=len(df_val),
            test_rows=len(df_test),
            split_bounds=split_bounds,
            baseline_mae=baseline_mae_val,
            baseline_rmse=baseline_rmse_val,
            model_mae=model_mae_val,
            model_rmse=model_rmse_val,
            model_mae_test=model_mae_test,
            model_beats_baseline=model_beats_baseline,
            artifact_path=str(artifact_path) if artifact_path else None,
            artifact_checksum=checksum,
            approved=False,  # Requires explicit promotion; not auto-approved
            notes=warnings + (
                ["Model does not beat baseline — requires review before promotion"]
                if not model_beats_baseline else []
            ),
            is_synthetic_test=is_synthetic_test,
        )

        # Save metadata alongside artifact
        if artifact_path:
            meta_path = artifact_path.with_suffix(".json")
            meta_path.write_text(
                json.dumps(artifact.to_dict(), indent=2, default=str)
            )

        logger.info(
            "Training complete: model_id=%s beats_baseline=%s artifact=%s",
            model_id, model_beats_baseline, artifact_path
        )

        return TrainingResult(
            success=True,
            gate_result=gate_result,
            artifact=artifact,
            warnings=warnings,
        )

    def _build_dataframe(
        self, observations: list[dict[str, Any]], warnings: list[str]
    ):
        """Constructs the ML feature DataFrame from observation records.

        Feature engineering (time-aware, no future leakage):
          hour_of_day, day_of_week, is_weekend, month, station_connector_count
        Target: is_busy (1 if availability_status == 'busy', else 0)
        """
        try:
            import pandas as pd
            import numpy as np
        except ImportError:
            return None

        rows = []
        skipped = 0
        seen: set[tuple[str, str]] = set()

        for obs in observations:
            raw_ts = obs.get("observed_at")
            station_id = obs.get("station_id")
            availability = str(obs.get("availability_status") or "").lower()
            connector_count = obs.get("connector_count")

            if not raw_ts or not station_id:
                skipped += 1
                continue

            if isinstance(raw_ts, str):
                try:
                    ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                except ValueError:
                    skipped += 1
                    continue
            elif isinstance(raw_ts, datetime):
                ts = raw_ts
            else:
                skipped += 1
                continue

            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            # Exact duplicates (same station + timestamp) train once: keeping
            # both would overweight double-ingested evidence.
            dup_key = (str(station_id), ts.isoformat())
            if dup_key in seen:
                skipped += 1
                continue
            seen.add(dup_key)

            rows.append({
                "observed_at": ts,
                "station_id": station_id,
                "hour_of_day": ts.hour,
                "day_of_week": ts.weekday(),
                "is_weekend": int(ts.weekday() >= 5),
                "month": ts.month,
                "station_connector_count": _safe_count(connector_count),
                TARGET_COLUMN: int(availability == "busy"),
            })

        if skipped > 0:
            warnings.append(f"Skipped {skipped} observations with missing fields or invalid timestamps.")

        if not rows:
            return None

        df = pd.DataFrame(rows)
        return df

    def _compute_baseline(
        self, df_train, df_val, df_test, target_col: str
    ):
        """Median-per-(hour, weekday) baseline from training data.

        This is the reference a model must beat to be considered useful.
        Uses only training data to compute the lookup table.
        """
        import numpy as np
        import pandas as pd

        lookup = (
            df_train.groupby(["hour_of_day", "day_of_week"])[target_col]
            .median()
            .to_dict()
        )
        global_median = float(df_train[target_col].median())

        def predict_baseline(df):
            preds = []
            for _, row in df.iterrows():
                key = (int(row["hour_of_day"]), int(row["day_of_week"]))
                preds.append(lookup.get(key, global_median))
            return np.array(preds, dtype=float)

        return predict_baseline(df_val), predict_baseline(df_test)

    def _fit_model(self, X_train, y_train):
        """Trains a scikit-learn model. Returns None if scikit-learn unavailable."""
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.1,
                random_state=42,
                min_samples_leaf=10,
            )
            model.fit(X_train, y_train)
            return model
        except ImportError:
            pass

        try:
            from sklearn.ensemble import RandomForestClassifier
            model = RandomForestClassifier(
                n_estimators=100,
                max_depth=6,
                random_state=42,
                min_samples_leaf=10,
            )
            model.fit(X_train, y_train)
            return model
        except ImportError:
            return None

    def _save_artifact(
        self,
        model: Any,
        model_id: str,
        model_version: str,
        col_medians,
    ) -> tuple[Optional[Path], Optional[str]]:
        """Saves model pickle + imputation metadata. Returns (path, sha256_checksum)."""
        try:
            self._artifact_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Cannot create artifact directory: %s", exc)
            return None, None

        payload = {
            "model": model,
            "feature_names": FEATURE_NAMES,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "col_medians": col_medians.tolist() if hasattr(col_medians, "tolist") else list(col_medians),
            "model_id": model_id,
            "model_version": model_version,
        }

        artifact_path = self._artifact_dir / f"model_{model_version}.pkl"
        try:
            pkl_bytes = pickle.dumps(payload, protocol=4)
        except Exception as exc:
            logger.error("Failed to serialize model: %s", exc)
            return None, None

        checksum = hashlib.sha256(pkl_bytes).hexdigest()

        try:
            artifact_path.write_bytes(pkl_bytes)
            logger.info("Model artifact saved: %s (sha256: %s)", artifact_path, checksum[:16])
        except OSError as exc:
            logger.error("Failed to write artifact: %s", exc)
            return None, None

        return artifact_path, checksum

    # ------------------------------------------------------------------
    # Warehouse recording (ml.* metadata tables, optional auxiliary)
    # ------------------------------------------------------------------

    def record_to_db(
        self,
        conn: Any,
        result: TrainingResult,
        *,
        experiment_name: str,
        dataset_name: str,
        model_type: str = "gradient_boosting",
    ) -> dict[str, Any]:
        """Records a successful training run in the ml.* metadata tables.

        Auxiliary bookkeeping: artifact files + sidecar JSON remain the source
        of truth for the registry. This only mirrors lineage (datasets,
        experiment, model version, metrics) into the approved ml.* schema so
        status surfaces and APIs can read it. Model bytes are NEVER stored in
        the DB — artifact_location is a relative path string.

        All statements are parameterized (no dynamic SQL). Commits on success,
        rolls back and raises on failure.
        """
        if not result.success or result.artifact is None:
            raise ValueError("record_to_db requires a successful TrainingResult")
        if model_type not in (
            "baseline", "gradient_boosting", "linear_regression",
            "logistic_regression", "random_forest", "xgboost",
            "lightgbm", "neural_network", "other",
        ):
            raise ValueError(f"model_type {model_type!r} violates the ml.model_versions CHECK")

        artifact = result.artifact
        bounds = artifact.split_bounds or {}
        synthetic_note = (
            " SYNTHETIC test-only run: must never count toward production maturity."
            if artifact.is_synthetic_test else ""
        )

        cur = conn.cursor()
        try:
            dataset_keys: dict[str, str] = {}
            for role, flag_col, rows in (
                ("train", "is_training", artifact.train_rows),
                ("validation", "is_validation", artifact.val_rows),
                ("test", "is_test", artifact.test_rows),
            ):
                role_bounds = bounds.get(role, {}) if isinstance(bounds, dict) else {}
                cur.execute(
                    "INSERT INTO ml.datasets (dataset_name, version_str, description, "
                    "source, time_range_start, time_range_end, row_count, "
                    "feature_count, data_maturity, "
                    + flag_col + ") "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'ready', TRUE) "
                    "RETURNING dataset_key;",
                    (
                        dataset_name,
                        f"{artifact.model_version}-{role}",
                        f"{role} partition of {dataset_name}.{synthetic_note}",
                        "public.station_observations",
                        role_bounds.get("start") or artifact.dataset_earliest,
                        role_bounds.get("end") or artifact.dataset_latest,
                        rows,
                        len(artifact.feature_names),
                    ),
                )
                dataset_keys[role] = str(cur.fetchone()[0])

            cur.execute(
                "INSERT INTO ml.experiments (experiment_name, description, dataset_key, "
                "status, started_at, completed_at) "
                "VALUES (%s, %s, %s, 'completed', %s, %s) "
                "RETURNING experiment_key;",
                (
                    experiment_name,
                    f"Busy-time forecasting ({model_type}).{synthetic_note}",
                    dataset_keys["train"],
                    artifact.training_started_at,
                    artifact.training_completed_at,
                ),
            )
            experiment_key = str(cur.fetchone()[0])

            ready = artifact.model_beats_baseline is True
            cur.execute(
                "INSERT INTO ml.model_versions (experiment_key, version_str, model_type, "
                "status, data_maturity, trained_at, completed_at, artifact_location, "
                "training_dataset_key, eval_dataset_key) "
                "VALUES (%s, %s, %s, %s, 'ready', %s, %s, %s, %s, %s) "
                "RETURNING model_key;",
                (
                    experiment_key,
                    artifact.model_version,
                    model_type,
                    "ready" if ready else "validation",
                    artifact.training_started_at,
                    artifact.training_completed_at,
                    artifact.artifact_path,
                    dataset_keys["train"],
                    dataset_keys["validation"],
                ),
            )
            model_key = str(cur.fetchone()[0])

            metrics: list[tuple[str, Optional[float], str]] = [
                ("baseline_mae", artifact.baseline_mae, "validation"),
                ("baseline_rmse", artifact.baseline_rmse, "validation"),
                ("mae", artifact.model_mae, "validation"),
                ("rmse", artifact.model_rmse, "validation"),
                ("mae", artifact.model_mae_test, "test"),
            ]
            for name, value, split in metrics:
                cur.execute(
                    "INSERT INTO ml.metrics (model_key, metric_name, metric_value, split) "
                    "VALUES (%s, %s, %s, %s);",
                    (model_key, name, value, split),
                )

            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                cur.close()
            except Exception:
                pass

        logger.info(
            "Recorded training %s in ml.* (experiment=%s model=%s)",
            artifact.model_version, experiment_key, model_key,
        )
        return {
            "ok": True,
            "experiment_key": experiment_key,
            "model_key": model_key,
            "dataset_keys": dataset_keys,
        }
