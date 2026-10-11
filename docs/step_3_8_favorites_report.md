# ChargePlus — Phase 3, Step 3.8: Connect Favorites — Implementation Report

## 1. Findings

- Saves were localStorage-only (`chargeplus:saved`), invisible across devices and
  leaking across users after the real-auth switch.
- Backend ready: `public.favorites(user_id, station_id)` PK blocks duplicates; RLS
  own-select/insert/delete on `auth.uid()`.

## 2. Implementation

- `src/lib/favorites.ts` (new): `listFavorites` (empty ≠ error), `addFavorite`
  (unique-violation → idempotent success), `removeFavorite` (all scoped to the
  session user id; RLS independently enforces ownership server-side).
- `SessionProvider`: `savedIds` now server-loaded on auth and cleared on sign-out;
  `toggleSaved` is async and returns `saved | removed | login-required | error`;
  localStorage saves removed entirely.
- `StationCard` / `StationPreviewSheet`: unauthenticated taps route to `/login`;
  server errors toast honestly; success behavior unchanged (no new toasts).
- `StationDetail.handleSave`: keeps the auth-prompt modal for logged-out users,
  handles the async result with honest error toast.
- `SavedClient`: joins server ids against `fetchStations()` with loading skeletons,
  error card + retry, and empty state; saved ids without canonical records are
  omitted, never fabricated.

## 3. Tests and verification (executed)

- New `tests/test_favorites.mjs`: **5/5 pass** (ordering/empty, throw-on-error,
  write scoping, duplicate idempotency, scoped remove).
- `typecheck`, `lint` clean (one null-narrowing fix).
- Live writes unverified (needs authenticated user; same OTP dependency as 3.6).
  RLS ownership verified by policy inspection.

## 4. Security review

Writes carry the session user id but authorization is server-side (`auth.uid()`
policies + PK); no client role/ownership trusted; sign-out clears all favorite
state (no cross-user leak on shared devices).

## 5. Next step

Step 3.9 — Connect reports (server-persisted user_reports).
