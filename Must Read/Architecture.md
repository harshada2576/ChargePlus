# Architecture.md — System Architecture & Interface Contract
### ChargePlus — EV Charging Discovery, Intelligence & Community Platform
**Status: LOCKED — architecture, core entities, data boundaries, and interface contracts must not drift without explicit project approval.**

## 0. How to use this document

This is the shared technical brain for ChargePlus. Every AI coding session must use this file together with PRD.md, Rules.md, Phases.md, Design.md, and Memory.md.

Before coding:
1. Read the relevant sections of this folder.
2. Do not silently change the stack, core entity model, API/data contract, or product scope.
3. If a proposed change affects architecture or a locked contract, stop and surface the change before implementing it.
4. Prefer the simplest architecture that can become a real hosted product. Do not add infrastructure merely to make the diagram look sophisticated.

## 1. Problem framing

ChargePlus helps EV drivers find compatible charging stations, understand whether a station is likely to be usable, compare practical options, and reach the right charger before arriving at a queue.

The initial product focus is Mumbai, while the data model and architecture must be India-ready.

The system combines:
- public station discovery
- connector and charging information
- freshness-aware status
- user reports and reviews
- saved stations and alerts
- historical analytics
- demand/busy-time intelligence
- explainable station recommendations

## 2. High-level system

```text
                    ┌──────────────────────────────┐
                    │        Next.js Frontend      │
                    │       TypeScript / UI        │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────┴───────────────┐
                    │            Supabase           │
                    │ Auth + PostgreSQL + PostGIS  │
                    │ RLS + Storage where needed   │
                    └──────────────┬───────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
   Operational data         Analytics warehouse       User data
   stations/connectors      dimensions/facts          reports/reviews
          │                        │                        │
          └────────────────────────┬────────────────────────┘
                                   │
                         Python Data/ML Layer
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
      Ingestion              Validation/Dedup          Analytics/ML
          │                        │                        │
   External sources          canonical station data   forecasts/recs
```

## 3. Core architectural principles

### 3.1 One physical station, many connectors

A station is a physical location. Connectors/chargers belong underneath it.

```text
Station
 ├── Connector 1: CCS2, 120 kW
 ├── Connector 2: CCS2, 120 kW
 └── Connector 3: Type 2, 22 kW
```

Never model every connector as a separate station.

### 3.2 Operational truth vs analytical intelligence

Operational data describes what is known about the station.

Analytical/ML data describes patterns inferred from historical or current evidence.

Always distinguish:
- operational status
- observed status
- predicted/estimated busy state
- data freshness

Never present an inference as a confirmed real-time fact.

### 3.3 Provenance without exposing technical details to drivers

Internally preserve:
- source
- source record identifier
- retrieved time
- observed time
- validation state
- freshness
- confidence where applicable

The normal driver-facing station page does not need to expose technical source metadata.

### 3.4 No synthetic production data

Synthetic data may be used for:
- tests
- UI development
- load testing
- pipeline development
- ML experimentation

Synthetic data must never silently become public station information or production analytics.

### 3.5 Mumbai first, India ready

The initial operational coverage is Mumbai. Tables must not contain Mumbai-specific assumptions that prevent expansion to other Indian cities/states.

## 4. Technology choices

| Layer | Choice | Rule |
|---|---|---|
| Frontend | Next.js + TypeScript | Mobile-first responsive web |
| UI | Existing locked ChargePlus frontend | Do not redesign core UX |
| Database | Supabase PostgreSQL | Primary operational and analytics database initially |
| Spatial data | PostGIS | Nearby station search |
| Auth | Supabase Auth | Phone/email OTP; no passwords |
| Backend logic | Python | Ingestion, ETL, validation, analytics, ML |
| API/backend service | FastAPI only where needed | Do not insert a needless API between frontend and Supabase |
| Maps | MapLibre + production-appropriate OSM-derived tiles | No Google Maps dependency |
| Data/ML | Python | pandas/numpy/scikit-learn and simple tools as justified |
| Hosting | Choose low/zero-cost suitable services | Deployment must be real-user capable |
| Version control | GitHub | Single source repository |

## 5. Repository structure

```text
ChargePlus/
├── README.md
├── .env.example
├── package.json
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── hooks/
│   ├── data/
│   └── types/
├── backend/
│   ├── ingestion/
│   ├── validation/
│   ├── deduplication/
│   ├── analytics/
│   ├── ml/
│   └── common/
├── supabase/
│   ├── migrations/
│   ├── functions/
│   └── seed/
├── sql/
│   ├── analytics/
│   └── views/
├── tests/
├── scripts/
└── Must-Read/
    ├── Architecture.md
    ├── PRD.md
    ├── Rules.md
    ├── Phases.md
    ├── Design.md
    └── Memory.md
```

