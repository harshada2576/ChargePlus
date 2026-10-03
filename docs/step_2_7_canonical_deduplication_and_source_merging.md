# ChargePlus Phase 2 / Step 2.7 — Canonical Deduplication Decision Layer & Source Merging

## 1. Executive Summary & Purpose

Step 2.7 establishes the **deterministic canonical deduplication and field-level survivorship decision engine** for ChargePlus.

### Foundational Distinction Across Phase 2
- **Step 2.4 (Cross-Source Entity Resolution)** asked: *"Does this pair of source records appear to refer to the same physical station?"* (Pairwise candidate matching).
- **Step 2.5 (Field Normalization)** asked: *"How do we represent its attributes in consistent ChargePlus vocabulary?"* (Data standardization).
- **Step 2.6 (Data Quality Validation)** asked: *"Is this record structurally and semantically trustworthy enough to proceed?"* (Quality grading & anomaly quarantine).
- **Step 2.7 (Canonical Deduplication Decision Layer)** asks: *"Given all of that evidence, what should ChargePlus consider the canonical identity, and which source evidence should contribute to it?"* (Multi-source cluster arbitration & survivorship).
- **Step 2.8 (Canonical Operational Persistence)** will ask: *"How do we persist that validated decision into operational database tables (`public.stations`, `public.connectors`, `public.station_source_link`)?"*

> **Critical Architectural Boundary:**
> **Step 2.7 decides canonical identity and survivorship; Step 2.8 persists the decision.**
>
> Step 2.7 is strictly non-destructive. It performs zero database writes, issues zero DDL/DML migrations, does not mutate operational or analytics tables, and operates entirely in memory as a pure, auditable decision engine.

---

## 2. Core Invariants & Architectural Rules

1. **One Physical Station = One ChargePlus Canonical ID**
   - External provider identifiers (`ocm_12345`, `osm_98765`, `cpo_555`) remain source identifiers. They are never used as ChargePlus canonical UUIDs.
   - Independent sources describing the same physical station are unified into a single canonical station representation.
2. **2.7 Decides. 2.8 Persists**
   - Step 2.7 evaluates evidence and outputs `CanonicalResolutionDecision` dossiers. It does not insert or update database records.
3. **Source Identity Remains Traceable**
   - Provenance is never collapsed into an opaque object. Every decision preserves participating source identities, raw source fields, and resolution evidence.
4. **Never Invent Source Precedence**
   - Arbitrary hierarchies like `"CPO > OCM > OSM"` or `"last-write-wins"` are strictly forbidden. Where no explicit, justified policy exists, field contradictions trigger `REVIEW`.
5. **Missing $\neq$ Conflict**
   - Omission in one source does not contradict a valid value in another. (e.g. Source A reports operator, Source B reports `None` $\to$ non-conflict).
6. **Connectors Are Never Blindly Summed**
   - Multiple sources reporting identical connectors (e.g. 2x CCS2 60kW) are deduplicated. Differing quantities take `max(quantity)` rather than additive summation ($2 + 2 \neq 4$).
7. **Validation Gating**
   - `REJECT` records are strictly barred from participating in canonical clusters and are isolated as blocked.
   - `QUARANTINE` records cannot silently become canonical; any cluster containing quarantined data is routed to `REVIEW` with `is_blocked = True`.
   - `ACCEPT_WITH_WARNINGS` records may merge when identity evidence is conclusive.
   - `ACCEPT` records merge cleanly.
8. **Transitive Contradiction Protection**
   - Pairwise matches ($A \leftrightarrow B$ and $B \leftrightarrow C$) do **not** automatically prove $A \leftrightarrow C$. Multi-source clusters are evaluated for mutual concordance; contradictions force `REVIEW`.
9. **Determinism & Idempotence**
   - Zero `datetime.now()` execution drift in decision IDs.
   - Inputs are sorted deterministically by `(source_id, source_station_id)`.
   - Running the engine multiple times on identical or permuted inputs produces identical outputs.

---

## 3. Decision States & Models

### Decision States (`CanonicalDecisionState`)
| State | Definition | Operational Meaning |
| :--- | :--- | :--- |
| `MERGE` | Multi-source new cluster unified into a canonical candidate | Multiple new source records refer to the same physical station with strong multi-signal agreement and no contradictions. |
| `LINK_TO_CANONICAL` | Record(s) resolve to an already-established canonical station | One or more source records match an existing canonical station UUID in the database. |
| `KEEP_SEPARATE` | Record represents a distinct, standalone physical station | Evidence shows an independent physical station; no matches to existing canonical stations or other incoming records. |
| `REVIEW` | Ambiguity, contradiction, or multi-canonical bridge | Unresolvable field contradictions, ambiguous entity resolution, quarantine records, or conflicting existing canonical stations requiring human review. |

