# ChargePlus — Phase 3, Step 3.3: Connect Search & Filters — Implementation Report

> Phase 3 invariants hold: no invented stations, availability, prices, counts, types,
> reviews, ratings, hours, or predictions. Unknown stays unknown. No redesign, no auth
> changes, no schema changes. Step 3.4 not started.

## 1. Step-count discrepancy (resolved)

`Memory.md`/`Phases.md` claimed "10 remaining steps (3.3–3.13)". The authoritative
roadmap defines Steps 3.1–3.13, so after Step 3.2 the remainder is **11 steps
(3.3–3.13)**. Corrected the arithmetic in both files; the roadmap itself is untouched.

## 2. Searchable fields and filter semantics

- **Searchable fields** (`filterAndSortStations`, all adapter-guaranteed strings, never
  null): `name`, `operator` ("Unknown Operator" fallback is searchable text, not an
  invented business), `area` ("Area unknown" fallback), `address` ("Address unavailable"
  fallback). Case-insensitive substring (`toLowerCase().includes`), trimmed; empty query
  returns the full collection; no synthetic aliases; no matching against serialized
  internals (only the four display fields are read).
- **Connector type**: normalized vocabulary (`CCS2/CCS1/CHAdeMO/Type 2/Type 1/
  Bharat AC001/Unknown`); station-level `some()` match preserved; `Unknown` never equals
  a specific type, so selecting e.g. CCS2 excludes unknown-type stations. Panel offers no
  "Unknown" chip (correct: unknown is absence of knowledge, not a selectable product).
- **Power/fast charging**: threshold over `getMaxPowerKw` (max across connectors —
  existing product rule: any-connector). Null power contributes 0 and therefore fails any
  positive threshold; never classified fast. Threshold 0 disables the filter.
- **Connector count**: `getTotalChargers` null (unknown) excluded from positive
  thresholds; zero-connector stations are known-zero (match only filter-off). No
  `?? 0`, no default-1.
- **Availability**: `availableOnly` matches `status === "available"` only (requires real
  telemetry via Rule 5); connector-level `available` never inferred from station status.
- **Price**: `freeOnly` matches `isFree === true` only; `maxPrice` excludes unknown
  prices (cannot prove under cap); explicit ₹0 matches both.
- **Open now**: `24h` always open; `open-close` evaluated against device-local time
  (station-local timezone **not modeled** — documented limitation); `unknown` never
  open. Overnight intervals supported.
- **Distance**: radius requires `userLoc`; invalid coords yield `Infinity` (fail finite
  radius, sort last in nearest-sort via `Infinity - finite = +Infinity`; `NaN`
  comparator results keep stable order, no crash). No default station location.
- **Operator**: no operator filter exists in the locked UI; operator text is searchable.
  Unchanged by design.
- **Ratings/reviews/congestion/queue**: no canonical evidence at cold start
  (`busyWindows []`, `rating null`). `lessBusy` honestly matches nothing; UI retained
  per locked design. `recommended` sort ranks availability then rating (null → 0).

## 3. Files changed and behavior implemented

- `src/data/exploreQuery.ts` — documented minChargers known-zero-vs-unknown and
  connector-type exclusion semantics, timezone limitation; added `visibleSelection`
  (pure derivation: visible id or null when filtered out).
- `src/app/explore/ExploreClient.tsx` — list highlight, map `selectedId`, and preview
  now use `visibleSelectedId`: filtering/searching a station out clears its highlight,
  popup, and sheet predictably; raw `selectedId` retained so reset restores selection
  without refetch. Counts (`filtered.length`), chips, reset (defaults + query clear,
  no refetch), and client-side-only filtering (no per-keystroke network) unchanged.
- `src/components/MapLibreMap.tsx` — popup removed (not left stale) when the selected
  station is absent from the current stations prop or has invalid coords.
- `src/components/FiltersPanel.tsx` — `reset()` uses canonical
  `DEFAULT_EXPLORE_FILTERS` (was an inline duplicate); removed dead `syncOpen`
  (BottomSheet unmounts on close, so draft re-initializes from `value` on reopen).
- `Must Read/Memory.md`, `Must Read/Phases.md` — step-count fix only (this step's
  completion entries follow the workflow below).
- `tests/test_search_filter.mjs` (new) — 21 focused tests covering all 20 required
  behaviors plus cold-start filter evidence.

## 4. Data flow and state management

Unchanged Step 3.2 pipeline: Supabase views → adapter → `stations` state →
`filterAndSortStations(stations, { query, filters, sort, userLoc })` (copy, memoized)
→ `filtered` → map + list + counts + `visibleSelection` → preview → canonical detail.
Search/filters/sort never mutate `stations` or `DEFAULT_EXPLORE_FILTERS`; retry/unmount
handling untouched; error/empty/ready states preserved (zero-result filter ≠ db error).

## 5. Tests and actual results

- New `tests/test_search_filter.mjs`: **21/21 pass** (case-insensitive, trim/empty,
  partial name/operator/location, sparse fields, composition, Unknown-type exclusion,
  null power, null quantity vs known zero, telemetry-only availability, unknown≠free,
  unknown-hours exclusion + overnight intervals, invalid-coord distance/sort,
  deterministic stable ties, non-mutation, counts, map/list id consistency, selection
  clear/restore, default reset, empty≠failure + reject-on-error, closed-world
  no-fabrication, cold-start `lessBusy`).
- Existing suites rerun: adapter + explore_map **22/22 pass**.
- `npm run typecheck`, `npm run lint`, `npm run build` — clean.
- `python -m pytest tests/ -q` — **376 passed**.
- Live anon check (read-only): 8 stations load; query `"tata"` matches 1; every
  filtered id exists in the loaded set.

## 6. Security and data-honesty review

- Final diff scanned: no new `innerHTML`, no `any`, no `STATIONS`/mock references, no
  invented locations, no `?? 0`/default-1 substitutions, no popup-escaping regression
  (popup code untouched). Anon public browsing intact; no auth/schema/backend changes.
- Stale sync access (`STATIONS`/`getStation`) remains only in Admin/Alerts/Reviews/
  Saved/Reports — out of scope for their own steps, unreachable from Explore.

## 7. Remaining risks and next step

- `isOpenNow` uses device-local timezone; travelers across zones may see shifted
  open/closed judgments for `open-close` stations. No station timezone data exists to
  do better; documented, not guessed.
- `lessBusy` toggle is a documented no-op until temporal evidence arrives (Step 5.x).
- Recommendation card still claims `matchConnector`/`lessBusyNow` reasons without
  per-connector evidence — pre-existing Step 3.2 UI, untouched; flag for review step.
- Next: Step 3.4 — Connect station detail.
