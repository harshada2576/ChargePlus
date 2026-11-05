"""ChargePlus — ML Operator CLI.

Phase: 5/6 (Data Mining, Forecasting & Recommendations)

Safe manual execution for training, inference, and status:

    # Gate + registry status (observations file optional; absent = COLD)
    python -m backend.ml.cli status --artifact-dir backend/ml/artifacts

    # Train on a real-evidence export (gate enforced; fails closed when COLD)
    python -m backend.ml.cli train --observations-json obs.json --data-kind real

    # Train on explicitly synthetic fixtures (artifact permanently test-only)
    python -m backend.ml.cli train --observations-json synth.json --data-kind synthetic

    # Single prediction (used by the Next.js /api/ml/predict route)
    python -m backend.ml.cli predict --features '{"hour_of_day":18,...}' \\
        --latest-observation-at 2026-10-11T12:00:00+00:00

Observations JSON shape: [{"station_id": str, "observed_at": ISO-8601,
"availability_status": "available|busy|broken|unknown", "connector_count": int?}]

Never prints secrets. Never manufactures evidence: --data-kind is required
and synthetic runs are permanently marked test-only (registry refuses them).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

logging.basicConfig(level=logging.WARNING)

from backend.ml.gates import MLUnavailableReason  # noqa: E402
from backend.ml.inference import InferenceService  # noqa: E402
from backend.ml.registry import ModelRegistry  # noqa: E402
from backend.ml.training import MLTrainingPipeline  # noqa: E402


def _load_observations(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"Observations file must contain a JSON list: {path}")
    return data


def _cmd_status(args: argparse.Namespace) -> int:
    registry = ModelRegistry(args.artifact_dir)
    service = InferenceService(registry)
    observations = _load_observations(args.observations_json)
    print(json.dumps(service.status(observations), indent=2, default=str))
    return 0


def _cmd_train(args: argparse.Namespace) -> int:
    observations = _load_observations(args.observations_json)
    pipeline = MLTrainingPipeline(artifact_dir=args.artifact_dir)
    result = pipeline.train(
        observations,
        is_synthetic_test=(args.data_kind == "synthetic"),
    )
    payload: dict[str, Any] = {
        "success": result.success,
        "gate": result.gate_result.to_dict(),
        "errors": result.errors,
        "warnings": result.warnings,
        "artifact": result.artifact.to_dict() if result.artifact else None,
    }

    db_info: dict[str, Any] = {"recorded": False}
    if result.success and args.record_to_db:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            payload["db_recording"] = {"recorded": False, "error": "DATABASE_URL not set"}
        else:
            try:
                import psycopg2  # type: ignore
            except ImportError:
                payload["db_recording"] = {
                    "recorded": False, "error": "psycopg2 not installed",
                }
            else:
                conn = psycopg2.connect(database_url)
                try:
                    db_info = pipeline.record_to_db(
                        conn, result,
                        experiment_name=args.experiment_name,
                        dataset_name=args.dataset_name,
                    )
                    db_info["recorded"] = True
                finally:
                    conn.close()
                payload["db_recording"] = db_info
    print(json.dumps(payload, indent=2, default=str))
    return 0 if result.success else 1


def _cmd_predict(args: argparse.Namespace) -> int:
    try:
        features = json.loads(args.features)
    except ValueError as exc:
        print(json.dumps({"success": False, "reason": "FEATURE_SCHEMA_MISMATCH",
                          "message": f"features is not valid JSON: {exc}"}))
        return 2
    registry = ModelRegistry(args.artifact_dir)
    service = InferenceService(registry)
    as_of = None
    if args.as_of:
        try:
            as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    result = service.predict(
        features,
        latest_observation_at=args.latest_observation_at,
        as_of=as_of,
    )
    print(json.dumps(result.to_dict(), indent=2))
    # Unavailable predictions are valid answers, not CLI failures.
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChargePlus ML operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--artifact-dir", default="backend/ml/artifacts",
            help="Model artifact directory (registry root)",
        )

    p_status = sub.add_parser("status", help="Gate + active-model status as JSON")
    add_common(p_status)
    p_status.add_argument("--observations-json", default=None)
    p_status.set_defaults(func=_cmd_status)

    p_train = sub.add_parser("train", help="Train on an observations export")
    add_common(p_train)
    p_train.add_argument("--observations-json", required=True)
    p_train.add_argument(
        "--data-kind", required=True, choices=("real", "synthetic"),
        help="'real' for genuine observation exports; 'synthetic' permanently "
             "marks the artifact test-only (never promotable to production).",
    )
    p_train.add_argument("--record-to-db", action="store_true",
                         help="Mirror lineage into ml.* (needs DATABASE_URL env)")
    p_train.add_argument("--experiment-name", default=None)
    p_train.add_argument("--dataset-name", default="station_busy_forecast")
    p_train.set_defaults(func=_cmd_train)

    p_predict = sub.add_parser("predict", help="Single P(busy) prediction as JSON")
    add_common(p_predict)
    p_predict.add_argument("--features", required=True)
    p_predict.add_argument("--latest-observation-at", default=None)
    p_predict.add_argument("--as-of", default=None)
    p_predict.set_defaults(func=_cmd_predict)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) == "train" and args.record_to_db:
        if not args.experiment_name:
            args.experiment_name = (
                f"busy_forecast_{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            )
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(json.dumps({"success": False, "error": f"File not found: {exc}"}))
        return 2
    except ValueError as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
