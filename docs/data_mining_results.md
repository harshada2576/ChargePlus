# ChargePlus: Data Mining Empirical Evaluation & Results

## 1. Executive Summary of Experimental Results

All experiments documented herein are strictly reproducible using the codebase and canonical datasets in the repository.

| Mining Task | Target Dataset | Algorithm / Metric | Key Output / Metric | Data Provenance |
| :--- | :--- | :--- | :--- | :--- |
| **Spatial Density** | 541 Real Stations (India Snapshot) | DBSCAN (Haversine $\epsilon=2.0\text{km}$, $\text{min\_samples}=3$) | **24 Clusters**, 114 Clustered, 427 Noise | Verified Open Charge Map Data |
| **Station Isolation** | 541 Real Stations (India Snapshot) | Pairwise Haversine k-NN ($>5.0\text{km}$) | **254 Isolated Stations**, 17 Extreme Outliers | Verified Open Charge Map Data |
| **Operational Grouping**| Canonical Station Subset | K-Means ($K=3$, Scaled Features) | 3 Centroid Archetypes ($K=3$) | Offline Experiment (Synthetic Demand) |
| **Occupancy Regression**| 17,280 Time-Series Steps | Random Forest (Chronological 80/20) | MAE: **0.2562**, RMSE: **0.3139**, $R^2$: **0.3956** | Synthetic Poisson/Gaussian Simulation |
| **Naive Baseline** | 17,280 Time-Series Steps | Train Hour-Mean Predictor | MAE: **0.2632**, RMSE: **0.3177** | Baseline Benchmark |
| **Production Gate** | Live Prediction Route | Telemetry Maturity Invariant | State: **COLD (Fail-Closed)** | Active Production Safety Guard |

---

## 2. Spatial Clustering Empirical Findings (DBSCAN)

### 2.1 Input Dataset Scope & Provenance
- **Dataset File:** `artifacts/chargeplus-real-dataset/stations.csv`
- **Source Snapshot:** Open Charge Map India Snapshot (`raw_snapshot_india.json`, CC BY 4.0)
- **Total Valid Stations:** 541 (100% valid WGS-84 coordinates)
- **Geographic Coverage:** 20 Indian states, 293 cities
  - Top States: Karnataka (176), Tamil Nadu (99), Kerala (81), Maharashtra (79), Delhi (23), Gujarat (20), Goa (6).
  - Latitude Range: $8.1154^{\circ}\text{N}$ to $32.8866^{\circ}\text{N}$
  - Longitude Range: $70.1167^{\circ}\text{E}$ to $88.4563^{\circ}\text{E}$

### 2.2 Clustering Statistics (Haversine Metric, $\epsilon=2.0\text{ km}$, $\text{min\_samples}=3$)
- **Total Stations Evaluated:** 541
- **Clustered Core Stations:** 114 (21.07%)
- **Spatial Noise Points:** 427 (78.93%)
- **Identified Clusters:** 24 discrete spatial clusters

### 2.3 Representative Cluster Profiles

| Cluster ID | Station Count | Centroid Lat, Lng | Radius | Primary Location & Sample Stations |
| :--- | :--- | :--- | :--- | :--- |
| **Cluster #0** | 8 | $18.61^{\circ}\text{N}, 73.75^{\circ}\text{E}$ | $1.73\text{ km}$ | Pune / Pimpri-Chinchwad corridor (Gaurav Icon Tower, MG Motor Showroom) |
| **Cluster #1** | 4 | $17.99^{\circ}\text{N}, 73.99^{\circ}\text{E}$ | $1.50\text{ km}$ | Satara, Maharashtra (Hotel Aram Regency, Hotel Ashirwad Inn) |
| **Cluster #2** | 5 | $16.70^{\circ}\text{N}, 74.25^{\circ}\text{E}$ | $2.07\text{ km}$ | Kolhapur, Maharashtra (Reliance Mall, Kolhapur Railway Station) |
| **Cluster #3** | 6 | $18.56^{\circ}\text{N}, 73.78^{\circ}\text{E}$ | $2.20\text{ km}$ | Pune Baner / Sus Road corridor (Shell Recharge Sus Road, B4S Baner) |
| **Cluster #4** | 4 | $9.93^{\circ}\text{N}, 76.32^{\circ}\text{E}$ | $1.47\text{ km}$ | Kochi / Ernakulam, Kerala (Nucleus Mall EVCS, Crowne Plaza EVCS) |
| **Cluster #6** | 6 | $28.63^{\circ}\text{N}, 77.22^{\circ}\text{E}$ | $1.43\text{ km}$ | Central Delhi / Connaught Place (EESL Devinder Collections, Le Méridien) |
| **Cluster #8** | 4 | $12.35^{\circ}\text{N}, 76.63^{\circ}\text{E}$ | $1.23\text{ km}$ | Mysuru, Karnataka (Hotel Arcore, Ganapati Fuel Station) |
| **Cluster #9** | 5 | $11.01^{\circ}\text{N}, 76.98^{\circ}\text{E}$ | $2.16\text{ km}$ | Coimbatore, Tamil Nadu (Zibe GRT Hotels, Ibis Coimbatore) |

