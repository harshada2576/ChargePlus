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
- What we built/changed: Synthesized the four independent schema audits into ONE production-safe, idempotent migration `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`. Authored: (1) public integrity constraints for causality, connector ownership superkey + composite FKs, capacity-group uniqueness, moderation audit consistency, slug formats, alert thresholds, source-link ranges; (2) analytics constraints for SCD2 operating hours mirror, connector vocabulary parity, deterministic surrogate-key self-consistency (using immutable CASE/EXTRACT arithmetic, no stable to_char), fact causality, UTC alignment, approved moderation provenance, daily status-count conservation; (3) ml intra-layer dataset FK, experiment lifecycle timestamps, dataset time range, model ready-gate prerequisites; (4) index optimization: composite newest-first idx_reviews_station, partial idx_user_reports_pending, SCD2 idx_dim_station_effective, and FK-supporting dataset indexes on ml.model_versions; (5) dropped 5 redundant/duplicate indexes across public and ml; (6) added architectural isolation assertion block. Synced all documentation.
- Current state: Step 1.6 COMPLETE (synthesized migration authored and passed all 8 static validation checks; not yet applied to live Supabase, awaiting Step 1.10 clean flow).
- Conceptual verification: boundary lock strictly intact (public OLTP, analytics canonical OLAP warehouse, ml metadata/control; zero cross-layer FKs; no legacy public.dim_*/fact_* touched; no frontend modified; no data seeded; PostGIS and future India expansion preserved).
- Blockers / waiting on: Step 1.7 RLS policies; final live application at Step 1.10.
- Next step: Step 1.7 — RLS policies.

