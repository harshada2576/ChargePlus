# ChargePlus Comprehensive QA Certification

**Campaign timestamp:** 2026-10-09 (IST)  
**Repository:** `harshada2576/ChargePlus`  
**Branch:** `feature/phase-6-production`  
**Starting commit:** `2ed89056a9f4eca17d98dbe88535987139e214cf`  
**Final commit:** uncommitted working tree; dependency/source/report changes are shown by `git diff`.  
**Working tree at campaign start:** only the prior uncommitted `docs/testing/` evidence directory was present.  
**Release decision:** **CONDITIONAL GO** for a non-production review/staging scope only. This is **not** a production release approval.

## Scope and evidence rules

This report replaces the unavailable `testing_release_certification.md` referenced by the campaign request. Historical claims were not used without current runner evidence. A test is marked PASS only when it executed and passed; unavailable infrastructure is marked BLOCKED. No production load, fault injection, OTP delivery, destructive migration, or production restore was attempted.

Evidence files are under [`docs/testing/evidence/`](./evidence/):

| Artifact | Command/result |
|---|---|
| [`node-test.log`](./evidence/node-test.log) | `npm test`; 126 passed, 0 failed, exit 0, 24.140 s |
| [`python-test.log`](./evidence/python-test.log) | `python -m pytest tests -q --ignore=tests/test_canonical_postgres_integration.py`; 432 passed, exit 0, 47.049 s |
| [`python-collect.log`](./evidence/python-collect.log) | Collection inventory: 438 tests, exit 0, 10.306 s |
| [`postgres-integration.log`](./evidence/postgres-integration.log) | 6 passed, exit 0; used configured `DATABASE_URL`, target identity not verified |
| [`typecheck.log`](./evidence/typecheck.log) | `npm run typecheck`; exit 0, 36.497 s |
| [`lint.log`](./evidence/lint.log) | `npm run lint`; exit 0 |
| [`build.log`](./evidence/build.log) | `npm run build`; exit 0, 318.288 s |
| [`npm-audit.json`](./evidence/npm-audit.json) | `npm audit --omit=dev`; 5 vulnerabilities: 2 critical, 3 high |
| [`pip-audit.log`](./evidence/pip-audit.log) | `pip-audit -r requirements.txt`; 10 findings in 3 packages, exit 1 |
| [`browser-homepage.txt`](./evidence/browser-homepage.txt) | Real Chrome browser smoke observation of `/`; route rendered successfully |
| [`node-test-final.log`](./evidence/node-test-final.log) | Final `npm test`; 126 passed, exit 0 |
| [`python-test-final.log`](./evidence/python-test-final.log) | Final safe Python suite; 432 passed, exit 0, 47.54 s |
| [`typecheck-final.log`](./evidence/typecheck-final.log) | Final `npm run typecheck`; exit 0 |
| [`lint-final.log`](./evidence/lint-final.log) | Final `npm run lint`; exit 0 |
| [`build-final.log`](./evidence/build-final.log) | Final `npm run build`; exit 0, 25 routes |
| [`npm-audit-final.json`](./evidence/npm-audit-final.json) | Final `npm audit --omit=dev`; 0 vulnerabilities, exit 0 |
| [`npm-audit-all-final.json`](./evidence/npm-audit-all-final.json) | Historical pre-remediation full `npm audit`; recorded result: 9 development-only vulnerabilities (4 moderate, 5 high), exit 1. Preserved as the before-snapshot. Current result: 5 high development-only findings — see [`dev-deps/after-audit-full.json`](./evidence/dev-deps/after-audit-full.json) |
| [`pip-audit-final.log`](./evidence/pip-audit-final.log) | Final `pip-audit -r requirements.txt`; no known vulnerabilities |
| [`dependency-tree-final.json`](./evidence/dependency-tree-final.json) | Final npm dependency tree |
| [`python-versions-final.json`](./evidence/python-versions-final.json) | Final installed Python versions |
| [`dev-deps/baseline-audit-full.json`](./evidence/dev-deps/baseline-audit-full.json) | Dev-dependency remediation baseline `npm audit --json`; 9 findings (4 moderate, 5 high) |
| [`dev-deps/after-audit-full.json`](./evidence/dev-deps/after-audit-full.json) | Post-remediation `npm audit --json`; 0 moderate, 5 high remain |
| [`dev-deps/after-exit-codes.txt`](./evidence/dev-deps/after-exit-codes.txt) | Verification exit codes: test 126/126 exit 0, typecheck/lint/`npm ls esbuild` exit 0, runtime audit exit 0 |
| [`dev-deps/after-npm-ci.log`](./evidence/dev-deps/after-npm-ci.log) | Isolated `npm ci` from `package.json`+lockfile; exit 0, override honored (CI contract intact) |
| [`dev-deps/after-esbuild-override-smoke.log`](./evidence/dev-deps/after-esbuild-override-smoke.log) | Override smoke: `@esbuild-kit/core-utils` `transformSync` and `drizzle-kit --help`; exit 0 |

