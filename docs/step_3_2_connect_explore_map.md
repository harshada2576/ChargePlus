# ChargePlus — Phase 3, Step 3.2: Connect Explore & Map Specification

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

## 1. Objective & Scope

The goal of Step 3.2 is to connect the Explore view (`src/app/explore/ExploreClient.tsx`) and the geospatial vector map (`src/components/MapLibreMap.tsx`) to authentic data loaded asynchronously from Supabase (`fetchStations()`), replacing synchronous static array references while maintaining full fidelity with the frozen UI/UX design.

### Key Objectives
1. **Async Data Loading**: Wire `ExploreClient` to invoke `fetchStations()` on mount, fetching canonical stations through `src/data/stationAdapter.ts` querying `public.v_station_current_state` and `public.v_station_connectors`.
2. **Resilient Lifecycle States**:
   - **Loading State**: Render existing `StationCardSkeleton` placeholders during data retrieval without UI flicker or layout shifts.
   - **Error State**: Gracefully catch fetch rejections (network timeout, offline status) with an honest retry action, falling back to static canonical fallback with clear status indication if offline.
   - **Empty State**: Provide honest empty-state feedback when zero stations match the selected filters or search queries.
3. **MapLibre Geospatial Integration**:
   - Render vector markers for all active stations with exact coordinates.
   - Maintain color hierarchy based on authentic derived status (`available`, `busy`, `broken`, `unknown`).
   - Retain MapLibre cluster grouping with dynamic count bubbles and zoom-to-cluster expansion.
   - Render sanitized popups using `escapeHtml()` with direct navigation to `/station/[id]`.
4. **Bi-directional Map & List Sync**:
   - Clicking a map marker opens the corresponding `StationPreviewSheet` or highlights the station card.
   - Selecting a station in the list pans the map smoothly to the station's coordinates.
5. **Geolocation & Distance Sorting**:
   - Browser geolocation retrieves user position (`lat`, `lng`).
   - Dynamic Haversine distance calculation (`distanceKm`) updates distance badges and nearest-first sorting.
6. **Data-Honest Filtering & Sorting**:
   - All filter predicates (`minPowerKw`, `fastCharging`, `availableOnly`, `freeOnly`, `maxPrice`, `minChargers`) strictly guard against `null` attributes and never treat `null` as 0 or available.

---

## 2. Architecture & Data Flow

```
┌────────────────────────────────────────────────────────┐
│                   Supabase Database                    │
│   (public.v_station_current_state & connectors views)  │
└───────────────────────────┬────────────────────────────┘
                            │ Public Anon Key
                            ▼
┌────────────────────────────────────────────────────────┐
│             src/data/stationAdapter.ts                 │
│   - Map DB rows to Station domain entities             │
│   - Enforce Rule 5 & Missing means Missing             │
│   - Null power, null quantity, null availability       │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│               src/data/stations.ts                     │
│   - fetchStations(): Promise<Station[]>                │
│   - CANONICAL_STATIONS fallback cache                  │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│          src/app/explore/ExploreClient.tsx             │
│   - State: stations, loading, error, query, filters    │
│   - Lifecycle: useEffect -> fetchStations()            │
│   - Memoized filtered & sorted station list            │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
               ▼                          ▼
┌───────────────────────────┐ ┌──────────────────────────┐
│src/components/MapLibreMap │ │ src/components/StationCard│
│ - Hardware-accel clusters │ │ - Distance badges        │
│ - Sanitized popup links   │ │ - Honest power & chargers│
│ - Bi-directional select   │ │ - StationPreviewSheet    │
└───────────────────────────┘ └──────────────────────────┘
```

---

## 3. Data-Honesty Rules for Explore & Map

1. **Status Honesty (Rule 5)**: Stations without genuine point-in-time telemetry observations must display the neutral gray status `#6B615E` (`unknown`). Operational equipment without live port status is NOT assumed to be available.
2. **Power Nullability**: When `powerKw` is `null`, filter `minPowerKw > 0` and `fastCharging` (>= 50 kW) must NOT match the connector; UI badges must display `"—"` rather than `0 kW`.
3. **Availability Nullability**: When connector `available` is `null`, `availableOnly` filter matches only stations with verified `status === "available"`. Stations with `status === "unknown"` are excluded when `availableOnly` is active.
4. **Price Transparency**: When `pricePerKwh` is `null`, the `freeOnly` filter does NOT match unless `isFree === true`.
5. **No Synthetic Geolocation**: If browser geolocation is denied or unavailable, distances are measured from the default canonical center (`MUMBAI_CENTER: 18.9690, 72.8210`) with explicit UI indicator, never pretending the user is located there.

---

## 4. Verification & Testing Strategy

| Test Area | Verification Method | Acceptance Gate |
| :--- | :--- | :--- |
| **Async Station Loading** | Unit & integration tests | `fetchStations()` called on mount; returns verified 8 stations |
| **Loading & Error States** | Component render inspection | Skeletons shown during fetch; error alert with retry button on failure |
| **Marker Rendering** | MapLibre layer inspection | 8 markers placed at exact DB lat/lng coordinates; clustering enabled |
| **Sanitized Popups** | HTML injection test | Names with special chars sanitized via `escapeHtml()`; links point to `/station/[id]` |
| **Filter Predicates** | Unit tests against null fields | Stations with unknown power or pricing correctly filtered without throwing |
| **TypeScript & Build** | `tsc --noEmit` & `next build` | 0 compiler errors; 0 lint errors; production build clean |

---

## 5. Next Steps

Upon switching to the feature branch `feature/step-3.2-connect-explore-map`:
1. Update `src/app/explore/ExploreClient.tsx` to add `stations` state, `loading` state, `error` state, and `fetchStations()` integration.
2. Ensure MapLibre marker selection and sheet preview open seamlessly with real station data.
3. Validate all filter sliders and checkboxes against live stations.
4. Run full test suite and build gates (`tsc`, `eslint`, `next build`, `pytest`).
