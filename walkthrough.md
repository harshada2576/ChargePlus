# ChargePlus — Correction & Completion Walkthrough (v2 Scope-Guarded)

All open gaps from the specification and Master Prompt v1.0 have been implemented and verified according to Section A's strict rules of engagement.

---

## 1. Summary of Changes

### P0: Real MapLibre Map (Replacing AbstractMap)
- **Dependency**: Added `maplibre-gl` to [package.json](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/package.json).
- **Map Component**: Created [MapLibreMap.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/components/MapLibreMap.tsx):
  - Uses vector tiles from OpenFreeMap (`https://tiles.openfreemap.org/styles/bright`) with no API key requirement, strictly avoiding `tile.openstreetmap.org` per SRS §18.
  - Markers plotted using real coordinates (`station.lat`, `station.lng`).
  - Native GPU clustering (`cluster: true`, radius 45, max zoom 14) with visible count labels, coral gradient palette (`#F08080`, `#D86A6A`, `#B05454`), and click-to-expand (`getClusterExpansionZoom`).
  - Unclustered station points styled with halo rings and colors mapped to the `StatusBadge` palette (`#2F9E6E` available, `#D9822B` busy, `#C8443A` broken, `#6B615E` unknown).
  - Marker popups styled to match ChargePlus design language (price pill, status badge, operator, area, and direct view details link).
  - Geolocation: Animated pulsing user location marker wired to recenter the map smoothly on user coordinates.
  - Mini-map support: Added single-station interactive mini-map mode.
- **Explore View**: Integrated into [ExploreClient.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/explore/ExploreClient.tsx).
- **Station Detail View**: Embedded location mini-map in [StationDetail.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/station/[id]/StationDetail.tsx).

---

### P1: Restored Missing Routes (Spec §55)
- **Reports Route**:
  - Created [page.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/reports/page.tsx) and [ReportsClient.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/reports/ReportsClient.tsx).
  - Displays user's submitted reports from `SessionProvider`, status badges, queue levels, and timestamps.
  - Friendly empty state with CTA to `/explore`.
- **Reviews Route**:
  - Created [page.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/reviews/page.tsx) and [ReviewsClient.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/reviews/ReviewsClient.tsx).
  - Reuses the star-rating display pattern from `StationReviewForm.tsx` (read-only 5-star rendering).
  - Displays station name, stars, review comment, and date.
  - Friendly empty state with CTA to `/explore`.
- **Search Redirect**:
  - Created [page.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/search/page.tsx) redirecting to `/explore?focus=search`.
  - [ExploreClient.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/explore/ExploreClient.tsx) detects `focus=search` and automatically focuses the search input on hydration for zero-click instant search.
- **Profile Menu (§53)**:
  - Updated [ProfileClient.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/profile/ProfileClient.tsx) to match the exact §53 sequence:
    1. Saved stations (`/saved`)
    2. Your reports (`/reports`)
    3. Your reviews (`/reviews`)
    4. Alerts (`/alerts`)
    5. Help (`/help`)
    6. Log out
- **Admin Operations Console (§56)**:
  - Created [layout.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/admin/layout.tsx): Dedicated dark console layout (`#0B1120`), completely independent of driver shell.
  - Updated [SiteHeader.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/components/SiteHeader.tsx), [BottomNav.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/components/BottomNav.tsx), and [SiteFooter.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/components/SiteFooter.tsx) to hide public navigation elements on `/admin`.
  - Created [page.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/admin/page.tsx) and [AdminDashboard.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/admin/AdminDashboard.tsx):
    - Gated behind `isAdmin` role check on [SessionProvider.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/state/SessionProvider.tsx) with a test simulation toggle.
    - All 7 spec-required modules individually labeled and populated:
      1. Station Management (network station directory & status filters)
      2. Report Moderation (driver crowd reports review queue)
      3. Review Moderation (ratings sentiment & commentary moderation)
      4. Information Quality (confidence thresholds & stale telemetry rules)
      5. Ingestion Health (OCM adapter, government feed, weather telemetry)
      6. Forecast / Model Status (queue prediction ML accuracy & latency)
      7. System Health (database connection pool, tile CDN latency, uptime)

---

### P2: Content & Trust Audit
- **Status Caveat**: Updated [StationCard.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/components/StationCard.tsx) to pair `StatusBadge` with `station.minutesSinceUpdate` ("last updated X min ago").
- **Footer**: Verified [SiteFooter.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/components/SiteFooter.tsx) matches §74.
- **Trust Language**: Audited `dictionaries.ts` for absolute certainty phrasing (0 matches found).

---

