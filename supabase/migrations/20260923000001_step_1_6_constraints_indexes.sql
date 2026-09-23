-- ============================================================================
-- ChargePlus Phase 1 — Step 1.6: Constraints & Indexes Synthesis
-- Migration: 20260923000001_step_1_6_constraints_indexes.sql
--
-- PURPOSE:
-- Final reconciled synthesis of all four schema audits into ONE minimal, production-safe,
-- idempotent migration for Phase 1 Step 1.6.
--
-- AUDIT RECONCILIATION SUMMARY:
-- 1. Integrity Constraints Added:
--    - Public (13 ADD CONSTRAINT + 1 Unique Index):
--        * Observation causality: chk_observations_causal_time (received_at >= observed_at)
--        * Report causality: chk_report_created_after_observed (created_at >= observed_at)
--        * Connector ownership: uq_connectors_id_station (UNIQUE superkey on connectors)
--        * Observation connector ownership: fk_observations_connector_owner (FK to connectors(station_id, id))
--        * Report connector ownership: fk_reports_connector_owner (FK to connectors(station_id, id))
--        * Report moderation audit: chk_user_reports_moderation_audit
--        * Report rejection reason: chk_user_reports_rejection_reason
--        * Review moderation audit: chk_reviews_moderation_audit
--        * Review rejection reason: chk_reviews_rejection_reason
--        * Station slug format: chk_stations_slug_format
--        * Operator slug format: chk_operators_slug_format
--        * Alert threshold non-negative: chk_alerts_threshold_positive
--        * Source-link chronology: chk_source_link_seen_range
--        * Capacity-group uniqueness: uq_connectors_station_type_power (UNIQUE INDEX)
--    - Analytics (10 ADD CONSTRAINT):
--        * Operating hours mirror: chk_dim_station_hours
--        * Deterministic dim_date self-consistency: chk_dim_date_self_consistent (IMMUTABLE expressions only)
--        * Deterministic dim_time self-consistency: chk_dim_time_self_consistent
--        * Connector vocabulary parity: chk_dim_connector_type
--        * Fact observation causality: chk_fact_observation_causal_time
--        * Fact observation dim alignment: chk_fact_observation_dim_alignment (UTC convention)
--        * Fact report dim alignment: chk_fact_report_dim_alignment (UTC convention)
--        * Fact report moderation provenance: chk_fact_report_moderated
--        * Fact review moderation provenance: chk_fact_review_moderated
--        * Fact daily status-count conservation: chk_fact_daily_status_counts
--    - ML (4 ADD CONSTRAINT):
--        * Intra-layer dataset FK: fk_experiments_dataset (dataset_key -> ml.datasets(dataset_key))
--        * Experiment lifecycle timestamps: chk_experiments_lifecycle
--        * Dataset time range ordering: chk_datasets_time_range
--        * Model ready gate: chk_model_ready_gate
--    Total Constraints: 27 ADD CONSTRAINT statements + 1 Unique Index = 28 constraints.
--
-- 2. Index Operations:
--    - Dropped Redundant/Duplicate Indexes (9 total):
--        * public.idx_reviews_station (dropped to be replaced by composite index)
--        * public.idx_reviews_user (covered by uq_reviews_user_station leading col)
--        * public.idx_favorites_user (covered by pk_favorites leading col)
--        * public.idx_station_source_link_source (covered by uq_station_source_link_source_record leading col)
--        * ml.idx_ml_features_name (exact duplicate of UNIQUE feature_name)
--        * ml.idx_ml_datasets_name (exact duplicate of uq_datasets_name_version)
--        * ml.idx_ml_modelversions_experiment (covered by uq_modelversions_experiment_version leading col)
--        * ml.idx_ml_metrics_model (covered by uq_metrics_model_name_split leading col)
--        * ml.idx_ml_predictionruns_model (covered by uq_predictionruns_model_station_datetime leading col)
--    - Created / Replaced Indexes (6 total):
--        * public.idx_reviews_station (composite on station_id, created_at DESC)
--        * public.idx_user_reports_pending (partial index on created_at WHERE moderation_status = 'pending')
--        * public.uq_connectors_station_type_power (UNIQUE INDEX on static capacity group)
--        * analytics.idx_dim_station_effective (SCD2 resolution index on station_id, effective_from, effective_to)
--        * ml.idx_ml_modelversions_training_dataset (FK-supporting index on training_dataset_key)
--        * ml.idx_ml_modelversions_eval_dataset (FK-supporting index on eval_dataset_key)
--    - Final Explicit Index Count:
--        * public: 18 baseline - 4 dropped + 3 created = 17
--        * analytics: 14 baseline - 0 dropped + 1 created = 15
--        * ml: 16 baseline - 5 dropped + 2 created = 13
--        * Total explicit indexes in final schema = 45
--
-- ARCHITECTURAL BOUNDARIES PRESERVED:
-- - public: Operational OLTP (no cross-layer FKs)
-- - analytics: Canonical Data Warehouse OLAP (no cross-layer FKs)
-- - ml: ML metadata & control (no cross-layer FKs)
-- - Legacy public.dim_* / public.fact_* tables: Strictly untouched
-- - Frontend: Untouched
-- - RLS: Strictly deferred to Step 1.7
-- - PostGIS & India-ready capabilities: Fully preserved
-- ============================================================================