The existing frontend may retain its current directory structure. Do not restructure it merely for aesthetics. The architecture above is the logical organization, not permission to rewrite working UI code unnecessarily.

## 6. Canonical operational entities

### Operators
```text
operator_id
name
status
created_at
updated_at
```

### Stations
```text
station_id
operator_id
name
address
city
state
pincode
latitude
longitude / PostGIS geography
opening_hours
status
status_observed_at
data_updated_at
created_at
updated_at
```

### Connectors
```text
connector_id
station_id
connector_type
power_kw
quantity
availability_status
price_information
created_at
updated_at
```

### Station sources
Preserve source-level provenance without making source metadata a normal driver-facing feature.

### User reports
One row per submitted station observation/report.

Report structure must support:
- Available
- Busy
- Broken
- queue category
- optional comment
- observed time
- user/time metadata

### Reviews
Separate from station status reports.

A review contains:
- star rating
- comment
- timestamps
- user/station references

### Favorites
One user to many saved stations.

### Alerts
Initially:
- availability
- congestion/busy-time condition

## 7. Analytics model

Authoritative canonical warehouse schemas (Phase 1 verified):

```text
analytics.dim_station
analytics.dim_operator
analytics.dim_connector
analytics.dim_location
analytics.dim_date
analytics.dim_time
analytics.dim_source
analytics.dim_weather

analytics.fact_station_observation
analytics.fact_user_report
analytics.fact_review
analytics.fact_station_daily
```

Fact grains:

- `fact_station_observation` = one source observation for a station/connector at a point in time
- `fact_user_report` = one crowdsourced user status report
- `fact_review` = one driver experience rating and commentary review
- `fact_station_daily` = one station/day analytical aggregate
*(Note: ML model metadata, training runs, and inference predictions are housed in the dedicated `ml.*` schema (`ml.models`, `ml.prediction_runs`, etc.), not as a warehouse fact).*

## 8. ML / recommendation boundary

ML is not the first implementation task.

When sufficient real historical data exists:
1. establish a baseline
2. create features
3. train a justified model
4. evaluate against the baseline
5. expose only useful, sufficiently supported intelligence

Possible features:
- hour
- weekday/weekend
- historical busy patterns
- recent reports
- connector characteristics
- station characteristics
- weather where available
- recent observed status

Recommendation should first filter for compatibility, then consider:
- distance
- connector compatibility
- charging power
- observed availability
- historical busy pattern
- predicted busy state where supported
- price
- reliability indicators
- data freshness/confidence

Recommendations must be explainable in ordinary language.

## 9. Data flow

```text
External station sources
        ↓
Python source adapters
        ↓
Raw records
        ↓
Validation
        ↓
Normalization
        ↓
Deduplication/entity matching
        ↓
Canonical stations/connectors
        ↓
Operational database
        ↓
Observation/history facts
        ↓
Analytics
        ↓
Forecasts/recommendations
        ↓
Next.js product
```

User reports enter through the product and become another structured observation stream.

## 10. API/data access rule

Use Supabase directly for normal:
- station reads
- station detail reads
- favorites
- reports
- reviews
- alerts
- profiles

Use Python/FastAPI when logic genuinely requires:
- protected server-side processing
- ingestion control
- complex recommendation computation
- ML execution
- scheduled data jobs
- transformations not appropriate in the client

Do not build a needless "frontend → FastAPI → Supabase" proxy for every request.

## 11. Security

- Supabase Auth for identity
- RLS for user-owned data
- never expose service-role keys in frontend
- environment secrets only
- validate all user input
- rate-limit abuse-prone actions
- keep timestamps server-generated where possible
- separate public station reads from private user data
- no passwords
- no real PII beyond what is necessary for account functionality

## 12. Data maturity

Every intelligence feature must respect:

```text
COLD
  ↓
WARMING
  ↓
READY
```

COLD:
not enough trustworthy history.

WARMING:
some observations exist but prediction quality is not established.

READY:
enough validated historical data to support the feature.

Never show a prediction merely because the UI has a place for it.

## 13. Locked conceptual decisions

- Public browsing does not require login.
- Login is requested only for actions that need an account.
- Auth is phone number or email + OTP, no passwords.
- Mobile-first responsive web.
- English, Hindi, Marathi.
- Warm ChargePlus palette only.
- MapLibre/OSM-derived mapping, no Google Maps dependency.
- External navigation through a user-selected navigation app.
- No station photos.
- Reviews = star rating + comment.
- Reports = structured quick observations with optional comment.
- User reports are not manually seeded.
- Station cards stay simple.
- Deeper intelligence belongs on station detail/recommendation contexts.
- No technical data-source display on normal station detail.
- No fabricated availability, prices, predictions, or reviews.
- Amenities are not part of the current filter scope.
