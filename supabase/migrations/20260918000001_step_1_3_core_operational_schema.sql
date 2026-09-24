-- ChargePlus Step 1.3 — Core operational schema
-- Phase 1/6 Step 1.3/10
--
-- SCOPE: creates 11 operational tables only:
--   public.profiles, public.operators, public.stations, public.connectors,
--   public.data_sources, public.station_source_link, public.station_observations,
--   public.user_reports, public.reviews, public.favorites, public.alerts
--
-- NON-NEGOTIABLE SAFETY:
--   Existing warehouse tables are NOT touched by this file:
--   dim_date, dim_location, dim_station, dim_tariff, dim_time, dim_vehicle,
--   dim_weather, fact_charging_session, fact_station_daily_agg.
--   This file contains NO DROP, NO TRUNCATE, NO ALTER of any existing table.
--   It contains no SEED/INSERT of station, availability, price, review,
--   observation, or ML data (no synthetic production data).
--
-- GEOGRAPHY DECISION (documented per spec):
--   Spec allows a GENERATED STORED geography column only if verified safe.
--   Docker daemon was unavailable in this environment, so the generated
--   expression could NOT be verified locally before touching Supabase.
--   Per spec fallback, this migration uses a normal
--   geography(Point,4326) column + BEFORE trigger (public.set_stations_geom)
--   to maintain geom from (longitude, latitude). No unsafe workaround.
--   geom is NOT NULL; the BEFORE trigger populates it before the
--   NOT NULL check on every INSERT / latitude-longitude UPDATE.
--
-- DELETION RULES (history preservation):
--   Stations are historical physical locations. Closure = operational_status
--   'permanently_closed', never hard DELETE while children exist.
--   RESTRICT: stations.operator_id, connectors.station_id,
--     station_source_link.(station_id, source_id),
--     station_observations.(station_id, connector_id, source_id),
--     user_reports.(station_id, connector_id), reviews.station_id.
--   CASCADE (user-owned pointers/content follow account deletion, GDPR):
--     profiles.id -> auth.users(id) CASCADE;
--     user_reports.user_id, reviews.user_id, favorites.user_id,
--     alerts.user_id CASCADE on profile delete;
--     favorites.station_id, alerts.station_id CASCADE (pure pointers;
--     station deletes are already blocked by RESTRICT elsewhere).
--   moderated_by has NO FK on purpose: moderation audit survives
--   moderator account deletion.
--
-- RLS: intentionally no RLS/policies in Step 1.3 (Step 1.7 owns RLS).
-- updated_at: application-maintained in Step 1.3 (no auto triggers except
--   geom maintenance); a centralized updated_at trigger may follow in 1.6/1.7.
--
-- IDEMPOTENCY: safe to re-run (IF NOT EXISTS guards + OR REPLACE function).
-- Under Supabase CLI this file runs once via supabase_migrations history.

-- Extensions (no-ops if already enabled on Supabase).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- 1. public.profiles — one row per Supabase Auth user
-- ============================================================
CREATE TABLE IF NOT EXISTS public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
  display_name TEXT NULL CHECK (display_name IS NULL OR char_length(display_name) BETWEEN 1 AND 120),
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  preferred_language TEXT NOT NULL DEFAULT 'en' CHECK (preferred_language IN ('en', 'hi', 'mr')),
  home_city TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.profiles IS 'Step 1.3: one profile per auth.users row; auth is source of truth, no passwords/OTPs stored here.';

-- ============================================================
-- 2. public.operators — canonical charging-network identity
-- ============================================================
CREATE TABLE IF NOT EXISTS public.operators (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
  slug TEXT UNIQUE CHECK (slug IS NULL OR char_length(slug) BETWEEN 1 AND 200),
  website_url TEXT NULL,
  support_phone TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.operators IS 'Step 1.3: canonical CPO registry; stations.operator_id FKs here, never free text.';

-- ============================================================
-- 3. public.stations — one row = one physical charging location
-- ============================================================
CREATE TABLE IF NOT EXISTS public.stations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE,
  name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 300),
  operator_id UUID NOT NULL REFERENCES public.operators (id) ON DELETE RESTRICT,
  address_line TEXT NULL,
  locality TEXT NULL,
  city TEXT NOT NULL DEFAULT 'Mumbai' CHECK (char_length(city) BETWEEN 1 AND 120),
  state TEXT NOT NULL DEFAULT 'Maharashtra' CHECK (char_length(state) BETWEEN 1 AND 120),
  postal_code TEXT NULL CHECK (postal_code IS NULL OR postal_code ~ '^[1-9][0-9]{5}$'),
  country TEXT NOT NULL DEFAULT 'India' CHECK (char_length(country) BETWEEN 1 AND 120),
  latitude DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
  longitude DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
  geom geography(Point, 4326) NOT NULL,
  opening_time TIME NULL,
  closing_time TIME NULL,
  is_24_hours BOOLEAN NOT NULL DEFAULT FALSE,
  access_type TEXT NULL,
  is_public BOOLEAN NOT NULL DEFAULT TRUE,
  operational_status TEXT NOT NULL DEFAULT 'unknown'
    CHECK (operational_status IN ('unknown', 'operational', 'temporarily_unavailable', 'permanently_closed')),
  phone TEXT NULL,
  website_url TEXT NULL,
  last_verified_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_stations_hours CHECK (
    (is_24_hours AND opening_time IS NULL AND closing_time IS NULL)
    OR (NOT is_24_hours AND opening_time IS NULL AND closing_time IS NULL)
    OR (NOT is_24_hours AND opening_time IS NOT NULL AND closing_time IS NOT NULL)
  )
);
COMMENT ON TABLE public.stations IS 'Step 1.3: canonical physical locations; live availability, ratings, predictions are derived elsewhere, never stored here.';
COMMENT ON COLUMN public.stations.geom IS 'Maintained by trg_stations_geom from (longitude, latitude); query with ST_DWithin.';
COMMENT ON COLUMN public.stations.postal_code IS 'TEXT to preserve leading zeros; CHECK enforces Indian 6-digit format when present, NULL when unknown.';