PowerShell reported some Unix-style test warnings as `NativeCommandError` because stderr was merged into stdout; the runner exit codes in each artifact are authoritative.

## Verified baseline

| Layer | Discovery | Executed | Result |
|---|---:|---:|---|
| Node test runner (`tests/test_*.mjs`) | 126 tests | 126 | PASS |
| Python safe suite | 438 collected | 432 | PASS; live PostgreSQL module excluded |
| PostgreSQL integration module | 6 tests | 6 | PASS, environment-qualified |
| TypeScript | n/a | n/a | PASS |
| ESLint | n/a | n/a | PASS |
| Production build | 25 routes generated | n/a | PASS |

The Python safe-suite count is lower than collection because `tests/test_canonical_postgres_integration.py` is excluded. The 6 live-module tests were run separately, so the combined executed count is 564 tests (126 + 432 + 6), without double-counting.

## Evidence matrix

| Test ID / risk | Test file or procedure | Exact command | Environment/isolation | Expected vs actual | Status | Evidence / defect |
|---|---|---|---|---|---|---|
| U-01 application logic | `tests/test_*.mjs` | `npm test` | Local Node runner, mocked dependencies | All tests pass; 126/126 | PASS | `node-test.log` |
| U-02 ingestion, validation, ETL, maturity | `tests/*.py` except live module | `python -m pytest tests -q --ignore=tests/test_canonical_postgres_integration.py` | Local Python fixtures/fakes | 432 pass | PASS | `python-test.log` |
| I-01 PostgreSQL persistence and cleanup | `tests/test_canonical_postgres_integration.py` | `python -m pytest tests/test_canonical_postgres_integration.py -q` | Configured `DATABASE_URL`; target not independently verified | 6 pass in 125.50 s | PASS* | `postgres-integration.log`; *not production-qualified |
| S-01 server route/build contract | Next production build | `npm run build` | Local production compiler | Build and all 25 routes complete | PASS | `build.log` |
| E2E-01 anonymous landing | Chrome at `http://localhost:3000/` | Start `npm run dev`, open `/` | Local dev server, real browser | Hero, search links, navigation and pilot content rendered | PASS | `browser-homepage.txt` |
| E2E-02 anonymous discovery/search/filter/station details | Existing unit/route tests; real browser multi-route run | `npm test`; browser `/explore`, `/search`, `/station/[id]` | Browser run became unreliable during concurrent Next compilation; no stable evidence | Runtime pass not established | BLOCKED | Requires stable server session and isolated browser run |
| E2E-03 auth states, favorites, reports/reviews, admin | `tests/test_auth_otp.mjs`, `test_favorites.mjs`, `test_reports.mjs`, `test_reviews.mjs`, `test_admin.mjs` | Included in `npm test` | Mocked Supabase/auth | Negative/error mappings pass; real identity flow not exercised | PARTIAL | `node-test.log`; requires disposable auth project |
| BB-01 API/user-facing negative and boundary behavior | Node route/library tests | `npm test` | Mocked DB and auth failures | Invalid IDs, missing sessions, denied writes reject honestly | PASS | `node-test.log` |
| WB-01 branch/error/idempotency/retry paths | Python ingestion/warehouse tests | Safe Python command above | Fakes and deterministic fixtures | Error, retry, dry-run, duplicate and maturity branches pass | PASS | `python-test.log` |
| DB-01 constraints, RLS, rollback, concurrency, migration compatibility | Supabase migrations and live integration | `supabase status`; live module command | Docker/Supabase unavailable; live target unverified | Cannot certify isolated role/RLS/rollback/concurrency | BLOCKED | Docker daemon unavailable; disposable PostgreSQL/Supabase required |
| SEC-01 JavaScript runtime dependencies | npm audit | `npm audit --omit=dev --json` | Local lockfile, registry advisory data | Expected zero known vulns; actual 0 | PASS | `npm-audit-final.json` |
| SEC-02 Python dependencies | pip-audit | `pip-audit -r requirements.txt` | Pinned requirements | Expected zero known vulns; actual none | PASS | `pip-audit-final.log` |
| SEC-03 JavaScript development dependencies | npm audit | `npm audit --json` | Local lockfile; not shipped in production image | Expected zero known vulns; baseline 9 (4 moderate, 5 high) reduced to 5 high (moderates resolved by scoped esbuild override); 5 high have no available upstream fix | PARTIAL / exception required | `npm-audit-all-final.json`, `evidence/dev-deps/after-audit-full.json`; see residual risk |
| LOAD-01 controlled load/stress/spike/endurance | No authorized staging target supplied | Not run | Safety gate | Must not run without disposable/authorized target | BLOCKED | Staging URL, limits and approval required |
| PERF-01 throughput/error/p50/p95/p99/resource metrics | No benchmark harness/target | Not run | No safe target | Metrics unavailable | BLOCKED | Add authorized benchmark environment |
| RES-01 DB/source outage, timeout, malformed/partial failures | Fixture-level failure tests only | Included in Python safe suite | Local fakes | Logic paths pass; live outage behavior unverified | PARTIAL | `python-test.log`; disposable staging required |
| B&R-01 backup/restore rehearsal | No recovery project/isolated database | Not run | Safety gate | No restore over production | BLOCKED | Recovery project and backup artifact required |
| COMP-01 supported browsers/mobile viewports | Chrome homepage only | Browser smoke | Chrome desktop default viewport | Homepage renders | PARTIAL | `browser-homepage.txt`; Edge/mobile matrix remains |
| A11Y-01 accessibility checks | No axe/Lighthouse runner installed | Not run | No automated accessibility harness | Not measured | BLOCKED | Install/use authorized accessibility runner |
| CI-01 workflow definition | `.github/workflows/ci.yml`, `scheduled_ingestion.yml` inspection | Reviewed definitions | Static workflow inspection | CI defines typecheck, lint, Node/Python tests, build, Docker; scheduled pipeline requires secrets | PARTIAL | Workflow files; no GitHub run evidence in this campaign |
| ML-01 maturity gate | `tests/test_maturity.py` | Safe Python command above | Deterministic empty/rich fixtures | COLD and `NOT TRAINABLE`/`NO_MODEL` semantics preserved | PASS | `python-test.log` |