### Final Cleanup
- Deleted `src/components/AbstractMap.tsx`.
- Removed unused `toNormalized` function from [ExploreClient.tsx](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/app/explore/ExploreClient.tsx).
- Removed abstract `x` and `y` properties from [types.ts](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/data/types.ts) (`Station` type) and [stations.ts](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/data/stations.ts).
- Removed `project` projection function from [stations.ts](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/src/data/stations.ts).

---

## 2. Verification Results

### Automated Checks
| Check | Command | Result |
| :--- | :--- | :--- |
| **TypeScript Compiler** | `npm run typecheck` | ✅ **0 errors** (`tsc --noEmit` passed) |
| **ESLint** | `npm run lint` | ✅ **0 errors** (`eslint .` passed) |
| **Next.js Production Build** | `npm run build` | ✅ **Compiled successfully in Turbopack**, 25/25 static & dynamic pages generated |

---

### Browser Verification
Full interactive session verified and recorded by browser subagent:

1. **MapLibre Interactive Map on `/explore`**:
   ![Explore Map](C:/Users/Admin/.gemini/antigravity-ide/brain/25cf1a26-8fbf-4efe-ad57-572fcd38dc2e/explore_page_map_1789623477158.png)
   *Features verified*: Real OpenFreeMap vector tiles, marker clustering with counts, StatusBadge color language, and station focus on card click.

2. **Station Detail Mini-Map (`/station/st-andheri-east-1`)**:
   ![Station Detail Mini-Map](C:/Users/Admin/.gemini/antigravity-ide/brain/25cf1a26-8fbf-4efe-ad57-572fcd38dc2e/station_detail_minimap_loaded_1789623611779.png)
   *Features verified*: Embedded interactive mini-map centered on station coordinates with area name and address.

3. **Search Auto-Focus Redirect (`/search`)**:
   ![Search Redirect](C:/Users/Admin/.gemini/antigravity-ide/brain/25cf1a26-8fbf-4efe-ad57-572fcd38dc2e/explore_search_focused_1789623659347.png)
   *Features verified*: Seamless redirect to `/explore?focus=search` with active focus on search input.

4. **Logged-in Profile with §53 Menu Order (`/profile`)**:
   ![Profile Menu](C:/Users/Admin/.gemini/antigravity-ide/brain/25cf1a26-8fbf-4efe-ad57-572fcd38dc2e/profile_page_logged_in_1789623919078.png)
   *Features verified*: Exact order (Saved stations → Your reports → Your reviews → Alerts → Help → Log out).

5. **Reports Route (`/reports`) & Reviews Route (`/reviews`)**:
   ![Reports Page](C:/Users/Admin/.gemini/antigravity-ide/brain/25cf1a26-8fbf-4efe-ad57-572fcd38dc2e/reports_page_view_1789623987723.png)
   ![Reviews Page](C:/Users/Admin/.gemini/antigravity-ide/brain/25cf1a26-8fbf-4efe-ad57-572fcd38dc2e/reviews_page_view_1789624030947.png)
   *Features verified*: Populated routes with empty states, user-facing CTA buttons, and header consistency.

6. **Admin Security Gate & Operations Console (`/admin`)**:
   ![Admin Gate](C:/Users/Admin/.gemini/antigravity-ide/brain/25cf1a26-8fbf-4efe-ad57-572fcd38dc2e/admin_gate_page_1789624083844.png)
   ![Admin Operations Console](C:/Users/Admin/.gemini/antigravity-ide/brain/25cf1a26-8fbf-4efe-ad57-572fcd38dc2e/admin_operations_console_1789624356438.png)
   *Features verified*: HTTP 403 restriction gate, role authentication simulation, dark console layout, all 7 operational modules, and absence of public navigation elements.

---

## 3. Definition of Done Checklist

- [x] Real MapLibre map live on `/explore` and station-detail mini-map, real lat/lng, real clustering, on-brand marker styling
- [x] No hardcoded/index-based marker positioning anywhere in the codebase
- [x] `/reports` and `/reviews` routes exist, populated from real session data, with empty states
- [x] Profile menu matches §53 order exactly, all links resolve
- [x] `/search` entry points resolve — zero dead links (redirect-to-focused-Explore documented and functioning)
- [x] `/admin` exists, has its own distinct layout, is gated, covers all seven listed sub-areas, and is linked from nowhere public
- [x] Footer, trust language, and no-login-wall audits done — only genuinely-failing items edited
- [x] `AbstractMap.tsx` and unused `x`/`y` fields removed in final cleanup after map migration was confirmed working
- [x] Every file/component listed as protected in Section A, Rule 3, is untouched
- [x] No dependency changes beyond `maplibre-gl` for Task 1
- [x] Existing i18n strings (all three languages) preserved intact

