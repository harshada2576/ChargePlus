# ChargePlus — Canonical Station & Connector Input Contract Specification

**Phase:** 2/6 (Real Data Ingestion & Data Quality)  
**Step:** 2.1 (Define Canonical Station/Connector Input Contract)  
**Contract Version:** `1.0.0`  
**Status:** COMPLETE & AUTHORITATIVE  
**Implementation Modules:** [`backend/ingestion/contracts.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/contracts.py), [`backend/ingestion/validation.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/validation.py), [`backend/ingestion/constants.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/constants.py)  
**Test Suite:** [`tests/test_canonical_contracts.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/tests/test_canonical_contracts.py) (17/17 tests passing)  

---

## 1. Executive Summary & Purpose

The purpose of **Step 2.1** is to establish the source-neutral canonical input contract that governs all external charging station data entering ChargePlus.

Before ChargePlus accepts station data from any external source (e.g., OpenChargeMap, government portals, CPO private APIs, community aggregators), the data must conform to this contract. This contract answers:

> *"What does a valid, trustworthy incoming charging-station record look like before ChargePlus accepts it into the operational system?"*

### Core Architectural Mandates
1. **Source Neutrality**: No single commercial provider (OpenChargeMap, Google, PlugShare, Tata Power) dictates our schema. All external formats must map *into* the ChargePlus contract.
2. **Missing Means Missing**: Never invent default data. Missing price is `None` (never ₹0). Missing power is `None` (never 0 kW). Missing availability is `unknown` (never assumed "available"). Missing coordinates are rejected (never defaulted to Mumbai).
3. **Strict Separation of Data Layers**: Raw payloads are archived unaltered. Normalized records are validated. Canonical physical stations and connectors represent physical reality. Observations capture telemetry snapshots over time. The analytical warehouse (`analytics.*`) stores historical facts.
4. **Hard Status Demarcation**: Operational station status, point-in-time connector occupancy, crowdsourced user reports, data freshness, and future ML predictions are distinct semantic concepts and must never be collapsed into a single status field.

---

## 2. The Six Architectural Data Layers

