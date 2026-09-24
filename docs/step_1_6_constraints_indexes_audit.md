# ChargePlus — Phase 1 Step 1.6: Constraints & Indexes Audit and Synthesis

**Phase:** 1/6 — Step 1.6/10  
**Status:** CREATED & STATICALLY VERIFIED / NOT YET EXECUTED against Supabase (23 Sep 2026)  
**Migration File:** `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`  
**Scope:** Reconciled synthesis of four independent audits into ONE minimal, production-safe, idempotent migration. No destructive SQL, no frontend modifications, no data seeding/insertion, no cross-layer foreign keys, no touches to legacy `public.dim_*`/`public.fact_*` tables.

---

## 1. Audit Reconciliation Overview

Step 1.6 synthesized findings across four independent audits of the Phase 1 schema against the actual committed Step 1.3, 1.4, and 1.5 migrations:
1. **Data-Integrity Constraint Audit**: Identified domain invariants (observation/report causality, connector physical ownership, capacity-group uniqueness, moderation audit consistency, surrogate-key self-consistency, and ML lifecycle completeness).
2. **Index Optimization & Redundancy Review**: Replaced single-column reviews lookup with composite `(station_id, created_at DESC)`, added partial index for pending reports, provided SCD2 point-in-time index `idx_dim_station_effective`, and dropped 9 redundant/duplicate indexes across `public` and `ml`.
3. **ML Layer Inventory & FK-Supporting Review**: Confirmed `ml.experiments.dataset_key` lacked a DDL `REFERENCES` clause in Step 1.5 (added as intra-schema FK `fk_experiments_dataset`), added missing FK indexes on `ml.model_versions` (`training_dataset_key`, `eval_dataset_key`), and removed redundant ML indexes.
4. **Architectural Boundary Verification**: Verified strict isolation between operational OLTP (`public`), canonical warehouse OLAP (`analytics`), and ML metadata/control (`ml`).

---

## 2. Implemented Schema Changes in Step 1.6

### 2.1 Public Schema (`public` — Operational OLTP)

**Index Changes (4 dropped, 3 created):**
- **Dropped redundant indexes (4):**
  - `idx_reviews_station` (dropped to be replaced by composite below)
  - `idx_reviews_user` (covered by `uq_reviews_user_station(user_id, station_id)` leading col)
  - `idx_favorites_user` (covered by `pk_favorites(user_id, station_id)` leading col)
  - `idx_station_source_link_source` (covered by `uq_station_source_link_source_record(source_id, source_station_id)` leading col)
- **Created / Replaced indexes (3):**
  - `idx_reviews_station`: Composite index `(station_id, created_at DESC)` for station-detail reviews listing.
  - `idx_user_reports_pending`: Partial index `(created_at) WHERE moderation_status = 'pending'` for driver report moderation queue.
  - `uq_connectors_station_type_power`: Unique index on `(station_id, connector_type, power_kw, COALESCE(charging_standard, ''))` preventing duplicate static capacity groups.

**Integrity Constraints (13 ADD CONSTRAINT + 1 Unique Index = 14 constraints):**
1. `chk_observations_causal_time`: `received_at >= observed_at` on `station_observations`.
2. `chk_report_created_after_observed`: `created_at >= observed_at` on `user_reports`.
3. `uq_connectors_id_station`: Unique superkey on `connectors(station_id, id)` enabling composite connector ownership FKs.
4. `fk_observations_connector_owner`: Composite FK on `station_observations(station_id, connector_id)` referencing `connectors(station_id, id)`.
5. `fk_reports_connector_owner`: Composite FK on `user_reports(station_id, connector_id)` referencing `connectors(station_id, id)`.
6. `chk_user_reports_moderation_audit`: Pending has no decision fields; approved/rejected requires `moderated_at`.
7. `chk_user_reports_rejection_reason`: Rejected requires `moderation_reason`.
8. `chk_reviews_moderation_audit`: Pending has no decision fields; approved/rejected requires `moderated_at`.
9. `chk_reviews_rejection_reason`: Rejected requires `moderation_reason`.
10. `chk_stations_slug_format`: Safe token regex format `^[a-zA-Z0-9][a-zA-Z0-9_-]*$`.
11. `chk_operators_slug_format`: Safe token regex format `^[a-zA-Z0-9][a-zA-Z0-9_-]*$`.
12. `chk_alerts_threshold_positive`: Non-negative magnitude `threshold_value >= 0`.
13. `chk_source_link_seen_range`: `last_seen_at >= first_seen_at`.
*(Plus unique index `uq_connectors_station_type_power` enforcing capacity-group uniqueness).*

### 2.2 Analytics Schema (`analytics` — Data Warehouse OLAP)

