# ChargePlus — Global EV Charging Data Source Research & Acquisition Architecture

**Status:** COMPLETE, AUDITED & ARCHITECTURALLY LOCKED (Phase 2, Step 2.2 Closure)  
**Scope:** Global EV Charging Data Sources, Acquisition Taxonomy, Real-Time Telemetry Boundaries, and Ingestion Strategy  
**Implementation Phase:** Architecture Lock for Step 2.2 — Transition to Step 2.3  
**Target Pilot:** Mumbai Metropolitan Region (MMR), Maharashtra, India (Expanding nationwide and globally)

---

## 1. Executive Summary & Problem Context

Electric vehicle (EV) charging information is globally fragmented, frequently stale, structurally incomplete, and plagued by unsubstantiated availability claims. The primary engineering goal of ChargePlus is encapsulated in its mission:

> *"Find the right charger, before you reach the queue."*

To deliver on this promise without compromising data integrity, ChargePlus enforces a foundational tenet: **Truth in Ingestion — We never fabricate business truth, availability, pricing, or physical connectivity.**

This document synthesizes global EV charging data source research, evaluates technical accessibility and legal boundaries, formally defines real-time telemetry ingestion, specifies deduplication and provenance mechanics, and establishes an immutable architectural lock for the Phase 2 ingestion pipeline.

---

## 2. Source Verification & Classification Framework

Every candidate external data source evaluated by ChargePlus is classified under a strict evidentiary hierarchy:

- **VERIFIED:** Publicly documented, legally accessible, stable API or data dump with confirmed licensing, predictable schema, and tested access mechanics.
- **PARTIALLY VERIFIED:** Authoritative organization or dataset exists, but public programmatic access, rate limits, licensing terms, or endpoint stability are undocumented or restricted.
- **UNVERIFIED — DO NOT USE:** Speculative endpoints, private mobile application backends, undocumented scrapers, or third-party feeds without clear redistribution rights.

### Source Priority Tiers for Ingestion Planning

```
┌────────────────────────────────────────────────────────────────────────┐
│ TIER 1: USABLE NOW / LOWEST FRICTION (Open & Documented)               │
│ - OpenChargeMap (API v3, verified global coverage, active community)   │
│ - OpenStreetMap (Overpass API / Planet dumps, spatial geometry)        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ TIER 2: STATIC / PERIODIC SUPPORTING DATASETS (Official Reference)     │
│ - NREL Alternative Fuels Data Center (US/Canada gold standard reference)│
│ - Indian Government Open Data (data.gov.in, state EV portal dumps)     │
│ - Bureau of Energy Efficiency (BEE) public registry notices            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ TIER 3: PARTNERSHIP & PERMISSION DEPENDENT (Direct Integration)        │
│ - e-AMRIT (NITI Aayog / BEE National EV Portal — requires MoA/API key) │
│ - Direct CPO Feeds via OCPI 2.2.1 (Tata Power, Jio-bp, Statiq, etc.)  │
│ - Roaming Hubs (Hubject intercharge, GIREVE)                           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ TIER 4: COMMERCIAL / REDISTRIBUTION RESTRICTED (Commercial Contract)   │
│ - Commercial Mapping APIs (Google Places, HERE EV, TomTom, Mappls)     │
│ - Subject to strict no-caching and derivative-data licensing terms     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ TIER 5: STRICTLY PROHIBITED (Unethical / Illegal / Fragile)            │
│ - Reverse-engineered private CPO mobile application APIs               │
│ - Unauthorized scraping of private web portals                         │
│ - Unverified third-party data aggregators with unknown provenance      │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Source Evaluations

### 3.1 Tier 1: OpenChargeMap (OCM) — VERIFIED
- **Coverage:** Global, with strong coverage across Europe, North America, and growing crowdsourced coverage in India (>2,500 listed stations across India; active Mumbai hub coverage).
- **Format & Access:** RESTful JSON API (`https://api.openchargemap.io/v3/poi/`), API key required via `X-ApiKey` header. Supports spatial bounding box filtering (`boundingbox=(lat1,lng1),(lat2,lng2)`), country codes (`countrycode=IN`), and delta timestamps (`modifiedsince`).
- **Data Model:** Clean separation between `AddressInfo` (spatial identity), `OperatorInfo` (CPO identity), `StatusType` (operational status), and `Connections` (connectors with power, voltage, quantity, and mechanical type).
- **Availability Semantics:** Primarily static equipment operational status (`StatusTypeID: 50` $\to$ Operational). Certain partner networks supply automated telemetry (`StatusTypeID: 10` $\to$ Available, `StatusTypeID: 20` $\to$ In Use) with `DateLastStatusUpdate`.
- **Licensing & Attribution:** Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) with third-party contributor terms. Ingestion pipeline must preserve data provider credits and origin licensing per record.