-- Trigger: maintain geom from longitude/latitude (see header decision note).
CREATE OR REPLACE FUNCTION public.set_stations_geom()
RETURNS trigger
LANGUAGE plpgsql
AS $func$
BEGIN
  NEW.geom := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326)::geography;
  RETURN NEW;
END;
$func$;

DROP TRIGGER IF EXISTS trg_stations_geom ON public.stations;
CREATE TRIGGER trg_stations_geom
  BEFORE INSERT OR UPDATE OF latitude, longitude ON public.stations
  FOR EACH ROW EXECUTE FUNCTION public.set_stations_geom();

-- ============================================================
-- 4. public.connectors — STATIC capacity groups (no live state)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.connectors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id UUID NOT NULL REFERENCES public.stations (id) ON DELETE RESTRICT,
  connector_type TEXT NOT NULL
    CHECK (connector_type IN ('CCS2', 'CHAdeMO', 'Type 2', 'Type 1', 'GB/T', 'Bharat AC001', 'Bharat DC001')),
  charging_standard TEXT NULL,
  power_kw NUMERIC(8, 2) NOT NULL CHECK (power_kw > 0),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  pricing_type TEXT NULL,
  price_per_kwh NUMERIC(10, 2) NULL CHECK (price_per_kwh IS NULL OR price_per_kwh >= 0),
  price_per_session NUMERIC(10, 2) NULL CHECK (price_per_session IS NULL OR price_per_session >= 0),
  currency TEXT NOT NULL DEFAULT 'INR' CHECK (char_length(currency) BETWEEN 1 AND 10),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.connectors IS 'Step 1.3: static capacity groups per station; live availability lives in station_observations only.';

-- ============================================================
-- 5. public.data_sources — external feed registry (no seed rows)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.data_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE CHECK (char_length(name) BETWEEN 1 AND 120),
  source_type TEXT NOT NULL CHECK (char_length(source_type) BETWEEN 1 AND 120),
  base_url TEXT NULL,
  source_priority INTEGER NOT NULL DEFAULT 100,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.data_sources IS 'Step 1.3: feed registry; source_priority reserved for future conflict resolution. No seed rows in this step.';

-- ============================================================
-- 6. public.station_source_link — canonical <-> source identity map
-- ============================================================
CREATE TABLE IF NOT EXISTS public.station_source_link (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id UUID NOT NULL REFERENCES public.stations (id) ON DELETE RESTRICT,
  source_id UUID NOT NULL REFERENCES public.data_sources (id) ON DELETE RESTRICT,
  source_station_id TEXT NOT NULL CHECK (char_length(source_station_id) BETWEEN 1 AND 500),
  source_url TEXT NULL,
  first_seen_at TIMESTAMPTZ NULL,
  last_seen_at TIMESTAMPTZ NULL,
  last_ingested_at TIMESTAMPTZ NULL,
  source_payload_hash TEXT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_station_source_link_source_record UNIQUE (source_id, source_station_id)
);
COMMENT ON TABLE public.station_source_link IS 'Step 1.3: provenance map; source IDs are internal only, never canonical frontend IDs.';

-- ============================================================
-- 7. public.station_observations — append-only system/source history
-- ============================================================
CREATE TABLE IF NOT EXISTS public.station_observations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id UUID NOT NULL REFERENCES public.stations (id) ON DELETE RESTRICT,
  connector_id UUID NULL REFERENCES public.connectors (id) ON DELETE RESTRICT,
  source_id UUID NOT NULL REFERENCES public.data_sources (id) ON DELETE RESTRICT,
  availability_status TEXT NOT NULL CHECK (availability_status IN ('available', 'busy', 'broken', 'unknown')),
  queue_level TEXT NOT NULL CHECK (queue_level IN ('none', 'short', 'medium', 'long', 'unknown')),
  available_connectors INTEGER NULL CHECK (available_connectors IS NULL OR available_connectors >= 0),
  total_connectors INTEGER NOT NULL CHECK (total_connectors >= 0),
  observed_at TIMESTAMPTZ NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  confidence_score NUMERIC(5, 4) NULL CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)),
  source_payload_hash TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_station_observations_counts CHECK (
    available_connectors IS NULL OR available_connectors <= total_connectors
  )
);
COMMENT ON TABLE public.station_observations IS 'Step 1.3: append-only system/source observations; conceptual no-UPDATE, no frontend writes; feeds future observation facts.';

