-- ============================================================================
-- CHARGEPLUS — MIGRATION: PHASE 1 / STEP 1.8: VIEWS + FUNCTIONS
-- File: supabase/migrations/20260925000001_step_1_8_views_functions.sql
--
-- PURPOSE:
-- Implement a conservative, production-safe view and function layer composing
-- the operational schema and canonical data warehouse:
-- 1. Helper function for sanitizing review author display names (SECURITY DEFINER)
-- 2. Canonical public station current-state view (v_station_current_state)
-- 3. Station connector specifications & availability view (v_station_connectors)
-- 4. Sanitized approved community reviews view (v_station_approved_reviews)
-- 5. PostGIS geospatial discovery function (nearby_stations, SECURITY INVOKER)
-- 6. Canonical analytics warehouse daily summary view (analytics.v_station_daily_summary)
-- 7. Self-verifying architectural assertion block
--
-- ARCHITECTURAL BOUNDARIES (STRICT):
--   public     = OPERATIONAL OLTP (real-time app state, RLS enabled, security_invoker views)
--   analytics  = DATA WAREHOUSE OLAP (historical star-schema facts/dims, Python ETL writes)
--   ml         = ML METADATA & CONTROL (model versions, features, runs)
--   legacy     = 9 legacy public.dim_* / public.fact_* tables remain UNTOUCHED and EMPTY
--
-- SECURITY PRINCIPLES:
-- - Views created WITH (security_invoker = true) so caller's RLS is strictly enforced
-- - Functions use explicit fixed search_path to prevent search_path spoofing
-- - nearby_stations is SECURITY INVOKER (caller's RLS applies, bounded radius and limits)
-- - get_author_display_name is SECURITY DEFINER strictly returning display_name text,
--   preventing exposure of the profiles table or auth user UUIDs
-- - Raw user_reports, internal provenance (station_source_link), and data_sources
--   remain completely unexposed in public views
-- - Zero synthetic/fake data inserted
-- ============================================================================

-- ============================================================================
-- PART 1: HELPER FUNCTIONS
-- ============================================================================

-- Helper function to resolve an author's public display name from profiles
-- without exposing user UUIDs, email, home city, or role.
CREATE OR REPLACE FUNCTION public.get_author_display_name(author_id uuid)
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE(NULLIF(TRIM(p.display_name), ''), 'Verified Driver')
  FROM public.profiles p
  WHERE p.id = author_id;
$$;

COMMENT ON FUNCTION public.get_author_display_name(uuid) IS
  'Step 1.8: Returns sanitized author display name for public reviews without exposing user IDs or private profile columns.';

REVOKE ALL ON FUNCTION public.get_author_display_name(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_author_display_name(uuid) TO anon, authenticated, service_role;

-- ============================================================================
-- PART 2: OPERATIONAL PUBLIC VIEWS (OLTP)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 2.1 public.v_station_current_state
-- Composes station identity, operator details, location, static connector specs,
-- latest live observation status, and approved community review metrics.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.v_station_current_state
WITH (security_invoker = true)
AS
WITH conn_summary AS (
    SELECT 
        c.station_id,
        count(c.id)::integer AS total_connector_types,
        coalesce(sum(c.quantity), 0)::integer AS total_plugs,
        max(c.power_kw) AS max_power_kw,
        min(c.price_per_kwh) AS min_price_per_kwh,
        coalesce(array_agg(DISTINCT c.connector_type ORDER BY c.connector_type), ARRAY[]::text[]) AS connector_types
    FROM public.connectors c
    GROUP BY c.station_id
),
rev_summary AS (
    SELECT 
        r.station_id,
        round(avg(r.rating)::numeric, 2) AS avg_rating,
        count(r.id)::bigint AS review_count
    FROM public.reviews r
    WHERE r.moderation_status = 'approved'
    GROUP BY r.station_id
),
latest_obs AS (
    SELECT DISTINCT ON (obs.station_id)
        obs.station_id,
        obs.id AS latest_observation_id,
        obs.availability_status AS latest_availability_status,
        obs.queue_level AS latest_queue_level,
        obs.available_connectors AS latest_available_connectors,
        obs.total_connectors AS latest_observed_total_connectors,
        obs.observed_at AS latest_observed_at
    FROM public.station_observations obs
    WHERE obs.observed_at <= now()
    ORDER BY obs.station_id, (obs.connector_id IS NULL) DESC, obs.observed_at DESC, obs.received_at DESC, obs.id DESC
)
SELECT 
    s.id,
    s.slug,
    s.name,
    s.operator_id,
    o.name AS operator_name,
    o.slug AS operator_slug,
    o.website_url AS operator_website,
    o.support_phone AS operator_phone,
    s.address_line,
    s.locality,
    s.city,
    s.state,
    s.postal_code,
    s.country,
    s.latitude,
    s.longitude,
    s.geom,
    s.is_24_hours,
    s.opening_time,
    s.closing_time,
    s.access_type,
    s.operational_status,
    s.phone,
    s.website_url,
    s.last_verified_at,
    s.updated_at,
    -- Static connector aggregates
    coalesce(cs.total_connector_types, 0)::integer AS total_connector_types,
    coalesce(cs.total_plugs, 0)::integer AS total_plugs,
    cs.max_power_kw,
    cs.min_price_per_kwh,
    coalesce(cs.connector_types, ARRAY[]::text[]) AS connector_types,
    -- Live observation state (NULL if no observation exists)
    lo.latest_observation_id,
    lo.latest_availability_status,
    lo.latest_queue_level,
    lo.latest_available_connectors,
    lo.latest_observed_total_connectors,
    lo.latest_observed_at,
    CASE 
        WHEN lo.latest_observed_at IS NOT NULL 
        THEN round(EXTRACT(EPOCH FROM (now() - lo.latest_observed_at)) / 60.0)::integer
        ELSE NULL 
    END AS minutes_since_observation,
    -- Community review aggregates (from approved reviews only)
    rs.avg_rating,
    coalesce(rs.review_count, 0)::bigint AS review_count
FROM public.stations s
JOIN public.operators o ON s.operator_id = o.id
LEFT JOIN conn_summary cs ON cs.station_id = s.id
LEFT JOIN rev_summary rs ON rs.station_id = s.id
LEFT JOIN latest_obs lo ON lo.station_id = s.id;

COMMENT ON VIEW public.v_station_current_state IS
  'Step 1.8: Canonical public view composing station metadata, operator details, connector specs, latest observation, and approved reviews.';

REVOKE ALL ON public.v_station_current_state FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.v_station_current_state FROM anon, authenticated;
GRANT SELECT ON public.v_station_current_state TO anon, authenticated, service_role;

-- ----------------------------------------------------------------------------
-- 2.2 public.v_station_connectors
-- Exposes connector specifications per station alongside the latest connector-level
-- live observation (if one exists).
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.v_station_connectors
WITH (security_invoker = true)
AS
WITH latest_conn_obs AS (
    SELECT DISTINCT ON (obs.connector_id)
        obs.connector_id,
        obs.availability_status AS latest_availability_status,
        obs.available_connectors AS latest_available_connectors,
        obs.observed_at AS latest_observed_at
    FROM public.station_observations obs
    WHERE obs.connector_id IS NOT NULL
      AND obs.observed_at <= now()
    ORDER BY obs.connector_id, obs.observed_at DESC, obs.received_at DESC, obs.id DESC
)
SELECT 
    c.id,
    c.station_id,
    c.connector_type,
    c.charging_standard,
    c.power_kw,
    c.quantity AS total_quantity,
    c.pricing_type,
    c.price_per_kwh,
    c.price_per_session,
    c.currency,
    lco.latest_availability_status,
    lco.latest_available_connectors,
    lco.latest_observed_at,
    CASE 
        WHEN lco.latest_observed_at IS NOT NULL 
        THEN round(EXTRACT(EPOCH FROM (now() - lco.latest_observed_at)) / 60.0)::integer
        ELSE NULL 
    END AS minutes_since_observation
FROM public.connectors c
LEFT JOIN latest_conn_obs lco ON lco.connector_id = c.id;

COMMENT ON VIEW public.v_station_connectors IS
  'Step 1.8: Connector specifications and connector-level availability status for station detail.';

REVOKE ALL ON public.v_station_connectors FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.v_station_connectors FROM anon, authenticated;
GRANT SELECT ON public.v_station_connectors TO anon, authenticated, service_role;

-- ----------------------------------------------------------------------------
-- 2.3 public.v_station_approved_reviews
-- Exposes approved community reviews with author display names, omitting user IDs,
-- moderator IDs, moderation reasons, and unapproved reviews.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.v_station_approved_reviews
WITH (security_invoker = true)
AS
SELECT 
    r.id,
    r.station_id,
    r.rating,
    r.comment,
    public.get_author_display_name(r.user_id) AS author_display_name,
    r.created_at
FROM public.reviews r
WHERE r.moderation_status = 'approved';

COMMENT ON VIEW public.v_station_approved_reviews IS
  'Step 1.8: Sanitized public feed of approved customer reviews without internal moderation fields or user UUIDs.';

REVOKE ALL ON public.v_station_approved_reviews FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.v_station_approved_reviews FROM anon, authenticated;
GRANT SELECT ON public.v_station_approved_reviews TO anon, authenticated, service_role;

-- ============================================================================
-- PART 3: GEOSPATIAL SEARCH / DISCOVERY FUNCTION
-- ============================================================================

-- Function: nearby_stations
-- Efficient geospatial search using PostGIS ST_DWithin and GIST spatial index
-- on public.stations(geom). Bounded inputs, sorted by distance ASC.
CREATE OR REPLACE FUNCTION public.nearby_stations(
    user_lat double precision,
    user_lng double precision,
    radius_meters double precision DEFAULT 50000,
    max_results integer DEFAULT 50
)
RETURNS TABLE (
    id uuid,
    slug text,
    name text,
    operator_name text,
    operator_slug text,
    address_line text,
    locality text,
    city text,
    latitude double precision,
    longitude double precision,
    distance_meters double precision,
    operational_status text,
    is_24_hours boolean,
    opening_time time,
    closing_time time,
    total_plugs integer,
    max_power_kw numeric,
    min_price_per_kwh numeric,
    connector_types text[],
    latest_availability_status text,
    latest_observed_at timestamptz,
    minutes_since_observation integer,
    avg_rating numeric,
    review_count bigint
)
LANGUAGE sql
STABLE
PARALLEL SAFE
SECURITY INVOKER
SET search_path = public, extensions, pg_temp
AS $$
  SELECT 
      v.id,
      v.slug,
      v.name,
      v.operator_name,
      v.operator_slug,
      v.address_line,
      v.locality,
      v.city,
      v.latitude,
      v.longitude,
      round(ST_Distance(v.geom, ST_SetSRID(ST_MakePoint(user_lng, user_lat), 4326)::geography))::double precision AS distance_meters,
      v.operational_status,
      v.is_24_hours,
      v.opening_time,
      v.closing_time,
      v.total_plugs,
      v.max_power_kw,
      v.min_price_per_kwh,
      v.connector_types,
      v.latest_availability_status,
      v.latest_observed_at,
      v.minutes_since_observation,
      v.avg_rating,
      v.review_count
  FROM public.v_station_current_state v
  WHERE user_lat BETWEEN -90.0 AND 90.0
    AND user_lng BETWEEN -180.0 AND 180.0
    AND radius_meters > 0
    AND ST_DWithin(v.geom, ST_SetSRID(ST_MakePoint(user_lng, user_lat), 4326)::geography, LEAST(radius_meters, 200000.0))
  ORDER BY distance_meters ASC
  LIMIT LEAST(GREATEST(max_results, 1), 100);
$$;

COMMENT ON FUNCTION public.nearby_stations(double precision, double precision, double precision, integer) IS
  'Step 1.8: PostGIS spatial radius search returning nearest public stations with composed current state.';

REVOKE ALL ON FUNCTION public.nearby_stations(double precision, double precision, double precision, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.nearby_stations(double precision, double precision, double precision, integer) TO anon, authenticated, service_role;

-- ============================================================================
-- PART 4: ANALYTICS WAREHOUSE VIEW (OLAP)
-- ============================================================================

-- Daily station activity and performance summary view joining dimensional model.
-- Strictly for internal reporting, Python ETL validation, and BI tools.
CREATE OR REPLACE VIEW analytics.v_station_daily_summary
WITH (security_invoker = true)
AS
SELECT 
    d.full_date,
    d.year,
    d.month,
    d.day_name,
    d.is_weekend,
    ds.station_key,
    ds.station_id AS operational_station_id,
    ds.station_name,
    dop.operator_name,
    ds.latitude,
    ds.longitude,
    f.observation_count,
    f.available_count,
    f.busy_count,
    f.broken_count,
    f.availability_ratio,
    f.busy_ratio,
    f.broken_ratio,
    f.avg_queue_score,
    f.peak_queue_score,
    f.report_count,
    f.review_count,
    f.avg_rating,
    f.data_completeness_score,
    f.source_count,
    f.maturity,
    f.has_evidence
FROM analytics.fact_station_daily f
JOIN analytics.dim_date d ON f.date_key = d.date_key
JOIN analytics.dim_station ds ON f.station_key = ds.station_key
JOIN analytics.dim_operator dop ON ds.operator_key = dop.operator_key;

COMMENT ON VIEW analytics.v_station_daily_summary IS
  'Step 1.8: OLAP star-schema reporting view joining fact_station_daily with conformed dimensions for analytics consumers.';

-- No client grants for analytics view (internal warehouse only)
REVOKE ALL ON analytics.v_station_daily_summary FROM PUBLIC;
REVOKE ALL ON analytics.v_station_daily_summary FROM anon, authenticated;
GRANT SELECT ON analytics.v_station_daily_summary TO service_role;

-- ============================================================================
-- PART 5: SELF-VERIFYING ASSERTION BLOCK
-- ============================================================================

DO $$
DECLARE
    v_views_count integer;
    v_funcs_count integer;
    v_rls_count integer;
    v_public_policies integer;
    v_analytics_policies integer;
    v_ml_policies integer;
    v_cross_fks integer;
    v_legacy_count integer;
    v_date_count integer;
    v_time_count integer;
    v_stations_count integer;
    v_test_current_state_count integer;
    v_test_connectors_count integer;
    v_test_reviews_count integer;
    v_test_nearby_count integer;
    v_test_analytics_count integer;
BEGIN
    -- 1. Verify exact 4 views created
    SELECT count(*) INTO v_views_count
    FROM information_schema.views
    WHERE (table_schema = 'public' AND table_name IN ('v_station_current_state', 'v_station_connectors', 'v_station_approved_reviews'))
       OR (table_schema = 'analytics' AND table_name = 'v_station_daily_summary');
    IF v_views_count != 4 THEN
        RAISE EXCEPTION 'Assertion failed: expected exactly 4 views, found %', v_views_count;
    END IF;

    -- 2. Verify exact 2 functions created
    SELECT count(*) INTO v_funcs_count
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
      AND p.proname IN ('get_author_display_name', 'nearby_stations');
    IF v_funcs_count != 2 THEN
        RAISE EXCEPTION 'Assertion failed: expected 2 functions, found %', v_funcs_count;
    END IF;

    -- 3. Verify RLS remains enabled on all 29 active tables
    SELECT count(*) INTO v_rls_count
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('public', 'analytics', 'ml')
      AND c.relkind = 'r'
      AND c.relrowsecurity = true;
    IF v_rls_count != 29 THEN
        RAISE EXCEPTION 'Assertion failed: expected 29 tables with RLS enabled, found %', v_rls_count;
    END IF;

    -- 4. Verify public policies count remains exactly 29
    SELECT count(*) INTO v_public_policies
    FROM pg_policies
    WHERE schemaname = 'public';
    IF v_public_policies != 29 THEN
        RAISE EXCEPTION 'Assertion failed: expected exactly 29 public policies, found %', v_public_policies;
    END IF;

    -- 5. Verify 0 client policies on analytics and ml
    SELECT count(*) INTO v_analytics_policies
    FROM pg_policy pol
    JOIN pg_class c ON pol.polrelid = c.oid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'analytics';
    IF v_analytics_policies != 0 THEN
        RAISE EXCEPTION 'Assertion failed: expected 0 analytics policies, found %', v_analytics_policies;
    END IF;

    SELECT count(*) INTO v_ml_policies
    FROM pg_policy pol
    JOIN pg_class c ON pol.polrelid = c.oid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'ml';
    IF v_ml_policies != 0 THEN
        RAISE EXCEPTION 'Assertion failed: expected 0 ml policies, found %', v_ml_policies;
    END IF;

    -- 6. Verify ZERO cross-layer foreign keys
    SELECT count(*) INTO v_cross_fks
    FROM pg_constraint c
    JOIN pg_class child_cls ON c.conrelid = child_cls.oid
    JOIN pg_namespace child_ns ON child_cls.relnamespace = child_ns.oid
    JOIN pg_class parent_cls ON c.confrelid = parent_cls.oid
    JOIN pg_namespace parent_ns ON parent_cls.relnamespace = parent_ns.oid
    WHERE c.contype = 'f'
      AND child_ns.nspname IN ('public', 'analytics', 'ml')
      AND parent_ns.nspname IN ('public', 'analytics', 'ml')
      AND child_ns.nspname <> parent_ns.nspname;
    IF v_cross_fks != 0 THEN
        RAISE EXCEPTION 'Assertion failed: expected 0 cross-layer FKs, found %', v_cross_fks;
    END IF;

    -- 7. Verify all 9 legacy tables remain untouched and empty
    SELECT (
        (SELECT count(*) FROM public.dim_date) +
        (SELECT count(*) FROM public.dim_location) +
        (SELECT count(*) FROM public.dim_station) +
        (SELECT count(*) FROM public.dim_tariff) +
        (SELECT count(*) FROM public.dim_time) +
        (SELECT count(*) FROM public.dim_vehicle) +
        (SELECT count(*) FROM public.dim_weather) +
        (SELECT count(*) FROM public.fact_charging_session) +
        (SELECT count(*) FROM public.fact_station_daily_agg)
    ) INTO v_legacy_count;
    IF v_legacy_count != 0 THEN
        RAISE EXCEPTION 'Assertion failed: legacy public tables modified, row count = %', v_legacy_count;
    END IF;

    -- 8. Verify reference data row counts
    SELECT count(*) INTO v_date_count FROM analytics.dim_date;
    IF v_date_count != 3288 THEN
        RAISE EXCEPTION 'Assertion failed: analytics.dim_date expected 3288 rows, found %', v_date_count;
    END IF;

    SELECT count(*) INTO v_time_count FROM analytics.dim_time;
    IF v_time_count != 96 THEN
        RAISE EXCEPTION 'Assertion failed: analytics.dim_time expected 96 rows, found %', v_time_count;
    END IF;

    -- 9. Verify operational station count is 0
    SELECT count(*) INTO v_stations_count FROM public.stations;
    IF v_stations_count != 0 THEN
        RAISE EXCEPTION 'Assertion failed: unexpected stations found in public.stations, count = %', v_stations_count;
    END IF;

    -- 10. Verify all views and functions execute cleanly against current empty state
    SELECT count(*) INTO v_test_current_state_count FROM public.v_station_current_state;
    SELECT count(*) INTO v_test_connectors_count FROM public.v_station_connectors;
    SELECT count(*) INTO v_test_reviews_count FROM public.v_station_approved_reviews;
    SELECT count(*) INTO v_test_nearby_count FROM public.nearby_stations(19.0760, 72.8777, 10000, 10);
    SELECT count(*) INTO v_test_analytics_count FROM analytics.v_station_daily_summary;

    RAISE NOTICE 'Step 1.8 migration verified successfully: 4 views, 2 functions, 29 RLS tables, 29 public policies, 0 cross-layer FKs, 9 legacy empty tables intact.';
END $$;
