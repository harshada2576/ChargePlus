# ChargePlus — Step 2.6 Documentation
## Ingestion-Wide Data Quality Validation & Anomaly Quarantine

**Phase:** 2/6 (Real Data Ingestion & Data Quality)  
**Step:** 2.6  
**Status:** COMPLETE / LOCKED  
**Module:** [`backend/ingestion/validation.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/validation.py)  
**Test Suite:** [`tests/test_data_quality_validation.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/tests/test_data_quality_validation.py) (40 tests passing, 137 total suite passing)

---

### 1. Executive Summary & Purpose

The purpose of **Step 2.6** is to operationalize and strengthen the ChargePlus data-quality layer so that normalized station records from legitimate external sources are evaluated consistently before downstream canonical merging and persistence.

The validator assesses incoming [`NormalizedStationRecord`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/contracts.py) instances against contract specifications, physical plausibility bounds, and operational semantics to classify each record into one of four deterministic outcomes:
1. **`ACCEPT`**: Fully compliant, production ready.
2. **`ACCEPT_WITH_WARNINGS`**: Compliant for operational persistence, but possesses non-blocking quality limitations.
3. **`QUARANTINE`**: Plausible physical record containing a serious anomaly or boundary conflict requiring human review before downstream canonical promotion.
4. **`REJECT`**: Fatal, non-negotiable defect (unusable, corrupt, missing coordinates or source identity).

---

### 2. Architectural Boundaries (Steps 2.4 through 2.8)

```text
┌────────────────────────────────────────────────────────────────────────┐
│ STEP 2.4: Cross-Source Entity Resolution                               │
│ "Could these source records represent the same physical station?"      │
│ Candidate generation (<= 50m radius) & multi-signal evidence fusion.   │
├────────────────────────────────────────────────────────────────────────┤
│ STEP 2.5: Cross-Source Field Normalization                             │
│ "Are equivalent fields represented consistently enough to process?"    │
│ Standard vocabulary, unit conversions, explicit alias resolution.      │
├────────────────────────────────────────────────────────────────────────┤
│ STEP 2.6: Ingestion Data Quality Validation & Quarantine (CURRENT)     │
│ "Does the record satisfy data-quality and physical plausibility rules?"│
│ Transparent findings, anomaly quarantine ledger, batch quality metrics.│
├────────────────────────────────────────────────────────────────────────┤
│ STEP 2.7: Canonical Decision Layer & Precedence Survivorship (NEXT)    │
│ "Which records become one canonical station, and which values survive?"│
│ Authority arbitration, attribute survivorship, deduplication execution.│
├────────────────────────────────────────────────────────────────────────┤
│ STEP 2.8: Canonical Operational Persistence & Warehouse Loading        │
│ "Safely persist canonical master records and dimensional data."        │
└────────────────────────────────────────────────────────────────────────┘
```

#### Strict Non-Goals for Step 2.6:
- **No Merging or Deduplication:** Step 2.6 does not merge stations or resolve duplicate entities.
- **No Canonical UUID Assignment:** External records retain source identifiers; canonical station UUID assignment belongs to Step 2.7/2.8.
- **No Source Precedence Arbitration:** Step 2.6 does not choose whether Source A or Source B is more authoritative.
- **No Operational State Mutation:** Step 2.6 validates; it does not mutate database tables or canonical operational state.
- **No Silent Repair:** Bad data is never silently corrected, coerced into zero, or defaulted.

---

### 3. Core Architectural Invariants

1. **No Silent Repair:**
   - Negative power (`-50 kW`) is flagged as invalid, never coerced to `+50 kW`.
   - Missing connector quantity is never defaulted to `1` plug.
   - Missing price is preserved as `None` / `UNKNOWN`, never defaulted to ₹0 or Free.
   - Missing operating hours are never assumed to be 24/7 or closed.
   - Malformed Indian PINs are flagged, never truncated or guessed.

2. **Decoupling of Operational Semantics:**
   - **Station Operational Status:** Station hardware state (`operational`, `temporarily_unavailable`, `permanently_closed`).
   - **Real-Time Connector Availability:** Point-in-time occupancy telemetry (`available`, `busy`, `broken`).
   - A station being `OPERATIONAL` does **not** prove `available_now = True`.
   - A stale observation (> 24 hours old) does **not** prove a station is `BROKEN` or `UNAVAILABLE`.

3. **Pure & Deterministic Functionality:**
   - Zero network requests, zero LLMs, zero random numbers.
   - Validation output is bitwise identical for identical inputs:
     $$\text{validate}(r, t) \equiv \text{validate}(r, t)$$

4. **In-Memory Anomaly Quarantine:**
   - Quarantined records do not enter canonical operational persistence (`public.stations`, `public.connectors`).
   - Quarantined records preserve complete Layer 1 raw provenance, all failed rule identifiers, and human-readable diagnostic messages.

