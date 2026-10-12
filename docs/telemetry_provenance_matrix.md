# ChargePlus — Telemetry Sources, Provenance & Provider Capability Matrix

**Document Version**: 1.0.0  
**Phase**: Phase 2 / Honest Telemetry & Data Provenance  
**Date**: October 12, 2026  

---

## 1. Authoritative Source Categories

ChargePlus enforces five explicit, non-overlapping source categories across all data ingestion pipelines, warehouse tables, and presentation layers:

| Source Category | Code Enum | Definition & Criteria | Freshness Expectation | UI Presentation |
| :--- | :--- | :--- | :--- | :--- |
| **Verified Live Provider** | `verified_live` | Direct, authenticated API or webhook integration from authorized Charge Point Operators (CPO via OCPI 2.2.1 or OICP 2.3) or verified live telemetry feeds. | Fresh window: $\le 30$ min. Aging: $30\text{--}120$ min. | Green pill badge: **Verified Live Feed** |
| **Actual Recent Observation** | `recent_observation` | Direct operational observation recorded within the operational freshness threshold (e.g., driver community report or recent aggregator poll). | Fresh window: $\le 60$ min. Aging: $60\text{--}120$ min. | Slate pill badge: **Recent Observation** |
| **Historical Observation / Aggregate** | `historical` | Observation or aggregate whose timestamp exceeds the stale threshold ($> 120$ min) or originates from daily warehouse rollups. | Stale: $> 120$ min. Valid historical evidence only. | Gray pill badge: **Historical Record** (Never claimed as live) |
| **Simulated / Demo Data** | `simulated` | Version-controlled synthetic telemetry or fixture dataset used strictly for offline demonstrations, local development, or unit testing. | Synthetic timestamp curve. | Warning/Amber badge: **Simulated Demo Data** |
| **Unknown / Unavailable** | `unknown` | Static station record with no telemetry observations, missing timestamps, or unverified operational state. | Timestamp null or unresolvable. | Neutral badge: **Status Unknown** |

---

## 2. Invariants & Freshness Decay Policy

### Core Invariants:
1. **Rule 5 / Static $\ne$ Live Availability**: A static station record having `operational_status = 'operational'` merely confirms physical existence. It **never** implies that chargers are currently available or unoccupied.
2. **STALE $\ne$ UNAVAILABLE**: An aging or stale observation remains valid historical evidence of what happened at that time. It is **never** coerced to `"unavailable"` or `"broken"` solely because time has elapsed.
3. **Observation Time $\ne$ Ingestion Time**:
   - `observed_at`: The precise instant when reality occurred at the physical connector.
   - `received_at`: The instant when ChargePlus ingested and persisted the record.
   - Freshness evaluation is strictly evaluated against `observed_at`.
4. **No Synthetic Promotion**: Synthetic demo records and test fixtures are cryptographically and contextually isolated. They cannot be merged or promoted into production tables.
5. **Fail-Closed on Expired Telemetry**: If telemetry age exceeds the configured stale threshold (120 minutes), the live status indicator resolves to `unknown` rather than projecting false availability.

---

## 3. Provider Capability Matrix

| Provider / Feed | Protocol / Standard | Implemented | Conformance Tested | Configured Credentials | Verified Live Data | Current Operational Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **OpenChargeMap (OCM)** | REST API v3 (JSON) | ✅ Yes | ✅ Yes (18 fixtures) | ✅ Yes (`OPENCHARGEMAP_API_KEY`) | ✅ Yes (8 Mumbai hubs) | **ACTIVE**: Primary production bootstrap feed. |
| **OpenStreetMap (OSM)** | Overpass QL / Overpass API | ✅ Yes | ✅ Yes (Unit suite) | None needed (Public Overpass mirror) | ⚠️ Supervised dry-run | **MANUAL / DRY-RUN**: Guarded against automated cron until MMR bounding box audited. |
| **data.gov.in (OGD)** | REST API (OGD Platform) | ✅ Yes | ✅ Yes (Unit suite) | ⚠️ Key set, Resource ID pending | ❌ Fails closed | **BLOCKED ON RESOURCE ID**: Requires verified Ministry of Heavy Industries dataset ID. |
| **Tata Power EV Charging** | OCPI 2.2.1 Locations | ✅ Yes | ✅ Yes (Simulator) | ❌ Awaiting bilateral keys | ❌ None | **NOT_CONFIGURED**: Production ready, awaiting CPO commercial onboarding. |
| **Jio-bp pulse** | OCPI 2.2.1 Locations | ✅ Yes | ✅ Yes (Simulator) | ❌ Awaiting bilateral keys | ❌ None | **NOT_CONFIGURED**: Production ready, awaiting CPO commercial onboarding. |
| **Hubject Intercharge** | OICP 2.3 PullEVSEData | ✅ Yes | ✅ Yes (Simulator) | ❌ Awaiting roaming contract | ❌ None | **NOT_CONFIGURED**: Production ready, awaiting roaming contract credentials. |
| **Community Driver Reports** | Authenticated PostGIS reports | ✅ Yes | ✅ Yes (App suite) | ✅ Yes (Supabase Auth RLS) | ✅ Verified (Driver submitted) | **ACTIVE**: Moderated via Admin Console. |

---

## 4. Observable Failure Handling

When external provider integrations encounter timeouts, HTTP 4xx/5xx responses, or missing credentials:
1. **Station Discovery Resiliency**: Discovery (`fetchStations`, `/explore`) never crashes. Missing provider telemetry leaves stations in their known static state with `status = "unknown"`.
2. **Accounting & Logging**: Ingestion failures increment `error_count` in `public.ingestion_runs` with structured JSON diagnostic logs (scrubbing all secrets, tokens, and query strings).
3. **No Silent Swallowing**: Critical failures raise observable errors to monitoring (`serverLog`) and exit non-zero in CLI runners.