-- ============================================================================
-- PART 1: PUBLIC SCHEMA (OLTP)
-- ============================================================================

-- 1.1 Drop redundant single-column indexes covered by UNIQUE/PK leading columns
DROP INDEX IF EXISTS public.idx_reviews_user;
DROP INDEX IF EXISTS public.idx_favorites_user;
DROP INDEX IF EXISTS public.idx_station_source_link_source;

-- 1.2 Replace single-column reviews index with newest-first composite index
DROP INDEX IF EXISTS public.idx_reviews_station;
CREATE INDEX IF NOT EXISTS idx_reviews_station
  ON public.reviews (station_id, created_at DESC);

-- 1.3 Add partial index for driver reports pending moderation
CREATE INDEX IF NOT EXISTS idx_user_reports_pending
  ON public.user_reports (created_at)
  WHERE moderation_status = 'pending';

-- 1.4 Enforce capacity-group uniqueness per station
-- Prevents identical duplicate capacity groups for the same station.
CREATE UNIQUE INDEX IF NOT EXISTS uq_connectors_station_type_power
  ON public.connectors (station_id, connector_type, power_kw, COALESCE(charging_standard, ''));

-- 1.5 Constraints for Public Schema (Idempotent DO block)
DO $$
BEGIN
  -- A1. Observation causality: a feed cannot be received before it is observed
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_observations_causal_time') THEN
    ALTER TABLE public.station_observations
      ADD CONSTRAINT chk_observations_causal_time
      CHECK (received_at >= observed_at);
  END IF;

  -- A2. Report causality: a user report cannot be created before observation
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_report_created_after_observed') THEN
    ALTER TABLE public.user_reports
      ADD CONSTRAINT chk_report_created_after_observed
      CHECK (created_at >= observed_at);
  END IF;

  -- A3. Connector ownership superkey on connectors
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_connectors_id_station') THEN
    ALTER TABLE public.connectors
      ADD CONSTRAINT uq_connectors_id_station
      UNIQUE (station_id, id);
  END IF;

  -- A3. Connector ownership FK on station_observations
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_observations_connector_owner') THEN
    ALTER TABLE public.station_observations
      ADD CONSTRAINT fk_observations_connector_owner
      FOREIGN KEY (station_id, connector_id) REFERENCES public.connectors (station_id, id);
  END IF;

  -- A3. Connector ownership FK on user_reports
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_reports_connector_owner') THEN
    ALTER TABLE public.user_reports
      ADD CONSTRAINT fk_reports_connector_owner
      FOREIGN KEY (station_id, connector_id) REFERENCES public.connectors (station_id, id);
  END IF;

  -- A5. Moderation audit consistency on user_reports
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_user_reports_moderation_audit') THEN
    ALTER TABLE public.user_reports
      ADD CONSTRAINT chk_user_reports_moderation_audit
      CHECK (
        (moderation_status = 'pending' AND moderated_at IS NULL AND moderation_reason IS NULL)
        OR (moderation_status IN ('approved', 'rejected') AND moderated_at IS NOT NULL)
      );
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_user_reports_rejection_reason') THEN
    ALTER TABLE public.user_reports
      ADD CONSTRAINT chk_user_reports_rejection_reason
      CHECK (moderation_status <> 'rejected' OR moderation_reason IS NOT NULL);
  END IF;

  -- A5b. Moderation audit consistency on reviews
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_reviews_moderation_audit') THEN
    ALTER TABLE public.reviews
      ADD CONSTRAINT chk_reviews_moderation_audit
      CHECK (
        (moderation_status = 'pending' AND moderated_at IS NULL AND moderation_reason IS NULL)
        OR (moderation_status IN ('approved', 'rejected') AND moderated_at IS NOT NULL)
      );
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_reviews_rejection_reason') THEN
    ALTER TABLE public.reviews
      ADD CONSTRAINT chk_reviews_rejection_reason
      CHECK (moderation_status <> 'rejected' OR moderation_reason IS NOT NULL);
  END IF;

  -- A6. Canonical slug token format validation
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_stations_slug_format') THEN
    ALTER TABLE public.stations
      ADD CONSTRAINT chk_stations_slug_format
      CHECK (slug IS NULL OR slug ~ '^[a-zA-Z0-9][a-zA-Z0-9_-]*$');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_operators_slug_format') THEN
    ALTER TABLE public.operators
      ADD CONSTRAINT chk_operators_slug_format
      CHECK (slug IS NULL OR slug ~ '^[a-zA-Z0-9][a-zA-Z0-9_-]*$');
  END IF;

  -- A7. Alert threshold non-negative magnitude
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_alerts_threshold_positive') THEN
    ALTER TABLE public.alerts
      ADD CONSTRAINT chk_alerts_threshold_positive
      CHECK (threshold_value IS NULL OR threshold_value >= 0);
  END IF;

  -- A8. Source-link chronology
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_source_link_seen_range') THEN
    ALTER TABLE public.station_source_link
      ADD CONSTRAINT chk_source_link_seen_range
      CHECK (last_seen_at IS NULL OR first_seen_at IS NULL OR last_seen_at >= first_seen_at);
  END IF;
