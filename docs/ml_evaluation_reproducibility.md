# Machine Learning Evaluation, Provenance & Reproducibility Report

## Executive Summary

ChargePlus utilizes machine learning for two analytical objectives:
1. **Unsupervised Spatial Demand Clustering**: Grouping Mumbai EV charging locations via K-Means ($k=3$) to identify high-density transit corridors, suburban commercial hubs, and peripheral catchment areas.
2. **Supervised Congestion Forecasting**: Predicting connector occupancy ratio ($0.0 \dots 1.0$) via Random Forest Regressor to forecast queuing bottlenecks and schedule proactive dispatching.

This report establishes **deterministic offline reproducibility**, audits historical metrics, documents data provenance, and enforces strict production model governance.

---

## 1. Dataset Provenance, Schema & Limitations

| Attribute | Specification |
| :--- | :--- |
| **Files** | `data/canonical_stations.json`, `data/observations.json` |
| **Row Count** | 12 canonical stations, 8,640 hourly observations (30 days $\times$ 24 hours $\times$ 12 stations) |
| **Licence / Origin** | Generated via deterministic synthetic Poisson/Gaussian process (`backend/ingestion/seed_observations.py`) anchored on Mumbai geographic coordinates |
| **Observation Schema** | `station_id` (str), `observed_at` (ISO 8601), `hour` (0–23), `day_of_week` (0–6), `is_weekend` (0/1), `total_connectors` (int), `available_connectors` (int) |
| **Target Variable** | `occupancy_ratio = (total_connectors - available_connectors) / total_connectors` |
| **Data Limitations** | Synthetically generated demonstration data. Contains Gaussian noise and simulated diurnal traffic spikes. **Not verified against live Indian CPO hardware.** |

---

## 2. Feature Engineering & Target Definition

- **Target**: `occupancy_ratio` $\in [0.0, 1.0]$.
- **Features**:
  - `hour`: Diurnal traffic signal (accounts for 90.0% of feature importance).
  - `is_commercial_hub`: Binary indicator flag identifying high-demand commercial clusters (Bandra Kurla Complex, Mumbai Airport, Lower Parel).
  - `day_of_week`: Day of the week (0 = Monday, 6 = Sunday).
  - `total_connectors`: Physical station capacity.
  - `is_weekend`: Weekend indicator flag.
- **Missing Value Handling**: Neutral fallback defaults are applied (`hour=12`, `day_of_week=0`, `is_weekend=0`, `total_connectors=4`).

---

## 3. Train / Test Methodology & Leakage Audit

### Audit of Historical Metrics ($R^2 = 0.4105, \text{MAE} = 0.2565$)
An inspection of the original `backend/ml/demand_mining.py` revealed two critical data leakages:
1. **Temporal Leakage**: Used `train_test_split(..., test_size=0.2, random_state=42)` on time-series observations. Shuffling observations across timestamps caused past hours to be predicted using future data and vice versa.
2. **Target Leakage in Baseline**: The historical baseline lookup (`df_obs.groupby("hour")["occupancy_ratio"].mean()`) was computed across the *entire* dataset including the test set.

### Honest Chronological Evaluation
To eliminate leakage, the updated evaluation pipeline provides two distinct benchmarks:
- **Chronological Split**: First 80% of timestamps (days 1–24, 6,912 records) form the training set; final 20% of timestamps (days 25–30, 1,728 records) form the test set.
- **Train-Only Baseline**: The naive hourly mean baseline is calculated strictly on the training partition.

---

## 4. Empirical Evaluation Results

| Benchmark | Split Type | Naive Baseline MAE | Random Forest MAE | Random Forest RMSE | $R^2$ Score | Error Reduction | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Legacy Leaked Benchmark** | Random Shuffle ($80/20$) | $0.2655$ | **$0.2565$** | $0.3133$ | **$0.4105$** | $3.4\%$ | Exact reproduction of historical claim; suffers from temporal shuffle leakage. |
| **Honest Chronological Benchmark** | Chronological ($80/20$) | $0.2632$ | **$0.2562$** | $0.3139$ | **$0.3956$** | $2.7\%$ | Zero temporal leakage; naive baseline trained solely on training partition. |

### Feature Importance (Honest Model):
- `hour`: 90.0%
- `is_commercial_hub`: 4.4%
- `day_of_week`: 3.2%
- `total_connectors`: 1.6%
- `is_weekend`: 0.8%

---

## 5. Production Model Lifecycle & Governance

ChargePlus enforces a fail-closed production model lifecycle governed by `backend/ml/gates.py`:
$$\text{COLD} \longrightarrow \text{WARMING} \longrightarrow \text{READY}$$

### Production Gating Invariants:
1. **Synthetic Data Prohibition**: Synthetic data **NEVER** counts toward production data maturity.
2. **Current State**: Production warehouse currently possesses 0 verified real-world CPO observation events.
3. **Fail-Closed Gate**: `evaluate_gate` returns `DataMaturityState.COLD` and `MLUnavailableReason.DATA_MATURITY_COLD`.
4. **Offline Isolation**: Running `demand_mining.py` generates demonstration reports in `data/ml/` but does **NOT** register or promote models in the production registry. Production API endpoints fail closed with typed unavailable responses rather than serving fabricated predictions.

---

## 6. How to Reproduce Locally

Run the complete pipeline deterministically with a single command:
```powershell
python backend/ml/demand_mining.py
```

Generated machine-readable artifacts:
- `data/ml/mining_summary.json`: Backward-compatible summary metrics.
- `data/ml/offline_evaluation_report.json`: Comprehensive report containing metadata, provenance, legacy and honest benchmarks, feature importance, and 20-sample actual-versus-predicted comparisons.
