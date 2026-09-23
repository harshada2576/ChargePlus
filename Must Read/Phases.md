# Phases.md — ChargePlus Build Plan
### ChargePlus
**Status: LOCKED ROADMAP — work sequentially unless a dependency requires a small parallel task.**

## How we will track progress

There are **6 phases**.

For every work session, must explicitly state:
- Current Phase: X/6
- Remaining Phases: Y
- Current Step: X.Y
- Remaining Steps in the current phase: Y
- What is complete
- What we are doing now
- What comes next

We will also perform a conceptual check, not just a code check.

---

# Phase 1 — Foundation & Real Database
**Goal:** replace prototype storage assumptions with the actual product foundation.

### Steps
1.1 Create/configure Supabase project  
1.2 Enable required PostgreSQL/PostGIS capabilities  
1.3 Create core operational schema  
1.4 Create analytics schema  
1.5 Create ML metadata schema  
1.6 Add indexes and constraints  
1.7 Add RLS policies  
1.8 Add safe database views/functions where justified  
1.9 Establish environment variables/secrets  
1.10 Verify database with a clean test flow

### Concept check
- Does the schema represent physical stations correctly?
- Are connectors children of stations?
- Can Mumbai expand to India?
- Are operational and analytics concerns separated?
- Are user-owned records protected?
- Is provenance retained?

---

# Phase 2 — Real Data Ingestion
**Goal:** replace hardcoded station data with trustworthy external/community data.

### Steps
2.1 Define canonical station/connector input contract  
2.2 Build Python source-adapter structure  
2.3 Connect first legitimate station data source  
2.4 Preserve raw records  
2.5 Normalize fields  
2.6 Validate records  
2.7 Deduplicate/entity-match stations  
2.8 Load canonical stations/connectors  
2.9 Record freshness/provenance  
2.10 Schedule/repeat ingestion  
2.11 Verify Mumbai coverage

### Concept check
- Are stations real?
- Are source records traceable?
- Are stale values distinguished from current observations?
- Are duplicates controlled?
- Are we accidentally treating operational status as connector availability?

---

# Phase 3 — Connect the Locked Frontend
**Goal:** turn the completed UI into a real product without redesigning it.

### Steps
3.1 Replace hardcoded station dataset  
3.2 Connect Explore/map  
3.3 Connect search/filter  
3.4 Connect station detail  
3.5 Connect navigation handoff  
3.6 Connect auth/OTP  
3.7 Connect profiles  
3.8 Connect favorites  
3.9 Connect reports  
3.10 Connect reviews  
3.11 Connect alerts  
3.12 Connect admin data views  
3.13 Test loading/empty/error states against real data

### Concept check
- Does the UI say only what the data supports?
- Are unknown fields handled honestly?
- Is login requested only when needed?
- Does the existing UX remain intact?

---

# Phase 4 — Warehouse, Analytics & Data Quality
**Goal:** satisfy the data-warehouse requirement using ChargePlus's real product data.

### Steps
4.1 Build dimensions  
4.2 Build observation/report facts  
4.3 Build daily/hourly aggregates where justified  
4.4 Create ETL/ELT jobs in Python  
4.5 Add data-quality checks  
4.6 Create OLAP queries  
4.7 Build analytics/admin views  
4.8 Validate historical consistency

### Concept check
- Are fact grains explicit?
- Are dimensions reusable?
- Are aggregates derived from real observations?
- Can every analytical number be traced back to underlying records?

---

# Phase 5 — Data Mining, Forecasting & Recommendations
**Goal:** add intelligence only after enough real data exists.

### Steps
5.1 Measure data maturity  
5.2 Establish baseline  
5.3 Feature engineering  
5.4 Train simple model  
5.5 Evaluate MAE/RMSE and appropriate metrics  
5.6 Compare against baseline  
5.7 Produce station busy-time estimates  
5.8 Produce congestion/availability intelligence where supported  
5.9 Build explainable recommendation scoring  
5.10 Connect recommendations/alerts to frontend  
5.11 Document limitations

### Concept check
- Is there enough data?
- Does ML beat or meaningfully complement the baseline?
- Are predictions clearly distinguished from observations?
- Are recommendations explainable?
- Are we avoiding fake confidence?

---

# Phase 6 — Production & Public Beta
**Goal:** make ChargePlus safe and stable for real users.

### Steps
6.1 Production deployment  
6.2 Domain/configuration  
6.3 Security review  
6.4 RLS review  
6.5 Rate limiting/abuse controls  
6.6 Error monitoring/logging  
6.7 Ingestion monitoring  
6.8 ML/forecast monitoring  
6.9 Performance testing  
6.10 Mobile/browser compatibility  
6.11 Data-quality review  
6.12 Public beta checklist  
6.13 Final documentation

### Concept check
- Could a real user misunderstand stale data as live?
- Could one user corrupt shared station knowledge?
- Are failures visible?
- Are secrets protected?
- Can the system be maintained?

---

## Current status

Frontend design and implementation are complete enough to freeze.

**Current: Phase 1/6 — Step 1.6** (Steps 1.1–1.2 scaffolded in `walkthrough.md`; Steps 1.3/1.4/1.5/1.6 migrations authored; Step 1.6 synthesized constraints and indexes migration authored & statically verified — `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`.)

Completed in Phase 1:
- **1.3** Core operational OLTP schema (`public`, 11 tables) — `supabase/migrations/20260918000001_step_1_3_core_operational_schema.sql`
- **1.4** Analytics warehouse schema (`analytics`, 12 tables + dim_date/dim_time seeds + verification assertions) — `supabase/migrations/20260922000001_step_1_4_analytics_warehouse_schema.sql`
- **1.5** ML metadata schema (`ml`, 6 tables + verification assertions) — `supabase/migrations/20260922000001_step_1_5_ml_metadata_schema.sql`
- **1.6** Synthesized constraints & indexes migration authored & verified (23 CHECK/UNIQUE/FK constraints, 4 new/optimized indexes, 5 redundant indexes dropped, 0 destructive statements, no cross-layer FKs) — `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`; documentation synchronised — `docs/step_1_6_constraints_indexes_audit.md`, `docs/data_dictionary.md`

Next immediate task:
**Step 1.7 — Add RLS policies** (`public` user-owned rows + anonymous station reads, `analytics`/`ml` read-only grants, Python ETL via service/privileged context).

Note: Steps 1.1/1.2 (linked Supabase project, PostGIS/pgcrypto) are scaffolded as prerequisites; clean-flow **live** verification belongs to Step 1.10.