END $$;


-- ============================================================================
-- PART 2: ANALYTICS SCHEMA (WAREHOUSE OLAP)
-- ============================================================================

-- 2.1 SCD2 Point-in-Time Resolution Index
-- Supports ETL fact ingestion resolving station_key where effective_from <= observed_at < effective_to.
CREATE INDEX IF NOT EXISTS idx_dim_station_effective
  ON analytics.dim_station (station_id, effective_from, effective_to);

-- 2.2 Constraints for Analytics Schema (Idempotent DO block)
DO $$
BEGIN
  -- B1. dim_station operating hours consistency (mirrors public.chk_stations_hours)
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_dim_station_hours') THEN
    ALTER TABLE analytics.dim_station
      ADD CONSTRAINT chk_dim_station_hours
      CHECK (
        (is_24_hours AND opening_time IS NULL AND closing_time IS NULL)
        OR (NOT is_24_hours AND opening_time IS NULL AND closing_time IS NULL)
        OR (NOT is_24_hours AND opening_time IS NOT NULL AND closing_time IS NOT NULL)
      );
  END IF;

  -- B2. dim_date surrogate-key self-consistency
  -- Note: Uses strictly IMMUTABLE EXTRACT and CASE expressions to guarantee PG portability.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_dim_date_self_consistent') THEN
    ALTER TABLE analytics.dim_date
      ADD CONSTRAINT chk_dim_date_self_consistent
      CHECK (
        date_key = (EXTRACT(YEAR FROM full_date)::integer * 10000)
                 + (EXTRACT(MONTH FROM full_date)::integer * 100)
                 + EXTRACT(DAY FROM full_date)::integer
        AND year::integer        = EXTRACT(YEAR FROM full_date)
        AND quarter::integer     = EXTRACT(QUARTER FROM full_date)
        AND month::integer       = EXTRACT(MONTH FROM full_date)
        AND week::integer        = EXTRACT(WEEK FROM full_date)
        AND day_of_month::integer= EXTRACT(DAY FROM full_date)
        AND day_of_week::integer = EXTRACT(ISODOW FROM full_date)
        AND is_weekend           = (EXTRACT(ISODOW FROM full_date) IN (6, 7))
        AND month_name = CASE EXTRACT(MONTH FROM full_date)::integer
          WHEN 1 THEN 'January' WHEN 2 THEN 'February' WHEN 3 THEN 'March'
          WHEN 4 THEN 'April' WHEN 5 THEN 'May' WHEN 6 THEN 'June'
          WHEN 7 THEN 'July' WHEN 8 THEN 'August' WHEN 9 THEN 'September'
          WHEN 10 THEN 'October' WHEN 11 THEN 'November' WHEN 12 THEN 'December'
        END
        AND day_name = CASE EXTRACT(ISODOW FROM full_date)::integer
          WHEN 1 THEN 'Monday' WHEN 2 THEN 'Tuesday' WHEN 3 THEN 'Wednesday'
          WHEN 4 THEN 'Thursday' WHEN 5 THEN 'Friday' WHEN 6 THEN 'Saturday'
          WHEN 7 THEN 'Sunday'
        END
      );
  END IF;

  -- B3. dim_time surrogate-key self-consistency
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_dim_time_self_consistent') THEN
    ALTER TABLE analytics.dim_time
      ADD CONSTRAINT chk_dim_time_self_consistent
      CHECK (
        time_key = (hour * 4 + minute / 15)
        AND slot_15min = lpad(hour::text, 2, '0') || ':' || lpad(minute::text, 2, '0')
        AND time_of_day = (CASE
            WHEN hour BETWEEN 5 AND 11  THEN 'morning'
            WHEN hour BETWEEN 12 AND 16 THEN 'afternoon'
            WHEN hour BETWEEN 17 AND 20 THEN 'evening'
            ELSE 'night' END)
      );
  END IF;

  -- B4. dim_connector vocabulary parity with public.connectors
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_dim_connector_type') THEN
    ALTER TABLE analytics.dim_connector
      ADD CONSTRAINT chk_dim_connector_type
      CHECK (
        connector_type IN ('CCS2', 'CHAdeMO', 'Type 2', 'Type 1',
                           'GB/T', 'Bharat AC001', 'Bharat DC001')
      );
  END IF;

  -- B5. fact_station_observation causality & dim alignment
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_fact_observation_causal_time') THEN
    ALTER TABLE analytics.fact_station_observation
      ADD CONSTRAINT chk_fact_observation_causal_time
      CHECK (received_at >= observed_at);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_fact_observation_dim_alignment') THEN
    ALTER TABLE analytics.fact_station_observation
      ADD CONSTRAINT chk_fact_observation_dim_alignment
      CHECK (
        date_key = (EXTRACT(YEAR FROM (observed_at AT TIME ZONE 'UTC'))::integer * 10000)
                 + (EXTRACT(MONTH FROM (observed_at AT TIME ZONE 'UTC'))::integer * 100)
                 + EXTRACT(DAY FROM (observed_at AT TIME ZONE 'UTC'))::integer
        AND time_key = (EXTRACT(HOUR FROM (observed_at AT TIME ZONE 'UTC'))::integer * 4
                      + EXTRACT(MINUTE FROM (observed_at AT TIME ZONE 'UTC'))::integer / 15)::smallint
      );
  END IF;

  -- B6. fact_user_report alignment & moderation provenance
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_fact_report_dim_alignment') THEN
    ALTER TABLE analytics.fact_user_report
      ADD CONSTRAINT chk_fact_report_dim_alignment
      CHECK (
        date_key = (EXTRACT(YEAR FROM (observed_at AT TIME ZONE 'UTC'))::integer * 10000)
                 + (EXTRACT(MONTH FROM (observed_at AT TIME ZONE 'UTC'))::integer * 100)
                 + EXTRACT(DAY FROM (observed_at AT TIME ZONE 'UTC'))::integer
        AND time_key = (EXTRACT(HOUR FROM (observed_at AT TIME ZONE 'UTC'))::integer * 4
                      + EXTRACT(MINUTE FROM (observed_at AT TIME ZONE 'UTC'))::integer / 15)::smallint
      );
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_fact_report_moderated') THEN
    ALTER TABLE analytics.fact_user_report
      ADD CONSTRAINT chk_fact_report_moderated
      CHECK (moderated_at IS NOT NULL);
  END IF;

  -- B6b. fact_review moderation provenance
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_fact_review_moderated') THEN
    ALTER TABLE analytics.fact_review
      ADD CONSTRAINT chk_fact_review_moderated
      CHECK (moderated_at IS NOT NULL);
  END IF;

  -- B7. fact_station_daily status count conservation
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_fact_daily_status_counts') THEN
    ALTER TABLE analytics.fact_station_daily
      ADD CONSTRAINT chk_fact_daily_status_counts
      CHECK (available_count + busy_count + broken_count <= observation_count);
  END IF;