---

### 4. Severity & Outcome Decision Matrix

The validator uses a four-level severity hierarchy mapped deterministically to the contract outcome:

```
[QualitySeverity]
  ├── INFO      ──> Non-blocking informational notice (e.g. unbranded operator, coordinate-only location)
  ├── WARNING   ──> Non-blocking quality limitation or commercial anomaly (e.g. power > 500kW, stale telemetry)
  ├── HIGH      ──> Serious physical anomaly or cross-field conflict (e.g. power > 2000kW, geofence mismatch)
  └── CRITICAL  ──> Fatal defect preventing safe interpretation (e.g. power <= 0, lat > 90, missing source_id)
```

| Highest Severity Finding | Contract Outcome | Is Valid? | Enters Operational DB? | Action / Destination |
| :--- | :--- | :---: | :---: | :--- |
| **None** | `ACCEPT` | `True` | Yes | Direct canonical ingestion pipeline |
| **INFO / WARNING** | `ACCEPT_WITH_WARNINGS` | `True` | Yes | Persisted with quality findings attached |
| **HIGH** | `QUARANTINE` | `False` | **No** | In-memory quarantine ledger for operator review |
| **CRITICAL** | `REJECT` | `False` | **No** | Immediate rejection; rejected ledger |

---

### 5. Stable Rule Catalog

Every rule is assigned an immutable, structured identifier following the format `DQ-<DOMAIN>-<NUMBER>`:

| Rule ID | Category | Severity | Target Field | Failure Condition | Outcome Impact |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`DQ-PROV-001`** | `PROVENANCE` | `CRITICAL` | `source_id` | Missing or blank source identity | `REJECT` |
| **`DQ-PROV-002`** | `PROVENANCE` | `CRITICAL` | `source_station_id` | Missing or blank source record identity | `REJECT` |
| **`DQ-PROV-003`** | `SCHEMA` | `CRITICAL` | `contract_version` | Incompatible contract version (not 1.x.x) | `REJECT` |
| **`DQ-PROV-004`** | `PROVENANCE` | `WARNING` | `raw_payload_hash` | Non-64 character hexadecimal SHA-256 digest | `ACCEPT_WITH_WARNINGS` |
| **`DQ-NAME-001`** | `COMPLETENESS` | `CRITICAL` | `name` | Station name missing or length < 2 | `REJECT` |
| **`DQ-NAME-002`** | `FORMAT` | `WARNING` | `name` | Test/demo placeholder name ("Test", "Demo Station") | `ACCEPT_WITH_WARNINGS` |
| **`DQ-OP-001`** | `COMPLETENESS` | `INFO` | `operator_name` | Missing operator identity (unbranded station) | Informational |
| **`DQ-GEO-001`** | `GEOGRAPHY` | `CRITICAL` | `latitude` | Latitude outside physical range `[-90.0, 90.0]` | `REJECT` |
| **`DQ-GEO-002`** | `GEOGRAPHY` | `CRITICAL` | `longitude` | Longitude outside physical range `[-180.0, 180.0]` | `REJECT` |
| **`DQ-GEO-003`** | `GEOGRAPHY` | `CRITICAL` | `coordinates` | Coordinate pair `(0.0, 0.0)` Null Island sentinel | `REJECT` |
| **`DQ-GEO-004`** | `GEOGRAPHY` | `HIGH` | `coordinates` | Country is India but coordinates outside India bounding box | `QUARANTINE` |
| **`DQ-GEO-005`** | `GEOGRAPHY` | `WARNING` | `coordinates` | City is Mumbai/MMR but coordinates outside MMR bounding box | `ACCEPT_WITH_WARNINGS` |
| **`DQ-ADDR-001`** | `COMPLETENESS` | `INFO` | `address_line` | Both street address and locality missing | Informational |
| **`DQ-ADDR-002`** | `FORMAT` | `WARNING` | `postal_code` | Indian postal code does not match `^[1-9][0-9]{5}$` | `ACCEPT_WITH_WARNINGS` |
| **`DQ-HOURS-001`** | `CONSISTENCY` | `WARNING` | `is_24_hours` | Marked 24/7, but opening/closing times also defined | `ACCEPT_WITH_WARNINGS` |
| **`DQ-HOURS-002`** | `FORMAT` | `CRITICAL` | `opening_time` / `closing_time` | Invalid time representation (e.g. "27:00", "9:00") | `REJECT` |
| **`DQ-HOURS-003`** | `HOURS` | `HIGH` | `is_24_hours` | Marked 24/7, but metadata or operational status is closed | `QUARANTINE` |
| **`DQ-CONN-001`** | `CONNECTOR` | `INFO` | `connectors` | Station has 0 connectors reported (shell station) | Informational |
| **`DQ-CONN-002`** | `CONNECTOR` | `CRITICAL` | `quantity` | Connector quantity < 1 | `REJECT` |
| **`DQ-CONN-003`** | `CONNECTOR` | `WARNING` | `connector_type` | Unmapped connector standard (raw label preserved) | `ACCEPT_WITH_WARNINGS` |
| **`DQ-CONN-004`** | `CONNECTOR` | `WARNING` | `quantity` | Connector quantity unusually high (> 50) | `ACCEPT_WITH_WARNINGS` |
| **`DQ-ELEC-001`** | `ELECTRICAL` | `CRITICAL` | `power_kw` | Rated output power <= 0.0 kW | `REJECT` |
| **`DQ-ELEC-002`** | `ELECTRICAL` | `HIGH` | `power_kw` | Output power > 2000.0 kW (exceeds physical EV limits) | `QUARANTINE` |
| **`DQ-ELEC-003`** | `ELECTRICAL` | `WARNING` | `power_kw` | Output power outside standard commercial range `[1, 500]` kW | `ACCEPT_WITH_WARNINGS` |
| **`DQ-ELEC-004`** | `ELECTRICAL` | `CRITICAL` | `voltage_v` | Voltage <= 0.0 V | `REJECT` |
| **`DQ-ELEC-005`** | `ELECTRICAL` | `WARNING` | `voltage_v` | Voltage > 1000.0 V | `ACCEPT_WITH_WARNINGS` |
| **`DQ-ELEC-006`** | `ELECTRICAL` | `CRITICAL` | `amperage_a` | Current <= 0.0 A | `REJECT` |
| **`DQ-ELEC-007`** | `ELECTRICAL` | `WARNING` | `amperage_a` | Current > 1000.0 A | `ACCEPT_WITH_WARNINGS` |
| **`DQ-ELEC-008`** | `ELECTRICAL` | `WARNING` | `power_kw` | Missing power_kw rating | `ACCEPT_WITH_WARNINGS` |
| **`DQ-PRICE-001`** | `PRICING` | `CRITICAL` | `price_per_kwh` / `price_per_session` | Negative tariff rate or session fee | `REJECT` |
| **`DQ-PRICE-002`** | `PRICING` | `HIGH` | `pricing_type` | Marked FREE charging, but specifies positive tariff rate | `QUARANTINE` |
| **`DQ-PRICE-003`** | `PRICING` | `WARNING` | `pricing` | Missing pricing details (tariff is unknown) | `ACCEPT_WITH_WARNINGS` |
| **`DQ-PRICE-004`** | `FORMAT` | `CRITICAL` / `WARNING` | `currency` | Non-alphabetic currency (CRITICAL) or length > 10 (WARNING) | `REJECT` / `ACCEPT_WITH_WARNINGS` |
| **`DQ-OBS-001`** | `OPERATIONAL` | `CRITICAL` | `observation.observed_at` | Future telemetry timestamp (> 5 min clock skew) | `REJECT` |
| **`DQ-OBS-002`** | `OPERATIONAL` | `WARNING` | `observation.observed_at` | Stale telemetry (> 24 hours old); cannot be real-time | `ACCEPT_WITH_WARNINGS` |
| **`DQ-OBS-003`** | `CONSISTENCY` | `CRITICAL` | `observation.available_connectors` | Available connectors reported > total connectors | `REJECT` |

