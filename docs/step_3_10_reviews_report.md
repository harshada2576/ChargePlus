# ChargePlus — Phase 3, Step 3.10: Connect Reviews — Implementation Report

## 1. Findings

- Reviews were localStorage-only; the detail page could never show real feedback and its date helper divided minutes by 60 for sub-hour values (removed as dead code with the old path).
- Backend ready: `public.reviews` with unique (user, station), pending-default moderation, RLS own-insert/update/delete + approved-public select; sanitized `v_station_approved_reviews` (no user ids, approved only); `avg_rating`/`review_count` already flow through the station view into the adapter.

## 2. Implementation

- `src/lib/reviews.ts` (new): `validateReview` (1–5 integer stars, UUID station, 500-char trim), `submitReview` (insert, then own-row update on 23505; success only after server confirmation), `listApprovedReviews` (sanitized view, anonymous-readable, nameless authors become "A driver"), `listOwnReviews` (with moderation status).
- `StationReviewForm`: real submit with guards; `station/[id]/page.tsx` fetches approved reviews server-side (review-fetch failure leaves the section empty, never blocks the record); `StationDetail` renders them with dates, keeps the empty state, and still gates the rating header on non-null.
- `ReviewsClient`: own reviews + canonical join (fixed hardcoded "Mumbai" fallback), pending chip, loading/error(retry)/empty states, encoded links.
- `ProfileClient`: server-truth review count (`—` when unknown).

## 3. Tests and verification (executed)

- New `tests/test_reviews.mjs`: **6/6 pass** (validation, insert-then-update semantics, no fake success, sanitized honest listing, own-status visibility).
- `typecheck`, `lint` clean.
- Live writes unverified (needs authenticated user; OTP dependency). RLS + view contract verified by migration inspection.

## 4. Security review

User id from session; ownership server-enforced (policies + unique constraint); no user ids or moderation internals reach the public feed; no client moderation writes possible (insert policy forces pending).

## 5. Next step

Step 3.11 — Connect alerts (server-persisted watch conditions).
