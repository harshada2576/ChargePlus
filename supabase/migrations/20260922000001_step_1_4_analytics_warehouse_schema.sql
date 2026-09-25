-- ============================================================================
-- ChargePlus Step 1.4 — Analytics / Data Warehouse schema
-- Phase 1/6 Step 1.4/10
-- ============================================================================
--
-- ARCHITECTURAL LOCK — READ FIRST:
--
--   public    = OPERATIONAL DATABASE (OLTP)
--               Current application/product state and operational history.
--               Tables: profiles, operators, stations, connectors, data_sources,
--               station_source_link, station_observations, user_reports, reviews,
--               favorites, alerts (Step 1.3). Frontend reads/writes live here
--               (subject to Step 1.7 RLS).
--
--   analytics = DATA WAREHOUSE (OLAP)
--               Historical facts, conformed dimensions, aggregates, OLAP, and
--               later ML feature preparation. Populated ONLY by Python ETL jobs
--               that move legitimate historical operational data into this
--               layer using business-key / surrogate-key mapping. There are NO
--               frontend writes to analytics tables, and NO cross-layer foreign
--               keys (e.g. analytics.station_key -> public.stations.id is
--               FORBIDDEN). The warehouse is a separate logical layer.
--
--   The whole Supabase/PostgreSQL database is NOT "the data warehouse".
--   Only the analytics schema is the warehouse.
--
-- LEGACY SAFETY (ABSOLUTE RULE):
--   The following pre-existing public tables are EMPTY and remain UNTOUCHED
--   and future-reserved where applicable:
--     public.dim_date, public.dim_location, public.dim_station,
--     public.dim_tariff, public.dim_time, public.dim_vehicle,
--     public.dim_weather, public.fact_charging_session,
--     public.fact_station_daily_agg.
--   This file contains NO DROP, NO ALTER, NO RENAME, NO TRUNCATE, NO INSERT,
--   NO UPDATE, and NO DELETE touching any of those tables. They are referenced
--   here in comments ONLY; no executable statement in this file names them.
--
-- SCOPE OF THIS FILE:
--   Creates schema `analytics` with 8 dimensions and 4 facts (12 tables):
--     dims : dim_station (SCD2), dim_operator, dim_location, dim_connector,
--            dim_date (static), dim_time (static), dim_source, dim_weather
--     facts: fact_station_observation, fact_user_report, fact_review,
--            fact_station_daily (append-only, idempotent by business key)
--   Seeds ONLY the deterministic reference dimensions dim_date (2024-01-01
--   through 2032-12-31 = 3288 rows) and dim_time (96 fifteen-minute rows).
--   NO stations, connectors, observations, reports, reviews, weather,
--   sessions, prices, or predictions are inserted here.
--
-- EXPLICITLY OUT OF SCOPE (later steps/phases):
--   RLS, Python ETL execution, ingestion jobs, ML, forecasting,
--   recommendations, weather ingestion, charging sessions, synthetic data of
--   any kind, warehouse retention deletion, hourly streaming,
--   analytics.dim_user, analytics.dim_vehicle, analytics.dim_tariff,
--   analytics.fact_charging_session, analytics.fact_forecast,
--   analytics.fact_station_hourly.
--
-- KEY DESIGN RULES APPLIED:
--   1. No frontend writes to analytics (enforced later via grants/RLS;
--      by default the Supabase anon/authenticated roles hold no privileges
--      on this new schema until a later step grants read access).
--   2. No cross-layer foreign keys. All REFERENCES below stay inside the
--      analytics schema. ETL resolves public UUIDs -> warehouse keys.
--   3. Every dimension has a surrogate key; business keys are also retained.
--   4. Grain + additivity documented via COMMENTs on every table/measure.
--   5. Indexes target business keys, SCD lookups, and fact (station, date)
--      access paths only. No over-indexing.
--   6. Facts are append-only and idempotent by business key (UNIQUE on the
--      operational UUID). No triggers populate facts.
--
-- IDEMPOTENCY: safe to re-run (IF NOT EXISTS guards + ON CONFLICT DO NOTHING
-- seeds + a final assertion block that raises on seed-count mismatch).
-- Under Supabase CLI this file runs once via supabase_migrations history.
--
-- LOAD ORDER INSIDE THIS FILE (intra-warehouse FK dependencies):
--   dim_operator, dim_location -> dim_station (SCD2 snowflake refs)
--   dim_date, dim_time, dim_source, dim_weather, dim_connector (independent)
--   facts last (reference dims only).
--   Python ETL must respect the same order.
-- ============================================================================