### Survivorship Strategies (`SurvivorshipStrategy`)
| Strategy | Description |
| :--- | :--- |
| `UNANIMOUS_AGREEMENT` | All reporting sources agree exactly on the value. |
| `SINGLE_REPORTING_SOURCE` | Field reported by only one source; missing values in other sources are non-conflicting. |
| `HIGHEST_QUALITY_SCORE` | Value deterministically selected from source with highest data-quality score (with stable lexicographical tiebreaker). |
| `MOST_COMPLETE_VALUE` | Most descriptive/informative string representation selected (e.g. longest clean station name). |
| `EXPLICIT_FIELD_POLICY` | Domain policy applied (e.g. explicit free pricing preserved; operator change resolved to latest timestamp). |
| `DEDUPLICATED_SET` | Structured deduplication without double counting (e.g. connector specifications). |
| `CONFLICT_UNRESOLVED` | Material contradiction with no justified precedence policy; routes cluster to `REVIEW`. |

---

## 4. Multi-Source Cluster Resolution & Transitive Protection

Pairwise entity resolution from Step 2.4 operates on pairs $(A, B)$. However, real-world data ingestion frequently involves three or more sources:
- Source A (OpenChargeMap)
- Source B (OpenStreetMap)
- Source C (Direct CPO feed)

### The Transitive False Merge Hazard
Consider the scenario:
- Record $A$ is 25 meters west of Record $B$ ($A \leftrightarrow B$ evaluates to `MATCH`).
- Record $B$ is 30 meters west of Record $C$ ($B \leftrightarrow C$ evaluates to `MATCH`).
- However, Record $A$ and Record $C$ are 55 meters apart ($> 50$m candidate radius), representing geographically distinct physical locations or different entrances.
- Naive connected components would group $\{A, B, C\}$ into a single station, causing a transitive false merge.

### ChargePlus Concordance Verification
`CanonicalDeduplicationEngine` enforces strict **cluster concordance verification**:
1. Connected components builds candidate groupings based on `MATCH` or `AMBIGUOUS` links.
2. For every proposed cluster of size $\ge 2$, **all** pairs $(i, j)$ in the cluster are verified:
   - If any pair has `MatchState.AMBIGUOUS`: Flagged as ambiguous identity $\to$ `REVIEW`.
   - If any pair has `MatchState.NON_MATCH` or distance $> 50$m: Flagged as transitive contradiction $\to$ `REVIEW`.
3. Automated merging proceeds to `MERGE` **only** when all internal pairs demonstrate mutual positive concordance.

---

## 5. Field-Level Survivorship Engine

Canonicalization operates attribute-by-attribute rather than "picking one winner source record":

### 1. Coordinates (`resolve_coordinates`)
- **Identical ($\le 1$mm spread)**: Retained with `UNANIMOUS_AGREEMENT`.
- **Close Proximity ($\le 50$m spread)**: Selected from the record with the highest data-quality score (with stable lexicographical tiebreaker on `source_id:source_station_id`). Coordinates are **never averaged** into a synthetic midpoint.
- **Material Conflict ($> 50$m spread)**: Coordinates marked `CONFLICT_UNRESOLVED`, routing cluster to `REVIEW`.

### 2. Station Display Name (`resolve_name`)
- If identical across sources $\to$ `UNANIMOUS_AGREEMENT`.
- If differing $\to$ `MOST_COMPLETE_VALUE` selects the most descriptive name (longest informative name with quality score tiebreaker).

### 3. Operator Identity (`resolve_operator`)
- If missing in all sources $\to$ operator remains unknown.
- If single reporting source $\to$ `SINGLE_REPORTING_SOURCE` (missing $\neq$ conflict).
- If sources share normalized slug (e.g. "Tata Power" vs "Tata Power EZ Charge" $\to$ `tata-power`) $\to$ `UNANIMOUS_AGREEMENT` with the most descriptive display name.
- If operator changed over time (rebrand/takeover) and temporal recency metadata is present $\to$ `EXPLICIT_FIELD_POLICY` selects latest operator while preserving all source records in `participating_values`.
- If conflicting unaliased operators without recency evidence $\to$ `CONFLICT_UNRESOLVED` and `REVIEW`.

### 4. Pricing & Tariffs (`resolve_pricing`)
- If missing across all sources $\to$ preserved as `UNKNOWN` (never fabricated as ₹0).
- If single source reports pricing $\to$ `SINGLE_REPORTING_SOURCE`.
- If explicit FREE reported $\to$ preserved as `FREE` (`EXPLICIT_FIELD_POLICY`).
- If conflicting pricing (FREE vs PAID, or differing paid rates like ₹18 vs ₹24) $\to$ `CONFLICT_UNRESOLVED` and `REVIEW`.

### 5. Connectors (`resolve_connectors`)
Connector survivorship operates on a principled **Two-Level Reconciliation Model** to avoid both artificial double-counting and inadvertent undercounting:
- **Level 1 — Intra-Source Summation**:
  Within a single source record, multiple distinct connector entries sharing the same specification `(connector_type, round(power_kw))` (e.g. two individually enumerated 120 kW CCS2 plugs with distinct `source_connector_id`s) represent distinct physical plugs observed by that source. Their quantities are **summed** to yield that source's reported capacity for that specification.
