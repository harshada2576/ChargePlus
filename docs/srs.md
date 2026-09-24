# ChargePlus — Software Requirements Specification v1.0

**Status:** Build-ready baseline
**Product:** ChargePlus
**Pilot:** Mumbai, India
**Target:** Publicly hosted mobile-first web product + academic Data Warehouse/Data Mining project
**Primary stack:** Next.js + TypeScript, Supabase, Python, PostgreSQL, MapLibre
**Data principle:** No fabricated production observations

This SRS supersedes the earlier broad proposal where the requirements conflict. The original proposal remains the conceptual foundation. 

---

# 1. Executive Summary

**ChargePlus** is a mobile-first EV charging intelligence platform designed initially for Mumbai and architected for expansion across India.

The platform aggregates charging-station information from multiple legitimate data sources into one interface and combines that information with user-generated observations, historical analytics and machine-learning predictions.

The core user problem is:

> **EV drivers have difficulty finding complete, current and trustworthy charging information, and may encounter unavailable chargers or long queues after reaching a station.**

ChargePlus aims to help users answer:

> **"Where should I charge?"**

rather than simply:

> "Where is a charger?"

---

# 2. Product Vision

### Vision

> **Make EV charging information easier to discover, understand and act upon by bringing fragmented station information into one intelligent platform.**

### Long-term vision

```text
Multiple data sources
        ↓
Unified charging database
        ↓
Data quality + provenance
        ↓
Historical intelligence
        ↓
Prediction
        ↓
Recommendation
        ↓
Better charging decisions
        ↓
More user observations
        ↓
Better intelligence
```

---

# 3. Product Positioning

Existing products already provide substantial station discovery functionality.

ChargeZone, for example, provides station discovery, real-time availability, reservations, payments, favorites and charging history. ([App Store][1])

Open Charge Map provides an API that exposes charging locations, comments, check-ins and other station information. ([Open Charge Map][2])

A newer Indian product, NextCharge, is also explicitly targeting the fragmented multi-network discovery problem. ([NextCharge][3])

Therefore ChargePlus will **not** compete primarily on:

* payments
* bookings
* charger control
* operating a charging network
* simply displaying pins on a map

Instead, ChargePlus differentiates through:

1. **Multi-source aggregation**
2. **Information completeness**
3. **Data provenance**
4. **Data-quality scoring**
5. **Historical station intelligence**
6. **Demand/availability prediction**
7. **Recommendation**
8. **Community observations**

---

# 4. Goals

## P0 — Required

* Build a publicly accessible EV charging discovery platform.
* Aggregate station information from multiple sources.
* Provide Mumbai-first coverage.
* Allow India-wide station data architecture.
* Provide mobile-first map/search experience.
* Allow users to report station conditions.
* Allow reviews.
* Provide favorites.
* Implement secure authentication.
* Build automated Python ingestion pipelines.
* Build a PostgreSQL analytical model.
* Implement data-quality and provenance tracking.
* Implement forecasting where sufficient data exists.

## P1 — Important

* Station recommendations.
* Availability/congestion prediction.
* Reliability analytics.
* Forecast evaluation.
* Alerts.
* Advanced station analytics.

## P2 — Future

* Operator analytics.
* New-station location recommendations.
* Predictive maintenance.
* Smart charging simulations.
* Dynamic pricing simulations.
* Network/operator integrations.

---

# 5. Non-Goals

The MVP will **not** include:

* Payment processing
* Charging-session initiation
* Charger OCPP control
* Reservations
* Native Android/iOS applications
* User-uploaded photos
* Full navigation engine
* Charging-network operator management
* Artificial production sessions
* Kafka/Spark/Kubernetes
* Complex microservice architecture

---

# 6. Target Users

## 6.1 EV Driver

Can:

* search stations
* view stations on a map
* filter stations
* inspect station details
* compare charging options
* see available information
* see predictions when supported
* navigate externally
* favorite stations
* submit reports
* write reviews
* create alerts

## 6.2 Contributor

A registered driver who provides:

* station status
* queue observations
* reviews
* corrections

## 6.3 Administrator

Can monitor:

* data ingestion
* data quality
* station coverage
* reports
* reviews
* forecasting
* model performance
* system health

---

# 7. Core User Journey

```text
Open ChargePlus
       ↓
Search / use location
       ↓
See nearby stations
       ↓
Filter by requirements
       ↓
Open station
       ↓
Compare information
       ↓
Choose recommended station
       ↓
Navigate externally
       ↓
Optionally report experience
```

