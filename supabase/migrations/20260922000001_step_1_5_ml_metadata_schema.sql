-- ============================================================================
-- ChargePlus Step 1.5 — ML Metadata Schema
-- Phase 1/6 Step 1.5/10
-- ============================================================================

-- ARCHITECTURAL LOCK — READ FIRST:
--
--   public    = OPERATIONAL DATABASE (OLTP)
--               Current application/product state and operational history.
--
--   analytics = DATA WAREHOUSE (OLAP)
--               Historical facts, conformed dimensions, aggregates, OLAP and
--               future ML feature preparation. Populated ONLY by Python ETL
--               jobs that move legitimate historical operational data into
--               this layer using business-key / surrogate-key mapping. There
--               are NO frontend writes to analytics tables, and NO cross-layer
--               foreign keys (e.g. analytics.station_key -> public.stations.id
--               is FORBIDDEN). The warehouse is a separate logical layer.
--
--   ml        = ML METADATA/CONTROL LAYER
--               Schema-level metadata describing ML experiments, models,
--               features, datasets, and prediction runs. This layer stores
--               metadata only — NO model bytes, NO synthetic data, NO fake
--               predictions. Populated by Python ETL/ML pipeline init jobs.
--               Frontend reads are allowed via grants; no frontend writes.
--
--   Python    = ETL/ELT + ML pipeline boundary
--               Responsible for populating ml.* tables from operational data.
--               No frontend logic depends on ml.* content.
--
--   The whole Supabase/PostgreSQL database is NOT "the data warehouse".
--   Only the analytics schema is the warehouse. The ml schema is a
--   separate logical layer for ML metadata control.
--
--   CROSS-LAYER FK RULE: No foreign keys cross between schemas (public,
--   analytics, ml). The ml layer references operational/business keys as
--   plain columns (UUIDs, integers) without REFERENCES clauses. ETL
--   resolves business-key -> surrogate-key mappings in application code.
--
-- LEGACY SAFETY (ABSOLUTE RULE):
--   The following pre-existing tables are EMPTY and remain UNTOUCHED:
--     public.dim_date, public.dim_location, public.dim_station,
--     public.dim_tariff, public.dim_time, public.dim_vehicle,
--     public.dim_weather, public.fact_charging_session,
--     public.fact_station_daily_agg.
--   This file contains NO DROP, NO ALTER, NO RENAME, NO TRUNCATE, NO INSERT,
--   NO UPDATE, and NO DELETE touching any of those tables. They are referenced
--   here in comments ONLY; no executable statement in this file names them.
--
--   Also untouched: ALL analytics.* tables and ALL public.* tables.
--   This file creates ONLY the ml schema.
--
-- SCOPE OF THIS FILE:
--   Creates schema `ml` with 6 tables for ML metadata:
--     ml.features — feature definitions
--     ml.datasets — dataset/training-data version metadata
--     ml.experiments — ML experiments
--     ml.model_versions — model versions/runs with lifecycle + data maturity
--     ml.metrics — model evaluation metrics (name/value/split)
--     ml.prediction_runs — prediction-run metadata (metadata only, not values)
--   Seeds NO rows. All tables use IF NOT EXISTS guards for rerunnability.
--
-- KEY DESIGN RULES APPLIED:
--   1. No cross-layer foreign keys between any schemas (public, analytics, ml).
--      All FKs stay within the same schema. ETL resolves business-key mappings.
--   2. Every table has a surrogate UUID primary key AND business/version keys.
--   3. Grain + semantics documented via COMMENTs on every table/column.
--   4. Idempotent: IF NOT EXISTS guards + ON CONFLICT DO NOTHING patterns.
--   5. Metric store is name/value/split — not hardcoded MAE/RMSE columns.
--   6. Prediction metadata stored separately from prediction values.
--   7. Model status and data_maturity are separate concerns:
--      status = model lifecycle, data_maturity = COLD→WARMING→READY evidence.
--   8. No synthetic training data, no fake predictions, no model bytes.
--   9. No dim_user, no user PII, no mixing predicted with observed.
--  10. No duplication of analytics fact tables.
--
-- LOAD ORDER INSIDE THIS FILE (intra-ml FK dependencies):
--   ml.features (independent)
--   ml.datasets (independent, referenced by experiments and model_versions)
--   ml.experiments (references ml.datasets)
--   ml.model_versions (references ml.experiments)
--   ml.metrics (references ml.model_versions)
--   ml.prediction_runs (references ml.model_versions)
--   Python ETL must respect the same order.
--
-- IDEMPOTENCY: safe to re-run (IF NOT EXISTS guards + ON CONFLICT DO NOTHING).
-- Under Supabase CLI this file runs once via supabase_migrations history.
-- ============================================================================

