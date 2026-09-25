# Phases.md — ChargePlus Build Plan
### ChargePlus
**Status: LOCKED ROADMAP — work sequentially unless a dependency requires a small parallel task.**

## How we will track progress

There are **6 phases**.

For every work session, must explicitly state:
- Current Phase: X/6
- Remaining Phases: Y
- Current Step: X.Y
- Remaining Steps in the current phase: Y
- What is complete
- What we are doing now
- What comes next

We will also perform a conceptual check, not just a code check.

---

# Phase 1 — Foundation & Real Database
**Goal:** replace prototype storage assumptions with the actual product foundation.

### Steps
1.1 Create/configure Supabase project — COMPLETE  
1.2 Enable required PostgreSQL/PostGIS capabilities — COMPLETE  
1.3 Create core operational schema — COMPLETE  
1.4 Create analytics schema — COMPLETE  
1.5 Create ML metadata schema — COMPLETE  
1.6 Add indexes and constraints — COMPLETE  
1.7 Add RLS policies — COMPLETE  
1.8 Add safe database views/functions where justified — COMPLETE (EXECUTED + LIVE VERIFIED)  
1.9 Establish environment variables/secrets — COMPLETE (AUDITED + CONFIGURED)  
1.10 Verify database with a clean test flow — COMPLETE (AUDITED + LIVE VERIFIED + PHASE 1 SIGN-OFF)  

### Concept check (All Verified)
- Does the schema represent physical stations correctly? Yes (Step 1.3/1.6/1.8).
- Are connectors children of stations? Yes (composite FKs enforce station ownership).
- Can Mumbai expand to India? Yes (PostGIS coordinates, country/state/city in dimensions).
- Are operational and analytics concerns separated? Yes (public OLTP vs analytics OLAP warehouse).
- Are user-owned records protected? Yes (29 public RLS policies, role escalation defenses).
- Is provenance retained? Yes (data_sources, station_source_link, observation timestamps).


---

# Phase 2 — Real Data Ingestion
**Goal:** replace hardcoded station data with trustworthy external/community data.

### Steps
2.1 Define canonical station/connector input contract — COMPLETE (CONTRACT DEFINED, VALIDATED, 17/17 TESTS PASSED)  
2.2 Build Python source-adapter structure & Global Source Strategy — COMPLETE / LOCKED (BASE ADAPTER, OCM ADAPTER, GLOBAL SOURCE RESEARCH, 18 FIXTURES, 37/37 TESTS PASSED)  
2.3 Connect first legitimate station data source — COMPLETE / LOCKED (PERSISTENCE SERVICE, IDEMPOTENT RUNNER, LIVE SUPABASE VERIFIED, 52/52 TESTS PASSED)  
2.4 Cross-source entity resolution (candidate generation & evidence fusion) — COMPLETE / LOCKED (PURE RESOLVER, MULTI-SIGNAL EVIDENCE FUSION, 67/67 TESTS PASSED)  
2.5 Normalize fields (cross-source operator, connector, tariff & electrical vocabulary) — COMPLETE / LOCKED (CANONICAL VOCABULARIES, SAFE ALIASES, UNIT CONVERSIONS, 97/97 TESTS PASSED)  
2.6 Validate records (ingestion-wide data quality validation & anomaly quarantine) — NEXT  
2.7 Deduplicate/entity-match stations (canonical decision layer, source priority arbitration & survivorship)  
2.8 Load canonical stations/connectors (transactional operational loading & mutation isolation)  
2.9 Record freshness/provenance (freshness decay engine & observation provenance tracking)  
2.10 Schedule/repeat ingestion (polling daemons, cron scheduling & retry/backoff policies)  
2.11 Verify Mumbai coverage (spatial audit, missing-field rates & Phase 2 quality sign-off)

### Concept check
- Are stations real?
- Are source records traceable?
- Are stale values distinguished from current observations?
- Are duplicates controlled?
- Are we accidentally treating operational status as connector availability?

---

# Phase 3 — Connect the Locked Frontend
**Goal:** turn the completed UI into a real product without redesigning it.

### Steps
3.1 Replace hardcoded station dataset  
3.2 Connect Explore/map  
3.3 Connect search/filter  
3.4 Connect station detail  
3.5 Connect navigation handoff  
3.6 Connect auth/OTP  
3.7 Connect profiles  
3.8 Connect favorites  
3.9 Connect reports  
3.10 Connect reviews  
3.11 Connect alerts  
3.12 Connect admin data views  
3.13 Test loading/empty/error states against real data