---

### 6. Domain-Specific Quality Validation Logic

#### A. Geographic Validation (`DQ-GEO-001` to `DQ-GEO-005`)
- **Null Island Sentinel:** Pair `(0.0, 0.0)` is unconditionally rejected.
- **Prime Meridian / Equator:** Individual zero coordinates (e.g. `latitude = 0.0, longitude = 32.0` on the Equator, or `latitude = 51.4769, longitude = 0.0` in Greenwich) are completely valid and accepted.
- **India Geofence:** When country is India, coordinates outside `[6.0, 38.0] N` and `[68.0, 98.0] E` trigger `QUARANTINE` (`DQ-GEO-004`).
- **Pilot Geographic Warning:** Stations tagged with Mumbai/MMR outside `[18.70, 19.50] N` and `[72.70, 73.30] E` receive non-fatal warning `DQ-GEO-005`.

#### B. Physical & Electrical Plausibility (`DQ-ELEC-001` to `DQ-ELEC-008`)
- Non-positive electrical values (`power <= 0 kW`, `voltage <= 0 V`, `amperage <= 0 A`) trigger fatal `REJECT`.
- Values between 500 kW and 2000 kW (e.g., MCS Megawatt charging prototypes) generate warnings (`DQ-ELEC-003`).
- Values exceeding 2000 kW trigger `QUARANTINE` (`DQ-ELEC-002`).

