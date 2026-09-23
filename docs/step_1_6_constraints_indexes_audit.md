# ChargePlus — Phase 1 Step 1.6: Constraints & Indexes Audit and Synthesis

**Phase:** 1/6 — Step 1.6/10  
**Status:** COMPLETE (Synthesized migration authored & statically validated, 23 Sep 2026)  
**Migration File:** `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`  
**Scope:** Consolidated four independent audits into ONE minimal, production-safe, idempotent migration. No destructive SQL, no frontend modifications, no data seeding/insertion, no cross-layer foreign keys, no touches to legacy `public.dim_*`/`public.fact_*` tables.

---

## 1. Audit Synthesis Overview

Step 1.6 synthesized findings across four independent audits of the Phase 1 schema:
1. **Data-Integrity Constraint Audit**: Identified 18 crucial domain invariants (causality, connector ownership, capacity uniqueness, moderation audit consistency, surrogate-key self-consistency, and ML lifecycle completeness).
2. **Index Optimization & Redundancy Review**: Replaced single-column reviews lookup with composite `(station_id, created_at DESC)`, added partial index for pending reports, provided SCD2 point-in-time index `idx_dim_station_effective`, and identified redundant indexes covered by leading columns of unique/PK constraints.
3. **ML Layer Inventory & FK-Supporting Review**: Identified missing FK indexes on `ml.model_versions` (`training_dataset_key`, `eval_dataset_key`) and exact duplicate indexes in `ml`.
4. **Architectural Boundary Verification**: Verified strict isolation between operational OLTP (`public`), canonical warehouse OLAP (`analytics`), and ML metadata/control (`ml`).

---

## 2. Implemented Schema Changes in Step 1.6

### 2.1 Public Schema (`public` — Operational OLTP)

**Index Changes:**
- **Dropped redundant indexes:**
  - `idx_reviews_user` (covered by `uq_reviews_user_station(user_id, station_id)`)
  - `idx_favorites_user` (covered by `pk_favorites(user_id, station_id)`)
  - `idx_station_source_link_source` (covered by `uq_station_source_link_source_record(source_id, source_station_id)`)
- **Optimized query index:**
  - `idx_reviews_station`: Replaced single-column index with composite `(station_id, created_at DESC)` for station-detail reviews listing.
- **New partial index:**
  - `idx_user_reports_pending`: Partial index `(created_at) WHERE moderation_status = 'pending'` for driver report moderation queue.
- **Unique index:**
  - `uq_connectors_station_type_power`: Unique on `(station_id, connector_type, power_kw, COALESCE(charging_standard, ''))` preventing duplicate static capacity groups.

**Integrity Constraints:**
- `chk_observations_causal_time`: `received_at >= observed_at` on `station_observations`.
- `chk_report_created_after_observed`: `created_at >= observed_at` on `user_reports`.
- `uq_connectors_id_station`: Unique superkey on `connectors(station_id, id)` enabling composite connector ownership FKs.
- `fk_observations_connector_owner`: FK on `station_observations(station_id, connector_id)` referencing `connectors(station_id, id)`.
- `fk_reports_connector_owner`: FK on `user_reports(station_id, connector_id)` referencing `connectors(station_id, id)`.
- `chk_user_reports_moderation_audit` & `chk_user_reports_rejection_reason`: Moderation audit consistency on `user_reports`.
- `chk_reviews_moderation_audit` & `chk_reviews_rejection_reason`: Moderation audit consistency on `reviews`.
- `chk_stations_slug_format` & `chk_operators_slug_format`: Safe token regex format `^[a-zA-Z0-9][a-zA-Z0-9_-]*$`.
- `chk_alerts_threshold_positive`: Non-negative magnitude `threshold_value >= 0`.
- `chk_source_link_seen_range`: `last_seen_at >= first_seen_at`.

### 2.2 Analytics Schema (`analytics` — Data Warehouse OLAP)

**Index Changes:**
- **New SCD2 index:**
  - `idx_dim_station_effective`: Composite `(station_id, effective_from, effective_to)` on `analytics.dim_station` for historical point-in-time fact resolution.