The data flywheel:

```text
User observations
       ↓
More data
       ↓
Better historical patterns
       ↓
Better predictions
       ↓
Better recommendations
       ↓
More useful product
```

---

# 8. Station Discovery Requirements

### FR-DISC-001

The system shall display charging stations on an interactive map.

### FR-DISC-002

The system shall provide list and map representations.

### FR-DISC-003

Users shall be able to search by:

* city
* locality
* station name
* operator
* location

### FR-DISC-004

Users shall be able to filter by:

* distance
* connector type
* charging power
* operator
* availability
* price
* open now
* number of connectors
* fast charging
* free charging
* reliability where sufficient data exists

Amenities are explicitly excluded from MVP filtering.

---

# 9. Station Model

A physical charging location is the primary entity.

```text
Station
 ├── Connector
 ├── Connector
 ├── Connector
 └── Connector
```

Example:

```text
Station A
4 × CCS2
2 × Type-2
```

The application shall represent this as **one station with six connectors**, not six independent stations.

---

# 10. Station Detail Requirements

A station page shall provide, where available:

* station name
* operator
* address
* coordinates
* distance
* connector types
* connector count
* charging power
* pricing
* opening hours
* station status
* source
* update information
* user reviews
* recent reports
* historical demand
* predictions
* recommendation information
* favorite action
* report action
* navigation action

The primary map card will **not** display:

* reliability score
* congestion prediction
* data freshness

Those belong deeper in the station experience.

---

# 11. Availability Model

ChargePlus shall distinguish:

### Operational status

> Is the station recorded as operational?

### Observed status

> What has a data source/user actually reported?

### Predicted status

> What does ChargePlus estimate is likely to happen?

These shall never be silently conflated.

Example:

```text
Observed:
Busy

Predicted:
Likely busy

Operational:
Operational
```

---

# 12. Data Confidence

Every prediction/status system shall account for evidence quality.

Potential maturity states:

```text
COLD
Insufficient evidence

WARMING
Some observations

READY
Sufficient historical evidence
```

A station without sufficient data shall display:

> **Not enough data for a reliable prediction**

rather than a fabricated value.

---

# 13. User Reports

Reports shall be deliberately quick.

### Required

Status:

* Available
* Busy
* Broken

Queue:

* None
* 1–2
* 3–5
* 5+

### Optional

* comment

The system shall timestamp every report.

A report shall be associated with:

* user
* station
* timestamp
* status
* queue category
* comment

---

# 14. Reviews

Reviews are separate from observations.

A review contains:

```text
rating: 1–5
comment
user
station
timestamp
```

Photos are excluded.

Reviews shall not directly be treated as objective station-status observations.

---

# 15. Authentication

The target authentication method is:

> **Phone number + OTP**

Supabase Auth will be used.

However, an important infrastructure constraint must be documented:

**A genuinely zero-cost production phone-OTP system cannot be guaranteed.** Supabase's current Free plan excludes its Advanced Phone MFA capability, and SMS/WhatsApp messages also incur provider charges. ([Supabase][4])

Therefore:

### MVP strategy

Public browsing remains completely unauthenticated.

Authentication-dependent functionality can initially be:

* developed/tested with a supported OTP configuration
* enabled for production once an SMS provider/budget is available

**We will not secretly replace phone authentication with email just to claim the project is zero-cost.**

---

# 16. Favorites

Authenticated users can:

* add station to favorites
* remove station
* view favorites
* receive alerts for favorite stations

---

# 17. Alerts

The architecture shall support:

### Station availability

> Notify when station is likely available.

### Congestion

> Notify when predicted congestion falls below a threshold.

### Station status

> Notify when station status changes.

Alerts are P1 rather than a requirement for the first public MVP.

---

# 18. Navigation

ChargePlus will **not depend on Google Maps**.

The application shall provide an external navigation action.

MapLibre/OpenStreetMap-compatible infrastructure will be investigated for mapping and routing.

We will not use `tile.openstreetmap.org` as an unlimited production tile backend; OSM explicitly warns that its public tile infrastructure has capacity limits and may block inappropriate/high-volume use. ([OSMF Operations][5])

A no-key MapLibre-compatible tile provider such as OpenFreeMap or another appropriate production provider can be evaluated. ([GitHub][6])

---

# 19. Data Acquisition

ChargePlus shall use a pluggable source-adapter architecture.