```text
┌────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: RAW SOURCE RECORD                                             │
│ Verbatim external payload, source ID, record key, retrieval timestamp, │
│ deterministic SHA-256 payload hash. Never mutated.                     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Python Adapter Parsing
┌───────────────────────────────────▼────────────────────────────────────┐
│ LAYER 2: NORMALIZED SOURCE RECORD                                      │
│ Standardized fields (WGS 84 coords, cleaned name, normalized plugs,   │
│ observation telemetry), preserving raw strings and extra metadata.     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Data Quality Validation & Deduplication
                  ┌─────────────────┴─────────────────┐
                  ▼                                   ▼
┌───────────────────────────────────┐ ┌──────────────────────────────────┐
│ LAYER 3: CANONICAL STATION        │ │ LAYER 4: CANONICAL CONNECTORS    │
│ Physical location: public.stations│ │ Capacity: public.connectors      │
│ One physical site, unique UUID.   │ │ Children of station, composite FK│
└─────────────────┬─────────────────┘ └──────────────────┬───────────────┘
                  │                                      │
                  └─────────────────┬────────────────────┘
                                    │ Real-Time Telemetry Stream
┌───────────────────────────────────▼────────────────────────────────────┐
│ LAYER 5: OPERATIONAL OBSERVATIONS                                      │
│ Time-varying status: public.station_observations                       │
│ Point-in-time availability, queue level, available plug counts.        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Python Warehouse ETL
┌───────────────────────────────────▼────────────────────────────────────┐
│ LAYER 6: ANALYTICAL DATA WAREHOUSE                                     │
│ Canonical OLAP warehouse: analytics.* (8 dimensions + 4 facts)         │
│ Canonical Facts:                                                       │
│   • analytics.fact_station_observation                                 │
│   • analytics.fact_user_report                                         │
│   • analytics.fact_review                                              │
│   • analytics.fact_station_daily                                       │
│ (Note: analytics.fact_charging_session is NOT part of the canonical    │
│ Phase 1 warehouse; excluded because no legitimate session feed exists) │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Station Input Contract Specification

The station record represents a physical charging facility.

| Field Name | Type | Mandatory? | Semantic Meaning | Validation & Normalization Rules | Destination Layer / DB Placement | Volatility |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `contract_version` | String | **Required** | Contract specification version | Must equal `"1.0.0"`. | Contract Header / Provenance | Static |
| `source_id` | String | **Required** | Registry ID of external source | Non-empty string (1–120 chars), e.g. `'open_charge_map'`. | `public.station_source_link.source_id` | Static |
| `source_station_id` | String | **Required** | External provider primary key | Non-empty string (1–500 chars). Unaltered external key. | `public.station_source_link.source_station_id` | Static |
| `source_url` | String | Optional | Web URL to external station page | Valid URI format if present; `None` if missing. | `public.station_source_link.source_url` | Static |
| `raw_payload_hash` | String | Optional | SHA-256 hash of Layer 1 payload | 64-character hexadecimal digest for change detection. | `public.station_source_link.source_payload_hash` | Per Ingestion |
| `name` | String | **Required** | Cleaned station display name | Stripped, 2–300 chars. Title-cased if uppercase. | `public.stations.name` | Low |
| `raw_name` | String | Optional | Unaltered source station name | Preserved for audit and entity resolution. | Raw Layer / Metadata | Static |
| `operator_name` | String | Optional | Commercial operator/CPO name | Cleaned name (e.g. "Tata Power EZ Charge", "Jio-bp pulse"). | Resolves `public.stations.operator_id` | Low |
| `operator_slug` | String | Optional | Normalized token for operator lookup | Alphanumeric slug matching `^[a-zA-Z0-9_-]+$`. | Maps to `public.operators.slug` | Low |
| `latitude` | Float | **Required** | WGS 84 latitude in decimal degrees | Must be in `[-90.0, 90.0]`. `(lat, lon) != (0.0, 0.0)`. (0.0 on Equator is valid). | `public.stations.latitude` & `geom` | Static |
| `longitude` | Float | **Required** | WGS 84 longitude in decimal degrees | Must be in `[-180.0, 180.0]`. `(lat, lon) != (0.0, 0.0)`. (0.0 on Prime Meridian is valid). | `public.stations.longitude` & `geom` | Static |
| `address_line` | String | Optional | Street address, building, road | Cleaned street address string; `None` if missing. | `public.stations.address_line` | Low |
| `locality` | String | Optional | Suburb / neighborhood / district | Area identifier (e.g. "BKC", "Andheri East"). | `public.stations.locality` | Low |
| `city` | String | **Required** | Municipality / City | Defaults to `'Mumbai'` for pilot, India-ready. | `public.stations.city` | Low |
| `state` | String | **Required** | State or Province | Defaults to `'Maharashtra'`, India-ready. | `public.stations.state` | Low |
| `postal_code` | String | Optional | Postal code / PIN code | In India, must match `^[1-9][0-9]{5}$`. `None` if unknown. | `public.stations.postal_code` | Low |
| `country` | String | **Required** | Sovereign nation | Defaults to `'India'`. Ingestion handles any valid nation. | `public.stations.country` | Low |
| `is_24_hours` | Boolean | Optional | 24-hour operation flag | Boolean or `None`. Cannot conflict with open/close times. | `public.stations.is_24_hours` | Low |
| `opening_time` | String | Optional | Daily opening time | Format `HH:MM` (24h clock); `None` if 24h or unknown. | `public.stations.opening_time` | Low |
| `closing_time` | String | Optional | Daily closing time | Format `HH:MM` (24h clock); `None` if 24h or unknown. | `public.stations.closing_time` | Low |
| `access_type` | String | Optional | Site access restriction | Descriptive string ("Public", "Customer Only", "Fleet"). | `public.stations.access_type` | Low |
| `is_public` | Boolean | **Required** | Public accessibility boolean | Defaults to `True`. `False` for strictly private/fleet. | `public.stations.is_public` | Low |
| `operational_status` | Enum | **Required** | Site operational state | Enum: `unknown`, `operational`, `temporarily_unavailable`, `permanently_closed`. | `public.stations.operational_status` | Medium |
| `phone` | String | Optional | Support / site telephone | Validated phone string; `None` if missing. | `public.stations.phone` | Low |
| `website_url` | String | Optional | Specific website link | Validated URI format; `None` if missing. | `public.stations.website_url` | Low |
| `connectors` | List | Optional | Child connector specifications | List of `NormalizedConnectorRecord`. Minimum 0. | `public.connectors` | Medium |
| `observation` | Object | Optional | Initial telemetry snapshot | `NormalizedObservationRecord` if provided by feed. | `public.station_observations` | High |
| `extra_metadata` | Dict | Optional | Unmapped provider attributes | JSON dictionary storing provider-specific extensions. | `public.station_source_link` / raw | Medium |

---

## 4. Connector Input Contract Specification

Connectors model charging points attached to physical stations.

| Field Name | Type | Mandatory? | Semantic Meaning | Handling & Normalization Rules | Destination Layer / DB Placement |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `source_connector_id` | String | Optional | External plug identifier | Individual plug key if source identifies plugs individually; `None` if aggregated. | `public.connectors.id` (or mapped) |
| `connector_type` | String | **Required** | Normalized standard | Normalized to standard enum: `CCS2`, `CCS1`, `CHAdeMO`, `Type 2`, `Type 1`, `GB/T`, `Bharat AC001`, `Bharat DC001`, or `'Other'`. | `public.connectors.connector_type` |
| `raw_connector_type` | String | **Required** | Raw label from source | Exact string from source (e.g. `"CCS (Type 2)"`, `"IEC 62196-2 Mennekes"`). Preserved without loss. | Adapter / Warehouse lineage |
| `charging_standard` | String | Optional | Underlying electrical standard | Standard specification string (e.g. `'IEC 62196-3'`); `None` if omitted. | `public.connectors.charging_standard` |
| `power_kw` | Float | Optional | Peak output power in kW | Must be strictly positive (`> 0.0`). Plausibility range `[1.0, 500.0]`. **NEVER 0.0**. `None` if missing. | `public.connectors.power_kw` |
| `voltage_v` | Float | Optional | Operating voltage in Volts | Rated voltage if supplied by source; `None` if omitted. | Raw payload / Warehouse extension |
| `amperage_a` | Float | Optional | Operating current in Amps | Rated current if supplied by source; `None` if omitted. | Raw payload / Warehouse extension |
| `quantity` | Integer | **Required** | Number of physical plugs | Integer `>= 1`. Supports aggregated source reports (e.g. "4x CCS2 60kW"). | `public.connectors.quantity` |
| `is_aggregated` | Boolean | **Required** | Aggregation indicator | `True` if `quantity > 1` represents multiple physical plugs grouped together. | Internal ingestion metadata |
| `pricing_type` | Enum | **Required** | High-level pricing category | Enum: `free`, `paid`, `unknown`. Default `unknown`. **NEVER assumed free**. | `public.connectors.pricing_type` |
| `price_per_kwh` | Float | Optional | Rate per kilowatt-hour | Numeric `>= 0.0`. `None` if unknown. **NEVER ₹0** unless explicitly verified free. | `public.connectors.price_per_kwh` |
| `price_per_session` | Float | Optional | Fixed connection/parking fee | Numeric `>= 0.0`. `None` if unknown. | `public.connectors.price_per_session` |
| `currency` | String | **Required** | Tariff currency code | Defaults to `'INR'`. Length 1–10 chars. | `public.connectors.currency` |
| `status` | Enum | Optional | Connector-level occupancy | Optional point-in-time occupancy status if feed reports per-plug state. | Telemetry observation link |

### Handling Individual vs. Aggregated Plugs
- **Individual Plugs**: When an API reports individual plugs with unique IDs (`source_connector_id = "PLUG-01"`, `quantity = 1`), they are ingested as distinct connector entities.
- **Aggregated Groups**: When an API reports aggregated capacity (e.g., *"4 CCS chargers, 60 kW"*), the record is ingested with `quantity = 4`, `is_aggregated = True`, and `source_connector_id = None`. **ChargePlus does NOT fabricate synthetic plug IDs** at the source contract level.

---

## 5. Observation Contract Specification

Observations capture volatile point-in-time telemetry distinct from static station identity.

| Field Name | Type | Mandatory? | Semantic Meaning | Handling & Validation Rules | Destination Layer / DB Placement |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `source_id` | String | **Required** | Originating feed identifier | Must match registered source. | `public.station_observations.source_id` |
| `source_station_id` | String | **Required** | External station identifier | Links observation to station provenance. | `public.station_source_link` lookup |
| `source_connector_id` | String | Optional | External plug identifier | Connector-specific observation if supplied; `None` for station-level. | `public.station_observations.connector_id` |
| `observed_at` | DateTime | **Required** | Event occurrence timestamp | UTC timestamp. Cannot be in the future (5 min margin). Must include timezone. | `public.station_observations.observed_at` |
| `retrieved_at` | DateTime | **Required** | System ingestion timestamp | UTC timestamp generated at time of fetch. `retrieved_at >= observed_at`. | `public.station_observations.received_at` |
| `availability_status` | Enum | **Required** | Observed occupancy state | Enum: `available`, `busy`, `broken`, `unknown`. Default `unknown`. | `public.station_observations.availability_status` |
| `queue_level` | Enum | **Required** | Observed queue severity | Enum: `none`, `short`, `medium`, `long`, `unknown`. Default `unknown`. | `public.station_observations.queue_level` |
| `available_connectors`| Integer | Optional | Count of vacant plugs | Integer `>= 0`. Must be `<= total_connectors` if both provided. | `public.station_observations.available_connectors` |
| `total_connectors` | Integer | Optional | Count of total operational plugs | Integer `>= 0`. `None` if unknown. | `public.station_observations.total_connectors` |
| `raw_status_label` | String | Optional | Verbatim external status | Preserves exact raw string (e.g. `"Charging"`, `"Faulted"`). | Lineage / Telemetry audit |
| `confidence_score` | Float | Optional | Data trustworthiness rating | Numeric between `0.0` and `1.0`. Evaluated by source latency and type. | `public.station_observations.confidence_score` |
| `source_payload_hash` | String | Optional | Telemetry payload hash | SHA-256 hash for telemetry change detection. | `public.station_observations.source_payload_hash` |

---

## 6. Status Semantics (Six Distinct Concepts)

ChargePlus strictly separates status into six distinct semantic dimensions. **They must never be collapsed into a single generic "status":**

```text
┌────────────────────────────────────────────────────────────────────────┐
│ 1. OPERATIONAL STATE (Physical Site Facility)                          │
│    Is the location open and powered?                                   │
│    Values: operational, temporarily_unavailable, permanently_closed,   │
│            unknown                                                     │
├────────────────────────────────────────────────────────────────────────┤
│ 2. CONNECTOR AVAILABILITY (Occupancy Telemetry)                        │
│    Is a specific plug currently plugged into a car or vacant?          │
│    Values: available, busy, broken, unknown                            │
├────────────────────────────────────────────────────────────────────────┤
│ 3. OBSERVATION STATE (Point-in-Time Snapshot)                          │
│    Telemetry evidence recorded at observed_at with queue level.        │
│    Values: queue_level (none, short, medium, long, unknown)            │
├────────────────────────────────────────────────────────────────────────┤
│ 4. USER REPORT STATE (Crowdsourced Human Evidence)                     │
│    Community submissions subject to moderation.                        │
│    Values: moderation_status (pending, approved, rejected)             │
├────────────────────────────────────────────────────────────────────────┤
│ 5. PREDICTED STATE (Analytical / ML Inference)                         │
│    Historical pattern or machine learning forecast for a time horizon. │
│    Values: busy-window suggestions, congestion probability [0.0..1.0]  │
│    NEVER presented as confirmed real-time truth.                       │
├────────────────────────────────────────────────────────────────────────┤
│ 6. DATA FRESHNESS (Temporal Relevance)                                 │
│    Time elapsed since observation (minutes_since_observation).         │
│    Rule: Stale (e.g. 5 hours old) ≠ Unavailable. Missing ≠ Broken.    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Identity & Entity Deduplication Evidence