-- ============================================================================
-- 0. Schema
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS ml;
COMMENT ON SCHEMA ml IS
'Step 1.5: ML METADATA/CONTROL LAYER. Schema-level metadata describing ML experiments, models, features, datasets, and prediction runs. '
'Stores metadata only — no model bytes, no synthetic data, no fake predictions. '
'Populated by Python ETL/ML pipeline init jobs. Separate from analytics (OLAP) '
'and public (OLTP) layers. Cross-layer FKs are FORBIDDEN: all business-key '
'references to other schemas are stored as plain columns without REFERENCES. '
'Frontend reads allowed via grants (Step 1.7); no frontend writes.';

-- ============================================================================
-- 1. ml.features — feature definitions
-- GRAIN: one row per feature definition.
-- Business key: feature_name (unique across the ml layer).
-- feature_type controls the kind of data the feature holds.
-- feature_group categorizes the feature by its intended ML use case,
--    supporting future station demand, queue/congestion, and
--    recommendation features without duplicating the feature table.
-- generated_by indicates whether the feature is derived from observed data
--    (vs. raw station attributes) or engineered.
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml.features (
  feature_key    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  feature_name   TEXT NOT NULL UNIQUE,
  feature_type   TEXT NOT NULL
    CHECK (feature_type IN ('categorical', 'numerical', 'boolean', 'temporal',
                            'station_id', 'geospatial', 'count', 'ratio',
                            'aggregate', 'composite')),
  feature_group  TEXT NOT NULL
    CHECK (feature_group IN ('demand_estimation', 'queue_congestion',
                              'recommendation', 'station_attributes',
                              'temporal_pattern', 'general')),
  units          TEXT NULL,
  description    TEXT NULL,
  generated_by   TEXT NULL
    CHECK (generated_by IS NULL OR generated_by IN ('raw_attribute', 'derived', 'engineered')),
  formula        TEXT NULL,
  source_column  TEXT NULL,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE ml.features IS
'GRAIN: one row per feature definition. feature_name is unique across the ml layer. '
'feature_type determines the data kind; feature_group categorizes by intended ML use case '
'(demand_estimation, queue_congestion, recommendation, station_attributes, temporal_pattern, general). '
'generated_by tracks whether the feature is a raw attribute, a derived observation, or an engineered construct. '
'formula is stored as text for reproducibility but never executed inside the DB. source_column records the '
'operational/warehouse column name for ETL traceability without cross-layer FKs.';

COMMENT ON COLUMN ml.features.feature_group IS
'Intended ML use case category. Allows filtering features '
'by future workload: demand_estimation, queue_congestion, '
'recommendation, or general-purpose.';
COMMENT ON COLUMN ml.features.formula IS
'Optional Python expression or SQL that computes the feature; '
'stored as text for reproducibility; never executed inside the DB.';
COMMENT ON COLUMN ml.features.source_column IS
'If the feature maps directly to an operational or warehouse '
'column, the column name is recorded here for ETL traceability. '
'No cross-layer FK; ETL resolves the mapping.';
COMMENT ON COLUMN ml.features.is_active IS
'Whether the feature is currently in use. Soft-deactivation '
'preserves history without removing the definition.';

-- ============================================================================
-- 2. ml.datasets — dataset/training-data version metadata
-- GRAIN: one row per dataset/training-data version.
-- Business key: (dataset_name, version_str) — unique pair.
-- source maps from the operational business key (public.data_sources.id or
--   a station_id) to the warehouse as a plain string, NOT a cross-layer FK.
-- is_training / is_validation / is_test partition the dataset role.
-- time_range_start/end are inclusive bounds.
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml.datasets (
  dataset_key      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_name     TEXT NOT NULL,
  version_str      TEXT NOT NULL,
  description      TEXT NULL,
  source           TEXT NULL,
  time_range_start TIMESTAMPTZ NOT NULL,
  time_range_end   TIMESTAMPTZ NOT NULL,
  row_count        BIGINT NOT NULL DEFAULT 0 CHECK (row_count >= 0),
  feature_count    INTEGER NOT NULL DEFAULT 0 CHECK (feature_count >= 0),
  data_maturity    TEXT NOT NULL DEFAULT 'cold'
    CHECK (data_maturity IN ('cold', 'warming', 'ready')),
  is_training      BOOLEAN NOT NULL DEFAULT FALSE,
  is_validation    BOOLEAN NOT NULL DEFAULT FALSE,
  is_test          BOOLEAN NOT NULL DEFAULT FALSE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_datasets_name_version UNIQUE (dataset_name, version_str),
  CONSTRAINT uq_datasets_partition CHECK (
    (is_training::INTEGER + is_validation::INTEGER + is_test::INTEGER) <= 1
  )
);

COMMENT ON TABLE ml.datasets IS
'GRAIN: one row per dataset/training-data version. (dataset_name, version_str) '
'is the business key pair, UNIQUE across the ml layer. source is a business-key '
'pointer to the operational layer stored as plain text — no cross-layer FK. '
'time_range_start/end are inclusive calendar bounds. exactly one of '
'is_training/is_validation/is_test may be TRUE per row (enforced by '
'uq_datasets_partition). data_maturity reflects the evidence level of the '
'dataset, aligned with analytics.fact_station_daily.maturity.';

COMMENT ON COLUMN ml.datasets.source IS
'Business key reference: public.data_sources.id or a station_id '
'from the operational layer. Stored as plain text — no cross-layer FK. '
'ETL resolves the mapping.';
COMMENT ON COLUMN ml.datasets.time_range_start IS
'Inclusive start of the calendar window from which rows were drawn.';
COMMENT ON COLUMN ml.datasets.time_range_end IS
'Inclusive end of the calendar window from which rows were drawn.';
COMMENT ON COLUMN ml.datasets.data_maturity IS
'Data maturity of this dataset, aligned with '
'analytics.fact_station_daily.maturity (cold / warming / ready). '
'A dataset for training must have at least warming maturity.';
COMMENT ON COLUMN ml.datasets.is_training IS
'TRUE when this dataset is the training partition.';
COMMENT ON COLUMN ml.datasets.is_validation IS
'TRUE when this dataset is the validation partition.';
COMMENT ON COLUMN ml.datasets.is_test IS
'TRUE when this dataset is the test partition. At most one of '
'is_training, is_validation, is_test can be TRUE for a given row.';

-- ============================================================================
-- 3. ml.experiments — ML experiments
-- GRAIN: one row per ML experiment run.
-- Business key: experiment_name (unique).
-- dataset_key links to ml.datasets the experiment used for training/eval.
-- status tracks the experiment lifecycle: proposed -> running -> completed -> failed.
-- created_at/updated_at for reproducibility.
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml.experiments (
  experiment_key  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_name TEXT NOT NULL UNIQUE,
  description     TEXT NULL,
  dataset_key     UUID NOT NULL,
  status          TEXT NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'running', 'completed', 'failed')),
  started_at      TIMESTAMPTZ NULL,
  completed_at    TIMESTAMPTZ NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE ml.experiments IS