```text
OCM Adapter
Government Adapter
Weather Adapter
Future Network Adapter
        ↓
Normalized records
        ↓
Validation
        ↓
Deduplication
        ↓
Canonical database
```

Initial sources will be evaluated based on:

* availability
* licensing/terms
* reliability
* update frequency
* coverage
* technical accessibility

---

# 20. Open Charge Map

OCM will be a major initial source.

Its API supports charging-location information as well as comments/check-ins and related data. ([Open Charge Map][2])

However:

> **We will not assume OCM provides universal live connector occupancy.**

Live status will only be used where the actual source provides appropriate evidence.

---

# 21. Data Provenance

External records shall retain:

```text
source
source_record_id
retrieved_at
observed_at
source_priority
```

Where applicable:

```text
confidence
```

This allows ChargePlus to answer:

> Where did this information come from?

and:

> How recently was it obtained?

---

# 22. Station Deduplication

Different sources may represent the same station differently.

The Python pipeline shall identify potential duplicates using combinations of:

* geographic proximity
* station/operator names
* address similarity
* operator
* connector characteristics

Potential duplicates shall be resolved through deterministic rules where possible and flagged for review where ambiguous.

---

# 23. Data Quality

The pipeline shall validate:

### Completeness

* coordinates
* operator
* connectors
* power
* address

### Validity

* latitude/longitude
* connector types
* power values
* status values

### Consistency

* connector counts
* operator identity
* station metadata

### Freshness

* source retrieval time
* observation age

### Duplication

* duplicate POIs
* duplicate connectors
* repeated source records

---

# 24. Application Database

Initial Supabase PostgreSQL schema will contain operational entities such as:

```text
stations
connectors
operators
station_sources
users/profiles
user_reports
reviews
favorites
alerts
```

Analytics entities will be separated logically into an analytics schema.

This means we can use **one Supabase PostgreSQL project initially without pretending the operational database and warehouse are the same logical model.**

---

# 25. Analytics Warehouse

### Dimensions

```text
dim_station
dim_connector
dim_operator
dim_location
dim_date
dim_time
dim_weather
```

### Facts

```text
fact_station_observation
fact_user_report
fact_station_daily
fact_forecast
```

Potential hourly fact:

```text
fact_station_hourly
```

will be introduced only if the forecasting workload requires it.

---

# 26. Warehouse Grain

This must be explicit.

### `fact_user_report`

> One row = one user-submitted station report.

### `fact_station_observation`

> One row = one source observation for one station/connector at a point in time.

### `fact_station_daily`

> One row = one station for one calendar day.

### `fact_forecast`

> One row = one forecast generated for one station/time horizon.

This grain will be documented in the data dictionary.

---

# 27. OLAP Requirements

ChargePlus shall support analytical questions such as:

* station utilization by city
* demand by hour
* weekday vs weekend demand
* operator comparisons
* connector-type demand
* station performance over time
* Mumbai locality demand
* peak charging periods
* station data completeness
* station observation coverage

Operations demonstrated in the academic component:

* roll-up
* drill-down
* slice
* dice
* pivot

---

# 28. Forecasting

### Primary ML problem

> Predict future station demand/occupancy patterns.

Initial prediction target can be:

```text
expected station demand by hour
```

where sufficient historical evidence exists.

### Baseline

Historical same-period / rolling-average baseline.

### Advanced model

Gradient boosting/regression model where justified.

Potential features:

* hour
* day of week
* weekend
* historical demand
* lag demand
* rolling averages
* weather
* station characteristics
* recent observations

---

# 29. Model Evaluation

The system shall compare ML models against a baseline.

Metrics:

* MAE
* RMSE
* MAPE where appropriate

We will not claim:

> "94% accurate"

unless the evaluation methodology supports such a statement.

The admin analytics layer shall track:

```text
baseline performance
model performance
training period
model version
evaluation period
prediction coverage
```

---

# 30. Availability/Congestion Prediction

Where sufficient data exists, ChargePlus may predict:

```text
Likely available
Likely busy
Likely full
```

The prediction must include an evidence/confidence concept internally.

Stations without enough evidence shall fall back to:

> No reliable prediction available.

---

# 31. Recommendation Engine

This is the main user-facing intelligence feature.

Candidate stations shall first be filtered for compatibility.

Potential recommendation factors:

```text
distance
connector compatibility
charging power
price
observed availability
historical demand
predicted demand
reliability
data confidence
```

The exact weighting will be determined experimentally.

Recommendations should explain themselves:

> Recommended because it is compatible, nearby and has lower predicted demand.

