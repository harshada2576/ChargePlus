# ChargePlus — Data Dictionary / Schema & Table Inventory

**Phase:** 1/6 — Complete Foundation (Steps 1.1–1.10 EXECUTED + LIVE VERIFIED + SIGNED OFF)  
**Status:** fully verified against linked Supabase project (source of truth = `supabase/migrations/`).  
**Boundary lock (must never drift):**
- `public` = operational OLTP (29 explicit RLS policies, defense-in-depth column grants, security_invoker views)
- `analytics` = canonical data warehouse OLAP (RLS enabled, 0 client policies, Python ETL writes only; no frontend writes)
- `ml` = ML metadata/control (RLS enabled, 0 client policies; metadata only; populated by Python ETL/ML pipeline)
- Python = ETL/ML boundary
- legacy `public.dim_*` / `public.fact_*` = untouched, empty, future-reserved (RLS disabled)
- no fake/synthetic production data anywhere

---

## Schema map

| Schema | Role | Tables / Views | Authoritative Migration(s) |
|---|---|---|---|
| `public` | Operational OLTP | 11 operational tables (**+ 9 legacy empty tables**)<br>3 views, 2 functions | Step 1.3 `20260918000001_step_1_3_core_operational_schema.sql`<br>Step 1.6 `20260923000001_step_1_6_constraints_indexes.sql`<br>Step 1.7 `20260924000001_step_1_7_rls_security_policies.sql`<br>Step 1.8 `20260925000001_step_1_8_views_functions.sql` |
| `analytics` | Data warehouse OLAP | 12 (8 dims + 4 facts)<br>1 view | Step 1.4 `20260922000001_step_1_4_analytics_warehouse_schema.sql`<br>Step 1.6 `20260923000001_step_1_6_constraints_indexes.sql`<br>Step 1.7 `20260924000001_step_1_7_rls_security_policies.sql`<br>Step 1.8 `20260925000001_step_1_8_views_functions.sql` |
| `ml` | ML metadata/control | 6 | Step 1.5 `20260922000001_step_1_5_ml_metadata_schema.sql`<br>Step 1.6 `20260923000001_step_1_6_constraints_indexes.sql`<br>Step 1.7 `20260924000001_step_1_7_rls_security_policies.sql` |
| `auth` | Supabase-managed authentication | (managed by Supabase) | never modified manually |
| extensions | `postgis`, `pgcrypto` | — | enabled in Step 1.3 (`CREATE EXTENSION IF NOT EXISTS`) |

Grain/SCD/ETL details live in `docs/data_warehouse.md`; the constraint/index audit lives in `docs/step_1_6_constraints_indexes_audit.md`.

---

## Legacy `public` tables (untouched, empty, future-reserved)

The following pre-existing `public` tables are **empty** and remain **untouched**:

`public.dim_date`, `public.dim_location`, `public.dim_station`, `public.dim_tariff`, `public.dim_time`, `public.dim_vehicle`, `public.dim_weather`, `public.fact_charging_session`, `public.fact_station_daily_agg`

Policy (absolute): no `DROP`, `ALTER`, `RENAME`, `TRUNCATE`, `INSERT`, `UPDATE`, or `DELETE` touching any of them. The Step 1.3/1.4/1.5/1.6 migrations reference them in header comments only.

---

# 1. `public` schema — operational OLTP (11 tables)

## 1.1 `public.profiles`
One row per Supabase Auth user. Auth is the source of truth; no passwords/OTPs stored here.

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, FK → `auth.users(id)` ON DELETE CASCADE |
| `display_name` | TEXT | NULL CHECK (len 1–120) |
| `role` | TEXT | NOT NULL DEFAULT `'user'` CHECK IN (`user`,`admin`) |
| `preferred_language` | TEXT | NOT NULL DEFAULT `'en'` CHECK IN (`en`,`hi`,`mr`) |
| `home_city` | TEXT | NULL |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

*Indexes: none beyond PK. RLS: enabled (Step 1.7: profiles_select_own, profiles_insert_own, profiles_update_own; column privileges protect `role` from user manipulation).*

## 1.2 `public.operators`
Canonical CPO registry; `stations.operator_id` FKs here (never free text).

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK DEFAULT gen_random_uuid() |
| `name` | TEXT | NOT NULL CHECK (len 1–200) |
| `slug` | TEXT | UNIQUE CHECK (len 1–200); `chk_operators_slug_format` (safe token regex) |
| `website_url`, `support_phone` | TEXT | NULL |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

