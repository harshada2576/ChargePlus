# ChargePlus — Database & API Specification v1.0

> **⚠️ SUPERSEDED DESIGN — documentation synchronisation (Phase 1 Step 1.8).**
> This is the *pre-implementation* database/API design that preceded the actual migrations.
> It is retained for historical reference only and must **not** be treated as the implemented schema.
> Several objects named here were **not** built:
> - `ingestion` schema (`ingestion.sources/runs/raw_station_records/data_quality_results`)
>   → not created; the feed registry is implemented as `public.data_sources` + `public.station_source_link` (Step 1.3).
> - `ml.models` / `ml.forecast_runs` → not created; the ML layer is implemented as `ml.features`,
>   `ml.datasets`, `ml.experiments` (with dataset_key intra-ml FK), `ml.model_versions` (with ready-gate constraints and FK indexes),
>   `ml.metrics`, `ml.prediction_runs` (Step 1.5 + Step 1.6 synthesis).
> - `analytics.fact_station_hourly`, `analytics.fact_forecast` → not created (explicitly deferred).
> - `public.notification_events`, `public.station_current_status`, `public.station_sources`,
>   `public.station_search_view`, `ml.forecasts` → not created.
>   Implemented views and functions are: `public.v_station_current_state`, `public.v_station_connectors`,
>   `public.v_station_approved_reviews`, `public.nearby_stations`, `public.get_author_display_name`,
>   and `analytics.v_station_daily_summary` (Step 1.8 `20260925000001_step_1_8_views_functions.sql` — EXECUTED + VERIFIED).
>
> **Authoritative documents for the implemented architecture:**
> `Must Read/Architecture.md` · `docs/data_warehouse.md` (canonical warehouse docs) ·
> `docs/data_dictionary.md` (table inventory) · `docs/step_1_6_constraints_indexes_audit.md` · `docs/step_1_8_views_functions_audit.md` ·
> `supabase/migrations/*.sql` (the actual DDL including Step 1.6, Step 1.7, and Step 1.8 — EXECUTED + VERIFIED).
>
> Locked boundary: `public` = operational OLTP (29 RLS policies, 3 views, 2 functions) · `analytics` = canonical data warehouse OLAP (RLS enabled, 0 client policies, 1 view) ·
> `ml` = ML metadata/control (RLS enabled, 0 client policies) · Python = ETL/ML boundary · legacy `public.dim_*` / `public.fact_*`
> untouched/future-reserved (RLS disabled) · no fake production data.

This is the next implementation artifact after the SRS.
---

## 1. Architecture

```text
                         ┌──────────────────────┐
                         │      Next.js UI      │
                         │ Mobile-first Web App  │
                         └──────────┬───────────┘
                                    │
                         Supabase JS / REST
                                    │
                 ┌──────────────────▼──────────────────┐
                 │          Supabase PostgreSQL         │
                 │                                      │
                 │  public/app   Operational database   │
                 │  analytics    Data warehouse         │
                 │  ingestion    Raw/provenance data   │
                 │  ml           Forecast/model data   │
                 └──────────┬───────────────┬──────────┘
                            │               │
                    Python jobs        Supabase Auth
                            │
              ┌─────────────▼─────────────┐
              │ Ingestion / ETL / ML      │
              │ Python                    │
              └─────────────┬─────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
       OCM/API          Government        Weather
        Sources           Sources          Sources
```

### Key principle

We **do not** create a FastAPI endpoint for every database operation.

Next.js can directly use Supabase for normal authenticated/public CRUD. Python/FastAPI is reserved for logic that actually belongs on the backend:

* ingestion
* deduplication
* data-quality processing
* forecasting
* recommendation computation when necessary
* ML jobs
* administrative operations
* protected server-side workflows

---

# 2. PostgreSQL Schemas

We'll logically separate the database into:

| Schema      | Purpose                                           |
| ----------- | ------------------------------------------------- |
| `public`    | Supabase/Auth-facing operational application data |
| `ingestion` | Raw external data + provenance + ingestion runs   |
| `analytics` | Data warehouse / OLAP                             |
| `ml`        | Models, forecasts, feature outputs                |
| `auth`      | Supabase-managed authentication                   |

