# Memory.md — ChargePlus Running Progress Log
### ChargePlus
**Status: ACTIVE — update at the end of every meaningful work session.**

## Why this file exists

This prevents future AI sessions from re-deriving decisions, inventing work that was already rejected, or changing architecture accidentally.

## Rules for updating

Keep entries short.

Every entry should include:
- what changed
- what works
- what is untested/broken
- blockers
- next step
- current phase/step

## Entry format

```text
### [Date] — [Work area]
- Phase / Step:
- What we built/changed:
- Current state:
- Conceptual verification:
- Blockers / waiting on:
- Next step:
```

## Current project state

### 17 Sep 2026 — Frontend → Backend transition
- Phase / Step: Phase 1/6 — Step 1.1
- What we built/changed: ChargePlus frontend is complete and frozen as the presentation/product layer. Must-Read project governance files are being established.
- Current state: UI structure exists; core station/user data plumbing still needs to move from prototype/mock storage to Supabase.
- Conceptual verification: Product decisions remain Mumbai-first, India-ready, public browsing, phone/email OTP, no passwords, one physical station with child connectors, honest freshness/status, no fabricated production data.
- Blockers / waiting on: Supabase project configuration and database implementation.
- Next step: Create/configure Supabase project and implement Phase 1 database foundation.

### 18 Sep 2026 — Phase 1 Step 1.3 Core operational schema
- Phase / Step: Phase 1/6 — Step 1.3
- What we built/changed: Authored first Phase 1 Supabase migration: `supabase/migrations/20260918000001_step_1_3_core_operational_schema.sql` — 11 `public` tables (profiles, operators, stations, connectors, data_sources, station_source_link, station_observations, user_reports, reviews, favorites, alerts), PostGIS + pgcrypto extensions, `geom geography(Point,4326)` maintained by BEFORE trigger `set_stations_geom()`, constraints/indexes authored inline.
- Current state: Full OLTP schema authored and static-verified; NOT yet applied to a live project.
- Conceptual verification: physical stations with child connectors; operator registry; provenance via station_source_link; user-owned records; `updated_at` application-maintained (no auto-trigger added); RLS explicitly deferred to Step 1.7.
- Blockers / waiting on: Steps 1.4/1.5 migrations + final live application at Step 1.10.
- Next step: Step 1.4 — analytics warehouse schema.

### 22 Sep 2026 — Phase 1 Steps 1.4 + 1.5 Warehouse & ML schemas
- Phase / Step: Phase 1/6 — Steps 1.4, 1.5
- What we built/changed: Authored `20260922000001_step_1_4_analytics_warehouse_schema.sql` (12 `analytics` tables: 8 dims + 4 facts; dim_date 2024–2032 = 3,288 rows, dim_time = 96 rows; append-only idempotent facts; no cross-layer FKs; self-verifying assertion blocks) and `20260922000001_step_1_5_ml_metadata_schema.sql` (6 `ml` tables: features, datasets, experiments, model_versions, metrics, prediction_runs; metadata-only; same-schema FKs only; assertion blocks for ml-layer isolation). Documentation: `docs/data_warehouse.md`.
- Current state: 29 tables (11 public + 12 analytics + 6 ml) authored and static-verified; NOT yet applied live.
- Conceptual verification: operational/analytics separation; legacy `public.dim_*`/`fact_*` untouched/future-reserved; grains explicit; ML maturity aligned to `analytics.fact_station_daily.maturity`.
- Blockers / waiting on: final live application + Step 1.10 clean-flow verification.
- Next step: Step 1.6 — constraints/indexes audit + documentation synchronisation.

