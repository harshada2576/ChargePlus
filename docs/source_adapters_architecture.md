# ChargePlus — Source-Specific Ingestion Adapters Architecture & OpenChargeMap Specification

**Status:** ACTIVE & LOCKED (Phase 2, Step 2.2)  
**Boundary:** Source Payload $\to$ Source-Specific Adapter $\to$ Step 2.1 Canonical Input Contract  
**ETL Layer:** Python Server-Side (`backend/ingestion/`)  
**Database Persistence:** STRICTLY FORBIDDEN IN THIS LAYER (Zero writes to Supabase)

---

## 1. Architectural Overview & Design Philosophy

The ChargePlus data ingestion subsystem operates under strict boundary isolation:
```
┌─────────────────────────┐
│ External Data Sources   │ (OpenChargeMap API, future CPO feeds, static datasets)
└────────────┬────────────┘
             │ Raw JSON / Payload
             ▼
┌─────────────────────────┐
│ Fetch Layer             │ fetch_raw(bounding_box, ...) [Network I/O & API Auth only]
└────────────┬────────────┘
             │ Raw Dict / List[Dict]
             ▼
┌─────────────────────────┐
│ Parsing Layer           │ parse_raw(raw_payload) $\to$ RawSourceRecord (SHA-256 hash & provenance)
└────────────┬────────────┘
             │ RawSourceRecord
             ▼
┌─────────────────────────┐
│ Normalization Layer     │ normalize_station(raw_record) $\to$ NormalizedStationRecord
└────────────┬────────────┘
             │ NormalizedStationRecord
             ▼
┌─────────────────────────┐
│ Validation Layer        │ DataQualityValidator.validate_station(record)
└────────────┬────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Canonical Ingestion Result                                             │
│ (NormalizedStationRecord, NormalizedConnectorRecord, ProvenanceInfo)   │
└────────────────────────────────────────────────────────────────────────┘
             │ (Handed off to Step 2.4 Entity Resolution & Step 2.5 Persistence)
             ▼
     [NO SUPABASE WRITES HERE]
```

### Core Design Rules
1. **Unidirectional Contract Boundary:** The adapter produces Step 2.1 canonical models (`NormalizedStationRecord`, `NormalizedConnectorRecord`, `NormalizedObservationRecord`, `ProvenanceInfo`). It never leaks source-specific schemas into operational tables.
2. **Deterministic Provenance:** Every raw payload is preserved unmutated, SHA-256 fingerprinted, and linked via `ProvenanceInfo`.
3. **No Synthetic Truth:** Missing data is preserved as `None` or `unknown`. Zero power or free pricing is never fabricated.
4. **Static Equipment $\neq$ Live Availability:** Static operational statuses (e.g. OCM Status 50 "Operational") represent physical equipment status, NOT real-time bay availability. Live observations are only produced when real telemetry timestamps and dynamic bay statuses are provided.
5. **Record-Level Error Isolation:** A malformed station record inside a batch of 1,000 records must never crash the entire batch. Malformed records are captured with structured errors in `BatchAdapterResult.rejected_records`.

---

## 2. Base Adapter Interface (`BaseSourceAdapter`)

