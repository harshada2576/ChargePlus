# ChargePlus — Phase 3, Step 3.1: Replace Hardcoded Station Dataset

> **Phase 3 Invariants & Principles**
> 1. Never invent stations, availability, prices, reviews, connector power, observations, queue estimates, or predictions.
> 2. Unknown values remain unknown: unknown connector power is SQL `NULL` and TypeScript `null`, never `0` or fabricated.
> 3. Static station operational status (`operational_status`) must never be represented as live connector availability (Rule 5).
> 4. Public station browsing must not require authentication.
> 5. The existing frontend visual design, tokens, typography, and layout are locked.
> 6. Do not introduce a FastAPI proxy: frontend queries Supabase directly via the public anonymous key.

---

## 1. Objective and Scope

The goal of Step 3.1 is to replace the prototype hardcoded in-memory station dataset (`seed` array in `src/data/stations.ts`) with authentic data sourced from Supabase views, without altering the locked UI design or introducing unvetted data proxies.

### Acceptance Criteria
- [x] Security Prerequisite: Fix MapLibre popup HTML-injection vulnerability before binding external database strings to markup.
- [x] Data Layer Modernization: Create pure domain adapter mapping `public.v_station_current_state` and `public.v_station_connectors` view rows to frontend domain models.
- [x] Honesty & Cold-Start Preservation:
  - Unknown connector power is preserved as `null`.
  - Static operational status without live observations maps to `status = "unknown"`, never `"available"`.
  - Unobserved pricing maps to `pricePerKwh: null, isFree: null`, never free or ₹0.
  - Reviews and busy windows start empty (`[]`), never fabricated.
- [x] Live Data Access Functions: Implement `fetchStations()` and `fetchStationById(id)` querying Supabase views via `@supabase/supabase-js`.
- [x] Station Route Integration: Connect `src/app/station/[id]/page.tsx` to `fetchStationById(id)` with `notFound()` and dynamic generation.
- [x] Backward Compatibility: Retain synchronous exports and utility functions (`distanceKm`, `formatDistance`, `getTotalChargers`, `getAvailableChargers`, `getMaxPowerKw`, `MUMBAI_CENTER`) so existing views remain stable.
- [x] Verification: Pass unit tests, Python regression suite (376 tests), TypeScript typecheck, ESLint, Next.js production build, and live Supabase queries.

---

## 2. Implementation Details

### 2.1 Security Hardening: MapLibre Popup HTML Sanitization
- **Vulnerability**: In `src/components/MapLibreMap.tsx`, station properties (`name`, `operator`, `area`) and `id` were directly interpolated into `popupNode.innerHTML` strings.
- **Remediation**:
  - Implemented `escapeHtml(str)` in `src/lib/util.ts` replacing `&`, `<`, `>`, `"`, and `'`.
  - Wrapped `escapeHtml(st.name)`, `escapeHtml(st.operator)`, `escapeHtml(st.area)`, and `encodeURIComponent(st.id)` in `src/components/MapLibreMap.tsx`.

### 2.2 Domain Types Alignment (`src/data/types.ts`)
- Updated `Connector.powerKw` from `number` to `number | null`.
- Preserves the Phase 2.12 invariant where 3 of 5 live connectors have `power_kw IS NULL`.

### 2.3 Supabase Domain Adapter (`src/data/stationAdapter.ts`)
Created a standalone, pure mapping module:
- `normalizeConnectorType(raw)`: Maps variations and IEC standard strings (e.g. `62196-2` to `Type 2`, `62196-3` to `CCS2`, `J1772` to `Type 1`) to the strict `ConnectorType` union.
- `deriveStationStatus(latestAvailabilityStatus, operationalStatus)`: Enforces priority of live telemetry observations. In the absence of telemetry, decommissioned or temporarily unavailable stations map to `"broken"`, while operational stations map to `"unknown"` (Rule 5).
- `derivePricing(row)`: Preserves missing rates as `pricePerKwh: null, isFree: null`. Only explicit 0 rates map to `isFree: true`.
- `deriveHours(row)`: Formats 24h, open-close, and unknown hours.
- `deriveArea(row)` & `deriveAddress(row)`: Safely compose geographic strings with standard fallbacks.
- `mapDbConnectorToConnector(row, stationStatus)`: Preserves `power_kw` as `null` when missing.
- `mapDbStationToStation(row, connectors)`: Combines all attributes into a faithful `Station` entity with cold-start empty `busyWindows: []`.

### 2.4 Data Access Layer (`src/data/stations.ts`)
- Completely removed the 330-line dummy `seed` array containing 17 fabricated stations.
- Established `CANONICAL_STATIONS` based on the 8 live verified database stations in Mumbai.
- Exported `STATIONS = CANONICAL_STATIONS` for immediate synchronous backward compatibility.
- Implemented `fetchStations(): Promise<Station[]>` querying `v_station_current_state` and `v_station_connectors` concurrently.
- Implemented `fetchStationById(id: string): Promise<Station | null>` querying by station UUID.
- Reset `REVIEWS` to `[]` (0 fabricated reviews).
- Updated `getMaxPowerKw(s)` to safely handle `c.powerKw ?? 0`.

### 2.5 UI Honesty Updates
- `src/components/StationCard.tsx`: Formatted max power to render `"—"` when power is unknown or 0.
- `src/components/StationPreviewSheet.tsx`: Formatted max power to render `"—"` when power is unknown or 0.
- `src/app/station/[id]/StationDetail.tsx`: Formatted individual connector power to render `"—"` when `powerKw` is null.
- `src/app/station/[id]/page.tsx`: Updated `Page` to load live station data via `await fetchStationById(id)` with `notFound()` and dynamic route generation.

---

## 3. Verification & Quality Gates

### 3.1 Quality Gate Summary
| Quality Gate | Command | Result |
| :--- | :--- | :--- |
| **Python Regression Suite** | `python -m pytest tests/ -q` | **376 passed** (0 failures, 173.93s) |
| **Station Adapter Unit Tests** | `node --experimental-strip-types tests/test_station_adapter.mjs` | **8 passed** (0 failures, 134ms) |
| **TypeScript Typecheck** | `npm run typecheck` (`tsc --noEmit`) | **Clean** (0 errors) |
| **ESLint** | `npm run lint` (`eslint .`) | **Clean** (0 errors) |
| **Next.js Production Build** | `npm run build` (`next build`) | **Compiled successfully** (18/18 routes generated) |
| **Live Database Verification** | Public anon client query script | **8 stations, 5 connectors verified** |

### 3.2 Live Database Query Verification
- Verified public unauthenticated queries against Supabase using `NEXT_PUBLIC_SUPABASE_ANON_KEY`:
  - `v_station_current_state`: Exactly 8 rows returned.
  - `v_station_connectors`: Exactly 5 rows returned.
  - Single station lookup by UUID returned exact record ("Tata Power Receiving Station").
  - Non-existent station UUID lookup returned `null` (fails closed).
  - Unknown connector power verified as `null` in 3 connector records.
  - Zero fabricated availability observations or synthetic pricing detected.

---

## 4. Conclusion & Next Step

Step 3.1 is **fully complete, verified, and locked**. The frontend data layer is now bound to the real canonical database baseline without mock data or fabricated attributes.

**Next Step:** Step 3.2 — Connect Explore/map.