END $$;


-- ============================================================================
-- PART 3: ML SCHEMA (METADATA & CONTROL)
-- ============================================================================

-- 3.1 Drop exact duplicate and redundant prefix indexes in ml schema
DROP INDEX IF EXISTS ml.idx_ml_features_name;
DROP INDEX IF EXISTS ml.idx_ml_datasets_name;
DROP INDEX IF EXISTS ml.idx_ml_modelversions_experiment;
DROP INDEX IF EXISTS ml.idx_ml_metrics_model;
DROP INDEX IF EXISTS ml.idx_ml_predictionruns_model;

-- 3.2 Add foreign key supporting indexes on ml.model_versions
CREATE INDEX IF NOT EXISTS idx_ml_modelversions_training_dataset
  ON ml.model_versions (training_dataset_key);

CREATE INDEX IF NOT EXISTS idx_ml_modelversions_eval_dataset
  ON ml.model_versions (eval_dataset_key);

-- 3.3 Constraints for ML Schema (Idempotent DO block)
DO $$
BEGIN
  -- C1. Intra-schema foreign key: experiments.dataset_key -> datasets.dataset_key
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_experiments_dataset') THEN
    ALTER TABLE ml.experiments
      ADD CONSTRAINT fk_experiments_dataset
      FOREIGN KEY (dataset_key) REFERENCES ml.datasets (dataset_key) ON DELETE RESTRICT;
  END IF;

  -- C2. Experiment lifecycle timestamp alignment with status
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_experiments_lifecycle') THEN
    ALTER TABLE ml.experiments
      ADD CONSTRAINT chk_experiments_lifecycle
      CHECK (
        (status = 'proposed' AND started_at IS NULL)
        OR (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL)
        OR (status = 'failed' AND started_at IS NOT NULL AND completed_at IS NULL)
        OR (status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL)
      );
  END IF;

  -- C3. Dataset time range ordering
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_datasets_time_range') THEN
    ALTER TABLE ml.datasets
      ADD CONSTRAINT chk_datasets_time_range
      CHECK (time_range_end >= time_range_start);
  END IF;

  -- C4. Model ready gate: ready status requires completed training & evaluation trace
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_model_ready_gate') THEN
    ALTER TABLE ml.model_versions
      ADD CONSTRAINT chk_model_ready_gate
      CHECK (
        status <> 'ready'
        OR (trained_at IS NOT NULL AND completed_at IS NOT NULL
            AND training_dataset_key IS NOT NULL AND eval_dataset_key IS NOT NULL)
      );
  END IF;
