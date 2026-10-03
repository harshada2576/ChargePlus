-- ============================================================
-- ChargePlus — Phase 2.12 Recovery Hardening
-- Allow Unknown Power (NULL power_kw) on Connectors
-- ============================================================
-- Connectors reported by legitimate sources with unknown power
-- must be preserved rather than dropped.
-- Invariants:
-- - missing power != 0 kW
-- - missing power != missing connector
-- - missing power != unavailable connector
-- - power_kw > 0 when known, NULL when unknown
-- ============================================================

BEGIN;

-- 1. Operational Table: public.connectors
ALTER TABLE public.connectors ALTER COLUMN power_kw DROP NOT NULL;

ALTER TABLE public.connectors DROP CONSTRAINT IF EXISTS connectors_power_kw_check;
ALTER TABLE public.connectors DROP CONSTRAINT IF EXISTS chk_connectors_power_kw;
ALTER TABLE public.connectors ADD CONSTRAINT chk_connectors_power_kw CHECK (power_kw IS NULL OR power_kw > 0);

-- Recreate capacity-group unique index with NULLS NOT DISTINCT (PostgreSQL 15+)
DROP INDEX IF EXISTS public.uq_connectors_station_type_power;
CREATE UNIQUE INDEX uq_connectors_station_type_power
  ON public.connectors (station_id, connector_type, power_kw, COALESCE(charging_standard, ''))
  NULLS NOT DISTINCT;

-- 2. Conformed Dimension: analytics.dim_connector
ALTER TABLE analytics.dim_connector ALTER COLUMN power_kw DROP NOT NULL;

ALTER TABLE analytics.dim_connector DROP CONSTRAINT IF EXISTS dim_connector_power_kw_check;
ALTER TABLE analytics.dim_connector DROP CONSTRAINT IF EXISTS chk_dim_connector_power_kw;
ALTER TABLE analytics.dim_connector ADD CONSTRAINT chk_dim_connector_power_kw CHECK (power_kw IS NULL OR power_kw > 0);

COMMIT;
