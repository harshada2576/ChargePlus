# ChargePlus — Phase 3, Step 3.2: Connect Explore & Map — Implementation Report

> Phase 3 invariants hold: no invented stations, availability, prices, reviews, power,
> observations, or predictions. Unknown stays unknown (`null`/`Unknown`). Rule 5 enforced
> (static operational status is never live availability). No redesign, no auth changes,
> no schema changes, no backend proxy.

## 1. Initial findings (gaps found before editing)

1. `ExploreClient.tsx` rendered the old synchronous `STATIONS` array with a 350 ms simulated
   loading timer — no canonical fetch, no error state, no retry.
2. The in-progress working tree replaced it with a half-migrated component that did not
   compile: `useReducer` without import, `setLoading`/`setStations`/`setError` calls with no
   such state, and all UI state (`query`, `filters`, `sort`, `selectedId`, `userLoc`,
   `locating`, `locError`, `filtersOpen`, `sortOpen`, `searchInputRef`) deleted while still
   referenced. `tsc`/`eslint`/`build` all failed on this file.
3. `fetchStations()` / `fetchStationById()` took no client parameter, so the 12 required
   Explore/map tests (mock-client injection) could not run against them.
4. Old filter logic had two honesty bugs: `minChargers` used `(getTotalChargers(s) ?? 0)`
   (collapsing unknown to 0 instead of excluding), and `lessBusy` was a no-op
   (`busyWindows.length > 0 || length === 0`, always true).
5. `MapLibreMap` built GeoJSON from every station without coordinate validation and
   selected/initialized from unvalidated coords; popup `isFree` check (`st.isFree`,
   truthy) treated `null` loosely (rendered correctly only by accident).
6. Spec doc (`docs/step_3_2_connect_explore_map.md`) proposes an offline "static canonical
   fallback". That conflicts with the step requirement (never replace failed canonical data
   with hardcoded examples) and was NOT implemented: failures throw and render an honest
   error state. The static `CANONICAL_STATIONS` snapshot remains only as a typed
   reference for non-Explore surfaces (Saved/Alerts/Admin, later steps) and is unreachable
   from the Explore/map path.

## 2. Files changed and behavior implemented

- `src/data/stations.ts`
  - `fetchStations(client = supabase)` and `fetchStationById(id, client = supabase)` accept
    an injectable `StationDbClient` (minimal `{ from(table): ... }` surface). Production
    behavior unchanged (defaults to the public anon client). Both throw on query error —
    never fall back to `CANONICAL_STATIONS`. `distanceKm` returns `Infinity` for
    null/invalid inputs (missing coords fail finite-radius filters instead of crashing).
- `src/data/exploreQuery.ts` (new)
  - Single canonical query layer: `DEFAULT_EXPLORE_FILTERS`, `filterAndSortStations`
    (copies, never mutates), `mappableStations` / `toStationGeoJSON` (invalid coords
    omitted, never defaulted to a Mumbai coordinate), `resolveSelectedStation`
    (filtered-first, full-collection fallback so selection survives filtering),
    `stationDetailHref`, `exploreLoadState` (loading > error > empty > ready),
    `rankAvailability`, `isOpenNow`.
  - Explicit unknown-data policy: `availableOnly` matches `status === "available"` only;
    `freeOnly` matches `isFree === true` only; `maxPrice` excludes unknown prices;
    `minPowerKw`/`fastCharging` exclude unknown-only power; `minChargers` excludes
    unknown quantities; connector-type filter never matches `Unknown`; `openNow` excludes
    unknown hours; `lessBusy` requires non-empty `busyWindows` (cold start: no match).
- `src/app/explore/ExploreClient.tsx`
  - Loads `fetchStations()` on mount; `active` flag guards unmount/stale responses.
    Loading skeletons → error card with retry (`loadStations`, state reset in the event
    handler) → empty state → list. Error and empty are distinct states.
  - List and `MapLibreMap` both receive the same `filtered` collection; list click and
    marker click both set `selectedId`; `StationPreviewSheet` gets
    `resolveSelectedStation(selectedId, filtered, stations)`; deselect clears preview and
    popup. No visual redesign.