## 1.3 `public.stations`
One row = one physical charging location. Live availability/ratings/predictions are derived elsewhere, never stored here.

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK DEFAULT gen_random_uuid() |
| `slug` | TEXT | UNIQUE; `chk_stations_slug_format` (safe token regex) |
| `name` | TEXT | NOT NULL CHECK (len 1–300) |
| `operator_id` | UUID | NOT NULL FK → `operators(id)` RESTRICT |
| `address_line`, `locality` | TEXT | NULL |
| `city` | TEXT | NOT NULL DEFAULT `'Mumbai'` CHECK (len 1–120) |
| `state` | TEXT | NOT NULL DEFAULT `'Maharashtra'` CHECK (len 1–120) |
| `postal_code` | TEXT | NULL CHECK matches `^[1-9][0-9]{5}$` (Indian 6-digit, leading zeros preserved) |
| `country` | TEXT | NOT NULL DEFAULT `'India'` CHECK (len 1–120) |
| `latitude` / `longitude` | DOUBLE PRECISION | NOT NULL CHECK lat −90…90, lng −180…180 |
| `geom` | geography(Point,4326) | NOT NULL; maintained by `trg_stations_geom` from (longitude, latitude) |
| `opening_time` / `closing_time` | TIME | NULL |
| `is_24_hours` | BOOLEAN | NOT NULL DEFAULT FALSE |
| `access_type` | TEXT | NULL |
| `is_public` | BOOLEAN | NOT NULL DEFAULT TRUE |
| `operational_status` | TEXT | NOT NULL DEFAULT `'unknown'` CHECK IN (`unknown`,`operational`,`temporarily_unavailable`,`permanently_closed`) |
| `phone`, `website_url` | TEXT | NULL |
| `last_verified_at` | TIMESTAMPTZ | NULL |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Constraint `chk_stations_hours`:** `is_24_hours` ⟺ both opening/closing NULL, or both present when not 24h.  
**Constraint `chk_stations_slug_format`:** `slug IS NULL OR slug ~ '^[a-zA-Z0-9][a-zA-Z0-9_-]*$'`.  
*Indexes: `idx_stations_geom` (GIST), `idx_stations_city`, `idx_stations_operator`, `idx_stations_slug`.*  
*Trigger: `trg_stations_geom` → `set_stations_geom()`.*

## 1.4 `public.connectors`
Static capacity groups per station (no live state); availability lives in `station_observations`.

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK DEFAULT gen_random_uuid(); part of superkey `uq_connectors_id_station` |
| `station_id` | UUID | NOT NULL FK → `stations(id)` RESTRICT; part of superkey `uq_connectors_id_station` |
| `connector_type` | TEXT | NOT NULL CHECK IN (`CCS2`,`CHAdeMO`,`Type 2`,`Type 1`,`GB/T`,`Bharat AC001`,`Bharat DC001`) |
| `charging_standard` | TEXT | NULL |
| `power_kw` | NUMERIC(8,2) | NOT NULL CHECK > 0 |
| `quantity` | INTEGER | NOT NULL CHECK > 0 |
| `pricing_type` | TEXT | NULL |
| `price_per_kwh` / `price_per_session` | NUMERIC(10,2) | NULL CHECK ≥ 0 |
| `currency` | TEXT | NOT NULL DEFAULT `'INR'` CHECK (len 1–10) |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Constraint `uq_connectors_id_station`:** UNIQUE `(station_id, id)` (enables composite connector ownership FKs).  
*Indexes: `idx_connectors_station`, unique index `uq_connectors_station_type_power (station_id, connector_type, power_kw, COALESCE(charging_standard, ''))`.*  
*Note: `is_fast_charging` exists only in the warehouse (`analytics.dim_connector`), NOT here.*

## 1.5 `public.data_sources`
External feed registry (no seed rows in Phase 1).

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK DEFAULT gen_random_uuid() |
| `name` | TEXT | NOT NULL UNIQUE CHECK (len 1–120) |
| `source_type` | TEXT | NOT NULL CHECK (len 1–120) |
| `base_url` | TEXT | NULL |
| `source_priority` | INTEGER | NOT NULL DEFAULT 100 (reserved for future conflict resolution) |
| `is_active` | BOOLEAN | NOT NULL DEFAULT TRUE |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

