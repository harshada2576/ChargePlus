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

**ACTIVE PHASE / STEP: Phase 2/6 — Step 2.4 COMPLETE (Ready for Step 2.5)**
- **Phase 1 (Foundation & Real Database, Steps 1.1–1.10)**: COMPLETE & SIGNED OFF (All 29 active tables, RLS, 4 views, 2 functions, constraints, indexes live verified on Supabase).
- **Phase 2 (Real Data Ingestion & Data Quality)**:
  - Step 2.1 COMPLETE (Canonical Station/Connector Input Contract, Pydantic models, validation engine, 17/17 tests passing).
  - Step 2.2 COMPLETE & LOCKED (Base adapter framework, OpenChargeMapAdapter, global data source research lock, 37/37 tests passing).
  - Step 2.3 COMPLETE & LOCKED (Operational persistence service, idempotent runner, live Supabase PostgreSQL verified, 52/52 tests passing).
  - Step 2.4 COMPLETE & LOCKED (Cross-source entity resolution, multi-signal evidence fusion, 67/67 tests passing).
- **Next Immediate Step**: Step 2.5 — Normalize fields (cross-source operator, connector, tariff & electrical vocabulary) (Do NOT start until explicitly instructed).
- **Production Database**: Live compatibility verified against Supabase; zero schema modifications; legacy warehouse tables untouched.

### Historical Progress Log
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

### 25 Sep 2026 — Phase 1 Step 1.10 Final foundation verification & Phase 1 sign-off
- Phase / Step: Phase 1/6 — Step 1.10 (FINAL PHASE 1 FOUNDATION GATE)
- What we built/changed: Comprehensive live audit and end-to-end verification of the ChargePlus Phase 1 foundation against the linked Supabase project (`abclmxvaxkdbiqdfgdvl`): (1) Confirmed all 29 active target tables (11 public operational, 12 analytics canonical warehouse, 6 ml metadata); (2) Confirmed all 9 legacy tables remain untouched, empty (0 rows), and isolated with RLS disabled; (3) Verified reference dimension counts (`analytics.dim_date` = 3,288 rows, `analytics.dim_time` = 96 rows) and confirmed 0 fake/unauthorized rows in all operational and ML tables; (4) Verified all 28 Step 1.6 integrity constraints (14 public, 10 analytics, 4 ml); (5) Verified all 45 explicit indexes (17 public, 15 analytics, 13 ml); (6) Verified Row-Level Security on all 29 active tables with exactly 29 public RLS policies and 0 client policies on analytics/ml; (7) Verified 0 cross-layer FKs (sole cross-schema FK is standard `public.profiles.id -> auth.users.id`); (8) Verified all 4 database views (`public.v_station_current_state`, `public.v_station_connectors`, `public.v_station_approved_reviews`, `analytics.v_station_daily_summary`) configured with `security_invoker = true`, verified 2 functions (`public.get_author_display_name` SECURITY DEFINER with fixed search_path, `public.nearby_stations` PostGIS RPC), and verified empty-state query executions; (9) PostGIS spatial extension, geometry point SRID 4326, and spatial index verified; (10) Verified environment safety and secrets boundary (public-safe client keys vs server-only keys, 0 secrets leaked, `.gitignore` validated); (11) Verified frontend prototype remains completely intact with fixtures and local session untouched; (12) Clean TypeScript typecheck (`tsc --noEmit`) and ESLint (`eslint .`) with 0 errors.
- Current state: PHASE 1 COMPLETE — FOUNDATION VERIFIED & SIGNED OFF.
- Conceptual verification: Hard three-layer boundary maintained (public OLTP, analytics canonical OLAP warehouse, ml metadata/control, Python ETL boundary); zero cross-layer FKs; no synthetic data; full security isolation; production ready for Phase 2 ingestion.
- Blockers / waiting on: Phase 2 Real Data Ingestion (Step 2.1).
- Next step: Phase 2 Step 2.1 — Define canonical station/connector input contract.