We should **not modify Supabase's `auth` schema manually**.

---

# 3. Operational Database

## 3.1 `public.operators`

Represents charging-network/operator organizations.

| Column          | Type        | Constraints   |
| --------------- | ----------- | ------------- |
| `id`            | UUID        | PK            |
| `name`          | TEXT        | NOT NULL      |
| `slug`          | TEXT        | UNIQUE        |
| `website_url`   | TEXT        | nullable      |
| `support_phone` | TEXT        | nullable      |
| `created_at`    | TIMESTAMPTZ | default now() |
| `updated_at`    | TIMESTAMPTZ | default now() |

Examples:

```text
Tata Power
ChargeZone
Statiq
Jio-bp
Ather
```

The actual list comes from ingestion rather than hard-coded seed data.

---

# 4. `public.stations`

**One physical charging location = one station.**

Connectors belong underneath it.

| Column               | Type             | Constraints       |
| -------------------- | ---------------- | ----------------- |
| `id`                 | UUID             | PK                |
| `name`               | TEXT             | NOT NULL          |
| `operator_id`        | UUID             | FK                |
| `address_line`       | TEXT             | nullable          |
| `locality`           | TEXT             | nullable          |
| `city`               | TEXT             | NOT NULL          |
| `state`              | TEXT             | NOT NULL          |
| `country`            | TEXT             | default `'India'` |
| `postal_code`        | TEXT             | nullable          |
| `latitude`           | DOUBLE PRECISION | NOT NULL          |
| `longitude`          | DOUBLE PRECISION | NOT NULL          |
| `is_public`          | BOOLEAN          | default TRUE      |
| `operational_status` | TEXT             | constrained       |
| `access_type`        | TEXT             | nullable          |
| `opening_time`       | TIME             | nullable          |
| `closing_time`       | TIME             | nullable          |
| `is_24_hours`        | BOOLEAN          | default FALSE     |
| `price_summary`      | TEXT             | nullable          |
| `description`        | TEXT             | nullable          |
| `last_verified_at`   | TIMESTAMPTZ      | nullable          |
| `created_at`         | TIMESTAMPTZ      | default now()     |
| `updated_at`         | TIMESTAMPTZ      | default now()     |

### `operational_status`

Allowed values:

```text
unknown
operational
temporarily_unavailable
permanently_closed
```

Important distinction:

> `operational_status` does **not** mean a connector is currently free.

Current availability belongs to observations/status records.

---

# 5. `public.station_sources`

Links a canonical station to external sources.

| Column                | Type        |
| --------------------- | ----------- |
| `id`                  | UUID PK     |
| `station_id`          | UUID FK     |
| `source_name`         | TEXT        |
| `source_station_id`   | TEXT        |
| `source_url`          | TEXT        |
| `first_seen_at`       | TIMESTAMPTZ |
| `last_seen_at`        | TIMESTAMPTZ |
| `last_ingested_at`    | TIMESTAMPTZ |
| `source_payload_hash` | TEXT        |
| `is_active`           | BOOLEAN     |

### Why this matters

Suppose:

```text
OCM → station ABC
Government source → station XYZ
```

After deduplication:

```text
ChargePlus station CP-001
 ├── OCM ABC
 └── Government XYZ
```

We preserve the source identities rather than throwing them away.

---

# 6. `public.connectors`

A station can have multiple connectors.

| Column              | Type          |
| ------------------- | ------------- |
| `id`                | UUID PK       |
| `station_id`        | UUID FK       |
| `connector_type`    | TEXT          |
| `charging_standard` | TEXT          |
| `power_kw`          | NUMERIC(8,2)  |
| `quantity`          | INTEGER       |
| `pricing_type`      | TEXT          |
| `price_per_kwh`     | NUMERIC(10,2) |
| `price_per_session` | NUMERIC(10,2) |
| `is_fast_charging`  | BOOLEAN       |
| `created_at`        | TIMESTAMPTZ   |
| `updated_at`        | TIMESTAMPTZ   |

