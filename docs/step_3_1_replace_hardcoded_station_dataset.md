# ChargePlus — Phase 3, Step 3.1: Replace Hardcoded Station Dataset & Data-Honesty Audit

> **Phase 3 Invariants & Principles**
> 1. Never invent stations, availability, prices, reviews, connector power, observations, queue estimates, or predictions.
> 2. Unknown values remain unknown: unknown connector power is SQL `NULL` and TypeScript `null`, never `0` or fabricated.
> 3. Unknown connector physical quantity is `null`, never defaulted to `1`.
> 4. Unknown connector availability is `null`, never defaulted to `0` (busy) or `total` (available).
> 5. Static station operational status (`operational_status`) must never be represented as live connector availability (Rule 5).
> 6. Unknown locations or addresses must never invent presumed cities (e.g. Mumbai) or synthesized street addresses.
> 7. Public station browsing must not require authentication.
> 8. The existing frontend visual design, tokens, typography, and layout are locked.
> 9. Do not introduce a FastAPI proxy: frontend queries Supabase directly via the public anonymous key.

---

## 1. Objective and Scope

The goal of Step 3.1 is to replace the prototype hardcoded in-memory station dataset (`seed` array in `src/data/stations.ts`) with authentic data sourced from Supabase views, without altering the locked UI design or introducing unvetted data proxies.

### Acceptance Criteria
- [x] **Security Prerequisite**: Mitigated MapLibre popup HTML-injection vulnerability before binding external database strings to markup.
- [x] **Data Layer Modernization**: Built pure domain adapter mapping `public.v_station_current_state` and `public.v_station_connectors` view rows to frontend domain models.
- [x] **Honesty & Cold-Start Preservation**:
  - Unknown connector power is preserved as `null`.
  - Unknown connector physical quantity is preserved as `null` (not defaulted to `1`).
  - Unknown connector availability is preserved as `null` (distinct from zero and from fully available; not derived from station-level status).
  - Unknown connector type maps to `"Unknown"` (never defaulted to `"CCS2"`).
  - Static operational status without live observations maps to `status = "unknown"`, never `"available"`.
  - Unobserved pricing maps to `pricePerKwh: null, isFree: null`, never free or ₹0.
  - Missing locality/city/state maps to `"Area unknown"` (never presuming Mumbai).
  - Missing address components map to `"Address unavailable"` (never constructing factual addresses like `"${name}, Mumbai, Maharashtra"`).
  - Missing operator maps to `"Unknown Operator"` (never presuming `"Independent"`).
  - Reviews and busy windows start empty (`[]`), never fabricated.
- [x] **Live Data Access Functions**: Implemented `fetchStations()` and `fetchStationById(id)` querying Supabase views via `@supabase/supabase-js`.
- [x] **Station Route Integration**: Connected `src/app/station/[id]/page.tsx` to `fetchStationById(id)` with `notFound()` and dynamic generation.
- [x] **Backward Compatibility**: Retained synchronous exports and utility functions (`distanceKm`, `formatDistance`, `getTotalChargers`, `getAvailableChargers`, `getMaxPowerKw`, `MUMBAI_CENTER`) so existing views remain stable.
- [x] **Verification**: Passed 8 Node unit tests, Python regression suite (376 tests), TypeScript typecheck, ESLint, Next.js production build, and live Supabase queries.

---

## 2. Implementation Details

### 2.1 Security Hardening: MapLibre Popup HTML Sanitization
- **Vulnerability**: In `src/components/MapLibreMap.tsx`, station properties (`name`, `operator`, `area`) and `id` were directly interpolated into `popupNode.innerHTML` strings.
- **Remediation**:
  - Implemented `escapeHtml(str)` in `src/lib/util.ts` replacing `&`, `<`, `>`, `"`, and `'`.
  - Wrapped `escapeHtml(st.name)`, `escapeHtml(st.operator)`, `escapeHtml(st.area)`, and `encodeURIComponent(st.id)` in `src/components/MapLibreMap.tsx`.

### 2.2 Domain Types Alignment (`src/data/types.ts`)
- Updated `Connector`:
  - `powerKw: number | null` (preserving uninvented power as SQL/TypeScript `null`).
  - `total: number | null` (preserving unknown connector quantity as `null`).
  - `available: number | null` (preserving unknown connector availability as `null`).
  - `type: ConnectorType` includes `"Unknown"` to avoid fabricating `"CCS2"`.