To prevent duplicate physical charging stations from cluttering the map when ingested across multiple external sources, Step 2.1 defines the **identity inputs** that future entity resolution (Step 2.7) will evaluate:

1. **Source Identity (Layer 1/2)**: `(source_id, source_station_id)` uniquely identifies a record within a vendor feed. Enforced by database constraint `uq_station_source_link_source_record`.
2. **Canonical Station Identity (Layer 3)**: Independent `public.stations.id` (UUID). External source IDs **never** become canonical station UUIDs.
3. **Candidate Matching Features (for Step 2.7 Entity Matching)**:
   - **Spatial Proximity**: Geodetic distance calculated via PostGIS `ST_DWithin` (threshold e.g. `< 50 meters`).
   - **Operator Match**: Normalized `operator_slug` equivalence.
   - **Name Similarity**: Token sort ratio / Levenshtein distance on `name`.
   - **Address & Locality**: Suburb, road name, and postal PIN code matching.
   - **Connector Signature**: Set intersection of supported connector types and power tiers.

---

## 8. Data Quality Rules & Validation Outcomes

The `DataQualityValidator` evaluates every incoming record into one of four deterministic outcomes:

```text
                  Incoming Normalized Record
                              │
                     Has Fatal Defects?
                  (missing coords, bad lat/lng,
                   empty name, missing source ID)
                             / \
                       YES  /   \  NO
                           /     \
                      REJECT   Has Critical Geofence /
                               Plausibility Anomaly?
                               (coords outside India)
                                       / \
                                 YES  /   \  NO
                                     /     \
                               QUARANTINE  Has Quality Warnings?
                                           (missing phone, PIN code format,
                                            unmapped plug type, stale time)
                                                   / \
                                             YES  /   \  NO
                                                 /     \
                                ACCEPT_WITH_WARNINGS  ACCEPT
```

