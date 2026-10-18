-- Demo provenance migration (additive, not applied remotely)
ALTER TABLE public.stations ADD COLUMN IF NOT EXISTS is_simulated boolean NOT NULL DEFAULT false;
ALTER TABLE public.connectors ADD COLUMN IF NOT EXISTS is_simulated boolean NOT NULL DEFAULT false;
ALTER TABLE public.station_observations ADD COLUMN IF NOT EXISTS is_simulated boolean NOT NULL DEFAULT false;
ALTER TABLE public.station_source_link ADD COLUMN IF NOT EXISTS is_simulated boolean NOT NULL DEFAULT false;
ALTER TABLE public.operators ADD COLUMN IF NOT EXISTS is_simulated boolean NOT NULL DEFAULT false;
ALTER TABLE public.ingestion_runs ADD COLUMN IF NOT EXISTS is_simulated boolean NOT NULL DEFAULT false;

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
        obs.observed_at AS latest_observed_at,
        obs.is_simulated AS observation_is_simulated
    FROM public.station_observations obs
    WHERE obs.observed_at <= now()
    ORDER BY obs.station_id, obs.is_simulated ASC, (obs.connector_id IS NULL) DESC, obs.observed_at DESC, obs.received_at DESC, obs.id DESC
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
    coalesce(cs.total_connector_types, 0)::integer AS total_connector_types,
    coalesce(cs.total_plugs, 0)::integer AS total_plugs,
    cs.max_power_kw,
    cs.min_price_per_kwh,
    coalesce(cs.connector_types, ARRAY[]::text[]) AS connector_types,
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
    rs.avg_rating,
    coalesce(rs.review_count, 0)::bigint AS review_count,
    s.is_simulated,
    lo.observation_is_simulated
FROM public.stations s
JOIN public.operators o ON s.operator_id = o.id
LEFT JOIN conn_summary cs ON cs.station_id = s.id
LEFT JOIN rev_summary rs ON rs.station_id = s.id
LEFT JOIN latest_obs lo ON lo.station_id = s.id;

COMMENT ON VIEW public.v_station_current_state IS
  'Canonical public view with demo provenance (is_simulated) and live observation priority.';

CREATE OR REPLACE VIEW public.v_station_connectors
WITH (security_invoker = true)
AS
WITH latest_conn_obs AS (
    SELECT DISTINCT ON (obs.connector_id)
        obs.connector_id,
        obs.availability_status AS latest_availability_status,
        obs.available_connectors AS latest_available_connectors,
        obs.observed_at AS latest_observed_at,
        obs.is_simulated AS observation_is_simulated
    FROM public.station_observations obs
    WHERE obs.connector_id IS NOT NULL
      AND obs.observed_at <= now()
    ORDER BY obs.connector_id, obs.is_simulated ASC, obs.observed_at DESC, obs.received_at DESC, obs.id DESC
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
    END AS minutes_since_observation,
    c.price_estimate_per_kwh,
    c.price_estimate_raw,
    c.price_estimate_source,
    c.is_simulated,
    lco.observation_is_simulated
FROM public.connectors c
LEFT JOIN latest_conn_obs lco ON lco.connector_id = c.id;

COMMENT ON VIEW public.v_station_connectors IS
  'Connector specs, availability, pricing, and demo provenance with live observation priority.';