### 25 Sep 2026 — Phase 2 Step 2.1 Canonical Station/Connector Input Contract
- Phase / Step: Phase 2/6 — Step 2.1
- What we built/changed: Designed and implemented the source-neutral canonical input contract for ChargePlus EV data ingestion: (1) Established the 6-layer architecture (Raw Source, Normalized Record, Canonical Station, Canonical Connector, Telemetry Observations, Analytical Warehouse); (2) Clarified Layer 6 canonical warehouse facts: exactly 4 canonical facts (`analytics.fact_station_observation`, `analytics.fact_user_report`, `analytics.fact_review`, `analytics.fact_station_daily`), explicitly excluding `fact_charging_session` which is not in our canonical Phase 1 warehouse; (3) Created strongly-typed Python models (`backend/ingestion/contracts.py`) for `RawSourceRecord`, `NormalizedStationRecord`, `NormalizedConnectorRecord`, and `NormalizedObservationRecord` with strict validation rules and contract versioning (`1.0.0`); (4) Created data quality validation engine (`backend/ingestion/validation.py`) with deterministic outcomes (`ACCEPT`, `ACCEPT_WITH_WARNINGS`, `QUARANTINE`, `REJECT`) and completeness scoring; (5) Refined coordinate validation: coordinates in `[-90, 90]` and `[-180, 180]` are valid, individual 0.0 on the Equator or Prime Meridian is valid, and ONLY `(0.0, 0.0)` together is rejected as Null Island; (6) Formalized missing-data semantics ("Missing means Missing" — no fake ₹0 prices, no fake 0 kW power, no fake 'available' statuses); (7) Formalized the 6 distinct status semantics (operational state, connector availability, observation state, user reports, predictions, data freshness); (8) Defined entity resolution / deduplication candidate features (geodetic distance, operator slug, token sort name matching, address/PIN, connector signatures); (9) Preserved raw source payloads and unmapped vendor fields via `extra_metadata`; (10) Built comprehensive unit test suite (`tests/test_canonical_contracts.py`) covering all 17 contract scenarios with 100% pass rate; (11) Authored complete specification document `docs/canonical_station_input_contract.md`; (12) Verified clean TypeScript typecheck (`tsc --noEmit`) and ESLint (`eslint src`).
- Current state: STEP 2.1 COMPLETE & LOCKED — READY FOR STEP 2.2.
- Conceptual verification: Fully source-neutral contract matching real-world EV charging topologies (single station to multiple connectors, aggregated capacity vs individual plugs, multi-operator support, Mumbai pilot bounds with India-wide expansion, strict separation of static identity from telemetry observations); zero production database mutations; zero fake data.
- Blockers / waiting on: Step 2.2 (Build Python source-adapter structure).
- Next step: Phase 2 Step 2.2 — Build Python source-adapter structure.

### 25 Sep 2026 — Phase 2 Step 2.2 Build Source-Specific Adapters
- Phase / Step: Phase 2/6 — Step 2.2
- What we built/changed: Designed and implemented the first source adapter architecture and the production-grade `OpenChargeMapAdapter`:
  1. Base Source Adapter Architecture (`backend/ingestion/base.py`): Defined `BaseSourceAdapter` abstract base class with clean lifecycle phases (`fetch_raw`, `parse_raw`, `normalize_station`, `validate_record`, `process_record`, `process_batch`), `AdapterResult` (single-record outcome with error/warning tracking), and `BatchAdapterResult` (batch execution with record-level error isolation where malformed records are quarantined/rejected without failing the entire batch).
  2. First-Class Provenance Integration: Added `ProvenanceInfo` model and `RawSourceRecord.to_provenance()` method in `backend/ingestion/contracts.py`, ensuring deterministic SHA-256 fingerprinting of pristine source JSON payloads alongside timestamps and source IDs.
  3. Real OpenChargeMap Ingestion Adapter (`backend/ingestion/adapters/openchargemap.py`):
     - Verified actual OCM API schema (`AddressInfo`, `Connections`, `StatusType`, `UsageType`, `OperatorInfo`, `UsageCost`).
     - Mapped OCM station identity (`ID`, `Title`), geocoordinates, full postal address, country (`IN`), operator, access rules, and contact info.
     - Preserved unmapped vendor fields (`UUID`, `DataProviderID`, `NumberOfPoints`) in `extra_metadata`.
     - Connector Normalization: Implemented confident type mapping (OCM 33 $\to$ CCS2, 32 $\to$ CCS1, 25/1036 $\to$ Type 2, 2 $\to$ CHAdeMO, 34/35 $\to$ GB/T) and ambiguous fallback to `OTHER` with explicit warnings. Supported both individual connector IDs and aggregated connector information (`quantity >= 1`, omitting fake IDs).
     - Power Normalization: Extracted `PowerKW` to float kW; preserved missing power strictly as `None` (never default to 0 kW or guessed from connector type); safely caught malformed power values.
     - Operational vs Availability Separation: OCM StatusType 50 ("Operational") mapped to `OperationalStatus.OPERATIONAL` on station, with connector status remaining `UNKNOWN` and `observation = None` (no fake observations manufactured). Real telemetry status (StatusType 10 "Available", 20 "Occupied") paired with `DateLastStatusUpdate` produces formal `NormalizedObservationRecord`.
     - Transport & Security Isolation: Abstracted `fetch_raw()` with strict `OPENCHARGEMAP_API_KEY` environment variable enforcement and runtime exceptions if credentials are missing; offline tests run strictly against fixtures.
  4. Test Fixtures & Unit Test Suite:
     - Authored 18 comprehensive test fixture scenarios in `tests/fixtures/ocm_fixtures.py` (complete valid station, multiple connectors, aggregated connectors, missing optional fields, unknown connector, missing power, equator zero-latitude, prime meridian zero-longitude, Null Island rejection, non-India quarantine, malformed coordinates, malformed power, telemetry observation, static operational non-observation, extra fields preservation, duplicate payload hash determinism, malformed empty payload, missing station ID).
     - Authored 20 unit tests in `tests/test_openchargemap_adapter.py` testing all fixture scenarios, batch error isolation, and credential security.
     - Full test suite passed: 37/37 tests (17 canonical contract tests + 20 adapter tests).
  5. Verified Zero Database Mutations: Confirmed 0 rows inserted into `public.stations`, `public.connectors`, `public.station_observations`, `analytics.*`, or `ml.*`.
  6. Documentation & Secrets: Created `docs/source_adapters_architecture.md`, created `docs/global_ev_charging_data_source_research.md` (authoritative global EV data source research, 5-tier classification, telemetry models, Kafka exclusion decision, and duplicate prevention architecture), updated `.env.example` with `OPENCHARGEMAP_API_KEY`, verified `tsc --noEmit` and `npm run lint` clean (0 errors).