---

# 32. Python Requirement

Python shall be the primary language for:

* ingestion
* ETL
* transformation
* validation
* deduplication
* analytics
* feature engineering
* ML
* forecasting
* recommendation logic
* scheduled data jobs
* automated evaluation
* backend services where appropriate

Potential libraries:

```text
Python
FastAPI
Pydantic
SQLAlchemy
pandas / Polars
NumPy
scikit-learn
XGBoost where justified
GeoPandas
Shapely
pytest
```

The exact dependency set will be finalized during implementation.

---

# 33. Frontend

### Stack

* Next.js
* TypeScript
* MapLibre
* responsive/mobile-first UI

### Primary screens

1. Home/map
2. Search/results
3. Station details
4. Authentication
5. Favorites
6. Profile
7. Submit report
8. Review
9. Alerts
10. Admin/analytics

The detailed visual design will be specified separately after the SRS.

---

# 34. Supabase

Supabase will provide as much infrastructure as practical:

* PostgreSQL
* Auth
* RLS
* database APIs
* user profiles
* favorites
* reports
* reviews
* alerts
* analytics storage initially

Supabase's current Free tier includes 500 MB database storage, 1 GB file storage, 5 GB egress and 50,000 MAU. ([Supabase][4])

The 500 MB database limit means raw high-frequency status history must **not** grow indefinitely.

Therefore we need retention/aggregation policies.

---

# 35. Data Retention

Raw observations should be:

```text
Raw observation
      ↓
Daily/hourly aggregation
      ↓
Long-term analytical record
```

Old high-volume raw records may be compressed/removed after the required analytical aggregates have been produced.

This prevents the database from being consumed by polling history.

---

# 36. Security

Required:

* Supabase Auth
* PostgreSQL RLS
* server-side secrets
* environment variables
* HTTPS
* input validation
* rate limiting
* abuse protection
* database constraints
* audit timestamps
* least-privilege service credentials

User phone numbers shall never be publicly exposed.

---

# 37. Abuse Prevention

Public community data requires protection against:

* repeated fake reports
* review spam
* automated submissions
* malicious station modifications

Initial mechanisms:

* authenticated reports
* rate limits
* duplicate-report detection
* timestamping
* report history
* moderation/admin tools

A sophisticated trust-score system is deferred until actual usage justifies it.

---

# 38. Admin Console

The admin interface shall provide:

### Data

* source status
* ingestion runs
* records fetched
* records rejected
* duplicate candidates
* data completeness

### Product

* users
* reports
* reviews
* flagged content

### ML

* forecast coverage
* model versions
* baseline comparison
* error metrics

### System

* failed jobs
* API errors
* processing times

---

# 39. Observability

Every ingestion job should record:

```text
started_at
completed_at
source
records_fetched
records_inserted
records_updated
records_rejected
duplicates
error_count
status
```

Every model run should record:

```text
model_version
training_data_period
training_rows
features
metrics
generated_at
```

---

# 40. Testing

### Unit

Python functions, transformations, recommendation calculations.

### Integration

* Supabase
* APIs
* ingestion
* authentication

### Data

* schema validation
* duplicates
* missing values
* invalid coordinates

### ML

* temporal train/test split
* baseline comparison
* leakage checks
* regression tests

### Frontend

* component tests
* mobile responsiveness
* user flows

### End-to-end

```text
Browse
→ station
→ login
→ report
→ review
→ favorite
```

---

# 41. Deployment

Target architecture:

```text
GitHub
   │
   ├── Next.js frontend
   │
   ├── Python services/jobs
   │
   └── migrations/tests
          │
          ▼
      Supabase
```

CI/CD should automatically run:

* tests
* linting
* type checking
* migration checks
* build

before production deployment.

---

# 42. Development Phases

## Phase 0 — Data feasibility

**Week 1**

* OCM investigation
* government-source investigation
* source licensing/terms
* Mumbai coverage assessment
* Supabase setup
* repository

## Phase 1 — Data platform

**Weeks 1–2**

* schema
* ingestion
* normalization
* deduplication
* validation
* provenance

## Phase 2 — Core product

**Weeks 3–4**

* map
* search
* filters
* station detail
* mobile UI

## Phase 3 — Community

**Weeks 4–5**

* authentication
* reports
* reviews
* favorites

## Phase 4 — Analytics

**Weeks 5–6**

* warehouse
* OLAP
* station metrics
* data-quality dashboard

## Phase 5 — Intelligence

