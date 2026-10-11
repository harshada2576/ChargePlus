# ChargePlus — Step 2.5 Documentation
## Cross-Source Field Normalization & Standard Vocabulary

**Phase:** 2/6 (Real Data Ingestion & Data Quality)  
**Step:** 2.5  
**Status:** COMPLETE / LOCKED  
**Module:** [`backend/ingestion/normalization.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/normalization.py)  
**Test Suite:** [`tests/test_field_normalization.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/tests/test_field_normalization.py) (30 tests passing, 97 total suite passing)

---

### 1. Executive Summary & Purpose

The purpose of **Step 2.5** is to establish a deterministic normalization layer that converts source-specific station, connector, operator, location, electrical, pricing, and operating-hours representations into the standard canonical vocabulary expected by ChargePlus.

Step 2.5 is strictly about **field semantics and representation**.

> *"Are equivalent fields represented consistently enough to compare, validate, and process them downstream?"*

#### Architectural Invariants
1. **Never Fabricate Missing Data:**
   Missing power remains `None` (never 0.0 kW). Missing pricing remains `None` / `UNKNOWN` (never ₹0). Missing operator remains `None` / `UNKNOWN` (never "Unknown" as a fake CPO). Missing PIN remains `None` (never guessed). Missing operating hours remain unstructured/unknown (never assumed 24x7 or closed).
2. **Normalization != Merging:**
   Mapping `"CCS Combo 2"` and `"CCS2"` to the canonical standard connector vocabulary does **not** imply that records represent the same physical station. Normalization does **not** assign station UUIDs and does **not** merge entities.
3. **Normalization != Source Precedence:**
   If Source A reports 150 kW and Source B reports 120 kW for the same physical plug, both values are normalized into comparable float kW numbers. Normalization does **not** pick a winner. Survivorship and source priority arbitration belong exclusively to Step 2.7.
4. **Preserve Raw Source Information:**
   Every normalization operation retains the raw source text, provider metadata, and Layer 1 provenance intact.
5. **Deterministic & Idempotent:**
   Normalization is implemented using pure computational functions without LLMs, random numbers, network requests, or external APIs:
   $$\text{normalize}(x) \equiv \text{normalize}(\text{normalize}(x))$$

---

### 2. Architectural Boundaries (Steps 2.4 through 2.7)

```text
┌────────────────────────────────────────────────────────────────────────┐
│ STEP 2.4: Cross-Source Entity Resolution                               │
│ "Could these source records represent the same physical station?"      │
│ Candidate generation (<= 50m radius) & multi-signal evidence fusion.   │
├────────────────────────────────────────────────────────────────────────┤
│ STEP 2.5: Cross-Source Field Normalization (CURRENT STEP)              │
│ "Are equivalent fields represented consistently enough to process?"    │
│ Standard vocabulary, unit conversions, explicit alias resolution.      │
├────────────────────────────────────────────────────────────────────────┤
│ STEP 2.6: Ingestion Data Quality Validation & Quarantine (NEXT)        │
│ "Does the resulting record satisfy data-quality and boundary rules?"   │
│ Anomaly quarantine, plausibility checks, completeness scoring.         │
├────────────────────────────────────────────────────────────────────────┤
│ STEP 2.7: Canonical Decision Layer & Precedence Survivorship           │
│ "Which records become one canonical station, and which values survive?"│
│ Authority arbitration, attribute survivorship, deduplication execution.│
└────────────────────────────────────────────────────────────────────────┘
```

---

### 3. Normalization Status Semantics

Every normalized field communicates its provenance and lifecycle state via `NormalizationStatus`:

| Status | Definition | Example Scenario |
| :--- | :--- | :--- |
| **`NORMALIZED`** | Raw variant successfully standardized into canonical vocabulary or unit. | `"CCS Combo 2"` $\to$ `"CCS2"`, `"50000 W"` $\to$ `50.0 kW`, `"400 051"` $\to$ `"400051"`. |
| **`UNCHANGED`** | Raw value was already strictly identical to the canonical format. | `60.0` (float) $\to$ `60.0`, `"CCS2"` $\to$ `"CCS2"`, `"400051"` $\to$ `"400051"`. |
| **`UNKNOWN`** | Field was omitted or empty in source payload; missing-data invariant preserved. | `power_kw = None` $\to$ `None`, `operator_name = None` $\to$ `None`. |
| **`UNMAPPED`** | Present in source, but does not match any known canonical vocabulary or alias; preserved safely. | `"Tesla Supercharger"` $\to$ `"Other"` (raw label preserved), `"Custom AC Socket"` $\to$ `"Other"`. |
| **`INVALID`** | Present in source, but physically impossible, malformed, or contradictory. | `0.0 kW`, `-50 kW`, `(0.0, 0.0)` Null Island, malformed PIN `"ABC123"`. |

---

### 4. Normalization Domains & Vocabularies