Examples:

```text
CCS2
CHAdeMO
Type 2
GB/T
```

The exact supported values should remain extensible.

---

# 7. `public.user_reports`

This is the community observation system.

| Column                | Type                 |
| --------------------- | -------------------- |
| `id`                  | UUID PK              |
| `user_id`             | UUID FK → auth.users |
| `station_id`          | UUID FK              |
| `connector_id`        | UUID nullable        |
| `availability_status` | TEXT                 |
| `queue_level`         | TEXT                 |
| `comment`             | TEXT nullable        |
| `observed_at`         | TIMESTAMPTZ          |
| `created_at`          | TIMESTAMPTZ          |
| `is_flagged`          | BOOLEAN              |
| `moderation_status`   | TEXT                 |

### Availability

```text
available
busy
broken
unknown
```

### Queue

```text
none
short
medium
long
unknown
```

The UI should make this extremely quick.

Example:

```text
How is this station?

🟢 Available
🟠 Busy
🔴 Broken

Queue:
None / Short / Medium / Long

Comment:
[optional]
```

---

# 8. `public.reviews`

Reviews are intentionally separate from operational reports.

| Column              | Type        |
| ------------------- | ----------- |
| `id`                | UUID PK     |
| `user_id`           | UUID FK     |
| `station_id`        | UUID FK     |
| `rating`            | SMALLINT    |
| `comment`           | TEXT        |
| `created_at`        | TIMESTAMPTZ |
| `updated_at`        | TIMESTAMPTZ |
| `is_flagged`        | BOOLEAN     |
| `moderation_status` | TEXT        |

Constraint:

```text
rating BETWEEN 1 AND 5
```

A review answers:

> "What was your experience?"

A report answers:

> "What is happening at this station?"

That distinction is important for analytics.

---

# 9. `public.favorites`

| Column       | Type        |
| ------------ | ----------- |
| `user_id`    | UUID        |
| `station_id` | UUID        |
| `created_at` | TIMESTAMPTZ |

Primary key:

```text
(user_id, station_id)
```

This prevents duplicate favorites.

---

# 10. `public.alerts`

| Column              | Type                 |
| ------------------- | -------------------- |
| `id`                | UUID PK              |
| `user_id`           | UUID FK              |
| `station_id`        | UUID nullable        |
| `alert_type`        | TEXT                 |
| `threshold_value`   | NUMERIC nullable     |
| `is_enabled`        | BOOLEAN              |
| `created_at`        | TIMESTAMPTZ          |
| `updated_at`        | TIMESTAMPTZ          |
| `last_triggered_at` | TIMESTAMPTZ nullable |

Possible alert types:

```text
station_available
station_status_change
congestion_threshold
nearby_station_change
```

---

# 11. `public.notification_events`

Eventually useful for tracking whether alerts were actually delivered.

| Column         | Type                 |
| -------------- | -------------------- |
| `id`           | UUID PK              |
| `user_id`      | UUID                 |
| `alert_id`     | UUID                 |
| `event_type`   | TEXT                 |
| `payload`      | JSONB                |
| `created_at`   | TIMESTAMPTZ          |
| `delivered_at` | TIMESTAMPTZ nullable |

---

# 12. `public.station_current_status`

This is a **derived/current snapshot**, not the historical warehouse.

| Column                 | Type             |
| ---------------------- | ---------------- |
| `station_id`           | UUID PK          |
| `availability_status`  | TEXT             |
| `available_connectors` | INTEGER nullable |
| `total_connectors`     | INTEGER          |
| `queue_level`          | TEXT             |
| `observed_at`          | TIMESTAMPTZ      |
| `source_type`          | TEXT             |
| `confidence_score`     | NUMERIC(5,4)     |
| `updated_at`           | TIMESTAMPTZ      |

This allows the map to load quickly without scanning thousands of historical observations.

---

# 13. Data Provenance

This is one of the most important parts of ChargePlus.

## `ingestion.sources`

| Column        | Type        |
| ------------- | ----------- |
| `id`          | UUID PK     |
| `name`        | TEXT        |
| `source_type` | TEXT        |
| `base_url`    | TEXT        |
| `is_active`   | BOOLEAN     |
| `created_at`  | TIMESTAMPTZ |

