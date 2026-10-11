# ChargePlus RLS / Role Verification Matrix (prepared — NOT EXECUTED)

Status: **BLOCKED — NOT EXECUTED** on current migration text. No Docker, no
disposable target is available in this environment, so no case below has been
run. This document is the procedure the operator runs on Route B
(disposable Supabase-hosted project, `supabase/README.md`).

Method per case (unless noted): `psql $DISPOSABLE_DATABASE_URL`,
`SET ROLE <role>`, and for authenticated cases
`SELECT set_config('request.jwt.claims','{"sub":"<uuid>"}',true)` matching a
seeded `public.profiles` row, then the probe query. Record ALLOW (row/rows
returned or write succeeds) vs DENY (0 rows / `permission denied` /
`new row violates row-level security policy`). Two-session cases use two
concurrent `psql` sessions. Rollback cases verify counts before/after.

Seed two test users (profiles rows A=user, B=user, C=admin) plus one station,
then delete all test rows afterwards; bootstrap counts must be restored.

## A. Anonymous (8)

| # | Probe | Expected |
|---|---|---|
| A1 | `SELECT` public.stations | ALLOW (public read policy) |
| A2 | `SELECT` public.operators / connectors / station_observations | ALLOW (public read policies) |
| A3 | `SELECT` public.data_sources | DENY (admin-only) |
| A4 | `SELECT` public.station_source_link | DENY (admin-only) |
| A5 | `SELECT` public.ingestion_runs | DENY (no anon grant, R5) |
| A6 | `SELECT` analytics.fact_station_observation | DENY (0 client policies) |
| A7 | `SELECT` ml.features | DENY (0 client policies) |
| A8 | `INSERT` public.stations | DENY (no insert policy for anon) |

## B. Authenticated own-row (7)

| # | Probe as A | Expected |
|---|---|---|
| B1 | `SELECT` own profiles row | ALLOW |
| B2 | `SELECT` B's profiles row | DENY |
| B3 | `UPDATE` own profiles row (non-role columns) | ALLOW |
| B4 | `UPDATE` own profiles row setting `role='admin'` | DENY (role guard trigger) |
| B5 | `INSERT/SELECT/DELETE` own favorites row | ALLOW / ALLOW / ALLOW |
| B6 | `SELECT` B's favorites rows | DENY |
| B7 | `INSERT` public.reviews + `SELECT` own unapproved review | ALLOW / ALLOW |

## C. Cross-user isolation (4)

| # | Probe | Expected |
|---|---|---|
| C1 | A `SELECT` B's user_reports | DENY |
| C2 | A `UPDATE` B's reviews row | DENY |
| C3 | A `DELETE` B's alerts row | DENY |
| C4 | A `SELECT` approved reviews (any author) | ALLOW (approved-visibility policy) |

## D. Administrator (6)

| # | Probe as C (role='admin') | Expected |
|---|---|---|
| D1 | `SELECT` public.data_sources | ALLOW |
| D2 | `SELECT` public.ingestion_runs | ALLOW (admin policy) |
| D3 | `SELECT` any user_reports / reviews (incl. unapproved) | ALLOW |
| D4 | `UPDATE` B's reviews row | ALLOW |
| D5 | `DELETE` any user_reports row | ALLOW |
| D6 | Ordinary user B `SELECT` ingestion_runs | DENY (admin-only) |

## E. Privilege escalation defense (3)

| # | Probe | Expected |
|---|---|---|
| E1 | B `UPDATE profiles SET role='admin' WHERE id=<self>` | DENY (trigger `trg_profiles_role_guard`) |
| E2 | B direct `GRANT` / `ALTER TABLE` attempt | DENY (no DDL privilege; revoked trigger/truncate) |
| E3 | anon `SELECT` from `auth.users` via crafted view call | DENY |

## F. service_role / server paths (3)

| # | Probe | Expected |
|---|---|---|
| F1 | service_role `INSERT` public.ingestion_runs (BYPASSRLS) | ALLOW |
| F2 | service_role `SELECT` analytics facts | ALLOW (bypass) |
| F3 | `get_author_display_name` SECURITY DEFINER executes for anon with `search_path='public, pg_temp'` | ALLOW, no privilege gain |

## G. Concurrency (2, two sessions)

| # | Probe | Expected |
|---|---|---|
| G1 | Concurrent duplicate favorites insert (same user/station) | exactly one wins; other gets unique violation |
| G2 | Concurrent identical `ingestion_runs` idempotency-key insert | exactly one row (`ON CONFLICT` no duplicates) |

## H. Rollback / recovery (2)

| # | Probe | Expected |
|---|---|---|
| H1 | Failed multi-statement ingestion batch rolls back fully | counts identical before/after |
| H2 | Re-apply of the failed migration file from its start converges (idempotent guards) | applies clean; assertions pass |

Total: 8+7+4+6+3+3+2+2 = **35 cases**. If first execution shows a schema
difference (e.g. the 29th public policy not covered above), update this file
and the static invariant test together — never silently.
