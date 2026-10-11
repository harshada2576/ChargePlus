# Database Migration Recovery Guide

ChargePlus migration files are written to be idempotent (`IF NOT EXISTS` /
`DROP IF EXISTS` / `CREATE OR REPLACE` / existence-guarded assertions), so a
failed file can usually be re-applied as a whole. Supabase tracks migration
history per *file* (not per statement): `supabase db push` does **not** detect
already-applied components inside a file or skip them — it re-runs the file,
and safety comes from the files' own idempotency guards, not from the CLI.

## Recovery Procedure

If a migration fails partway through a **disposable** target:
1. Address any underlying issue (connection problems, etc.)
2. Inspect `supabase_migrations.schema_migrations` and the failing SQL error to
   determine whether the failed file committed any statements.
3. Re-run the migration: `supabase db push`
4. The re-run re-executes the failed file from its start; idempotent guards
   make already-applied objects no-ops, and the file's assertions re-validate
   the end state.

For a **non-disposable** database: do NOT wipe and reapply. Take a
backup/snapshot first (see `docs/production.md` §8), then reconcile at object
level — nontransactional effects (index builds, statements committed before a
failure) may need a reviewed forward-fix migration, and a history row must
never be marked applied manually. See `supabase/README.md` ("Partial-failure
recovery") for the full procedure.

## Why Re-running Works (and Its Limits)

- All CREATE statements use `IF NOT EXISTS`
- All DROP/CREATE pairs use `DROP IF EXISTS` before creation
- All CREATE OR REPLACE for functions/views
- Assertions are conditional on object existence where order-independence requires it
- Unconditional assertions (policy counts, reference row counts, RLS posture)
  re-validate the end state on every run instead of assuming it

Limits: replay is safe only in file order and only for the cases above. The
grants file (`..._step_2_10_ingestion_runs_grants.sql`) must NOT be replayed
after the later R5 hardening (`20260927000002_pre_phase4_ingestion_runs_admin.sql`):
it re-grants anon SELECT and its own assertion expects the pre-R5 posture.
Replay the ordered set from the failed file forward; never cherry-pick a
single earlier file ahead of later ones.

No manual cleanup or wipe-and-reapply needed on a disposable target — simply
re-run the migration. Non-disposable targets always require the
backup-first procedure above.