### Outcome Definitions & Examples

| Outcome | Definition | Ingestion Action | Example Scenarios |
| :--- | :--- | :--- | :--- |
| **`ACCEPT`** | Fully compliant record. Valid coordinates, name, operator, connectors, and fresh observation. | Persist to operational tables (`public.stations`, `public.connectors`, `public.station_observations`). | Clean Mumbai station with valid CCS2 60kW plug, phone, BKC address, and fresh telemetry. |
| **`ACCEPT_WITH_WARNINGS`** | Valid physical station, but missing optional attributes or has non-fatal formatting warnings. | Persist to operational tables with warnings logged for data quality audit. | - Station with valid coordinates but missing phone or website.<br>- Station with unstandardized plug label (e.g. "Custom Mennekes").<br>- Valid station with stale observation (> 24 hours old). |
| **`QUARANTINE`** | Plausible EV charging data, but failed a critical geographic boundary or verification threshold. | Divert to quarantine queue for secondary automated verification or operator review. | - Station listed with country "India", but coordinates fall outside Indian geographic territory.<br>- Multiple conflicting operator claims for the same physical address. |
| **`REJECT`** | Fatal, unrecoverable defect that would corrupt platform integrity. | Completely discard from operational ingestion. Log fatal error with source context. | - Missing latitude or longitude.<br>- Coordinates at exactly (0.0, 0.0) [Null Island] (Note: individual 0.0 on Equator or Prime Meridian is valid; only the combination is rejected).<br>- Latitude outside `[-90, 90]` or longitude outside `[-180, 180]`.<br>- Missing station name or empty source ID.<br>- Connector power `<= 0.0 kW` (e.g. 0 kW or negative).<br>- Observation timestamp in the future (> 5 min). |