#### Domain A: Operator Aliases
- **Canonical Vocabulary:** Registry of verified Indian charging networks derived strictly from project evidence, fixtures, and source adapters: `Tata Power`, `Jio-bp pulse`, `Ather Energy`, `Fortum Charge & Drive`, `ChargeZone`, `Statiq`, `Magenta ChargeGrid`, `Bolt.Earth`, `Zeon Charging`, `Kazam`, `Lithion Power`, `Stilt Mobility`, `ChargePlus`.
- **Explicit Aliases Only:** No guessing or general corporate assumptions.
  - `"Tata Power EZ Charge"`, `"Tata Power EV Charging"` $\to$ `Tata Power` (Slug: `tata-power`, Mapping: `ALIAS`)
  - `"jio bp pulse"`, `"jio-bp"`, `"jio bp"` $\to$ `Jio-bp pulse` (Slug: `jio-bp`, Mapping: `ALIAS`)
  - `"Ather Grid"` $\to$ `Ather Energy` (Slug: `ather-energy`, Mapping: `ALIAS`)
  - `"Fortum"` $\to$ `Fortum Charge & Drive` (Slug: `fortum`, Mapping: `ALIAS`)
  - `"Charge Zone"` $\to$ `ChargeZone` (Slug: `chargezone`, Mapping: `ALIAS`)
  - `"ChargeGrid"` $\to$ `Magenta ChargeGrid` (Slug: `magenta-chargegrid`, Mapping: `ALIAS`)
  - `"Bolt Earth"` $\to$ `Bolt.Earth` (Slug: `bolt-earth`, Mapping: `ALIAS`)
- **Unmapped Operators:** If an operator string is unrecognized (e.g. `"Acme EV Fast Charging Co."`), canonical name is `None`, raw name is preserved verbatim, and mapping type is `UNMAPPED`. Unjustified aliases (e.g., `Relux Electric`, `PlugNgo`, `ElectreeFi`, or parent company legal entities) are omitted.

#### Domain B: Connector Standard Vocabulary
- **Canonical Vocabulary (`StandardConnectorType`):**
  - `CCS2`: `"CCS Combo 2"`, `"Combined Charging System 2"`, `"Type 2 Combo"`, `"IEC 62196-3 Configuration FF"`
  - `CCS1`: `"CCS Combo 1"`, `"Combined Charging System 1"`, `"IEC 62196-3 Configuration EE"`
  - `Type 2`: `"Mennekes"`, `"IEC 62196-2 Type 2"`, `"Type 2 (Socket Only)"`, `"Type 2 (Tethered Connector)"`
  - `Type 1`: `"J1772"`, `"SAE J1772"`, `"Type 1 (J1772)"`
  - `CHAdeMO`: `"CHAdeMO"`, `"IEC 62196-3 Configuration AA"`
  - `GB/T`: `"GB/T (AC)"`, `"GB/T (DC)"`, `"GB/T 20234.2"`, `"GB/T 20234.3"`
  - `Bharat AC001`: `"Bharat AC001"`, `"IEC 60309"`
  - `Bharat DC001`: `"Bharat DC001"`, `"GB/T Bharat DC"`
- **Tesla & Proprietary:** Mapped safely to `Other` with raw label preserved intact in `raw_connector_type`.

#### Domain C: Electrical & Power Normalization
- **Power Unit Standard:** Normalized strictly to kilowatts (`kW`) as positive `float`.
- **Direct kW:** Preserves `60.0 kW` as `60.0` with `POWER_KW_DIRECT` rule.
- **Watts Conversion:** Deterministically converts watts:
  $$\text{kW} = \frac{\text{W}}{1000.0}$$
  Example: `"50000 W"` $\to$ `50.0 kW` (`POWER_CONVERTED_WATTS_TO_KW`).
- **Megawatts Conversion:** Deterministically converts MW:
  $$\text{kW} = \text{MW} \times 1000.0$$
- **Voltage & Amperage Separation:** Voltage is normalized to Volts (`V`), amperage to Amperes (`A`). They are never collapsed or used to invent power unless verified hardware inputs exist.
- **Non-Positive Rejection:** $\le 0.0$ kW is rejected as `INVALID`.

#### Domain D: Current / Electrical Type
- **Canonical Vocabulary (`CurrentType`):** `AC`, `DC`, `unknown`.
- **AC Variants:** `"Alternating Current"`, `"AC (Single-Phase)"`, `"AC (Three-Phase)"` $\to$ `CurrentType.AC`.
- **DC Variants:** `"Direct Current"`, `"DC Fast"`, `"DC Fast Charging"` $\to$ `CurrentType.DC`.
- **Unknown Semantics:** Missing current type evaluates to `CurrentType.UNKNOWN`. AC/DC is never inferred from connector name alone.

