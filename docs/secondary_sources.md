# Secondary-Source Ingestion — Operations Guide

Supplements `source_adapters_architecture.md` (adapter architecture) and
`step_2_3_first_live_source_persistence.md` (primary OCM source). This doc
covers the two secondary sources: OpenStreetMap (Overpass) and data.gov.in.

## Source status

| Source | Adapter | Live verified | Blocker (if any) |
|---|---|---|---|
| OpenChargeMap | `backend/ingestion/adapters/openchargemap.py` | Yes (8 Mumbai stations) | — |
| OpenStreetMap / Overpass | `backend/ingestion/adapters/osm.py` | Not yet (offline-tested) | Needs an approved endpoint/bbox + a supervised first run |
| data.gov.in | `backend/ingestion/adapters/datagovin.py` | Not yet (offline-tested) | `BLOCKED_EXTERNAL_DEPENDENCY`: API key registration + verified resource ID |

Neither secondary source is cron-scheduled. The scheduled workflow runs OCM
only; `ScheduledIngestionOrchestrator` refuses unattended runs for any source
outside `SCHEDULED_BY_DEFAULT` (`backend/ingestion/runner.py`).

## OpenStreetMap / Overpass

- **What it is:** static community inventory (`amenity=charging_station`
  nodes/ways/relations). Zero live availability, zero tariffs. OSM records
  never produce observations.
- **License:** © OpenStreetMap contributors, ODbL 1.0. Attribution is stored
  per record (`extra_metadata.attribution`) and must accompany any public use.
- **Queries:** bounded Overpass QL per bounding box
  (`build_overpass_query`). Global extracts are refused by the adapter.
- **Safeguards:** 2s minimum inter-request interval, per-request timeout
  (default 60s), bounded retries with backoff+jitter+Retry-After via the
  shared `request_with_retry` transport, bbox-required partitioning for bulk
  collection (tile regions; do not hammer public infrastructure).
- **Identity:** stable `node/<id>`, `way/<id>`, `relation/<id>` identifiers;
  OSM version/timestamp/changeset/user retained; repeated imports idempotent.
- **Config:** `OSM_OVERPASS_ENDPOINT` (default public endpoint; override only
  with an approved endpoint/mirror).

Manual execution (safe first):

```bash
python -m backend.ingestion.runner --source osm --dry-run --limit 50
python -m backend.ingestion.runner --source osm --limit 200   # live persist
```

## data.gov.in

- **What it is:** Indian government open-data registry datasets (e.g.
  FAME-II/BEE station listings). Schemas vary by publisher; this adapter
  handles common field names and treats everything else as missing.
- **License:** NDSAP 2012 (attribution stored per record).
- **Prerequisites (external):** register at https://data.gov.in for
  `DATAGOVIN_API_KEY`; verify the target dataset and set
  `DATAGOVIN_RESOURCE_ID`. Without both, the adapter raises
  `DataGovInCredentialError` (PERMANENT, no retries, nothing ingested).
- **Retrieval:** offset/limit pagination, client-side bbox filter (the API has
  no native geo filter), `start_offset` for checkpoint resume of interrupted
  bulk fetches, per-request timeout (default 30s), shared retry transport.
- **No telemetry:** government datasets carry no live availability; records
  never produce observations.

Manual execution:

```bash
python -m backend.ingestion.runner --source datagovin --dry-run --limit 100
```

## Canonical pipeline (shared by all sources)

Secondary records flow through the exact OCM pipeline: adapter
`process_record`/`process_batch` (record-level isolation) → canonical
normalization (Step 2.5) → validation gating (Step 2.6) → candidate retrieval
→ entity resolution + deduplication (Steps 2.4/2.7, no invented precedence;
conflicts → REVIEW) → persistence (Step 2.8) → freshness evaluation (Step
2.9, STALE ≠ UNAVAILABLE) → run accounting (Step 2.10, one row per run).

Cross-source deduplication is geographic + evidence-based: nearby OSM/OCM
records for the same physical site merge; similar names alone never merge.

## Scheduling & monitoring

- Per-source enable/disable: `--source` selection + `ScheduleConfig.enabled`.
  Secondary cron scheduling stays off until a supervised dry-run + live run
  pair is reviewed.
- Every run writes `public.ingestion_runs` (fetched/parsed/accepted/
  quarantined/rejected/persisted + sanitized errors). Watch consecutive
  failures and unexpected zero-result runs.
- Retries: per-request (transport) + per-run (orchestrator, TRANSIENT only).
  Credential/config errors are PERMANENT and fail fast.
- Logs never contain API keys, tokens, or credential-bearing URLs
  (`_scrub_secrets` + header-only auth).

## What still needs a human

1. OSM: pick an approved endpoint + Mumbai tile plan; run supervised
   dry-run → live `--run-once`; review quarantine counts.
2. data.gov.in: register API key; verify the EV-charging resource ID at
   data.gov.in; set `DATAGOVIN_RESOURCE_ID`; same supervised rollout.
3. After either source's first verified live run, re-evaluate cron scheduling.