### 3.2 Tier 1: OpenStreetMap (OSM) — VERIFIED
- **Coverage:** Extensive global geographic coverage; highly detailed micro-location spatial data (exact bay footprint, access tags, surface type, opening hours).
- **Format & Access:** Overpass QL API / Overpass Turbo, Planet OSM PBF dumps. Querying `amenity=charging_station`.
- **Key Tags:** `socket:<type>=<count>`, `capacity=*`, `operator=*`, `brand=*`, `opening_hours=*`, `fee=yes/no`, `authentication:*=yes/no`.
- **Availability Semantics:** Completely static physical inventory. OSM *never* carries dynamic live availability telemetry.
- **Licensing & Attribution:** Open Database License (ODbL) 1.0. Attribution required: *"© OpenStreetMap contributors"*. Data mixed into derivative databases must adhere to ODbL Share-Alike terms.

### 3.3 Tier 2: NREL Alternative Fuels Data Center (AFDC) — VERIFIED (US/Canada Reference)
- **Coverage:** United States and Canada (Federal repository maintained by US Department of Energy).
- **Significance:** Industry benchmark for government data governance, standardized connector taxonomy (J1772, CCS, CHAdeMO, NACS/J3400), and station verification tiers.
- **Role in ChargePlus:** Serves as a reference architectural standard for schema design, field rigor, and government registry integration patterns.