**Weeks 7–8**

* baseline forecasting
* prediction
* recommendation engine

## Phase 6 — Public beta

**Weeks 9–10**

* testing
* monitoring
* performance
* deployment
* documentation

## Phase 7 — Advanced

**Weeks 10–12**

Only if core product is stable:

* alerts
* anomaly detection
* improved models
* expansion scoring
* advanced analytics

---

# 43. Acceptance Criteria for MVP

ChargePlus MVP is considered complete when:

### Product

* [ ] Public user can open ChargePlus without login.
* [ ] Mumbai stations can be searched.
* [ ] Stations display on a map.
* [ ] Filters work.
* [ ] Station details work.
* [ ] External navigation works.
* [ ] Users can authenticate.
* [ ] Users can submit reports.
* [ ] Users can submit reviews.
* [ ] Users can favorite stations.

### Data

* [ ] Automated ingestion works.
* [ ] Sources are recorded.
* [ ] Duplicate stations are handled.
* [ ] Invalid records are rejected.
* [ ] Data freshness is tracked.
* [ ] Provenance is retained.

### Analytics

* [ ] Star schema exists.
* [ ] OLAP queries exist.
* [ ] Station/day aggregates work.
* [ ] KPIs work.

### ML

* [ ] Baseline exists.
* [ ] Forecast pipeline exists.
* [ ] Forecasts are only shown when sufficient evidence exists.
* [ ] Predictions are evaluated against observations.
* [ ] Recommendation engine has a documented scoring method.

### Engineering

* [ ] Production deployment.
* [ ] Automated tests.
* [ ] Error logging.
* [ ] Secrets protected.
* [ ] RLS configured.
* [ ] README/documentation complete.

---

# 44. Success Metrics

Because this starts as a portfolio/public-beta project, we'll use three categories.

### Product

* registered users
* active users
* station searches
* station detail views
* recommendation requests
* navigation clicks
* reports
* reviews

### Data

* stations covered
* Mumbai coverage
* source coverage
* information completeness
* observations collected
* percentage of stations with sufficient historical data

### ML

* forecast coverage
* baseline MAE
* model MAE
* forecast error over time
* recommendation feedback

---

# 45. Resume/academic outcome

ChargePlus should ultimately demonstrate:

```text
                    CHARGEPLUS
                         │
       ┌─────────────────┼──────────────────┐
       ▼                 ▼                  ▼
 DATA ENGINEERING      PRODUCT             ML
       │                 │                  │
 ingestion             users             forecasting
 ETL                   auth              prediction
 DWH                   reports           evaluation
 quality               reviews            recommendation
 provenance            search             monitoring
       │                 │                  │
       └─────────────────┼──────────────────┘
                         ▼
                  DEPLOYED PRODUCT
```

This is the key:

**The college Data Warehouse/Data Mining requirements become the underlying engineering infrastructure of a real product.**

---

# 46. Final architecture

```text
                         CHARGEPLUS
                             │
                    Mobile-first Web
                             │
                    Next.js + TypeScript
                             │
             ┌───────────────┴──────────────┐
             │                              │
        Supabase Auth                  Application APIs
             │                              │
             └──────────────┬───────────────┘
                            │
                     Supabase PostgreSQL
                    ┌────────┴─────────┐
                    │                  │
              Operational          Analytics
                Schema               Schema
                    │                  │
                    │             ┌────┴────┐
                    │             │         │
                    │          OLAP        ML
                    │                       │
                    │                  Forecasting
                    │                  Prediction
                    │                  Recommendation
                    │
                    └─────────┬────────────
                              │
                       Python Data Platform
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
         OCM             Government          Other APIs
          │                   │                   │
          └───────────────────┼───────────────────┘
                              ▼
                        Normalization
                              ▼
                         Validation
                              ▼
                         Deduplication
                              ▼
                         Provenance
                              ▼
                         PostgreSQL
```

---

# 47. SRS status

**ChargePlus SRS v1.0 is now sufficiently locked to begin implementation planning.**

The next artifact should **not** be another conceptual discussion.

## Next: Database + API Design

We'll produce:

1. Exact PostgreSQL tables
2. Every column
3. Data types
4. PK/FK relationships
5. indexes
6. constraints
7. RLS policies
8. operational vs analytics schemas
9. exact star schema
10. sample records
11. ingestion tables
12. provenance tables
13. forecast tables
14. complete REST/API contract
15. Python project structure
16. Supabase project structure
17. GitHub repository structure

