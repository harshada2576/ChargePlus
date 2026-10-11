# Local Supabase database lifecycle

This directory is the supported clean-clone database entry point for ChargePlus.
The local project is identified by `project_id = "chargeplus-local"` in
[`config.toml`](./config.toml); it is not a cloud Supabase project reference.

## Migration order and dependencies

Supabase applies migration files in lexicographic filename order. The current
order and object dependencies are:

| Order | Migration | Depends on | Owns |
| --- | --- | --- | --- |
| 1 | `20260918000001_step_1_3_core_operational_schema.sql` | PostGIS and pgcrypto extensions | `public` operational tables, geometry trigger, base indexes |
| 2 | `20260922000001_step_1_4_analytics_warehouse_schema.sql` | extensions only | `analytics` schema, 8 dimensions, 4 facts, deterministic `dim_date`/`dim_time` reference rows |
| 3 | `20260922000002_step_1_5_ml_metadata_schema.sql` | pgcrypto | `ml` schema and its 6 metadata tables |
| 4 | `20260923000001_step_1_6_constraints_indexes.sql` | steps 1.3-1.5 tables and indexes | cross-column constraints and final indexes |
| 5 | `20260924000001_step_1_7_rls_security_policies.sql` | steps 1.3-1.5 tables | grants, RLS, and 29 public policies |
| 6 | `20260925000001_step_1_8_views_functions.sql` | steps 1.3-1.7 views/tables/policies | public and analytics views/functions |
| 7 | `20260926000001_step_2_10_ingestion_runs.sql` | `public.data_sources` from step 1.3 | `public.ingestion_runs`, indexes, final admin/service policies |
| 8 | `20260926000002_step_2_10_ingestion_runs_grants.sql` | step 2.10 table | least-privilege table grants and repeated admin policy hardening |
| 9 | `20260926000003_step_2_12_connector_unknown_power.sql` | connector tables and indexes | nullable connector power semantics |
| 10 | `20260927000001_pre_phase4_connector_ccs1_vocab.sql` | connector tables and step 1.6 connector constraint | CCS1 vocabulary parity |
| 11 | `20260927000002_pre_phase4_ingestion_runs_admin.sql` | `public.ingestion_runs` | final admin-only ingestion-run read policy |
| 12 | `20260927000003_pre_phase4_profiles_role_guard.sql` | `public.profiles` | profile role protection trigger |
| 13 | `20260927000004_pre_phase4_alerts_uniqueness.sql` | `public.alerts` | station-scoped alert uniqueness |
| 14 | `20260928000001_phase4_dim_connector_null_power.sql` | `analytics.dim_connector` | warehouse nullable-power parity |

The `public.dim_*` and `public.fact_*` names described as legacy in migration
comments are not bootstrap dependencies. No migration in this repository creates
them. A clean clone therefore does not create placeholder legacy tables.
`analytics.*` is the warehouse layer; `ml.*` is metadata/control; neither uses
cross-layer foreign keys.

## Clean local bootstrap

Prerequisites (Docker-free workflow — no Docker Desktop, no `supabase start`):

- Supabase CLI installed and available as `supabase` (used for `link`, `db push`, `migration list`; the local daemon is not used).
- `psql` client and Python with `psycopg2` (covered by `requirements.txt`) for ordered applies and checks.
- No cloud production project is used by any command below. Disposable targets only.

## Docker-free verification routes (BLOCKED — NOT EXECUTED on current migration text)

No route below has been run against the current migration files. Do not claim
verification until real results exist.

**Route B (full verification — required for RLS/role claims): dedicated
disposable Supabase-hosted project.** Native PostgreSQL cannot supply the
`auth` schema (`auth.uid()`), managed roles, or PostGIS-backed Supabase
behavior the RLS matrix depends on. From the repository root:

```powershell
supabase link --project-ref <disposable-project-ref>
supabase db push
supabase migration list
```