## Security findings

## Security remediation verification

The remediation started from `2ed89056a9f4eca17d98dbe88535987139e214cf` and changed only dependency manifests/lockfiles plus the MapLibre import required by the major-version module export change.

| Package | Before | After | Direct/transitive | Advisory/disposition |
|---|---:|---:|---|---|
| `next` | 16.2.6 | 16.3.8 | Direct runtime | Patched runtime range selected; production audit clean |
| `maplibre-gl` | 5.24.0 | 6.4.1 | Direct runtime | Required major upgrade; vendor advisory fixes DOM sanitizer XSS |
| `postcss` | 8.5.8 | 8.5.29 | Direct development/build | Patched direct version; runtime audit clean |
| `sharp` | 0.34.5 | resolved through patched Next tree | Transitive runtime/build | No longer reported by runtime audit |
| `source-map-js` | 1.2.1 | resolved through regenerated lockfile | Transitive | No longer reported by runtime audit |
| `python-dotenv` | 1.1.0 | 1.2.2 | Direct runtime/worker | `PYSEC-2026-2270`; fixed version |
| `requests` | 2.31.0 | 2.33.0 | Direct worker runtime | `PYSEC-2026-1872`, `PYSEC-2026-1873`, `PYSEC-2026-2275`; fixed version selected |
| `pytest` | 8.3.5 | 9.0.3 | Direct development/test | `PYSEC-2026-1845`; fixed version |
| `pytest-asyncio` | 0.26.0 | 1.4.0 | Direct development/test | Compatibility upgrade required because 0.26.0/1.2.0 require pytest `<9` |
| `esbuild` (under `@esbuild-kit/core-utils`) | 0.18.20 | 0.25.11 via scoped `overrides` | Transitive development (`drizzle-kit` → `@esbuild-kit/esm-loader`) | Advisory `GHSA-67mh-4wv8-2f99` (dev server CORS, affected `<=0.24.2`); resolved all 4 moderate findings without touching drizzle-kit/ESLint/Next versions |