Examples:

```text
open_charge_map
government
weather
future_network_api
```

---

# 14. `ingestion.runs`

Every ingestion execution gets a record.

| Column               | Type          |
| -------------------- | ------------- |
| `id`                 | UUID PK       |
| `source_id`          | UUID FK       |
| `started_at`         | TIMESTAMPTZ   |
| `completed_at`       | TIMESTAMPTZ   |
| `status`             | TEXT          |
| `records_received`   | INTEGER       |
| `records_inserted`   | INTEGER       |
| `records_updated`    | INTEGER       |
| `records_rejected`   | INTEGER       |
| `records_duplicated` | INTEGER       |
| `error_message`      | TEXT nullable |

This gives us an actual data-engineering story:

```text
Source
 ↓
Ingestion run
 ↓
Raw records
 ↓
Validation
 ↓
Deduplication
 ↓
Canonical station
 ↓
Analytics warehouse
```

---

# 15. `ingestion.raw_station_records`

Raw source payloads should be preserved.

| Column              | Type          |
| ------------------- | ------------- |
| `id`                | UUID PK       |
| `run_id`            | UUID FK       |
| `source_station_id` | TEXT          |
| `payload`           | JSONB         |
| `payload_hash`      | TEXT          |
| `received_at`       | TIMESTAMPTZ   |
| `processing_status` | TEXT          |
| `rejection_reason`  | TEXT nullable |

This is extremely useful for:

* debugging
* reprocessing
* audits
* data-quality analysis
* demonstrating ETL
* reproducing transformations

---

# 16. `ingestion.data_quality_results`

| Column       | Type        |
| ------------ | ----------- |
| `id`         | UUID PK     |
| `run_id`     | UUID        |
| `record_id`  | UUID        |
| `check_name` | TEXT        |
| `severity`   | TEXT        |
| `passed`     | BOOLEAN     |
| `message`    | TEXT        |
| `created_at` | TIMESTAMPTZ |

Checks include:

```text
coordinates_valid
required_fields_present
power_valid
connector_valid
duplicate_candidate
address_consistent
source_freshness
```

---

# 17. Analytics Warehouse

Now we build the part directly useful for your **Data Warehouse / Data Mining** requirements.

---

## Dimensions

### `analytics.dim_station`

```text
station_key
station_id
station_name
operator_key
city
state
latitude
longitude
access_type
is_24_hours
effective_from
effective_to
is_current
```

This supports slowly changing station attributes.

---

### `analytics.dim_operator`

```text
operator_key
operator_id
operator_name
```

---

### `analytics.dim_connector`

```text
connector_key
connector_id
connector_type
charging_standard
power_kw
is_fast_charging
```

---

### `analytics.dim_date`

Standard date dimension.

```text
date_key
full_date
year
quarter
month
month_name
week
day_of_month
day_of_week
day_name
is_weekend
```

---

### `analytics.dim_time`

```text
time_key
hour
minute
15_minute_bucket
time_of_day
```

---

### `analytics.dim_weather`

```text
weather_key
temperature
precipitation
humidity
wind_speed
weather_condition
```

---

# 18. Fact Tables

## `analytics.fact_station_observation`

**Grain: one source observation of a station/connector at a point in time.**

```text
observation_key
station_key
connector_key
date_key
time_key
weather_key
source_id
observed_at
availability_status
queue_level
available_connectors
total_connectors
confidence_score
```

This becomes one of the core analytical datasets.

---

# 19. `analytics.fact_user_report`

**Grain: one user report.**

```text
report_key
station_key
date_key
time_key
user_id
availability_status
queue_level
created_at
```

We deliberately don't need to expose personally identifying information in analytical queries.

---

# 20. `analytics.fact_station_daily`

**Grain: one station per day.**

Possible measures:

```text
station_key
date_key

observation_count
user_report_count

available_observation_count
busy_observation_count
broken_observation_count

average_queue_score
peak_queue_score

estimated_demand
estimated_congestion

average_rating
review_count
```

