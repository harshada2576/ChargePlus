# ChargePlus — Pre-Phase-4 Remediation Gate Report

- **Phase:** Pre-Phase-4 remediation gate (Phase 4 NOT STARTED)
- **Previous phase:** Phase 3/6 — Connect the Locked Frontend (reported complete)
- **Branch:** `feature/phase-3-complete`
- **Principle:** hardening pass, not a rewrite. No architecture redesign, no Phase 4 work.

## 1. Remediation status

| Finding | Confirmed? | Fixed? | Verification | Remaining risk |
|---|---|---|---|---|
| R1 live authenticated write round-trip | Path traced, not live-proven | Code-verified only | RLS owner/admin policies traced; mocked tests assert denial propagation; sign-out clears state (`SessionProvider.tsx:124-139`) | Needs test identity + SMS provider + admin (see §4) |
| R2 scheduled ingestion | Workflow exists & correct | Static + offline proof | `.github/workflows/scheduled_ingestion.yml` matches canonical `--run-once`; fixtures dry-run 7→6 decisions, 0 writes | Recurring GitHub execution unverified from here |
| R3 duplicate migration version (`...22000001` × 2) | Yes | Renamed 1_5 → `...22000002...` (`git mv`); versions unique, order preserved | Version-uniqueness script; 1_5 fully `IF NOT EXISTS` | Live replay needs linked project; repair procedure below |
| R4 CCS1/`Other` vocab gap | Yes (CCS1 skippable, `Other` skipped) | DB CHECKs extended with CCS1; `ALLOWED_DB_CONNECTOR_TYPES` += CCS1; `Other` stays skipped (no honest value) | `tests/test_pre_phase4_gate.py` 4/4 (adapter→persist→allow-list parity) | None known |
| R5 `ingestion_runs` world-readable | Yes (`USING(true)`, anon grant) | Admin-only SELECT policy + anon grant revoked (migration `...27000002...`) | In-migration assertions; admin console queries via authenticated session (unaffected) | Must be applied to linked project |
| R6 `profiles.role` relies on column grants | Yes (update policy pins id only) | `trg_profiles_role_guard` trigger (migration `...27000003...`); RLS untouched | In-migration assertion; Phase 3 edits touch other columns only | Must be applied to linked project |
| R7 alert uniqueness app-only | Yes | Partial unique index (station-scoped) + `setAlert` 23505 recovery | Migration assertion + new `test_alerts.mjs` race test 7/7 | NULL-station alerts unconstrained by design |
| R8 dead code | Partially (audit over-claimed) | `STATIONS` alias + `getStation` deleted; `SavedClient` dead branch deleted; `supabase-test` route deleted; `persist_station` reclassified legacy-but-tested (11 test sites, zero production callers) | Full suites re-run (§5) | None |
| Run-state FAILED-vs-PARTIAL split | Yes (runner FAILED where orchestrator says PARTIAL) | Runner aligned: FAILED only on raise | New gate test asserts DB row PARTIAL on rejections | None |
| Advisory-lock local fallback on pg error | Yes | Fail-closed: pg error denies (CANCELLED downstream); local lock offline-only | 2 new gate tests; 32 scheduled tests green | None |
| Freshness STALE≠UNAVAILABLE | Verified intact, no fix | — | Adapter passes age through; UI pairs badge with recency; `busyWindows: []` | None |

### R3 repair procedure for the already-running project

The renamed file changes no schema content (1_5 is fully `IF NOT EXISTS`).
On the linked project, either (a) `supabase migration repair --status applied`
the old version and push (new version applies idempotently), or (b) mark
`20260922000002` applied if its objects already exist. Clean environments replay
the chain in order with unique versions (verified statically; live replay needs
a running Postgres + Supabase CLI — Docker daemon was unavailable here).

## 2. Database/migration verification (static; live apply pending)

- Versions unique (9 + 4 new = 13 files, monotonic). Ordering preserved.
- New migrations carry self-verifying assertion blocks (policy/trigger/index/vocab).
- RLS/grants/role/alerts covered in §1. Authenticated ownership + admin checks
  follow the existing `EXISTS (profiles.role='admin')` pattern; no new roles.

## 3. Ingestion verification

- Offline fixtures dry-run: 7 fetched → 7 parsed → 2 accepted + 5 warnings →
  6 decisions (1 REVIEW skipped) → 8 connectors, 1 observation, freshness 7/2 stale.
- Idempotency, provenance, SCD2 sync unchanged (covered by existing suites).
- Scheduler: canonical `--run-once` path, single-owner accounting intact
  (test_14–19 green), retry/backoff untouched.

## 4. Phase 3 verification (no behavior change except alerts race + dead-code removal)

Auth/profiles/favorites/reports/reviews/alerts/admin/loading-error-empty states:
statically re-verified; suites green. Live OTP delivery, authenticated writes,
and admin moderation still require a test identity + dashboard SMS provider +
admin role — explicitly **not claimed** here.

## 5. Test results (this gate)

- Python: `test_pre_phase4_gate.py` 6/6; `test_scheduled_ingestion.py` 32/32;
  full suite + others in final gate run (see session report).
- Node: `test_alerts.mjs` 7/7 (incl. new 23505 race test); full 12-file run in final gate.
- `tsc --noEmit`, `eslint`, `next build` in final gate.

## 6. What was NOT touched (out of scope)

Phase 4 warehouse, second source adapter, ML/forecasting, E2E framework,
rate limiting, APM, performance architecture. Historical log entries were not
rewritten (old migration filename in dated entries is history).
