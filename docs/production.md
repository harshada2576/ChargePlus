# ChargePlus — Production Operations (Phase 6)

## 1. Deployment

- **Web Runtime:** Docker image (`Dockerfile`, Node 22, deployment-only and optional) or any Node 22 host. Docker is not used in development or CI.
  Build: `npm ci && npm run build`. Start: `npm run start` (port 3000).
  Pre-configured build args (`ARG NEXT_PUBLIC_SUPABASE_URL`, `ARG NEXT_PUBLIC_SUPABASE_ANON_KEY`)
  allow standalone Docker builds to succeed reproducibly without leaking secrets.
- **Python Environment:** Pinned reproducible manifest in `requirements.txt`:
  `pydantic==1.10.22`, `python-dotenv==1.2.2`, `requests==2.33.0`,
  `psycopg2-binary==2.9.10`, `pytest==9.0.3`, `pytest-asyncio==1.4.0`.
- **Scheduled Automation:** GitHub Actions (`.github/workflows/scheduled_ingestion.yml`)
  defines a six-hour schedule and a manual dispatch:
  `Ingestion (runner.py)` → `Warehouse ETL (etl.py)` → `Data Quality (quality.py)` → `Maturity Gate (maturity.py)`.
  Scheduled execution is disabled unless `SCHEDULED_INGESTION_ENABLED=true` is
  configured. The job targets the `staging-ingestion` environment and uses
  `STAGING_*` secrets; dry-run is the default. The workflow file must be on the
  default branch for GitHub's scheduler to load it. This repository configuration
  does not claim that a live workflow has executed.
- **CI/CD:** `.github/workflows/ci.yml` runs full validation on every commit:
  Node typecheck (`tsc --noEmit`), ESLint (`eslint .`), Node unit tests (`npm test` — 135 tests: 134 pass, 1 environment-gated skip),
  Next.js production build (`npm run build` — 21 routes), Python test suite (`pytest tests/ -q --ignore=tests/test_canonical_postgres_integration.py` — 462 passed, 3 skipped; live-PostgreSQL module excluded locally). Container image builds are a deployment-time concern only, not a CI gate.
- **Rollback:** Redeploy previous image tag (or previous Node build). Migrations are non-destructive and
  idempotent (`IF NOT EXISTS` / `ON CONFLICT` / guarded blocks). Reverse migrations are applied
  forward via new migration files, never by mutating applied history.
- **Migrations:** Applied in filename order via `supabase db push` against a Supabase-managed database only (required: `anon`/`authenticated`/`service_role` roles, `auth` schema, PostGIS/pgcrypto — bare PostgreSQL is not sufficient). For a clean local clone use `supabase start` + `supabase db reset` per `supabase/README.md`. Execution of the current migration text is unverified (BLOCKED — not executed).

## 2. Environment & Secrets Classification

| Variable | Scope | Required | Purpose |
|---|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Public (browser) | Yes | Supabase endpoint |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public (browser) | Yes | RLS-governed anon client key |
| `DATABASE_URL` | Server-only | Yes | Privileged connection pool for health check & Python jobs |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only | Yes | Admin API route authorization & bypass RLS |
| `OPENCHARGEMAP_API_KEY` | Server-only | Yes | Live external station ingestion |

Rules:
1. Only `NEXT_PUBLIC_*` is bundled into client code.
2. Server-only keys (`DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENCHARGEMAP_API_KEY`) never reach the browser.
3. `.env*.local` is strictly git-ignored.
4. `.env*.bak` backups and `.playwright-mcp/` browser artifacts are git-ignored (local-only, never committed).
4. Python logger scrubs credentials via `_scrub_secrets`.

## 3. Domain & Authentication Checklist (Supabase Dashboard)

- [ ] Production URL set as Site URL in Supabase Auth Settings.
- [ ] Auth redirect allow-list includes `/verify` callback.
- [ ] Phone SMS provider (Twilio/MessageBird) configured for SMS OTP delivery.
- [ ] Email OTP templates reviewed and customized.
- [ ] Supabase Auth rate limits enabled alongside in-app limits (§5).