'GRAIN: one row per ML experiment run. experiment_name is unique. '
'dataset_key links to the ml.datasets used for training/evaluation. '
'status tracks the experiment lifecycle: proposed (init) -> running (in '
'progress) -> completed (success) -> failed (error). started_at/completed_at '
'provide reproducibility timestamps.';

COMMENT ON COLUMN ml.experiments.dataset_key IS
'References ml.datasets.dataset_key. Same schema FK — no cross-layer.';
COMMENT ON COLUMN ml.experiments.started_at IS
'When the experiment started (training began). NULL if not yet running.';
COMMENT ON COLUMN ml.experiments.completed_at IS
'When the experiment completed (training + eval finished). NULL if still running or failed.';

-- ============================================================================
-- 4. ml.model_versions — model versions/runs
-- GRAIN: one row per model version/run.
-- Business key: (experiment_key, version_str) — unique per experiment.
-- status supports the model lifecycle without implying production readiness:
--   proposed, training, validation, ready, archived, deprecated.
-- data_maturity preserves COLD→WARMING→READY semantics aligned with
--   analytics.fact_station_daily.maturity. An unvalidated model never
--   reaches ready data_maturity regardless of status.
-- trained_at/completed_at for reproducibility.
-- artifact_location is optional (e.g. S3 path); the model bytes themselves
--   are NEVER stored in the DB per hard requirements.
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml.model_versions (
  model_key          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_key     UUID NOT NULL
    REFERENCES ml.experiments (experiment_key) ON DELETE CASCADE,
  version_str        TEXT NOT NULL,
  model_type         TEXT NOT NULL
    CHECK (model_type IN ('baseline', 'gradient_boosting', 'linear_regression',
                           'logistic_regression', 'random_forest', 'xgboost',
                           'lightgbm', 'neural_network', 'other')),
  status             TEXT NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'training', 'validation', 'ready', 'archived', 'deprecated')),
  data_maturity      TEXT NOT NULL DEFAULT 'cold'
    CHECK (data_maturity IN ('cold', 'warming', 'ready')),
  trained_at         TIMESTAMPTZ NULL,
  completed_at       TIMESTAMPTZ NULL,
  artifact_location  TEXT NULL,
  training_dataset_key UUID NULL
    REFERENCES ml.datasets (dataset_key) ON DELETE SET NULL,
  eval_dataset_key   UUID NULL
    REFERENCES ml.datasets (dataset_key) ON DELETE SET NULL,
  feature_keys       UUID[] NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_modelversions_experiment_version UNIQUE (experiment_key, version_str),
  CONSTRAINT chk_model_maturity_status CHECK (
    -- A model in early lifecycle can have any data maturity.
    (status IN ('proposed', 'training', 'validation') AND data_maturity IN ('cold', 'warming', 'ready'))
    -- A model marked ready must have at least warming data maturity.
    OR (status = 'ready' AND data_maturity IN ('warming', 'ready'))
    -- Terminal states accept any maturity.
    OR (status IN ('archived', 'deprecated'))
  )
);