#### C. Operating Hours & Schedule Consistency (`DQ-HOURS-001` to `DQ-HOURS-003`)
- Standard formats (`HH:MM` in 24-hour clock) are validated with `^([01][0-9]|2[0-3]):[0-5][0-9]$`.
- Overnight schedules (e.g., `opening_time = 22:00, closing_time = 06:00`) parse cleanly as valid intervals.
- Missing hours are never defaulted to 24/7.
- Declaring `is_24_hours = True` while having metadata comments "closed all days" or `operational_status = PERMANENTLY_CLOSED` triggers `QUARANTINE` (`DQ-HOURS-003`).

#### D. Pricing Semantics (`DQ-PRICE-001` to `DQ-PRICE-004`)
- Negative prices are rejected.
- Explicit Free pricing (`pricing_type = FREE`) with `price_per_kwh = 0.0` is accepted.
- Contradictory Free pricing (`pricing_type = FREE` with `price_per_kwh > 0.0`) triggers `QUARANTINE`.
- Missing pricing is marked `UNKNOWN` with non-blocking recommendation `DQ-PRICE-003` (never defaulted to ₹0).
- Per-kWh rates and fixed per-session fees are tracked as distinct attributes.

---

### 7. Batch Validation & Aggregated Quality Reporting

The validator provides `validate_batch(records, current_time=None)` which produces a deterministic [`BatchValidationReport`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/validation.py#L167-L204):
- **Total Record Accounting:** Zero records are silently dropped.
  $$\text{total} \equiv \text{accepted} + \text{accepted\_with\_warnings} + \text{quarantined} + \text{rejected}$$
- **Issue Distribution:** Aggregate frequencies indexed by Rule ID and Severity.
- **Field Completeness Rates:** Measured completeness percentages for operator, address, PIN, power, operating hours, and telemetry.
- **Anomaly Rate:** Deterministic fraction of batch requiring quarantine or rejection.

---

### 8. Verification & Test Coverage

All 40 required test scenarios are implemented in [`tests/test_data_quality_validation.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/tests/test_data_quality_validation.py):
1. Fully valid station => `ACCEPT`
2. Missing optional power => `ACCEPT_WITH_WARNINGS` (`DQ-ELEC-008`)
3. Missing optional price => `ACCEPT_WITH_WARNINGS` (`DQ-PRICE-003`)
4. Missing operator => Does not reject (`DQ-OP-001` INFO)
5. Missing connector quantity => Does not invent quantity
6. Invalid latitude outside `[-90, 90]` => `REJECT` (`DQ-GEO-001`)
7. Invalid longitude outside `[-180, 180]` => `REJECT` (`DQ-GEO-002`)
8. Latitude 0 alone => Allowed
9. Longitude 0 alone => Allowed
10. Null Island `(0,0)` => `REJECT` (`DQ-GEO-003`)
11. Negative power => `REJECT` (`DQ-ELEC-001`)
12. Negative voltage => `REJECT` (`DQ-ELEC-004`)
13. Negative amperage => `REJECT` (`DQ-ELEC-006`)
14. Negative connector quantity => `REJECT` (`DQ-CONN-002`)
15. Suspicious power (600 kW) => `ACCEPT_WITH_WARNINGS` (`DQ-ELEC-003`)
16. Unknown connector standard => `ACCEPT_WITH_WARNINGS` (`DQ-CONN-003`)
17. Explicit FREE pricing + zero amount => `ACCEPT`
18. Missing pricing => UNKNOWN, not free
19. Negative price => `REJECT` (`DQ-PRICE-001`)
20. Invalid non-alphabetic currency => `REJECT` (`DQ-PRICE-004`)
21. Per-kWh and per-session tariff bases remain distinct
22. Valid normal operating hours (09:00 - 21:00) => `ACCEPT`
23. Valid overnight operating hours (22:00 - 06:00) => `ACCEPT`
24. Invalid time format ("27:00") => `REJECT` (`DQ-HOURS-002`)
25. Missing operating hours => Allowed, not rejected
26. Canonical 24/7 representation => `ACCEPT`
27. Contradictory 24/7 schedule => `QUARANTINE` (`DQ-HOURS-003`)
28. Provenance missing `source_id` => `REJECT` (`DQ-PROV-001`)
29. Provenance missing `source_station_id` => `REJECT` (`DQ-PROV-002`)
30. Operational status decoupled from live availability
31. Stale observation (>24h) decoupled from broken/unavailable
32. Batch report counts every input record without omission
33. Batch report issue frequencies are strictly deterministic
34. Multi-defect records retain all distinct findings
35. Quarantine retains complete provenance, reasons, and findings
36. Quarantined records do not enter operational persistence
37. Input records are never mutated by validation
38. Validator output is bitwise deterministic
39. Extreme power (>2000 kW) triggers `QUARANTINE` (`DQ-ELEC-002`)
40. Contradictory Free pricing triggers `QUARANTINE` (`DQ-PRICE-002`)
