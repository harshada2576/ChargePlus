# ChargePlus — Next-Gen EV Charging Platform

> A high-reliability, real-time Electric Vehicle (EV) charging station discovery, telemetry tracking, and network operations platform built with Next.js, TypeScript, MapLibre GL, and Drizzle ORM.

---

## ⚡ Overview

**ChargePlus** is designed to solve EV charging anxiety by delivering transparent, dependable, and real-time charging telemetry. The platform enables drivers to locate fast chargers, verify connector availability, assess live queue levels, contribute community reports, and view honest ratings. For network administrators and operators, it features an isolated, secure Operations Console for managing charging infrastructure, ingestion feeds, and telemetry health.

---

## 🚀 Key Features

### 🗺️ Interactive Geospatial Mapping
- **MapLibre GL Vector Engine**: Powered by OpenFreeMap bright vector tiles with zero third-party API keys required.
- **Hardware-Accelerated Clustering**: Native GPU marker clustering with dynamic count indicators and zoom expansion.
- **Live Status Color Hierarchy**: Color-coded station markers reflecting real-time availability:
  - 🟢 **Available** (`#2F9E6E`)
  - 🟠 **Busy / In Use** (`#D9822B`)
  - 🔴 **Broken / Down** (`#C8443A`)
  - ⚪ **Unknown** (`#6B615E`)
- **Geolocation & Station Mini-Maps**: Real-time user position tracking with animated pulse indicator and embedded station-specific mini-maps.

### 🔍 Discovery & Zero-Click Search
- **Instant Search**: Direct `/search` redirect with autofocus hydration for zero-click queries.
- **Multi-Parameter Filtering**: Filter by network operator, connector type (CCS2, Type 2, CHAdeMO, GB/T), minimum power output (kW), pricing, and real-time availability.
- **Distance & Proximity Sorting**: Real-time distance calculations from user coordinates.

### 🔋 Detailed Station Telemetry
- **Connector Level Availability**: Granular breakdown of individual plugs, rated power (kW), and active ports.
- **Transparent Pricing & Hours**: Clear per-kWh pricing, free charging indicators, and 24/7 or scheduled operating hours.
- **Predictive Busy Windows**: Historical queue estimates and peak hour projections.
- **Time Since Last Update**: Verified status recency indicators ("last updated X min ago").

### 👥 Community Crowdsourcing
- **Driver Reports (`/reports`)**: Live queue reporting and hardware outage submissions.
- **Driver Reviews (`/reviews`)**: Verified 5-star rating breakdowns, comments, and experience feedback.
- **Personalized Driver Profile (`/profile`)**: Manage saved stations, submitted reports, reviews, alerts, and account preferences.

### 🛡️ Admin Operations Console (`/admin`)
An isolated, role-gated dark console (`#0B1120`) decoupled from the driver shell, covering 7 core operational pillars:
1. **Station Management**: Network station directory, connector configuration, and status overrides.
2. **Report Moderation**: Driver crowd reports moderation and validation queue.
3. **Review Moderation**: Rating sentiment analysis and user commentary review.
4. **Information Quality**: Telemetry confidence thresholds and stale data suppression rules.
5. **Ingestion Health**: Upstream feed monitors (Open Charge Map adapter, government data feeds, weather telemetry).
6. **Forecast & Queue ML Models**: Queue prediction model accuracy, inference latency, and drift tracking.
7. **System & Infrastructure Health**: Database connection pool status, tile CDN latency, and service uptime.

---

## 🛠️ Technology Stack