Then run the post-bootstrap checks below, the repeatability run (fresh
disposable project or full revert + push), the canonical integration suite,
and the 35-case RLS/role matrix. Never use a production or ordinary staging
`DATABASE_URL` for these destructive tests; the test suite refuses
non-loopback targets unless ALL of `CHARGEPLUS_TEST_DB_HOSTS` (exact host
allowlist), `CHARGEPLUS_DISPOSABLE_DB=1` (explicit disposable intent), and —
for Supabase hosts — `CHARGEPLUS_DISPOSABLE_PROJECT_REF` (exact project-ref
match) are configured, enforced by `tests/db_target_guard.py`. An allowlist
alone is never proof of disposability; verify the disposable project identity
(operator confirmation + `supabase migration list` on the linked project)
before authorizing any remote write. A non-destructive preflight is available
anytime (prints only the sanitized host verdict, never connects, never prints
credentials): `python tests/db_target_guard.py --preflight` (exit 0 ALLOW,
exit 2 DENY; refuses on ambiguity).

**Route A (partial verification — no Supabase project): isolated native
PostgreSQL 17 with the PostGIS extension**, plus `CREATE ROLE
anon/authenticated/service_role` and an `auth` schema stub sufficient for
`CREATE POLICY` to resolve `auth.uid()`. Apply the 14 files in filename order
with `psql -v ON_ERROR_STOP=1 -f`. This verifies DDL, constraints, reference
rows, and the owner-connection integration suite, but **not** RLS-by-role
behavior — Route B is still required before any staging claim.

The only rows expected from migrations are
the deterministic `analytics.dim_date` and `analytics.dim_time` reference
dimensions. Do not put operational station, observation, pricing, availability,
review, or telemetry records in a seed file.

`supabase db reset` requires the Docker-backed local stack and is **not**
available in this workflow; re-provision a fresh disposable target instead for
repeatability runs. `supabase db reset` is a destructive local test operation only.

## Required post-bootstrap checks

Use the disposable target's verified connection string (loopback or explicitly
allowlisted host — never production) and run read-only
catalog checks for:

- RLS enabled on the 11 `public`, 12 `analytics`, and 6 `ml` owned tables.
- 29 policies on the 11 public operational tables.
- No policies on `analytics` or `ml`, and no cross-layer foreign keys.
- `public.ingestion_runs`: authenticated/anon table grants are SELECT-only,
  with the admin-only RLS policy; service-side writes use `service_role`.
- Indexes and constraints from steps 1.6, 2.12, R4, R7, and 4.1.
- `analytics.dim_date` has 3,288 rows and `analytics.dim_time` has 96 rows.
- No operational rows were manufactured by bootstrap.
- Legacy public tables are absent on a clean clone unless supplied by an
  external legacy installation; if present, migrations only assert that they
  remain untouched and empty.

## Partial-failure recovery

First inspect the local migration history and the failing SQL error:

```powershell
supabase migration list
```

then re-provision a fresh disposable target and re-apply from zero
(`supabase db reset` needs Docker and is unavailable in this workflow).

For a disposable target, re-provisioning is the supported recovery path. It
recreates the instance and reruns the ordered set from zero.

For a non-disposable database, do **not** wipe and reapply. Preserve the error,
inspect `supabase_migrations.schema_migrations`, and determine whether the
failed migration committed any statements. PostgreSQL statements in these files
are intended to be replay-safe where practical (`IF EXISTS`, `IF NOT EXISTS`,
and policy replacement), but a migration history row must not be marked applied
manually. Nontransactional effects such as index creation or statements
committed before a failure require an object-level reconciliation and a reviewed
forward-fix migration. Take a backup/snapshot according to the operator's
restore procedure before attempting recovery.

The repository does not claim cloud parity, restore readiness, or production
recovery safety from local bootstrap evidence. The cloud Supabase project is
never a test target for this procedure.
