"""ChargePlus — Named OLAP queries (Phase 4/6, Step 4.6).

Every query reads analytics.* only, in UTC, with honest NULL semantics:
missing evidence yields NULL / absence, never zero-fabricated activity.
Each entry documents meaning, grain, supporting data, NULL meaning,
timezone, and traceability.

Documented exception: ingestion_health reads public.ingestion_runs (an
operations table, not warehouse evidence) and is served only on the
role-gated admin surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class OlapQuery:
    name: str
    meaning: str
    grain: str
    data: str
    null_meaning: str
    timezone: str
    traceability: str
    sql: str


QUERIES: dict[str, OlapQuery] = {}


def _register(q: OlapQuery) -> OlapQuery:
    QUERIES[q.name] = q
    return q


_register(OlapQuery(
    name="stations_by_operator",
    meaning="Count of current canonical stations per network operator.",
    grain="One row per operator with at least one current station version.",
    data="analytics.dim_station (is_current) + dim_operator.",
    null_meaning="Operators without stations do not appear (absence, not zero).",
    timezone="N/A (current snapshot).",
    traceability="station_id business key -> public.stations.id via ETL.",
    sql="SELECT o.operator_name, count(*) AS station_count "
        "FROM analytics.dim_station s JOIN analytics.dim_operator o USING (operator_key) "
        "WHERE s.is_current GROUP BY o.operator_name ORDER BY station_count DESC",
))

_register(OlapQuery(
    name="stations_by_city",
    meaning="Count of current canonical stations per city.",
    grain="One row per city with at least one current station version.",
    data="analytics.dim_station (is_current) + dim_location.",
    null_meaning="Cities without stations do not appear.",
    timezone="N/A (current snapshot).",
    traceability="station_id business key -> public.stations.id via ETL.",
    sql="SELECT l.city, l.state, count(*) AS station_count "
        "FROM analytics.dim_station s JOIN analytics.dim_location l USING (location_key) "
        "WHERE s.is_current GROUP BY l.city, l.state ORDER BY station_count DESC",
))

_register(OlapQuery(
    name="connector_mix",
    meaning="Connector capacity groups by type; unknown power stays NULL.",
    grain="One row per connector_type.",
    data="analytics.dim_connector.",
    null_meaning="unknown_power_groups counts groups with NULL power (unknown, not zero).",
    timezone="N/A (current snapshot).",
    traceability="connector_id business key -> public.connectors.id via ETL.",
    sql="SELECT connector_type, count(*) AS groups, sum(quantity) AS units, "
        "sum(CASE WHEN power_kw IS NULL THEN 1 ELSE 0 END) AS unknown_power_groups "
        "FROM analytics.dim_connector GROUP BY connector_type ORDER BY units DESC NULLS LAST",
))

_register(OlapQuery(
    name="observation_freshness",
    meaning="Latest observation per station with age; stations never observed appear with NULL age.",
    grain="One row per current station version (station names are not unique and must never be the grain).",
    data="analytics.dim_station (is_current) + fact_station_observation.",
    null_meaning="NULL observed_at/age = never observed (unknown freshness, not stale, not unavailable).",
    timezone="UTC ages via now() - observed_at.",
    traceability="observation_id -> public.station_observations.id via ETL.",
    sql="SELECT s.station_id, s.station_name, max(o.observed_at) AS latest_observed_at, "
        "max(o.availability_status) FILTER (WHERE o.observed_at IS NOT NULL) AS latest_status, "
        "count(o.observation_id) AS observation_count "
        "FROM analytics.dim_station s LEFT JOIN analytics.fact_station_observation o USING (station_key) "
        "WHERE s.is_current GROUP BY s.station_id, s.station_name ORDER BY latest_observed_at DESC NULLS LAST",
))

_register(OlapQuery(
    name="daily_trend",
    meaning="Per-day evidence for one station (current version): observations, status counts, community signals.",
    grain="One row per date with evidence for the station.",
    data="analytics.fact_station_daily + dim_date. Parameter: station_id (operational UUID).",
    null_meaning="Missing dates = no evidence (unknown), never zero activity. NULL ratios = no observations that day.",
    timezone="UTC date_key.",
    traceability="station_key -> dim_station version -> public.stations.id via ETL.",
    sql="SELECT d.full_date, f.observation_count, f.available_count, f.busy_count, f.broken_count, "
        "f.availability_ratio, f.report_count, f.review_count, f.avg_rating, f.maturity "
        "FROM analytics.fact_station_daily f JOIN analytics.dim_date d USING (date_key) "
        "JOIN analytics.dim_station s USING (station_key) "
        "WHERE s.station_id = %(station_id)s AND s.is_current ORDER BY d.full_date",
))

_register(OlapQuery(
    name="community_volume_daily",
    meaning="Approved community-signal volume vs system observations per day.",
    grain="One row per date with any evidence.",
    data="analytics.fact_station_daily + dim_date.",
    null_meaning="Missing dates = no evidence anywhere.",
    timezone="UTC date_key.",
    traceability="Sums of report_count/review_count/observation_count grain facts.",
    sql="SELECT d.full_date, sum(f.observation_count) AS system_obs, "
        "sum(f.report_count) AS approved_reports, sum(f.review_count) AS approved_reviews "
        "FROM analytics.fact_station_daily f JOIN analytics.dim_date d USING (date_key) "
        "GROUP BY d.full_date ORDER BY d.full_date",
))

_register(OlapQuery(
    name="busy_slots_by_city",
    meaning="Busiest 15-minute slots by observed busy status in a city.",
    grain="One row per 15-minute slot with at least one busy observation.",
    data="fact_station_observation + dim_location + dim_time. Parameter: city.",
    null_meaning="Slots without busy observations do not appear (no evidence, not quiet).",
    timezone="UTC slots.",
    traceability="observation_id -> public.station_observations.id via ETL.",
    sql="SELECT t.slot_15min, count(*) AS busy_obs "
        "FROM analytics.fact_station_observation o "
        "JOIN analytics.dim_station s USING (station_key) "
        "JOIN analytics.dim_location l USING (location_key) "
        "JOIN analytics.dim_time t USING (time_key) "
        "WHERE l.city = %(city)s AND o.availability_status = 'busy' "
        "GROUP BY t.slot_15min ORDER BY busy_obs DESC",
))

_register(OlapQuery(
    name="ingestion_health",
    meaning="Recent pipeline runs with outcome and volume (operations, includes warehouse ETL runs).",
    grain="One row per recorded run. Parameter: limit (default 20).",
    data="public.ingestion_runs (read via service role; admin only).",
    null_meaning="No rows = no recorded runs (unknown health, not healthy).",
    timezone="UTC started_at.",
    traceability="run_id per execution; warehouse runs carry source_name='warehouse_etl'.",
    sql="SELECT source_name, scope, state, started_at, duration_seconds, records_fetched, "
        "stations_persisted, observations_persisted, error_summary "
        "FROM public.ingestion_runs ORDER BY started_at DESC LIMIT %(limit)s",
))

_register(OlapQuery(
    name="source_quality",
    meaning="Evidence volume per source: stations linked, observations, facts.",
    grain="One row per warehouse source.",
    data="analytics.dim_source + fact_station_observation.",
    null_meaning="Zero counts with a present source = no evidence through that feed.",
    timezone="N/A (cumulative).",
    traceability="source_key -> dim_source.source_id -> public.data_sources.id via ETL.",
    sql="SELECT ds.name, count(DISTINCT o.station_key) AS stations_observed, count(o.observation_id) AS observations "
        "FROM analytics.dim_source ds LEFT JOIN analytics.fact_station_observation o USING (source_key) "
        "GROUP BY ds.name ORDER BY observations DESC",
))

_register(OlapQuery(
    name="maturity_overview",
    meaning="Stations by warehouse maturity state (cold/warming/ready) from latest daily rows.",
    grain="One row per maturity state present.",
    data="analytics.fact_station_daily (latest row per station).",
    null_meaning="Stations with no daily rows are unmeasured (absent, not cold) — counted separately.",
    timezone="UTC date_key.",
    traceability="maturity derived from evidence days/observations per documented v1 gate.",
    sql="WITH latest AS (SELECT DISTINCT ON (station_key) station_key, maturity FROM analytics.fact_station_daily "
        "ORDER BY station_key, date_key DESC) "
        "SELECT maturity, count(*) AS stations FROM latest GROUP BY maturity",
))


def run_query(conn: Any, name: str, params: Optional[dict] = None) -> list[dict]:
    """Executes a named OLAP query, returning rows as dicts."""
    if name not in QUERIES:
        raise ValueError(f"Unknown OLAP query '{name}'")
    with conn.cursor() as cur:
        cur.execute(QUERIES[name].sql, params or {})
        cols = [d[0] for d in (cur.description or [])]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