COMMENT ON TABLE ml.model_versions IS
'GRAIN: one row per model version/run. One version per experiment; '
'(experiment_key, version_str) is UNIQUE. status tracks the model lifecycle '
'(proposed -> training -> validation -> ready, or archived/deprecated) without '
'implying production readiness. data_maturity (cold/warming/ready) preserves '
'COLD→WARMING→READY semantics aligned with analytics.fact_station_daily.maturity. '
'An unvalidated model (status != ready) may have any data_maturity. '
'status = ready requires data_maturity IN (warming, ready). trained_at/completed_at '
'provide reproducibility timestamps. artifact_location references an external store; '
'model bytes are never stored here. eval_dataset_key links the evaluation dataset. '
'feature_keys records the exact feature set used for reproducibility.';

COMMENT ON COLUMN ml.model_versions.version_str IS
'Semantic version string (e.g. "1.0.0", "baseline-q2-2024").';
COMMENT ON COLUMN ml.model_versions.status IS
'Model lifecycle status. proposed (concept) -> training (being built) '
'-> validation (being evaluated) -> ready (production-ready). '
'Archived/deprecated are terminal states. A model must pass validation '
'before status can become ready.';
COMMENT ON COLUMN ml.model_versions.data_maturity IS
'Data maturity the model is built upon, aligned with '
'analytics.fact_station_daily.maturity (cold / warming / ready). '
'COLD→WARMING→READY semantics preserved. status = ready requires '
'data_maturity IN (warming, ready); early lifecycle statuses may '
'have any maturity.';
COMMENT ON COLUMN ml.model_versions.trained_at IS
'When model training completed. NULL if still training or not yet started.';
COMMENT ON COLUMN ml.model_versions.completed_at IS
'When model validation + registration completed. NULL if not ready.';
COMMENT ON COLUMN ml.model_versions.artifact_location IS
'Optional external artifact location (e.g. S3 key, GCS path). '
'The model binary bytes are NEVER stored in this DB. Null means no artifact '
'has been published yet.';
COMMENT ON COLUMN ml.model_versions.training_dataset_key IS
'The ml.dataset used for training. NULL if not yet trained.';
COMMENT ON COLUMN ml.model_versions.eval_dataset_key IS
'The ml.dataset used for evaluation/validation. NULL if not yet evaluated.';
COMMENT ON COLUMN ml.model_versions.feature_keys IS
'Array of feature_keys from ml.features used in this model. '
'NULL if feature set is not yet determined. Provides reproducibility: '
'a model run is traceable to its exact feature set.';

