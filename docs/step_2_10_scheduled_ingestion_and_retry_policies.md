# ChargePlus — Phase 2, Step 2.10: Scheduled Ingestion Workflows, Polling Daemons & Retry Policies

> **Core Architectural Principles**:  
> **"ONE PIPELINE, MULTIPLE TRIGGERS"** — The scheduler controls WHEN and HOW OFTEN the pipeline runs, never WHAT the pipeline means. It executes the exact same canonical pipeline as manual CLI invocations.  
> **"TRANSIENT RETRIES ONLY"** — Deterministic failures (bad credentials, schema validation rejections, bad configuration) are never retried. Only transient network, 5xx, or 429 errors are retried.  
> **"CONCURRENCY PROTECTION"** — Overlapping ingestion runs for the same source and scope are strictly prevented via PostgreSQL advisory locks.  
> **"IDEMPOTENCY UNDER ALL RETRIES & CRASHES"** — Rerunning the same payload or recovering from partial batch commits never creates duplicate stations, duplicate source links, or duplicate observations.  
> **"ZERO FAKE TELEMETRY"** — A scheduled metadata retrieval does not fabricate live availability observations. Static retrieval timestamp is strictly distinct from live observation timestamp.

---

## 1. Architectural Overview

Step 2.10 implements the orchestration, scheduling, retry, and operational resilience layer for the ChargePlus data ingestion pipeline ([`backend/ingestion/scheduling.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/scheduling.py)).

```
+-----------------------------------------------------------------------------------+
|                            Ingestion Triggers                                     |
|  - GitHub Actions Workflow (Platform Cron)                                        |
|  - Long-lived Polling Daemon (`PollingDaemon` with SIGINT/SIGTERM)                |
|  - Manual CLI (`python -m backend.ingestion.runner --source openchargemap`)      |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|               ScheduledIngestionOrchestrator (`run_orchestrated`)                 |
|  1. Parse ScheduleConfig (source_id, interval, retry_policy, scope, timeout)      |
|  2. Acquire Concurrency Lock (`pg_try_advisory_lock(key)` or in-memory)           |
|  3. Record Ingestion Run in `public.ingestion_runs` (`STARTED`)                   |
|  4. Execute Pipeline with Transient Retry Loop (Exponential Backoff + Jitter)    |
|  5. Call Authoritative Canonical Pipeline (`IngestionRunner.run`)                |
|  6. Persist Accounting Metrics & Run State (`SUCCEEDED`, `PARTIAL`, `FAILED`)     |
|  7. Release Concurrency Lock (`pg_advisory_unlock(key)`)                          |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                  Existing Authoritative Ingestion Pipeline                        |
|  Source Adapter ➔ Contract Validation ➔ Field Normalization ➔ Data Quality        |
|  Validation ➔ Entity Resolution ➔ Deduplication ➔ Canonical Persistence & Loading |
|  ➔ Observation Provenance & Freshness Engine                                      |
+-----------------------------------------------------------------------------------+
```

---

## 2. Scheduler Triggers & Execution Modes

The ingestion orchestrator supports three primary triggering models without introducing external queuing infrastructure (no Celery, Redis, Airflow, or Kafka):

1. **Platform-Native Cron (Recommended for Production)**:
   - Triggered via short-lived runners (e.g. GitHub Actions, AWS ECS scheduled tasks, or host cron).
   - CLI invocation: `python -m backend.ingestion.runner --source openchargemap --run-once`
   - Configured in [`.github/workflows/scheduled_ingestion.yml`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/.github/workflows/scheduled_ingestion.yml) running on a scheduled interval (e.g. every 6 hours) with manual `workflow_dispatch` support.

2. **Continuous Polling Daemon (`PollingDaemon`)**:
   - For environments supporting persistent worker processes (e.g. Docker container, systemd service, Kubernetes Pod).
   - CLI invocation: `python -m backend.ingestion.runner --source openchargemap --daemon --interval 3600`
   - Features clean graceful shutdown on `SIGINT` (Ctrl+C) and `SIGTERM`, completing active runs before exiting.

3. **Manual CLI Execution**:
   - For developer testing, ad-hoc backfills, and operational incident remediation.
   - CLI invocation:
     ```powershell
     python -m backend.ingestion.runner --source openchargemap --run-once --limit 100 --dry-run
     python -m backend.ingestion.runner --source openchargemap --run-once --max-attempts 3 --timeout 30.0
     ```

All triggers invoke `IngestionRunner.run_scheduled()`, which delegates to `ScheduledIngestionOrchestrator.execute()`. There is exactly **one canonical execution path**.

---

## 3. Source & Schedule Configuration

Schedules are defined via explicit, strongly-typed configuration objects ([`ScheduleConfig`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/scheduling.py)):

```python
@dataclass
class ScheduleConfig:
    source_id: str                          # e.g., 'openchargemap'
    enabled: bool = True                    # Enabled flag
    interval_seconds: int = 3600            # Polling cadence
    batch_limit: Optional[int] = None       # Maximum records per fetch
    timeout_seconds: float = 30.0           # Total HTTP timeout
    connect_timeout_seconds: float = 10.0   # Connect timeout
    read_timeout_seconds: float = 20.0      # Read timeout
    retry_policy: RetryPolicy = ...         # Retry parameters
    geographic_scope: Optional[str] = None  # e.g., 'mumbai', 'IN'
    extra_params: Dict[str, Any] = ...      # Adapter query parameters
```

Source API keys and sensitive credentials remain strictly in environment variables (e.g. `OPENCHARGEMAP_API_KEY`) and are never committed or exposed to the frontend.

---

## 4. Ingestion Run Lifecycle & State Model

Every execution is assigned a unique, traceable UUIDv4 `ingestion_run_id` and tracks a strict state model:

| State | Definition | Trigger Conditions |
| :--- | :--- | :--- |
| `STARTED` | Initial registration | Run record created in database before acquiring locks or making network calls. |
| `RUNNING` | Active execution | Concurrency lock acquired; adapter fetch and pipeline processing in progress. |
| `SUCCEEDED` | Complete success | Pipeline completed with zero rejected or quarantined records. |
| `PARTIAL` | Completed with quality exceptions | Pipeline completed, but one or more records were quarantined or rejected by validation. Not a transport failure. |
| `FAILED` | Terminal run error | Unhandled non-retryable error, max retry attempts exhausted, or fatal adapter failure. |
| `CANCELLED` | Gracefully aborted | Daemon received SIGINT/SIGTERM or lock acquisition was skipped. |

State transitions are recorded in `public.ingestion_runs` along with timestamps, retry attempt counts, and accounting counters.

---

## 5. Explicit Retry Classification & Error Handling

To prevent hammering upstream APIs or retrying unrecoverable errors, failures are explicitly classified into two categories ([`FailureClassification`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/scheduling.py)):

### Transient Failures (Retryable)
- Network timeouts (`TimeoutError`, `requests.exceptions.Timeout`, `urllib.error.URLError` timeout)
- Connection resets and aborted sockets (`ConnectionResetError`, `ConnectionRefusedError`, `BrokenPipeError`)
- Upstream server errors: HTTP `500 Internal Server Error`, `502 Bad Gateway`, `503 Service Unavailable`, `504 Gateway Timeout`
- Upstream rate limits: HTTP `429 Too Many Requests`
- Database deadlock or transient connectivity loss (`OperationalError`)

### Permanent Failures (Non-Retryable — Fail Fast)
- Authentication & authorization errors: HTTP `401 Unauthorized`, `403 Forbidden`, missing/invalid API key
- Client configuration errors: HTTP `400 Bad Request`, invalid query parameters, unsupported source format
- Malformed payloads and schema violations
- Deterministic programming errors (`KeyError`, `TypeError`, `ValueError` in business logic)

---

## 6. Backoff Policy, Jitter & HTTP 429 `Retry-After`

Transient retries use bounded exponential backoff with randomized proportional jitter:

$$\text{delay} = \min\left(\text{initial\_delay} \times \text{multiplier}^{\text{attempt} - 1},\; \text{max\_delay}\right) \times (1 \pm \text{jitter})$$

Default policy parameters:
- `max_attempts`: `3`
- `initial_delay_seconds`: `2.0`
- `multiplier`: `2.0`
- `max_delay_seconds`: `60.0`
- `jitter`: `0.2` ($\pm 20\%$ variance)

### HTTP 429 `Retry-After` Handling
When an upstream server returns an HTTP 429 status code with a `Retry-After` header:
- **Integer delay**: e.g., `Retry-After: 30` ➔ sleeps 30 seconds.
- **HTTP date**: e.g., `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT` ➔ parses delta from current UTC time.
- The delay is clamped to `max_delay_seconds` to prevent rogue headers from hanging the worker.

---

## 7. Concurrency Protection & Locking

To prevent race conditions, duplicate processing, and redundant upstream API calls, overlapping runs for the same `(source_id, scope)` are strictly prevented via **PostgreSQL Session Advisory Locks** ([`IngestionConcurrencyLock`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/scheduling.py)):

- Key derivation: A deterministic 64-bit signed integer is computed from `SHA-256(f"{source_id}:{scope}")`.
- Acquisition: `SELECT pg_try_advisory_lock(%s)`.
  - If `TRUE`: Lock acquired, proceed with ingestion.
  - If `FALSE`: Another run is already active for this source/scope. The current run exits cleanly with status `CANCELLED` and log message `"Concurrent ingestion run active for source... skipping"`.
- Release: `SELECT pg_advisory_unlock(%s)` in a `finally:` block.
- Crash Safety: PostgreSQL session advisory locks are tied to the database connection. If the worker process crashes or the network drops, PostgreSQL automatically releases the advisory lock immediately upon connection termination.
- Standalone / In-Memory Fallback: When running in unit tests or environments without direct PostgreSQL access, an in-memory thread lock with active key tracking provides identical concurrency guarantees.

---

## 8. Timeout Management

Every network operation is subject to finite, strict timeouts:
- `connect_timeout`: `10.0s` (detect unreachable hosts and TCP routing issues).
- `read_timeout`: `20.0s` (detect hung responses or slow upstream servers).
- `total_timeout`: `30.0s` (overall bounding limit).

No network call or scheduler worker is permitted to block indefinitely.

---

## 9. Partial Failure Isolation & Record Quarantine

A single malformed record must never abort an entire batch of valid stations. The pipeline isolates failures at three levels:

1. **Source-Level Failure**: Upstream API down, bad credentials, or invalid response format. Fails the entire run (`FAILED`).
2. **Record-Level Validation Failure**: Record fails Step 2.6 schema validation. The record is quarantined (`QUARANTINE`) or rejected (`REJECT`), logged with validation error codes, and omitted from persistence. The remaining valid records continue through resolution and persistence. The run completes with status `PARTIAL`.
3. **Record-Level Persistence Failure**: Database error during canonical mutation for an individual station. Step 2.8 isolated transaction rolls back for that single station. Other stations in the batch are unaffected.

---

## 10. Idempotency Guarantees Under Retries and Crashes

The scheduler guarantees complete idempotency across repeated runs, crashes, and transient retries:

1. **Station Identity**: Step 2.7 resolution matches on coordinate proximity ($\le 25\text{m}$) and normalized name similarity ($\ge 0.85$), linking back to the existing canonical station. Rerunning never creates a second canonical station.
2. **Station-Source Links**: `public.station_source_link` enforces `ON CONFLICT (source_id, source_station_id) DO UPDATE`.
3. **Connectors**: Step 2.8 operational loading updates existing connectors in place or inserts missing ones. Rerunning preserves connector count.
4. **Historical Observations**: `persist_observation()` verifies existing observations by `(station_id, observed_at, source_payload_hash)`. If an observation for the identical timestamp and payload hash already exists, the insert is skipped. Rerunning the same payload produces **zero duplicate observations**.
5. **Mutation Isolation**: Step 2.8 atomic per-station transactions ensure no half-written canonical entities remain if a crash occurs mid-batch.

---

## 11. Run Accounting & Audit Trail (`public.ingestion_runs`)

Ingestion run metrics are persisted to the dedicated PostgreSQL audit table created in migration `20260926000001_step_2_10_ingestion_runs.sql`:

```sql
CREATE TABLE IF NOT EXISTS public.ingestion_runs (
    id UUID PRIMARY KEY,
    source_id VARCHAR(64) NOT NULL,
    geographic_scope VARCHAR(64),
    state VARCHAR(32) NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    records_fetched INTEGER NOT NULL DEFAULT 0,
    records_parsed INTEGER NOT NULL DEFAULT 0,
    records_accepted INTEGER NOT NULL DEFAULT 0,
    records_accepted_with_warnings INTEGER NOT NULL DEFAULT 0,
    records_quarantined INTEGER NOT NULL DEFAULT 0,
    records_rejected INTEGER NOT NULL DEFAULT 0,
    records_persisted INTEGER NOT NULL DEFAULT 0,
    records_unchanged INTEGER NOT NULL DEFAULT 0,
    observations_persisted INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT,
    is_dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    duration_seconds DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Measured Facts Policy
All metrics represent **measured facts**:
- If records were parsed: exact integer count.
- If duration was measured: exact floating-point seconds.
- Zero means "measured zero" (e.g. `records_rejected: 0`).
- No fake numbers or unmeasured placeholders are ever recorded.

---

## 12. Logging, Sanitization & Secret Hygiene

Logs follow structured operational formatting and enforce strict redaction of sensitive credentials via `_scrub_secrets()`:
- `OPENCHARGEMAP_API_KEY` and generic API keys (`api_key=...`, `key=...`) are sanitized to `[REDACTED]`.
- Supabase service-role keys and JWT bearer tokens (`Bearer ey...`) are sanitized.
- PostgreSQL connection strings containing passwords (`postgres://user:pass@host...`) are sanitized.
- Full raw source JSON payloads are excluded from log outputs.

---

## 13. Step Boundaries & Non-Goals

Step 2.10 strictly honors all architectural boundaries:
- **Does NOT redesign the frontend**: No UI changes made.
- **Does NOT invent availability**: OCM `StatusTypeID 50` is operational status, not live dynamic availability. No fake telemetry observations are fabricated.
- **Does NOT alter Step 2.9 Freshness**: `STALE != UNAVAILABLE` and `UNKNOWN != UNAVAILABLE` remain intact.
- **Does NOT introduce heavy infrastructure**: No Celery, Redis, Airflow, APScheduler, or Kafka.
- **Does NOT implement Step 2.11**: Mumbai coverage auditing and spatial gap analysis belong exclusively to Step 2.11.
