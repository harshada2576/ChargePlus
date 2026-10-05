-- ============================================================
-- ChargePlus — Pre-Phase-4 Remediation Gate (R5)
-- Restrict public.ingestion_runs reads to admins
-- ============================================================
-- Finding: ingestion_runs carried SELECT USING (true) with no TO clause,
-- so anonymous clients could read raw run metrics, error_summary, and
-- operational metadata.
--
-- Intended contract: ingestion-run detail is operator information.
-- Only the admin operations console reads it (AdminDashboard renders
-- solely for sessions whose canonical profile role is 'admin', and it
-- queries through the authenticated client, so the admin RLS check
-- passes). Anonymous and ordinary authenticated users get no rows.
-- service_role writes are unaffected (BYPASSRLS).
--
-- Grants: keep the least-privilege SELECT grant for authenticated
-- (RLS now enforces admin-only); revoke the anon SELECT grant so
-- anonymous callers are denied at both layers.
-- ============================================================

BEGIN;

-- 1. Replace the world-readable policy with the admin-only policy
--    (same EXISTS (profiles.role = 'admin') pattern as Step 1.7
--    data_sources_select_admin / station_source_link_select_admin).
DROP POLICY IF EXISTS "Allow public read access to ingestion_runs" ON public.ingestion_runs;

DROP POLICY IF EXISTS "ingestion_runs_select_admin" ON public.ingestion_runs;
CREATE POLICY "ingestion_runs_select_admin" ON public.ingestion_runs
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

-- 2. Belt-and-suspenders grants: anon loses even the grant-level SELECT.
REVOKE SELECT ON public.ingestion_runs FROM anon;
GRANT SELECT ON public.ingestion_runs TO authenticated;
GRANT ALL ON public.ingestion_runs TO service_role;

-- 3. Self-verifying assertions: no USING(true) SELECT policy remains,
--    exactly one admin SELECT policy exists, anon holds no grants.
DO $$
DECLARE
  v_open_count integer;
  v_admin_count integer;
  v_anon_grants integer;
BEGIN
  SELECT count(*) INTO v_open_count
  FROM pg_policies
  WHERE schemaname = 'public'
    AND tablename = 'ingestion_runs'
    AND cmd = 'SELECT'
    AND qual = 'true';

  SELECT count(*) INTO v_admin_count
  FROM pg_policies
  WHERE schemaname = 'public'
    AND tablename = 'ingestion_runs'
    AND policyname = 'ingestion_runs_select_admin';

  SELECT count(*) INTO v_anon_grants
  FROM information_schema.role_table_grants
  WHERE table_schema = 'public'
    AND table_name = 'ingestion_runs'
    AND grantee = 'anon';

  IF v_open_count <> 0 THEN
    RAISE EXCEPTION 'R5: world-readable ingestion_runs SELECT policy still present';
  END IF;
  IF v_admin_count <> 1 THEN
    RAISE EXCEPTION 'R5: ingestion_runs_select_admin policy missing';
  END IF;
  IF v_anon_grants <> 0 THEN
    RAISE EXCEPTION 'R5: anon still holds % grant(s) on ingestion_runs', v_anon_grants;
  END IF;
END
$$;

COMMIT;
