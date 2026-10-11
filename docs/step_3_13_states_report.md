# ChargePlus — Phase 3, Step 3.13: Loading/Empty/Error States — Implementation Report

## 1. Audit matrix (code-inspected against live behavior)

| Surface | Loading | Error + retry | Empty | Auth gate |
|---|---|---|---|---|
| Explore | skeletons | card + retry | no-results + clear | public |
| Station detail | server render | `error.tsx` + reset | — | public; 404 on no-match |
| Saved | skeletons | card + retry | empty CTA | AuthPrompt after `authReady` |
| Alerts | text | card + retry | empty CTA | AuthPrompt after `authReady` |
| Reports | text | card + retry | empty CTA | AuthPrompt after `authReady` |
| Reviews | text | card + retry | empty CTA | AuthPrompt after `authReady` |
| Profile | text | counts show "—" | sign-in card | sign-in card after `authReady` |
| Login/Verify | submitting guards | inline errors | n/a | n/a |
| Admin | text | inline error + reload | per-queue empties | 403 gate after `authReady` |
| Forms (report/review) | submitting guards | error states | n/a | auth prompt upstream |

## 2. Implementation

- `SessionProvider`: new `authReady` (initial session resolved). All gated surfaces render a loading state until ready, then the AuthPrompt/403 gate — no more logged-in flashes of logged-out UI.
- Known transient (documented, self-correcting): the canonical role overlay lands just after the session, so a real admin may briefly see the 403 gate before the console appears. No interaction needed; RLS remains the real boundary.
- No new unit tests: 3.13 adds no pure logic (JSX gates are not node-testable); coverage comes from the full suite rerun + live checks + this inspection matrix.

## 3. Verification (executed)

- Node suites **117/117**; `typecheck`, `lint`, `build` clean; `pytest` **376 passed**.
- Live anon (read-only): 8 stations load; 4th list record opens the identical detail record; absent id → null; forced failure throws distinctly from empty.

## 4. Next step

Phase 3 final end-to-end audit and closure decision.
