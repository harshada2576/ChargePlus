-- ============================================================
-- ChargePlus — Phase 4 Step 4.1 (dimensions)
-- analytics.dim_connector: allow unknown power (NULL), keep > 0 rule
-- ============================================================
-- Finding: Step 2.12 made public.connectors.power_kw nullable
-- (unknown power preserved as NULL), and the canonical persistence
-- path mirrors NULL-power connectors into analytics.dim_connector —
-- but dim_connector.power_kw stayed NOT NULL, so any NULL-power
-- connector mirror violates the constraint and rolls back the whole
-- canonical decision. The warehouse must preserve the same
-- unknown-means-NULL semantics as OLTP.
--
-- Fix: DROP NOT NULL (no-op if already nullable) + CHECK
-- (power_kw IS NULL OR power_kw > 0), mirroring chk_connectors_power_kw.
-- No data change: existing rows already satisfy the CHECK.
-- Idempotent and replay-safe.
-- ============================================================

BEGIN;

ALTER TABLE analytics.dim_connector ALTER COLUMN power_kw DROP NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_dim_connector_power_kw') THEN
    ALTER TABLE analytics.dim_connector
      ADD CONSTRAINT chk_dim_connector_power_kw
      CHECK (power_kw IS NULL OR power_kw > 0);
  END IF;
END
$$;

-- Self-verifying assertions.
DO $$
DECLARE
  v_nullable text;
  v_chk integer;
BEGIN
  SELECT is_nullable INTO v_nullable
  FROM information_schema.columns
  WHERE table_schema = 'analytics'
    AND table_name = 'dim_connector'
    AND column_name = 'power_kw';
  IF v_nullable <> 'YES' THEN
    RAISE EXCEPTION '4.1: analytics.dim_connector.power_kw must be nullable';
  END IF;

  SELECT count(*) INTO v_chk
  FROM pg_constraint
  WHERE conname = 'chk_dim_connector_power_kw'
    AND pg_get_constraintdef(oid) LIKE '%power_kw IS NULL%';
  IF v_chk <> 1 THEN
    RAISE EXCEPTION '4.1: chk_dim_connector_power_kw missing on analytics.dim_connector';
  END IF;
END
$$;

COMMIT;
