# ChargePlus — Phase 3, Step 3.6: Connect Auth/OTP — Implementation Report

> No passwords, no hardcoded codes, no fake sessions. Missing provider config
> surfaces honestly. Public browsing unchanged (anon client, no auth gates added).

## 1. Findings

- Login/Verify were fully mock: any 6-digit code signed in a `u-${Date.now()}` user
  persisted to localStorage; resend was a toast; sign-out only dropped the key while
  prototype stores leaked across users on shared devices.
- Backend ready: Supabase Auth is the provider; `public.profiles` insert-own policy
  allows first-login row creation; column grants block role self-escalation.

## 2. Implementation

- `src/lib/auth.ts` (new): `normalizePhone` (Indian E.164, 6–9 series),
  `normalizeEmail`, `normalizeContact`/`normalizeCode` (throw `AuthValidationError`),
  `sendOtp` / `verifyOtpCode` / `signOut` against an injectable `AuthClient`
  (provider errors mapped to safe capped messages, never tokens), `safeRedirect`
  (single-slash internal targets only).
- `SessionProvider`: user/session now come from `getSession` + `onAuthStateChange`
  (contact = email ?? phone); `ensureProfileRow` inserts the canonical profiles row
  on first sign-in; sign-out ends the server session and clears in-memory + stored
  prototype state; `signIn` mock and `AUTH_KEY` removed; `setMockRole` kept
  in-memory-only until Step 3.12 removes it.
- `LoginClient`: real `sendOtp`, normalized pending contact in sessionStorage,
  provider/validation errors rendered inline, duplicate-submit guard kept.
- `VerifyClient`: real `verifyOtpCode` (session auto-established, picked up by the
  provider listener), real resend with cooldown, submitting guard, subtitle uses the
  stored normalized contact (no doubled +91).
- Phone SMS delivery requires a dashboard SMS provider (externally dependent,
  reported, not simulated). Email OTP uses Supabase Auth email delivery.

## 3. Tests and verification (executed)

- New `tests/test_auth_otp.mjs`: **9/9 pass** (normalization, validation-first
  ordering, channel mapping, honest provider errors, null-user rejection,
  redirect safety, sign-out delegation).
- `typecheck`, `lint` clean (one `set-state-in-effect` found and fixed via
  queueMicrotask seeding).
- Live limits (documented, no synthetic users created): no OTP was sent (would
  create auth.users rows); `getSession` anonymous state + anon station reads to be
  re-verified in the final gate run; end-to-end delivery depends on dashboard
  provider/billing configuration.

## 4. Security review

No passwords introduced; no OTP/token logging; safe error messages; redirect target
closed to internal paths; role column still unwritable by clients (grants + RLS);
`setMockRole` explicitly in-memory-only and flagged for removal in Step 3.12.

## 5. Next step

Step 3.7 — Connect profiles (canonical profile read/update).
