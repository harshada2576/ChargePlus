# ChargePlus — Phase 3, Step 3.5: Connect Navigation Handoff — Implementation Report

> Invariants hold: canonical IDs only (never names/indexes/labels as identity); no
> fabricated records; no mock fallbacks; locked design preserved; no schema changes;
> no Step 3.6 work.

## 1. Route inventory and navigation behavior (code-inspected)

- Journey: Explore list (`setSelectedId`) / map marker (`onSelect` → same id) →
  `StationPreviewSheet` (`visibleSelectedId`) → `stationDetailHref(id)` →
  `/station/[id]` (`fetchStationById` → record / `notFound()` / `error.tsx`) →
  back Link `/explore`. No station object is ever serialized into a URL.
- Primary links audited: BottomNav (`/`, `/explore`, `/saved`, `/alerts`, `/profile`),
  header (`/explore`, `/saved`, `/alerts`), footer (`/explore`, `/about`, `/help`,
  `/contact`, `/privacy`, `/terms`), profile rows, auth flows
  (`/login` ↔ `/verify?kind=` closed union ↔ `/profile`), `/search` →
  `/explore?focus=search` redirect (consumed by ExploreClient). Admin `href="/"`
  links are intentional ("Return/Exit to Driver App"). No dead links found.
- Return behavior: detail back is a plain Link to `/explore` (natural browser
  history preserved; Explore remounts with default filters — intentional reset,
  filter restoration not promised or implemented).
- Preview close (`onClose` → `setSelectedId(null)`) clears selection; map popup is
  removed on deselect; switching stations replaces identity (single `onSelect` path,
  no duplicate callbacks — inner card Links bubble one selection + one navigation,
  harmless across unmount).
- Prototype actions (save/report/review/alert) stay auth-gated and local-only for
  Steps 3.6–3.11; review/report success toasts are acknowledged as optimistic and
  left for those steps (no copy changes without locale coverage).

## 2. Files changed and behavior implemented

- `src/data/exploreQuery.ts` — `stationDetailHref` now encodes IDs
  (`/station/${encodeURIComponent(id)}`; identity for UUIDs).
- `src/components/StationCard.tsx`, `StationPreviewSheet.tsx` — detail links use
  the helper instead of raw template interpolation.
- `src/data/navigation.ts` (new) — single source of truth for bottom/header hrefs.
- `src/components/BottomNav.tsx`, `SiteHeader.tsx` — consume it (icons attached
  locally); rendered output identical.
- `tests/test_navigation.mjs` (new) — 15 tests incl. a real filesystem route
  inventory (walks `src/app`, asserts every primary href resolves to a `page.tsx`,
  dynamic `[id]` aware).

## 3. Canonical station-ID flow (test-proven)

List-click id and marker-click id resolve to the same preview record; preview href
carries the exact canonical UUID; loader round-trip preserves it; live check:
list first id → detail match `true`, missing UUID → null. Malformed IDs → null
(Step 3.4 guard); failures throw (never fabricated).

## 4. Accessibility and URL-safety audit (code-inspected)

Links share one encoding helper; map popup already encodes; external map URLs use
validated numbers + encoded names over https/geo only; `verify?kind=` is a closed
union (no open redirect); no privileged Supabase access in navigation. Known
limitation left untouched: Explore list nests Links inside the selection `<button>`
— restructuring risks redesign; handoff verified working and keyboard-operable
(outer button focuses/activates; inner links tab-reachable).

## 5. Tests and actual results (executed)

New suite **15/15**; existing suites **61/61** (node total 76); `typecheck`, `lint`,
`build` clean; `pytest` **376 passed**.

## 6. Live-data verification (anon, read-only, executed)

8 stations load; first list id → same detail record; href correct; nonexistent id →
null; zero writes; no secrets printed.

## 7. Remaining risks and next step

- Nested interactive card structure (above) deferred deliberately.
- Prototype success toasts precede server persistence (Steps 3.9–3.11).
- Return-to-Explore resets filters by design (no restoration promised).
- Next: Step 3.6 — Connect auth/OTP.