## 4. Security Posture & RLS Inventory

- **Secrets Boundary:** Server-only isolation audited; 0 secret leaks in git or build bundles.
- **XSS & Markup Safety:** MapLibre popup contents sanitized via `escapeHtml`; URL params encoded.
- **Authentication & Authorization:** Phone/Email OTP via Supabase Auth; admin endpoints enforce server-side token verification and `profiles.role = 'admin'`.
- **Role Escalation Defense:** Column-level privilege restriction + BEFORE UPDATE trigger `trg_profiles_role_guard` prevents non-admin callers from self-promoting.
- **RLS Coverage:** RLS enabled on all 29 core tables + `public.ingestion_runs`. Exactly 29 public RLS policies on the 11 operational tables, plus on `ingestion_runs` 1 admin-only SELECT policy and 1 service_role write policy (31 public policies total), and 0 client policies on `analytics` and `ml` (default deny-all to client roles; ETL bypasses via service role).

## 5. Abuse Controls & Rate Limiting

- **In-App Token Bucket (`src/lib/rateLimit.ts`):**
  - Admin Warehouse API (`/api/admin/warehouse`): 60 requests/min per credential (`429 Too Many Requests` + `Retry-After`).
  - Health check API (`/api/health`): 300 requests/min per client IP.
- **Boundary:** Per-instance in-memory token bucket; prevents memory denial-of-service without adding Redis dependencies. Edge-level rate limiting (Cloudflare/Vercel) recommended for multi-instance clusters.
- **Browsing:** Anonymous station browsing is unthrottled beyond the health ceiling; write paths require authentication and RLS ownership.

## 6. Observability & Alerting

- **Structured Server Logs (`src/lib/serverLog.ts`):** Emits JSON lines to stdout with timestamp, level (`info`, `warn`, `error`), `service: "chargeplus-web"`, `event`, and scrubbed context. Never logs tokens or credentials.
- **Health Endpoint (`/api/health`):** Verifies live database connectivity via `SELECT 1`. Throttled at 300 req/min; returns `500` and logs `health.db_unreachable` if database is down.
- **Ingestion & ETL Observability:**
  - Every run is tracked in `public.ingestion_runs` (`SUCCEEDED`, `PARTIAL`, `FAILED`, `CANCELLED`).
  - Runner fails closed and exits with non-zero exit code on failure, preventing silent data stagnation.
  - Failures are surfaced live in the `/admin` console dashboard.
- **Workflow Failure Diagnostics:** A failed run emits a sanitized diagnostic step
  linking the GitHub Actions run. This is log/run-history visibility, not an
  external notification. Configure and test a repository-owned notification
  destination separately before claiming alerting coverage.
- **External Monitoring Recommendation:** Connect `/api/health` to an uptime monitor (BetterStack, UptimeRobot, or AWS Route 53 Health Checks) for 1-minute interval pinging with PagerDuty/SMS alerts. No destination is configured by this repository.

### Alert coverage: implemented vs external (all external rows BLOCKED until configured)

| Signal | Implemented in repo | Requires external config |
|---|---|---|
| Ingestion/ETL/DQ/maturity failure | Non-zero exit + sanitized failure-diagnostics step with run URL | Notification delivery (email/Slack/PagerDuty) to repo owners |
| `/api/health` DB-down (`health.db_unreachable`) | JSON log line + HTTP 500 | Uptime monitor pinging + paging |
| Auth/OTP delivery failure | Server-side error returned to client | SMS provider (Twilio/MessageBird) + Supabase config |
| Database errors (RLS denials, constraint violations) | Structured server logs, no secret leakage | Log aggregation + alert rules |

## 7. Automated Ingestion & Warehouse Pipeline

