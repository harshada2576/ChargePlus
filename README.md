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

### 1. Data Ingestion & Canonical Dataset (`artifacts/chargeplus-real-dataset/`, `backend/ingestion/`)
- Curated canonical records from an authentic **India Nationwide Open Charge Map Snapshot** (541 verified stations, 655 connectors across 20 states and 293 cities, including Maharashtra, Karnataka, Tamil Nadu, Kerala, Delhi NCR, and Gujarat).
- Strict **Provenance Isolation**: Genuine live stations carry verified source metadata; simulated records carry explicit `is_simulated = true` markings so synthetic data never masks or overwrites genuine operational state.
- Normalizes major Indian CPOs (Tata Power, Jio-bp, Ather Energy, Statiq, ChargeZone, Fortum, Kazam, Magenta, Bolt.Earth, Zeon).
- Multi-standard connectors: CCS-2, Type 2 AC, CHAdeMO, and Bharat AC-001.

### 2. Operational Telemetry & Historical Observations
- Houses **80,000 operational observations** and **50,300+ daily station aggregates** (`analytics.fact_station_daily_agg`).
- Realistic diurnal traffic modeling with peak morning rush and evening commute curves.
- Live weather telemetry integration (`/api/weather`) fetching ambient temperature and atmospheric conditions via Open-Meteo.

### 3. Star Schema ETL Pipeline (`backend/etl/`)
- **Conformed Dimensions**:
  - `analytics.dim_operator` (CPO registry with alias mapping)
  - `analytics.dim_location` (MMR spatial zones & localities)
  - `analytics.dim_station` (Physical stations, SCD-Type 2 compatible)
  - `analytics.dim_connector` (Standardized connector configurations)
  - `analytics.dim_date` (3,288 calendar entries) & `analytics.dim_time` (96 quarter-hour slots)
- **Fact Tables**:
  - `analytics.fact_station_observation` (Atomic telemetry observations)
  - `analytics.fact_station_daily_agg` (Daily summaries aggregating utilization %, uptime %, and fault ticks).

### 4. Data Mining & Predictive Modeling (`backend/ml/`)
- **Spatial Density Clustering (DBSCAN + Haversine Metric)**:
  - Discovers 24 spatial density clusters across 541 real stations using true spherical great-circle distances ($\epsilon = 2.0\text{ km}$, $\text{min\_samples} = 3$).
  - Station-isolation analysis flags 254 solitary stations ($>5\text{ km}$ from nearest recorded neighbor in snapshot), with 17 extreme statistical outliers ($>75.4\text{ km}$, upper Tukey fence) and a 25-station sample.
- **Unsupervised Grouping (K-Means)**:
  - Partitions network into spatial clusters identifying high-density charging demand archetypes ($K=3$).
- **Supervised Forecasting (Random Forest Regressor)**:
  - Evaluates chronological 80/20 train/test holdout split ($N=17,280$ observation steps) yielding MAE `0.2562`, RMSE `0.3139`, $R^2 = 0.3956$ over hourly mean baseline.
  - **Production ML Contract**: Gated behind strict fail-closed data maturity checks (`backend/warehouse/maturity.py`). Production inference strictly returns `COLD / NO_MODEL` during cold start to avoid hallucinating fake congestion.

### 5. Interactive Driver Discovery & Admin Operations Console
- **MapLibre GL Map**: Native GPU clustering, vector tiles via OpenFreeMap, station selection, and live geolocation.
- **Dedicated REST APIs**: `/api/stations` (server-side spatial distance calculation, filters, and progressive pagination) and `/api/weather` (live localized weather badges).
- **Internationalization**: Full interface localization across English, Hindi (हिन्दी), and Marathi (मराठी).
- **Admin Operations Console (`/admin`)**: Real-time operational dashboard featuring Station Management with Live vs. Demo provenance split, community Report & Review moderation queues, Ingestion run tracking, and Warehouse analytics.

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
| **Weather Telemetry** | Open-Meteo Weather API |

---

## 📁 Repository Structure

```text
ChargePlus/
├── README.md                          # DWDM & engineering platform guide
├── package.json                       # Next.js scripts and dependencies
├── backend/
│   ├── ingestion/                     # Multi-source adapters, contracts, validation & dedup
│   ├── etl/                           # Star Schema ETL transformation pipeline
│   ├── ml/                            # K-Means clustering, Random Forest regressor & registry
│   └── warehouse/                     # 24-rule Data Quality validator & maturity checks
├── data/
│   ├── canonical_stations.json        # Normalized station & connector entities
│   ├── observations.json              # Historical observation ticks
│   ├── ml/                            # Model summary metrics
│   └── warehouse/                     # Dimensional Star Schema CSV catalogs
├── docs/
│   ├── olap/                          # Roll-up, Drill-down, Cube, Window ranking queries
│   └── production.md                  # Operations runbook, security posture & checklists
└── src/                               # Next.js application source
    ├── app/                           # App Router routes (/explore, /station, /admin, /api/*)
    ├── components/                    # UI components (MapLibreMap, StationCard, WeatherBadge)
    ├── data/                          # Station domain adapter, queries & types
    ├── i18n/                          # Multi-lingual dictionaries (EN, HI, MR)
    └── lib/                           # Supabase client, rate limiting, reviews & warehouse helpers
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

### 2b. Running Verification & Automated Tests
```bash
# Typecheck
npm run typecheck

# Full Node.js test suite (207 unit & integration tests: 206 passed, 0 failed, 1 skipped)
npm test

# Full Python test suite (749 passed, 3 skipped, 0 failed)
python -u -m pytest tests/ -q --ignore=tests/test_canonical_postgres_integration.py

# Production build
npm run build
```

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
