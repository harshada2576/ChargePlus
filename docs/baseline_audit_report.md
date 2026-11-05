# ChargePlus — Phase 1 Baseline Audit Report

**Date**: October 12, 2026  
**Auditor**: Senior Full-Stack, Data, ML & Security Engineering Lead  
**Branch**: `dev`  
**Base Commit**: `25e8612`  
**Git Working Tree**: Clean  

---

## 1. Executive Summary

A comprehensive architectural and code-level audit was conducted across the ChargePlus repository covering:
- Frontend presentation layer (Next.js 16, React 19, MapLibre GL)
- Operational database schema and Supabase migrations (`supabase/migrations/`)
- Drizzle ORM configuration and usage (`drizzle.config.json`, `src/db/`)
- Ingestion pipelines, external adapters, freshness and provenance engines (`backend/ingestion/`)
- Machine learning, demand mining, and maturity governance (`backend/ml/demand_mining.py`, `backend/ml/gates.py`)
- Authentication, phone OTP, and session management (`src/lib/auth.ts`, `src/state/SessionProvider.tsx`)
- Test suites (Node test runner, pytest) and CI workflows

The baseline audit confirmed that existing core functionality is stable and well-tested, but identified **five critical architectural gaps and release blockers** that must be remediated to achieve release-gate closure.

---

## 2. Baseline Test Suite Results (Prior to Modifications)

| Test Suite | Command | Collected | Passed | Failed | Skipped | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Node Unit & Integration** | `npm test` | 135 | 134 | 0 | 1 (`test_explore_map.mjs:406` live opt-in) | ✅ PASS |
| **Python Unit & Pipeline** | `pytest -q` | 687 | 678 | 0 | 9 (live DB target guard gated) | ✅ PASS |
| **TypeScript Typecheck** | `npm run typecheck` | N/A | Clean | 0 errors | 0 | ✅ PASS |
| **ESLint** | `npm run lint` | N/A | Clean | 0 errors | 0 | ✅ PASS |
| **Next.js Production Build** | `npm run build` | 23 routes | Clean | 0 errors | 0 | ✅ PASS |

---

## 3. Findings & Defect Inventory

### Finding 1: Telemetry Provenance & Freshness Not Exposed to UI (Severity: HIGH)
- **Affected Files**: `src/data/types.ts`, `src/data/stationAdapter.ts`, `src/app/station/[id]/StationDetail.tsx`, `src/components/StationCard.tsx`
- **Root Cause**: The database views (`v_station_current_state`, `v_station_connectors`) calculate `minutes_since_observation` and `latest_availability_status`, but the TypeScript domain types (`Station`, `Connector`) discard observation IDs, timestamps (`observed_at`, `received_at`), source categories (`verified_live`, `recent_observation`, `historical`, `simulated`, `unknown`), and simulation flags. Consequently, the UI only displays a relative string ("updated X min ago") without source attribution or distinct freshness states (Fresh, Aging, Stale, Unknown).
- **Reproduction**: Inspect `StationDetail.tsx` lines 165–217: connector availability renders as open or busy without showing which observation produced it, what source feed provided it, or whether it is stale.
- **Proposed Fix**: Add explicit provenance and freshness fields to domain models, thread them through `stationAdapter.ts`, display data freshness badges and source attribution in the UI, and compile an authoritative Provider Capability Matrix.

---

### Finding 2: Missing Offline Developer Demo & Environment Isolation (Severity: HIGH)
- **Affected Files**: `.env.example`, `.env.local`, `src/lib/supabase.ts`, `src/data/stations.ts`, `README.md`
- **Root Cause**: The application requires remote Supabase credentials (`NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`) even for local development. If unconfigured or offline, `getClient()` throws an unhandled exception, causing the frontend to fail on startup. There is no automated, idempotent seed command for local PostgreSQL/PostGIS, no explicit `DEMO` vs `PRODUCTION` mode toggle, and no visible UI demo-data indicator.
- **Reproduction**: Clone repository into a clean environment without `.env.local`; run `npm run dev` and navigate to `/explore`. The application crashes with `Supabase client not configured`.
- **Proposed Fix**:
  1. Implement safe handling in `src/lib/supabase.ts` and `src/data/stations.ts` with explicit `NEXT_PUBLIC_DEMO_MODE=true` support.
  2. Provide a local PostgreSQL seed script (`backend/ingestion/seed_demo_db.py`) that populates the database idempotently.
  3. Add a visible "DEMO MODE — Synthetic Test Data" indicator in `SiteHeader.tsx` when demo mode is active.
  4. Ensure production fail-closed security: production never falls back to demo data.