-- ============================================================================
-- 5. ml.metrics — model evaluation metrics
-- GRAIN: one row per metric recording (name/value/split).
-- Business key: (model_key, metric_name, split) — unique per model+metric+split.
-- metric_name is free-text (e.g. "mae", "rmse", "accuracy", "f1", "r2")
--    — NOT hardcoded columns. metric_value is the scalar result.
-- split identifies the data partition: "train", "validation", "test", "holdout".
-- epoch_or_step identifies the training step if applicable.
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml.metrics (
  metric_key   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  model_key    UUID NOT NULL
    REFERENCES ml.model_versions (model_key) ON DELETE CASCADE,
  metric_name  TEXT NOT NULL,
  metric_value NUMERIC(12, 6) NULL,
  split        TEXT NOT NULL
    CHECK (split IN ('train', 'validation', 'test', 'holdout')),
  epoch_or_step INTEGER NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_metrics_model_name_split UNIQUE (model_key, metric_name, split)
);

COMMENT ON TABLE ml.metrics IS
'GRAIN: one row per metric recording (name/value/split). Business key '
'(model_key, metric_name, split) is unique. metric_name is free-text — no '
'columns are hardcoded for MAE/RMSE etc. New metrics can be added without '
'ALTER TABLE. metric_value is the scalar result. split identifies the data '
'partition. epoch_or_step tracks the training step if applicable.';

COMMENT ON COLUMN ml.metrics.metric_name IS
'Free-text metric name (e.g. "mae", "rmse", "accuracy", "f1", "r2", '
'"auc", "mape", "rmse_per_station", etc.). No columns are hardcoded for '
'specific metrics; the name is stored as data so new metrics can be added '
'without ALTER.';
COMMENT ON COLUMN ml.metrics.metric_value IS
'The scalar metric value. NULL is allowed only for metrics that '
'cannot yet be computed (e.g. pending experiment).';
COMMENT ON COLUMN ml.metrics.split IS
'The data partition the metric applies to: train, validation, test, '
'or holdout. One metric_name per split per model is the typical pattern.';
COMMENT ON COLUMN ml.metrics.epoch_or_step IS
'Training epoch or iteration step at which this metric was recorded. '
'NULL if the metric is not epoch-dependent (e.g. final holdout score).';

