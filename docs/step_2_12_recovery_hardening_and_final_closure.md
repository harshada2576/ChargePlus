# ChargePlus — Phase 2, Step 2.12: Recovery Hardening & Final Phase 2 Closure

> **Phase 2 Invariants & Principles**
> 1. Missing power != 0 kW — unknown connector power is preserved as `NULL`, never zeroed or fabricated.
> 2. Missing power != missing connector — absent wattage does not erase physical charging equipment.
> 3. Candidate lookup failure != empty database — database errors fail closed, preventing duplicate stations.
> 4. One logical execution attempt = exactly one durable `ingestion_runs` audit record.
> 5. Scheduler controls WHEN; Runner controls WHAT.
> 6. STALE != UNAVAILABLE — stale observations remain historical facts, never rewritten as unavailable.
> 7. Strict 3-layer architecture: Public OLTP, Analytics OLAP, and ML metadata schemas remain isolated.

---

## 1. Executive Summary

Phase 2.12 resolves the **FINAL FOUR BLOCKERS** identified during the post-recovery Phase 2 reconciliation audit. This hardening step guarantees data integrity, failure safety, single-owner audit accounting, and reproducible Git governance without redesigning the system or expanding scope prematurely.

With all four blockers resolved, **Phase 2 is fully closed and verified live**, and the repository is provably ready for Phase 3 (Connecting the Locked Frontend).

---

## 2. The Four Blockers & Their Solutions

### Blocker 1: Reconcile and Commit Verified Recovery State
- **Problem**: The working tree contained essential canonical runtime wiring, grants hardening, tests, and database migrations, but the repository HEAD remained pre-recovery and untracked scratch artifacts cluttered the repository.
- **Solution**:
  - Removed scratch and debug residue (`scratch/`).
  - Reconciled documentation across `Must Read/Memory.md`, `Must Read/Phases.md`, and `README.md` to reflect unified, verified live counts.
  - Sequentially committed all recovery implementation, migrations, tests, and governance rules into Git with meaningful, descriptive commit messages.

### Blocker 2: Unknown-Power Connector Semantics
- **Problem**: When an upstream source record provided a connector without rated power (`power_kw = null`), strict validation warnings caused canonical persistence to skip the connector entirely. Consequently, 6 of 8 live pilot stations falsely appeared to have zero connectors.
- **Solution**:
  - Applied migration `supabase/migrations/20260926000003_step_2_12_connector_unknown_power.sql`:
    - Made `public.connectors.power_kw` and `analytics.dim_connector.power_kw` nullable.
    - Added `CHECK (power_kw IS NULL OR power_kw > 0)` to guarantee power is never recorded as 0 kW or negative.
    - Created unique index `public.uq_connectors_station_type_power (station_id, connector_type, power_kw, COALESCE(charging_standard, '')) NULLS NOT DISTINCT` to enforce capacity group uniqueness even when `power_kw` is `NULL`.
  - Updated `backend/ingestion/persistence.py` (`_reconcile_and_persist_connectors`, `_persist_keep_separate`, `_persist_merge`, `_persist_link_to_canonical`, `_sync_dim_connector`):
    - Preserves `power_kw = None` as SQL `NULL`.
    - Preserves physical connector quantity (`quantity >= 1`) and source connector IDs.
    - Emits durable metrics `connectors_with_unknown_power` and `connectors_skipped` in `ingestion_runs.metadata`.
  - Live Database Remediation: Bounded live ingestion against OpenChargeMap restored 3 connectors across 3 stations, increasing live connectors from 2 to 5. Zero stations falsely appear connector-less among sources providing connection data.

### Blocker 3: Fail-Closed Candidate Lookup Safety
- **Problem**: In `backend/ingestion/runner.py`, a database error during `fetch_existing_canonical_stations()` fell back to `existing = []`. This unsafe fail-open behavior caused the deduplication engine to treat established stations as new stations, risking duplicate station creation.
- **Solution**:
  - Created `CandidateLookupError(RuntimeError)` in `backend/ingestion/contracts.py`.
  - Updated `backend/ingestion/runner.py` to raise `CandidateLookupError` upon any candidate retrieval failure, instantly aborting canonical execution before any station or connector persistence occurs.
  - Classified `CandidateLookupError` as `FailureClassification.TRANSIENT` in `backend/ingestion/scheduling.py`, allowing exponential backoff and scheduler retry policies to execute safely.
  - Added regression test proving 0 mutations occur on lookup failure, the run is marked `FAILED`, and legitimate retries are possible.

