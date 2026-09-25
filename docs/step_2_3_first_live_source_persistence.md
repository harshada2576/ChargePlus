# ChargePlus — Step 2.3 Documentation
## Connect First Legitimate Station Data Source: OpenChargeMap → Real Database

**Phase:** 2/6 (Real Data Ingestion & Data Quality)  
**Step:** 2.3  
**Status:** COMPLETE / LOCKED  
**Module:** `backend/ingestion/persistence.py`, `backend/ingestion/runner.py`

---

### 1. How OpenChargeMap Ingestion Works

The ChargePlus ingestion pipeline follows a strict unidirectional, decoupled architecture:

```
External Source (OpenChargeMap API / Fixtures)
       ↓
BaseSourceAdapter.fetch_raw()
       ↓
OpenChargeMapAdapter.parse_raw() & normalize_station()
       ↓
NormalizedStationRecord (Contract Version 1.0.0)
       ↓
DataQualityValidator.validate_record()
       ↓ [ACCEPT / ACCEPT_WITH_WARNINGS]
IngestionPersistenceService (Transactional Operational Boundary)
       ├── public.data_sources (Feed registration)
       ├── public.operators (Operator deduplication / registration)
       ├── public.stations (Canonical physical charging locations)
       ├── public.connectors (Reconciled capacity groups, NOT NULL power)
       └── public.station_source_link (Provenance mapping & idempotency)
       ↓ [ONLY IF GENUINE TELEMETRY OBSERVATION EXISTS]
analytics.fact_station_observation + public.station_observations
       ├── Dimensional conformed date_key (YYYYMMDD)
       ├── Dimensional conformed time_key (0..95 in UTC)
       ├── analytics.dim_station / dim_operator / dim_location sync
       └── Available / total plug counts
```

**Architectural Decoupling:**
The adapter (`backend/ingestion/adapters/openchargemap.py`) is strictly **non-persistent** and acts solely as a data extraction and transformation component. Database mutations are exclusively handled by `IngestionPersistenceService` (`backend/ingestion/persistence.py`) orchestrated by `IngestionRunner` (`backend/ingestion/runner.py`).

---

### 2. How to Configure `OPENCHARGEMAP_API_KEY`

OpenChargeMap API requires an API key for live queries. This key is server-only:
1. Add to `.env.local` (or server environment variables):
   ```bash
   OPENCHARGEMAP_API_KEY=your_openchargemap_api_key_here
   ```
2. **Security Rules:**
   - Never prefix with `NEXT_PUBLIC_`.
   - Never import or expose in client-side Next.js components or browser code.
   - Never log in execution reports, error dumps, or terminal outputs.
   - If `OPENCHARGEMAP_API_KEY` is not found, `IngestionRunner` halts with a clear, safe `RuntimeError` rather than fabricating dummy data.

---

### 3. How to Perform Dry-Run Ingestion

A dry run executes the entire ingestion lifecycle (fetching, parsing, normalizing, validating, and calculating would-be database mutations) with **zero writes** to PostgreSQL:

```bash
# 1. Dry run against live OpenChargeMap API (fetches 10 records, zero DB writes)
python -m backend.ingestion.runner --dry-run --limit 10

# 2. Dry run in offline mode using representative fixtures (no network call, zero DB writes)
python -m backend.ingestion.runner --use-fixtures --dry-run

# 3. Dry run output in machine-readable JSON format
python -m backend.ingestion.runner --use-fixtures --dry-run --json
```

---

### 4. How to Perform Controlled Real Ingestion

Controlled live ingestion writes canonical stations, connectors, and provenance records to Supabase PostgreSQL:

```bash
# Controlled live ingestion for Mumbai pilot (default limit: 50)
python -m backend.ingestion.runner --limit 10

# Controlled offline ingestion using representative fixtures into Supabase
python -m backend.ingestion.runner --use-fixtures --limit 10
```

---

### 5. Geographic Scope

Ingestion is strictly scoped **Mumbai-first** to protect operational integrity and prevent unconstrained global data ingestion:
- **Default Scope:** Mumbai Metropolitan Region (MMR)
  - Latitude: `18.70° N` to `19.50° N` (`MUMBAI_LAT_MIN`, `MUMBAI_LAT_MAX`)
  - Longitude: `72.70° E` to `73.30° E` (`MUMBAI_LNG_MIN`, `MUMBAI_LNG_MAX`)