- **Level 2 — Cross-Source Reconciliation**:
  Across disparate sources describing the same physical station (e.g. OCM and OSM), multiple sources describe the same physical equipment. To prevent artificial double-counting, the canonical quantity for each specification group is reconciled using:
  $$\text{canonical\_qty}(T, P) = \max_{r \in \text{records}} \text{source\_qty}(r, T, P)$$
  Blind summation across sources is strictly forbidden ($2 \text{ plugs from OCM} + 2 \text{ plugs from OSM} = 2 \text{ plugs in reality}$, not 4).
- **Multi-Tier Co-existence**:
  Charging hubs often co-locate chargers with different power ratings (e.g. 1x 60 kW CCS2 and 1x 120 kW CCS2). Distinct power tiers are maintained as distinct capacity groups and are never falsely flagged as conflicts.
- **Incompatible Signatures**:
  Disjoint connector types across sources that each claim to describe the entire site (e.g. one source reports only CHAdeMO and another reports only Type 2), or single-tier stations where sources contradict on power (e.g. 30 kW vs 350 kW), trigger `CONFLICT_UNRESOLVED` and route to `REVIEW`.
- **Connector Identity vs Capacity Group**:
  External `source_connector_id`s are source-specific local keys (e.g. OCM connection ID vs CPO plug ID) and will almost never match across sources. They are preserved in `participating_values` for provenance, while canonical operational connectors represent verified capacity groups matching the database constraint `uq_connectors_station_type_power(station_id, connector_type, power_kw, charging_standard)`.

---

## 6. Existing Canonical Station Reconciliation

`CanonicalDeduplicationEngine` evaluates incoming records against the pool of established canonical stations:
- **Single Canonical Match**: If a record or cluster matches exactly one existing canonical station (via external source link or strict spatial proximity $< 15$m with name concordance) $\to$ `LINK_TO_CANONICAL`.
- **Ambiguous Match**: If a source record matches multiple existing canonical stations $\to$ `REVIEW` (preventing unsafe arbitrary assignment).
- **Cluster Bridges Multiple Canonical Stations**: If an incoming cluster touches two different existing canonical stations $\to$ `REVIEW` (preventing silent consolidation of established stations).

---

## 7. Determinism & Idempotence Guarantees

1. **Deterministic Cluster Hashing**:
   `cluster_id` is computed as:
   $$\text{cluster\_id} = \text{"cluster\_"} + \text{SHA256}(\text{sorted}([\text{source\_id:source\_station\_id}]))[:16]$$
   Zero random numbers or runtime timestamps are used.
2. **Input Order Independence**:
   Input records are sorted deterministically by `(source_id, source_station_id)` prior to cluster formation.
3. **Idempotence**:
   Executing the decision engine repeatedly against the same input dataset yields byte-for-byte identical decision dossiers.

---

## 8. Verification & Test Coverage

Step 2.7 is verified by a dedicated 36-test suite in [`tests/test_canonical_deduplication.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/tests/test_canonical_deduplication.py):
- **Section A: Basic Identity (Tests 1–3)**: Match $\to$ MERGE, separation $\to$ KEEP_SEPARATE, ambiguity $\to$ REVIEW.
- **Section B: Validation Gating (Tests 4–7)**: REJECT blocked, QUARANTINE blocked/review, ACCEPT_WITH_WARNINGS allowed, ACCEPT allowed.
- **Section C: Field Survivorship (Tests 8–12)**: Unanimous agreement, missing $\neq$ conflict, unresolvable conflict $\to$ REVIEW, justified policy, provenance retention.
- **Section D: Coordinates (Tests 13–15)**: Close coordinates safe handling, material conflict ($> 50$m) $\to$ REVIEW, zero synthetic averaging.
- **Section E: Connectors (Tests 16–18)**: Zero double-counting, max quantity reconciliation, incompatible connectors $\to$ REVIEW.
- **Section F: Operators (Tests 19–21)**: Naming variations, operator change/recency, historical provenance retention.
- **Section G: Pricing (Tests 22–24)**: Missing remains unknown, explicit free preserved, conflicting tariffs $\to$ REVIEW.
- **Section H: Multi-Source Clusters (Tests 25–27)**: Concordant cluster formation, transitive contradiction protection, order independence.
- **Section I: Existing Canonical Stations (Tests 28–30)**: Single canonical link, ambiguous multi-canonical $\to$ REVIEW, zero canonical collapse.
- **Section J: Determinism & Idempotence (Tests 31–33)**: Repeated execution, shuffled input order, zero side-effects.
- **Section K: Provenance & Architecture (Tests 34–36)**: Source IDs preserved, canonical ID distinct from external key, auditable reasons retained.

**Test Suite Execution**: 173 total test cases passed across Phase 2 (100% green).