-- ============================================================================
-- 6. ml.prediction_runs — prediction-run metadata
-- GRAIN: one row per prediction-run metadata.
-- Business key: (model_key, station_id, date_key, time_key, run_at) — unique
--   per model+station+date+time combination when a prediction was generated.
-- NOTE: This table stores METADATA about prediction runs only — NOT the
-- actual prediction values. Actual predictions are generated by Python code
-- and are not stored in the DB (keeping prediction metadata separate from
-- prediction values per the hard requirement).
-- station_id is the operational UUID (business key) stored as a plain column
--   without a cross-layer FK. ETL resolves it to warehouse keys.
-- date_key and time_key are plain integers without cross-layer FKs.
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml.prediction_runs (
  prediction_run_key UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  model_key          UUID NOT NULL
    REFERENCES ml.model_versions (model_key) ON DELETE CASCADE,
  station_id         UUID NULL,
  date_key           INTEGER NULL,
  time_key           SMALLINT NULL,
  prediction_horizon TEXT NOT NULL
    CHECK (prediction_horizon IN ('1h', '3h', '6h', '12h', '24h', '48h', '72h',
                                   'custom')),
  run_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  status             TEXT NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'running', 'completed', 'failed')),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_predictionruns_model_station_datetime UNIQUE (model_key, station_id, date_key, time_key, run_at)
);

COMMENT ON TABLE ml.prediction_runs IS
'GRAIN: one row per prediction-run metadata. Stores metadata about a prediction '
'run only — NOT the actual prediction values. This separation keeps the ml layer '
'as a control/metadata layer only; actual predicted availability/congestion values '
'are generated by Python ETL and surfaced to the frontend via API, never stored '
'as persistent ML records. model_key links the model used. station_id '
'is the operational station UUID (business key, no cross-layer FK). date_key and '
'time_key are plain integers (no cross-layer FKs). prediction_horizon limits the '
'look-ahead window. status tracks the run lifecycle. run_at ensures reproducibility.';

COMMENT ON COLUMN ml.prediction_runs.station_id IS
'Operational station business key (public.stations.id). Stored as '
'plain UUID — no cross-layer FK to public.* or analytics.*. ETL resolves '
'the mapping to warehouse keys if needed.';
COMMENT ON COLUMN ml.prediction_runs.date_key IS
'Calendar date key (YYYYMMDD integer). Plain column without '
'cross-layer FK to analytics.dim_date. NULL when not date-specific.';
COMMENT ON COLUMN ml.prediction_runs.time_key IS
'15-minute time slot key (0..95). Plain column without cross-layer '
'FK to analytics.dim_time. NULL when not time-specific.';
COMMENT ON COLUMN ml.prediction_runs.prediction_horizon IS
'How far into the future the prediction covers. Kept as a limited '
'enumeration to ensure consistency; custom is allowed for ad-hoc horizons.';
COMMENT ON COLUMN ml.prediction_runs.run_at IS
'When this prediction run was initiated. Critical for '
'reproducibility: a model can be re-run at a different time and the '
'run_at distinguishes the runs.';
COMMENT ON COLUMN ml.prediction_runs.status IS
'Prediction-run status: proposed (scheduled) -> running (in '
'progress) -> completed (success) -> failed (error).';

-- ============================================================================
-- 7. Indexes for query performance
-- All indexes stay within the ml schema — no cross-layer index dependencies.
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_ml_features_name ON ml.features (feature_name);
CREATE INDEX IF NOT EXISTS idx_ml_features_group ON ml.features (feature_group);
CREATE INDEX IF NOT EXISTS idx_ml_datasets_name ON ml.datasets (dataset_name, version_str);
CREATE INDEX IF NOT EXISTS idx_ml_datasets_maturity ON ml.datasets (data_maturity);
CREATE INDEX IF NOT EXISTS idx_ml_experiments_dataset ON ml.experiments (dataset_key);
CREATE INDEX IF NOT EXISTS idx_ml_experiments_status ON ml.experiments (status);
CREATE INDEX IF NOT EXISTS idx_ml_modelversions_experiment ON ml.model_versions (experiment_key);
CREATE INDEX IF NOT EXISTS idx_ml_modelversions_status ON ml.model_versions (status);
CREATE INDEX IF NOT EXISTS idx_ml_modelversions_maturity ON ml.model_versions (data_maturity);
CREATE INDEX IF NOT EXISTS idx_ml_modelversions_trained ON ml.model_versions (trained_at) WHERE trained_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ml_metrics_model ON ml.metrics (model_key);
CREATE INDEX IF NOT EXISTS idx_ml_metrics_name_split ON ml.metrics (metric_name, split);
CREATE INDEX IF NOT EXISTS idx_ml_predictionruns_model ON ml.prediction_runs (model_key);
CREATE INDEX IF NOT EXISTS idx_ml_predictionruns_station_date ON ml.prediction_runs (station_id, date_key, time_key);
CREATE INDEX IF NOT EXISTS idx_ml_predictionruns_horizon ON ml.prediction_runs (prediction_horizon);
CREATE INDEX IF NOT EXISTS idx_ml_predictionruns_run_at ON ml.prediction_runs (run_at);

