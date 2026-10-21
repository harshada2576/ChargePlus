# ChargePlus: Data Mining Empirical Evaluation & Results

## 1. Executive Summary of Experimental Results

All experiments documented herein are strictly reproducible using the codebase and canonical datasets in the repository.

| Mining Task | Target Dataset | Algorithm / Metric | Key Output / Metric | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Spatial Density** | 541 Real MMR Stations | DBSCAN (Haversine $\epsilon=2.0\text{km}$) | **24 Clusters**, 114 Clustered, 427 Noise | Verified Real Data |
| **Coverage Gaps** | 541 Real MMR Stations | BallTree k-NN Distance ($>5.0\text{km}$) | **254 Gap Stations**, 17 Extreme Outliers | Verified Real Data |
| **Operational Grouping**| Canonical Station Subset| K-Means ($K=3$, Scaled Features) | 3 Centroid Archetypes ($k=3$) | Offline Experiment |
| **Occupancy Regression**| 17,280 Time-Series Steps | Random Forest (Chronological 80/20) | MAE: **0.2562**, RMSE: **0.3139**, $R^2$: **0.3956** | Synthetic Simulation |
| **Naive Baseline** | 17,280 Time-Series Steps | Train Hour-Mean Predictor | MAE: **0.2632**, RMSE: **0.3177** | Baseline Benchmark |
| **Production Gate** | Live Prediction Route | Telemetry Maturity Invariant | State: **COLD (Fail-Closed)** | Active Production Guard |

---

## 2. Spatial Clustering Empirical Findings (DBSCAN)

- **Input Dataset:** `artifacts/chargeplus-real-dataset/stations.csv` (541 stations across MMR).
- **Coordinate Integrity:** 100% valid WGS-84 coordinates (Lat: $18.5^{\circ}\text{N} - 19.5^{\circ}\text{N}$, Lng: $72.7^{\circ}\text{E} - 73.8^{\circ}\text{E}$).
- **Clustering Statistics:**
  - **Total Stations:** 541
  - **Clustered Core Stations:** 114 (21.07%)
  - **Spatial Noise Points:** 427 (78.93%)
  - **Identified Clusters:** 24 distinct geographic hubs

### 2.1 Major Clusters Profile

1. **Cluster #0 (Pimpri-Chinchwad / Pune Corridor):**
   - Station count: 8 stations
   - Centroid: $18.609^{\circ}\text{N}, 73.750^{\circ}\text{E}$
   - Maximum cluster spread: $1.734\text{ km}$
   - Operators: Shell, MG Motor, Independent CPOs
2. **Cluster #1 (Navi Mumbai / Turbhe Industrial Hub):**
   - Station count: 7 stations
   - Centroid: $19.068^{\circ}\text{N}, 73.018^{\circ}\text{E}$
   - Maximum cluster spread: $1.921\text{ km}$
3. **Cluster #2 (Andheri East Commercial District):**
   - Station count: 6 stations
   - Centroid: $19.115^{\circ}\text{N}, 72.871^{\circ}\text{E}$
   - Maximum cluster spread: $1.412\text{ km}$

### 2.2 Coverage Gap Analysis
- **Threshold:** Distance to nearest neighbor charger $> 5.0\text{ km}$.
- **Result:** **254 stations (46.95%)** are isolated beyond 5 km.
- **Extreme Spatial Outliers:** 17 stations exceed $25.0\text{ km}$ isolation from any other charging station.
- **Top Isolated Station:** *Tata EV Fast Charging - Lexican Motors, Siliguri* ($254.8\text{ km}$ to nearest recorded station in regional dataset), pinpointing extreme highway feeder nodes.

---

## 3. Occupancy Regression Empirical Findings

### 3.1 Dataset Provenance & Synthesis Notice
> **IMPORTANT DISCLOSURE:** The regression experiment was trained on 17,280 time-series observation steps generated via `backend/ingestion/seed_observations.py` modeling diurnal Poisson/Gaussian charging events across 12 canonical MMR stations over a 60-day interval. This demonstrates model architecture, train/test discipline, and feature importance, but is not validated against live Indian CPO smart-meter hardware.

### 3.2 Evaluation Comparison Matrix

| Evaluation Methodology | Train Split ($N$) | Test Split ($N$) | Baseline MAE | Model MAE | Model RMSE | Model $R^2$ | Improvement |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Honest Chronological Split** | 13,824 (80%) | 3,456 (20%) | **0.2632** | **0.2562** | **0.3139** | **0.3956** | **+2.66%** |
| **Legacy Random Split (Reproduced)** | 13,824 (80%) | 3,456 (20%) | **0.2655** | **0.2565** | **0.3133** | **0.4105** | **+3.38%** |

### 3.3 Feature Importance Breakdown (Random Forest Gini Impurity)

| Feature | Gini Importance | Interpretation |
| :--- | :--- | :--- |
| **`hour`** | **89.99%** | Diurnal cycle dominates demand curves (morning/evening rush hours). |
| **`is_commercial_hub`** | **4.42%** | Stations in corporate zones experience elevated daytime charging. |
| **`day_of_week`** | **3.20%** | Weekly business vs leisure charging divergence. |
| **`total_connectors`** | **1.59%** | Multi-bay stations buffer queue overflow. |
| **`is_weekend`** | **0.79%** | Weekend transit pattern alteration. |

### 3.4 Academic Critique of Feature Distribution
The overwhelming dominance of `hour` (89.99%) reflects a critical property of the synthetic data generator: synthetic seeds follow an idealized mathematical diurnal distribution. In real-world empirical EV charging:
- Traffic congestion, dynamic electricity tariffs, weather extremes, and charger downtime introduce substantially higher stochasticity.
- A production model on real telemetry would exhibit distributed importance across weather and pricing features.

---

## 4. Production Maturity & Fail-Closed Guard

Because genuine live streaming telemetry is not currently connected to the live database:
1. `GET /api/ml/status` and `GET /api/intelligence` return status **`COLD`**.
2. Prediction serving is intentionally **DISABLED**.
3. No hallucinated occupancy percentages are served to end users.
4. Offline experiment results are served strictly as verified historical research benchmarks.