### Concept check
- Does the UI say only what the data supports?
- Are unknown fields handled honestly?
- Is login requested only when needed?
- Does the existing UX remain intact?

---

# Phase 4 — Warehouse, Analytics & Data Quality
**Goal:** satisfy the data-warehouse requirement using ChargePlus's real product data.

### Steps
4.1 Build dimensions  
4.2 Build observation/report facts  
4.3 Build daily/hourly aggregates where justified  
4.4 Create ETL/ELT jobs in Python  
4.5 Add data-quality checks  
4.6 Create OLAP queries  
4.7 Build analytics/admin views  
4.8 Validate historical consistency

### Concept check
- Are fact grains explicit?
- Are dimensions reusable?
- Are aggregates derived from real observations?
- Can every analytical number be traced back to underlying records?

---

# Phase 5 — Data Mining, Forecasting & Recommendations
**Goal:** add intelligence only after enough real data exists.

### Steps
5.1 Measure data maturity  
5.2 Establish baseline  
5.3 Feature engineering  
5.4 Train simple model  
5.5 Evaluate MAE/RMSE and appropriate metrics  
5.6 Compare against baseline  
5.7 Produce station busy-time estimates  
5.8 Produce congestion/availability intelligence where supported  
5.9 Build explainable recommendation scoring  
5.10 Connect recommendations/alerts to frontend  
5.11 Document limitations

### Concept check
- Is there enough data?
- Does ML beat or meaningfully complement the baseline?
- Are predictions clearly distinguished from observations?
- Are recommendations explainable?
- Are we avoiding fake confidence?

---

# Phase 6 — Production & Public Beta
**Goal:** make ChargePlus safe and stable for real users.

### Steps
6.1 Production deployment  
6.2 Domain/configuration  
6.3 Security review  
6.4 RLS review  
6.5 Rate limiting/abuse controls  
6.6 Error monitoring/logging  
6.7 Ingestion monitoring  
6.8 ML/forecast monitoring  
6.9 Performance testing  
6.10 Mobile/browser compatibility  
6.11 Data-quality review  
6.12 Public beta checklist  
6.13 Final documentation

### Concept check
- Could a real user misunderstand stale data as live?
- Could one user corrupt shared station knowledge?
- Are failures visible?
- Are secrets protected?
- Can the system be maintained?

---

## Current status

- **Current Phase**: Phase 2/6 — Real Data Ingestion & Data Quality
- **Remaining Phases**: 4 (Phase 3: Connect Locked Frontend, Phase 4: Warehouse, Analytics & Data Quality, Phase 5: Data Mining, Forecasting & Recommendations, Phase 6: Production & Public Beta)
- **Current Step**: Step 2.1 COMPLETE — Ready for Step 2.2
- **Remaining Steps in Phase 2**: 10 (Steps 2.2 through 2.11)

### What is complete:
- **Phase 1 — Foundation & Real Database (Steps 1.1–1.10) — COMPLETE & SIGNED OFF**:
  - 1.1 Create/configure Supabase project — COMPLETE
  - 1.2 Enable required PostgreSQL/PostGIS capabilities — COMPLETE
  - 1.3 Create core operational schema (11 public tables) — COMPLETE
  - 1.4 Create analytics schema (12 analytics tables) — COMPLETE
  - 1.5 Create ML metadata schema (6 ml tables) — COMPLETE
  - 1.6 Add indexes (45 explicit) and constraints (28 explicit) — COMPLETE
  - 1.7 Add RLS policies (29 public, 0 analytics/ml client policies) — COMPLETE
  - 1.8 Add safe database views (4) and functions (2) — COMPLETE (EXECUTED + LIVE VERIFIED)
  - 1.9 Establish environment variables/secrets — COMPLETE (AUDITED + CONFIGURED)
  - 1.10 Verify database with a clean test flow — COMPLETE (AUDITED + LIVE VERIFIED + PHASE 1 SIGN-OFF)

