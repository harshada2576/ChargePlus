# CPO Partner Integrations — Protocols, Scope & Activation

Code: `backend/cpo/{partners,ocpi,oicp,sync,simulator,cli}.py`.
Tests: `tests/test_cpo_{ocpi,oicp,sync}.py` (isolated simulator; offline).

## Protocol scope (pinned)

OCPI and OICP are **not** interchangeable:

| | OCPI 2.2.1 | OICP 2.3 (eRoaming subset) |
|---|---|---|
| Style | Peer-to-peer REST (CPO ↔ platform) | Roaming-hub SOAP (Hubject) |
| Implemented | Versions negotiation (2.2.1 required), credentials-handshake builders, Locations pull (incremental `date_from`, offset/limit + Link pagination), Location→canonical mapping incl. live EVSE-status observations, tariff mapping helper | PullEVSEData request builder + response parser, EVSE→canonical mapping incl. status observations |
| Out of scope | Commands, Sessions, CDRs, Tokens, SmartCharging (need partner contracts) | Authorization, sessions/CDRs, push services, payments (need partner contracts) |
| Auth | `Authorization: Token <token>` (env only) | `Authorization: Bearer <token>` + partner TLS specifics at onboarding |

Unsupported OCPI versions are refused, not downgraded. Complex tariffs stay
`UNKNOWN` pricing — a missing price is never free and a composite tariff is
never reduced to a guessed number.

## Canonical data rules

- One adapter instance per partner+environment; `source_id` embeds both
  (`ocpi:<partner>:<env>`), so sandbox and production provenance never mix.
- Partner isolation: records outside the configured country/party/operator
  scope fail at record level; one partner's records never enter another's scope.
- Live partner status becomes genuine `station_observations`; static fields
  stay static. `publish=false` locations are skipped, never ingested.
- Out-of-order/replayed records are dropped by per-location cursors; reruns
  are idempotent; interrupted syncs resume from persisted `SyncState`.
- Audit rows land in `public.ingestion_runs` under the partner source_id;
  unexpected zero-result pulls warn instead of silently passing.

## Partner status

| Partner | Protocol | Sandbox | Production | Blocker |
|---|---|---|---|---|
| *(none onboarded)* | — | `NOT_CONFIGURED` | `NOT_CONFIGURED` | bilateral agreement + issued credentials per partner |

No partner is configured, no sandbox exchange has run, and nothing is marked
verified. Simulator tests prove adapter logic only.

## Activation checklist (per partner+environment)

Local (`backend/cpo/cli.py status` shows local state; secrets never printed):

1. `agreement` (external): bilateral business/roaming agreement signed.
2. `protocol_scope` (local): fixed scope above — done in code.
3. `sandbox_credentials` (external): partner issues sandbox endpoint + token.
4. `sandbox_config` (local): set `<PREFIX>_ENDPOINT/_TOKEN`
   (`_TOKEN_EXPIRES_AT`, `_COUNTRY_CODE`, `_PARTY_ID` recommended) →
   `SANDBOX_READY`. Prefix default: `{PROTOCOL}_{PARTNER}_{ENV}`.
5. `sandbox_exchange` (joint): authorized sandbox pull with recorded evidence
   → operator records `SANDBOX_VERIFIED`.
6. `conformance` (external): partner certification where required →
   `AWAITING_APPROVAL`.
7. `production_credentials` (external): **separate** production endpoint +
   token (never reuse sandbox) → `PRODUCTION_READY`.
8. `production_exchange` (joint): authorized production pull with recorded
   evidence → `PRODUCTION_VERIFIED`.

```bash
python -m backend.cpo.cli --partner simco --protocol ocpi --env sandbox status
python -m backend.cpo.cli --partner simco --protocol ocpi --env sandbox sync --dry-run
python -m backend.cpo.cli --partner simco --protocol ocpi --env production sync --live --state-path ./state/simco-prod.json
```

`sync` is dry-run by default; `--live` requires `DATABASE_URL` and usable
credentials, and refuses `NOT_CONFIGURED`/expired setups without touching
anything. Syncs are manual until a partner reaches `SANDBOX_VERIFIED`; no
cron schedule exists for partners.