Located in [`backend/ingestion/base.py`](file:///c:/Users/Admin/Desktop/Projects/ChargePlus/backend/ingestion/base.py), the `BaseSourceAdapter` defines the contract for all present and future source adapters:

```python
class BaseSourceAdapter(ABC):
    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique slug identifying the external data source (e.g. 'openchargemap')."""
        pass

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable display name for the source."""
        pass

    @abstractmethod
    def parse_raw(self, raw_payload: Union[Dict[str, Any], str], retrieved_at: Optional[datetime] = None) -> RawSourceRecord:
        """Wraps raw source payload, generates deterministic SHA-256 hash, and captures extraction timestamp."""
        pass

    @abstractmethod
    def normalize_station(self, raw_record: RawSourceRecord) -> NormalizedStationRecord:
        """Parses source-specific hierarchy and produces the canonical NormalizedStationRecord."""
        pass

    def validate_record(self, station_record: NormalizedStationRecord) -> ValidationResult:
        """Runs Step 2.1 DataQualityValidator rules."""
        return DataQualityValidator.validate_station(station_record)

    def process_record(self, raw_payload: Union[Dict[str, Any], str], retrieved_at: Optional[datetime] = None) -> AdapterResult:
        """End-to-end processing pipeline for a single record with error isolation."""
        pass

    def process_batch(self, raw_payloads: List[Union[Dict[str, Any], str]], retrieved_at: Optional[datetime] = None) -> BatchAdapterResult:
        """Batch ingestion pipeline with record-level failure quarantine."""
        pass
```

---

## 3. OpenChargeMap Source Verification & API Realities

OpenChargeMap (OCM) was verified against official documentation, API schemas, and live endpoint structures:

### Verified OCM Data Characteristics
- **Station Identity:** `ID` (integer, e.g. `295001`), `UUID` (GUID string), `DataProviderID` (integer).
- **Location:** Encapsulated inside `AddressInfo`:
  - `Title`: station name.
  - `Latitude`, `Longitude`: float decimal degrees.
  - `AddressLine1`, `AddressLine2`, `Town`, `StateOrProvince`, `Postcode`.
  - `Country`: nested object with `ISOCode` (e.g. `"IN"`), `Title` (e.g. `"India"`).
  - `AccessComments`: string with access directions or site rules.
  - `ContactTelephone1`: string phone number.
  - `RelatedURL`: web link.
- **Operator Information:** Encapsulated inside `OperatorInfo`:
  - `ID`: integer operator identifier.
  - `Title`: operator name (e.g. `"Tata Power EZ Charge"`).
  - `WebsiteURL`: operator site.
- **Operational Status:**
  - `StatusType`: nested object with `ID`, `Title`, `IsOperational`.
  - `StatusTypeID == 50`: "Operational" (equipment is deployed and working).
  - `StatusTypeID == 100`: "Planned / Under Construction".
  - `StatusTypeID == 150`: "Temporarily Unavailable / Out of Service".
  - `StatusTypeID == 200`: "Decommissioned / Removed".
- **Dynamic Telemetry:**
  - `StatusTypeID == 10`: "Currently Available (Automated Status)".
  - `StatusTypeID == 20`: "Currently In Use (Automated Status)".
  - `DateLastStatusUpdate`: ISO-8601 UTC timestamp of the last status update.
- **Connectors:** List of `Connections` objects:
  - `ID`: integer connection ID (may be absent in aggregated feeds).
  - `ConnectionType`: nested object with `ID` and `Title` (e.g. `ConnectionTypeID: 33` $\to$ `"CCS (Type 2)"`).
  - `Quantity`: integer (e.g. `4` connectors of this type).
  - `PowerKW`: float/decimal power in kilowatts.
  - `CurrentType`: nested object with `ID` and `Title` (e.g. `"AC (Three-Phase)"`, `"DC"`).
  - `Voltage`: float/int (volts).
  - `Amps`: float/int (amperes).
  - `StatusType`: per-connection status.
- **Pricing:** `UsageCost` (free-text string, e.g. `"₹18.50/kWh"`).
- **Usage Restrictions:** `UsageType` (e.g. `ID: 1` $\to$ `"Public"`, `ID: 6` $\to$ `"Private"`).

---

## 4. OpenChargeMap Field Mapping Table

| OCM Source Path | ChargePlus Canonical Target | Transformation / Rule | Req / Opt | Fallback Behavior | Provenance Handling |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ID` | `source_station_id` | String conversion: `str(raw["ID"])` | Required | Throws `ValueError` (Record Rejected) | Stored as primary source record ID |
| `AddressInfo.Title` | `name` | Stripped string; defaults to `"Unnamed Charging Station"` if whitespace | Required | Fallback to default name string | Preserved in `raw_payload` |
| `AddressInfo.Latitude` | `latitude` | Float conversion; validated $[-90, +90]$; Null Island rejected | Required | Validation error; record rejected | Preserved in `raw_payload` |
| `AddressInfo.Longitude` | `longitude` | Float conversion; validated $[-180, +180]$; Null Island rejected | Required | Validation error; record rejected | Preserved in `raw_payload` |
| `AddressInfo.AddressLine1` | `address` | String trimmed; concatenated with `AddressLine2` if both present | Optional | `None` | Preserved in `raw_payload` |
| `AddressInfo.Town` | `city` | String trimmed | Optional | `None` | Preserved in `raw_payload` |
| `AddressInfo.StateOrProvince` | `state` | String trimmed | Optional | `None` | Preserved in `raw_payload` |
| `AddressInfo.Postcode` | `postal_code` | String trimmed | Optional | `None` | Preserved in `raw_payload` |
| `AddressInfo.Country.ISOCode` | `country` | Uppercase 2-letter ISO code; validated against India pilot boundary | Optional | `"IN"` if Country Title is `"India"`, else `None` | Non-IN records quarantined with warning |
| `OperatorInfo.Title` | `operator_name` | String trimmed | Optional | `None` | Preserved in `raw_payload` |
| `AddressInfo.ContactTelephone1` | `contact_phone` | String trimmed | Optional | `None` | Preserved in `raw_payload` |
| `AddressInfo.RelatedURL` | `contact_url` | String trimmed; validated URL syntax | Optional | `None` | Preserved in `raw_payload` |
| `UsageType.Title` | `access_type` | Mapped to `public`, `private`, `restricted`, `unknown` | Optional | `unknown` | Original usage title in `extra_metadata` |
| `StatusType.ID` | `operational_status` | Status 50 $\to$ `OPERATIONAL`; 100 $\to$ `PLANNED`; 150 $\to$ `TEMPORARILY_UNAVAILABLE`; 200 $\to$ `DECOMMISSIONED` | Optional | `UNKNOWN` | Original status title in `extra_metadata` |
| `DateLastStatusUpdate` / `DateLastVerified` | `source_updated_at` | Parsed ISO-8601 datetime with UTC normalization | Optional | `None` | Stored in `RawSourceRecord` & `ProvenanceInfo` |
| `Connections[i].ID` | `source_connector_id` | String conversion if present; **omitted for aggregated connectors** | Optional | `None` (Never invented!) | Original connection ID |
| `Connections[i].ConnectionType.ID` | `connector_type` | Strict mapping table $\to$ `StandardConnectorType` | Required | `OTHER` with parsing warning | Original OCM ConnectionType Title in metadata |
| `Connections[i].CurrentType.Title` | `current_type` | Contains "AC" $\to$ `CurrentType.AC`; contains "DC" $\to$ `CurrentType.DC` | Optional | `UNKNOWN` | Original CurrentType Title |
| `Connections[i].Quantity` | `quantity` | Integer conversion; validated $\ge 1$ | Required | Defaults to `1` | Preserved in connector `extra_metadata` |
| `Connections[i].PowerKW` | `power_kw` | Float conversion; validated $\in (0, 1000]$ | Optional | `None` (Never invented!) | Original value preserved |
| `Connections[i].Voltage` | `voltage` | Float conversion | Optional | `None` | Preserved in `extra_metadata` |
| `Connections[i].Amps` | `amperage` | Float conversion | Optional | `None` | Preserved in `extra_metadata` |
| `UsageCost` | `pricing_raw` | Preserved as exact raw string; never parsed to free tariff | Optional | `None` | Preserved in `raw_payload` |
| `DataProvider`, `UUID`, etc. | `extra_metadata` | Preserved as key-value JSON in station metadata | Optional | Clean dictionary | Full access to source attributes |

---

## 5. Connector Normalization Specification

### Connector Type Mapping
OpenChargeMap categorizes connectors using `ConnectionTypeID`. ChargePlus enforces confident normalization vs ambiguous fallback:

| OCM ConnectionTypeID | OCM Title | ChargePlus Canonical Type | Mapping Confidence |
| :--- | :--- | :--- | :--- |
| `33` | `CCS (Type 2)` | `StandardConnectorType.CCS2` | CONFIDENT |
| `32` | `CCS (Type 1)` | `StandardConnectorType.CCS1` | CONFIDENT |
| `25` | `Type 2 (Socket Only)` | `StandardConnectorType.TYPE_2` | CONFIDENT |
| `1036` | `Type 2 (Tethered Connector)` | `StandardConnectorType.TYPE_2` | CONFIDENT |
| `1` | `Type 1 (J1772)` | `StandardConnectorType.TYPE_1` | CONFIDENT |
| `2` | `CHAdeMO` | `StandardConnectorType.CHADEMO` | CONFIDENT |
| `34` | `GB/T (AC)` | `StandardConnectorType.GB_T` | CONFIDENT |
| `35` | `GB/T (DC)` | `StandardConnectorType.GB_T` | CONFIDENT |
| `28` | `CEE 7/4 - Schuko` | `StandardConnectorType.OTHER` | FALLBACK (Domestic AC Socket) |
| Any unmapped ID | e.g. Proprietary / Regional | `StandardConnectorType.OTHER` | AMBIGUOUS / WARNING EMITTED |

### Aggregated Connectors vs Individual Connectors
- **Individual Connectors:** When OCM provides individual `ID` fields (e.g. `Connection.ID = 1001`), the adapter sets `source_connector_id = "1001"`, `quantity = 1`.
- **Aggregated Connectors:** When OCM provides `Quantity: 4` under a single connection block without individual IDs, the adapter produces:
  - `connector_type = StandardConnectorType.CCS2`
  - `quantity = 4`
  - `source_connector_id = None`
  - **CRITICAL ANTI-PATTERN PREVENTED:** The adapter NEVER fabricates synthetic IDs (`"conn_1"`, `"conn_2"`).

---

## 6. Power & Electrical Normalization

1. **Unit Standard:** Power is strictly normalized to kilowatts (`kW`).
2. **Missing Power Handling:** If OCM omits `PowerKW` or specifies `null`:
   - `power_kw = None`
   - **CRITICAL ANTI-PATTERN PREVENTED:** The adapter NEVER defaults missing power to `0` kW and NEVER invents power based on connector type (e.g. guessing 50 kW for CCS2).
3. **Malformed Power Handling:** If OCM supplies invalid power (e.g. negative numbers, string junk, or non-numeric values), the value is safely caught, set to `None`, and an explicit warning is recorded.

---

## 7. Operational State vs Live Telemetry Observations

ChargePlus maintains a strict semantic distinction between static equipment operational state and dynamic real-time bay availability:

### Static Operational Status
- Mapped from `StatusType.ID` (e.g. 50 $\to$ `OPERATIONAL`, 150 $\to$ `TEMPORARILY_UNAVAILABLE`).
- Stored directly on `NormalizedStationRecord.operational_status`.
- Connectors retain `status = AvailabilityStatus.UNKNOWN`.
- `NormalizedStationRecord.observation` is set to `None`.
- **CRITICAL RULE:** Static operational status NEVER manufactures a fake observation or implies that a connector is free to plug in.

### Dynamic Telemetry Observations
- Created ONLY when OCM provides real-time automated status:
  - `StatusTypeID == 10` ("Currently Available") $\to$ `AvailabilityStatus.AVAILABLE`
  - `StatusTypeID == 20` ("Currently In Use") $\to$ `AvailabilityStatus.OCCUPIED`
- AND provides a valid timestamp in `DateLastStatusUpdate`.
- Produces a formal `NormalizedObservationRecord` with:
  - `source_id = "openchargemap"`
  - `source_station_id = str(raw["ID"])`
  - `observed_at = parsed_DateLastStatusUpdate`
  - `retrieved_at = ingestion_run_time`
  - `availability_status = AvailabilityStatus.AVAILABLE | OCCUPIED`
- If no timestamp is provided with the status update, no observation record is emitted.

---

## 8. Provenance & Payload Integrity

Every record processed through `OpenChargeMapAdapter` retains complete lineage:
- **`RawSourceRecord.raw_payload`:** The pristine, unmutated JSON dictionary received from the API or fixture.
- **`RawSourceRecord.raw_payload_hash`:** Deterministic SHA-256 digest computed across canonical JSON serialization (`sort_keys=True, separators=(',', ':')`).
- **`retrieved_at`:** Exact UTC timestamp when the payload was retrieved.
- **`source_updated_at`:** Exact UTC timestamp reported by OCM when the station was last edited/verified.
- **`ProvenanceInfo`:** First-class model linking `source_id`, `source_station_id`, `raw_payload_hash`, `retrieved_at`, and `contract_version = "1.0.0"`.

---

## 9. Error Isolation & Batch Resiliency

The adapter distinguishes between fatal payload errors and record-level recoverable errors:
```
Batch of N Payloads
       │
       ├── Record 1: Valid $\to$ NormalizedStationRecord $\to$ Added to batch.valid_stations
       ├── Record 2: Missing required ID $\to$ AdapterResult(success=False, error="...") $\to$ Added to batch.rejected_records
       ├── Record 3: Null Island (0,0) $\to$ AdapterResult(success=False, validation=CRITICAL) $\to$ Added to batch.rejected_records
       ├── Record 4: Non-India Coordinate $\to$ AdapterResult(success=True, validation=WARNING) $\to$ Added to batch.quarantined_records
       └── Record 5: Valid $\to$ NormalizedStationRecord $\to$ Added to batch.valid_stations
```

- **Record-Level Isolation:** Failure of Record 2 or 3 does not stop processing of Records 4 and 5.
- **Batch Outcome:** Returned as `BatchAdapterResult` with counts: `total_processed`, `valid_count`, `rejected_count`, `quarantined_count`.

---

## 10. API Authentication & Network Transport Security

Located in `OpenChargeMapAdapter.fetch_raw()`:
1. **API Key Requirement:** OCM API requires an `X-ApiKey` header.
2. **Environment Variable:** Loaded strictly from `OPENCHARGEMAP_API_KEY`.
3. **No Hardcoded Keys:** Code and unit tests never contain hardcoded keys.
4. **Offline Testability:** All automated unit tests run against offline fixtures without making outbound HTTP requests. If `OPENCHARGEMAP_API_KEY` is missing during live fetch invocation, `RuntimeError` is raised immediately before any network socket is opened.

---

## 11. Boundaries: What This Adapter Intentionally Does NOT Do

To maintain strict Phase 2 separation of concerns, the adapter explicitly DOES NOT:
1. **Does NOT write to Supabase:** No queries to `public.stations`, `public.connectors`, or `public.station_observations`.
2. **Does NOT perform Entity Resolution:** Does not merge OCM stations with other sources or deduplicate nearby stations. (Reserved for Step 2.4).
3. **Does NOT load the Data Warehouse:** No inserts into `analytics.*`. (Reserved for Phase 4).
4. **Does NOT run ML Models:** No predictions or feature generation. (Reserved for Phase 5).
5. **Does NOT invent missing data:** Missing power, missing pricing, and unknown connectors are preserved faithfully without guesswork.
