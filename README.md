# ChargePlus — EV Charging Data Warehouse & Data Mining Platform

> An end-to-end Electric Vehicle (EV) charging telemetry platform, dimensional data warehouse (Kimball Star Schema), and classical data mining suite built for Mumbai metropolitan charging networks.

---

## ⚡ Overview & Academic Alignment

**ChargePlus** combines an interactive Next.js geospatial discovery interface with a full-stack **Data Warehouse & Data Mining (DWDM)** pipeline. Designed specifically to adhere to academic and industry data warehouse standards without relying on generative LLMs, the platform demonstrates:

1. **OLTP Application Layer**: Public station exploration with PostGIS coordinates, connector-level availability hierarchy, crowdsourced community reports, and an Admin Operations Console.
2. **Automated ETL Pipeline**: Extraction of real multi-operator Mumbai stations, transformation into surrogate keys, calendar dimension mapping, and daily dimensional roll-ups.
3. **Kimball Star Schema Warehouse**: 4 conformed dimensions (`dim_station`, `dim_operator`, `dim_location`, `dim_connector`) referencing atomic facts (`fact_station_observation`) and summary facts (`fact_station_daily`).
4. **Classical Data Mining (No LLMs)**:
   - **Unsupervised Mining**: K-Means clustering identifying spatial charging demand hotspots across Mumbai.
   - **Supervised Mining**: Random Forest regression predicting charger congestion and queue levels evaluated with Mean Absolute Error (MAE) and $R^2$ against a naive baseline.
5. **Analytical SQL Suite**: Comprehensive OLAP demonstrations (`ROLLUP`, `CUBE`, `DRILL-DOWN`, `SLICE & DICE`, and Window ranking functions).

---

## 🏛️ System Architecture

```text
┌────────────────────────────────────────────────────────┐
│             Next.js 16 Presentation Layer              │
│       Explore Map, Search, Admin Operations Console    │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────┐
│              Operational Database (OLTP)               │
│       Supabase PostgreSQL + PostGIS (public schema)    │
│       stations, connectors, operators, observations    │
└───────────────────────────┬────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │    Python ETL Pipeline    │
              │  (backend/etl/etl_pipeline.py)
              └─────────────┬─────────────┘
                            │
┌───────────────────────────┴────────────────────────────┐
│             Kimball Star Schema Warehouse              │
│             (analytics schema / data/warehouse/)       │
│   dim_station  dim_operator  dim_location  dim_time    │
│           └───►  fact_station_daily  ◄───┘             │
└───────────────────────────┬────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │    Data Mining Engine     │
              │  (backend/ml/demand_mining.py)
              └───────────────────────────┘
               ├── K-Means Spatial Clusters (3 Hotspots)
               └── Random Forest Queue Regressor (R² = 0.41)
```

---

## 🚀 Key Features

### 1. Data Ingestion & Canonical Dataset (`backend/ingestion/`)
- Curated canonical records for **12 major charging hubs** across Greater Mumbai (BKC, Nariman Point, Airport T2, Powai, Goregaon, Lower Parel, Dadar, Thane, Vashi).
- Normalizes **8 major CPOs** (Tata Power, Jio-bp, Ather Energy, Statiq, ChargeZone, Fortum, Kazam, Magenta).
- Multi-standard connectors: CCS-2, Type 2 AC, CHAdeMO, and Bharat AC-001.

### 2. Operational History Generation (`backend/ingestion/seed_observations.py`)
- Synthesizes **17,280 hourly observations** across a 30-day monitoring window.
- Realistic diurnal traffic modeling with morning rush (8:00–10:00 AM) and evening peak (6:00–9:00 PM) utilization curves.

### 3. Star Schema ETL Pipeline (`backend/etl/etl_pipeline.py`)
- **Conformed Dimensions**:
  - `analytics.dim_operator` (8 operators)
  - `analytics.dim_location` (12 localities)
  - `analytics.dim_station` (12 physical stations, SCD-Type 2 compatible)
  - `analytics.dim_connector` (24 connector configurations)
- **Fact Table**:
  - `analytics.fact_station_daily` (360 daily summaries aggregating utilization %, uptime %, and fault ticks).

### 4. Data Mining & Predictive Modeling (`backend/ml/demand_mining.py`)
- **Unsupervised Clustering (K-Means)**:
  - Partitions network into 3 distinct spatial clusters (Western Suburban Corridor, Peripheral Suburbs, High-Density Core Hubs).
