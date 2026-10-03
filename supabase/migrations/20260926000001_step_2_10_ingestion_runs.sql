-- ============================================================
-- ChargePlus — Phase 2 Step 2.10 Migration
-- Ingestion Runs Audit & Operational Monitoring
-- ============================================================
-- Tracks ingestion workflow runs, attempt counts, execution metrics,
-- error summaries, and operational states for data quality audits.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.ingestion_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id UUID NULL REFERENCES public.data_sources(id) ON DELETE SET NULL,
  source_name TEXT NOT NULL CHECK (char_length(source_name) BETWEEN 1 AND 120),
  scope TEXT NOT NULL CHECK (char_length(scope) BETWEEN 1 AND 255),
  state TEXT NOT NULL CHECK (state IN ('STARTED', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ NULL,
  duration_seconds NUMERIC(10, 2) NULL,
  attempt_count INTEGER NOT NULL DEFAULT 1 CHECK (attempt_count >= 1),
  records_fetched INTEGER NOT NULL DEFAULT 0 CHECK (records_fetched >= 0),
  records_parsed INTEGER NOT NULL DEFAULT 0 CHECK (records_parsed >= 0),
  records_accepted INTEGER NOT NULL DEFAULT 0 CHECK (records_accepted >= 0),
  records_accepted_with_warnings INTEGER NOT NULL DEFAULT 0 CHECK (records_accepted_with_warnings >= 0),
  records_quarantined INTEGER NOT NULL DEFAULT 0 CHECK (records_quarantined >= 0),
  records_rejected INTEGER NOT NULL DEFAULT 0 CHECK (records_rejected >= 0),
  stations_persisted INTEGER NOT NULL DEFAULT 0 CHECK (stations_persisted >= 0),
  stations_updated INTEGER NOT NULL DEFAULT 0 CHECK (stations_updated >= 0),
  stations_unchanged INTEGER NOT NULL DEFAULT 0 CHECK (stations_unchanged >= 0),
  connectors_persisted INTEGER NOT NULL DEFAULT 0 CHECK (connectors_persisted >= 0),
  observations_persisted INTEGER NOT NULL DEFAULT 0 CHECK (observations_persisted >= 0),
  error_summary TEXT NULL,
  metadata JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.ingestion_runs IS 'Step 2.10: operational accounting of scheduled and manual ingestion pipeline runs, metrics, and error classifications.';

-- Indexes for monitoring queries and console views
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source_started 
  ON public.ingestion_runs(source_name, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_state 
  ON public.ingestion_runs(state);

-- Enable Row-Level Security
ALTER TABLE public.ingestion_runs ENABLE ROW LEVEL SECURITY;

-- Read policy: Allow public/authenticated read access for operations console & monitoring
CREATE POLICY "Allow public read access to ingestion_runs" 
  ON public.ingestion_runs 
  FOR SELECT 
  USING (true);

-- Write policy: Only service_role can insert/update run records
CREATE POLICY "Allow service_role write access to ingestion_runs" 
  ON public.ingestion_runs 
  FOR ALL 
  TO service_role 
  USING (true) 
  WITH CHECK (true);