**Index Changes (0 dropped, 1 created):**
- **Created SCD2 index (1):**
  - `idx_dim_station_effective`: Composite `(station_id, effective_from, effective_to)` on `analytics.dim_station` for historical point-in-time fact resolution.

**Integrity Constraints (10 ADD CONSTRAINT):**
14. `chk_dim_station_hours`: Mirrors `public.chk_stations_hours` on `analytics.dim_station`.
15. `chk_dim_date_self_consistent`: Enforces exact derivation of `date_key`, `year`, `quarter`, `month`, `week`, `day_of_month`, `day_of_week`, `is_weekend`, `month_name`, and `day_name` from `full_date` using strictly **IMMUTABLE** CASE and EXTRACT expressions (verified compatible with all 3,288 seeded date rows; avoids Postgres `42P17` errors from locale-dependent `to_char`).
16. `chk_dim_time_self_consistent`: Enforces `time_key = (hour * 4 + minute / 15)`, `slot_15min = lpad(...)`, and `time_of_day` bucket alignment (verified compatible with all 96 seeded time rows).
17. `chk_dim_connector_type`: Enforces parity with the Indian/international connector vocabulary (`CCS2`, `CHAdeMO`, `Type 2`, `Type 1`, `GB/T`, `Bharat AC001`, `Bharat DC001`).
18. `chk_fact_observation_causal_time`: `received_at >= observed_at` on `fact_station_observation`.
19. `chk_fact_observation_dim_alignment`: Enforces `date_key` and `time_key` alignment with `observed_at AT TIME ZONE 'UTC'`.
20. `chk_fact_report_dim_alignment`: Enforces `date_key` and `time_key` alignment with `observed_at AT TIME ZONE 'UTC'`.
21. `chk_fact_report_moderated`: Approved-only warehouse gate requires `moderated_at IS NOT NULL`.
22. `chk_fact_review_moderated`: Approved-only warehouse gate requires `moderated_at IS NOT NULL`.
23. `chk_fact_daily_status_counts`: Status count conservation `available_count + busy_count + broken_count <= observation_count`.

### 2.3 ML Schema (`ml` — Metadata & Control)

**Index Changes (5 dropped, 2 created):**
- **Dropped redundant/duplicate indexes (5):**
  - `ml.idx_ml_features_name` (exact duplicate of `UNIQUE (feature_name)`)
  - `ml.idx_ml_datasets_name` (exact duplicate of `uq_datasets_name_version (dataset_name, version_str)`)
  - `ml.idx_ml_modelversions_experiment` (covered by `uq_modelversions_experiment_version` leading col)
  - `ml.idx_ml_metrics_model` (covered by `uq_metrics_model_name_split` leading col)
  - `ml.idx_ml_predictionruns_model` (covered by `uq_predictionruns_model_station_datetime` leading col)
- **Created FK-supporting indexes (2):**
  - `idx_ml_modelversions_training_dataset`: Indexes `training_dataset_key` to support `ON DELETE SET NULL` scans and dataset-to-model joins.
  - `idx_ml_modelversions_eval_dataset`: Indexes `eval_dataset_key` to support `ON DELETE SET NULL` scans and dataset-to-model joins.

**Integrity Constraints (4 ADD CONSTRAINT):**
24. `fk_experiments_dataset`: Intra-ml foreign key linking `experiments.dataset_key` to `ml.datasets(dataset_key)` ON DELETE RESTRICT (fulfills Step 1.5 column comment intent).
25. `chk_experiments_lifecycle`: Enforces timestamp alignment with experiment status (`proposed` has no timestamps; `running`/`failed` have `started_at`; `completed` has both).
26. `chk_datasets_time_range`: `time_range_end >= time_range_start`.
27. `chk_model_ready_gate`: A model marked `ready` strictly requires `trained_at`, `completed_at`, `training_dataset_key`, and `eval_dataset_key`.

---

## 3. Mathematical Inventory Breakdown

| Metric | Public | Analytics | ML | Total |
|---|---|---|---|---|
| **ADD CONSTRAINT statements** | 13 | 10 | 4 | **27** |
| **Unique Indexes (Capacity)** | 1 | 0 | 0 | **1** |
| **Total Constraints Added** | **14** | **10** | **4** | **28** |
| **Baseline Indexes (1.3–1.5)** | 18 | 14 | 16 | **48** |
| **Indexes Dropped in 1.6** | 4 | 0 | 5 | **9** |
| **Indexes Created in 1.6** | 3 | 1 | 2 | **6** |
| **Retained Baseline Indexes** | 14 | 14 | 11 | **39** |
| **Final State Explicit Indexes** | **17** | **15** | **13** | **45** |

---

## 4. Verification & Safety Guarantees