---

## 3. Station Isolation & Outlier Analysis

- **Isolation Threshold:** Nearest-neighbor Haversine distance $d_{\text{min}} > 5.0\text{ km}$.
- **Isolated Stations in Snapshot:** **254 stations (46.95%)** have no neighboring station within 5 km in this snapshot.
- **Extreme Isolation Outliers (IQR Tukey Fences):** 17 stations exceed the upper Tukey fence ($Q_3 + 1.5 \times IQR \approx 75.4\text{ km}$; observed range $75.9\text{ km} - 254.8\text{ km}$).
- **Sampled Most Isolated Stations:** 25 stations recorded in the artifact sample ($60.9\text{ km} - 254.8\text{ km}$).
- **Notable Isolated Stations:**
  - *Tata EV Fast Charging - Lexican Motors, Siliguri* ($254.8\text{ km}$ nearest recorded neighbor)
  - *Electrify Bihar EV Charging Station* ($238.9\text{ km}$ nearest recorded neighbor)
  - *Khajuraho Airport, Madhya Pradesh* ($240.2\text{ km}$ nearest recorded neighbor)
- **Academic Limitation Notice:** These metrics measure isolation relative to the *recorded Open Charge Map dataset snapshot*. They indicate network sparsity within this open directory rather than establishing an exhaustive census of all real-world commercial charging infrastructure.

---

## 4. Occupancy Regression Empirical Findings

### 4.1 Dataset Provenance & Synthesis Notice
> **IMPORTANT ACADEMIC DISCLOSURE:** The regression experiment was evaluated on 17,280 time-series observation steps generated via `backend/ingestion/seed_observations.py` modeling diurnal Poisson/Gaussian charging events across 12 canonical stations over a 60-day interval (15-minute sampling). This demonstrates machine learning methodology, chronological train/test discipline, and feature attribution, but is **not** validated against live Indian CPO smart-meter hardware.

### 4.2 Comparative Evaluation Matrix

| Evaluation Methodology | Train Split ($N$) | Test Split ($N$) | Baseline MAE | Model MAE | Model RMSE | Model $R^2$ | Improvement |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Honest Chronological Split** | 13,824 (80%) | 3,456 (20%) | **0.2632** | **0.2562** | **0.3139** | **0.3956** | **+2.66%** |
| **Legacy Random Split (Reproduced)** | 13,824 (80%) | 3,456 (20%) | **0.2655** | **0.2565** | **0.3133** | **0.4105** | **+3.38%** (leaked) |

### 4.3 Feature Importance Breakdown (Random Forest Gini Impurity)

| Feature | Gini Importance | Interpretation |
| :--- | :--- | :--- |
| **`hour`** | **89.99%** | Diurnal cycle dominates demand curves (morning/evening rush hours). |
| **`is_commercial_hub`** | **4.42%** | Stations in corporate zones experience elevated daytime charging. |
| **`day_of_week`** | **3.20%** | Weekly business vs leisure charging divergence. |
| **`total_connectors`** | **1.59%** | Multi-bay stations buffer queue overflow. |
| **`is_weekend`** | **0.79%** | Weekend transit pattern alteration. |

### 4.4 Academic Critique of Feature Distribution
The overwhelming dominance of `hour` (89.99%) is an artifact of the synthetic observation generator, which models diurnal commute spikes using mathematical distributions. In real-world empirical charging telemetry:
- Traffic congestion, dynamic electricity tariffs, weather extremes, and charger downtime introduce substantially higher stochasticity.
- A production model on real telemetry would exhibit distributed importance across weather and pricing features.

---

## 5. Production Maturity & Fail-Closed Guard

Because genuine live streaming telemetry is not currently connected:
1. `GET /api/ml/status` and `GET /api/intelligence` return status **`COLD`**.
2. Prediction serving is intentionally **DISABLED**.
3. No hallucinated occupancy percentages are served to end users.
4. Offline experiment results are served strictly as verified historical research benchmarks.
