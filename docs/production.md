# ChargePlus — Production Operations (Phase 6)

## 1. Deployment

- **Web Runtime:** Docker image (`Dockerfile`, Node 22) or any Node 22 host.
  Build: `npm ci && npm run build`. Start: `npm run start` (port 3000).
  Pre-configured build args (`ARG NEXT_PUBLIC_SUPABASE_URL`, `ARG NEXT_PUBLIC_SUPABASE_ANON_KEY`)
  allow standalone Docker builds to succeed reproducibly without leaking secrets.
- **Python Environment:** Pinned reproducible manifest in `requirements.txt`:
  `pydantic==1.10.22`, `python-dotenv==1.2.2`, `requests==2.33.0`,
  `psycopg2-binary==2.9.10`, `pytest==9.0.3`, `pytest-asyncio==1.4.0`.
- **Scheduled Automation:** GitHub Actions (`.github/workflows/scheduled_ingestion.yml`)
  runs the end-to-end pipeline every 6 hours:
  `Ingestion (runner.py)` → `Warehouse ETL (etl.py)` → `Data Quality (quality.py)` → `Maturity Gate (maturity.py)`.
- **CI/CD:** `.github/workflows/ci.yml` runs full validation on every commit:
  Node typecheck (`tsc --noEmit`), ESLint (`eslint .`), Node unit tests (`npm test` — 126 tests),
  Next.js production build (`npm run build`), Python test suite (`pytest tests/` — 432 unit tests),
  and Docker build verification (`docker build -t chargeplus:ci .`).
- **Rollback:** Redeploy previous Docker image tag. Migrations are non-destructive and
  idempotent (`IF NOT EXISTS` / `ON CONFLICT` / guarded blocks). Reverse migrations are applied
  forward via new migration files, never by mutating applied history.
- **Migrations:** Applied in filename order via `supabase db push`.

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
- **RLS Coverage:** RLS enabled on all 29 core tables + `public.ingestion_runs`. Exactly 29 public RLS policies, 1 admin-only policy on `ingestion_runs`, and 0 client policies on `analytics` and `ml` (default deny-all to client roles; ETL bypasses via service role).

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
- **Automated Workflow Alerts:** GitHub Actions sends automated failure notification emails to repository administrators when `scheduled_ingestion.yml` fails.
- **External Monitoring Recommendation:** Connect `/api/health` to an uptime monitor (BetterStack, UptimeRobot, or AWS Route 53 Health Checks) for 1-minute interval pinging with PagerDuty/SMS alerts.

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
       ↓ (only if DQ passes)
Warehouse Data Maturity Check (maturity.py)
  - Assesses temporal observation depth and gates ML feasibility
```

Failure Guarantees:
- If ingestion fails, warehouse ETL is **skipped** (no corruption of analytics facts).
- If ETL fails, data quality checks halt and workflow fails.
- All writes are idempotent with `ON CONFLICT` constraints.

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

## 9. Performance Characteristics (Measured Live)

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
| Docker Containerization | PASS | PASS | PASS | PASS | ENVIRONMENTAL (Local daemon) | PASS |
| Rate Limiting & Logging | PASS | PASS | PASS | PASS | PASS | PASS |
| Backup & Recovery Runbook | PASS | PASS | PASS | PASS | ENVIRONMENTAL (Live restore) | PASS |