---

## 4. Phase 1 Step 1.6 — Constraints & Indexes Synthesis

### Summary of Database Work
- Consolidated four independent audits into ONE minimal, production-safe, idempotent migration:
  `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`
- **Execution Status:** EXECUTED + VERIFIED against linked Supabase project.
  - *Execution Note:* First execution attempt rolled back completely due to a false-positive `information_schema` join assertion (constraint name collision with legacy `public.dim_*` tables). Corrected to authoritative `pg_catalog` assertion. Second execution attempt succeeded as one atomic transaction.
- **Integrity Constraints Added (27 ADD CONSTRAINT + 1 Unique Index = 28 total):**
  - `public` (14 constraints: 13 ADD CONSTRAINT + 1 Unique Index): Observation causality (`chk_observations_causal_time`), report causality (`chk_report_created_after_observed`), connector ownership superkey (`uq_connectors_id_station`) + 2 composite FKs (`fk_observations_connector_owner`, `fk_reports_connector_owner`), capacity uniqueness (`uq_connectors_station_type_power`), moderation consistency & reason rules on `user_reports` & `reviews` (4 checks), safe token regex on `stations.slug` & `operators.slug` (2 checks), non-negative `alerts.threshold_value`, and source-link chronology (`chk_source_link_seen_range`).
  - `analytics` (10 constraints: 10 ADD CONSTRAINT): `dim_station` operating hours mirror (`chk_dim_station_hours`), connector vocabulary parity (`chk_dim_connector_type`), deterministic surrogate-key self-consistency (`chk_dim_date_self_consistent`, `chk_dim_time_self_consistent` using immutable CASE/EXTRACT arithmetic), fact observation causality (`chk_fact_observation_causal_time`), UTC date/time alignment (`chk_fact_observation_dim_alignment`, `chk_fact_report_dim_alignment`), moderation provenance (`chk_fact_report_moderated`, `chk_fact_review_moderated`), and daily status-count conservation (`chk_fact_daily_status_counts`).
  - `ml` (4 constraints: 4 ADD CONSTRAINT): Intra-layer dataset FK (`fk_experiments_dataset`), experiment lifecycle timestamps (`chk_experiments_lifecycle`), dataset time range (`chk_datasets_time_range`), and model ready-gate (`chk_model_ready_gate`).
- **Index Operations:**
  - Dropped 9 redundant/duplicate indexes: `public.idx_reviews_station`, `public.idx_reviews_user`, `public.idx_favorites_user`, `public.idx_station_source_link_source`, `ml.idx_ml_features_name`, `ml.idx_ml_datasets_name`, `ml.idx_ml_modelversions_experiment`, `ml.idx_ml_metrics_model`, `ml.idx_ml_predictionruns_model`.
  - Created 6 indexes: `public.idx_reviews_station` (composite), `public.idx_user_reports_pending` (partial), `public.uq_connectors_station_type_power` (unique index), `analytics.idx_dim_station_effective` (composite SCD2), `ml.idx_ml_modelversions_training_dataset`, `ml.idx_ml_modelversions_eval_dataset`.
  - Final explicit index count: 48 baseline - 9 dropped + 6 created = **45 explicit indexes in final state** (public=17, analytics=15, ml=13).
- **Validation Checklist:**
  - [x] Static SQL validation (parentheses, DO blocks, syntax clean)
  - [x] Verify no destructive statements (0 drop table/column/schema/truncate/constraint)
  - [x] Verify no legacy table changes (legacy `public.dim_*` / `public.fact_*` untouched)
  - [x] Verify no frontend changes (`src/` untouched)
  - [x] Verify no data insertion (0 INSERT/UPDATE/DELETE)
  - [x] Verify all referenced tables/columns exist across Step 1.3, 1.4, 1.5 schemas
  - [x] Verify indexes are not duplicates (9 redundant dropped, 6 new targeted created)
  - [x] Verify constraints don't conflict (strict reinforcement of invariants)
  - [x] Seeded reference data verified (3,288 date rows, 96 time slots verified against checks)
  - [x] Clean temporary files (0 temp scripts left)
  - [x] Live Supabase execution succeeded as one atomic transaction
  - [x] 28 constraints verified (public=14, analytics=10, ml=4)
  - [x] 45 explicit indexes verified (public=17, analytics=15, ml=13)
  - [x] 6 required new indexes verified present
  - [x] 8 redundant indexes verified dropped
  - [x] Reference data counts verified (dim_date=3288, dim_time=96)
  - [x] 0 cross-layer FKs confirmed via pg_constraint
  - [x] 9 legacy public tables remain at 0 rows

