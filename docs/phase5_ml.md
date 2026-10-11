# Phase 5 ML — Training, Artifacts, Inference & Operations

Complements `db+warehouse+ml.md` (schema/design) with the implemented runtime:
`backend/ml/{gates,training,registry,inference,cli}.py`, the file-based
approved-model registry, and the `/api/ml/*` routes.

## Current state (2026-10)

**Code: complete. Production inference: legitimately disabled.** The live
database holds ~0 real station observations (COLD maturity), so the gate
refuses training and inference answers `NO_MODEL`. No model is approved, no
prediction is served, and station discovery is unaffected. This is the
designed fail-closed behavior — not a defect.

## Maturity gate (`gates.py`)

Authoritative thresholds (`MLGateConfig`, do not lower to force a pass):

| Requirement | READY | WARMING |
|---|---|---|
| Total real observations | ≥ 500 | ≥ 50 |
| Stations with observations | ≥ 5 | ≥ 2 |
| Calendar days covered | ≥ 30 | ≥ 7 |
| Min observations / station | ≥ 50 | — |
| Latest observation age | ≤ 72h | ≤ 72h |

Rules: exact `(station_id, observed_at)` duplicates count once (double-ingest
is not evidence); invalid timestamps are skipped with notes; inverted time
bounds fail as integrity errors; synthetic data never counts (it never
reaches the gate — see below).

## Training (`training.py` + `cli.py train`)

- Features (locked `v1` schema): `hour_of_day, day_of_week, is_weekend,
  month, station_connector_count`. Target: `is_busy`.
- Chronological 70/15/15 train/validation/test splits — never random (test
  `test_13_no_temporal_leakage` proves future labels cannot leak).
- Baseline first: median per (hour, weekday); the model must beat it on
  validation to be promotable without a recorded override.
- Missing counts impute from training medians (documented model-input
  fallback, never a stored fact); an entirely-missing feature falls back to
  0.0 with a loud warning.
- Overlapping runs are refused (`training.lock`, stale locks reclaimed after
  2h → `TRAINING_IN_PROGRESS`).
- `--data-kind` is required: `real` for genuine exports, `synthetic` for
  fixtures (artifact permanently marked test-only; the registry refuses it).

```bash
python -m backend.ml.cli status --artifact-dir backend/ml/artifacts
python -m backend.ml.cli train --observations-json obs.json --data-kind real
python -m backend.ml.cli train --observations-json obs.json --data-kind real \
  --record-to-db --experiment-name busy_forecast_20261011   # needs DATABASE_URL
```

`--record-to-db` mirrors lineage into the approved `ml.*` schema (datasets →
experiment → model_version → metrics). Model bytes are never stored in the DB.

## Artifacts & promotion (`registry.py`)

- Artifacts: `model_<version>.pkl` + `.json` sidecar (config, lineage,
  metrics, sha256) under `ML_ARTIFACT_DIR` (default
  `backend/ml/artifacts/`).
- `approve()` requires: checksum verification, locked-schema compatibility,
  non-synthetic (unless an explicit test registry), baseline beaten or a
  recorded override reason. Approval rewrites the sidecar atomically, appends
  the audit log, and moves the single active pointer.
- `rollback()` re-points to the previously approved version. A stale pointer
  (missing/invalid/unapproved bytes) degrades to `NO_MODEL`.
- Paths are contained in the artifact directory; `..`/absolute paths refused.
  Verification precedes every unpickle — unverified bytes are never loaded.

## Inference (`inference.py`, `/api/ml/*`)

Per prediction: active approved model → freshness check (≤72h, verifiable) →
locked-schema validation → verified load → scoring → finite [0,1] output
check. Any failure returns a typed refusal (`NO_MODEL`,
`INSUFFICIENT_HISTORY`, `STALE_FEATURES`, `FEATURE_SCHEMA_MISMATCH`,
`MODEL_ARTIFACT_INVALID`) with remediation text. Results carry model version,
timestamp, input cutoff, and horizon (`current`); predictions are returned,
never stored in observation tables.

- `GET /api/ml/status` — gate state + active model (read-only, server-side).
- `POST /api/ml/predict` — validates input, shells to the Python CLI with a
  20s timeout, passes the typed result through. 400 on bad input, 503 with
  `NO_MODEL` when the backend is unavailable. No UI depends on it.

## Spatial Density Clustering & Coverage Gaps (`spatial_clustering.py`)

- **Algorithm**: Density-Based Spatial Clustering of Applications with Noise (DBSCAN).
- **Distance Metric**: Great-circle spherical Haversine metric ($R = 6371.0088\text{ km}$). No naive Euclidean approximations on latitude/longitude degrees.
- **Corridor Discovery**: Groups geographically dense charging hubs (`eps_km=5.0`, `min_samples=2`), calculating cluster centroids, bounding boxes, and cluster radii.
- **Coverage Gap Mining (`find_coverage_gaps`)**: Nearest-neighbor geodesic distance algorithm evaluating isolation distance in kilometers to flag underserved areas and pioneer stations requiring network expansion.
- **Tests**: `tests/test_spatial_clustering.py` (5 tests covering empty edge cases, Mumbai landmark distance validations, and canonical Mumbai stations dataset).

## What unlocks production ML (real-data checklist)

1. Live observation history: ≥500 real observations across ≥5 stations over
   ≥30 days, fresh (≤72h), via OCM/CPO telemetry ingestion.
2. `train --data-kind real` succeeds (gate READY) with evaluation metrics.
3. `record-to-db` lineage recorded; operator reviews metrics.
4. `registry.approve()` by a named approver (override reason if the model
   does not beat baseline).
5. `/api/ml/status` reports `inference_available: true`.

Until all five hold, any "ML ready" claim is false. The code is done; the
data is not — and the system says so explicitly.
