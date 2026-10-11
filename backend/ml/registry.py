"""ChargePlus — ML metadata registry writers (Phase 5/6, Step 5.9).

Writes ONLY to ml.* (control/metadata layer): features, datasets,
experiments, model_versions, metrics. Never stores model bytes, secrets,
or predictions. Status transitions respect the schema CHECK vocabularies.
Invoked only when a real training event occurs; with no evidence there is
nothing to register.
"""

from __future__ import annotations

from typing import Any, Optional

MODEL_TYPES = {"baseline", "gradient_boosting", "linear_regression",
               "logistic_regression", "random_forest", "xgboost",
               "lightgbm", "neural_network", "other"}
MODEL_STATUSES = {"proposed", "training", "validation", "ready", "archived", "deprecated"}
EXPERIMENT_STATUSES = {"proposed", "running", "completed", "failed"}
DATA_MATURITY = {"cold", "warming", "ready"}
METRIC_SPLITS = {"train", "validation", "test", "holdout"}


def _one(cur: Any) -> Optional[tuple]:
    row = cur.fetchone()
    return tuple(row) if row is not None else None


def register_feature(cur: Any, name: str, feature_type: str, feature_group: str,
                     description: str = "", source_column: Optional[str] = None,
                     formula: Optional[str] = None, generated_by: str = "raw_attribute") -> str:
    cur.execute(
        "INSERT INTO ml.features (feature_name, feature_type, feature_group, description,"
        " source_column, formula, generated_by) VALUES (%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (feature_name) DO UPDATE SET description = EXCLUDED.description,"
        " updated_at = now() RETURNING feature_key;",
        (name, feature_type, feature_group, description, source_column, formula, generated_by),
    )
    row = _one(cur)
    if not row:
        raise RuntimeError(f"register_feature returned no key for '{name}'")
    return str(row[0])


def register_dataset(cur: Any, name: str, version: str, time_start: Any, time_end: Any,
                     row_count: int, feature_count: int, maturity: str = "cold",
                     role: str = "training") -> str:
    flags = {"is_training": role == "training", "is_validation": role == "validation",
             "is_test": role == "test"}
    if role not in ("training", "validation", "test"):
        raise ValueError(f"unknown dataset role '{role}'")
    if maturity not in DATA_MATURITY:
        raise ValueError(f"unknown data_maturity '{maturity}'")
    cur.execute(
        "INSERT INTO ml.datasets (dataset_name, version_str, time_range_start, time_range_end,"
        " row_count, feature_count, data_maturity, is_training, is_validation, is_test)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (dataset_name, version_str) DO UPDATE SET row_count = EXCLUDED.row_count,"
        " feature_count = EXCLUDED.feature_count, data_maturity = EXCLUDED.data_maturity,"
        " updated_at = now() RETURNING dataset_key;",
        (name, version, time_start, time_end, row_count, feature_count, maturity,
         flags["is_training"], flags["is_validation"], flags["is_test"]),
    )
    row = _one(cur)
    if not row:
        raise RuntimeError(f"register_dataset returned no key for '{name}/{version}'")
    return str(row[0])


def register_experiment(cur: Any, name: str, dataset_key: str,
                        description: str = "") -> str:
    cur.execute(
        "INSERT INTO ml.experiments (experiment_name, description, dataset_key)"
        " VALUES (%s,%s,%s)"
        " ON CONFLICT (experiment_name) DO NOTHING RETURNING experiment_key;",
        (name, description, str(dataset_key)),
    )
    row = _one(cur)
    if row:
        return str(row[0])
    cur.execute("SELECT experiment_key FROM ml.experiments WHERE experiment_name = %s;", (name,))
    row = _one(cur)
    if not row:
        raise RuntimeError(f"register_experiment could not resolve '{name}'")
    return str(row[0])


def set_experiment_status(cur: Any, experiment_key: str, status: str) -> None:
    if status not in EXPERIMENT_STATUSES:
        raise ValueError(f"unknown experiment status '{status}'")
    cur.execute("UPDATE ml.experiments SET status = %s, updated_at = now() WHERE experiment_key = %s;",
                (status, str(experiment_key)))


def register_model_version(cur: Any, experiment_key: str, version: str, model_type: str,
                           maturity: str = "cold") -> str:
    if model_type not in MODEL_TYPES:
        raise ValueError(f"unknown model_type '{model_type}'")
    if maturity not in DATA_MATURITY:
        raise ValueError(f"unknown data_maturity '{maturity}'")
    cur.execute(
        "INSERT INTO ml.model_versions (experiment_key, version_str, model_type, data_maturity)"
        " VALUES (%s,%s,%s,%s)"
        " ON CONFLICT (experiment_key, version_str) DO NOTHING RETURNING model_key;",
        (str(experiment_key), version, model_type, maturity),
    )
    row = _one(cur)
    if row:
        return str(row[0])
    cur.execute("SELECT model_key FROM ml.model_versions WHERE experiment_key = %s AND version_str = %s;",
                (str(experiment_key), version))
    row = _one(cur)
    if not row:
        raise RuntimeError("register_model_version could not resolve key")
    return str(row[0])


def set_model_status(cur: Any, model_key: str, status: str) -> None:
    """Enforces the schema rule: 'ready' requires warming/ready maturity."""
    if status not in MODEL_STATUSES:
        raise ValueError(f"unknown model status '{status}'")
    if status == "ready":
        cur.execute("SELECT data_maturity FROM ml.model_versions WHERE model_key = %s;",
                    (str(model_key),))
        row = _one(cur)
        if not row or str(row[0]) not in ("warming", "ready"):
            raise ValueError("model cannot be ready without warming/ready data maturity")
    cur.execute("UPDATE ml.model_versions SET status = %s, updated_at = now() WHERE model_key = %s;",
                (status, str(model_key)))


def record_metric(cur: Any, model_key: str, name: str, value: Optional[float],
                  split: str) -> None:
    if split not in METRIC_SPLITS:
        raise ValueError(f"unknown metric split '{split}'")
    cur.execute(
        "INSERT INTO ml.metrics (model_key, metric_name, metric_value, split)"
        " VALUES (%s,%s,%s,%s)"
        " ON CONFLICT (model_key, metric_name, split) DO UPDATE SET"
        " metric_value = EXCLUDED.metric_value, updated_at = now();",
        (str(model_key), name, value, split),
    )