### 23 Sep 2026 — Phase 1 Step 1.6 Constraints & indexes synthesis
- Phase / Step: Phase 1/6 — Step 1.6
- What we built/changed: Final reconciled synthesis of all four schema audits into ONE production-safe, idempotent migration `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`. Exactly reconciled inventory: (1) 27 ADD CONSTRAINT statements + 1 unique index (28 total constraints: 14 public, 10 analytics, 4 ml); (2) 9 redundant/duplicate indexes dropped (4 in public, 5 in ml); (3) 6 indexes created/optimized (3 in public, 1 in analytics, 2 in ml); (4) 45 explicit indexes in final schema state (17 public, 15 analytics, 13 ml); (5) strictly immutable expressions in dim_date/dim_time (verified against 3,288 date rows and 96 time slots); (6) intra-ml dataset_key FK on ml.experiments; (7) architectural isolation assertion block. Synced all documentation.
- Current state: EXECUTED + VERIFIED against linked Supabase project. (Initial execution attempt rolled back due to false-positive information_schema join assertion; corrected to authoritative pg_catalog assertion; execution attempt 2 succeeded as one transaction: 28 total constraints [public=14, analytics=10, ml=4], 45 explicit indexes [public=17, analytics=15, ml=13], 9 redundant indexes removed, 6 targeted indexes created, 0 cross-layer FKs confirmed via pg_constraint, reference data and legacy tables intact).
- Conceptual verification: boundary lock strictly intact (public OLTP, analytics canonical OLAP warehouse, ml metadata/control; zero cross-layer FKs confirmed via pg_constraint; no legacy public.dim_*/fact_* touched; no frontend modified; no data seeded; PostGIS and future India expansion preserved).
- Blockers / waiting on: Step 1.7 RLS policies.
- Next step: Step 1.7 — RLS policies.

### 24 Sep 2026 — Phase 1 Step 1.7 RLS & security policies
- Phase / Step: Phase 1/6 — Step 1.7
- What we built/changed: Authored and executed `supabase/migrations/20260924000001_step_1_7_rls_security_policies.sql`. Implemented defense-in-depth: (1) Schema/table grants sanitization (revoked truncate/trigger/references from anon/authenticated on public schema; revoked client writes on static/ingestion tables operators, stations, connectors, station_observations, data_sources, station_source_link; revoked write on profiles.role so users cannot self-promote to admin; revoked update/delete on user_reports from anon); (2) Enabled RLS on all 29 active target tables (11 public, 12 analytics, 6 ml); (3) Created exactly 29 explicit public RLS policies (profiles 3, operators 1, stations 1, connectors 1, station_observations 1, data_sources 1, station_source_link 1, user_reports 5, reviews 8, favorites 3, alerts 4); (4) Created 0 client policies on analytics and ml (complete default deny-all to client roles; Python ETL accesses via service_role with BYPASSRLS); (5) Zero legacy tables touched (all 9 legacy tables remain untouched with RLS disabled); (6) Zero cross-layer FKs; (7) Atomic self-verifying assertion block.
- Current state: EXECUTED + VERIFIED against linked Supabase project (`abclmxvaxkdbiqdfgdvl`). All live verifications passed: 29 active tables with RLS enabled; 29 public policies verified by name and command; 0 analytics/ml policies; profiles.role column privileges restricted to SELECT; moderation tampering blocked; reference data intact (dim_date=3288, dim_time=96); 0 rows mutated; 0 cross-layer FKs; Step 1.6 constraints (28) and explicit indexes (45) preserved; frontend typecheck clean.
- Conceptual verification: OLTP (public) secured by grants + RLS; OLAP (analytics) isolated for Python ETL; ML metadata (ml) isolated; no client data leaks; user_reports not publicly exposed.
- Blockers / waiting on: Step 1.8 views & functions.
- Next step: Step 1.8 — Add safe database views/functions where justified.

