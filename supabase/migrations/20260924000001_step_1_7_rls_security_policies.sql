-- ============================================================================
-- Migration: 20260924000001_step_1_7_rls_security_policies.sql
-- Phase: 1/6 — Foundation & Real Database
-- Step: 1.7/10 — RLS & Security Policies
--
-- Canonical Architecture:
--   public    = operational OLTP database (11 active tables, 29 RLS policies)
--   analytics = canonical OLAP / data warehouse (12 tables, RLS enabled, 0 client policies)
--   ml        = ML metadata/control layer (6 tables, RLS enabled, 0 client policies)
--   Python ETL = boundary between operational OLTP and canonical warehouse
--
-- Frozen Legacy Objects:
--   public.dim_date, public.dim_location, public.dim_station, public.dim_tariff,
--   public.dim_time, public.dim_vehicle, public.dim_weather,
--   public.fact_charging_session, public.fact_station_daily_agg
--   (UNTOTUCHED — RLS remains disabled, zero policies, zero changes).
--
-- Defense-in-Depth Security Strategy:
--   1. Schema & Table Grants: Revoke truncate/trigger/references; revoke client
--      writes on static/ingestion-managed operational tables; revoke UPDATE/INSERT
--      on profiles.role from authenticated users.
--   2. Row Level Security: Enforce tenant/ownership boundaries (auth.uid()),
--      public station discovery (is_public = true), admin moderation gates,
--      and append-only community contribution rules.
--   3. Controlled Service Boundary: Python ETL / background services access
--      warehouse tables via service_role / direct database pool (BYPASSRLS = true).
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. DEFENSE-IN-DEPTH: PRIVILEGES & GRANTS SANITIZATION
-- ============================================================================

-- 1.1 Revoke dangerous table-level privileges from anon and authenticated on public tables
REVOKE TRUNCATE, TRIGGER, REFERENCES ON ALL TABLES IN SCHEMA public FROM anon, authenticated;

-- 1.2 Revoke client writes on static / ingestion-managed operational tables
REVOKE INSERT, UPDATE, DELETE ON 
  public.operators, 
  public.stations, 
  public.connectors, 
  public.station_observations, 
  public.data_sources, 
  public.station_source_link 
FROM anon, authenticated;

-- 1.3 Revoke all permissions on internal provenance and user-isolated tables from anon
REVOKE ALL ON public.data_sources, public.station_source_link FROM anon;
REVOKE ALL ON public.profiles, public.user_reports, public.favorites, public.alerts FROM anon;

-- 1.4 Grant appropriate base read permissions to anon and authenticated
GRANT SELECT ON public.operators, public.stations, public.connectors, public.station_observations, public.reviews TO anon, authenticated;
GRANT SELECT ON public.data_sources, public.station_source_link TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_reports, public.reviews, public.alerts TO authenticated;
GRANT SELECT, INSERT, DELETE ON public.favorites TO authenticated;
GRANT SELECT ON public.profiles TO authenticated;

-- 1.5 Protect profiles.role at column privilege level (Privilege Escalation Defense)
REVOKE INSERT, UPDATE ON public.profiles FROM anon, authenticated;
GRANT UPDATE (display_name, preferred_language, home_city, updated_at) ON public.profiles TO authenticated;
GRANT INSERT (id, display_name, preferred_language, home_city, created_at, updated_at) ON public.profiles TO authenticated;

-- ============================================================================
-- 2. ENABLE ROW LEVEL SECURITY ACROSS ALL 29 ACTIVE TARGET TABLES
-- ============================================================================

-- 2.1 Public Schema Operational Tables (11 tables)
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.operators ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.connectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.station_source_link ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.station_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.favorites ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alerts ENABLE ROW LEVEL SECURITY;

-- 2.2 Analytics Warehouse Schema Tables (12 tables)
ALTER TABLE analytics.dim_station ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.dim_operator ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.dim_location ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.dim_connector ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.dim_date ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.dim_time ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.dim_source ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.dim_weather ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.fact_station_observation ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.fact_user_report ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.fact_review ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.fact_station_daily ENABLE ROW LEVEL SECURITY;

