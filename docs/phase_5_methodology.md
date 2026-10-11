# ChargePlus — Phase 5 Methodology (Steps 5.2–5.10)

Warehouse is COLD with zero temporal target events. Phase 5 therefore
establishes **methodology, contracts, gates, and tests** that activate
naturally when real evidence arrives. No model is trained, no prediction
is served, no synthetic production data exists.

## Modules (`backend/ml/`, stdlib only — no new dependencies)

| Module | Step | Contents |
|---|---|---|
| `gates.py` | all | Gates A–I evaluation over a 5.1 maturity report; `TASK_SPECS` for the six roadmap tasks |
| `baselines.py` | 5.2 | `BASELINE_SPECS` (target/baseline/inputs/metric/split/evidence gate); guarded metrics (accuracy, macro-F1, MAE/RMSE/MedAE, MAPE-zero-guard, MASE); Majority/Median/LastKnown predictors; chronological split; baseline comparison |
| `features.py` | 5.3 | Static extraction (unknowns stay None); temporal features (empty history → None); SCD2 version-at-time resolution; train-fit-only `MeanImputer`; `FEATURE_DEFINITIONS` in `ml.features` registry vocabulary |
| `datasets.py` | 5.4 | Gated builder: no target events → blocked artifact with reason, zero rows; chronological splits; full provenance |
| `models.py` | 5.5 | `train_gated`: refuses unless gates + dataset pass; simple majority/median models; split metrics + baseline comparison |
| `forecasting.py` | 5.6 | `FORECAST_SPECS` (horizon/frequency/cutoff/windows); seasonal-naive (None when short); cutoff windowing with tz enforcement |
| `anomaly.py` | 5.7 | z-score / IQR / stable-run-change detectors; ≥10-point reference minimum; single records never flagged |
| `recommendations.py` | 5.8 | Transparent additive scorer (compatibility, distance, known fast power); unknowns neutral + explained; prediction signals marked NO_MODEL; radius exclusion, not down-rank |
| `registry.py` | 5.9 | Writers for `ml.features/datasets/experiments/model_versions/metrics` honoring CHECK vocabularies (incl. ready-requires-warming rule); no secrets, no bytes, no predictions stored |
| `inference.py` | 5.10 | `Prediction` contract (VALUE vs NOT_AVAILABLE/INSUFFICIENT_DATA/STALE/NO_MODEL); unavailability never becomes 0 or station-unavailable; product-claim mapping |

## Evidence gates (all currently failing live → DO NOT TRAIN)

A, B, C, D, F mandatory (target, depth ≥30, dates ≥14, entities, chronological split);
E/G/H methodology-always; I usefulness declared per task.

## Leakage posture

Version-at-time joins (never `is_current` on history); moderation as load-gate only;
no connector backfill; daily cells from same-day-or-earlier facts; chronological
splits; OCM operational status never a label.

## Activation rule

When `python -m backend.warehouse.maturity` reports a station reaching WARMING
with a real target, re-run gates: training unlocks per task, baselines first,
comparison mandatory, registry records everything, inference stays contract-bound.
