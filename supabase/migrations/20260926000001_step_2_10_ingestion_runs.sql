-- ============================================================
-- ChargePlus — Phase 2 Step 2.10 Migration
-- Ingestion Runs Audit & Operational Monitoring
-- ============================================================
-- Tracks ingestion workflow runs, attempt counts, execution metrics,
-- error summaries, and operational states for data quality audits.
--
-- Access posture (see the two follow-up hardenings, which only re-assert this):
--   authenticated: SELECT restricted to public.profiles.role = 'admin'
--   service_role : ALL (Python scheduler / ETL writer, BYPASSRLS)
--   anon         : nothing (table grants revoked by 20260926000002)
--
-- IDEMPOTENCY: DROP POLICY IF EXISTS / CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT
-- EXISTS make the file safe to replay for partial-failure recovery.
-- Under Supabase CLI this file runs once via supabase_migrations history.
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

-- Read policy: ingestion-run accounting is operator information, so reads are admin-only
-- (same EXISTS (profiles.role = 'admin') pattern as Step 1.7 data_sources/station_source_link).
-- It is written directly in its final least-privilege form on purpose: if this file is ever
-- replayed (partial-failure recovery), it must not re-introduce a world-readable policy.
-- The follow-up hardenings (20260926000002 grants, pre-phase-4 R5) only re-assert the same
-- posture, so replaying any of them is a no-op.
DROP POLICY IF EXISTS "Allow public read access to ingestion_runs" ON public.ingestion_runs;
DROP POLICY IF EXISTS "ingestion_runs_select_admin" ON public.ingestion_runs;
CREATE POLICY "ingestion_runs_select_admin" ON public.ingestion_runs
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

-- Write policy: Only service_role can insert/update run records (BYPASSRLS writer)
DROP POLICY IF EXISTS "Allow service_role write access to ingestion_runs" ON public.ingestion_runs;
CREATE POLICY "Allow service_role write access to ingestion_runs"
  ON public.ingestion_runs
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);