## 1.6 `public.station_source_link`
Canonical ↔ source identity map (provenance). Source IDs are internal only, never canonical frontend IDs.

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK DEFAULT gen_random_uuid() |
| `station_id` | UUID | NOT NULL FK → `stations(id)` RESTRICT |
| `source_id` | UUID | NOT NULL FK → `data_sources(id)` RESTRICT |
| `source_station_id` | TEXT | NOT NULL CHECK (len 1–500) |
| `source_url` / `first_seen_at` / `last_seen_at` / `last_ingested_at` / `source_payload_hash` | — | NULL |
| `is_active` | BOOLEAN | NOT NULL DEFAULT TRUE |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Constraint `uq_station_source_link_source_record`:** UNIQUE `(source_id, source_station_id)`.  
**Constraint `chk_source_link_seen_range`:** `last_seen_at IS NULL OR first_seen_at IS NULL OR last_seen_at >= first_seen_at`.  
*Index: `idx_station_source_link_station`. (Redundant `idx_station_source_link_source` dropped in Step 1.6 as covered by UNIQUE leading column).*

## 1.7 `public.station_observations`
Append-only system/source observations; feeds future observation facts.

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK DEFAULT gen_random_uuid() |
| `station_id` | UUID | NOT NULL FK → `stations(id)` RESTRICT; part of FK `fk_observations_connector_owner` |
| `connector_id` | UUID | NULL FK → `connectors(id)` RESTRICT; part of FK `fk_observations_connector_owner` |
| `source_id` | UUID | NOT NULL FK → `data_sources(id)` RESTRICT |
| `availability_status` | TEXT | NOT NULL CHECK IN (`available`,`busy`,`broken`,`unknown`) |
| `queue_level` | TEXT | NOT NULL CHECK IN (`none`,`short`,`medium`,`long`,`unknown`) |
| `available_connectors` / `total_connectors` | INTEGER | NULL / NOT NULL, ≥ 0 |
| `observed_at` | TIMESTAMPTZ | NOT NULL |
| `received_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| `confidence_score` | NUMERIC(5,4) | NULL CHECK 0–1 |
| `source_payload_hash` | TEXT | NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Constraint `chk_station_observations_counts`:** `available_connectors <= total_connectors` when present.  
**Constraint `chk_observations_causal_time`:** `received_at >= observed_at`.  
**Foreign Key `fk_observations_connector_owner`:** `(station_id, connector_id) REFERENCES public.connectors (station_id, id)`.  
*Indexes: `idx_station_observations_station_time`, `..._connector_time`, `..._source_time` (observed_at DESC).*

## 1.8 `public.user_reports`
Append-only authenticated community reports; never overwrites stations/connectors.

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK DEFAULT gen_random_uuid() |
| `user_id` | UUID | NOT NULL FK → `profiles(id)` ON DELETE CASCADE |
| `station_id` | UUID | NOT NULL FK → `stations(id)` RESTRICT; part of FK `fk_reports_connector_owner` |
| `connector_id` | UUID | NULL FK → `connectors(id)` RESTRICT; part of FK `fk_reports_connector_owner` |
| `availability_status` | TEXT | NOT NULL CHECK IN (`available`,`busy`,`broken`,`unknown`) |
| `queue_level` | TEXT | NOT NULL CHECK IN (`none`,`short`,`medium`,`long`,`unknown`) |
| `comment` / `moderation_reason` | TEXT | NULL |
| `observed_at` / `created_at` | TIMESTAMPTZ | NOT NULL |
| `is_flagged` | BOOLEAN | NOT NULL DEFAULT FALSE |
| `moderation_status` | TEXT | NOT NULL DEFAULT `'pending'` CHECK IN (`pending`,`approved`,`rejected`) |
| `moderated_by` | UUID | NULL, **no FK** (audit survives moderator deletion) |
| `moderated_at` | TIMESTAMPTZ | NULL |

**Constraint `chk_report_created_after_observed`:** `created_at >= observed_at`.  
**Foreign Key `fk_reports_connector_owner`:** `(station_id, connector_id) REFERENCES public.connectors (station_id, id)`.  
**Constraint `chk_user_reports_moderation_audit`:** pending has no decision fields; approved/rejected requires `moderated_at`.  
**Constraint `chk_user_reports_rejection_reason`:** rejected requires `moderation_reason`.  
*Indexes: `idx_user_reports_station_time`, `idx_user_reports_user_time`, `idx_user_reports_pending` (partial index `WHERE moderation_status = 'pending'`).*

## 1.9 `public.reviews`
Experience feedback only (NOT availability labels).

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK DEFAULT gen_random_uuid() |
| `user_id` | UUID | NOT NULL FK → `profiles(id)` ON DELETE CASCADE |
| `station_id` | UUID | NOT NULL FK → `stations(id)` RESTRICT |
| `rating` | INTEGER | NOT NULL CHECK 1–5 |
| `comment` / `moderation_reason` | TEXT | NULL |
| `is_flagged` | BOOLEAN | NOT NULL DEFAULT FALSE |
| `moderation_status` | TEXT | NOT NULL DEFAULT `'pending'` CHECK IN (`pending`,`approved`,`rejected`) |
| `moderated_by` | UUID | NULL, no FK |
| `moderated_at` | TIMESTAMPTZ | NULL |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Constraint `uq_reviews_user_station`:** UNIQUE `(user_id, station_id)` (one review per user per station).  
**Constraint `chk_reviews_moderation_audit`:** pending has no decision fields; approved/rejected requires `moderated_at`.  
**Constraint `chk_reviews_rejection_reason`:** rejected requires `moderation_reason`.  
*Indexes: `idx_reviews_station (station_id, created_at DESC)` (optimized composite). (Redundant `idx_reviews_user` dropped in Step 1.6 as covered by UNIQUE leading column).*

## 1.10 `public.favorites`
Saved-stations join; composite PK prevents duplicates.

| Column | Type | Constraints |
|---|---|---|
| `user_id` | UUID | FK → `profiles(id)` ON DELETE CASCADE; part of PK |
| `station_id` | UUID | FK → `stations(id)` ON DELETE CASCADE; part of PK |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**PK:** `pk_favorites (user_id, station_id)`.  
*Index: `idx_favorites_station`. (Redundant `idx_favorites_user` dropped in Step 1.6 as covered by PK leading column).*

## 1.11 `public.alerts`
User watch conditions (no delivery log yet; `notification_events` deferred).

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK DEFAULT gen_random_uuid() |
| `user_id` | UUID | NOT NULL FK → `profiles(id)` ON DELETE CASCADE |
| `station_id` | UUID | NULL FK → `stations(id)` ON DELETE CASCADE (NULL = nearby/watchlist alert) |
| `alert_type` | TEXT | NOT NULL CHECK IN (`station_available`,`station_status_change`,`congestion_threshold`,`nearby_station_change`) |
| `params` | JSONB | NOT NULL DEFAULT `'{}'` CHECK `jsonb_typeof = 'object'` |
| `threshold_value` | NUMERIC | NULL; `chk_alerts_threshold_positive` (>= 0) |
| `is_enabled` | BOOLEAN | NOT NULL DEFAULT TRUE |
| `last_triggered_at` | TIMESTAMPTZ | NULL |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Constraint `chk_alerts_threshold_positive`:** `threshold_value IS NULL OR threshold_value >= 0`.  
*Indexes: `idx_alerts_user`, `idx_alerts_station`.*

---

# 2. `analytics` schema — data warehouse OLAP (12 tables)

Canonical DW documentation: `docs/data_warehouse.md`. Rules: no frontend writes; no cross-layer FKs; append-only idempotent facts; surrogate keys; only approved reports/reviews reach facts; no-evidence days produce no `fact_station_daily` row.

## 2.1 `analytics.dim_operator` — SCD Type 1
GRAIN: one row per operator. Business key `operator_id` → `public.operators.id` (via ETL, no FK).

`operator_key BIGINT identity PK`, `operator_id UUID NOT NULL UNIQUE`, `operator_name TEXT NOT NULL`, `slug`, `website_url`, `support_phone`, `created_at`, `updated_at`.

## 2.2 `analytics.dim_location` — SCD Type 1
GRAIN: one row per locality/location. Natural key `(country, state, city, locality, postal_code)`.

`location_key BIGINT identity PK`, `city NOT NULL`, `state NOT NULL`, `country NOT NULL DEFAULT 'India'`, `locality`, `postal_code`, `created_at`, `updated_at`.  
**UNIQUE index `uq_dim_location_natural`** on `(country, state, city, COALESCE(locality,''), COALESCE(postal_code,''))`.

## 2.3 `analytics.dim_station` — SCD Type 2 (versioned)
GRAIN: one row per VERSION of one physical station.

`station_key BIGINT identity PK`, `station_id UUID NOT NULL`, `station_name TEXT NOT NULL`, `operator_key → dim_operator`, `location_key → dim_location`, `latitude/longitude NOT NULL`, `address`, `access_type`, `is_public`, `operational_status`, `is_24_hours`, `opening_time`, `closing_time`, `effective_from/effective_to`, `is_current`, `version >= 1`, `created_at`, `updated_at`.
- **UNIQUE partial index `uq_dim_station_current`** on `(station_id) WHERE is_current`.
- `chk_dim_station_scd_range`, `chk_dim_station_current_open`.
- **Constraint `chk_dim_station_hours`:** Operating hours mirror of public.stations.
- *Indexes: `idx_dim_station_business_lookup`, `idx_dim_station_operator`, `idx_dim_station_location`, `idx_dim_station_effective (station_id, effective_from, effective_to)`.*

## 2.4 `analytics.dim_connector` — SCD Type 1 (initially)
GRAIN: one row per operational connector (static capacity group).

`connector_key BIGINT identity PK`, `connector_id UUID NOT NULL UNIQUE`, `station_id UUID NOT NULL` (business reference, not a FK), `connector_type`, `charging_standard`, `power_kw > 0`, `quantity > 0`, `pricing_type`, `price_per_kwh/price_per_session ≥ 0`, `currency DEFAULT 'INR'`, `is_fast_charging BOOLEAN NULL`, `created_at`, `updated_at`.  
**Constraint `chk_dim_connector_type`:** Enforces connector vocabulary parity (`CCS2`, `CHAdeMO`, `Type 2`, `Type 1`, `GB/T`, `Bharat AC001`, `Bharat DC001`).  
*Index: `idx_dim_connector_station`.*

## 2.5 `analytics.dim_date` — static conformed date dimension
GRAIN: one calendar date per row. `date_key INTEGER PK` = YYYYMMDD.

`full_date DATE UNIQUE`, `year`, `quarter`, `month`, `month_name`, `week` (ISO), `day_of_month`, `day_of_week` (ISO 1=Mon…7=Sun), `day_name`, `is_weekend`.  
**Constraint `chk_dim_date_self_consistent`:** Guarantees date_key, calendar components, names, and weekend flag match full_date via immutable expressions.  
**Seeded: 2024-01-01 … 2032-12-31 = 3,288 rows** (deterministic reference data).

## 2.6 `analytics.dim_time` — static conformed time dimension, 15-minute grain
GRAIN: exactly 96 rows per day, slot start HH24:MI.

`time_key SMALLINT PK CHECK 0–95`, `hour`, `minute IN (0,15,30,45)`, `slot_15min` (start-of-slot label), `time_of_day IN (night,morning,afternoon,evening)`.  
**Constraint `chk_dim_time_self_consistent`:** Guarantees time_key = hour * 4 + minute / 15, slot_15min, and time_of_day bucket consistency.  
**Seeded: 96 rows** (deterministic reference data).

## 2.7 `analytics.dim_source` — SCD Type 1
GRAIN: one row per data source (feed registry mirror); lineage axis for facts.

`source_key BIGINT identity PK`, `source_id UUID NOT NULL UNIQUE` (→ `public.data_sources.id`, no FK), `name`, `source_type`, `source_priority`, `is_active`, `base_url`, `created_at`, `updated_at`.

## 2.8 `analytics.dim_weather` — SCD Type 1 (structural placeholder)
GRAIN: one row per weather observation/condition representation. **No weather adapter exists in Phase 1 → no rows seeded; `weather_key` stays NULLABLE** (NULL = unknown, never clear).

`weather_key BIGINT identity PK`, `temperature_c`, `humidity_pct [0,100]`, `precipitation_mm ≥ 0`, `wind_speed_kph ≥ 0`, `weather_condition`, `created_at`, `updated_at`.

## 2.9 `analytics.fact_station_observation` — append-only, idempotent
EXACT GRAIN: one row = one `public.station_observations` row. Business key `observation_id`.

`observation_key BIGINT identity PK`, `observation_id UUID NOT NULL UNIQUE`, `station_key → dim_station`, `connector_key → dim_connector NULL`, `date_key → dim_date`, `time_key → dim_time`, `source_key → dim_source`, `weather_key → dim_weather NULL`, `observed_at`, `received_at`, `availability_status`, `queue_level`, `available_connectors`, `total_connectors`, `confidence_score 0–1`, `source_payload_hash`, `created_at`.  
**Constraint `chk_fact_observation_counts`:** `available_connectors <= total_connectors`.  
**Constraint `chk_fact_observation_causal_time`:** `received_at >= observed_at`.  
**Constraint `chk_fact_observation_dim_alignment`:** `date_key` and `time_key` align with `observed_at AT TIME ZONE 'UTC'`.  
*Indexes: `idx_fso_station_date`, `idx_fso_date`, `idx_fso_source`.*

## 2.10 `analytics.fact_user_report` — append-only, approved reports only
EXACT GRAIN: one row = one APPROVED `public.user_reports` row. Business key `report_id`. **No PII**.

`report_key BIGINT identity PK`, `report_id UUID NOT NULL UNIQUE`, `station_key → dim_station`, `connector_key → dim_connector NULL`, `date_key`, `time_key`, `observed_at`, `availability_status`, `queue_level`, `report_count SMALLINT = 1`, `moderation_status = 'approved'`, `moderated_at`, `is_flagged`, `created_at`.  
**Constraint `chk_fact_report_dim_alignment`:** `date_key` and `time_key` align with `observed_at AT TIME ZONE 'UTC'`.  
**Constraint `chk_fact_report_moderated`:** `moderated_at IS NOT NULL`.  
*Indexes: `idx_fur_station_date`, `idx_fur_date`.*

## 2.11 `analytics.fact_review` — append-only, approved reviews only
EXACT GRAIN: one row = one APPROVED `public.reviews` row. Business key `review_id`. No PII.

`review_key BIGINT identity PK`, `review_id UUID NOT NULL UNIQUE`, `station_key → dim_station`, `date_key`, `rating 1–5`, `review_count = 1`, `moderation_status = 'approved'`, `moderated_at`, `created_at`.  
**Constraint `chk_fact_review_moderated`:** `moderated_at IS NOT NULL`.  
*Indexes: `idx_fr_station_date`, `idx_fr_date`.*

## 2.12 `analytics.fact_station_daily` — primary daily OLAP / future ML aggregate
EXACT GRAIN: one row = one `station_key × date_key` WITH evidence. No row for no-evidence days.

| Column | Type | Notes |
|---|---|---|
| `station_key` / `date_key` | BIGINT / INTEGER | composite PK `pk_fact_station_daily` |
| `observation_count`, `report_count`, `review_count`, `available_count`, `busy_count`, `broken_count`, `source_count` | INTEGER ≥ 0 | **ADDITIVE** (safe to SUM) |
| `availability_ratio`, `busy_ratio`, `broken_ratio` | NUMERIC(5,4) 0–1 | **NON-ADDITIVE** (never SUM) |
| `avg_queue_score`, `peak_queue_score` | NUMERIC(5,4) 0–1 | NON-ADDITIVE |
| `avg_rating` | NUMERIC(3,2) 1–5 | NON-ADDITIVE |
| `data_completeness_score` | NUMERIC(5,4) 0–1 | NON-ADDITIVE |
| `maturity` | TEXT | `cold` / `warming` / `ready` — descriptive, gates ML |
| `has_evidence` | BOOLEAN | always TRUE for stored rows |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL |

**Constraint `chk_fact_daily_status_counts`:** `available_count + busy_count + broken_count <= observation_count`.  
*Index: `idx_fsd_date`.*

---

# 3. `ml` schema — ML metadata/control (6 tables)

ML layer rules: metadata only (no model bytes, no synthetic data, no fake predictions); all FKs stay inside `ml`; cross-layer keys are plain business-key columns without `REFERENCES`; `data_maturity` aligns with `analytics.fact_station_daily.maturity`.

## 3.1 `ml.features` — feature definitions
GRAIN: one row per feature definition. Business key `feature_name` (UNIQUE).

`feature_key UUID PK`, `feature_name TEXT UNIQUE`, `feature_type`, `feature_group`, `units`, `description`, `generated_by`, `formula`, `source_column`, `is_active`, `created_at`, `updated_at`.  
*Index: `idx_ml_features_group`. (Duplicate `idx_ml_features_name` dropped in Step 1.6 as covered by UNIQUE feature_name).*

## 3.2 `ml.datasets` — dataset/training-data version metadata
GRAIN: one row per dataset version. Business key `(dataset_name, version_str)`.

`dataset_key UUID PK`, `dataset_name`, `version_str`, `description`, `source`, `time_range_start`/`time_range_end` (inclusive), `row_count ≥ 0`, `feature_count ≥ 0`, `data_maturity IN (cold,warming,ready)`, `is_training`/`is_validation`/`is_test`, `created_at`, `updated_at`.  
**UNIQUE `uq_datasets_name_version`.**  
**Constraint `chk_datasets_time_range`:** `time_range_end >= time_range_start`.  
*Index: `idx_ml_datasets_maturity`. (Duplicate `idx_ml_datasets_name` dropped in Step 1.6 as covered by UNIQUE `uq_datasets_name_version`).*

## 3.3 `ml.experiments` — ML experiments
GRAIN: one row per experiment run. Business key `experiment_name` (UNIQUE).

`experiment_key UUID PK`, `experiment_name UNIQUE`, `description`, `dataset_key UUID`, `status IN (proposed,running,completed,failed)`, `started_at`, `completed_at`, `created_at`, `updated_at`.  
**Foreign Key `fk_experiments_dataset`:** `(dataset_key) REFERENCES ml.datasets (dataset_key) ON DELETE RESTRICT`.  
**Constraint `chk_experiments_lifecycle`:** Timestamps must agree with lifecycle status.  
*Indexes: `idx_ml_experiments_dataset`, `idx_ml_experiments_status`.*

## 3.4 `ml.model_versions` — model versions/runs with lifecycle + data maturity
GRAIN: one row per model version/run. Business key `(experiment_key, version_str)`.

`model_key UUID PK`, `experiment_key UUID FK → ml.experiments ON DELETE CASCADE`, `version_str`, `model_type`, `status`, `data_maturity`, `trained_at`, `completed_at`, `artifact_location`, `training_dataset_key`/`eval_dataset_key UUID FK → ml.datasets ON DELETE SET NULL`, `feature_keys UUID[]`, `created_at`, `updated_at`.  
- **UNIQUE `uq_modelversions_experiment_version`** `(experiment_key, version_str)`.  
- **CHECK `chk_model_maturity_status`:** `status='ready'` requires `data_maturity IN (warming, ready)`.  
- **CHECK `chk_model_ready_gate`:** `status='ready'` requires `trained_at`, `completed_at`, `training_dataset_key`, and `eval_dataset_key`.  
*Indexes: `idx_ml_modelversions_status`, `..._maturity`, `..._trained` (partial), `idx_ml_modelversions_training_dataset`, `idx_ml_modelversions_eval_dataset`. (Redundant `idx_ml_modelversions_experiment` dropped in Step 1.6 as covered by UNIQUE leading column).*

## 3.5 `ml.metrics` — model evaluation metrics
GRAIN: one row per metric recording (name/value/split).

`metric_key UUID PK`, `model_key UUID FK → ml.model_versions ON DELETE CASCADE`, `metric_name`, `metric_value NUMERIC(12,6)`, `split IN (train,validation,test,holdout)`, `epoch_or_step`, `created_at`, `updated_at`.  
**UNIQUE `uq_metrics_model_name_split` `(model_key, metric_name, split)`.**  
*Index: `idx_ml_metrics_name_split`. (Redundant `idx_ml_metrics_model` dropped in Step 1.6 as covered by UNIQUE leading column).*

## 3.6 `ml.prediction_runs` — prediction-run metadata (not values)
GRAIN: one row per prediction-run metadata.

`prediction_run_key UUID PK`, `model_key UUID FK → ml.model_versions ON DELETE CASCADE`, `station_id UUID NULL`, `date_key INTEGER NULL`, `time_key SMALLINT NULL`, `prediction_horizon`, `run_at TIMESTAMPTZ`, `status`, `created_at`, `updated_at`.  
**UNIQUE `uq_predictionruns_model_station_datetime` `(model_key, station_id, date_key, time_key, run_at)`.**  
*Indexes: `idx_ml_predictionruns_station_date`, `..._horizon`, `..._run_at`. (Redundant `idx_ml_predictionruns_model` dropped in Step 1.6 as covered by UNIQUE leading column).*

---

# 4. Step 1.6 Reconciled Inventory Summary

| Layer | Tables | Active Explicit Indexes | Key Constraints Enforced in Step 1.6 |
|---|---|---|---|
| `public` | 11 | 17 (1 GIST, 1 partial, 15 b-tree) | 13 ADD CONSTRAINT + 1 Unique Index: Causality (`chk_observations_causal_time`, `chk_report_created_after_observed`), connector ownership superkey (`uq_connectors_id_station`) + 2 composite FKs (`fk_observations_connector_owner`, `fk_reports_connector_owner`), capacity uniqueness (`uq_connectors_station_type_power`), moderation consistency & reason checks (reports & reviews), slug format regex, alert threshold non-negative, source chronology |
| `analytics` | 12 | 15 (2 UNIQUE, 13 b-tree) | 10 ADD CONSTRAINT: SCD2 effective-range index (`idx_dim_station_effective`), hours mirror, connector vocabulary parity, deterministic surrogate-key self-consistency (immutable), fact causality, UTC alignment, moderation provenance, daily status-count conservation |
| `ml` | 6 | 13 (all b-tree) | 4 ADD CONSTRAINT: Intra-layer FK (`fk_experiments_dataset`), FK-supporting indexes (`training_dataset_key`, `eval_dataset_key`), lifecycle timestamps, dataset time range, model ready-gate |
| **Total** | **29** | **45 explicit indexes** | **28 total constraints** (27 ADD CONSTRAINT + 1 Unique Index) |
*Execution note: Step 1.6 migration executed and fully verified against linked Supabase project as one atomic transaction (initial attempt rolled back due to false-positive information_schema join; corrected to pg_catalog).*

---

# 5. Step 1.8 Views & Functions Inventory

All objects created in Step 1.8 migration `supabase/migrations/20260925000001_step_1_8_views_functions.sql`.

| Schema | Object Name | Type | Security Mode | Access Grants | Description & Boundary Guarantee |
|---|---|---|---|---|---|
| `public` | `get_author_display_name(author_id uuid)` | Function | `SECURITY DEFINER`<br>`SET search_path = public, pg_temp` | `EXECUTE`: `anon, authenticated, service_role` | Returns sanitized author nickname for approved reviews without exposing `profiles` table or auth UUIDs. |
| `public` | `v_station_current_state` | View | `WITH (security_invoker = true)` | `SELECT`: `anon, authenticated, service_role` | Composes physical station metadata, operator details, connector capacity summary, latest live observation status, derived freshness, and approved review metrics. Zero fake data; observations default to NULL when absent. |
| `public` | `v_station_connectors` | View | `WITH (security_invoker = true)` | `SELECT`: `anon, authenticated, service_role` | Exposes connector specifications per station alongside latest connector-level live observation (if present). |
| `public` | `v_station_approved_reviews` | View | `WITH (security_invoker = true)` | `SELECT`: `anon, authenticated, service_role` | Public feed of approved driver reviews with author display names. Deliberately hides `user_id`, `moderated_by`, `moderation_reason`, and unapproved reviews. |
| `public` | `nearby_stations(user_lat, user_lng, radius_meters, max_results)` | Function | `SECURITY INVOKER`<br>`SET search_path = public, extensions, pg_temp` | `EXECUTE`: `anon, authenticated, service_role` | PostGIS spatial discovery utilizing GIST index `idx_stations_geom` on `stations.geom`. Bounded radius (max 200km) and limit (max 100). |
| `analytics` | `v_station_daily_summary` | View | `WITH (security_invoker = true)` | `SELECT`: `service_role` only | OLAP star-schema reporting view joining `fact_station_daily` with `dim_date`, `dim_station`, and `dim_operator` for Python ETL and BI tools. No client access. |

---

## Cross-references

- Authoritative Migrations:
  - `supabase/migrations/20260918000001_step_1_3_core_operational_schema.sql`
  - `supabase/migrations/20260922000001_step_1_4_analytics_warehouse_schema.sql`
  - `supabase/migrations/20260922000001_step_1_5_ml_metadata_schema.sql`
  - `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`
  - `supabase/migrations/20260924000001_step_1_7_rls_security_policies.sql`
  - `supabase/migrations/20260925000001_step_1_8_views_functions.sql`
- Warehouse grain/SCD/ETL design: `docs/data_warehouse.md`.
- Step 1.6 synthesis audit report: `docs/step_1_6_constraints_indexes_audit.md`.
- Step 1.8 views & functions audit: `docs/step_1_8_views_functions_audit.md`.
- Conceptual architecture & rules: `Must Read/Architecture.md`, `Must Read/PRD.md`, `Must Read/Rules.md`, `Must Read/Phases.md`.