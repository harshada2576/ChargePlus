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
| **Framework** | [Next.js](https://nextjs.org/) (App Router, Turbopack) |
| **Runtime / UI** | [React 19](https://react.dev/) & [TypeScript](https://www.typescriptlang.org/) |
| **Styling** | [Tailwind CSS v4](https://tailwindcss.com/) with PostCSS |
| **Geospatial & Maps** | [MapLibre GL](https://maplibre.org/) with OpenFreeMap vector tiles |
| **Database & ORM** | [Drizzle ORM](https://orm.drizzle.team/) & [PostgreSQL](https://www.postgresql.org/) ([Supabase](https://supabase.com/)) |
| **Linting & Quality** | ESLint 9 (Flat config) & Strict TypeScript checking |

---

## 📁 Repository Structure

```text
ChargePlus/
├── .gitignore                         # Project ignore rules (builds, env, caches, archives)
├── README.md                          # Project documentation
├── STATION_DATA_CONTRACT_AUDIT.md     # Frontend data contract & database alignment audit
├── drizzle.config.json                # Drizzle ORM config — optional dev layer, NOT schema source of truth
├── eslint.config.mjs                  # Flat ESLint configuration with Next.js Core Web Vitals
├── next.config.ts                     # Next.js configuration
├── next-env.d.ts                      # Next.js TypeScript definitions
├── package.json                       # Scripts and project dependencies
├── postcss.config.mjs                 # PostCSS setup with Tailwind CSS v4 plugin
├── tsconfig.json                      # Strict TypeScript compiler options & path aliases
├── walkthrough.md                     # Implementation walkthrough & verification evidence
├── src/                               # Next.js application source (app, components, data, db, lib)
├── supabase/migrations/               # AUTHORITATIVE database schema — Phase 1 Steps 1.3–1.6 SQL
├── Must Read/                         # Locked governance docs (Architecture, Design, Memory, Phases, PRD, Rules)
└── docs/                              # SRS, data dictionary, data warehouse, Step 1.6 audit & synthesis
```

---

## 🚦 Getting Started

### Prerequisites

- **Node.js**: `v20.x` or later
- **npm**: `v10.x` or later (or `pnpm` / `yarn`)
- **PostgreSQL**: Local instance or remote database (e.g. Supabase)

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/harshada2576/ChargePlus.git
cd ChargePlus
npm install
```

### 2. Configure Environment Variables

Create a `.env.local` file in the root directory:

```env
DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/chargeplus"
NEXT_PUBLIC_SUPABASE_URL="https://your-project.supabase.co"
NEXT_PUBLIC_SUPABASE_ANON_KEY="your-anon-key"
```

### 3. Start Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser to explore the application.

---

## 📜 Available Scripts

| Command | Description |
| :--- | :--- |
| `npm run dev` | Launches the Next.js development server with hot reloading |
| `npm run build` | Builds the production bundle using Turbopack |
| `npm run start` | Starts the production server |
| `npm run typecheck` | Runs TypeScript compiler checks without emitting code (`tsc --noEmit`) |
| `npm run lint` | Runs ESLint analysis across the codebase |

---

## 🗄️ Database Management

The **authoritative schema is `supabase/migrations/*.sql`** (Phase 1 Steps 1.3/1.4/1.5/1.6 authored the `public`, `analytics`, and `ml` schemas — 29 tables — plus the Step 1.6 constraints and indexes synthesis migration). Apply them to a linked Supabase project:

```bash
supabase link --project-ref <project_ref>
supabase db push
```

[Drizzle ORM](https://orm.drizzle.team/) is installed and configured (`drizzle.config.json`, `src/db/`) but `src/db/schema.ts` is currently empty — Drizzle is an optional dev layer and **not** the schema-management source of truth. Do not use `drizzle-kit push` to alter the database.

No live Supabase project is linked yet (`supabase/config.toml` absent); end-to-end verification is Phase 1 Step 1.10.

