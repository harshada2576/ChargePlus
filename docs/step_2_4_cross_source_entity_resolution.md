# ChargePlus — Step 2.4 Documentation
## Cross-Source Entity Resolution: Candidate Generation & Evidence Fusion

**Phase:** 2/6 (Real Data Ingestion & Data Quality)  
**Step:** 2.4  
**Status:** COMPLETE / LOCKED  
**Module:** `backend/ingestion/resolution.py`  
**Test Suite:** `tests/test_entity_resolution.py` (15 tests passing)

---

### 1. Purpose

The purpose of Step 2.4 is to discover and evaluate records from different legitimate external sources (e.g., OpenChargeMap, OpenStreetMap, CPO feeds, government registries) that **could refer to the same physical EV charging station**.

Step 2.4 is strictly an **evidence-generation layer**. It constructs an auditable, transparent evidence dossier for candidate pairs, quantifying spatial proximity, lexical station name similarity, organizational operator reconciliation, electrical connector signature compatibility, and geographic locality/PIN overlap.

---

### 2. Architectural Boundaries

To avoid conflating distinct stages in multi-source EV charging ingestion, ChargePlus enforces strict boundaries:

```
[External Sources]
       │
       ▼
[Step 2.2 / 2.3] Source Adapters & Persistence
       │  • Idempotency: source_id + source_station_id + payload_hash
       │  • Persists source observations into operational tables
       ▼
[Step 2.4] Cross-Source Entity Resolution (CURRENT STEP)
       │  • Discovers candidate pairs within <= 50m
       │  • Pure computational evidence fusion across 5 signals
       │  • Produces transparent evidence dossiers: MATCH, NON_MATCH, AMBIGUOUS
       │  • ZERO database mutations, ZERO canonical merging
       ▼
[Step 2.5] Canonical Field Normalization (NEXT)
       │  • Cleans and standardizes raw field strings
       ▼
[Step 2.6] Validation & Quarantine
       │  • Quality gates for candidate payloads
       ▼
[Step 2.7] Deduplication & Precedence Survivorship
       │  • Decides authoritative source precedence
       │  • Resolves AMBIGUOUS candidates with survivorship rules
       ▼
[Step 2.8] Canonical Operational Loading
          • Merges physical entities into public.stations / public.connectors
```

#### Boundary with Step 2.3 (First Live Source Persistence)
- **Step 2.3 Responsibility:** Ingesting verified source records with *source-level idempotency* (same source + same source ID + payload hash never produces duplicate records).
- **Step 2.4 Responsibility:** Comparing *different* source records across providers to discover if they represent the same physical entity.

#### Boundary with Step 2.7 (Canonical Deduplication & Survivorship)
- **Step 2.4 Responsibility:** Computes evidence dossiers and classifies candidate states as `MATCH`, `NON_MATCH`, or `AMBIGUOUS`.
- **Step 2.7 Responsibility:** Takes the evidence dossiers from 2.4, arbitrates authoritativeness and source precedence, applies field survivorship, and executes canonical merges.
- **Strict Invariant:** Step 2.4 **never** merges stations, **never** assigns source IDs as ChargePlus station UUIDs, and **never** discards ambiguous records.

---

### 3. Candidate Generation & Spatial Geometry

1. **Geodetic Coordinate Calculation:**
   - Cartesian distance on decimal degrees ($\Delta x^2 + \Delta y^2$) is invalid for geographic coordinates because lines of longitude converge towards the poles.
   - Step 2.4 uses the exact **Haversine formula** on the WGS 84 mean spherical radius ($R = 6,371,000$ meters) to calculate great-circle physical distance in meters.
   - PostGIS compatibility: Semantics match `ST_Distance(geog_a, geog_b)`.

2. **Candidate Radius ($R \le 50.0$m):**
   - Stations separated by $> 50.0$ meters are immediately classified as `NON_MATCH` with `overall_confidence = 0.0`.
   - Stations separated by $\le 50.0$ meters generate a candidate pair and proceed to multi-signal evidence fusion.

---

### 4. Multi-Signal Evidence Fusion

Step 2.4 enforces that **proximity alone does not prove identity**. Stations sitting 5 meters apart in a dense commercial complex (e.g. Bandra Kurla Complex or Lower Parel) could be distinct operators (e.g. Ather scooter swap cabinet vs Tata Power 60 kW DC car charger).

The resolution engine evaluates five independent signals:

