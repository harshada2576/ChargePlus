# ChargePlus — Production Operations (Phase 6)

## 1. Deployment

- **Runtime:** Docker image (`Dockerfile`, Node 22) or any Node 22 host.
  Build: `npm ci && npm run build`. Start: `npm run start` (port 3000).
- **Python jobs** (ingestion, warehouse ETL, maturity) run in GitHub Actions,
  never in the web image. CI (`.github/workflows/ci.yml`) runs typecheck,
  lint, unit tests, and a placeholder-env production build.
- **Rollback:** redeploy the previous image tag. Migrations are idempotent
  (`IF NOT EXISTS` / `ON CONFLICT` / guarded DO blocks) and non-destructive,
  so rollback is code-only unless a migration itself must be reverted
  (reverse with a new migration, never by editing history).
- **Migrations:** apply in filename order via `supabase db push`. Gate + Phase 4
  migrations were applied with in-file self-verifying assertions.

## 2. Environment

| Variable | Scope | Required |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | public (browser) | yes |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | public (browser, RLS-governed) | yes |
| `DATABASE_URL` | server-only (privileged pool) | yes |
| `SUPABASE_SERVICE_ROLE_KEY` | server-only (admin route auth) | yes for admin analytics |
| `OPENCHARGEMAP_API_KEY` | server-only (Python ingestion) | yes for live ingestion |

Rules: only `NEXT_PUBLIC_*` reaches the browser. Never commit `.env.local`
(ignored). Dummy values are CI-only; the app fails fast on missing config.

## 3. Domain / auth checklist (Supabase dashboard, operator-owned)

- [ ] Production URL set as Site URL; preview URLs added as needed
- [ ] Auth redirect allow-list includes `/verify` callback
- [ ] Phone provider (Twilio/MessageBird) configured — SMS OTP depends on this
- [ ] Email OTP templates reviewed
- [ ] Auth rate limits reviewed (dashboard) alongside in-app limits (§5)

## 4. Security posture

- Secrets: server-only (§2); repo scans clean (only a synthetic test string
  for scrub tests, which asserts its own redaction); `.env*.local` ignored.
- Input: MapLibre popups escape user fields; IDs go through
  `encodeURIComponent`; no `eval`/raw HTML injection paths.
- AuthN/Z: OTP via Supabase Auth; admin enforced server-side in
  `/api/admin/warehouse` (token + `profiles.role`) plus RLS second layer;
  role self-promotion blocked by column grants + `trg_profiles_role_guard`.
- Live anon probes (Phase 6.4): public reads only intended data; anon writes
  denied (42501); `ingestion_runs` invisible to anon.

## 5. Abuse controls

- In-app token bucket (`src/lib/rateLimit.ts`): admin warehouse 60/min per
  credential (429 + `retry-after`); health 300/min per IP. Unit-tested.
- Limits: per-instance memory (resets on restart); distributed enforcement
  belongs to the hosting edge. Supabase Auth dashboard rate limits stay on.
- Anonymous station browsing is intentionally unthrottled beyond the health
  ceiling; write paths are auth- + RLS-gated per user.

## 6. Observability

- Server routes emit JSON lines (`src/lib/serverLog.ts`, never secrets):
  `admin.warehouse.failed`, `health.db_unreachable`, plus Python structured
  logs with secret scrubbing (`_scrub_secrets`).
- Ingestion health: `public.ingestion_runs` states (SUCCEEDED/PARTIAL/FAILED/
  CANCELLED) visible in the admin console; scheduler lock is fail-closed;
  single-owner accounting (no double rows).
- ML monitoring: no production model exists (correctly). Inference contracts
  return `NO_MODEL`; admin shows "No model deployed" + COLD maturity.
- Python ETL/DQ/maturity CLIs print machine-readable summaries (`--json`).

## 7. Performance (measured live, Phase 6.9)

- `v_station_current_state`: ~11ms; `v_station_connectors`: <1ms;
  warehouse summary aggregate: ~1ms; admin pending-reports: <1ms.
- `nearby_stations(1km)`: ~280ms server-side on 16 rows (RLS-per-row + view
  lateral joins). UNUSED by the frontend (client haversine instead) —
  classified FUTURE RISK: optimize only if wired at scale.
- No N+1: dashboard/console fetch in `Promise.all`; libs issue one query per
  call; admin warehouse is a single aggregate round trip; lists capped
  (`.limit(50)`, station slice 6). Map renders the live station set only.

## 8. Compatibility (static audit; no device lab)

Viewport meta, responsive breakpoints, bottom mobile nav, mobile padding,
touch-sized controls, existing loading/empty/error states throughout.
Status: PASS (static). Device/browser lab: NOT VERIFIED (environmental).

## 9. Data honesty (locked)

Unknown ≠ zero/unavailable/free; stale ≠ unavailable; operational ≠ live
availability; prediction ≠ observation. Warehouse COLD with zero temporal
evidence; admin surfaces show "No … yet" states, never 0% metrics.

## 10. Failure model (safe behaviors)

Supabase down → safe error states, retry; station timeout → error + retry;
source down → run FAILED/retried per policy, no fake data; lock held →
CANCELLED; partial failure → PARTIAL with per-record accounting; OTP provider
down → surfaced provider error, never fake session; malformed/oversized input
→ validation errors, RLS denial; forged IDs/roles → denied (RLS + trigger);
admin API direct call → 401/403; no model → NO_MODEL; empty warehouse →
honest empties; missing price/power → unknown display; stale source →
"last updated" pairing; map tiles fail → list UI still works; deploy fails →
previous image; migration fails → assertion aborts before partial apply;
monitoring fails → routes still serve (logging never throws).

## 11. Public beta checklist (actual status)

Product: browsing/search/filter/detail/navigation work (build + static; live
browser proof environmental) · auth/favorites/reports/reviews/alerts paths
code + RLS verified (live user proof needs SMS provider + test identities) ·
admin protected (server denial proven live).
Data: real stations/provenance, stale/unknown distinguished (live PASS) ·
ingestion operational (SUCCEEDED runs) · DQ 13/13 + 24/24 (live PASS).
Security: secrets/RLS/admin/abuse/input (live probes + tests PASS).
Reliability: error states + logging implemented; platform log collection is
hosting-dependent · rollback + migration process documented.
Performance: measured above; no blockers on wired paths.
Honesty: all claims evidence-backed; no fabricated ML/availability.

## 12. Known limitations

- Live browser/device proof, live OTP delivery, live user write round-trips,
  and authorized-admin UI proof need environment/identities (documented
  across phases; unchanged).
- Rate limiting is per-instance; edge enforcement pending hosting choice.
- `nearby_stations` slow if ever wired (future risk, currently unused).
- Hosting/domain/SSL live cutover not performed from here.