Pipeline flow (Option A — chained execution):
```text
OpenChargeMap API
       ↓
Ingestion Runner (runner.py)
  - Acquires pg_advisory_lock
  - Normalizes & validates records
  - Persists canonical stations & connectors
  - Records execution in public.ingestion_runs
       ↓ (only if ingestion succeeds)
Warehouse ETL (etl.py)
  - Idempotent SCD2 dimension sync
  - Conformed observation & report facts loading
  - Daily aggregations derivation
  - Records run in public.ingestion_runs (source='warehouse_etl')
       ↓ (only if ETL succeeds)
Warehouse Data Quality Checks (quality.py)
  - Runs all 24 DQ rules (referential integrity, duplicate grains, aggregates, null semantics, reconciliation)
  - Records a stage result as source_name='warehouse_dq'
       ↓ (only if DQ passes)
Warehouse Data Maturity Check (maturity.py)
  - Assesses temporal observation depth and gates ML feasibility
  - Records a stage result as source_name='warehouse_maturity'
```

Failure Guarantees:
- If ingestion fails, warehouse ETL is **skipped** (no corruption of analytics facts).
- If ETL fails, data quality checks halt and workflow fails.
- If DQ fails, maturity is skipped and the workflow exits non-zero.
- A zero-result ingestion (source returned no records) is recorded as `PARTIAL`
  with an explicit error summary, never `SUCCEEDED`: an empty response is
  indistinguishable from a source outage, so the run must not claim success.
- Stage accounting (ETL/DQ/maturity) is fail-closed: if the
  `public.ingestion_runs` write fails, the stage exits non-zero instead of
  reporting success with a lost audit record.
- COLD/WARMING/READY are evidence states; COLD is not an execution failure.
- All writes are idempotent with `ON CONFLICT` constraints.
- Shared bounded DB connect (`backend/ingestion/persistence.py:connect_database`, used by
  ingestion persistence, ETL, DQ, maturity): 10s connect, 30s statement, 10s lock timeout.
  Ceiling: the 30s statement timeout can kill long ETL fact/daily builds on a large
  warehouse — smoke-test staging before raising limits.
- `--dry-run` (runner, ETL, DQ, maturity) skips `public.ingestion_runs` writes and reports
  `run_id: null`; the scheduled workflow propagates the dry-run flag to all four stages.
- Runner CLI exits non-zero on any non-`SUCCEEDED` state (including `PARTIAL`), so a
  zero-record `PARTIAL` run fails the workflow step by design (fail-closed).
- `public.ingestion_runs` is reused for warehouse stages (`source_id=None`,
  `scope=warehouse:*`, `source_name=warehouse_etl|warehouse_dq|warehouse_maturity`;
  historic table COMMENT still reads "scheduled and manual"). The `/admin` console selects
  `ingestion_runs` unfiltered, so warehouse stage rows appear next to source runs.

### Staging operator checklist (workflow stays disabled by default; do not trigger yet)

1. Create/select the `staging-ingestion` environment; set `STAGING_DATABASE_URL`,
   `STAGING_SUPABASE_SERVICE_ROLE_KEY`, `STAGING_OPENCHARGEMAP_API_KEY` as
   environment secrets (never commit them). Leave `SCHEDULED_INGESTION_ENABLED`
   unset and `ALLOW_STAGING_WRITES=false`, `SCHEDULED_INGESTION_DRY_RUN=true`.
2. Validate the environment: confirm the secrets point at the disposable
   staging project (not production) via the Supabase dashboard project ref.
3. Run once via `workflow_dispatch` with `dry_run=true`; review ingestion
   source/limit/scope, ETL, DQ (24 rules), maturity, and accounting outcomes in
   the run logs and `public.ingestion_runs`.
4. Authorize a staging write separately and explicitly: set
   `ALLOW_STAGING_WRITES=true`, re-run with `dry_run=false`, verify rows, then
   revert the flag. Each non-dry-run requires fresh authorization.
5. Failure triage: a failed run exits non-zero with a sanitized diagnostic step
   linking the run (see Failure diagnostics step). Check stage logs in order
   (ingestion → ETL → DQ → maturity), fix the failing stage's input/config,
   and re-run; never mark a failed run successful by editing history.