-- ============================================================
-- 8. public.user_reports — append-only authenticated community reports
-- ============================================================
CREATE TABLE IF NOT EXISTS public.user_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
  station_id UUID NOT NULL REFERENCES public.stations (id) ON DELETE RESTRICT,
  connector_id UUID NULL REFERENCES public.connectors (id) ON DELETE RESTRICT,
  availability_status TEXT NOT NULL CHECK (availability_status IN ('available', 'busy', 'broken', 'unknown')),
  queue_level TEXT NOT NULL CHECK (queue_level IN ('none', 'short', 'medium', 'long', 'unknown')),
  comment TEXT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_flagged BOOLEAN NOT NULL DEFAULT FALSE,
  moderation_status TEXT NOT NULL DEFAULT 'pending' CHECK (moderation_status IN ('pending', 'approved', 'rejected')),
  moderated_by UUID NULL,
  moderated_at TIMESTAMPTZ NULL,
  moderation_reason TEXT NULL
);
COMMENT ON TABLE public.user_reports IS 'Step 1.3: community observations; never overwrites stations/connectors; moderated_by has no FK so audit survives moderator deletion.';

-- ============================================================
-- 9. public.reviews — experience feedback (NOT availability labels)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
  station_id UUID NOT NULL REFERENCES public.stations (id) ON DELETE RESTRICT,
  rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment TEXT NULL,
  is_flagged BOOLEAN NOT NULL DEFAULT FALSE,
  moderation_status TEXT NOT NULL DEFAULT 'pending' CHECK (moderation_status IN ('pending', 'approved', 'rejected')),
  moderated_by UUID NULL,
  moderated_at TIMESTAMPTZ NULL,
  moderation_reason TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_reviews_user_station UNIQUE (user_id, station_id)
);
COMMENT ON TABLE public.reviews IS 'Step 1.3: one review per user per station; experience feedback, never an availability/ML label.';

-- ============================================================
-- 10. public.favorites — saved stations join
-- ============================================================
CREATE TABLE IF NOT EXISTS public.favorites (
  user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
  station_id UUID NOT NULL REFERENCES public.stations (id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT pk_favorites PRIMARY KEY (user_id, station_id)
);
COMMENT ON TABLE public.favorites IS 'Step 1.3: saved-stations join; composite PK prevents duplicates.';

-- ============================================================
-- 11. public.alerts — user watch conditions (no delivery log yet)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
  station_id UUID NULL REFERENCES public.stations (id) ON DELETE CASCADE,
  alert_type TEXT NOT NULL
    CHECK (alert_type IN ('station_available', 'station_status_change', 'congestion_threshold', 'nearby_station_change')),
  params JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(params) = 'object'),
  threshold_value NUMERIC NULL,
  is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  last_triggered_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.alerts IS 'Step 1.3: watch conditions; station_id NULL = nearby/watchlist alert; params holds radius_km/connector_type etc.; notification_events deferred.';
COMMENT ON COLUMN public.alerts.params IS 'Must remain a JSON object; alert-type-specific keys documented in Phase 3.';

-- ============================================================
-- INDEXES — Step 1.3 query patterns only (no speculative ML/OLAP)
-- ============================================================
-- stations
CREATE INDEX IF NOT EXISTS idx_stations_geom ON public.stations USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_stations_city ON public.stations (city);
CREATE INDEX IF NOT EXISTS idx_stations_operator ON public.stations (operator_id);
CREATE INDEX IF NOT EXISTS idx_stations_slug ON public.stations (slug);

-- connectors
CREATE INDEX IF NOT EXISTS idx_connectors_station ON public.connectors (station_id);

-- station_source_link
CREATE INDEX IF NOT EXISTS idx_station_source_link_station ON public.station_source_link (station_id);
CREATE INDEX IF NOT EXISTS idx_station_source_link_source ON public.station_source_link (source_id);
-- uniqueness of (source_id, source_station_id) is enforced by uq constraint above

-- station_observations
CREATE INDEX IF NOT EXISTS idx_station_observations_station_time ON public.station_observations (station_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_station_observations_connector_time ON public.station_observations (connector_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_station_observations_source_time ON public.station_observations (source_id, observed_at DESC);

-- user_reports
CREATE INDEX IF NOT EXISTS idx_user_reports_station_time ON public.user_reports (station_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_reports_user_time ON public.user_reports (user_id, created_at DESC);

-- reviews
CREATE INDEX IF NOT EXISTS idx_reviews_station ON public.reviews (station_id);
CREATE INDEX IF NOT EXISTS idx_reviews_user ON public.reviews (user_id);

-- favorites
CREATE INDEX IF NOT EXISTS idx_favorites_station ON public.favorites (station_id);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON public.favorites (user_id);

-- alerts
CREATE INDEX IF NOT EXISTS idx_alerts_user ON public.alerts (user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_station ON public.alerts (station_id);
