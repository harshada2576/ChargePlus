# ChargePlus — Real-World EV Station Dataset (v2.1 Data-Quality Remediation & Verification)

## Overview & Objective

This package delivers a verified, source-backed collection of **541 genuine electric vehicle charging stations** across 20 Indian states and Union Territories, with comprehensive coverage in Maharashtra (Mumbai, Thane, Navi Mumbai, Kalyan-Dombivli, Mira-Bhayandar, Vasai-Virar, Pune, Satara, Kolhapur, Solapur, Dhule, Nashik, Ahmednagar, Nagpur, Chhatrapati Sambhajinagar), Karnataka, Tamil Nadu, Kerala, Gujarat, Delhi, Telangana, Rajasthan, Madhya Pradesh, Uttar Pradesh, Uttarakhand, Goa, West Bengal, Andhra Pradesh, Haryana, Himachal Pradesh, Jharkhand, Punjab, Bihar, and Jammu and Kashmir.

This dataset replaces synthetic demo records with authentic community- and operator-contributed charging stations from **Open Charge Map** under the **Creative Commons Attribution 4.0 International (CC BY 4.0)** license.

---

## 1. Safety Boundaries & Execution Requirements

- **Zero Live Database Mutations**: No connection to Supabase or any live database was initiated. Zero `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `DROP`, or migrations were run.
- **Frontend Preserved**: Zero frontend components, client-side hooks, state stores, or routes were modified.
- **Safe Working Copy**: Prior versions were backed up to `artifacts/chargeplus-real-dataset-backup/` (v1) and `artifacts/chargeplus-real-dataset-v2-backup/` (v2) prior to remediation.
- **No Secrets Exposed**: All pipeline scripts execute offline using local snapshots without requiring API keys or database connection strings.

---

## 2. Key Data-Quality Remediations (v2.1)

### A. Geographic Normalization, Locality Preservation & Town Disambiguation
The previous `resolve_location()` heuristic permitted Indian PIN-code prefixes to override explicit, valid source state information. In v2.1, source states and municipal localities are verified using geographic bounding boxes (`STATE_BOUNDS`) and canonical spelling maps (`STATE_CANONICAL_MAP`), ensuring that:
1. **Audi Service Center (OCM ID 308728)**: Corrected from `Maharashtra` to **Goa** (Town: **Verna**, PIN: 403722, Coords: 15.3612° N, 73.9536° E).
2. **1930 Vasco Mall (OCM ID 308727)**: Corrected from `Maharashtra` to **Goa** (Town: **Vasco Da Gama**, PIN: 403802, Coords: 15.3972° N, 73.8130° E).
3. **Royal Orchid Beach Resort & Spa (OCM ID 308725)**: Corrected from `Maharashtra` to **Goa** (Town: **Utorda**, PIN: 403713, Coords: 15.3203° N, 73.9018° E).
4. **Fortune Resort Benaulim (OCM ID 308724)**: Corrected from `Maharashtra` to **Goa** (Town: **Benaulim**, PIN: 403716, Coords: 15.2463° N, 73.9298° E).
5. **The St. Regis Resort (OCM ID 308723)**: Corrected from `Maharashtra` to **Goa** (Town: **Cavelossim**, PIN: 403731, Coords: 15.1541° N, 73.9512° E).
6. **Magsons Supermarket (OCM ID 308726)**: Corrected from `Maharashtra` to **Goa** (Town: **Vasco Da Gama**, PIN: 403802, Coords: 15.3879° N, 73.8632° E).
7. **Tamar Cafe (OCM ID 478884)**: Corrected from `Tamil Nadu` to **Kerala** (Town: **Kumbla**, Kasaragod district, Coords: 12.6063° N, 74.9384° E). The source PIN `621321` was a contributor typographical error that previously triggered a naive Tamil Nadu prefix rule.
8. **Vetri Hyundai (OCM ID 478874)**: Corrected from `Uttar Pradesh` to **Tamil Nadu** (Town: **Thanjavur**, Coords: 10.7409° N, 79.1076° E). The source PIN `208263` was a contributor typo that previously triggered a naive UP prefix rule.
9. **NE-4 KFC Parking (OCM ID 477284)**: Corrected from `Rajasthan` to **Haryana** (Town: **Nuh**, Delhi-Vadodara Expressway, Coords: 27.7356° N, 76.9839° E). Previously misclassified by a broad expressway bounding box rule.
10. **MobiLane Treat Imperial (OCM ID 502270)**: Flagged for manual review (`[FLAGGED_FOR_MANUAL_REVIEW: Coordinates 23.0318, 72.5112 conflict with Chhatrapati Sambhajinagar address]`) due to an OCM source data entry discrepancy where Ahmedabad coordinates were paired with a Chhatrapati Sambhajinagar address.
11. **Town vs. City Discrepancy Audit (48 Stations)**: An exhaustive investigation of all 48 stations where source `Town` differed from normalized `city` was performed. In 100% of these cases, the original town information was retained without loss by enriching the `locality` field (e.g. NH-48 waypoints such as *Wele*, *Surur*, *Khandala*, *Shendre*, *Malkapur*, *Kini*, *Shiroli*, *Toap* were preserved in `locality` while indexed under district municipal hubs *Satara* and *Kolhapur*; metropolitan suburbs such as *Baner*, *Pimpri-Chinchwad*, *Panambur*, *LB Nagar*, *Badarpur*, *Khardaha* were preserved in `locality`). See [`city_locality_audit.md`](file:///d:/Desktop/Projects/ChargePlus/artifacts/chargeplus-real-dataset/city_locality_audit.md) for individual record evidence and justifications.

### B. Operational Status Mapping Policy
Source operational statuses have been mapped using an explicit policy considering both `StatusType.Title` and `StatusType.IsOperational`:
- **Status ID 50 (`Operational`, `IsOperational: True`)** $\rightarrow$ `operational`
- **Status ID 75 (`Partly Operational`, `IsOperational: True`)** $\rightarrow$ `operational`
- **Status ID 100 (`Not Operational`, `IsOperational: False`)** $\rightarrow$ `temporarily_unavailable` (or `permanently_closed` if title contains closed/permanent).
  - *Fixed*: **SEL Dev Maharashtra (OCM ID 510426)**: Corrected from `operational` to `temporarily_unavailable`.
  - *Fixed*: **May Fair Green Mark Project (OCM ID 508927)**: Corrected from `operational` to `temporarily_unavailable`.
  - *Fixed*: **May Fair Marketing Office (OCM ID 508926)**: Corrected from `operational` to `temporarily_unavailable`.
- **Status ID 30 (`Temporarily Unavailable`, `IsOperational: True`)**: Contradictory flag preserved conservatively as `unknown`.
  - *Fixed*: **Auto Matrix, Bejai (OCM ID 309017)**: Preserved as `unknown`.
  - *Fixed*: **Sowkar M Baba Pai & Co (OCM ID 309015)**: Preserved as `unknown`.

### C. Mutually Exclusive Pricing Breakdown
Connectors are categorized into four mutually exclusive, non-overlapping pricing categories across all 655 connectors:
- **Verified per-kWh Tariffs**: **489** connectors (carry source-published per-kWh rates).
- **Explicit Free Tariffs**: **2** connectors (0.0 INR/kWh).
- **Unverified Numeric Estimates**: **82** connectors (stored in `price_estimate_per_kwh` with `price_estimate_source = 'ocm_usage_cost_unverified'`; never promoted to verified tariff fields).
- **Unknown Tariffs**: **82** connectors (pricing fields remain `NULL`).
- **Total Connectors**: **655** ($489 + 2 + 82 + 82 = 655$).

### D. Reproducible Quarantine & Curated Fixtures
The acquisition pipeline bundles `curated_project_fixtures.json` (the 12 canonical project fixtures, including Bandra Kurla Complex, Andheri East, Lower Parel, etc.) directly in the package. These 12 fixtures remain strictly quarantined alongside 361 unresolvable crowdsourced records, producing exactly **373 reproducible quarantine records** in `quarantine_records.csv`.

### E. Field-Level Provenance Ledger & Byte-for-Byte Determinism
`field_provenance.csv` now provides 4,328 field-level records (8 entries per station for `name`, `address`, `coordinates`, `operator`, `connector_type`, `power_kw`, `tariff`, and `operational_status`). Each record specifies `source_name = 'open_charge_map'`, source POI URL, snapshot retrieval timestamp (`2026-10-18T13:30:00Z`), and confidence tier `COMMUNITY_CROWDSOURCED_OPEN_DATA`. Volatile execution timestamps in `duplicate_review.csv` and manifests have been stabilized using deterministic build timestamps (`2026-10-18T14:00:00Z`), guaranteeing 100% byte-for-byte reproducibility across runs.

---

## 3. Package File Inventory

| File | Records / Rows | Description |
| :--- | :--- | :--- |
| `stations.csv` | 541 | Normalized, source-backed physical EV stations |
| `connectors.csv` | 655 | Standardized connector specifications (CCS2, Type 2, CHAdeMO, GB/T, Bharat AC001) |
| `operators.csv` | 31 | Operating networks (Tata Power, Jio-bp, Statiq, Chargezone, Zeon, GO EC, etc.) |
| `data_sources.csv` | 1 | Registry entry for Open Charge Map (`open_charge_map`) |
| `station_source_link.csv` | 541 | Provenance mapping linking internal UUIDs to OCM POI IDs, URLs, and payload hashes |
| `station_sources.csv` | 541 | Alias for spec compatibility |
| `source_registry.csv` | 2 | Detailed provider registry with licenses, URLs, and attribution terms |
| `field_provenance.csv` | 4,328 | Field-level provenance ledger covering 8 fields per station |
| `duplicate_review.csv` | 9 | Spatial duplicate collisions ($\le 40$m) logged with deterministic review evaluation |
| `rejected_records.csv` | 2 | Hard-rejected records (out-of-bounds coordinates) with documented reasons |
| `quarantine_records.csv` | 373 | Quarantined records (12 curated fixtures + 361 unresolvable crowdsourced entries) |
| `curated_project_fixtures.json` | 12 | Versioned, documented input artifact for curated project fixtures |
| `city_locality_audit.md` | 48 | Comprehensive audit of all 48 town-to-city normalization relationships |
| `data_dictionary.csv` | 16 | Field definitions, types, and database constraint mappings |
| `raw_snapshot_india.json` | 1,982 | Source snapshot retrieved from Open Charge Map API |
| `validation_report.json` | — | Comprehensive validation report demonstrating 22 passed integrity checks |
| `dataset_manifest.json` | — | Dataset metadata, record counts, geographic summary, and SHA-256 checksums |
| `manifest.json` | — | Manifest alias for spec compatibility |
| `reproduce_acquisition.py` | — | Deterministic offline reproduction pipeline |
| `sha256_checksums.txt` | — | SHA-256 integrity checksums for all deliverables |

---

## 4. Geographic Distribution Summary

- **Total States & UTs Covered**: 20
- **Karnataka**: 176 stations
- **Tamil Nadu**: 100 stations
- **Kerala**: 81 stations
- **Maharashtra**: 79 stations
- **Delhi**: 23 stations
- **Gujarat**: 20 stations
- **Telangana**: 9 stations
- **Madhya Pradesh**: 8 stations
- **Rajasthan**: 7 stations
- **Uttar Pradesh**: 6 stations
- **Uttarakhand**: 7 stations
- **Goa**: 6 stations
- **West Bengal**: 6 stations
- **Andhra Pradesh**: 6 stations
- **Himachal Pradesh**: 2 stations
- **Jharkhand**: 2 stations
- **Haryana**: 1 station
- **Punjab**: 1 station
- **Bihar**: 1 station
- **Jammu and Kashmir**: 1 station
- **Total Verified Stations**: **541 stations**

---

## 5. How to Reproduce

### A. Offline Reproduction (Zero Network, Fully Deterministic)
Run the pipeline from the dataset directory:
```powershell
python reproduce_acquisition.py --mode offline
```
This script reproduces all CSV deliverables, manifests, validation reports, and checksums byte-for-byte.

### B. Live Mode (Requires Open Charge Map API Key)
```powershell
$env:OPENCHARGEMAP_API_KEY = "your-api-key"
python reproduce_acquisition.py --mode live
```

---

## 6. Known Remaining Limitations

1. **`MobiLane Treat Imperial` (OCM ID 502270)**: Flagged for manual review. The physical address is in Chhatrapati Sambhajinagar, Maharashtra (PIN 431001), but the crowdsourced coordinates (23.0318° N, 72.5112° E) reflect an Ahmedabad, Gujarat location due to an OCM contributor batch submission error.
2. **Crowdsourced Opening Hours**: Most crowdsourced records do not specify explicit opening/closing hours; these default to `is_24_hours = false` with null opening/closing hours per schema constraints.
3. **Unverified Numeric Estimates**: 82 connectors contain ambiguous numeric tariff strings (e.g., bare numbers without explicit `/kWh` or `/session` units). These are isolated in `price_estimate_per_kwh` and must not be treated as legally published rates until verified.
