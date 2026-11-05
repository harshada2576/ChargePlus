# ChargePlus: Data Mining Methodology & Algorithms

## 1. Problem Formulation & Academic Objectives

The ChargePlus platform demonstrates empirical infrastructure analysis, spatial mining, and demand intelligence across a verified **India nationwide Open Charge Map snapshot** (541 stations across 20 states and 293 cities). While driver-facing applications typically focus on simple nearest-charger searches, this research applies formal **Data Mining (DM)** techniques to achieve five core analytical capabilities:

1. **Spatial Density Clustering:** Discover geographic agglomerations of EV charging infrastructure without assuming convex cluster geometries or predetermining cluster counts.
2. **Station-Isolation Analysis:** Pinpoint geographically isolated charging points relative to other recorded infrastructure in the dataset snapshot.
3. **Operational Profile Partitioning:** Segment charging stations into operational tiers based on capacity, spatial positioning, and synthetic utilization indicators.
4. **Temporal Occupancy Regression & Honest Chronological Evaluation:** Model diurnal charger occupancy, evaluate regression models against temporal naive baselines, and rigorously eliminate data leakage.
5. **Fail-Closed Model Governance:** Ensure unvalidated models and offline experiments never project fabricated numbers to production drivers.

---

## 2. Algorithm 1: Spatial Density Clustering (DBSCAN + Haversine Metric)

### 2.1 Theoretical Rationale
Traditional partitioning algorithms such as K-Means assume spherical, equally sized clusters and require predefining the cluster count ($k$). However, EV charging networks across India naturally follow linear transportation corridors (National Highways such as NH-48, NH-44) and irregular municipal boundaries (Delhi NCR, Bengaluru, Pune, Kochi, Coimbatore, Kolhapur). 

**DBSCAN (Density-Based Spatial Clustering of Applications with Noise)** was selected because:
- It discovers arbitrary-shaped clusters corresponding to real-world commercial districts and highway corridors.
- It explicitly classifies isolated points as **noise / spatial outliers** rather than forcing them into artificial groupings.
- It requires no prior knowledge of cluster count.

### 2.2 Mathematical Distance Formulation
Planar Euclidean distance ($\sqrt{\Delta x^2 + \Delta y^2}$) introduces severe distortion when applied to latitude/longitude coordinates on spherical planetary surfaces. Therefore, ChargePlus implements the **Haversine Great-Circle Distance Metric**:

$$\Delta\sigma = 2 \arcsin \left( \sqrt{\sin^2\left(\frac{\Delta\phi}{2}\right) + \cos\phi_1 \cos\phi_2 \sin^2\left(\frac{\Delta\lambda}{2}\right)} \right)$$

$$d = R \cdot \Delta\sigma$$

Where:
- $\phi_1, \phi_2$ are latitudes in radians.
- $\Delta\phi = \phi_2 - \phi_1$, $\Delta\lambda = \lambda_2 - \lambda_1$.
- $R = 6,371.0088\text{ km}$ (Earth volumetric mean radius).
- The $\epsilon$ neighborhood parameter in radians is given by $\epsilon_{\text{rad}} = \frac{\epsilon_{\text{km}}}{R}$.

### 2.3 Parameter Calibration & Academic Caveats
- **Epsilon ($\epsilon$):** Set to $2.0\text{ km}$. In metropolitan and suburban areas, an EV driver within a 2 km radius has access to alternative local charging or last-mile transit options.
- **MinSamples:** Set to $3$ stations. A cluster must represent a genuine localized charging hub (at least 3 independent stations) rather than an isolated pair.
- **Station-Isolation Threshold:** Set to $5.0\text{ km}$. Stations whose nearest neighbor distance $d_{\text{min}} > 5.0\text{ km}$ are cataloged as isolated stations in the snapshot.
- **Methodological Limitation Note:** Nearest-neighbor distance identifies solitary stations within the *recorded Open Charge Map dataset snapshot*. It does not constitute an exhaustive municipal area census of all Indian commercial charging infrastructure.

---

## 3. Algorithm 2: Station Grouping (K-Means Partitioning)

### 3.1 Objective
To segment stations into distinct operational archetypes to assist urban planners in identifying high-demand corridors versus low-power residential nodes.

### 3.2 Feature Space & Preprocessing
Each station record $i$ is mapped to a normalized 3-dimensional feature vector:
$$\mathbf{x}_i = \begin{bmatrix} \tilde{\phi}_i \\ \tilde{\lambda}_i \\ \tilde{S}_i \end{bmatrix}$$
Where:
- $\tilde{\phi}_i, \tilde{\lambda}_i$ are StandardScaled geographic coordinates.
- $\tilde{S}_i$ is the derived synthetic demand score (0–100) reflecting connector density and simulated peak throughput.