### 25 Sep 2026 — Phase 1 Step 1.8 Views & functions
- Phase / Step: Phase 1/6 — Step 1.8
- What we built/changed: Authored and executed `supabase/migrations/20260925000001_step_1_8_views_functions.sql`. Implemented conservative, secure view and function layer: (1) Helper function `public.get_author_display_name(author_id uuid)` (SECURITY DEFINER with fixed search_path, returns sanitized display_name without exposing profiles table or auth UUIDs); (2) Canonical public station view `public.v_station_current_state` (WITH security_invoker = true, composes station identity, operator info, static connector specs, latest valid observation status, derived freshness, and approved reviews); (3) Connector detail view `public.v_station_connectors` (WITH security_invoker = true, exposes static specs alongside latest connector-level live observation); (4) Sanitized community reviews view `public.v_station_approved_reviews` (WITH security_invoker = true, filters moderation_status = 'approved', omits user_id, moderator IDs, and moderation reasons); (5) Geospatial discovery function `public.nearby_stations` (SECURITY INVOKER with fixed search_path = public, extensions, pg_temp, bounded inputs, uses PostGIS ST_DWithin and GIST spatial index on stations.geom); (6) Analytics warehouse dimensional summary view `analytics.v_station_daily_summary` (WITH security_invoker = true, joins fact_station_daily with dim_date, dim_station, dim_operator for Python ETL and BI tools, service_role only); (7) Revoked writes on views from client roles; (8) Self-verifying architectural assertion block.
- Current state: EXECUTED + VERIFIED against linked Supabase project (`abclmxvaxkdbiqdfgdvl`). All live verifications passed: exactly 4 views created (3 public, 1 analytics, 0 ml) all with security_invoker = true; exactly 2 functions created (1 SECURITY DEFINER helper with fixed search_path, 1 SECURITY INVOKER PostGIS RPC); client roles hold only SELECT on public views and 0 privileges on analytics; all 29 active tables retain RLS enabled; public policies remain 29; analytics and ml policies remain 0; 0 cross-layer FKs; 9 legacy tables remain untouched and empty; reference data intact (dim_date=3288, dim_time=96); 0 rows mutated; views and functions tested cleanly on empty state returning 0 rows; frontend typecheck clean (0 errors).
- Conceptual verification: OLTP views respect RLS via security_invoker; zero raw user_reports exposed; zero internal provenance/source links exposed; no fake data; honest null handling when observations/reviews are absent; PostGIS spatial search bounded; warehouse OLAP view isolated from frontend.
- Blockers / waiting on: Step 1.9 environment variables & secrets.
- Next step: Step 1.9 — Establish environment variables/secrets.
### 25 Sep 2026 — Phase 1 Step 1.9 Environment variables & secrets
- Phase / Step: Phase 1/6 — Step 1.9
- What we built/changed: Comprehensive environment and secrets audit and configuration: (1) Complete git history and working tree secret scan (0 secret leaks in git log or tracked files); (2) Created authoritative `.env.example` clearly separating PUBLIC-SAFE client credentials (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, optional `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`) from SERVER-ONLY credentials (`DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`); (3) Strengthened `.gitignore` to explicitly block all environment variations (`.env`, `.env*.local`, `.env.development`, `.env.test`, `.env.production`, `.env.staging`) while explicitly preserving `.env.example` (`!.env.example`); (4) Verified client/server boundary (`src/lib/supabase.ts` imports only public-safe anon credentials; `DATABASE_URL` is isolated in server-only `src/db/index.ts` called exclusively by `src/app/api/health/route.ts`; 0 service-role keys imported or bundled); (5) Documented Supabase Phone OTP architectural boundary (handled natively via Supabase Auth provider dashboard without mock credentials in code); (6) Authored complete audit documentation `docs/step_1_9_environment_secrets_audit.md`.
- Current state: AUDITED + CONFIGURED + VERIFIED. Zero secrets leaked. All environment files tested with `git check-ignore`. Frontend typecheck (`tsc --noEmit`) and lint clean (0 errors).
- Conceptual verification: Strict credential classification; browser client uses public-safe credentials governed by Supabase RLS; privileged `DATABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` reserved exclusively for server routes, backend workers, and future Python ETL; no synthetic credentials invented; no database schema or RLS policies altered.
- Blockers / waiting on: Step 1.10 final Phase 1 verification.
- Next step: Step 1.10 — Phase 1 complete foundation verification.

### 25 Sep 2026 — Phase 1 Final Closure & Security Remediation
- Phase / Step: Phase 1/6 — Final Closure & Gate Sign-off
- What we built/changed: (1) Remediated credential exposure: purged scratch scripts, cleaned local environment comments, confirmed zero secrets in Git history; (2) Verified rotated database credentials live via IPv4 Supavisor connection pooler (`aws-0-ap-southeast-2.pooler.supabase.com:5432`); (3) Confirmed invalidation and rejection of previous rotated credentials; (4) Audited complete database catalog: fully reconciled object counts (public: 20 base tables + 3 views = 23; analytics: 12 base tables + 1 view = 13; ml: 6 base tables = 6); (5) Live verified data state (dim_date=3288, dim_time=96, all business/ML/legacy tables empty with 0 rows); (6) Re-verified RLS (29 public policies, 0 client analytics/ml policies, 0 client grants); (7) Re-verified cross-layer FKs = 0; (8) Corrected documentation contradiction in `Must Read/Phases.md` to reflect Phase 1 100% complete; (9) Codebase verification clean: `tsc --noEmit` clean, `eslint src` clean, `next build` clean (26/26 routes).
- Current state: PHASE 1 OFFICIALLY VERIFIED & CLOSED — READY FOR PHASE 2.
- Blockers / waiting on: None.
- Next step: Phase 2 Step 2.1 — Define canonical station/connector input contract.


