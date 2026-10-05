-- ============================================================
-- ChargePlus — Pre-Phase-4 Remediation Gate (R7)
-- Enforce one alert preference per (user, station, type)
-- ============================================================
-- Contract (src/lib/alerts.ts, schema comment): each watch condition
-- is a single row updated in place; setAlert does list-then-write and
-- callers serialize toggles with a pending lock. Without a database
-- guarantee, concurrent writes can create duplicate logical alerts.
--
-- Fix: partial unique index for station-scoped alerts. Rows with
-- station_id IS NULL (reserved for future nearby/watchlist semantics
-- per the Step 1.3 table comment) are intentionally left
-- unconstrained until that product contract is defined.
-- Fails loudly on pre-existing duplicates so they are cleaned
-- deliberately instead of silently kept.
-- ============================================================

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_user_station_type
  ON public.alerts (user_id, station_id, alert_type)
  WHERE station_id IS NOT NULL;

-- Self-verifying assertion.
DO $$
DECLARE
  v_count integer;
BEGIN
  SELECT count(*) INTO v_count
  FROM pg_indexes
  WHERE schemaname = 'public'
    AND tablename = 'alerts'
    AND indexname = 'uq_alerts_user_station_type';
  IF v_count <> 1 THEN
    RAISE EXCEPTION 'R7: uq_alerts_user_station_type missing on public.alerts';
  END IF;
END
$$;

COMMIT;
