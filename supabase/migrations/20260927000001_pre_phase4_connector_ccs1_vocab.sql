-- ============================================================
-- ChargePlus — Pre-Phase-4 Remediation Gate (R4)
-- Extend canonical connector vocabulary with CCS1
-- ============================================================
-- Finding: backend StandardConnectorType (constants.py) and the OCM
-- adapter (OCM connection type 32) can emit 'CCS1', and the frontend
-- ConnectorType already renders 'CCS1' — but the database CHECK
-- constraints only allowed 7 values, so CCS1 connectors were silently
-- skipped at persistence (counted, never stored).
--
-- Fix: extend the DB vocabulary with 'CCS1' on public.connectors and
-- analytics.dim_connector. 'Other' intentionally remains excluded: it
-- carries no physical information and has no honest DB representation;
-- Other-typed connectors stay skipped + counted (station shell kept).
-- Existing rows are a subset of the new vocabulary, so the migration
-- is non-destructive and replay-safe.
-- ============================================================

BEGIN;

-- 1. public.connectors: replace the vocabulary CHECK (whatever its
--    historical name) with the CCS1-inclusive named constraint.
DO $$
DECLARE
  v_conname text;
BEGIN
  SELECT conname INTO v_conname
  FROM pg_constraint
  WHERE conrelid = 'public.connectors'::regclass
    AND contype = 'c'
    AND pg_get_constraintdef(oid) LIKE '%connector_type IN%';

  IF v_conname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE public.connectors DROP CONSTRAINT %I', v_conname);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_connectors_connector_type') THEN
    ALTER TABLE public.connectors
      ADD CONSTRAINT chk_connectors_connector_type
      CHECK (connector_type IN ('CCS2', 'CCS1', 'CHAdeMO', 'Type 2', 'Type 1',
                                'GB/T', 'Bharat AC001', 'Bharat DC001'));
  END IF;
END
$$;

-- 2. analytics.dim_connector parity (Step 1.6 chk_dim_connector_type).
ALTER TABLE analytics.dim_connector DROP CONSTRAINT IF EXISTS chk_dim_connector_type;
ALTER TABLE analytics.dim_connector
  ADD CONSTRAINT chk_dim_connector_type
  CHECK (connector_type IN ('CCS2', 'CCS1', 'CHAdeMO', 'Type 2', 'Type 1',
                            'GB/T', 'Bharat AC001', 'Bharat DC001'));

-- 3. Self-verifying assertions.
DO $$
DECLARE
  v_pub_count integer;
  v_dim_count integer;
BEGIN
  SELECT count(*) INTO v_pub_count
  FROM pg_constraint
  WHERE conrelid = 'public.connectors'::regclass
    AND contype = 'c'
    AND pg_get_constraintdef(oid) LIKE '%connector_type IN%';
  IF v_pub_count <> 1 THEN
    RAISE EXCEPTION 'R4: expected exactly 1 connector_type vocabulary CHECK on public.connectors, found %', v_pub_count;
  END IF;

  SELECT count(*) INTO v_dim_count
  FROM pg_constraint
  WHERE conname = 'chk_dim_connector_type'
    AND pg_get_constraintdef(oid) LIKE '%CCS1%';
  IF v_dim_count <> 1 THEN
    RAISE EXCEPTION 'R4: chk_dim_connector_type missing or not CCS1-inclusive';
  END IF;
END
$$;

COMMIT;