This table makes OLAP queries fast.

---

# 21. `analytics.fact_station_hourly`

Optional but highly useful for forecasting.

```text
station_key
date_key
time_key

observation_count
availability_ratio
busy_ratio
broken_ratio
estimated_demand
queue_score
```

We don't need to generate fake rows.

If there is no evidence for an hour, it remains missing/unknown rather than being fabricated.

---

# 22. `analytics.fact_forecast`

```text
forecast_key
station_key
date_key
time_key
model_key
generated_at

forecast_horizon
predicted_demand
predicted_congestion
prediction_lower_bound
prediction_upper_bound
confidence_score
```

---

# 23. ML Tables

## `ml.models`

```text
id
model_name
model_version
model_type
training_started_at
training_completed_at
training_data_start
training_data_end
metrics
artifact_location
status
created_at
```

Example:

```text
station-demand-baseline
station-demand-gradient-boosting
```

---

## `ml.forecast_runs`

```text
id
model_id
started_at
completed_at
status
stations_processed
forecast_rows
metrics
error_message
```

---

# 24. Important Indexes

We should index the queries users actually perform.

### Stations

```sql
CREATE INDEX idx_stations_city
ON public.stations(city);

CREATE INDEX idx_stations_operator
ON public.stations(operator_id);

CREATE INDEX idx_stations_coordinates
ON public.stations(latitude, longitude);
```

For proper geographic search, we should eventually use **PostGIS** rather than calculating all distances in application code.

Then:

```sql
CREATE INDEX idx_stations_geo
ON public.stations
USING GIST (location);
```

where:

```text
location = geography(Point, 4326)
```

This is the correct direction for:

> "charging stations within 5 km"

rather than loading every Mumbai station into JavaScript.

---

### Reports

```sql
CREATE INDEX idx_reports_station_time
ON public.user_reports(station_id, observed_at DESC);
```

### Reviews

```sql
CREATE INDEX idx_reviews_station
ON public.reviews(station_id, created_at DESC);
```

### Favorites

```sql
CREATE INDEX idx_favorites_user
ON public.favorites(user_id);
```

### Forecasts

```sql
CREATE INDEX idx_forecasts_station_time
ON ml.forecasts(station_id, target_time);
```

---

# 25. Row-Level Security

This is essential because we're using Supabase.

## Public users

Can:

```text
READ stations
READ connectors
READ current station status
READ public reviews
```

Cannot:

```text
modify stations
modify connectors
modify ingestion data
modify forecasts
```

---

## Authenticated users

Can:

```text
READ public data

CREATE own reports
UPDATE own reports
DELETE own reports

CREATE own reviews
UPDATE own reviews
DELETE own reviews

CREATE/delete own favorites

CREATE/update/delete own alerts
```

They cannot modify another user's records.

Conceptually:

```sql
auth.uid() = user_id
```

---

# 26. Admin Access

Admin operations should **not** simply be:

```text
if frontend says admin → allow
```

Instead, maintain an admin role/claim and enforce it server-side/RLS.

Admin capabilities:

```text
manage moderation
inspect ingestion runs
inspect rejected records
inspect quality metrics
inspect model runs
inspect system health
```

---

# 27. API Design

We will use two categories.

## A. Supabase Data API

For straightforward operations.

### Public

```http
GET /stations
GET /stations/:id
GET /stations/:id/connectors
GET /stations/:id/reviews
GET /stations/:id/current-status
```

In practice these can be Supabase queries/views rather than custom FastAPI endpoints.

---

# 28. Station Search

Frontend needs one primary search operation.

Conceptually:

```http
GET /stations/search
```

Parameters:

```text
latitude
longitude
radius
connector_type
min_power_kw
operator
availability
price
open_now
fast_charging
free_charging
min_connectors
sort
```

Example:

```text
/stations/search
?lat=19.076
&lng=72.877
&radius=10
&connector_type=CCS2
&min_power_kw=50
&availability=available
```

The actual implementation can be a PostgreSQL RPC/function exposed through Supabase.

---

# 29. Station Detail Response