- Current state: STEP 2.1 COMPLETE, STEP 2.2 COMPLETE & LOCKED, STEP 2.2A RESEARCH COMPLETE & LOCKED — READY FOR STEP 2.3.
- Conceptual verification: Unidirectional boundary maintained (Source $\to$ Adapter $\to$ Step 2.1 Canonical Contract); no Supabase persistence; no cross-source entity deduplication; no synthetic business truth invented; record-level batch error isolation verified; Kafka excluded; real-time telemetry strictly separated from static equipment state; "Stale != Unavailable" invariant codified.
- Blockers / waiting on: Step 2.3 (Connect first legitimate station data source).
- Next step: Phase 2 Step 2.3 — Connect first legitimate station data source.

### 25 Sep 2026 — Phase 2 Step 2.3 Connect First Legitimate Station Data Source
- Phase / Step: Phase 2/6 — Step 2.3
- What we built/changed: Designed and implemented the controlled operational and historical observation persistence boundary for OpenChargeMap data:
  1. Transactional Persistence Service (`backend/ingestion/persistence.py`):
     - `IngestionPersistenceService` separates persistence logic entirely from transformation adapters.
     - Feeds registered in `public.data_sources` and mirrored to `analytics.dim_source`.
     - Operators registered in `public.operators` and mirrored to `analytics.dim_operator`.
     - Physical stations persisted to `public.stations` with PostGIS geometry trigger `trg_stations_geom` generating `POINT(lng lat)` automatically.
     - Connectors synchronized to `public.connectors` by aggregating identical `(connector_type, power_kw, charging_standard)` capacity groups to satisfy `uq_connectors_station_type_power`.
     - Strictly enforced `NOT NULL` and positive power without inventing power values; connectors lacking power are safely skipped with warnings.
     - Enforced `chk_stations_hours` constraint (opening/closing times NULL when `is_24_hours = true`).
     - Enforced Indian 6-digit PIN regex; non-compliant postal codes stored as NULL with warnings logged.
  2. Idempotency & Provenance Linkage:
     - Implemented `public.station_source_link` tracking `(source_id, source_station_id)`.
     - SHA-256 payload hash comparison: identical re-ingestion returns `UNCHANGED` and refreshes `last_seen_at` with 0 duplicate stations or connectors.
     - Changed source payload triggers in-place station attribute and connector `UPDATED`.
     - External source ID (`192840`) is decoupled from ChargePlus station `uuid.uuid4()`.
  3. Observation History & Analytics Fact Persistence:
     - Real point-in-time telemetry produces operational observation in `public.station_observations`.
     - Conformed observation mirrored to `analytics.fact_station_observation` resolving `station_key`, `operator_key`, `location_key`, `date_key` (YYYYMMDD UTC), and `time_key` (0..95 15-min interval UTC).
     - Static operational status (`StatusTypeID: 50`) never creates fake availability observations.
  4. Ingestion Orchestrator & CLI Runner (`backend/ingestion/runner.py`):
     - CLI options: `--dry-run`, `--limit`, `--all-india`, `--use-fixtures`, `--json`.
     - Geographic bounding box strictly defaults to Mumbai Metropolitan Region (`18.70-19.50 N`, `72.70-73.30 E`).
     - Record-level error isolation: individual record failure does not abort the entire batch.
     - Zero credentials exposed in logs or reports.
  5. Test Suite & Verification:
     - 15 comprehensive unit tests authored in `tests/test_ingestion_persistence.py`.
     - All 52 automated tests in `tests/` pass with 100% success rate (17 contract + 20 adapter + 15 persistence).
     - Dry run verified with 0 database writes.
     - Live Supabase PostgreSQL database compatibility tested and verified (PostGIS trigger, idempotency, observation fact keys).
     - Documentation completed in `docs/step_2_3_first_live_source_persistence.md`.