All 12 validation requirements were verified:
1. **Static SQL validation**: Parentheses (132 balanced pairs), `DO $$` blocks (4 balanced pairs), and statement terminators cleanly validated.
2. **Verify no destructive statements**: 0 `DROP TABLE`, 0 `DROP COLUMN`, 0 `DROP SCHEMA`, 0 `TRUNCATE`, 0 `ALTER TABLE ... DROP CONSTRAINT`. Only safe `DROP INDEX IF EXISTS`.
3. **Verify no legacy table changes**: 0 executable statements referencing the 9 legacy `public.dim_*` or `public.fact_*` tables.
4. **Verify no frontend changes**: `src/` directory is 100% untouched (`npm run typecheck` passed with 0 errors).
5. **Verify no data insertion**: 0 `INSERT INTO`, 0 `UPDATE`, 0 `DELETE`.
6. **Verify all referenced tables/columns exist**: All 19 referenced tables and columns exist in Steps 1.3, 1.4, or 1.5.
7. **Verify no duplicate indexes**: Dropped 9 redundant/duplicate indexes; added 6 targeted, non-duplicate query/FK/SCD2 indexes.
8. **Verify constraints don't conflict**: All constraints reinforce documented invariants without contradicting existing rules.
9. **Dimension check immutability**: Verified `chk_dim_date_self_consistent` and `chk_dim_time_self_consistent` use strictly IMMUTABLE arithmetic and CASE logic (free of STABLE `to_char`).
10. **Seeded reference data verified**: All 3,288 date rows (2024-01-01…2032-12-31) and all 96 time slots (0..95) pass the constraints.
11. **Idempotency**: All constraints wrapped in `IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = ...)` inside `DO $$` blocks; indexes use `CREATE INDEX IF NOT EXISTS` and `DROP INDEX IF EXISTS`.
12. **Clean temp files**: All temporary test and audit scripts (`test_seeds.py`, `audit_indexes.py`, `count_inventory.py`, `tmp_step_1_6_validate.py`) removed.

---

## 5. Current Status & Next Step

- **Step 1.6 Status: EXECUTED + VERIFIED against linked Supabase project.**
  - *Execution History:* Initial execution attempt rolled back due to a false-positive cross-layer FK assertion joining `information_schema.referential_constraints` and `information_schema.constraint_column_usage` without matching schemas (colliding with legacy `public.dim_*` table constraints). Corrected to authoritative `pg_catalog` query. The second execution attempt succeeded completely as one atomic transaction.
  - *Verification Summary:*
    - Constraints: Public (13 ADD CONSTRAINT + 1 Unique Index = 14), Analytics (10 ADD CONSTRAINT), ML (4 ADD CONSTRAINT) = 28 total constraints verified.
    - Explicit Indexes: Public (17), Analytics (15), ML (13) = 45 explicit indexes verified.
    - 6 required new indexes verified present; 8 redundant indexes verified dropped.
    - Reference data intact (`analytics.dim_date` = 3,288 rows; `analytics.dim_time` = 96 rows).
    - Operational/analytics/ML tables and all 9 frozen legacy `public.dim_*` / `public.fact_*` tables verified at 0 rows.
    - Cross-layer FK count confirmed = 0 via `pg_constraint`.
- **Step 1.7 Status: EXECUTED + VERIFIED against linked Supabase project.**
  - Migration file: `supabase/migrations/20260924000001_step_1_7_rls_security_policies.sql`
  - 29 active target tables with RLS enabled (`public`=11, `analytics`=12, `ml`=6).
  - 29 explicit policies created on `public` schema; 0 client policies on `analytics` and `ml`.
  - Defense-in-depth: table/column privileges sanitized (`profiles.role` column write revoked from authenticated; normal users cannot tamper with moderation fields on `user_reports` or `reviews`; `user_reports` direct anonymous SELECT denied).
  - Legacy tables untouched (9 legacy tables remain with RLS disabled).
- **Next scheduled task: Step 1.8 — Add safe database views/functions where justified** (station_current_status, safe aggregation).

---

## References

- Migration files:
  - `supabase/migrations/20260918000001_step_1_3_core_operational_schema.sql`
  - `supabase/migrations/20260922000001_step_1_4_analytics_warehouse_schema.sql`
  - `supabase/migrations/20260922000001_step_1_5_ml_metadata_schema.sql`
  - `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`
  - `supabase/migrations/20260924000001_step_1_7_rls_security_policies.sql`
- Documentation:
  - `Must Read/Architecture.md`, `Must Read/Phases.md`, `Must Read/Memory.md`, `Must Read/Rules.md`
  - `docs/data_dictionary.md`, `docs/data_warehouse.md`, `docs/db+warehouse+ml.md`