# ChargePlus — Phase 3, Step 3.4: Connect Station Detail — Implementation Report

> Phase 3 invariants hold: no invented facts; unknown stays unknown; locked design
> preserved; no auth/schema changes; no Step 3.5 work.

## 1. Field-to-source mapping (code-inspected against adapter + detail)

| Detail section | Source field(s) | Missing-data rendering |
|---|---|---|
| Name / operator / area | `name`, `operator_name` → "Unknown Operator", locality/city/state → "Area unknown" | Honest fallbacks; Mumbai never presumed |
| Address block | `address_line/locality/city/state/postal_code/country` → joined or "Address unavailable" | Name never synthesized into address |
| Rating header | `avg_rating` → null hides block; `review_count` → 0 | No fabricated counts |
| Mini-map + Navigate CTA/buttons/sheet | `latitude/longitude` via `isValidCoordinate` | Invalid coords omit map + all navigation; text stays |
| Charging-now + per-connector status | `latest_availability_status` (Rule 5) + connector `latest_available_connectors` | Unknown → `availabilityUnavailable`; never inferred |
| Freshness line | `minutes_since_observation` → null hides recency | No fake timestamps |
| Connector rows | `connector_type` → `Unknown`; `power_kw`/`total_quantity` → null shown as "—"/unavailable | No default-1, no 0 kW, no invented type |
| Price | `min_price_per_kwh` → null or value; `isFree === true` only when price is 0 | Unknown → `priceUnavailable`; never ₹0/free |
| Hours | `is_24_hours/opening_time/closing_time` → 24h / open–close / `hoursUnavailable` | Unknown never 24/7; device-local tz limitation documented |
| Busy windows | none (cold start `[]`) | `usuallyBusy.empty` text |
| Reviews | `getReviewsForStation` → `[]` (cold start) | `reviews.empty` text; session-local drafts never shown as canonical |
| Save/report/review/alert | localStorage prototype behind auth prompt (Steps 3.6–3.11 scope) | Explicit, not presented as persisted |
| Phone/website | adapter carries them; detail renders no phone/website links | Nothing to audit |

## 2. Files changed and behavior implemented

- `src/data/stations.ts` — `fetchStationById` returns null for malformed UUIDs without
  querying (PostgREST would reject the literal); genuine failures still throw.
- `src/app/station/[id]/error.tsx` (new) — route error boundary: design-consistent
  error card + `reset()` retry for query failures. `page.tsx` unchanged (throws →
  boundary; null → `notFound()`), giving three distinct outcomes: record / 404 / error.
- `src/app/station/[id]/StationDetail.tsx` — navigation + mini-map gated on valid
  coords; `isFree === true` consistency; review-button label fixed (`common.save` →
  `station.review.submit`); `formatMinutesAgo` arithmetic fixed (`min<60` showed
  `min/60`); unused `REVIEWS` import removed.
- `src/lib/util.ts` — `externalMapUrl` pure helper (null on invalid coords, https/geo
  only, encoded name); `openExternalMap` no-ops on null.
- `tests/test_station_detail.mjs` (new) — 18 tests covering all 17 required behaviors.

## 3. Loading, error, and not-found behavior

Valid UUID + row → record. Well-formed-but-absent or malformed UUID → null →
`notFound()`. Throwing loader → `error.tsx` + retry. `generateStaticParams` +
`force-dynamic` unchanged; public browsing intact (anon client, no auth gate).

## 4. Actions and navigation audit (code-inspected)

Back → `/explore`. Directions only with valid coords (guarded builder, `noopener/
noreferrer`, numbers + encoded name). Save/report/review/alert: auth-prompt-gated
localStorage prototypes, unchanged, documented for Steps 3.6–3.11; review form writes
session-only drafts never rendered as station reviews. No connector-selection,
phone, or website actions exist. Canonical UUID preserved route → loader → forms.

## 5. Tests and actual results (executed, not inferred)

- New `test_station_detail.mjs`: **18/18 pass** (17 required + malformed-no-query).
- Rerun suites: adapter + explore_map + search_filter **43/43 pass**. Node total: 61.
- `typecheck`, `lint`, `build` clean. `pytest`: **376 passed**.
- Live anon (read-only): known UUID loads with null power preserved; absent UUID →
  null; malformed UUID → null with zero client calls (mock-proven); no writes made.

## 6. Security and data-honesty review

Diff-scanned: no new `innerHTML`, no `STATIONS`/`getStation`/mock refs, no invented
defaults, popup escaping untouched, RLS/anon model intact, no secrets printed.
`geo:`/`https:` URLs use validated numbers + encoded name only.

## 7. Remaining risks and next step

- `error.tsx` retry re-runs the loader; persistent outages still surface the card —
  correct, not a silent 404.
- Session-prototype actions (save/report/review/alert) remain local-only until their
  steps; copy does not claim persistence.
- Next: Step 3.5 — Connect navigation handoff.
