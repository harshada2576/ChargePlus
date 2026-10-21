# ChargePlus: Data Mining Methodology & Algorithms

## 1. Problem Formulation & Academic Objectives

The ChargePlus platform addresses the infrastructure analysis and charging intelligence problem for the Mumbai Metropolitan Region (MMR). While driver-facing applications typically focus on simple nearest-charger searches, this research applies formal **Data Mining (DM)** techniques to achieve four core analytical capabilities:

1. **Spatial Density Clustering:** Discover geographic agglomerations of EV charging infrastructure without assuming convex cluster geometries or predetermining cluster counts.
2. **Infrastructure Coverage Gap & Spatial Outlier Mining:** Pinpoint isolated charging points and infrastructure deserts across transit corridors.
3. **Operational Profile Partitioning:** Segment charging stations into operational tiers based on capacity, spatial positioning, and synthetic utilization indicators.
4. **Temporal Occupancy Regression & Honest Chronological Evaluation:** Model diurnal charger occupancy, evaluate regression models against temporal naive baselines, and rigorously detect data leakage.
5. **Fail-Closed Model Governance:** Ensure unvalidated models and offline experiments never project fabricated numbers to production drivers.

---

## 2. Algorithm 1: Spatial Density Clustering (DBSCAN + Haversine Metric)

### 2.1 Theoretical Rationale
Traditional partitioning algorithms such as K-Means assume spherical, equally sized clusters and require predefining the cluster count ($k$). However, municipal EV charging networks follow linear transportation corridors (Western Express Highway, Eastern Express Highway, Mumbai-Pune Expressway) and irregularly shaped urban centers (Bandra-Kurla Complex, Lower Parel). 

**DBSCAN (Density-Based Spatial Clustering of Applications with Noise)** was selected because:
- It discovers arbitrary-shaped clusters corresponding to natural commercial districts and transit routes.
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

### 2.3 Parameter Calibration
- **Epsilon ($\epsilon$):** Set to $2.0\text{ km}$. In dense metropolitan areas such as Mumbai, an EV driver within a 2 km radius has access to alternative walking/last-mile transit options.
- **MinSamples:** Set to $3$ stations. A cluster must represent a genuine localized charging hub (at least 3 independent stations) rather than an isolated pair.
- **Coverage Gap Threshold:** Stations whose nearest neighbor distance $d_{\text{min}} > 5.0\text{ km}$ are cataloged as coverage gap nodes.

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

## 5. Algorithm 4: Spatial Anomaly & Coverage Gap Mining

1. **Nearest-Neighbor Distance Matrix:** Computed via spatial BallTree with Haversine metric.
2. **IQR Outlier Fences:**
   $$Q_1 = P_{25}(d_{\text{min}}), \quad Q_3 = P_{75}(d_{\text{min}}), \quad \text{IQR} = Q_3 - Q_1$$
   $$\text{Threshold}_{\text{extreme}} = Q_3 + 3.0 \times \text{IQR}$$
   Stations exceeding this boundary are flagged as extreme isolation outliers.