---

## 5. Phase 1 Step 1.7 — RLS & Security Policies

### Summary of Database Work
- Migration: `supabase/migrations/20260924000001_step_1_7_rls_security_policies.sql`
- **Execution Status:** EXECUTED + VERIFIED against linked Supabase project (`abclmxvaxkdbiqdfgdvl`).
- Executed cleanly as one atomic transaction with embedded self-verifying assertion blocks.

### Defense-in-Depth Security Strategy
1. **Schema & Table Grants Sanitization:**
   - Revoked dangerous table-level privileges (`TRUNCATE`, `TRIGGER`, `REFERENCES`) from `anon` and `authenticated` on all public tables.
   - Revoked client writes (`INSERT`, `UPDATE`, `DELETE`) on static/ingestion-managed operational tables (`operators`, `stations`, `connectors`, `station_observations`, `data_sources`, `station_source_link`) from `anon` and `authenticated`.
   - Revoked all permissions from `anon` on internal provenance and user-isolated tables (`data_sources`, `station_source_link`, `profiles`, `user_reports`, `favorites`, `alerts`).
   - Column-level privilege sanitization on `public.profiles`: revoked write permissions on `role` for `authenticated` (`GRANT UPDATE (display_name, preferred_language, home_city, updated_at)` and `GRANT INSERT (id, display_name, preferred_language, home_city, created_at, updated_at)`), permanently eliminating client privilege escalation to admin.
2. **Row Level Security (RLS Enabled on 29 Active Target Tables):**
   - `public`: 11 operational tables (`profiles`, `operators`, `stations`, `connectors`, `data_sources`, `station_source_link`, `station_observations`, `user_reports`, `reviews`, `favorites`, `alerts`).
   - `analytics`: 12 warehouse tables (`dim_station`, `dim_operator`, `dim_location`, `dim_connector`, `dim_date`, `dim_time`, `dim_source`, `dim_weather`, `fact_station_observation`, `fact_user_report`, `fact_review`, `fact_station_daily`).
   - `ml`: 6 metadata/control tables (`features`, `datasets`, `experiments`, `model_versions`, `metrics`, `prediction_runs`).
   - All 9 frozen legacy tables (`public.dim_*`, `public.fact_*`) remain untouched with RLS disabled.
3. **Exact Policy Inventory (29 Policies Created on Public Schema):**
   - `profiles` (3): `profiles_select_own` (own id), `profiles_insert_own` (own id, role forced to user), `profiles_update_own` (own id).
   - `operators` (1): `operators_select_public` (true).
   - `stations` (1): `stations_select_public` (`is_public = true`).
   - `connectors` (1): `connectors_select_public` (parent station `is_public = true`).
   - `station_observations` (1): `station_observations_select_public` (parent station `is_public = true`).
   - `data_sources` (1): `data_sources_select_admin` (admin only).
   - `station_source_link` (1): `station_source_link_select_admin` (admin only).
   - `user_reports` (5): `user_reports_select_own` (author only), `user_reports_select_admin` (admin queue), `user_reports_insert_own` (author only, pending forced, moderation fields NULL/clean), `user_reports_update_admin` (admin only), `user_reports_delete_admin` (admin only). Direct anonymous SELECT denied to protect user IDs and PII.
   - `reviews` (8): `reviews_select_approved` (public approved only), `reviews_select_own` (author view), `reviews_select_admin` (admin queue), `reviews_insert_own` (pending forced), `reviews_update_own` (author edit resets to pending, wipes moderation data), `reviews_update_admin` (admin moderation), `reviews_delete_own` (author delete), `reviews_delete_admin` (admin delete).
   - `favorites` (3): `favorites_select_own`, `favorites_insert_own`, `favorites_delete_own` (user_id = auth.uid()).
   - `alerts` (4): `alerts_select_own`, `alerts_insert_own`, `alerts_update_own`, `alerts_delete_own` (user_id = auth.uid()).
4. **Analytics & ML Boundary:**
   - 0 client-facing policies created on `analytics` or `ml`. Direct client access is denied by default.
   - Python ETL / backend services write via `service_role` / direct database pool (`BYPASSRLS = true`).