-- ============================================================================
-- 0. Schema
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS analytics;
COMMENT ON SCHEMA analytics IS
'Step 1.4: DATA WAREHOUSE / OLAP layer. Historical facts, conformed dimensions, aggregates, OLAP and future ML feature preparation. Separate logical layer from the public OLTP database; populated only by Python ETL, never by frontend writes.';

-- ============================================================================
-- 1. analytics.dim_operator — SCD Type 1 (overwrite in place)
-- GRAIN: one row per operator (charging-network organisation).
-- Business key: operator_id (-> public.operators.id via ETL; no cross-layer FK).
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.dim_operator (
  operator_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  operator_id  UUID NOT NULL UNIQUE,
  operator_name TEXT NOT NULL CHECK (char_length(operator_name) BETWEEN 1 AND 200),
  slug          TEXT NULL,
  website_url   TEXT NULL,
  support_phone TEXT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE analytics.dim_operator IS
'GRAIN: one row per operator. SCD Type 1: attribute changes overwrite in place (no history). Business key operator_id maps to public.operators.id via ETL; no cross-layer FK.';

-- ============================================================================
-- 2. analytics.dim_location — SCD Type 1 (overwrite in place)
-- GRAIN: one row per locality/location analytical entity.
-- Natural key: (country, state, city, locality, postal_code); surrogate key
-- retained for joins. NULL locality/postal_code normalised via COALESCE in
-- the uniqueness index so SCD1 lookups stay deterministic.
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.dim_location (
  location_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  city         TEXT NOT NULL CHECK (char_length(city) BETWEEN 1 AND 120),
  state        TEXT NOT NULL CHECK (char_length(state) BETWEEN 1 AND 120),
  country      TEXT NOT NULL DEFAULT 'India' CHECK (char_length(country) BETWEEN 1 AND 120),
  locality     TEXT NULL,
  postal_code  TEXT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dim_location_natural
  ON analytics.dim_location (country, state, city, COALESCE(locality, ''), COALESCE(postal_code, ''));
COMMENT ON TABLE analytics.dim_location IS
'GRAIN: one row per locality/location analytical entity (country/state/city/locality/postal_code). SCD Type 1: changes overwrite in place. Maps from public.stations address fields via ETL.';

-- ============================================================================
-- 3. analytics.dim_station — SCD Type 2 (versioned history)
-- GRAIN: one row per VERSION of one physical station.
-- Business key: station_id (-> public.stations.id via ETL; no cross-layer FK).
-- Tracked SCD2 attributes: station name, operator, address/location,
-- operational status, public/private status, opening/closing hours, access
-- attributes. A change to any of these closes the current version
-- (effective_to = change time, is_current = false) and opens a new version.
-- INVARIANT: exactly one current (is_current, open-ended) version per
-- station_id, enforced by chk_dim_station_current_open + uq_dim_station_current.
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.dim_station (
  station_key        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  station_id         UUID NOT NULL,
  station_name       TEXT NOT NULL CHECK (char_length(station_name) BETWEEN 1 AND 300),
  operator_key       BIGINT NOT NULL REFERENCES analytics.dim_operator (operator_key),
  location_key       BIGINT NOT NULL REFERENCES analytics.dim_location (location_key),
  latitude           DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
  longitude          DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
  address            TEXT NULL,
  access_type        TEXT NULL,
  is_public          BOOLEAN NOT NULL DEFAULT TRUE,
  operational_status TEXT NOT NULL DEFAULT 'unknown'
    CHECK (operational_status IN ('unknown', 'operational', 'temporarily_unavailable', 'permanently_closed')),
  is_24_hours        BOOLEAN NOT NULL DEFAULT FALSE,
  opening_time       TIME NULL,
  closing_time       TIME NULL,
  effective_from     TIMESTAMPTZ NOT NULL DEFAULT now(),
  effective_to       TIMESTAMPTZ NULL,
  is_current         BOOLEAN NOT NULL DEFAULT TRUE,
  version            INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_dim_station_scd_range CHECK (effective_to IS NULL OR effective_to > effective_from),
  CONSTRAINT chk_dim_station_current_open CHECK (
    (is_current AND effective_to IS NULL) OR (NOT is_current AND effective_to IS NOT NULL)
  )
);
-- Exactly one current version per station.
CREATE UNIQUE INDEX IF NOT EXISTS uq_dim_station_current
  ON analytics.dim_station (station_id) WHERE is_current;
-- SCD lookup / point-in-time resolution paths.
CREATE INDEX IF NOT EXISTS idx_dim_station_business_lookup
  ON analytics.dim_station (station_id, is_current);
CREATE INDEX IF NOT EXISTS idx_dim_station_operator ON analytics.dim_station (operator_key);
CREATE INDEX IF NOT EXISTS idx_dim_station_location ON analytics.dim_station (location_key);
COMMENT ON TABLE analytics.dim_station IS
'GRAIN: one row per version of one physical station. SCD Type 2 on name/operator/address/location/operational_status/public-private/hours/access. Facts join on station_key (point-in-time version resolved by ETL), never on the operational UUID directly.';
COMMENT ON COLUMN analytics.dim_station.address IS
'Maps from public.stations.address_line via ETL.';
COMMENT ON COLUMN analytics.dim_station.operational_status IS
'Slowly-changing station facet (open/closed). NEVER conflated with observation availability_status (free/busy right now) or with future predicted congestion.';

-- ============================================================================
-- 4. analytics.dim_connector — SCD Type 1 initially (overwrite in place)
-- GRAIN: one row per operational connector (static capacity group).
-- Business key: connector_id (-> public.connectors.id via ETL; no FK).
-- station_id is a warehouse BUSINESS reference (UUID, no FK to dim_station:
-- dim_station is SCD2-versioned, so ETL resolves station_key point-in-time).
-- These UUIDs are warehouse business keys only; never frontend IDs.
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.dim_connector (
  connector_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  connector_id       UUID NOT NULL UNIQUE,
  station_id         UUID NOT NULL,
  connector_type     TEXT NOT NULL,
  charging_standard  TEXT NULL,
  power_kw           NUMERIC(8, 2) NOT NULL CHECK (power_kw > 0),
  quantity           INTEGER NOT NULL CHECK (quantity > 0),
  pricing_type       TEXT NULL,
  price_per_kwh      NUMERIC(10, 2) NULL CHECK (price_per_kwh IS NULL OR price_per_kwh >= 0),
  price_per_session  NUMERIC(10, 2) NULL CHECK (price_per_session IS NULL OR price_per_session >= 0),
  currency           TEXT NOT NULL DEFAULT 'INR',
  is_fast_charging   BOOLEAN NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dim_connector_station ON analytics.dim_connector (station_id);
COMMENT ON TABLE analytics.dim_connector IS
'GRAIN: one row per operational connector. SCD Type 1 (initially): changes overwrite in place. station_id is a business reference for ETL point-in-time station_key resolution, not a FK.';
COMMENT ON COLUMN analytics.dim_connector.is_fast_charging IS
'DERIVED by ETL (e.g. from power_kw/standard thresholds). No is_fast_charging column exists in public.connectors; never fabricated without a documented rule.';

-- ============================================================================
-- 5. analytics.dim_date — static conformed date dimension
-- GRAIN: one calendar date per row. Surrogate date_key = YYYYMMDD integer.
-- Seeded deterministically below (2024-01-01..2032-12-31 = 3288 rows).
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.dim_date (
  date_key     INTEGER PRIMARY KEY,
  full_date    DATE NOT NULL UNIQUE,
  year         SMALLINT NOT NULL,
  quarter      SMALLINT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
  month        SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
  month_name   TEXT NOT NULL,
  week         SMALLINT NOT NULL CHECK (week BETWEEN 1 AND 53),
  day_of_month SMALLINT NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
  day_of_week  SMALLINT NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),
  day_name     TEXT NOT NULL,
  is_weekend   BOOLEAN NOT NULL
);
COMMENT ON TABLE analytics.dim_date IS
'GRAIN: one row per calendar date (conformed, static). date_key = YYYYMMDD. week = ISO week number; day_of_week = ISO (1=Monday..7=Sunday). Deterministic reference data, seeded by this migration.';
COMMENT ON COLUMN analytics.dim_date.date_key IS
'Additive-neutral conformed key (YYYYMMDD); used as fact aggregate axis, never summed.';

-- ============================================================================
-- 6. analytics.dim_time — static conformed time dimension, 15-minute grain
-- GRAIN: one 15-minute slot per row; exactly 96 rows per day.
-- time_key 0..95 (hour*4 + minute/15). NO second-level rows.
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.dim_time (
  time_key   SMALLINT PRIMARY KEY CHECK (time_key BETWEEN 0 AND 95),
  hour       SMALLINT NOT NULL CHECK (hour BETWEEN 0 AND 23),
  minute     SMALLINT NOT NULL CHECK (minute IN (0, 15, 30, 45)),
  slot_15min TEXT NOT NULL,
  time_of_day TEXT NOT NULL CHECK (time_of_day IN ('night', 'morning', 'afternoon', 'evening'))
);
COMMENT ON TABLE analytics.dim_time IS
'GRAIN: one 15-minute slot per row, exactly 96 rows (00:00..23:45). Conformed, static, deterministic. time_of_day buckets: morning 05:00-11:59, afternoon 12:00-16:59, evening 17:00-20:59, night otherwise.';
COMMENT ON COLUMN analytics.dim_time.slot_15min IS
'Start-of-slot label HH24:MI (e.g. 10:15). Descriptive, non-additive.';

-- ============================================================================
-- 7. analytics.dim_source — SCD Type 1 (overwrite in place)
-- GRAIN: one row per data source (feed registry mirror).
-- Business key: source_id (-> public.data_sources.id via ETL; no cross-layer FK).
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.dim_source (
  source_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id       UUID NOT NULL UNIQUE,
  name            TEXT NOT NULL,
  source_type     TEXT NOT NULL,
  source_priority INTEGER NOT NULL DEFAULT 100,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  base_url        TEXT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE analytics.dim_source IS
'GRAIN: one row per data source. SCD Type 1: registry changes overwrite in place. Lineage axis for facts (which feed an observation/report came through).';

-- ============================================================================
-- 8. analytics.dim_weather — SCD Type 1 (structural placeholder)
-- GRAIN: one row per weather observation/condition representation.
-- No weather adapter and no operational weather contract exist in Phase 1
-- (verified against Step 1.3: no weather table/columns), so this table is a
-- typed placeholder for a future adapter. NO rows are seeded here, no weather
-- values are invented, and every fact weather_key stays NULLABLE.
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.dim_weather (
  weather_key       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  temperature_c     NUMERIC(5, 2) NULL,
  humidity_pct      NUMERIC(5, 2) NULL CHECK (humidity_pct IS NULL OR (humidity_pct >= 0 AND humidity_pct <= 100)),
  precipitation_mm  NUMERIC(8, 2) NULL CHECK (precipitation_mm IS NULL OR precipitation_mm >= 0),
  wind_speed_kph    NUMERIC(8, 2) NULL CHECK (wind_speed_kph IS NULL OR wind_speed_kph >= 0),
  weather_condition TEXT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE analytics.dim_weather IS
'GRAIN: one row per weather observation/condition representation. SCD Type 1. PLACEHOLDER: no weather adapter exists yet, so no rows are seeded and fact weather_key columns are nullable. Vocabulary of weather_condition to be locked when the adapter lands; nothing here is observed data.';

-- ============================================================================
-- 9. analytics.fact_station_observation — append-only, idempotent
-- EXACT GRAIN: one row = one public.station_observations row.
-- Business key: observation_id (= station_observations.id). UNIQUE enforces
-- idempotent ETL reloads. Surrogate key: observation_key.
-- DISTINCTION PRESERVED (never combined):
--   stations.operational_status (station facet: open/closed)
--   != observation availability_status (point-in-time: free/busy right now)
--   != future predicted congestion (ML output, not a fact).
-- Additivity: counts (available/total_connectors) are additive across
-- stations/dates; availability_status/queue_level/confidence are descriptive
-- or non-additive (aggregate via ratios in fact_station_daily, never by
-- averaging averages).
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.fact_station_observation (
  observation_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  observation_id       UUID NOT NULL UNIQUE,
  station_key          BIGINT NOT NULL REFERENCES analytics.dim_station (station_key),
  connector_key        BIGINT NULL REFERENCES analytics.dim_connector (connector_key),
  date_key             INTEGER NOT NULL REFERENCES analytics.dim_date (date_key),
  time_key             SMALLINT NOT NULL REFERENCES analytics.dim_time (time_key),
  source_key           BIGINT NOT NULL REFERENCES analytics.dim_source (source_key),
  weather_key          BIGINT NULL REFERENCES analytics.dim_weather (weather_key),
  observed_at          TIMESTAMPTZ NOT NULL,
  received_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  availability_status  TEXT NOT NULL CHECK (availability_status IN ('available', 'busy', 'broken', 'unknown')),
  queue_level          TEXT NOT NULL CHECK (queue_level IN ('none', 'short', 'medium', 'long', 'unknown')),
  available_connectors INTEGER NULL CHECK (available_connectors IS NULL OR available_connectors >= 0),
  total_connectors     INTEGER NOT NULL CHECK (total_connectors >= 0),
  confidence_score     NUMERIC(5, 4) NULL CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)),
  source_payload_hash  TEXT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_fact_observation_counts CHECK (
    available_connectors IS NULL OR available_connectors <= total_connectors
  )
);
CREATE INDEX IF NOT EXISTS idx_fso_station_date
  ON analytics.fact_station_observation (station_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fso_date ON analytics.fact_station_observation (date_key);
CREATE INDEX IF NOT EXISTS idx_fso_source ON analytics.fact_station_observation (source_key);
COMMENT ON TABLE analytics.fact_station_observation IS
'EXACT GRAIN: one row = one public.station_observations row (observation_id = station_observations.id). Append-only, idempotent by business key. availability_status here is point-in-time observed state, distinct from stations.operational_status and from future predicted congestion.';
COMMENT ON COLUMN analytics.fact_station_observation.confidence_score IS
'Non-additive score (0..1): aggregate with weighted averages only, never SUM.';
COMMENT ON COLUMN analytics.fact_station_observation.weather_key IS
'Nullable: no weather adapter exists yet. NULL means unknown weather, never clear weather.';

-- ============================================================================
-- 10. analytics.fact_user_report — append-only, approved reports only
-- EXACT GRAIN: one row = one APPROVED public.user_reports row.
-- Business key: report_id (= user_reports.id). UNIQUE enforces idempotency.
-- PRIVACY: no user_id, no comment text, no PII of any kind enters the
-- warehouse. Moderation audit columns (moderation_status/moderated_at/
-- is_flagged) are retained WITHOUT identities (moderator UUIDs stay in OLTP).
-- GATE: chk_fact_report_approved guarantees only approved reports become
-- analytical truth; pending/rejected rows must never be loaded here.
-- report_count = 1 always (additive counter for OLAP rollups).
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.fact_user_report (
  report_key          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  report_id           UUID NOT NULL UNIQUE,
  station_key         BIGINT NOT NULL REFERENCES analytics.dim_station (station_key),
  connector_key       BIGINT NULL REFERENCES analytics.dim_connector (connector_key),
  date_key            INTEGER NOT NULL REFERENCES analytics.dim_date (date_key),
  time_key            SMALLINT NOT NULL REFERENCES analytics.dim_time (time_key),
  observed_at         TIMESTAMPTZ NOT NULL,
  availability_status TEXT NOT NULL CHECK (availability_status IN ('available', 'busy', 'broken', 'unknown')),
  queue_level         TEXT NOT NULL CHECK (queue_level IN ('none', 'short', 'medium', 'long', 'unknown')),
  report_count        SMALLINT NOT NULL DEFAULT 1 CHECK (report_count = 1),
  moderation_status   TEXT NOT NULL DEFAULT 'approved' CHECK (moderation_status = 'approved'),
  moderated_at        TIMESTAMPTZ NULL,
  is_flagged          BOOLEAN NOT NULL DEFAULT FALSE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fur_station_date
  ON analytics.fact_user_report (station_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fur_date ON analytics.fact_user_report (date_key);
COMMENT ON TABLE analytics.fact_user_report IS
'EXACT GRAIN: one row = one APPROVED public.user_reports row (report_id = user_reports.id). Append-only, idempotent. No PII. Pending/rejected reports must never be loaded here (enforced by chk_fact_report_approved).';
COMMENT ON COLUMN analytics.fact_user_report.report_count IS
'Additive fact (=1 per row): SUM(report_count) = approved report volume.';

-- ============================================================================
-- 11. analytics.fact_review — append-only, approved reviews only
-- EXACT GRAIN: one row = one APPROVED public.reviews row.
-- Business key: review_id (= reviews.id). UNIQUE enforces idempotency.
-- Reviews stay analytically SEPARATE from availability/busy-state facts:
-- rating answers experience quality, never station busyness.
-- PRIVACY: no user_id, no comment text. review_count = 1 (additive).
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.fact_review (
  review_key        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  review_id         UUID NOT NULL UNIQUE,
  station_key       BIGINT NOT NULL REFERENCES analytics.dim_station (station_key),
  date_key          INTEGER NOT NULL REFERENCES analytics.dim_date (date_key),
  rating            SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  review_count      SMALLINT NOT NULL DEFAULT 1 CHECK (review_count = 1),
  moderation_status TEXT NOT NULL DEFAULT 'approved' CHECK (moderation_status = 'approved'),
  moderated_at      TIMESTAMPTZ NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fr_station_date
  ON analytics.fact_review (station_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fr_date ON analytics.fact_review (date_key);
COMMENT ON TABLE analytics.fact_review IS
'EXACT GRAIN: one row = one APPROVED public.reviews row (review_id = reviews.id). Append-only, idempotent. Experience feedback only; never mixed with availability/busy-state analysis.';
COMMENT ON COLUMN analytics.fact_review.rating IS
'Semi-additive at best: SUM(rating) is meaningless. Use AVG/SUM pairs via fact_station_daily.avg_rating (non-additive aggregate) or recompute from this grain.';

-- ============================================================================
-- 12. analytics.fact_station_daily — primary daily OLAP / future ML aggregate
-- EXACT GRAIN: one row = one station_key x date_key WITH evidence.
-- (No-evidence days produce NO row: missing means unknown, never zero
-- activity and never fabricated.)
-- Additivity contract:
--   ADDITIVE (safe to SUM across stations/dates): observation_count,
--     report_count, review_count, available_count, busy_count, broken_count,
--     source_count.
--   NON-ADDITIVE (never SUM; recompute or average with weights):
--     availability_ratio, busy_ratio, broken_ratio, avg_queue_score,
--     peak_queue_score, avg_rating, data_completeness_score.
--   DESCRIPTIVE: maturity, has_evidence.
-- DELIBERATELY ABSENT (require legitimate charging-session data, must not be
-- fabricated): total_sessions, total_energy_kwh, total_revenue,
-- avg_duration_minutes, session_count.
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.fact_station_daily (
  station_key            BIGINT NOT NULL REFERENCES analytics.dim_station (station_key),
  date_key               INTEGER NOT NULL REFERENCES analytics.dim_date (date_key),
  observation_count      INTEGER NOT NULL DEFAULT 0 CHECK (observation_count >= 0),
  report_count           INTEGER NOT NULL DEFAULT 0 CHECK (report_count >= 0),
  review_count           INTEGER NOT NULL DEFAULT 0 CHECK (review_count >= 0),
  available_count        INTEGER NOT NULL DEFAULT 0 CHECK (available_count >= 0),
  busy_count             INTEGER NOT NULL DEFAULT 0 CHECK (busy_count >= 0),
  broken_count           INTEGER NOT NULL DEFAULT 0 CHECK (broken_count >= 0),
  availability_ratio     NUMERIC(5, 4) NULL CHECK (availability_ratio IS NULL OR (availability_ratio >= 0 AND availability_ratio <= 1)),
  busy_ratio             NUMERIC(5, 4) NULL CHECK (busy_ratio IS NULL OR (busy_ratio >= 0 AND busy_ratio <= 1)),
  broken_ratio           NUMERIC(5, 4) NULL CHECK (broken_ratio IS NULL OR (broken_ratio >= 0 AND broken_ratio <= 1)),
  avg_queue_score        NUMERIC(5, 4) NULL CHECK (avg_queue_score IS NULL OR (avg_queue_score >= 0 AND avg_queue_score <= 1)),
  peak_queue_score       NUMERIC(5, 4) NULL CHECK (peak_queue_score IS NULL OR (peak_queue_score >= 0 AND peak_queue_score <= 1)),
  avg_rating             NUMERIC(3, 2) NULL CHECK (avg_rating IS NULL OR (avg_rating >= 1 AND avg_rating <= 5)),
  data_completeness_score NUMERIC(5, 4) NULL CHECK (data_completeness_score IS NULL OR (data_completeness_score >= 0 AND data_completeness_score <= 1)),
  source_count           INTEGER NOT NULL DEFAULT 0 CHECK (source_count >= 0),
  maturity               TEXT NOT NULL DEFAULT 'cold' CHECK (maturity IN ('cold', 'warming', 'ready')),
  has_evidence           BOOLEAN NOT NULL DEFAULT TRUE,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT pk_fact_station_daily PRIMARY KEY (station_key, date_key)
);
CREATE INDEX IF NOT EXISTS idx_fsd_date ON analytics.fact_station_daily (date_key);
COMMENT ON TABLE analytics.fact_station_daily IS
'EXACT GRAIN: one row = one station_key x date_key WITH evidence (no row for no-evidence days). Primary daily OLAP table and future ML feature source. Counts are additive; ratios/scores are NON-ADDITIVE (never SUM). No session/energy/revenue measures: those need real charging-session data and must not be fabricated.';
COMMENT ON COLUMN analytics.fact_station_daily.maturity IS
'Data-confidence state: cold (very little evidence, no predictions), warming (some evidence, limited intelligence), ready (enough history for forecasts). Descriptive, non-additive.';
COMMENT ON COLUMN analytics.fact_station_daily.has_evidence IS
'Always TRUE for stored rows (rows exist only with evidence). Guards consumers against interpreting missing days as zero activity.';

-- ============================================================================
-- 13. Deterministic seeds — reference dimensions ONLY
-- dim_date (3288 rows) + dim_time (96 rows). Idempotent via ON CONFLICT.
-- No production/synthetic station, connector, observation, report, review,
-- weather, session, price, or prediction data is inserted anywhere in Step 1.4.
-- ============================================================================

-- 13a. dim_date: 2024-01-01 through 2032-12-31.
INSERT INTO analytics.dim_date (
  date_key, full_date, year, quarter, month, month_name,
  week, day_of_month, day_of_week, day_name, is_weekend
)
SELECT
  (to_char(d, 'YYYYMMDD'))::INTEGER            AS date_key,
  d::DATE                                      AS full_date,
  EXTRACT(YEAR FROM d)::SMALLINT               AS year,
  EXTRACT(QUARTER FROM d)::SMALLINT            AS quarter,
  EXTRACT(MONTH FROM d)::SMALLINT              AS month,
  to_char(d, 'FMMonth')                        AS month_name,
  EXTRACT(WEEK FROM d)::SMALLINT               AS week,
  EXTRACT(DAY FROM d)::SMALLINT                AS day_of_month,
  EXTRACT(ISODOW FROM d)::SMALLINT             AS day_of_week,
  to_char(d, 'FMDay')                          AS day_name,
  (EXTRACT(ISODOW FROM d) IN (6, 7))           AS is_weekend
FROM generate_series(DATE '2024-01-01', DATE '2032-12-31', INTERVAL '1 day') AS d
ON CONFLICT (date_key) DO NOTHING;

-- 13b. dim_time: exactly 96 fifteen-minute slots (00:00..23:45).
INSERT INTO analytics.dim_time (time_key, hour, minute, slot_15min, time_of_day)
SELECT
  slot                                                            AS time_key,
  (slot / 4)::SMALLINT                                            AS hour,
  ((slot % 4) * 15)::SMALLINT                                     AS minute,
  lpad((slot / 4)::TEXT, 2, '0') || ':' || lpad(((slot % 4) * 15)::TEXT, 2, '0') AS slot_15min,
  CASE
    WHEN (slot / 4) BETWEEN 5 AND 11 THEN 'morning'
    WHEN (slot / 4) BETWEEN 12 AND 16 THEN 'afternoon'
    WHEN (slot / 4) BETWEEN 17 AND 20 THEN 'evening'
    ELSE 'night'
  END                                                             AS time_of_day
FROM generate_series(0, 95) AS slot
ON CONFLICT (time_key) DO NOTHING;

-- ============================================================================
-- 14. Seed assertions — fail the migration if reference data is wrong
-- ============================================================================
DO $$
DECLARE
  v_date_cnt  INTEGER;
  v_time_cnt  INTEGER;
  v_min_date  DATE;
  v_max_date  DATE;
BEGIN
  SELECT count(*), min(full_date), max(full_date)
    INTO v_date_cnt, v_min_date, v_max_date
    FROM analytics.dim_date;
  SELECT count(*) INTO v_time_cnt FROM analytics.dim_time;

  IF v_date_cnt <> 3288 THEN
    RAISE EXCEPTION 'Step 1.4: analytics.dim_date must hold 3288 rows (2024-01-01..2032-12-31), found %', v_date_cnt;
  END IF;
  IF v_min_date <> DATE '2024-01-01' OR v_max_date <> DATE '2032-12-31' THEN
    RAISE EXCEPTION 'Step 1.4: analytics.dim_date range must be 2024-01-01..2032-12-31, found %..%', v_min_date, v_max_date;
  END IF;
  IF v_time_cnt <> 96 THEN
    RAISE EXCEPTION 'Step 1.4: analytics.dim_time must hold exactly 96 rows, found %', v_time_cnt;
  END IF;
END
$$;

-- End of Step 1.4 migration.