### 3.4 Tier 2 / Tier 3: Indian Government Initiatives (e-AMRIT, BEE, data.gov.in) — PARTIALLY VERIFIED
- **Overview:**
  - **e-AMRIT (Accelerated e-Mobility Revolution for India's Transportation):** NITI Aayog's flagship national EV portal, serving as the central clearinghouse for FAME-II and PM E-DRIVE subsidized infrastructure.
  - **BEE (Bureau of Energy Efficiency):** Central Nodal Agency for EV public charging infrastructure standards.
  - **data.gov.in:** Open Government Data (OGD) platform providing periodic CSV/JSON dumps of public charging stations registered under central schemes.
- **Access Reality:** While web portals exist, **no unrestricted, open-access, public real-time REST API is currently published for production commercial consumption**. Direct consumption of internal portal endpoints without bilateral authorization is prohibited (Tier 5).
- **Architectural Decision:** ChargePlus treats published government datasets (e.g. data.gov.in releases) as Tier 2 static verification feeds. Direct e-AMRIT programmatic integration is classified as Tier 3, requiring formal MoA or institutional API credentials.

### 3.5 Tier 3: Open Charge Point Interface (OCPI) — PROTOCOL (Not a Public Dataset)
- **Clarification of Common Misconception:** **OCPI is an open protocol standard, NOT a centralized public API or global database.**
- **Protocol Functionality:** OCPI (version 2.2.1) defines standardized peer-to-peer REST endpoints between Charge Point Operators (CPOs) and e-Mobility Service Providers (eMSPs):
  - `Locations` module: Physical station, EVSE, and connector topology.
  - `Tariffs` module: Complex real-time pricing models (flat, per-minute, per-kWh, idle fees).
  - `Sessions` module: Active charging transaction states.
  - `CDRs` (Charge Detail Records): Post-session billing records.
  - `Status` / `Commands`: Real-time EVSE availability pushes (`AVAILABLE`, `CHARGING`, `BLOCKED`, `OUTOFORDER`, `INOPERATIVE`).
- **ChargePlus Strategy:** ChargePlus will adopt OCPI 2.2.1 data models as its external CPO partnership boundary. However, each OCPI connection requires a bilateral business agreement, credentials exchange, and IP whitelisting with the individual CPO or roaming hub (Hubject / GIREVE).

### 3.6 Tier 4: Commercial Mapping & EV APIs — COMMERCIAL RESTRICTIONS
- **Providers:** Google Places API, HERE EV Charge Points API, TomTom EV Charging Stations API, MapmyIndia (Mappls) EV API.
- **Reality:** While technically sophisticated and rich in Mumbai POI coverage, standard developer commercial terms **strictly forbid permanent database caching, local historical storage, derivative ML training, or redisplay without their proprietary basemaps**.
- **Architectural Decision:** ChargePlus cannot build its canonical OLTP/OLAP warehouse on data sources that prohibit persistent local storage. Commercial APIs may only be evaluated if dedicated enterprise data-resale agreements are executed.

### 3.7 Tier 5: Reverse-Engineered CPO Mobile Apps — STRICTLY PROHIBITED
- **Policy:** Intercepting internal network calls from CPO mobile applications (e.g. Tata Power EZ Charge, Jio-bp pulse, Statiq, Zeon, Kazam) using proxy tools or reverse-engineering private mobile APIs is **strictly prohibited**.
- **Rationale:**
  1. Violates the Computer Fraud and Abuse Act (CFAA), Indian Information Technology Act 2000 (Section 43/66), and CPO terms of service.
  2. Highly fragile: private mobile endpoints change authentication headers, hashing salts, and schemas without notice.
  3. Reputational and legal hazard that invalidates institutional credibility.

---

## 4. Rigorous Real-Time Telemetry Definition

In marketing contexts, "real-time" is frequently misused to imply magical, instantaneous omniscience. In ChargePlus engineering, we establish an uncompromising operational definition:

> **ChargePlus Real-Time Definition:**  
> A real-time availability status represents an authoritative, point-in-time observation received from a legitimate data producer, captured with explicit timestamps, freshness bounds, and source provenance. It reflects what was legitimately observed at time $t$ — never an invented or extrapolated truth.

### The Three Telemetry Acquisition Mechanisms

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ MECHANISM A: LIVE SOURCE PUSH (Webhook / OCPI EVSE Status Event)                │
│ Origin: Authoritative CPO backend / Roaming Gateway                              │
│ Flow:   CPO EVSE sensor $\to$ CPO Cloud $\to$ HTTPS POST / Webhook $\to$ ChargePlus Ingestion  │
│ Latency: Bounded by network transport (< 5 seconds to 1 minute)                  │
│ Quality: Highest authority (Direct hardware telemetry)                           │
└──────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────┐
│ MECHANISM B: LIVE SOURCE POLLING (Periodic Scheduled REST Fetch)                 │
│ Origin: External API supporting dynamic status (e.g. OpenChargeMap modifiedsince)│
│ Flow:   Scheduled Worker $\to$ GET /status $\to$ Change Detection $\to$ Normalized Observation │
│ Latency: Bounded by polling interval (e.g. 2 min, 5 min, 15 min) + API cache TTL   │
│ Quality: High, but quantized by polling cadence and rate limits                  │
└──────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────┐
│ MECHANISM C: FIRST-PARTY USER OBSERVATIONS (Community Reports & Check-ins)       │
│ Origin: Authenticated ChargePlus EV Driver on-site                               │
│ Flow:   Driver App $\to$ POST /user_reports $\to$ Moderation / Trust Engine $\to$ Observation  │
│ Latency: Asynchronous, event-driven (Driver arrives at physical station)         │
│ Quality: Contextually rich (e.g. ICE-ing, broken plug, queue depth), subject to   │
│          user reputation weighting (analytics.fact_user_report)                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Concrete Telemetry Progression Example

Consider a fast-charging hub in Bandra-Kurla Complex (BKC), Mumbai, equipped with 6 CCS2 connectors:

- **14:00:00 UTC:** Polling run or webhook receives status: **4 of 6 connectors Available**.
  - `OperationalStatus`: `OPERATIONAL`
  - Observation emitted: `available_connectors = 4`, `total_connectors = 6`, `observed_at = 14:00:00`.
- **14:03:15 UTC:** Two vehicles plug in. CPO telemetry transmits an event: **2 of 6 connectors Available**.
  - Historical observation recorded in `analytics.fact_station_observation`.
  - Current-state view `public.v_station_current_state` updates to reflect 2 available.
- **14:05:40 UTC:** Two more vehicles plug in. Telemetry update: **0 of 6 connectors Available (All Occupied)**.
  - New observation recorded: `available_connectors = 0`.
  - Station operational status remains `OPERATIONAL` (chargers are functioning, but bays are occupied).
- **14:08:00 UTC:** A ChargePlus user arrives, observes a queue of 3 vehicles waiting, and submits a community report via Mechanism C:
  - User report recorded in `public.user_reports` and `analytics.fact_user_report`.
  - Queue metric recorded: `queue_level = 'medium'`, `estimated_wait_minutes = 25`.
- **14:20:00 UTC:** Network connection to the external CPO endpoint times out.
  - **CRITICAL ANTI-PATTERN PREVENTED:** ChargePlus **does NOT** mark the station as "Unavailable" or "Broken".
  - The latest observation (0/6 available at 14:05:40) remains recorded.
  - Freshness status transitions from `LIVE` (0-5m) $\to$ `AGING` (5-15m) $\to$ `STALE` (>15m).
  - The UI accurately informs the driver: *"Last observed occupied 15 minutes ago (Telemetry feed currently offline)"*.

---

## 5. Physical Entity Lifecycle vs. Time-Series Observation

A cardinal architectural failure in primitive EV apps is conflating physical infrastructure changes with operational state transitions. ChargePlus strictly enforces their conceptual separation:

```
┌────────────────────────────────────────────────────────┐
│ PHYSICAL ENTITY STATE (Infrequent / Structural)        │
│ Examples:                                              │
│ - Station constructed, commissioned, or decommissioned │
│ - Physical connector hardware replaced (e.g. 50kW $\to$ 120kW)│
│ - Operator or site host contract changed               │
│ - Address, coordinates, or parking access updated     │
│ Persistence Target: public.stations, public.connectors  │
│ Frequency: Months to years                             │
└────────────────────────────────────────────────────────┘
                           │
                           │ 1-to-Many
                           ▼
┌────────────────────────────────────────────────────────┐
│ TIME-SERIES OBSERVATION STATE (Dynamic / Ephemeral)    │
│ Examples:                                              │
│ - Connector plugged in / occupied                      │
│ - Connector fault / emergency stop pressed             │
│ - Bay blocked by non-EV (ICE-ed)                       │
│ - Physical queue formed outside charging bay           │
│ - Fluctuating dynamic energy tariff                    │
│ Persistence Target: public.station_observations,       │
│                     analytics.fact_station_observation │
│ Frequency: Seconds to minutes                          │
└────────────────────────────────────────────────────────┘
```

### Core Invariants
1. **Station UUID Stability:** An availability change **NEVER** creates a new station UUID or modifies `public.stations.id`.
2. **Non-Destructive Observation Logging:** An observation change **NEVER** overwrites historical observations. Every observed state is appended to the operational log and warehouse fact table.
3. **Decommissioning $\neq$ Deletion:** When a station closes permanently, its `operational_status` is updated to `permanently_closed`. The entity and its historical observation trail remain preserved for analytical integrity.

---

## 6. Freshness Semantics: "Stale ≠ Unavailable"

A fundamental tenet of data quality in ChargePlus is the distinction between system knowledge and physical reality:

$$\text{Staleness} = f(\text{Current Time} - \text{Observation Time})$$
$$\text{Physical Availability} \in \{\text{Available}, \text{Busy}, \text{Broken}, \text{Unknown}\}$$

- **Staleness is a property of our observation freshness**, governed by provider-specific Service Level Agreements (SLAs) and polling frequencies.
- **Physical Availability is a property of the charging hardware**.
- **The Rule:** If an observation is 30 minutes old because of an API network glitch, ChargePlus must report:
  - Last known state: `busy` (at 14:05 UTC)
  - Freshness: `stale` (30 minutes ago)
  - **FORBIDDEN:** Flipping the status to `broken` or `unavailable` merely because data is stale.
  - **FORBIDDEN:** Flipping the status to `available` on the naive assumption that the vehicle must have left.

---

## 7. Message Broker & Streaming Decision: Kafka is NOT Required

### The Decision: **NO KAFKA NOW**
Apache Kafka, Redis Streams, RabbitMQ, and MQTT are **strictly excluded** from the current Phase 2 architecture.

### Architectural Rationale
1. **Source Reality:** None of our Tier 1 or Tier 2 sources provide a sustained high-throughput distributed event stream. OpenChargeMap is a polled REST API with rate limits; OpenStreetMap provides periodic static XML/PBF snapshots; government datasets are batch files.
2. **Operational Overhead:** Deploying and maintaining a ZooKeeper/KRaft cluster, schema registries, partition rebalancing, and consumer offset stores introduces immense operational complexity with zero functional benefit at pilot scale.
3. **Current Throughput:** For the Mumbai pilot (~500 to 2,000 public charging points), polling cycles of 5 to 15 minutes generate an aggregate ingestion load of less than 10 requests per second. PostgreSQL, backed by indexed connection pools and Python batch workers, handles this load effortlessly with sub-millisecond write latencies.

### Future Re-evaluation Criteria (When Kafka Genuinely Becomes Justified)
A streaming broker will only be considered if all of the following conditions are simultaneously met:
- ChargePlus secures live OCPI webhook feeds from 5+ major CPOs generating $\ge 500$ continuous events/second.
- Multiple independent, decoupled backend microservices require pub/sub event fan-out (e.g. Real-time Notification Engine, Dynamic Pricing Engine, ML Streaming Inference, Fraud Detection).
- True streaming replay and backpressure buffering are required due to downstream database write saturation.

Until those conditions are physically present, ingestion is driven by deterministic Python batch and polling workers.

---

## 8. Two-Tiered Duplicate Prevention Architecture

Deduplication in ChargePlus addresses two fundamentally distinct problems requiring independent solutions:

```
┌────────────────────────────────────────────────────────────────────────┐
│ PROBLEM 1: INGESTION IDEMPOTENCY (Same Source Record Ingested Repeatedly)│
├────────────────────────────────────────────────────────────────────────┤
│ Scenario: Polling runs every 10 minutes against OpenChargeMap.          │
│ Mechanism: Source Identity + Raw Payload Cryptographic Hashing          │
│            - Natural Source Key: (source_id, source_station_id)        │
│            - Payload Fingerprint: SHA-256(canonical_json(raw_payload))  │
│ Outcome:   If payload_hash matches existing raw record:                 │
│            $\to$ Update last_seen_at timestamp                          │
│            $\to$ Skip redundant downstream normalization and entity matching │
│ Phase:     Enforced in Step 2.1 & Step 2.2                             │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│ PROBLEM 2: CROSS-SOURCE ENTITY RESOLUTION (Different Sources, Same Site) │
├────────────────────────────────────────────────────────────────────────┤
│ Scenario: OCM ID 192840 and OSM Node 8839201 both represent the        │
│           Tata Power BKC Fast Charging Hub at the exact same location. │
│ Mechanism: Multi-Signal Evidence Fusion                                │
│            - Geodetic Distance: PostGIS ST_DWithin $\le 50$ meters       │
│            - Normalized Name Similarity: Levenshtein / Jaro-Winkler     │
│            - Operator Identity: Normalized operator_slug match         │
│            - Connector Signature: Set compatibility of plug types/power │
│            - Postal Code & Street Address Token Overlap                │
│ Outcome:   Link both source records to one canonical public.stations.id │
│            via public.station_source_link                              │
│ Phase:     Reserved for Step 2.4 & Step 2.7                            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Canonical Identity Independence

A cornerstone invariant of the ChargePlus database:

$$\text{Canonical Station UUID} \neq \text{External Source ID}$$

- `public.stations.id` is an immutable `UUIDv4` generated internally by ChargePlus.
- External IDs (`OCM-192840`, `OSM-node-8839201`, `BEE-MH-0042`) are strictly stored in provenance fields and mapped via `public.station_source_link`.
- If an external source changes its internal IDs or is deprecated, ChargePlus's physical station graph, user favorites, reviews, and historical telemetry remain completely stable.

---

## 10. First-Class Provenance & Licensing-Aware Ingestion

### Cryptographic Provenance Tracking
Every record flowing through the pipeline is bundled with an immutable `ProvenanceInfo` descriptor:
- `source_id`: Slug identifying the provider (e.g. `'open_charge_map'`, `'osm'`).
- `source_station_id`: Primary identifier within the source system.
- `raw_payload_hash`: SHA-256 digest of pristine source JSON.
- `retrieval_timestamp`: Exact UTC time when data crossed the network boundary.
- `source_timestamp`: Explicit timestamp reported by external source if available.
- `contract_version`: Locked canonical schema version (`"1.0.0"`).

### Multi-License Awareness
External sources are not monolithic. OpenChargeMap contains both original crowdsourced contributions (CC BY-SA 4.0) and imported third-party datasets (with contributor-specific licenses). OpenStreetMap is strictly ODbL 1.0.
The ChargePlus ingestion pipeline preserves `data_provider_id`, `license_type`, and `attribution_url` per source link, ensuring downstream user interfaces and API endpoints can render compliant legal attributions dynamically.

---

## 11. Canonical Future Source Acquisition Sequence

The planned sequence of source integration across Phase 2:

1. **Step 2.1 — Canonical Input Contract:** COMPLETE & LOCKED.
2. **Step 2.2 — Source Adapter Architecture & OCM Adapter:** COMPLETE & LOCKED.
3. **Step 2.3 — Connect First Live Data Source (OpenChargeMap Live Feed):**
   - Configure live API client with `OPENCHARGEMAP_API_KEY`.
   - Implement rate-limiting, exponential backoff, and Mumbai bounding-box query parameters.
   - Execute controlled, non-destructive test fetch.
4. **Step 2.4 — Raw Payload Storage & Change Detection:**
   - Establish raw payload audit staging table/store.
   - Enforce SHA-256 change detection and idempotency.
5. **Step 2.5 — OpenStreetMap (OSM) Adapter:**
   - Implement Overpass QL parser for `amenity=charging_station`.
   - Normalize OSM tag topologies to Step 2.1 contract.
6. **Step 2.6 — Data Quality Validation Pipeline:**
   - Operationalize `DataQualityValidator` in ingestion pipeline.
7. **Step 2.7 — Cross-Source Entity Matching & Deduplication:**
   - Deploy spatial and fuzzy-matching engine to populate `public.station_source_link`.
8. **Step 2.8 — Canonical Database Loading:**
   - Initial population of `public.stations` and `public.connectors`.
9. **Step 2.9 — Provenance & Freshness Engine:**
   - Active tracking of `last_observed_at`, `last_verified_at`, and data decay rates.
10. **Step 2.10 — Scheduled Ingestion Workflows:**
    - Background polling daemons and cron triggers.
11. **Step 2.11 — Mumbai Pilot Verification & Sign-off:**
    - Comprehensive spatial audit of Mumbai operational coverage.

---

## 12. Step 2.2 Closure — Architecture Locked

With the completion of this research and reconciliation pass, the architectural boundaries of Step 2.2 are formally locked:

- **No Kafka now:** Simple, deterministic Python workers and PostgreSQL storage.
- **No fake real-time:** Telemetry is only produced when authoritative automated status exists.
- **OCM & OSM are initial external sources:** Tier 1 open datasets for Mumbai pilot foundation.
- **Live status is source-dependent:** Distinct paths for push, polling, and community observations.
- **Observation history is required:** Point-in-time states feed `analytics.fact_station_observation`.
- **Source IDs $\neq$ Canonical IDs:** External keys are mapped via provenance links.
- **Entity resolution is deferred:** Multi-source merging belongs strictly to Step 2.4 / Step 2.7.
- **Zero Supabase writes in Step 2.2:** Operational and warehouse tables remain pristine.
- **Next Step:** Proceed to **Phase 2, Step 2.3** ("Connect first legitimate station data source").