- `src/components/MapLibreMap.tsx`
  - GeoJSON via `toStationGeoJSON` (invalid coords never become markers); selection,
    single-station center, and recenter all guard with `isValidCoordinate`; popup keeps
    `escapeHtml` on name/operator/area, `encodeURIComponent` on id, `isFree === true`
    check. Marker/cluster layers, style, controls, and cleanup unchanged.
- `src/data/stationAdapter.ts` — `parseStationCoord` (null/""/garbage → `NaN`, never 0);
  coordinates flow through it. Nullable lat/lng in `DbStationRow`.
- `src/lib/util.ts` — `isValidCoordinate` (rejects non-numbers, NaN, (0,0), out-of-range).
- `src/app/station/[id]/page.tsx` — unchanged, verified: `fetchStationById` + `notFound()`.
- `tests/test_explore_map.mjs` (new, 13 tests), `tests/hooks.mjs` + `tests/register-hooks.mjs`
  (TS path-alias loader + dotenv so node tests import `src/*.ts` directly).

## 3. Data-flow explanation

Supabase views → `fetchStations` (anon client) → adapter (`mapDbStationToStation`,
Rule 5 + null-preserving) → `stations` state → `filterAndSortStations` (copy) →
`filtered` → `MapLibreMap stations={filtered}` + list + `resolveSelectedStation` →
`StationPreviewSheet` → `/station/[id]` via canonical id → `fetchStationById` →
`notFound()` when null. Map popup link uses `encodeURIComponent(st.id)`.

## 4. Tests and actual results

- `node --experimental-strip-types --import ./tests/register-hooks.mjs --test tests/test_station_adapter.mjs` → 9/9 pass.
- Same runner on `tests/test_explore_map.mjs` → 13/13 pass (covers all 12 required
  behaviors: canonical load, empty≠error, failure≠mock, retry, selection sync,
  invalid coords, unknown availability/price/type/quantity, no-mutation filtering,
  canonical-ID navigation, escaping; plus a live anon-client test).
- `npm run typecheck` → clean. `npm run lint` → clean (one `set-state-in-effect`
  violation found and fixed by moving the reset into the retry handler).
- `npm run build` → clean, all routes generated.
- `python -m pytest tests/ -q` → 376 passed.

## 5. Live-data verification results (public anon client, read-only)

- `fetchStations()` → 8 stations; leading IDs match the canonical snapshot
  (`2979dde1…`, `4ae2adf1…`, `862847e0…`); map/list derive from the same array by
  construction; `mappableStations`/`toStationGeoJSON` verified in tests.
- Honesty spot-check on live rows: 3 connectors with `powerKw: null`, all 5 with
  `available: null` — preserved, not zeroed or derived.
- Zero-row success → `exploreLoadState → "empty"` (test 2 + mock empty fetch).
- Forced query error → rejects with `fetchStations error: …`, no mock substitution
  (test 3); retry re-invokes the loader (test 4). No secrets printed; no writes made.

## 6. Security and data-honesty review

- Sole `innerHTML` (map popup) reviewed: every DB string escaped, id encoded, badge/price
  text derived from closed enums/numbers only. Test 12 pins `escapeHtml`.
- No fabricated coordinates, availability, prices, types, quantities, ratings, addresses,
  or hours. `MUMBAI_CENTER` is map-viewport default only, never assigned to a station.
- Public browsing unchanged (anon client, no auth gate on Explore/detail).

## 7. Git status

Branch `feature/step-3.2-connect-explore-map`. Step 3.2 changes committed and pushed;
working tree clean (verified via `git status --short`). Pre-existing untracked vendor
files (if any) left untouched.

## 8. Remaining risks and next step

- `CANONICAL_STATIONS`/`STATIONS`/`getStation` are still imported by Saved, Alerts, Admin,
  Reviews, Reports surfaces — out of scope here, to be wired in their own steps (3.6–3.12).
- `lessBusy`/`busyWindows` and ratings/reviews are cold-start empty until Steps 3.10/5.x;
  the filter honestly matches nothing today (documented, not guessed).
- Next: Step 3.3 — Connect search/filter.