| Layer | Technology |
| :--- | :--- |
| **Frontend Framework** | [Next.js](https://nextjs.org/) (App Router, Turbopack) |
| **Runtime / UI** | [React 19](https://react.dev/) & [TypeScript](https://www.typescriptlang.org/) |
| **Styling** | [Tailwind CSS v4](https://tailwindcss.com/) with PostCSS |
| **Geospatial & Maps** | [MapLibre GL](https://maplibre.org/) with OpenFreeMap vector tiles |
| **Database & Auth** | PostgreSQL / PostGIS on [Supabase](https://supabase.com/) (RLS, PostGIS, 3-layer architecture: OLTP, OLAP, ML) |
| **Ingestion & Validation** | Python 3.12+, Pydantic v2, SHA-256 Provenance Hashing |
| **Testing & Quality** | ESLint 9 (Flat config), Strict TypeScript (`tsc --noEmit`), Pytest (`pytest-asyncio`) |

---

## 📁 Repository Structure

```text
ChargePlus/
├── .gitignore                         # Project ignore rules (builds, env, caches, archives)
├── README.md                          # Project documentation
├── STATION_DATA_CONTRACT_AUDIT.md     # Frontend data contract & database alignment audit
├── package.json                       # Frontend dependencies & build scripts
├── next.config.ts                     # Next.js configuration
├── tsconfig.json                      # Strict TypeScript compiler options & path aliases
├── src/                               # Next.js application source (app, components, data, db, lib)
├── backend/                           # Python Data Ingestion & Quality Layer
│   └── ingestion/                     # Canonical input contract, validation & source adapters
│       ├── constants.py               # CONTRACT_VERSION ("1.0.0"), bounding boxes, enums
│       ├── contracts.py               # Pydantic models (RawSourceRecord, NormalizedStation, ProvenanceInfo)
│       ├── validation.py              # DataQualityValidator (geofencing, electrical bounds, scoring)
│       ├── base.py                    # BaseSourceAdapter, AdapterResult, BatchAdapterResult
│       ├── adapters/                  # Provider-specific implementations
│       │   └── openchargemap.py       # OpenChargeMapAdapter (schema parsing, telemetry extraction)
│       ├── persistence.py             # IngestionPersistenceService (idempotency, DB sync, fact tracking)
│       ├── runner.py                  # IngestionRunner CLI orchestrator
│       ├── resolution.py              # CrossSourceEntityResolver (geodetic candidate generation, evidence fusion)
│       ├── normalization.py           # Authoritative field normalization & standard vocabulary engine
│       ├── deduplication.py           # Canonical deduplication decision layer & field survivorship policy
│       ├── freshness.py               # Pure deterministic freshness decay engine & policy abstraction
│       ├── scheduling.py              # Ingestion run state machine, retry policies, backoff & PostgreSQL advisory lock
│       └── audit.py                   # Step 2.11 read-only Mumbai coverage & data quality audit engine
├── supabase/migrations/               # AUTHORITATIVE database schema — Phase 1 & 2 SQL migrations
├── tests/                             # Comprehensive test suites (348 automated tests passing)
│   ├── test_canonical_contracts.py         # 17 unit tests — Step 2.1 canonical input contract
│   ├── test_openchargemap_adapter.py        # 20 unit tests — Step 2.2 OCM adapter & error isolation
│   ├── test_ingestion_persistence.py        # 15 unit tests — Step 2.3 persistence & idempotency
│   ├── test_entity_resolution.py            # 15 unit tests — Step 2.4 cross-source entity resolution
│   ├── test_field_normalization.py          # 30 unit tests — Step 2.5 cross-source field normalization
│   ├── test_data_quality_validation.py      # 40 unit tests — Step 2.6 data quality validation & quarantine
│   ├── test_canonical_deduplication.py      # 39 unit tests — Step 2.7 canonical decision layer & merging
│   ├── test_canonical_operational_loading.py # 43 unit tests — Step 2.8 canonical loading & mutation isolation
│   ├── test_freshness_provenance.py          # 33 unit tests — Step 2.9 freshness, provenance & decay
│   ├── test_scheduled_ingestion.py           # 32 unit tests — Step 2.10 scheduling, retry, backoff & concurrency
│   ├── test_mumbai_coverage_audit.py         # 64 unit tests — Step 2.11 Mumbai coverage & data quality audit
│   └── fixtures/                             # Offline representative test fixtures
│       └── ocm_fixtures.py                   # 18 labeled OCM fixture scenarios
├── Must Read/                         # Locked governance docs (Architecture, Design, Memory, Phases, PRD, Rules)
└── docs/                              # Architecture specs, data dictionary, warehouse, and research
    ├── canonical_station_input_contract.md              # Step 2.1 Canonical contract specification
    ├── source_adapters_architecture.md                  # Step 2.2 Source adapter framework specification
    ├── global_ev_charging_data_source_research.md       # Authoritative source research & telemetry lock
    ├── step_2_3_first_live_source_persistence.md        # Step 2.3 Persistence & idempotency
    ├── step_2_4_cross_source_entity_resolution.md       # Step 2.4 Entity resolution & evidence fusion
    ├── step_2_5_field_normalization.md                  # Step 2.5 Field normalization & vocabulary
    ├── step_2_6_data_quality_validation.md              # Step 2.6 DQ validation & anomaly quarantine
    ├── step_2_7_canonical_deduplication_and_source_merging.md # Step 2.7 Canonical deduplication
    ├── step_2_8_canonical_operational_loading_and_mutation_isolation.md # Step 2.8 Canonical loading
    ├── step_2_9_freshness_provenance_and_staleness_decay.md # Step 2.9 Freshness engine & staleness
    ├── step_2_10_scheduled_ingestion_and_retry_policies.md  # Step 2.10 Scheduled ingestion & retry
    └── step_2_11_mumbai_coverage_and_data_quality_audit.md  # Step 2.11 Mumbai pilot audit & Phase 2 sign-off
```

---

## 🚦 Getting Started

### Prerequisites

- **Node.js**: `v20.x` or later
- **npm**: `v10.x` or later
- **Python**: `v3.12.x` or later with `pip`
- **PostgreSQL / PostGIS**: Supabase project or compatible PostgreSQL 15+ instance

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/harshada2576/ChargePlus.git
cd ChargePlus

# Install frontend dependencies
npm install

# Install Python ingestion dependencies
pip install pydantic pytest pytest-asyncio python-dotenv psycopg2-binary
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env.local` and populate your project secrets:

```bash
cp .env.example .env.local
```

Key environment classifications:
- **Client (Public-Safe)**: `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` are safe for browser exposure and protected by Supabase Row-Level Security (RLS).
- **Server-Only (Database & Admin)**: `DATABASE_URL` (direct PostgreSQL pool) and `SUPABASE_SERVICE_ROLE_KEY` (admin bypass) must NEVER have a `NEXT_PUBLIC_` prefix and must never be exposed to the browser.
- **Server-Only (Data Ingestion)**: `OPENCHARGEMAP_API_KEY` used exclusively by backend Python ingestion adapters.

See [`docs/step_1_9_environment_secrets_audit.md`](docs/step_1_9_environment_secrets_audit.md) and [`docs/source_adapters_architecture.md`](docs/source_adapters_architecture.md) for credentials classification.

### 3. Start Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser to explore the application.

---

## 📜 Available Scripts & Testing

| Command | Description |
| :--- | :--- |
| `npm run dev` | Launches the Next.js development server with hot reloading |
| `npm run build` | Builds the production bundle using Turbopack |
| `npm run start` | Starts the production server |
| `npm run typecheck` | Runs TypeScript compiler checks without emitting code (`tsc --noEmit`) |
| `npm run lint` | Runs ESLint analysis across the frontend codebase |
| `python -m pytest tests/ -v` | Runs the full Python test suite (348 tests: contracts, adapters, persistence, resolution, normalization, validation, deduplication, operational loading, freshness & provenance, scheduled ingestion & retry policies, Mumbai coverage audit) |
| `python -m backend.ingestion.audit --scope mumbai` | Runs the Step 2.11 deterministic Mumbai coverage & data quality audit against the live database |

---

## 🗄️ Database Management & Project Roadmap

The **authoritative schema is `supabase/migrations/*.sql`** (Phase 1 Steps 1.3–1.8 established the 3-layer PostgreSQL database: `public` operational OLTP, `analytics` canonical OLAP warehouse, and `ml` metadata schemas; Phase 2 Step 2.10 established `public.ingestion_runs` audit log).

Apply migrations to a linked Supabase project:

```bash
supabase link --project-ref <project_ref>
supabase db push
```

### Roadmap Status
- **Phase 1 (Foundation & Database):** 100% COMPLETE & LIVE VERIFIED (29 tables with RLS enabled, 29 public RLS policies, 4 views with `security_invoker = true`, 2 functions, 28 constraints, 45 explicit indexes, zero cross-layer FKs).
- **Phase 2 (Real Data Ingestion & Data Quality):** COMPLETE & SIGNED OFF
  - **Step 2.1 — Canonical Input Contract:** COMPLETE & LOCKED (17/17 tests).
  - **Step 2.2 — Source Adapters & OCM Ingestion:** COMPLETE & LOCKED (37/37 cumulative).
  - **Step 2.3 — Connect First Live Data Source:** COMPLETE & LOCKED (52/52 cumulative).
  - **Step 2.4 — Cross-Source Entity Resolution:** COMPLETE & LOCKED (67/67 cumulative).
  - **Step 2.5 — Normalize Fields:** COMPLETE & LOCKED (97/97 cumulative).
  - **Step 2.6 — Validate Records:** COMPLETE & LOCKED (137/137 cumulative).
  - **Step 2.7 — Canonical Station Decision Layer:** COMPLETE & LOCKED (176/176 cumulative).
  - **Step 2.8 — Persist Deduplicated Canonical Stations & Connectors:** COMPLETE & LOCKED (219/219 cumulative).
  - **Step 2.9 — Record Freshness/Provenance:** COMPLETE & LOCKED (252/252 cumulative).
  - **Step 2.10 — Schedule/Repeat Ingestion:** COMPLETE & LOCKED (284/284 cumulative).
  - **Step 2.11 — Mumbai Coverage Audit & Phase 2 Sign-off:** COMPLETE & LOCKED (`backend/ingestion/audit.py`, live audit against Supabase DB at `as_of=2026-09-26T06:30:00Z`, 2 canonical stations in MMR, 348/348 cumulative tests passing, report at `docs/step_2_11_mumbai_coverage_and_data_quality_audit.md`).
- **Phase 3 (Connect the Locked Frontend):** NEXT
  - **Step 3.1 — Replace hardcoded station dataset with real Supabase data.**