The MapLibre v6 upgrade required changing [`MapLibreMap.tsx`](../../src/components/MapLibreMap.tsx) from a default import to a namespace import. Typecheck, tests, lint, and build passed after that compatibility fix.

### Remaining development-only npm vulnerabilities

The full audit reported 9 findings at baseline (4 moderate, 5 high). The 4 moderate findings are resolved; **5 high findings remain**, all in development tooling and none present in `npm audit --omit=dev` (still 0, exit 0):

* **Resolved — `esbuild` chain (4 moderate).** `drizzle-kit 0.31.10` → `@esbuild-kit/esm-loader` → `@esbuild-kit/core-utils` pinned `esbuild ~0.18.20` (advisory `GHSA-67mh-4wv8-2f99`, affected `<=0.24.2`). A scoped npm override in `package.json` forces `esbuild 0.25.11` for `@esbuild-kit/core-utils` only; no package versions, scripts, tests, or lint rules were changed. Verified: `npm audit --json` reports 0 moderate, `npm ls esbuild --all` is clean (exit 0), isolated `npm ci` exits 0 and honors the override, `transformSync` and `drizzle-kit --help` smoke tests pass, and test/typecheck/lint/build all pass. Evidence: `evidence/dev-deps/`.
* **Open exception — `braces` chain (5 high).** `eslint-config-next 16.3.8` → `@next/eslint-plugin-next` → `fast-glob 3.3.1` → `micromatch 4.0.8` → `braces 3.0.3` (advisory `GHSA-vfj7-8cjw-p6xm`, stack-exhaustion DoS in deeply nested patterns). There is **no available fix**: the advisory's patched release for `braces` is `None` (latest published is still 3.0.3), and npm's only suggested fix is a downgrade to `eslint-config-next@14.2.35`, which is incompatible with the pinned Next 16 toolchain and the flat-config `eslint.config.mjs`, so it was not applied. Current `eslint-config-next@16.4.0`/canary still depend on `fast-glob 3.3.1`, so upgrading does not clear it either.

These are explicit development-only exceptions, not silently suppressed findings (no `audit-level` overrides or ignore rules were added). They remain a release-process action for the toolchain, but they do not ship in the runtime dependency set represented by the production audit (`npm audit --omit=dev` = 0 findings, exit 0). The `braces` path executes only at lint time against trusted local config, not at runtime.