---

## 9. Price, Tariff & Weather Policies

### Price & Tariff Policy
- Phase 1 intentionally does **not** have a canonical standalone tariff table (`dim_tariff` in public remains legacy and empty).
- `public.connectors` contains `pricing_type`, `price_per_kwh`, `price_per_session`, and `currency`.
- **Policy**: If an external source provides structured pricing, it is parsed into `price_per_kwh` and `pricing_type`. If pricing is omitted, it remains `None` / `PricingType.UNKNOWN`. **ChargePlus never fabricates rate details or assumes zero cost.** Complex time-of-day tariffs are stored in `extra_metadata` until future tariff models are introduced.

### Weather Policy
- `analytics.dim_weather` is an unpopulated warehouse placeholder.
- Weather observations are explicitly deferred to future enrichment pipelines. External station adapters must not attempt to fetch or inject synthetic weather data during station ingestion.

---

## 10. Raw Data Storage & Ingestion Pipeline Roadmap

### Why Raw Tables Belong in Step 2.2+, Not Step 2.1
- **Step 2.1** defines the input contract, validation criteria, and status semantics.
- In Phase 1, `public.data_sources` (source registry) and `public.station_source_link` (provenance link with `source_payload_hash`) were established and live verified.
- Dedicated staging infrastructure (e.g. file-based JSONL archive in object storage or an ingestion run table) will be implemented alongside the specific Python adapter structure in **Step 2.2**. This keeps Step 2.1 cleanly focused on the source-neutral contract.