- **Supervised Forecasting (Random Forest Regressor)**:
  - Predicts queue occupancy based on temporal and geographic features.
  - **Baseline (Hourly Mean)**: $\text{MAE} = 0.2655$, $\text{RMSE} = 0.3186$
  - **Random Forest Model**: $\text{MAE} = 0.2565$, $\text{RMSE} = 0.3133$, $R^2 = 0.4105$
  - **Top Predictive Feature**: Hour of Day ($90.1\%$).

### 5. Interactive Admin Operations Console (`/admin`)
- Displays live network metrics, moderation queues, and operational status.
- Area 6 (Forecast / Model Status) displays genuine experimental data mining metrics directly from the model summary.

---

## 🛠️ Technology Stack

| Layer | Technology |
| :--- | :--- |
| **Frontend Framework** | Next.js 16 (App Router, Turbopack) & React 19 |
| **Styling** | Tailwind CSS v4 |
| **Geospatial Engine** | MapLibre GL with OpenFreeMap vector tiles |
| **Operational DB** | PostgreSQL 15+ & PostGIS (Supabase) |
| **Data Science / ML** | Python 3, Pandas, Scikit-Learn, NumPy |
| **Warehouse Modeling** | Kimball Dimensional Star Schema (CSV / SQL) |

---

## 📁 Repository Structure

```text
ChargePlus/
├── README2.md                         # This file (DWDM project guide)
├── README.md                          # Original engineering documentation
├── package.json                       # Next.js scripts and dependencies
├── backend/
│   ├── ingestion/
│   │   ├── ingest_stations.py         # Canonical Mumbai station generator
│   │   └── seed_observations.py       # 30-day diurnal telemetry generator
│   ├── etl/
│   │   └── etl_pipeline.py            # Star Schema ETL transformation pipeline
│   └── ml/
│       └── demand_mining.py           # K-Means clustering & Random Forest ML suite
├── data/
│   ├── canonical_stations.json        # Normalized station & connector entities
│   ├── observations.json              # 17,280 observation ticks
│   ├── ml/
│   │   └── mining_summary.json        # Model metrics (MAE, RMSE, R², feature importances)
│   └── warehouse/                     # Dimensional Star Schema CSV catalogs
│       ├── dim_station.csv
│       ├── dim_operator.csv
│       ├── dim_location.csv
│       ├── dim_connector.csv
│       └── fact_station_daily.csv
├── docs/
│   ├── olap/
│   │   └── olap_queries.sql           # Roll-up, Drill-down, Cube, Window ranking queries
│   └── data_warehouse.md              # Dimensional grain specifications
└── src/                               # Next.js application source
    ├── app/                           # App Router routes (/explore, /admin, /station)
    ├── components/                    # UI components (MapLibreMap, StationCard)
    └── lib/                           # Utility functions & Supabase client
```

---

## 🚦 Getting Started & Reproducing Results

### 1. Prerequisites
- Node.js v20+ and npm v10+
- Python 3.10+

### 2. Frontend Setup
```bash
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to view the driver interface or [http://localhost:3000/admin](http://localhost:3000/admin) for the Operations Console.

### 3. Running the Data Warehouse & Mining Pipeline
```bash
# Set up Python virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install requests pandas scikit-learn numpy

# 1. Ingest canonical Mumbai stations
python backend/ingestion/ingest_stations.py

# 2. Generate 30-day operational telemetry logs
python backend/ingestion/seed_observations.py

# 3. Execute Star Schema ETL Pipeline
python backend/etl/etl_pipeline.py

# 4. Train K-Means and Random Forest models
python backend/ml/demand_mining.py
```

### 4. Running OLAP Queries
Inspect [`docs/olap/olap_queries.sql`](docs/olap/olap_queries.sql) for execution in any PostgreSQL client. Demonstrates:
- `ROLLUP` (Daily to Monthly temporal aggregation)
- `DRILL-DOWN` (City $\to$ Locality $\to$ Station $\to$ Operator)
- `SLICE & DICE` (High-power CPOs on Weekend business corridors)
- `CUBE` (Operator $\times$ Locality cross-tabulation)
- `DENSE_RANK() OVER` (Window partition rankings)

---

## 🎓 Academic Viva FAQ

- **Q: Did you use any Generative AI or LLMs?**  
  *A: No. The platform strictly implements Classical Data Mining techniques: K-Means for spatial clustering and Random Forest regression for queue forecasting, evaluated against statistical baselines.*
- **Q: What is the grain of your fact table?**  
  *A: `fact_station_daily` has a grain of one row per physical station per calendar date, summarizing 24 hourly observation ticks into utilization and uptime metrics.*
- **Q: Why Kimball Star Schema over Snowflake?**  
  *A: Dimensions are intentionally denormalized (`dim_location` captures city, state, postal code in a single conformed entity) to minimize join overhead during multidimensional OLAP aggregation.*