### Manual staging E2E (blocked — no staging environment configured)

OTP/auth login, station search/map render, filters, station details, favorites,
reports/reviews submission, admin console + access restrictions, and one
dry-run ingestion→ETL→DQ→maturity cycle. Record run IDs, screenshots/log
excerpts, and pass/fail per step in the §13 evidence checklist.

## 8. Backup & Disaster Recovery Runbook

| Attribute | Specification |
|---|---|
| **Backup Source** | Supabase Managed PostgreSQL Automated Backups (pg_dump + WAL-G) |
| **Backup Frequency** | Daily automated snapshots (00:00 UTC) + Continuous WAL archiving (Pro PITR) |
| **Retention** | 7 days (Free tier); 7–30 days (Pro / Team tier) |
| **PITR Availability** | Available on Supabase Pro via Dashboard → Database → Backups → Point-in-time Recovery |
| **Restore Authority** | Project / Organization Administrator via Supabase Dashboard or CLI |
| **RTO (Recovery Time Objective)** | < 30 minutes for snapshot restore; < 60 minutes for clean project recreation |
| **RPO (Recovery Point Objective)** | < 24 hours for daily snapshots; < 2 minutes with PITR |
| **Failure Assumptions** | Cloud region outage, catastrophic database corruption, accidental table deletion |

### Restore Procedure:
1. **Initiate Restore:**
   - In Supabase Dashboard: Navigate to **Database** → **Backups**.
   - Select the target snapshot or point in time and click **Restore**.
   - For disaster recovery to a clean project: Export snapshot via `supabase db dump` and import into target instance:
     ```bash
     psql "$NEW_DATABASE_URL" < backup_dump.sql
     ```
2. **Post-Restore Migration Alignment:**
   - Verify all migrations in `supabase/migrations/` are applied:
     ```bash
     supabase db push
     ```
3. **Post-Restore Validation Checklist:**
   - Execute PostgreSQL integration suite:
     ```bash
     python -m pytest tests/test_canonical_postgres_integration.py -v
     ```
   - Execute 24-rule Warehouse Data Quality suite:
     ```bash
     python -m backend.warehouse.quality
     ```
   - Verify reference dimension row counts:
     - `analytics.dim_date`: exactly 3,288 rows
     - `analytics.dim_time`: exactly 96 rows
   - Verify RLS is enabled on all 29 target tables + `public.ingestion_runs`.
   - Verify `/api/health` returns `{"ok": true}`.
- **Verification Status:** Documentation and verification procedures complete; live production destructive restore verification classified as **ENVIRONMENTAL** (preserving live database state).

### Restore-rehearsal checklist (blocked — requires a disposable target)

1. Provision a separate disposable Supabase project (never production, never the
   staging-ingestion project holding valuable data).
2. Take a fresh backup (`supabase db dump`), record start time, restore into the
   disposable target, record end time (duration evidence).
3. Verify: all 14 migrations accounted for (`supabase migration list`), run
   `supabase/verify_final_state.sql` (all checks match expected), spot-check
   `analytics.dim_date`=3288 / `dim_time`=96, `/api/health` returns `{"ok": true}`.
4. Record results (duration, check outputs, pass/fail) in the §13 evidence
   checklist. A rehearsal that skips step 3 is not a rehearsal.

## 9. Performance Characteristics (Unverified — do not quote as measured)

> No supporting evidence for the figures below exists in this repository
> (verified 2026-10-11: no latency evidence under `docs/testing/evidence/`).
> Treat them as historical single-sample observations, not certified
> measurements. Certify via a staging performance harness (throughput, error
> rate, p50/p95/p99, CPU/memory) before any beta/production claim.

- `v_station_current_state`: ~11 ms latency (16 stations, spatial + connector join).
- `v_station_connectors`: < 1 ms latency.
- `analytics.v_station_daily_summary`: ~1 ms latency.
- Admin pending reports query: < 1 ms latency.
- `nearby_stations(1km)`: ~280 ms server-side on 16 rows. **Note:** Currently UNUSED by frontend (client-side Haversine is used); flagged as a **Future Scaling Boundary** before adopting for >1,000 stations.
- No N+1 query patterns: Frontend uses `Promise.all` for parallel batches; admin dashboard uses single aggregate calls.