| Signal | Evaluation Methodology | Concordance Values | Weight |
| :--- | :--- | :--- | :--- |
| **1. Geo Proximity** | Haversine distance with linear decay: $1.0 - (d / 50.0)$ | Continuous $[0.0, 1.0]$ | 0.30 |
| **2. Name Similarity** | Blended metric: 35% Token Sort Levenshtein ratio, 35% Jaccard token similarity on stop-word filtered tokens, 30% Szymkiewicz-Simpson overlap coefficient. Expands Mumbai acronyms (e.g. `BKC` $\leftrightarrow$ `Bandra Kurla Complex`). Substring containment bonus ($0.85$). | `AGREE` ($\ge 0.75$), `DISAGREE` ($\le 0.35$), `UNKNOWN` | 0.30 |
| **3. Operator Reconciliation** | Normalized slug comparison (`tata-power`, `jio-bp`). Token overlap on operator components. | `AGREE`, `DISAGREE`, `UNKNOWN` | 0.15 |
| **4. Connector Signature** | Standard connector type intersection (`CCS2`, `Type 2`, `CHAdeMO`). 10% tolerance power rating compatibility. | `AGREE`, `DISAGREE`, `UNKNOWN` | 0.15 |
| **5. Address / PIN Overlap** | Exact 6-digit postal code comparison. Token Jaccard overlap on locality and street address. | `AGREE`, `DISAGREE`, `UNKNOWN` | 0.10 |

---

### 5. Match States & Decision Rules

The evidence engine outputs three discrete states:

#### `MATCH`
Achieved when there is strong positive multi-signal concordance:
- $d \le 25.0$m + high name similarity ($\ge 0.75$) + at least two confirming positive signals + zero contradictory signals.
- **Operator Disagreement Exception (Rule A3):** If physical site identity is overwhelming ($d \le 25$m, high name similarity, identical address/PIN, and identical connector signature), operator divergence does **not** force `NON_MATCH`. This correctly handles commercial takeovers, CPO acquisitions, and network rebranding (e.g., Fortum station rebranded to Jio-bp pulse).

#### `AMBIGUOUS`
Achieved when evidence within the candidate radius ($d \le 50$m) is mixed, partial, or conflicting:
- Two stations 20m apart with differing names and operators.
- Identical coordinates ($0$m) but conflicting metadata (e.g., two distinct tenants in a mall basement).
- Inconclusive records where missing fields prevent positive confirmation.
- **Rule:** Ambiguity is preserved, never discarded or forced.

#### `NON_MATCH`
- Any pair where physical distance exceeds candidate radius ($d > 50.0$m).

---

### 6. Missing Data Semantics

**"Missing != Disagreement"**

External EV registries vary widely in completeness. Missing attributes are never penalized as negative discord:
- Missing operator on Source B $\to$ `OperatorEvidence.signal = UNKNOWN` (neutral weight 0.5), NOT `DISAGREE`.
- Empty connector list on Source B $\to$ `ConnectorEvidence.signal = UNKNOWN`, NOT `DISAGREE`.
- Missing postal code or locality $\to$ `AddressEvidence.signal = UNKNOWN`, `pin_match = None`.
- Missing power rating on a matching connector $\to$ type agreement preserved, `power_compatibility = None`.

---

### 7. Configuration & Thresholds

Centralized and explicit in `EntityResolutionConfig`:
- `candidate_radius_meters = 50.0`
- `high_name_similarity_threshold = 0.75`
- `moderate_name_similarity_threshold = 0.55`
- `low_name_similarity_threshold = 0.35`
- `match_confidence_threshold = 0.70`
- `non_match_confidence_threshold = 0.38`
- Signal weights: `weight_proximity = 0.30`, `weight_name = 0.30`, `weight_operator = 0.15`, `weight_connector = 0.15`, `weight_address = 0.10` (sum = $1.0$).

---

### 8. Determinism & Non-Destructive Guarantees

1. **Determinism:**
   - Pure computational layer.
   - Zero random thresholds.
   - Zero external AI/LLM calls.
   - Zero network requests during evaluation.
   - Deterministic candidate ordering: `-overall_confidence`, `distance_meters`, `source_b`, `source_station_id_b`.
   - Repeated runs on identical inputs yield byte-for-byte identical evidence dossiers.

2. **Non-Destructive Guarantees:**
   - Step 2.4 does **not** mutate `public.stations`.
   - Step 2.4 does **not** mutate `public.connectors`.
   - Step 2.4 does **not** mutate `public.station_source_link`.
   - Step 2.4 does **not** mutate `analytics` fact or dimension tables.
   - Step 2.4 does **not** delete or merge any source records.
   - Input records remain completely immutable (`copy.deepcopy` invariant verified in unit tests).

3. **Source Identity Preservation:**
   - External source identifiers (`source_id`, `source_station_id`) are preserved verbatim in candidate dossiers.
   - ChargePlus canonical UUIDs are never assigned to external records during resolution.

---

### 9. Known Limitations (Addressed in Later Steps)

1. **Source Precedence Arbitrations (Step 2.7):**
   - When Source A reports 60 kW and Source B reports 50 kW on the same physical station, Step 2.4 documents the evidence dossier. Precedence survivorship is formally decided in Step 2.7.
2. **Text Normalization Breadth (Step 2.5):**
   - Step 2.4 incorporates targeted lexical normalization (NFKD unicode normalization, stop-word filtering, Mumbai acronym expansions). Full cross-field standardization belongs to Step 2.5.
3. **Database Candidate Caching:**
   - Step 2.4 is a pure in-memory evaluation engine. If persistent candidate review queues are required in production, an audit review table will be introduced without altering operational identities.