---

## 11. Code Verification & Test Results

The Python contract implementation was validated against all 17 required scenarios:

```bash
python -m pytest tests/test_canonical_contracts.py
```

### Test Suite Execution Output
```text
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-8.3.5, pluggy-1.6.0
rootdir: C:\Users\Admin\Desktop\Projects\ChargePlus
collected 17 items

tests/test_canonical_contracts.py .................                      [100%]

============================= 17 passed in 0.52s ==============================
```

| Test Case | Scenario Tested | Outcome Verified |
| :--- | :--- | :--- |
| `test_01_valid_station` | Fully compliant Mumbai station with connector & telemetry | `ACCEPT`, Quality score `0.70+` |
| `test_02_missing_optional_field` | Missing phone, website, and hours | `ACCEPT_WITH_WARNINGS`, `phone=None` |
| `test_03_missing_required_field` | Missing latitude or empty station name | `ValidationError` raised |
| `test_04_invalid_latitude` | Latitude `95.1234` | `ValidationError` raised |
| `test_05_invalid_longitude` | Longitude `185.0` | `ValidationError` raised |
| `test_06_invalid_power` | Connector power `0.0 kW` or `-25.0 kW` | `ValidationError` raised (never 0 kW) |
| `test_07_unknown_connector_type` | Proprietary/unmapped plug label | `ACCEPT_WITH_WARNINGS`, raw string preserved |
| `test_08_multiple_connectors` | Station with CCS2, CHAdeMO, and Type 2 | 3 connectors accepted under 1 station |
| `test_09_aggregated_connector_count` | 4x CCS2 capacity reported as group | `quantity=4`, `is_aggregated=True`, no fake IDs |
| `test_10_missing_availability` | Directory station without real-time telemetry | `observation=None`, missing ≠ broken |
| `test_11_stale_timestamp` | Observation timestamp 36 hours old | `ACCEPT_WITH_WARNINGS`, stale warning generated |
| `test_12_invalid_timestamp` | Observation timestamp 2 hours in future | `REJECT`, future timestamp error generated |
| `test_13_duplicate_source_record` | Identical raw payloads | Identical SHA-256 hash generated |
| `test_14_source_specific_extra_fields` | Unmapped provider metadata (amenities, parking) | Preserved in `extra_metadata` |
| `test_15_provenance_missing` | Empty source ID or source record key | `ValidationError` raised |
| `test_16_null_unknown_values` | Missing price, hours, phone, postal code | Preserved as `None`, never converted to zero |
| `test_17_contract_version` | Contract version verification | Matches `"1.0.0"` |