-- 2.3 ML Metadata/Control Schema Tables (6 tables)
ALTER TABLE ml.features ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml.datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml.experiments ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml.model_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml.metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml.prediction_runs ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- 3. CREATE EXACTLY 29 POLICIES ON PUBLIC OPERATIONAL TABLES
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 3.1 public.profiles (3 policies)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "profiles_select_own" ON public.profiles;
CREATE POLICY "profiles_select_own" ON public.profiles
  FOR SELECT TO authenticated
  USING (id = auth.uid());

DROP POLICY IF EXISTS "profiles_insert_own" ON public.profiles;
CREATE POLICY "profiles_insert_own" ON public.profiles
  FOR INSERT TO authenticated
  WITH CHECK (id = auth.uid() AND (role IS NULL OR role = 'user'));

DROP POLICY IF EXISTS "profiles_update_own" ON public.profiles;
CREATE POLICY "profiles_update_own" ON public.profiles
  FOR UPDATE TO authenticated
  USING (id = auth.uid())
  WITH CHECK (id = auth.uid());

-- ----------------------------------------------------------------------------
-- 3.2 public.operators (1 policy)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "operators_select_public" ON public.operators;
CREATE POLICY "operators_select_public" ON public.operators
  FOR SELECT TO anon, authenticated
  USING (true);

-- ----------------------------------------------------------------------------
-- 3.3 public.stations (1 policy)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "stations_select_public" ON public.stations;
CREATE POLICY "stations_select_public" ON public.stations
  FOR SELECT TO anon, authenticated
  USING (is_public = true);

-- ----------------------------------------------------------------------------
-- 3.4 public.connectors (1 policy)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "connectors_select_public" ON public.connectors;
CREATE POLICY "connectors_select_public" ON public.connectors
  FOR SELECT TO anon, authenticated
  USING (EXISTS (
    SELECT 1 FROM public.stations s
    WHERE s.id = connectors.station_id AND s.is_public = true
  ));

-- ----------------------------------------------------------------------------
-- 3.5 public.station_observations (1 policy)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "station_observations_select_public" ON public.station_observations;
CREATE POLICY "station_observations_select_public" ON public.station_observations
  FOR SELECT TO anon, authenticated
  USING (EXISTS (
    SELECT 1 FROM public.stations s
    WHERE s.id = station_observations.station_id AND s.is_public = true
  ));

-- ----------------------------------------------------------------------------
-- 3.6 public.data_sources (1 policy)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "data_sources_select_admin" ON public.data_sources;
CREATE POLICY "data_sources_select_admin" ON public.data_sources
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

-- ----------------------------------------------------------------------------
-- 3.7 public.station_source_link (1 policy)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "station_source_link_select_admin" ON public.station_source_link;
CREATE POLICY "station_source_link_select_admin" ON public.station_source_link
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

-- ----------------------------------------------------------------------------
-- 3.8 public.user_reports (5 policies)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "user_reports_select_own" ON public.user_reports;
CREATE POLICY "user_reports_select_own" ON public.user_reports
  FOR SELECT TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS "user_reports_select_admin" ON public.user_reports;
CREATE POLICY "user_reports_select_admin" ON public.user_reports
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

DROP POLICY IF EXISTS "user_reports_insert_own" ON public.user_reports;
CREATE POLICY "user_reports_insert_own" ON public.user_reports
  FOR INSERT TO authenticated
  WITH CHECK (
    user_id = auth.uid()
    AND moderation_status = 'pending'
    AND moderated_by IS NULL
    AND moderated_at IS NULL
    AND moderation_reason IS NULL
    AND is_flagged = false
  );

DROP POLICY IF EXISTS "user_reports_update_admin" ON public.user_reports;
CREATE POLICY "user_reports_update_admin" ON public.user_reports
  FOR UPDATE TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

DROP POLICY IF EXISTS "user_reports_delete_admin" ON public.user_reports;
CREATE POLICY "user_reports_delete_admin" ON public.user_reports
  FOR DELETE TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