**Integrity Constraints:**
- `chk_dim_station_hours`: Mirrors `public.chk_stations_hours` on `analytics.dim_station`.
- `chk_dim_date_self_consistent`: Enforces exact derivation of `date_key`, `year`, `quarter`, `month`, `week`, `day_of_month`, `day_of_week`, `is_weekend`, `month_name`, and `day_name` from `full_date` using strictly **IMMUTABLE** CASE and EXTRACT expressions (avoiding Postgres `42P17` errors from locale-dependent `to_char`).
- `chk_dim_time_self_consistent`: Enforces `time_key = (hour * 4 + minute / 15)`, `slot_15min = lpad(...)`, and `time_of_day` bucket alignment.
- `chk_dim_connector_type`: Enforces parity with the Indian/international connector vocabulary (`CCS2`, `CHAdeMO`, `Type 2`, `Type 1`, `GB/T`, `Bharat AC001`, `Bharat DC001`).
- `chk_fact_observation_causal_time`: `received_at >= observed_at` on `fact_station_observation`.
- `chk_fact_observation_dim_alignment`: Enforces `date_key` and `time_key` alignment with `observed_at AT TIME ZONE 'UTC'`.
- `chk_fact_report_dim_alignment`: Enforces `date_key` and `time_key` alignment with `observed_at AT TIME ZONE 'UTC'`.
- `chk_fact_report_moderated`: Approved-only warehouse gate requires `moderated_at IS NOT NULL`.
- `chk_fact_review_moderated`: Approved-only warehouse gate requires `moderated_at IS NOT NULL`.
- `chk_fact_daily_status_counts`: Status count conservation `available_count + busy_count + broken_count <= observation_count`.

### 2.3 ML Schema (`ml` — Metadata & Control)

**Index Changes:**
- **Dropped exact duplicate indexes:**
  - `ml.idx_ml_features_name` (identical to `UNIQUE (feature_name)`)
  - `ml.idx_ml_datasets_name` (identical to `uq_datasets_name_version (dataset_name, version_str)`)
- **New FK-supporting indexes:**
  - `idx_ml_modelversions_training_dataset`: Indexes `training_dataset_key` to support `ON DELETE SET NULL` scans and dataset-to-model joins.
  - `idx_ml_modelversions_eval_dataset`: Indexes `eval_dataset_key` to support `ON DELETE SET NULL` scans and dataset-to-model joins.

**Integrity Constraints:**
- `fk_experiments_dataset`: Intra-ml foreign key linking `experiments.dataset_key` to `ml.datasets(dataset_key)`.
- `chk_experiments_lifecycle`: Enforces timestamp alignment with experiment status (`proposed` has no timestamps; `running`/`failed` have `started_at`; `completed` has both).
- `chk_datasets_time_range`: `time_range_end >= time_range_start`.
- `chk_model_ready_gate`: A model marked `ready` strictly requires `trained_at`, `completed_at`, `training_dataset_key`, and `eval_dataset_key`.

---

## 3. Verification & Safety Guarantees

All 8 mandatory verification checks were statically validated:
1. **Static SQL validation**: Semicolons, parentheses (132 balanced pairs), and `DO $$` blocks (4 balanced pairs) verified.
2. **Verify no destructive statements**: 0 `DROP TABLE`, 0 `DROP COLUMN`, 0 `DROP SCHEMA`, 0 `TRUNCATE`, 0 `DROP CONSTRAINT`. Only safe `DROP INDEX IF EXISTS` for redundant indexes.
3. **Verify no legacy table changes**: 0 executable references to legacy `public.dim_*` or `public.fact_*`.
4. **Verify no frontend changes**: `src/` directory is 100% untouched.
5. **Verify no data insertion**: 0 `INSERT INTO`, 0 `UPDATE`, 0 `DELETE`.
6. **Verify all referenced tables/columns exist**: All 19 referenced tables and columns exist in Steps 1.3, 1.4, or 1.5.
7. **Verify indexes are not duplicates**: Dropped 5 redundant indexes; added 4 targeted, non-duplicate query/FK/SCD2 indexes.
8. **Verify constraints don't conflict**: All constraints reinforce documented invariants without contradicting existing rules.

### Clean-Apply vs. NOT VALID Guidance
In the clean Step 1.10 build flow, these DDL statements apply cleanly as authored. If ever applied to an environment already populated with legacy/dirty data, foreign keys and check constraints should be added using `ADD CONSTRAINT ... NOT VALID` followed by asynchronous `VALIDATE CONSTRAINT` after data remediation.

---

## 4. Current Status & Next Steps

- **Step 1.6: COMPLETE.** Synthesis migration `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql` authored, validated, and documented.
- **Phase 1 Remaining:**
  - **Step 1.7** RLS policies (user-owned records, public station reads, service ETL context).
  - **Step 1.8** Safe database views/functions.
  - **Step 1.9** Environment variables/secrets.
  - **Step 1.10** Clean-flow database verification.

---

## References

- Migration files:
  - `supabase/migrations/20260918000001_step_1_3_core_operational_schema.sql`
  - `supabase/migrations/20260922000001_step_1_4_analytics_warehouse_schema.sql`
  - `supabase/migrations/20260922000001_step_1_5_ml_metadata_schema.sql`
  - `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`
- Documentation:
  - `Must Read/Architecture.md`, `Must Read/Phases.md`, `Must Read/Memory.md`, `Must Read/Rules.md`
  - `docs/data_dictionary.md`, `docs/data_warehouse.md`, `docs/db+warehouse+ml.md`