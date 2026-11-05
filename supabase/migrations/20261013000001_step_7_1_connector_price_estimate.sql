-- ============================================================================
-- CHARGEPLUS — STEP 7.1: SEPARATE UNVERIFIED CONNECTOR PRICE ESTIMATES
--
-- Additive OLTP-only estimate path. These fields MUST NOT be treated as verified
-- tariffs and are intentionally NOT mirrored into analytics.dim_connector.
-- This migration is authored for review; it has NOT been executed.
-- ============================================================================

ALTER TABLE public.connectors
    ADD COLUMN IF NOT EXISTS price_estimate_per_kwh NUMERIC(10, 2)
        CHECK (price_estimate_per_kwh IS NULL OR (price_estimate_per_kwh > 0 AND price_estimate_per_kwh <= 500)),
    ADD COLUMN IF NOT EXISTS price_estimate_raw TEXT
        CHECK (price_estimate_raw IS NULL OR char_length(price_estimate_raw) <= 500),
    ADD COLUMN IF NOT EXISTS price_estimate_source TEXT
        CHECK (price_estimate_source IS NULL OR price_estimate_source IN ('ocm_usage_cost'));

COMMENT ON COLUMN public.connectors.price_estimate_per_kwh IS
    'Unverified INR/kWh estimate parsed conservatively from source free text; never a verified tariff.';
COMMENT ON COLUMN public.connectors.price_estimate_raw IS
    'Original source pricing text supporting the unverified estimate; maximum 500 characters.';
COMMENT ON COLUMN public.connectors.price_estimate_source IS
    'Provenance for unverified estimate; currently ocm_usage_cost only.';

-- CREATE OR REPLACE may append view columns but must not reorder existing ones.
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
    END AS minutes_since_observation,
    c.price_estimate_per_kwh,
    c.price_estimate_raw,
    c.price_estimate_source
FROM public.connectors c
LEFT JOIN latest_conn_obs lco ON lco.connector_id = c.id;

COMMENT ON VIEW public.v_station_connectors IS
    'Connector specifications, connector-level availability, verified pricing, and separately labeled unverified estimates.';

REVOKE ALL ON public.v_station_connectors FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.v_station_connectors FROM anon, authenticated;
GRANT SELECT ON public.v_station_connectors TO anon, authenticated, service_role;
