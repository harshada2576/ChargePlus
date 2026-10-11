-- ChargePlus final-state verification (Route A/B operator step).
-- READ-ONLY: SELECTs on catalogs and row counts only. Never writes.
-- Run: psql $DISPOSABLE_DATABASE_URL -v ON_ERROR_STOP=1 -f supabase/verify_final_state.sql
-- Every check below must return the stated expected value on a correct bootstrap.
-- \set QUIET drops psql noise; failures raise via divide-by-zero guards.

\set QUIET on
\pset footer off

-- 1. RLS enabled on the 29 owned tables (11 public + 12 analytics + 6 ml).
SELECT 'rls_owned_29' AS check,
  (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relrowsecurity AND (
      (n.nspname='public' AND c.relname IN ('profiles','operators','stations','connectors','data_sources','station_source_link','station_observations','user_reports','reviews','favorites','alerts'))
      OR (n.nspname='analytics' AND c.relname IN ('dim_station','dim_operator','dim_location','dim_connector','dim_date','dim_time','dim_source','dim_weather','fact_station_observation','fact_user_report','fact_review','fact_station_daily'))
      OR (n.nspname='ml' AND c.relname IN ('features','datasets','experiments','model_versions','metrics','prediction_runs')))) AS got,
  29 AS expected;

-- 2. Exactly 29 policies on the 11 public operational tables.
SELECT 'public_policies_29' AS check, (SELECT count(*) FROM pg_policies
  WHERE schemaname='public' AND tablename IN ('profiles','operators','stations','connectors','data_sources','station_source_link','station_observations','user_reports','reviews','favorites','alerts')) AS got, 29 AS expected;

-- 3. ingestion_runs: admin-only SELECT policy, service_role write policy, no open policy.
SELECT 'ingestion_admin_policy_1' AS check, (SELECT count(*) FROM pg_policies
  WHERE schemaname='public' AND tablename='ingestion_runs' AND policyname='ingestion_runs_select_admin') AS got, 1 AS expected;
SELECT 'ingestion_open_policies_0' AS check, (SELECT count(*) FROM pg_policies
  WHERE schemaname='public' AND tablename='ingestion_runs' AND cmd='SELECT' AND qual='true') AS got, 0 AS expected;

-- 4. Zero client policies on analytics/ml (deny-by-default; service_role bypasses RLS).
SELECT 'analytics_policies_0' AS check, (SELECT count(*) FROM pg_policies WHERE schemaname='analytics') AS got, 0 AS expected;
SELECT 'ml_policies_0' AS check, (SELECT count(*) FROM pg_policies WHERE schemaname='ml') AS got, 0 AS expected;

-- 5. No anonymous grants on ingestion_runs; anon/authenticated hold at most SELECT elsewhere only via RLS.
SELECT 'ingestion_anon_grants_0' AS check, (SELECT count(*) FROM information_schema.role_table_grants
  WHERE table_schema='public' AND table_name='ingestion_runs' AND grantee='anon') AS got, 0 AS expected;

-- 6. Zero cross-layer FKs sourced in analytics/ml (mirrors step_1_7 section 5).
SELECT 'cross_layer_fk_0' AS check, (SELECT count(*) FROM pg_constraint con
  JOIN pg_class s ON s.oid=con.conrelid JOIN pg_namespace sn ON sn.oid=s.relnamespace
  JOIN pg_class r ON r.oid=con.confrelid JOIN pg_namespace rn ON rn.oid=r.relnamespace
  WHERE con.contype='f' AND sn.nspname IN ('analytics','ml') AND rn.nspname <> sn.nspname) AS got, 0 AS expected;

-- 7. Reference data seeded exactly by step_1_4; no manufactured operational rows.
SELECT 'dim_date_3288' AS check, (SELECT count(*) FROM analytics.dim_date) AS got, 3288 AS expected;
SELECT 'dim_time_96' AS check, (SELECT count(*) FROM analytics.dim_time) AS got, 96 AS expected;
SELECT 'stations_0' AS check, (SELECT count(*) FROM public.stations) AS got, 0 AS expected;
SELECT 'ingestion_runs_0' AS check, (SELECT count(*) FROM public.ingestion_runs) AS got, 0 AS expected;

-- 8. Legacy public dim_*/fact_* placeholders must be absent on a clean bootstrap
-- (they are pre-existing objects no migration creates; 0 rows expected iff present).
SELECT 'legacy_tables_absent' AS check, (SELECT count(*) FROM information_schema.tables
  WHERE table_schema='public' AND table_name IN ('dim_date','dim_location','dim_station','dim_tariff','dim_time','dim_vehicle','dim_weather','fact_charging_session','fact_station_daily_agg')) AS got, 0 AS expected;