-- ----------------------------------------------------------------------------
-- 3.9 public.reviews (8 policies)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "reviews_select_approved" ON public.reviews;
CREATE POLICY "reviews_select_approved" ON public.reviews
  FOR SELECT TO anon, authenticated
  USING (moderation_status = 'approved');

DROP POLICY IF EXISTS "reviews_select_own" ON public.reviews;
CREATE POLICY "reviews_select_own" ON public.reviews
  FOR SELECT TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS "reviews_select_admin" ON public.reviews;
CREATE POLICY "reviews_select_admin" ON public.reviews
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

DROP POLICY IF EXISTS "reviews_insert_own" ON public.reviews;
CREATE POLICY "reviews_insert_own" ON public.reviews
  FOR INSERT TO authenticated
  WITH CHECK (
    user_id = auth.uid()
    AND moderation_status = 'pending'
    AND moderated_by IS NULL
    AND moderated_at IS NULL
    AND moderation_reason IS NULL
    AND is_flagged = false
  );

DROP POLICY IF EXISTS "reviews_update_own" ON public.reviews;
CREATE POLICY "reviews_update_own" ON public.reviews
  FOR UPDATE TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (
    user_id = auth.uid()
    AND moderation_status = 'pending'
    AND moderated_by IS NULL
    AND moderated_at IS NULL
    AND moderation_reason IS NULL
    AND is_flagged = false
  );

DROP POLICY IF EXISTS "reviews_update_admin" ON public.reviews;
CREATE POLICY "reviews_update_admin" ON public.reviews
  FOR UPDATE TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

DROP POLICY IF EXISTS "reviews_delete_own" ON public.reviews;
CREATE POLICY "reviews_delete_own" ON public.reviews
  FOR DELETE TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS "reviews_delete_admin" ON public.reviews;
CREATE POLICY "reviews_delete_admin" ON public.reviews
  FOR DELETE TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.profiles p
    WHERE p.id = auth.uid() AND p.role = 'admin'
  ));

-- ----------------------------------------------------------------------------
-- 3.10 public.favorites (3 policies)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "favorites_select_own" ON public.favorites;
CREATE POLICY "favorites_select_own" ON public.favorites
  FOR SELECT TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS "favorites_insert_own" ON public.favorites;
CREATE POLICY "favorites_insert_own" ON public.favorites
  FOR INSERT TO authenticated
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "favorites_delete_own" ON public.favorites;
CREATE POLICY "favorites_delete_own" ON public.favorites
  FOR DELETE TO authenticated
  USING (user_id = auth.uid());

-- ----------------------------------------------------------------------------
-- 3.11 public.alerts (4 policies)
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS "alerts_select_own" ON public.alerts;
CREATE POLICY "alerts_select_own" ON public.alerts
  FOR SELECT TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS "alerts_insert_own" ON public.alerts;
CREATE POLICY "alerts_insert_own" ON public.alerts
  FOR INSERT TO authenticated
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "alerts_update_own" ON public.alerts;
CREATE POLICY "alerts_update_own" ON public.alerts
  FOR UPDATE TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "alerts_delete_own" ON public.alerts;
CREATE POLICY "alerts_delete_own" ON public.alerts
  FOR DELETE TO authenticated
  USING (user_id = auth.uid());

-- ============================================================================
-- 4. ATOMIC SELF-VERIFYING ASSERTIONS BLOCK
-- ============================================================================
DO $$
DECLARE
  v_rls_count INTEGER;
  v_legacy_rls_count INTEGER;
  v_policy_count INTEGER;
  v_analytics_policy_count INTEGER;
  v_ml_policy_count INTEGER;
  v_cross_fk_count INTEGER;
  v_dim_date_count INTEGER;
  v_dim_time_count INTEGER;
  v_stations_count INTEGER;
  v_legacy_count INTEGER;