The frontend should receive something conceptually like:

```json
{
  "id": "uuid",
  "name": "Example Charging Station",
  "location": {
    "latitude": 19.076,
    "longitude": 72.877
  },
  "address": {
    "locality": "Andheri",
    "city": "Mumbai",
    "state": "Maharashtra"
  },
  "operator": {
    "id": "uuid",
    "name": "Example Operator"
  },
  "connectors": [
    {
      "type": "CCS2",
      "power_kw": 120,
      "quantity": 4
    }
  ],
  "current_status": {
    "status": "available",
    "available_connectors": 2,
    "total_connectors": 4,
    "observed_at": "2026-09-16T10:30:00Z"
  },
  "pricing": {
    "type": "per_kwh",
    "price": 18
  }
}
```

---

# 30. Intelligence Response

Keep predictions separate from factual station information.

```json
{
  "station_id": "uuid",
  "recommendation": {
    "score": 0.87,
    "rank": 1,
    "reasons": [
      "Compatible CCS2 connector",
      "2 connectors currently reported available",
      "Lower predicted congestion",
      "Within 4.2 km"
    ]
  },
  "prediction": {
    "available": true,
    "predicted_congestion": "low",
    "confidence": 0.76
  }
}
```

If confidence is insufficient:

```json
{
  "prediction": null
}
```

rather than inventing an answer.

---

# 31. Report API

### Create report

```http
POST /reports
```

```json
{
  "station_id": "uuid",
  "connector_id": "uuid",
  "availability_status": "busy",
  "queue_level": "medium",
  "comment": "Around three vehicles waiting."
}
```

Server automatically adds:

```text
user_id
created_at
observed_at
```

---

# 32. Review API

```http
POST /reviews
```

```json
{
  "station_id": "uuid",
  "rating": 4,
  "comment": "Fast charger and easy access."
}
```

---

# 33. Favorites API

```text
POST   /favorites
DELETE /favorites/:station_id
GET    /favorites
```

---

# 34. Alerts API

```text
GET    /alerts
POST   /alerts
PATCH  /alerts/:id
DELETE /alerts/:id
```

Example:

```json
{
  "station_id": "uuid",
  "alert_type": "congestion_threshold",
  "threshold_value": 0.7,
  "is_enabled": true
}
```

---

# 35. Python Backend Structure

I'm deliberately keeping this simpler than a microservice architecture.

```text
chargeplus/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── hooks/
│   ├── lib/
│   ├── styles/
│   └── types/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   │
│   │   ├── api/
│   │   │   ├── health.py
│   │   │   ├── stations.py
│   │   │   ├── recommendations.py
│   │   │   └── admin.py
│   │   │
│   │   ├── ingestion/
│   │   │   ├── base.py
│   │   │   ├── ocm.py
│   │   │   ├── government.py
│   │   │   └── pipeline.py
│   │   │
│   │   ├── quality/
│   │   │   ├── validators.py
│   │   │   ├── deduplication.py
│   │   │   └── scoring.py
│   │   │
│   │   ├── analytics/
│   │   │   ├── transforms.py
│   │   │   ├── aggregations.py
│   │   │   └── olap.py
│   │   │
│   │   ├── ml/
│   │   │   ├── features.py
│   │   │   ├── baseline.py
│   │   │   ├── forecasting.py
│   │   │   ├── evaluation.py
│   │   │   └── recommendation.py
│   │   │
│   │   └── db/
│   │       ├── client.py
│   │       └── queries.py
│   │
│   ├── jobs/
│   │   ├── ingest_stations.py
│   │   ├── refresh_status.py
│   │   ├── build_warehouse.py
│   │   └── generate_forecasts.py
│   │
│   ├── tests/
│   └── requirements.txt
│
├── database/
│   ├── migrations/
│   ├── functions/
│   ├── policies/
│   └── views/
│
├── notebooks/
│   ├── exploration/
│   ├── data_quality/
│   ├── forecasting/
│   └── evaluation/
│
├── docs/
│   ├── SRS.md
│   ├── DATABASE.md
│   ├── API.md
│   ├── DATA_DICTIONARY.md
│   └── ARCHITECTURE.md
│
└── README.md
```