### Live Verification Results
- [x] 29 active target tables verified with `relrowsecurity = true`
- [x] 9 legacy tables verified with `relrowsecurity = false`
- [x] Exactly 29 policies verified in `public` schema
- [x] 0 client policies verified in `analytics` and `ml` schemas
- [x] `profiles.role` column write privileges confirmed revoked for `authenticated`
- [x] Moderation-field tampering blocked by RLS `WITH CHECK` predicates
- [x] `user_reports` direct anonymous SELECT denied
- [x] 0 cross-layer FKs confirmed via `pg_constraint`
- [x] Reference data counts verified (`dim_date` = 3288, `dim_time` = 96)
- [x] Operational, fact, and ML rows verified at 0 (no fake data)
- [x] Step 1.6 constraints (28) and explicit indexes (45) preserved intact
- [x] `npm run typecheck` passed with 0 errors

---

## 6. Phase 1 Step 1.8 — Views + Functions

### Summary of Database Work
- Migration: `supabase/migrations/20260925000001_step_1_8_views_functions.sql`
- **Execution Status:** EXECUTED + VERIFIED against linked Supabase project (`abclmxvaxkdbiqdfgdvl`).
- Executed cleanly as one atomic transaction with self-verifying assertion blocks.

### Objects Created (4 Views, 2 Functions)
1. **`public.get_author_display_name(author_id uuid)`** (Function):
   - `SECURITY DEFINER` with fixed `search_path = public, pg_temp`.
   - Returns sanitized author nickname for approved customer reviews without exposing the `profiles` table or auth UUIDs.
   - Granted to `anon`, `authenticated`, `service_role`.
2. **`public.v_station_current_state`** (View):
   - Created `WITH (security_invoker = true)` to inherit caller's RLS.
   - Composes physical station metadata, operator details, static connector specs, latest live observation status, derived freshness (`minutes_since_observation`), and approved review metrics.
   - If no observation exists, status and counts default honestly to `NULL`.
   - Client write privileges revoked; only `SELECT` granted to `anon`, `authenticated`, `service_role`.
3. **`public.v_station_connectors`** (View):
   - Created `WITH (security_invoker = true)`.
   - Exposes connector specifications per station alongside latest connector-level live observation (if present).
   - Client writes revoked; `SELECT` granted to `anon`, `authenticated`, `service_role`.
4. **`public.v_station_approved_reviews`** (View):
   - Created `WITH (security_invoker = true)`.
   - Public feed of approved driver reviews with author display names.
   - Deliberately excludes `user_id`, `moderated_by`, `moderated_at`, `moderation_reason`, `is_flagged`, and unapproved reviews.
   - Client writes revoked; `SELECT` granted to `anon`, `authenticated`, `service_role`.
5. **`public.nearby_stations`** (Function / RPC):
   - `SECURITY INVOKER` with fixed `search_path = public, extensions, pg_temp`.
   - PostGIS spatial discovery utilizing GIST index `idx_stations_geom` on `stations.geom`.
   - Evaluates `ST_DWithin` and `ST_Distance` on geography points.
   - Bounded inputs: latitude range check (`-90..90`), longitude range check (`-180..180`), radius capped at 200km (`LEAST(radius_meters, 200000.0)`), and results capped at 100 (`LEAST(GREATEST(max_results, 1), 100)`).
   - Granted to `anon`, `authenticated`, `service_role`.
6. **`analytics.v_station_daily_summary`** (View):
   - Created `WITH (security_invoker = true)`.
   - Pure OLAP star-schema reporting view joining `fact_station_daily` with conformed dimensions `dim_date`, `dim_station`, and `dim_operator`.
   - Granted strictly to `service_role`. Zero client access, preserving warehouse isolation.

### Live Verification Results
- [x] Exactly 4 views verified present (`v_station_current_state`, `v_station_connectors`, `v_station_approved_reviews`, `v_station_daily_summary`)
- [x] All 4 views verified with `security_invoker = true` in `pg_class.reloptions`
- [x] Exactly 2 functions verified present (`get_author_display_name` SECURITY DEFINER, `nearby_stations` SECURITY INVOKER)
- [x] Functions verified with fixed, safe `search_path`
- [x] View writes (`INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`) confirmed revoked from `anon` and `authenticated`
- [x] `analytics.v_station_daily_summary` verified with 0 client permissions (`service_role` only)
- [x] All 29 active tables retain RLS enabled
- [x] Public policies remain exactly 29
- [x] Analytics and ML policies remain 0 (deny-all client default)
- [x] 0 cross-layer FKs confirmed via `pg_constraint`
- [x] 9 legacy tables remain intact with 0 rows and RLS disabled
- [x] Reference data counts verified (`dim_date` = 3288, `dim_time` = 96)
- [x] Operational stations, facts, and ML metadata verified at 0 rows (no fake data)
- [x] Live query execution tests against empty state passed cleanly for all views and functions (returned 0 rows without errors)
- [x] `npm run typecheck` passed with 0 errors