### Blocker 4: Single `ingestion_runs` Ownership
- **Problem**: `ScheduledIngestionOrchestrator` created an `ingestion_runs` row before delegating to `IngestionRunner.run()`, which subsequently created its own `ingestion_runs` row, resulting in 2 rows for 1 logical execution.
- **Solution**:
  - Established that **IngestionRunner owns execution run accounting**.
  - In `backend/ingestion/runner.py`, `run()` persists the execution record in a `finally` block, ensuring runs that fail or succeed are accurately recorded.
  - In `backend/ingestion/scheduling.py`, `execute_scheduled_run()` invokes `runner.run(attempt_count=attempt)` and checks if the runner persisted the record; if so, duplicate persistence is suppressed.
  - Invariant maintained: Direct runs create 1 row; scheduled runs create 1 row; separate retry attempts create distinct rows per attempt.

---

## 3. Live Database Verification (Before vs. After)

Verification executed against linked Supabase PostgreSQL instance:

| Entity / Table | Pre-Hardening State | Post-Hardening Live State | Verified Evidence |
| :--- | :---: | :---: | :--- |
| `public.stations` | 8 | **8** | Unchanged, 0 duplicate stations |
| `public.station_source_link` | 8 | **8** | 8 links with SHA-256 payload hashes |
| `public.connectors` (Total rows) | 2 | **5** | **+3 connectors** restored from source |
| `connectors` (`power_kw IS NULL`) | 0 | **3** | Preserved as NULL (not 0 kW) |
| `connectors` (`power_kw IS NOT NULL`) | 2 | **2** | Preserved (7 kW Type 2, 120 kW CCS2) |
| Stations falsely connector-less | 6 | **0** | Only 3 stations with empty source connections remain at 0 |
| `public.station_observations` | 0 | **0** | Zero fabricated telemetry |
| `public.ingestion_runs` | 2 | **3** | **Exactly +1 row** persisted for run (0 double-writes) |
| `analytics.dim_station` (current) | 8 | **8** | 100% aligned with OLTP |
| `analytics.dim_connector` | 2 | **5** | 100% aligned with OLTP |
| `analytics.fact_station_observation` | 0 | **0** | Zero fabricated facts |
| Working Tree Status | Uncommitted / Dirty | **Clean (`nothing to commit`)** | Reproducible from Git HEAD |

---

## 4. Test & Quality Gates

All automated verification commands executed and verified with 100% pass rates:

1. **Pytest Test Suite**:
   ```bash
   python -m pytest tests/ -q
   # Result: 376 passed in 125.06s (357 existing + 19 Phase 2.12 regression tests)
   ```
2. **TypeScript Compilation**:
   ```bash
   npm run typecheck
   # Result: tsc --noEmit exited 0 (0 errors)
   ```
3. **ESLint Analysis**:
   ```bash
   npm run lint
   # Result: eslint . exited 0 (0 errors)
   ```
4. **Next.js Production Build**:
   ```bash
   npm run build
   # Result: 26/26 pages generated cleanly with Turbopack (exited 0)
   ```
5. **Bounded Live Dry-Run**:
   ```bash
   python -m backend.ingestion.runner --dry-run --limit 10
   # Result: 8 fetched, 8 linked, 0 writes (exited 0)
   ```
6. **Bounded Live Run-Once**:
   ```bash
   python -m backend.ingestion.runner --run-once --limit 10
   # Result: Run ID 208d837a-f9ac-4bca-880c-96c6a57b8e04, state SUCCEEDED, 1 row written
   ```

---

## 5. Architectural & Conceptual Audit

- **Connector Integrity**: Missing power is distinct from missing connector and never converted to 0. Positive values (e.g. 7 kW, 120 kW) remain intact.
- **Identity & Deduplication**: Candidate lookup failure completely blocks persistence. Source identities (`open_charge_map`) remain distinct from canonical UUIDs.
- **Audit & Accounting**: Each execution attempt maps to exactly one durable record in `public.ingestion_runs`.
- **Honest Telemetry**: No fake telemetry, pricing, or availability is manufactured.
- **Three-Layer Database Isolation**: Public OLTP, Analytics OLAP, and ML metadata remain strictly segregated with zero cross-layer foreign keys.

---

## 6. Phase 2 Closure Status

```text
PHASE 2 VERIFIED COMPLETE — READY FOR PHASE 3
```