## 10. Compatibility & Responsive Design

- **Static Verification:** Clean viewport metadata, fluid CSS Grid / Flexbox layouts, touch targets >= 44px, bottom navigation for mobile viewports, safe empty/loading/error state boundaries throughout.
- **Device Lab Verification:** Marked **ENVIRONMENTAL** (physical mobile hardware testing pending user beta).

## 11. Data Honesty Invariants (Locked)

1. **Unknown != Zero / Free / Unavailable:** Missing power remains `null` (never 0 kW); missing price remains `null` (never ₹0); missing availability remains `null` (never 'unavailable').
2. **Stale != Unavailable:** Outdated observations preserve their original timestamp and are paired with "last updated" indicators.
3. **Operational != Available:** Static equipment status ("Operational") is never converted to live plug availability.
4. **Prediction != Observation:** ML contracts return `NO_MODEL` while warehouse is COLD; no synthetic predictions or fake busy hours are served.

## 12. Public Beta Sign-Off Matrix

| Capability | Code | Unit Tests | Integration | CI | Live | Production Status |
|---|---|---|---|---|---|---|
| Database Schema & PostGIS | PASS | PASS | PASS | PASS | PASS | PASS |
| Row-Level Security (RLS) | PASS | PASS | PASS | PASS | PASS | PASS |
| Supabase Auth / OTP | PASS | PASS | PASS | PASS | ENVIRONMENTAL (SMS provider) | PASS (Gated) |
| Ingestion Pipeline | PASS | PASS | PASS | PASS | PASS (8 MMR stations) | PASS |
| Warehouse ETL & Aggregates | PASS | PASS | PASS | PASS | PASS (Idempotent) | PASS |
| Warehouse Data Quality (24 rules) | PASS | PASS | PASS | PASS | PASS (24/24 PASS) | PASS |
| ML Feasibility & Gating | PASS | PASS | PASS | PASS | PASS (COLD pass) | PASS (Correctly Blocked) |
| Frontend UX & Responsive Layout | PASS | PASS | PASS | PASS | ENVIRONMENTAL (Device lab) | PASS |
| Docker image (deployment-only, optional; not in dev/CI) | PASS | PASS | PASS | Removed (Docker-free CI) | ENVIRONMENTAL (No daemon) | PASS |
| Rate Limiting & Logging | PASS | PASS | PASS | PASS | PASS | PASS |
| Backup & Recovery Runbook | PASS | PASS | PASS | PASS | ENVIRONMENTAL (Live restore) | PASS |

## 13. Release Evidence Checklist (all rows BLOCKED until executed with evidence)

| Gate | Owner | Action | Evidence required |
|---|---|---|---|
| Migration clean-apply + repeatability | DBA/operator | Route B on disposable project (§8, `supabase/README.md`) | `db push` logs, `verify_final_state.sql` outputs, `migration list` |
| RLS/role matrix 35 cases | DBA/operator | `docs/testing/ROLE_MATRIX.md` on disposable project | per-case ALLOW/DENY log, counts restored |
| Canonical integration suite (6 tests) | Operator | Guard-verified disposable target only | pytest output, target-identity record |
| Staging dry-run + authorized write | Operator | §7 checklist | workflow run IDs, `ingestion_runs` rows |
| Staging manual E2E | QA | §7 E2E steps | step-by-step pass/fail + screenshots |
| Restore rehearsal | DBA/operator | §8 rehearsal checklist | duration, verification outputs |
| Alert delivery | Operator | Configure monitor + notification; trigger test failure | delivered alert artifact |
| SMS/OTP provider | Operator | Configure Twilio/MessageBird; end-to-end OTP login | successful OTP login log |
| Measured performance | Perf owner | Staging harness (p50/p95/p99, error rate) | harness report (replaces §9 estimates) |