BEGIN
  -- 1. Assert exactly 29 active tables have RLS enabled (11 public + 12 analytics + 6 ml)
  SELECT count(*) INTO v_rls_count
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname IN ('public', 'analytics', 'ml')
    AND c.relkind = 'r'
    AND c.relrowsecurity = true;
  IF v_rls_count <> 29 THEN
    RAISE EXCEPTION 'CRITICAL: Active RLS table count mismatch (expected 29, got %)', v_rls_count;
  END IF;

  -- 2. Assert zero legacy tables have RLS enabled (legacy public dim_*/fact_* remain untouched)
  SELECT count(*) INTO v_legacy_rls_count
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public'
    AND c.relname IN (
      'dim_date', 'dim_location', 'dim_station', 'dim_tariff', 'dim_time',
      'dim_vehicle', 'dim_weather', 'fact_charging_session', 'fact_station_daily_agg'
    )
    AND c.relrowsecurity = true;
  IF v_legacy_rls_count <> 0 THEN
    RAISE EXCEPTION 'CRITICAL: Legacy tables RLS violation (expected 0, got %)', v_legacy_rls_count;
  END IF;

  -- 3. Assert exactly 29 policies created in public schema
  SELECT count(*) INTO v_policy_count
  FROM pg_policies
  WHERE schemaname = 'public';
  IF v_policy_count <> 29 THEN
    RAISE EXCEPTION 'CRITICAL: Public policy count mismatch (expected 29, got %)', v_policy_count;
  END IF;

  -- 4. Assert zero client policies in analytics or ml schemas
  SELECT count(*) INTO v_analytics_policy_count FROM pg_policies WHERE schemaname = 'analytics';
  SELECT count(*) INTO v_ml_policy_count FROM pg_policies WHERE schemaname = 'ml';
  IF v_analytics_policy_count <> 0 OR v_ml_policy_count <> 0 THEN
    RAISE EXCEPTION 'CRITICAL: Policies detected in analytics (%) or ml (%)', v_analytics_policy_count, v_ml_policy_count;
  END IF;

  -- 5. Assert zero cross-layer foreign keys (using authoritative pg_catalog OID relationships)
  SELECT count(*) INTO v_cross_fk_count
  FROM pg_constraint con
  JOIN pg_class src_table ON src_table.oid = con.conrelid
  JOIN pg_namespace src_schema ON src_schema.oid = src_table.relnamespace
  JOIN pg_class ref_table ON ref_table.oid = con.confrelid
  JOIN pg_namespace ref_schema ON ref_schema.oid = ref_table.relnamespace
  WHERE con.contype = 'f'
    AND src_schema.nspname IN ('analytics', 'ml')
    AND ref_schema.nspname <> src_schema.nspname;
  IF v_cross_fk_count > 0 THEN
    RAISE EXCEPTION 'CRITICAL: Cross-layer foreign keys detected (count=%)', v_cross_fk_count;
  END IF;

  -- 6. Assert reference data counts remain unchanged
  SELECT count(*) INTO v_dim_date_count FROM analytics.dim_date;
  IF v_dim_date_count <> 3288 THEN
    RAISE EXCEPTION 'CRITICAL: analytics.dim_date row count mutated (expected 3288, got %)', v_dim_date_count;
  END IF;

  SELECT count(*) INTO v_dim_time_count FROM analytics.dim_time;
  IF v_dim_time_count <> 96 THEN
    RAISE EXCEPTION 'CRITICAL: analytics.dim_time row count mutated (expected 96, got %)', v_dim_time_count;
  END IF;

  -- 7. Assert operational stations remain at 0 rows (DDL-only, no fake data)
  SELECT count(*) INTO v_stations_count FROM public.stations;
  IF v_stations_count <> 0 THEN
    RAISE EXCEPTION 'CRITICAL: Data insertion detected on public.stations (count=%)', v_stations_count;
  END IF;

  -- 8. Assert legacy tables remain at 0 rows
  SELECT count(*) INTO v_legacy_count FROM public.dim_date;
  IF v_legacy_count <> 0 THEN
    RAISE EXCEPTION 'CRITICAL: Data mutation on legacy public.dim_date (count=%)', v_legacy_count;
  END IF;
END $$;

COMMIT;