- Current state: STEP 2.3 COMPLETE & LOCKED.
- Conceptual verification: Operational state (`public.*`) separated from canonical warehouse facts (`analytics.*`); adapters remain strictly non-persistent; "Missing means missing" strictly honored; external IDs never become station UUIDs; no message brokers; no cross-source fuzzy entity matching (deferred to Step 2.4).
- Blockers / waiting on: Step 2.4.
- Next step: Phase 2 Step 2.4 — Cross-source entity resolution (candidate generation & evidence fusion).

### 25 Sep 2026 — Phase 2 Step 2.4 Cross-Source Entity Resolution (Candidate Generation & Evidence Fusion)
- Phase / Step: Phase 2/6 — Step 2.4
- What we built/changed:
  1. Authoritative Evidence Generation Engine (`backend/ingestion/resolution.py`):
     - Pure computational, deterministic, multi-signal evidence fusion layer.
     - Geodetic candidate generation using Haversine great-circle distance on WGS 84 ($R=6,371,000$m). Configurable candidate radius default $\le 50.0$ meters.
     - Multi-signal evaluation: Spatial proximity (0.30), Lexical name similarity with Mumbai acronym expansion and token overlap (0.30), Operator reconciliation (0.15), Electrical connector signature compatibility (0.15), and Locality/PIN overlap (0.10).
     - Discrete match states: `MATCH`, `NON_MATCH`, `AMBIGUOUS`.
     - Invariant: Proximity alone ($\le 50$m) does NOT prove identity. Weak or conflicting signals within 50m evaluate to `AMBIGUOUS`.
     - Invariant: Missing data evaluates to `UNKNOWN` (neutral weight), never negative disagreement ("Missing != Disagreement").
     - Invariant: Commercial takeover / rebranding handled safely (Rule A3 allows MATCH on identical physical site despite operator divergence).
     - Invariant: External source identifiers preserved verbatim; zero generation of ChargePlus station UUIDs in resolution.
     - Invariant: Non-destructive guarantee. Zero mutations to `public.stations`, `public.connectors`, `public.station_source_link`, or `analytics` facts.
  2. Module Integration & Exports:
     - Exported all core classes in `backend/ingestion/__init__.py`.
  3. Comprehensive Unit Test Suite (`tests/test_entity_resolution.py`):
     - 15 unit tests covering all 14 mandatory scenarios: strong agreement, clearly different stations, close conflicting coordinates (ambiguous), same name far apart, missing connector data handling, rebranding/takeover, 50m boundary precision, 0m coordinates with weak metadata, missing address/PIN, connector signature variants, determinism, non-destructive immutability, multiple candidates preservation, and source identity preservation.
     - All 67 project automated tests pass with 100% success rate.
  4. Quality Gates:
     - `pytest` (67/67 passing).
     - `npx tsc --noEmit` (0 errors).
     - `npm run lint` (0 errors).
     - `npm run build` (successful production build).
  5. Documentation:
     - Completed comprehensive reference in `docs/step_2_4_cross_source_entity_resolution.md`.
- Current state: STEP 2.4 COMPLETE & LOCKED — READY FOR STEP 2.5.
- Conceptual verification: Resolution engine is purely computational; evidence dossier is fully transparent with auditable reasons; ambiguity is preserved rather than discarded; source IDs remain source IDs; zero DB migrations; canonical source precedence and survivorship deferred to Step 2.7.
- Blockers / waiting on: Step 2.5 (Normalize fields).
- Next step: Phase 2 Step 2.5 — Normalize fields (cross-source operator, connector, tariff & electrical vocabulary).