#### Domain E: Address & Geography Normalization
- **Unicode NFKD:** Eliminates non-breaking spaces and accents.
- **Whitespace & Punctuation:** Cleans interior spacing before punctuation marks (e.g. `"block ,"` $\to$ `"block,"`).
- **Safe Abbreviations:** Expands standard road descriptors without losing context:
  `Rd.`/`Rd` $\to$ `Road`, `St.`/`St` $\to$ `Street`, `Ave.` $\to$ `Avenue`, `Opp.` $\to$ `Opposite`, `Nr.` $\to$ `Near`, `Bldg.` $\to$ `Building`.
- **Case Preservation:** Title-cases mixed-case text while preserving standard infrastructure acronyms (`BKC`, `MIDC`, `SEZ`, `CIDCO`, `BEST`, `MCA`).

#### Domain F: Latitude / Longitude
- **WGS 84 Decimal Floats:** Parsed without aggressive rounding.
- **Equator & Prime Meridian:** Individual `0.0` latitude or longitude is legitimate and preserved.
- **Null Island Rejection:** Coordinates `(0.0, 0.0)` together are classified as `INVALID` (`COORDS_NULL_ISLAND`).

#### Domain G: Postal / PIN Code
- **Indian 6-Digit PIN:** Enforces regex `^[1-9][0-9]{5}$`. Cleans interior spaces and hyphens (`"400 051"` $\to$ `"400051"`).
- **Invalid PIN Handling:** Malformed PINs (e.g. `"40005"`, `"ABC123"`) evaluate to `status = INVALID`, `normalized_value = None`, with the raw string preserved for audit. A malformed PIN is **never** silently repaired into a different valid PIN.

#### Domain H: Pricing / Tariff Normalization
- **Tariff Basis Demarcation (`PricingBasis`):**
  - `PER_KWH`: `"₹18.50 per kWh"`, `"18.50/kWh"` $\to$ `price_per_kwh = 18.50`, `pricing_basis = PER_KWH`
  - `PER_SESSION`: `"₹50 per session"` $\to$ `price_per_session = 50.0`, `pricing_basis = PER_SESSION`
  - `PER_HOUR`: `"₹100 per hour"` $\to$ `price_per_hour = 100.0`, `pricing_basis = PER_HOUR`
- **Explicit Free Charging:**
  Represented as a first-class semantic state: `is_free = True`, `price_per_kwh = 0.0`, `pricing_type = FREE`.
- **Missing Pricing:**
  `price_per_kwh = None`, `is_free = False`, `pricing_type = UNKNOWN`. **Missing pricing is NEVER converted to ₹0.**

#### Domain I: Operating Hours Normalization
- **24x7 Schedule:**
  `"Open 24/7 all days"` $\to$ `is_24_hours = True`, `opening_time = None`, `closing_time = None` (strictly adhering to database check constraint `chk_stations_hours`).
- **Daily Interval:**
  `"08:00 - 22:00"` or `"8:00 AM - 10:00 PM"` $\to$ `is_24_hours = False`, `opening_time = "08:00"`, `closing_time = "22:00"`.
- **Overnight Intervals:**
  `"22:00 - 06:00"` $\to$ `TimeInterval(open_time="22:00", close_time="06:00", is_overnight=True)`.
- **Multiple Intervals:**
  `"09:00 - 13:00, 16:00 - 21:00"` $\to$ Day schedule containing two discrete intervals.
- **Closed Day:**
  `"Closed for maintenance"` $\to$ `DaySchedule(is_closed=True)`.
- **Unstructured Hours:**
  `"Subject to mall hours"` $\to$ preserved as raw text with `is_structured = False` and `status = UNMAPPED`. Missing hours remain `UNKNOWN` (never defaulted to 24x7 or closed).

---

### 5. Provenance & Non-Destructive Replacement

- Every call to `normalize_station_record()` produces a new `NormalizedStationRecord` without mutating the source record (`copy.deepcopy` invariant verified).
- Lineage fields (`source_id`, `source_station_id`, `source_url`, `raw_payload_hash`, `contract_version`) are preserved verbatim.
- Audited normalization metadata is added to `extra_metadata["normalization"]`:
  ```json
  {
    "version": "1.0.0"
  }
  ```
- Detailed typed normalization auditing is returned in `StationNormalizationResult` (`operator`, `coordinates`, `address`, `operating_hours`, `connectors`, `field_statuses`, `warnings`), leaving raw metadata clean and ensuring 100% deterministic, idempotent normalization without runtime timestamp drift. Deterministic source timestamps from telemetry observations or extra metadata are preserved without generating execution timestamps (`datetime.now()`).

---

### 6. Known Boundaries & Limitations

1. **Precedence Survivorship (Step 2.7):**
   When Source A reports ₹18.50/kWh and Source B reports ₹19.00/kWh, Step 2.5 normalizes both. Arbitrating which source wins is reserved for Step 2.7.
2. **Quality Quarantine (Step 2.6):**
   Step 2.5 flags malformed fields as `INVALID` or `UNMAPPED`. Step 2.6 evaluates whether the entire station record should be quarantined or accepted into the operational pipeline.
3. **Database Migration:**
   Zero database schema changes. Public and analytics tables remain completely intact.