END $$;


-- ============================================================================
-- PART 4: POST-MIGRATION INTEGRITY & ARCHITECTURE ASSERTIONS
-- ============================================================================
DO $$
DECLARE
  v_cross_fk_count INTEGER;
  v_seeded_row_count INTEGER;
BEGIN
  -- 1. Assert NO cross-layer foreign keys exist from analytics or ml
  SELECT count(*) INTO v_cross_fk_count
  FROM information_schema.table_constraints tc
  JOIN information_schema.referential_constraints rc ON tc.constraint_name = rc.constraint_name
  JOIN information_schema.constraint_column_usage ccu ON rc.unique_constraint_name = ccu.constraint_name
  WHERE tc.constraint_type = 'FOREIGN KEY'
    AND ((tc.table_schema = 'analytics' AND ccu.table_schema <> 'analytics')
      OR (tc.table_schema = 'ml' AND ccu.table_schema <> 'ml'));

  IF v_cross_fk_count > 0 THEN
    RAISE EXCEPTION 'CRITICAL: Architecture violation — cross-layer foreign keys detected (count=%)', v_cross_fk_count;
  END IF;

  -- 2. Assert NO rows were inserted into operational or ML tables (DDL-only verification)
  SELECT count(*) INTO v_seeded_row_count FROM public.stations;
  IF v_seeded_row_count > 0 THEN
    RAISE EXCEPTION 'CRITICAL: Data seeding violation — public.stations contains rows';
  END IF;

  SELECT count(*) INTO v_seeded_row_count FROM ml.features;
  IF v_seeded_row_count > 0 THEN
    RAISE EXCEPTION 'CRITICAL: Data seeding violation — ml.features contains rows';
  END IF;
END $$;