- **API Filtering:** Passed directly to OpenChargeMap via the boundingbox query parameter:
  `params["boundingbox"] = "(18.70,72.70),(19.50,73.30)"`
- **Optional Nationwide Expansion:** `--all-india` flag removes the MMR bounding box and queries `countrycode=IN`.

---

### 6. Idempotency Behavior

Running ingestion multiple times against unchanged source data will **never create duplicate stations or duplicate connectors**:
1. When a source station is fetched, `public.station_source_link` is queried by `(source_id, source_station_id)`.
2. The deterministic SHA-256 payload hash of the incoming record is compared with `source_payload_hash`.
3. **If identical:** The station is marked `UNCHANGED`. Zero rows are inserted into `public.stations` or `public.connectors`. Only `last_seen_at` in `public.station_source_link` is refreshed.
4. **If payload changed:** The station is marked `UPDATED`. Attributes in `public.stations` are updated in place, connectors are reconciled, and `source_payload_hash` is refreshed.
5. **If new source station:** A newly generated `uuid.uuid4()` is assigned as the ChargePlus `station_id`. The external source ID (`192840`) is recorded exclusively in `public.station_source_link.source_station_id`.

---

### 7. What OpenChargeMap Operational Status Means

OpenChargeMap reports site status such as:
- `StatusTypeID: 50` $\to$ "Operational"
- `StatusTypeID: 100` $\to$ "Planned For Future Date"
- `StatusTypeID: 150` $\to$ "Temporarily Unavailable"
- `StatusTypeID: 200` $\to$ "Permanently Closed"

**Critical Semantic Rule:**
"Operational" means the site hardware exists and is physically operational.
It does **NOT** mean:
- Connectors are currently vacant or unoccupied.
- Plugs are free for charging right now.
- There is zero waiting queue.

Therefore:
- `operational_status = OPERATIONAL`
- `availability_status = UNKNOWN`
- `observation = None`

---

### 8. When an Observation is Created

An observation row is inserted into `public.station_observations` and `analytics.fact_station_observation` **ONLY when genuine point-in-time telemetry exists**:
- Specifically when OpenChargeMap reports automated real-time status (e.g., `StatusTypeID: 10` "Currently Available (Automated Status)" or `StatusTypeID: 20` "Currently In Use (Automated Status)") accompanied by a genuine timestamp (`DateLastStatusUpdate`).
- Static metadata updates or directory listings **never** create fake observations.
- Missing availability counts remain `NULL` (never assumed as all vacant or all occupied).

---

### 9. What is Deliberately NOT Implemented Until Later Steps

To preserve architectural boundaries and prevent premature complexity:
- **No Kafka / Redis / RabbitMQ / MQTT:** Direct transactional persistence is used. Message brokers are explicitly excluded.
- **No Fuzzy Cross-Source Entity Resolution (Step 2.4):** Step 2.3 only links OpenChargeMap to ChargePlus UUIDs via `station_source_link`. It does NOT perform cross-source fuzzy name, geospatial clustering, or operator merging across OCM and other sources.
- **No OSM or Government Ingestion:** OpenStreetMap, e-AMRIT, and CPO private APIs remain scheduled for subsequent ingestion steps.
- **No Machine Learning / Queue Prediction (Phase 5):** No busy-time estimates or predictive wait times are generated.
- **No Frontend Redesign:** Frontend reads exclusively through existing views and contracts.

---

### 10. How to Safely Rerun Ingestion

Ingestion is fully safe to rerun repeatedly at any time:
1. Re-running the command executes idempotently.
2. Unchanged records update `last_seen_at` without duplicating stations or connectors.
3. If an individual record fails database constraints (e.g. malformed postal code or missing power), record-level failure isolation catches the error, rolls back the single record, and continues processing remaining stations in the batch.
4. Summary reports always indicate exact counts of:
   - `stations_persisted` (New)
   - `stations_updated`
   - `stations_unchanged`
   - `connectors_persisted`
   - `observations_persisted`
   - `persistence_errors`