### 3.3 Optimization Objective
$$J = \sum_{k=1}^K \sum_{i \in C_k} \|\mathbf{x}_i - \boldsymbol{\mu}_k\|^2$$
With $K=3$, random state fixed to $42$ for deterministic reproducibility.

---

## 4. Algorithm 3: Chronological Occupancy Regression (Random Forest)

### 4.1 Target Definition & Feature Engineering
- **Target ($y$):** Occupancy ratio $\in [0.0, 1.0]$, representing the proportion of occupied connectors at timestamp $t$.
- **Features ($\mathbf{x}$):**
  - Temporal: `hour` (0–23), `day_of_week` (0–6), `is_weekend` (binary).
  - Infrastructure: `total_connectors`, `is_commercial_hub` (derived from station locality).

### 4.2 Leakage Prevention & Train/Test Splitting
Standard random cross-validation (`train_test_split(shuffle=True)`) creates catastrophic temporal leakage in time-series telemetry: future observations bleed into past training partitions. 

ChargePlus enforces a strict **Chronological Holdout Split**:
- **Train partition:** Earliest 80% chronologically ordered records ($N_{\text{train}} = 13,824$).
- **Test partition:** Final 20% holdout records ($N_{\text{test}} = 3,456$).
- Preprocessing transformers and baseline lookups are fitted strictly on the train partition.

### 4.3 Naive Benchmark Comparison
A regression model is meaningless without demonstrating superior performance over a domain-specific baseline. ChargePlus compares the Random Forest against a **Naive Diurnal Baseline**:
$$\hat{y}_{\text{baseline}}(t) = \bar{y}_{\text{train}}(\text{hour}(t))$$
Evaluation metrics:
$$\text{MAE} = \frac{1}{N} \sum_{i=1}^N |y_i - \hat{y}_i|$$
$$\text{RMSE} = \sqrt{\frac{1}{N} \sum_{i=1}^N (y_i - \hat{y}_i)^2}$$
$$R^2 = 1 - \frac{\sum (y_i - \hat{y}_i)^2}{\sum (y_i - \bar{y})^2}$$

---

## 5. Algorithm 4: Spatial Outlier Mining (IQR Fences)

1. **Three Orthogonal Spatial Concepts:**
   - **DBSCAN Density / Noise Classification:** Stations without $\text{min\_samples} = 3$ neighbors within $\epsilon = 2.0\text{ km}$ are marked as noise/isolated points (427 stations in snapshot).
   - **Geographic Coverage Gap / Isolation Distance:** Stations whose nearest recorded neighbor distance $d_{\text{min}} > 5.0\text{ km}$ indicate sparse coverage within the dataset snapshot (254 stations).
   - **Statistical IQR Outlier Fences:** Applied on the distribution of distances $d_{\text{min}}$ among isolated stations to identify statistical anomalies.
2. **Tukey Quartile Thresholds:**
   $$Q_1 = P_{25}(d_{\text{min}}), \quad Q_3 = P_{75}(d_{\text{min}}), \quad \text{IQR} = Q_3 - Q_1$$
   - **Outlier Threshold ($k = 1.5$):**
     $$\text{Threshold}_{\text{isolation\_outlier}} = Q_3 + 1.5 \times \text{IQR}$$
     In this dataset snapshot, $Q_1 \approx 7.23\text{ km}$, $Q_3 \approx 34.50\text{ km}$, $\text{IQR} \approx 27.27\text{ km}$, setting the upper Tukey fence at $\approx 75.40\text{ km}$. Exactly **17 stations** exceed this boundary (range $75.89\text{ km} - 254.84\text{ km}$) and are tracked in the artifact `top_coverage_gaps` / `extreme_isolation_outliers`.
   - **Far Outlier Threshold ($k = 3.0$):**
     $$\text{Threshold}_{\text{far\_outlier}} = Q_3 + 3.0 \times \text{IQR} \approx 116.31\text{ km}$$
     Exactly **6 extreme outlier stations** exceed this outer boundary (e.g., Lexican Motors Siliguri at $254.8\text{ km}$, Electrify Bihar at $238.9\text{ km}$, Khajuraho Airport at $240.2\text{ km}$, Punjabi Haveli at $147.8\text{ km}$, Madhav Midway Treat at $137.0\text{ km}$, JCR Entertainment World at $117.4\text{ km}$).
   - **Implementation Invariant:** The pipeline (`backend/ml/run_spatial_mining.py`) standardizes on $k = 1.5$ (`iqr_anomalies(distances, k=1.5)`), yielding the verified set of 17 isolation outliers.