---

# 36. GitHub Repository

Recommended top level:

```text
ChargePlus/
```

Branches:

```text
main
develop
feature/*
fix/*
```

Initial development:

```text
feature/database-schema
feature/ingestion-pipeline
feature/station-map
feature/auth
feature/user-reports
feature/reviews
feature/analytics
feature/forecasting
feature/recommendations
```

Don't create dozens of repositories.

One monorepo is enough.

---

# 37. Database Views

We'll create frontend-friendly views instead of making the UI understand the entire warehouse.

### `public.station_search_view`

Contains:

```text
station
operator
coordinates
connector summary
current status
price
opening status
```

### `public.station_detail_view`

Contains richer station information.

### `public.station_rating_summary`

```text
station_id
average_rating
review_count
```

### `public.station_intelligence_view`

Contains only intelligence that has sufficient data.

---

# 38. Data Flow

This becomes the central pipeline:

```text
                 EXTERNAL SOURCES
                       │
                       ▼
              ┌─────────────────┐
              │ Raw ingestion   │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │ Validation      │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │ Deduplication   │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │ Canonical       │
              │ stations        │
              └────────┬────────┘
                       │
             ┌─────────┴──────────┐
             ▼                    ▼
       Operational DB        Analytics DW
             │                    │
             ▼                    ▼
        Product UI           ML pipeline
                                  │
                                  ▼
                            Forecasts
                                  │
                                  ▼
                           Recommendations
```

---

# 39. Data Maturity

Every station should effectively have a data-confidence state.

### COLD

Very little evidence.

Show:

```text
Station information
Source information
Basic connector data
```

Do **not** make strong availability predictions.

### WARMING

Some observations exist.

Show:

```text
recent reports
basic historical patterns
limited intelligence
```

### READY

Enough historical evidence exists.

Show:

```text
forecast
congestion estimate
recommendation intelligence
reliability indicators
```

This protects ChargePlus from pretending that an ML model is useful when the underlying data isn't.

---

# 40. What We Will NOT Do

To keep the project real rather than unnecessarily complicated:

```text
❌ Kafka
❌ Spark
❌ Kubernetes
❌ microservice explosion
❌ Redis initially
❌ separate warehouse server initially
❌ fake production traffic
❌ fake charging sessions
❌ fake user reports
❌ deep learning just for presentation
❌ custom navigation engine
❌ payment system
❌ booking engine
❌ OCPP
```

Python + Supabase/Postgres + scheduled jobs is enough to build the first real version.

---

# 41. Development Data Policy

### Development

Synthetic data is allowed for:

* UI development
* database testing
* algorithm testing
* ML experimentation
* load testing

### Production

Only:

```text
real external source data
+
real user reports
+
real reviews
+
derived calculations
```

enter production analytics.

No fake observations should quietly inflate the warehouse.

---

# 42. First Database Migration Order

We should implement migrations in this order:

```text
001_extensions
002_operators
003_stations
004_connectors
005_station_sources
006_current_status
007_user_reports
008_reviews
009_favorites
010_alerts
011_notification_events

020_ingestion_sources
021_ingestion_runs
022_raw_station_records
023_data_quality_results

030_analytics_dimensions
031_analytics_facts

040_ml_models
041_forecasts
042_forecast_runs

050_indexes
060_rls
070_views
080_functions
```

---

# 43. Final MVP Database

At the end of the first implementation phase, the important entities are:

```text
                    ┌────────────┐
                    │  Operator  │
                    └─────┬──────┘
                          │
                          ▼
                    ┌────────────┐
                    │  Station   │
                    └─────┬──────┘
                          │
             ┌────────────┼─────────────┐
             ▼            ▼             ▼
        Connectors    Sources      Current Status
                          │
                          ▼
                     Observations
                          ▲
                          │
                    User Reports

Station ─────── Reviews
Station ─────── Favorites
Station ─────── Alerts
Station ─────── Forecasts
```

This gives us a **real product database + data warehouse + ML foundation** without overengineering it.

