-- ============================================================
-- ChargePlus — Phase 2 Recovery Migration
-- Harden public.ingestion_runs grants to Step 1.7 posture
-- ============================================================
-- Reality audit found public.ingestion_runs retained default grants
-- (anon/authenticated held INSERT/UPDATE/DELETE/TRUNCATE/TRIGGER),
-- violating Step 1.7 defense-in-depth for ingestion-managed tables.
--
-- Intended posture (mirrors Step 1.7 sections 1.1-1.2):
-- - anon/authenticated: SELECT only (operations console monitoring)
-- - writes: service_role only (Python scheduler ETL via BYPASSRLS)
-- - RLS policies unchanged (public read + service_role write)
-- ============================================================

BEGIN;

-- Strip overly-broad client privileges (including TRUNCATE/TRIGGER/REFERENCES).
REVOKE ALL ON public.ingestion_runs FROM anon, authenticated;

-- Least-privilege read for operations console & monitoring.
GRANT SELECT ON public.ingestion_runs TO anon, authenticated;

-- Server-side writer (idempotent; service_role already holds ALL via ownership).
GRANT ALL ON public.ingestion_runs TO service_role;

-- Self-verifying assertion: anon/authenticated must hold exactly SELECT.
DO $$
DECLARE
  v_bad_count integer;
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
END
$$;

COMMIT;