### 2.3 Supabase Domain Adapter (`src/data/stationAdapter.ts`)
Created a standalone, pure mapping module with zero fabricating defaults:
- `normalizeConnectorType(raw)`: Maps variations and IEC standard strings (e.g. `62196-2` to `Type 2`, `62196-3` to `CCS2`, `J1772` to `Type 1`) to `ConnectorType`. If missing or unrecognized, returns `"Unknown"`, never `"CCS2"`.
- `deriveStationStatus(latestAvailabilityStatus, operationalStatus)`: Enforces priority of live telemetry observations. In the absence of telemetry, decommissioned or temporarily unavailable stations map to `"broken"`, while operational stations map to `"unknown"` (Rule 5).
- `derivePricing(row)`: Preserves missing rates as `pricePerKwh: null, isFree: null`. Only explicit 0 rates map to `isFree: true`.
- `deriveHours(row)`: Formats 24h, open-close, and unknown hours.
- `deriveArea(row)`: Uses `locality` -> `city` -> `state` -> `"Area unknown"`. Never presumes Mumbai.
- `deriveAddress(row)`: Composes explicit non-empty address fields (`address_line`, `locality`, `city`, `state`, `postal_code`, `country`). If empty, returns `"Address unavailable"`. Never synthesizes fake addresses.
- `mapDbConnectorToConnector(row, stationStatus)`:
  - Preserves `power_kw` as `null` when missing.
  - Preserves `total_quantity` as `null` when missing (never defaults to `1`).
  - Only populates `available` from `latest_available_connectors` observation. If missing, `available = null` (never defaults to total or 0).
- `mapDbStationToStation(row, connectors)`: Combines all attributes into a faithful `Station` entity with cold-start empty `busyWindows: []` and fallback operator `"Unknown Operator"` (never `"Independent"`).

### 2.4 Data Access Layer (`src/data/stations.ts`)
- Completely removed the 330-line dummy `seed` array containing 17 fabricated stations.
- Established `CANONICAL_STATIONS` based on the 8 live verified database stations in Mumbai.
- Exported `STATIONS = CANONICAL_STATIONS` for immediate synchronous backward compatibility.
- Implemented `fetchStations(): Promise<Station[]>` querying `v_station_current_state` and `v_station_connectors` concurrently.
- Implemented `fetchStationById(id: string): Promise<Station | null>` querying by station UUID.
- Reset `REVIEWS` to `[]` (0 fabricated reviews).
- Updated `getTotalChargers(s)` and `getAvailableChargers(s)` to return `number | null` without claiming unsupported counts.
- Updated `getMaxPowerKw(s)` to safely handle `c.powerKw ?? 0`.

### 2.5 UI Honesty Updates
- `src/components/StationCard.tsx`: Formatted max power to render `"—"` when power is unknown or 0. Formatted chargers to render `"—"` when unknown.
- `src/components/StationPreviewSheet.tsx`: Guarded charger count display when chargers is null.
- `src/app/station/[id]/StationDetail.tsx`: Rendered `"—"` when connector power is null. Handled null connector availability and null total count honestly using `t("station.availabilityUnavailable")`.
- `src/app/explore/ExploreClient.tsx`: Handled nullable `getTotalChargers` and `getAvailableChargers` safely.
- `src/app/station/[id]/page.tsx`: Updated `Page` to load live station data via `await fetchStationById(id)` with `notFound()` and dynamic route generation.

---

## 3. Verification & Quality Gates

### 3.1 Quality Gate Summary
| Quality Gate | Command | Result |
| :--- | :--- | :--- |
| **Station Adapter Unit Tests** | `node --experimental-strip-types tests/test_station_adapter.mjs` | **8 passed** (0 failures, 180ms) |
| **TypeScript Typecheck** | `npm run typecheck` (`tsc --noEmit`) | **Clean** (0 errors) |
| **ESLint** | `npm run lint` (`eslint .`) | **Clean** (0 errors) |
| **Next.js Production Build** | `npm run build` (`next build`) | **Compiled successfully** (18/18 routes generated) |
| **Python Regression Suite** | `python -m pytest tests/ -q` | **376 passed** (0 failures, 164.16s) |

---

## 4. Conclusion & Next Step

Step 3.1 is **fully audited, corrected, and verified complete**. No missing source attribute is converted into a factual value.

**Next Step:** Step 3.2 — Connect Explore/map.