### JavaScript

Before remediation, `npm audit --omit=dev` reported **2 critical and 3 high** vulnerability groups:

* `maplibre-gl` current range `<=6.4.0`: DOM sanitizer XSS bypass.
* `next` `16.2.6`: multiple App Router/server-action/image/middleware advisories; audit recommends ranges beginning at patched versions.
* `postcss` transitive: CSS/source-map disclosure and path traversal advisories.
* `sharp` transitive: libvips/libheif/librsvg advisories.
* `source-map-js` transitive: indexed source-map event-loop denial of service.

### Python

Before remediation, `pip-audit` reported **10 findings** (duplicate rows represent multiple advisory records) in:

* `python-dotenv 1.1.0`, fixed in `1.2.2` (`PYSEC-2026-2270`);
* `requests 2.31.0`, fixes beginning at `2.32.0`, `2.32.4`, and `2.33.0`;
* `pytest 8.3.5`, fixed in `9.0.3` (`PYSEC-2026-1845`).

These are release-blocking until dependency owners review compatibility and upgrade/regression-test the lock state.

## Defects and retest status

1. **Resolved:** runtime JavaScript findings; final `npm audit --omit=dev` is clean.
2. **Resolved:** Python findings; final `pip-audit -r requirements.txt` is clean.
3. **Partially resolved:** development-only npm findings reduced from 9 to 5. The 4 moderate `esbuild` findings were fixed with a scoped `overrides` entry (no version downgrades). The 5 high `eslint-config-next`/`braces` findings remain an open exception: no patched `braces` release exists and npm's suggested fix is an incompatible downgrade.
3. **Environment gap:** Docker/Supabase daemon unavailable, preventing isolated DB/RLS/migration and destructive resilience/backup tests.
4. **Evidence gap:** real multi-route browser E2E, supported-browser/mobile, and automated accessibility measurements are not certified.
5. **Evidence qualification:** the live PostgreSQL module passed but used a configured local `DATABASE_URL`; because target identity was not independently verified, it must be repeated against an explicitly disposable database.

No application assertion was weakened and no application defect was fixed during this evidence campaign.

## Reproduction commands

```powershell
npm test
python -m pytest tests -q --ignore=tests/test_canonical_postgres_integration.py
python -m pytest tests/test_canonical_postgres_integration.py -q
npm run typecheck
npm run lint
npm run build
npm audit --omit=dev
npm audit
pip-audit -r requirements.txt
python -m pip install -r requirements.txt
docker info
supabase status
```

For browser smoke, start `npm run dev`, then open `http://localhost:3000/` in Chrome. Do not point live integration, load, fault-injection, backup, or restore procedures at production.

## Prioritized remaining actions

1. Decide and document an approved remediation or exception for the 5 remaining high development-only npm findings (`braces`/`micromatch`/`fast-glob` chain). No patched `braces` release exists yet; revisit when upstream ships one, and do not downgrade Next/ESLint tooling blindly.
2. Provision a disposable Supabase/PostgreSQL project, verify its project/database identity, and rerun migrations, RLS-by-role, rollback, concurrency, ingestion, and warehouse tests.
3. Run the real browser matrix for anonymous discovery, filters, station details, auth states, favorites, reports/reviews, admin denial, stale/error/empty states, Edge, and mobile viewports.
4. Add an authorized staging performance harness reporting throughput, error rate, p50/p95/p99 latency, and CPU/memory; run load, stress, spike, endurance, timeout and partial-failure scenarios.
5. Perform an isolated backup/restore rehearsal and record RPO/RTO.
6. Run axe/Lighthouse accessibility checks and remediate any confirmed violations.
7. Capture GitHub Actions run IDs and logs for CI and scheduled ingestion after the above prerequisites are available.