---

### Finding 3: Phone OTP Lacks Local Simulation & Compliance Documentation (Severity: MEDIUM)
- **Affected Files**: `src/lib/auth.ts`, `src/app/login/LoginClient.tsx`, `src/app/verify/VerifyClient.tsx`, `docs/auth_otp_spec.md`
- **Root Cause**: `src/lib/auth.ts` dispatches directly to Supabase Auth's SMS provider. When testing locally or running a demo without an active Twilio integration and paid Indian SMS DLT gateway, phone login fails with provider errors. Furthermore, there is no documented specification for Indian Telecom Commercial Communications Customer Preference Regulations (TCCCPR 2018 / TRAI) DLT requirements (Principal Entity registration, Sender ID/Header registration, Consent templates, Content templates).
- **Reproduction**: In `/login`, enter an Indian phone number and click submit. Without an active Twilio SMS gateway configured in Supabase, the user receives an unhandled provider failure.
- **Proposed Fix**:
  1. Add a controlled local developer/demo authentication simulator with safe test accounts (`+919876543210` with code `123456`) restricted strictly to non-production environments (`process.env.NODE_ENV !== "production"` or `DEMO_MODE=true`).
  2. Maintain strict fail-closed production behavior: real Supabase Auth provider with rate limiting, expiry, and zero bypass.
  3. Ensure email OTP / magic-link remains available as an immediate fallback.
  4. Document external provider requirements, per-SMS pricing, and Indian DLT regulatory compliance.

---

### Finding 4: ML Offline Evaluation Contains Data & Target Leakage (Severity: HIGH)
- **Affected Files**: `backend/ml/demand_mining.py`, `data/ml/mining_summary.json`, `backend/ml/gates.py`
- **Root Cause**: In `backend/ml/demand_mining.py`:
  - `train_test_split(..., random_state=42)` is used on hourly time-series data. This randomly interleaves future and past observations across train and test sets, violating time-series causality (temporal data leakage).
  - `baseline_lookup = df_obs.groupby("hour")["occupancy_ratio"].mean().to_dict()` computes the hourly mean baseline over the entire dataset (including the test set), causing target leakage.
  - The reported metrics (`R² = 0.4105`, `MAE = 0.2565`) were artifacts of this random split.
  - The dataset is generated synthetically by `seed_observations.py` but lacked explicit provenance labeling.
- **Reproduction**: Run `python backend/ml/demand_mining.py`. Observe random shuffle split and baseline computed on full `df_obs`.
- **Proposed Fix**:
  1. Restructure evaluation pipeline to use a strict chronological split (first 80% time window for train, final 20% for test).
  2. Compute baseline exclusively on training split.
  3. Report metrics honestly (documenting both the historical random-split artifact and the true temporal-split performance).
  4. Keep production model readiness gated at `COLD` / `NO_MODEL` per `backend/ml/gates.py`.

---

### Finding 5: Migration Authority Split Between Supabase SQL and Drizzle (Severity: MEDIUM)
- **Affected Files**: `drizzle.config.json`, `src/db/schema.ts`, `src/db/index.ts`, `supabase/migrations/`
- **Root Cause**: The repository contains both `drizzle.config.json` (pointing to an empty `src/db/schema.ts`) and 14 authoritative SQL migrations in `supabase/migrations/`. Drizzle is not used for any active queries (`src/db/index.ts` only exports standard `pg.Pool`). This duality causes ambiguity about which tool owns the database schema.
- **Reproduction**: Check `src/db/schema.ts` — it contains `export {};`. Run `npx drizzle-kit push` — it attempts to wipe all 29 database tables because no Drizzle schema exists.
- **Proposed Fix**:
  1. Authoritatively designate `supabase/migrations/` as the single source of truth for database migrations.
  2. Provide a standalone SQL migration runner (`backend/warehouse/migrate.py`) that applies all 14 migrations idempotently to any PostgreSQL instance without requiring the Supabase CLI or remote account.
  3. Document the schema architecture and add regression checks against schema drift.