- **Phase 2 — Real Data Ingestion (Steps 2.1 & 2.2) — IN PROGRESS**:
  - 2.1 Define canonical station/connector input contract — COMPLETE
    - Canonical 6-layer contract defined (`RawSourceRecord`, `NormalizedStationRecord`, `NormalizedConnectorRecord`, `NormalizedObservationRecord`)
    - Pydantic models with strict validation rules and contract versioning (`1.0.0`) in `backend/ingestion/`
    - Data quality validation engine (`DataQualityValidator`) with deterministic outcomes (`ACCEPT`, `ACCEPT_WITH_WARNINGS`, `QUARANTINE`, `REJECT`) and 0.0–1.0 scoring
    - Strict missing-data semantics ("Missing means Missing" — no fake ₹0 prices, 0 kW power, or assumed availability)
    - 6 distinct status semantics (operational state, availability, observation, reports, predictions, freshness)
    - Entity resolution / deduplication candidate features preserved
    - 17/17 automated unit tests passed in `tests/test_canonical_contracts.py`
    - Authoritative contract specification: `docs/canonical_station_input_contract.md`
    - Zero production database mutations; Phase 1 architecture fully preserved
  - 2.2 Build Python source-adapter structure & Global Source Strategy — COMPLETE / LOCKED
    - Base adapter framework (`BaseSourceAdapter`, `AdapterResult`, `BatchAdapterResult`) with record-level failure isolation in `backend/ingestion/base.py`
    - Concrete OpenChargeMap adapter (`OpenChargeMapAdapter` in `backend/ingestion/adapters/openchargemap.py`) converting real OCM payloads to Step 2.1 canonical models
    - First-class provenance integration (`ProvenanceInfo`, deterministic SHA-256 payload digests)
    - Confident connector mapping vs ambiguous fallback (`OTHER` + warning); aggregated connectors handled without inventing fake IDs
    - Power normalized to kW; missing power kept `None` (never defaulted to 0 kW or guessed)
    - Strict separation of operational status from dynamic telemetry availability; no fake observations manufactured
    - 18 comprehensive test fixture scenarios in `tests/fixtures/ocm_fixtures.py`
    - 20 unit tests in `tests/test_openchargemap_adapter.py`; all 37 tests passing in `tests/`
    - Comprehensive source research & architecture lock (`docs/global_ev_charging_data_source_research.md`): 5-tier source classification, Kafka excluded, real-time telemetry definitions, 2-tier deduplication, canonical UUID vs source ID separation
    - Zero Supabase writes confirmed live across all tables
  - 2.3 Connect first legitimate station data source — COMPLETE / LOCKED
    - Transactional persistence boundary (`IngestionPersistenceService` in `backend/ingestion/persistence.py`) separate from non-persistent adapter
    - Safe idempotent mapping via `public.station_source_link` (SHA-256 payload hash, external OCM ID separated from ChargePlus UUID)
    - Full database constraint adherence (`chk_stations_hours`, Indian PIN validation, connector capacity group aggregation to satisfy `uq_connectors_station_type_power`)
    - PostGIS geometry trigger `trg_stations_geom` verified live generating `POINT(lng lat)`
    - Dimensional conformed observation persistence to `public.station_observations` and `analytics.fact_station_observation` (only when automated telemetry exists)
    - Orchestrator and CLI runner (`IngestionRunner` in `backend/ingestion/runner.py`) with `--dry-run`, `--limit`, `--use-fixtures`, and `--json`
    - Geographic bounding box enforcement (Mumbai Metropolitan Region `18.70-19.50 N`, `72.70-73.30 E`)
    - Record-level error isolation in batches; zero credentials exposed in logs/code
    - Comprehensive test suite: 15 persistence/orchestration tests in `tests/test_ingestion_persistence.py`; all 52 tests passing in `tests/`
    - Live Supabase PostgreSQL database integration verified with zero schema modifications
    - Complete documentation in `docs/step_2_3_first_live_source_persistence.md`
  - 2.4 Cross-source entity resolution & candidate engine — COMPLETE / LOCKED
    - Geodetic candidate generation using Haversine indexing within 500m radius (`CrossSourceEntityResolver` in `backend/ingestion/resolution.py`)
    - Multi-signal evidence fusion: Geodetic proximity, lexical name similarity (token sort ratio), address & hierarchy match, operator agreement, connector signature compatibility
    - 4 distinct match states: `MATCH` (confidence $\ge 0.85$), `PROBABLE_MATCH` ($0.65 \le c < 0.85$), `AMBIGUOUS` ($0.45 \le c < 0.65$), `NON_MATCH` ($c < 0.45$)
    - Strict boundary: Evaluates candidate physical identity without merging stations or mutating records
    - 15 unit tests in `tests/test_entity_resolution.py`; all 67 tests passing in `tests/`
    - Complete documentation in `docs/step_2_4_cross_source_entity_resolution.md`
  - 2.5 Cross-source field normalization & standard vocabulary — COMPLETE / LOCKED
    - Pure computational normalization engine (`backend/ingestion/normalization.py`) with zero external network or LLM dependencies
    - Canonical vocabularies: Verified operator registry with explicit alias mapping (`Tata Power`, `Jio-bp pulse`, `Ather Energy`, `Fortum Charge & Drive`, `ChargeZone`, `Statiq`, `Magenta ChargeGrid`, `Bolt.Earth`, `Zeon Charging`, `Kazam`, `Lithion Power`, `Stilt Mobility`, `ChargePlus`)
    - Connector vocabulary standardized to `StandardConnectorType` (`CCS2`, `CCS1`, `Type 2`, `Type 1`, `CHAdeMO`, `GB/T`, `Bharat AC001`, `Bharat DC001`, `Other`)
    - Electrical normalization: Direct kW preserved, Watts converted to kW ($W / 1000.0$), voltage and amperage kept strictly independent
    - Geospatial & Address: Unicode NFKD, safe road abbreviation expansion, infrastructure acronym preservation (`BKC`, `MIDC`), Indian 6-digit PIN enforcement (`^[1-9][0-9]{5}$`)
    - Pricing & Hours: Distinguishes tariff basis (`per_kwh`, `per_session`, `per_hour`), explicit free charging distinguished from missing pricing, 24x7 schedule formatted to satisfy DB check constraint `chk_stations_hours`
    - Invariant: "Missing means missing" strictly preserved (never defaulted to 0 kW, ₹0, or guessed schedules)
    - Full idempotency and determinism: $\text{normalize}(\text{normalize}(x)) \equiv \text{normalize}(x)$ with zero runtime timestamp drift
    - 30 unit tests in `tests/test_field_normalization.py`; all 97 tests passing in `tests/`
    - Complete documentation in `docs/step_2_5_field_normalization.md`
  - 2.6 Validate records (ingestion-wide data quality validation & anomaly quarantine) — COMPLETE / LOCKED
    - Multi-layered data quality evaluation framework (`backend/ingestion/validation.py`) with stable rule catalog IDs (`DQ-PROV-001..004`, `DQ-NAME-001..002`, `DQ-OP-001`, `DQ-GEO-001..005`, `DQ-ADDR-001..002`, `DQ-HOURS-001..003`, `DQ-CONN-001..004`, `DQ-ELEC-001..008`, `DQ-PRICE-001..004`, `DQ-OBS-001..003`)
    - Contract outcomes strictly mapped to four severity levels: `ACCEPT` (no issues), `ACCEPT_WITH_WARNINGS` (INFO / WARNING), `QUARANTINE` (HIGH physical / geofence anomaly), `REJECT` (CRITICAL non-negotiable defect)
    - Critical architectural invariants: No silent repair (bad data is never secretly corrected), missing means missing (never defaulted to 0 kW or ₹0), operational state decoupled from real-time availability and freshness
    - In-memory anomaly quarantine representation (`QuarantineRecord`) preserving full Layer 1 provenance, all failed rule IDs, and human-readable reasons, isolated from canonical operational tables
    - Deterministic batch validation engine (`BatchValidationReport`) with completeness ratios, issue distributions, and zero record loss
    - Strict boundary enforcement: Zero merging, zero deduplication, zero canonical UUID assignment, zero source precedence decisions (deferred to Step 2.7)
    - 40 comprehensive unit tests in `tests/test_data_quality_validation.py`; all 137 tests passing in `tests/`
    - Complete documentation in `docs/step_2_6_data_quality_validation.md`

### Current Phase & Step:
- Current Phase: Phase 2/6 (Real Data Ingestion & Data Quality)
- Remaining Phases: 4 (Phases 3, 4, 5, 6)
- Current Step: Step 2.6 COMPLETE / LOCKED
- Remaining Steps in Phase 2: 5 (Steps 2.7 through 2.11)

### What we are doing now:
- Step 2.6 completed, verified, tested, and locked. Ready to begin Step 2.7 upon instruction.

### What comes next:
- **Step 2.7 — Canonical station decision layer (source precedence & survivorship)**: Canonical station deduplication, multi-source conflict arbitration, field-level survivorship rules, and canonical station clustering.


