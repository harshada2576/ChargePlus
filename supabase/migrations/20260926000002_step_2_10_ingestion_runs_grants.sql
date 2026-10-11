-- ============================================================
-- ChargePlus — Phase 2 Recovery Migration
-- Harden public.ingestion_runs grants to Step 1.7 posture
-- ============================================================
-- Reality audit found public.ingestion_runs retained default grants
-- (anon/authenticated held INSERT/UPDATE/DELETE/TRUNCATE/TRIGGER),
-- violating Step 1.7 defense-in-depth for ingestion-managed tables.
--
-- Intended posture (mirrors Step 1.7 sections 1.1-1.2):
-- - anon/authenticated: SELECT only (operations console monitoring),
--   restricted by RLS admin-only policy.
-- - writes: service_role only (Python scheduler ETL via BYPASSRLS)
-- - RLS policies: admin-only SELECT, no world-readable policies
-- ============================================================

BEGIN;

-- Enable Row-Level Security on ingestion_runs (idempotent if already enabled)
ALTER TABLE public.ingestion_runs ENABLE ROW LEVEL SECURITY;

-- Strip overly-broad client privileges (including TRUNCATE/TRIGGER/REFERENCES).
REVOKE ALL ON public.ingestion_runs FROM anon, authenticated;

-- Least-privilege read for operations console & monitoring.
-- Table-level SELECT grant is a fallback; actual access is governed by RLS policies.
GRANT SELECT ON public.ingestion_runs TO anon, authenticated;

-- Server-side writer (idempotent; service_role already holds ALL via ownership).
GRANT ALL ON public.ingestion_runs TO service_role;

-- Create admin-only SELECT policy: only users with admin profile role can read.
DROP POLICY IF EXISTS "ingestion_runs_select_admin" ON public.ingestion_runs;
CREATE POLICY "ingestion_runs_select_admin" ON public.ingestion_runs
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

-- Self-verifying assertion: anon/authenticated must hold exactly SELECT at table level.
DO $$
DECLARE
  v_bad_count integer;
  v_select_count integer;
BEGIN
  SELECT count(*) INTO v_bad_count
  FROM information_schema.role_table_grants
  WHERE table_schema = 'public'
    AND table_name = 'ingestion_runs'
    AND grantee IN ('anon', 'authenticated')
    AND privilege_type <> 'SELECT';
  IF v_bad_count <> 0 THEN
    RAISE EXCEPTION 'ingestion_runs grants hardening failed: % non-SELECT client grants remain', v_bad_count;
  END IF;

  SELECT count(*) INTO v_select_count
  FROM information_schema.role_table_grants
  WHERE table_schema = 'public'
    AND table_name = 'ingestion_runs'
    AND grantee IN ('anon', 'authenticated')
    AND privilege_type = 'SELECT';
  IF v_select_count <> 2 THEN
    RAISE EXCEPTION 'ingestion_runs grants hardening failed: expected SELECT for anon and authenticated, found % grant(s)', v_select_count;
  END IF;
END
$$;

COMMIT;