-- ============================================================================
-- 8. Migration assertion — verify no unintended data was seeded
-- All ml tables must be empty after migration (DDL-only, idempotent).
-- ============================================================================
DO $$
DECLARE
  v_feature_cnt       INTEGER;
  v_dataset_cnt       INTEGER;
  v_experiment_cnt    INTEGER;
  v_model_cnt         INTEGER;
  v_metric_cnt        INTEGER;
  v_prediction_cnt    INTEGER;
BEGIN
  SELECT count(*) INTO v_feature_cnt FROM ml.features;
  SELECT count(*) INTO v_dataset_cnt FROM ml.datasets;
  SELECT count(*) INTO v_experiment_cnt FROM ml.experiments;
  SELECT count(*) INTO v_model_cnt FROM ml.model_versions;
  SELECT count(*) INTO v_metric_cnt FROM ml.metrics;
  SELECT count(*) INTO v_prediction_cnt FROM ml.prediction_runs;

  -- Verify zero rows seeded (migration is DDL-only, idempotent)
  IF v_feature_cnt > 0 THEN
    RAISE EXCEPTION 'Step 1.5: ml.features must be empty after migration (no synthetic data), found %', v_feature_cnt;
  END IF;
  IF v_dataset_cnt > 0 THEN
    RAISE EXCEPTION 'Step 1.5: ml.datasets must be empty after migration (no synthetic data), found %', v_dataset_cnt;
  END IF;
  IF v_experiment_cnt > 0 THEN
    RAISE EXCEPTION 'Step 1.5: ml.experiments must be empty after migration (no synthetic data), found %', v_experiment_cnt;
  END IF;
  IF v_model_cnt > 0 THEN
    RAISE EXCEPTION 'Step 1.5: ml.model_versions must be empty after migration (no synthetic data), found %', v_model_cnt;
  END IF;
  IF v_metric_cnt > 0 THEN
    RAISE EXCEPTION 'Step 1.5: ml.metrics must be empty after migration (no synthetic data), found %', v_metric_cnt;
  END IF;
  IF v_prediction_cnt > 0 THEN
    RAISE EXCEPTION 'Step 1.5: ml.prediction_runs must be empty after migration (no synthetic data), found %', v_prediction_cnt;
  END IF;
END
$$;

-- ============================================================================
-- 9. Schema verification — confirm no cross-layer FKs exist
-- ============================================================================
DO $$
DECLARE
  v_cross_fk_count INTEGER;
BEGIN
  SELECT count(*)
  INTO v_cross_fk_count
  FROM pg_constraint con
  JOIN pg_class src_table
    ON src_table.oid = con.conrelid
  JOIN pg_namespace src_schema
    ON src_schema.oid = src_table.relnamespace
  JOIN pg_class ref_table
    ON ref_table.oid = con.confrelid
  JOIN pg_namespace ref_schema
    ON ref_schema.oid = ref_table.relnamespace
  WHERE con.contype = 'f'
    AND src_schema.nspname = 'ml'
    AND ref_schema.nspname <> 'ml';

  IF v_cross_fk_count > 0 THEN
    RAISE EXCEPTION
      'Step 1.5: Cross-layer foreign keys detected in ml schema: %. All FKs must stay within ml.',
      v_cross_fk_count;
  END IF;
END
$$;

-- End of Step 1.5 migration.
