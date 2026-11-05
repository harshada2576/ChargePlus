# Database Migration Ownership & Schema Authority Specification

## 1. Single Authoritative Migration Source of Truth

ChargePlus establishes **`supabase/migrations/`** as the single, authoritative, and version-controlled migration source of truth.

The database schema spans 29 owned tables across three PostgreSQL schemas:
- **`public` (11 tables)**: Operational transactional data (`stations`, `connectors`, `station_observations`, `data_sources`, `station_source_link`, `profiles`, `operators`, `user_reports`, `reviews`, `favorites`, `alerts`, plus `ingestion_runs`).
- **`analytics` (12 tables)**: Kimball star schema warehouse (`dim_station`, `dim_operator`, `dim_location`, `dim_connector`, `dim_date`, `dim_time`, `dim_source`, `dim_weather`, `fact_station_observation`, `fact_user_report`, `fact_review`, `fact_station_daily`).
- **`ml` (6 tables)**: ML feature store and lineage tracking (`features`, `datasets`, `experiments`, `model_versions`, `metrics`, `prediction_runs`).

---

## 2. Drizzle ORM Analysis & Conflict Decommissioning

### Codebase Audit Findings:
1. `drizzle.config.json` previously pointed to `src/db/schema.ts`.
2. `src/db/schema.ts` contains only `export {};` (no tables defined).
3. If a developer executed `drizzle-kit push`, Drizzle would compare its empty schema definition against the database and issue destructive `DROP TABLE` statements across all 29 tables.
4. An import scan across `src/` revealed that **no application queries use Drizzle ORM queries** (`db.query.*` or `db.select()`).
5. Only `pool` (raw `pg.Pool`) is used by Next.js route handlers (`src/app/api/admin/warehouse/route.ts`, `src/app/api/ml/status/route.ts`, `src/app/api/health/route.ts`).

### Authority Rule:
- **`supabase/migrations/` owns all schema evolution**.
- `drizzle-kit push` and Drizzle migrations are **strictly prohibited** in CI and production.
- `src/db/index.ts` remains strictly as a resilient connection pool provider (`pg.Pool`).

---

## 3. Migration Inventory & Execution Order

All 14 migration files must execute in strict alphanumeric order:

| Step | Migration File | Target Schema / Responsibility |
| :---: | :--- | :--- |
| **01** | `20260918000001_step_1_3_core_operational_schema.sql` | `public` core tables, PostGIS extensions, enums |
| **02** | `20260922000001_step_1_4_analytics_warehouse_schema.sql` | `analytics` Kimball star schema dimension & fact tables |
| **03** | `20260922000002_step_1_5_ml_metadata_schema.sql` | `ml` schema tables, feature store, model lineage |
| **04** | `20260923000001_step_1_6_constraints_indexes.sql` | Spatial GiST indexes, foreign keys, unique constraints |
| **05** | `20260924000001_step_1_7_rls_security_policies.sql` | 29 RLS policies on `public`; 0 client policies on `analytics`/`ml` |
| **06** | `20260925000001_step_1_8_views_functions.sql` | PostGIS spatial queries, view definitions, helper functions |
| **07** | `20260926000001_step_2_10_ingestion_runs.sql` | Idempotent `ingestion_runs` table and audit logging |
| **08** | `20260926000002_step_2_10_ingestion_runs_grants.sql` | Least-privilege role permissions |
| **09** | `20260926000003_step_2_12_connector_unknown_power.sql` | Connector schema hardening |
| **10** | `20260927000001_pre_phase4_connector_ccs1_vocab.sql` | Plug type standard vocabulary |
| **11** | `20260927000002_pre_phase4_ingestion_runs_admin.sql` | Ingestion admin policy guards |
| **12** | `20260927000003_pre_phase4_profiles_role_guard.sql` | Profile RBAC security guards |
| **13** | `20260927000004_pre_phase4_alerts_uniqueness.sql` | Alert deduplication indexes |
| **14** | `20260928000001_phase4_dim_connector_null_power.sql` | Analytics dimension nullability hardening |

---

## 4. Standalone Migration Runner (`backend/warehouse/migrate.py`)

To eliminate hard dependencies on the Supabase CLI in offline, CI, and local Docker environments, ChargePlus includes a dedicated migration runner:

```powershell
python backend/warehouse/migrate.py
```

### Safety & Operational Features:
- **`_schema_migrations` Table**: Idempotently tracks applied migrations. Skips already applied migrations upon replay.
- **Fail-Closed Guard**: Invokes `require_disposable_target(DATABASE_URL)`. Throws `UnsafeDatabaseTarget` if attempting to target non-loopback hosts without explicit `CHARGEPLUS_DISPOSABLE_DB=1` confirmation.
- **Atomic Transactions**: Each migration executes within an explicit transaction block, committing only upon complete statement success.

---

## 5. Migration Replay & Invariant Verification

Static invariants over the migration suite are pinned in `tests/test_migration_static_invariants.py`:
- Asserts strict ordering of all 14 files.
- Asserts RLS is enabled on all 29 owned tables across `public`, `analytics`, and `ml`.
- Asserts zero client-facing policies exist on `analytics.*` or `ml.*`.
- Asserts least-privilege service-role constraints.
- Asserts unit test coverage of runner in `tests/test_migrate.py`.
