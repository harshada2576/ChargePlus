"""ChargePlus — Data maturity measurement & ML feasibility gate (Phase 5/6, Step 5.1).

Read-only assessment of what the REAL warehouse evidence can support.
Never fabricates history; unknown is reported as unknown, never zero.

Reuses the Phase 4 maturity vocabulary (COLD / WARMING / READY) and the
v1 gate constants from backend.warehouse.etl:
  WARMING: >= 7 evidence days in trailing 90 days (per station)
  READY:   >= 30 evidence days AND >= 200 observations (per station)
Overall warehouse maturity = highest per-station state achieved; with no
temporal evidence the warehouse is COLD. Thresholds below marked
[DIAGNOSTIC] are analytical diagnostics, not product requirements.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import Any, Optional

from dotenv import load_dotenv

from backend.warehouse.etl import (
    MATURITY_READY_DAYS,
    MATURITY_READY_OBSERVATIONS,
    MATURITY_WARMING_DAYS,
)

logger = logging.getLogger("chargeplus.warehouse.maturity")

# [DIAGNOSTIC] minimum target events and distinct dates for a chronological
# 60/20/20 train/validation/test split to be non-empty in every bucket.
MIN_TRAIN_EVENTS = 30
MIN_TRAIN_DATES = 14

# [DIAGNOSTIC] station history sufficiency buckets.
SUFFICIENT_HISTORY_OBS = 10


def _scalar(cur: Any, sql: str, params: tuple = ()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return 0
    return int(row[0] if isinstance(row, (tuple, list)) else list(row.values())[0])


def _rows(cur: Any, sql: str, params: tuple = ()) -> list[tuple]:
    cur.execute(sql, params)
    return [tuple(r) for r in cur.fetchall()]


# ----------------------------------------------------------------------
# Pure helpers (deterministic, unit-tested with fixtures)
# ----------------------------------------------------------------------
def gap_stats(dates: list[str]) -> dict[str, Any]:
    """Gap statistics over sorted ISO date strings. Empty -> unknown Nones."""
    uniq = sorted(set(dates))
    if len(uniq) < 2:
        return {"distinct_dates": len(uniq), "max_gap_days": None,
                "median_gap_days": None, "regularity": "unknown"}
    ords = [datetime.fromisoformat(d).date().toordinal() for d in uniq]
    gaps = [b - a for a, b in zip(ords, ords[1:])]
    med = float(median(gaps))
    if med <= 1.5 and max(gaps) <= 7:
        regularity = "regular"
    elif med <= 7:
        regularity = "irregular"
    else:
        regularity = "sparse"
    return {"distinct_dates": len(uniq), "max_gap_days": max(gaps),
            "median_gap_days": med, "regularity": regularity}


def classify_station(evidence_days_90d: int, total_observations: int) -> str:
    """Per-station COLD/WARMING/READY using the Phase 4 v1 gate constants."""
    if (evidence_days_90d >= MATURITY_READY_DAYS
            and total_observations >= MATURITY_READY_OBSERVATIONS):
        return "READY"
    if evidence_days_90d >= MATURITY_WARMING_DAYS:
        return "WARMING"
    return "COLD"


def split_feasible(n_events: int, n_dates: int) -> dict[str, Any]:
    """Whether a chronological 60/20/20 split can be non-empty everywhere."""
    feasible = n_events >= MIN_TRAIN_EVENTS and n_dates >= MIN_TRAIN_DATES
    return {"feasible": feasible, "min_events": MIN_TRAIN_EVENTS,
            "min_dates": MIN_TRAIN_DATES, "n_events": n_events, "n_dates": n_dates}


def pct(missing: int, total: int) -> Optional[float]:
    if total <= 0:
        return None  # unknown denominator: unknown, never 0%
    return round(100.0 * missing / total, 2)


# ----------------------------------------------------------------------
# Live measurement (read-only SQL over warehouse + OLTP counts)
# ----------------------------------------------------------------------
def get_counts(cur: Any) -> dict[str, int]:
    tables = ["public.stations", "public.connectors", "public.station_observations",
              "public.user_reports", "public.reviews", "public.favorites", "public.alerts",
              "public.ingestion_runs", "analytics.dim_station", "analytics.dim_connector",
              "analytics.fact_station_observation", "analytics.fact_user_report",
              "analytics.fact_review", "analytics.fact_station_daily"]
    out = {}
    for t in tables:
        out[t] = _scalar(cur, f"SELECT count(*) FROM {t}")
    out["stations_current"] = _scalar(
        cur, "SELECT count(*) FROM analytics.dim_station WHERE is_current")
    out["station_identities"] = _scalar(
        cur, "SELECT count(DISTINCT station_id) FROM analytics.dim_station")
    return out


def temporal_profile(cur: Any, table: str, ts_col: str, extra: str = "") -> dict[str, Any]:
    """Depth + coverage for one temporal source. Zero rows -> explicit unknown."""
    n = _scalar(cur, f"SELECT count(*) FROM {table} {extra}".rstrip())
    if n == 0:
        return {"count": 0, "earliest": None, "latest": None, "duration_days": None,
                "distinct_dates": 0, "distinct_weeks": 0, "distinct_months": 0,
                "max_gap_days": None, "median_gap_days": None, "regularity": "no evidence"}
    cur.execute(
        f"SELECT min({ts_col}), max({ts_col}) FROM {table} {extra}".rstrip())
    earliest, latest = cur.fetchone()
    # Be liberal in what we accept: drivers may return ISO strings.
    if isinstance(earliest, str):
        earliest = datetime.fromisoformat(earliest)
    if isinstance(latest, str):
        latest = datetime.fromisoformat(latest)
    cur.execute(
        f"SELECT DISTINCT ({ts_col} AT TIME ZONE 'UTC')::date FROM {table} {extra}".rstrip())
    dates = sorted(str(r[0]) for r in cur.fetchall())
    duration = (latest - earliest).days if earliest and latest else 0
    weeks = {d[:7] + "-W" + str(datetime.fromisoformat(d).isocalendar()[1]) for d in dates}
    months = {d[:7] for d in dates}
    profile = {"count": n,
               "earliest": earliest.isoformat() if earliest else None,
               "latest": latest.isoformat() if latest else None,
               "duration_days": duration,
               "distinct_weeks": len(weeks), "distinct_months": len(months)}
    profile.update(gap_stats(dates))
    return profile


def station_coverage(cur: Any) -> dict[str, Any]:
    total = _scalar(cur, "SELECT count(*) FROM public.stations")
    with_obs = _scalar(cur,
        "SELECT count(DISTINCT station_id) FROM public.station_observations")
    with_10 = _scalar(cur,
        "SELECT count(*) FROM (SELECT station_id FROM public.station_observations "
        "GROUP BY station_id HAVING count(*) >= %s) t", (SUFFICIENT_HISTORY_OBS,))
    return {"total_current": total, "with_ge_1_obs": with_obs,
            f"with_ge_{SUFFICIENT_HISTORY_OBS}_obs": with_10}


def connector_coverage(cur: Any) -> dict[str, Any]:
    rows = _rows(cur,
        "SELECT connector_type, charging_standard, count(*), "
        "sum(quantity), sum(CASE WHEN power_kw IS NULL THEN 1 ELSE 0 END) "
        "FROM public.connectors GROUP BY 1, 2 ORDER BY 1, 2")
    return {"by_type_standard": [
        {"type": r[0], "standard": r[1], "groups": int(r[2]),
         "units": int(r[3] or 0), "unknown_power_groups": int(r[4] or 0)} for r in rows],
        "note": "static inventory, not a time series"}


def price_profile(cur: Any) -> dict[str, Any]:
    total = _scalar(cur, "SELECT count(*) FROM public.connectors")
    known = _scalar(cur, "SELECT count(*) FROM public.connectors WHERE price_per_kwh IS NOT NULL")
    free = _scalar(cur, "SELECT count(*) FROM public.connectors WHERE price_per_kwh = 0")
    hist = _scalar(cur, "SELECT count(*) FROM analytics.fact_station_daily WHERE 1=0")
    return {"connectors": total, "known_price": known, "explicit_free": free,
            "unknown_price": total - known, "price_history_rows": hist,
            "history_supportable": False}


def behavior_profile(cur: Any) -> dict[str, Any]:
    out = {}
    for t in ("public.favorites", "public.user_reports", "public.reviews", "public.alerts"):
        n = _scalar(cur, f"SELECT count(*) FROM {t}")
        cur.execute(f"SELECT min(created_at), max(created_at) FROM {t}")
        mn, mx = cur.fetchone()
        out[t] = {"count": n,
                  "earliest": mn.isoformat() if mn else None,
                  "latest": mx.isoformat() if mx else None}
    return out


def missingness(cur: Any) -> list[dict[str, Any]]:
    rows = []
    total_conn = _scalar(cur, "SELECT count(*) FROM public.connectors")
    null_power = _scalar(cur, "SELECT count(*) FROM public.connectors WHERE power_kw IS NULL")
    rows.append({"field": "power_kw", "rows": total_conn, "missing": null_power,
                 "pct": pct(null_power, total_conn), "meaning": "expected unknown state, not corruption"})
    null_price = _scalar(cur, "SELECT count(*) FROM public.connectors WHERE price_per_kwh IS NULL")
    rows.append({"field": "price_per_kwh", "rows": total_conn, "missing": null_price,
                 "pct": pct(null_price, total_conn), "meaning": "unknown price, never free"})
    total_obs = _scalar(cur, "SELECT count(*) FROM public.station_observations")
    unk_avail = _scalar(cur, "SELECT count(*) FROM public.station_observations WHERE availability_status = 'unknown'")
    rows.append({"field": "availability", "rows": total_obs, "missing": unk_avail,
                 "pct": pct(unk_avail, total_obs), "meaning": "unknown availability, never unavailable"})
    total_st = _scalar(cur, "SELECT count(*) FROM public.stations")
    unk_op = _scalar(cur,
        "SELECT count(*) FROM public.stations s JOIN public.operators o ON o.id = s.operator_id "
        "WHERE o.name = 'Unknown Operator'")
    rows.append({"field": "operator", "rows": total_st, "missing": unk_op,
                 "pct": pct(unk_op, total_st), "meaning": "unattributed source operator"})
    rows.append({"field": "rating", "rows": 0, "missing": 0, "pct": None,
                 "meaning": "no reviews: unknown rating, never 0"})
    return rows


def source_coverage(cur: Any) -> list[dict[str, Any]]:
    rows = _rows(cur, "SELECT id, name FROM public.data_sources ORDER BY name")
    out = []
    for sid, name in rows:
        stations = _scalar(cur,
            "SELECT count(DISTINCT station_id) FROM public.station_source_link WHERE source_id = %s", (str(sid),))
        obs = _scalar(cur,
            "SELECT count(*) FROM public.station_observations WHERE source_id = %s", (str(sid),))
        cur.execute("SELECT min(created_at), max(created_at) FROM public.station_observations WHERE source_id = %s",
                    (str(sid),))
        mn, mx = cur.fetchone()
        out.append({"source": name, "stations": stations, "observations": obs,
                    "earliest": mn.isoformat() if mn else None,
                    "latest": mx.isoformat() if mx else None,
                    "temporal_evidence": obs > 0})
    return out


def ingestion_vs_evidence(cur: Any) -> dict[str, Any]:
    runs = _scalar(cur, "SELECT count(*) FROM public.ingestion_runs WHERE source_name <> 'warehouse_etl'")
    fetched = _scalar(cur, "SELECT COALESCE(sum(records_fetched),0) FROM public.ingestion_runs WHERE source_name <> 'warehouse_etl'")
    obs_made = _scalar(cur, "SELECT COALESCE(sum(observations_persisted),0) FROM public.ingestion_runs")
    return {"ingestion_runs": runs, "records_fetched_total": int(fetched),
            "observations_persisted_total": int(obs_made),
            "note": "scheduler runs are not observations"}


def target_assessment(cur: Any) -> list[dict[str, Any]]:
    avail = _scalar(cur,
        "SELECT count(*) FROM public.station_observations WHERE availability_status <> 'unknown'")
    avail_dates = _scalar(cur,
        "SELECT count(DISTINCT (observed_at AT TIME ZONE 'UTC')::date) "
        "FROM public.station_observations WHERE availability_status <> 'unknown'")
    queue = _scalar(cur,
        "SELECT count(*) FROM public.station_observations WHERE queue_level NOT IN ('unknown')")
    queue_dates = _scalar(cur,
        "SELECT count(DISTINCT (observed_at AT TIME ZONE 'UTC')::date) "
        "FROM public.station_observations WHERE queue_level NOT IN ('unknown')")
    tasks = [
        {"task": "availability forecasting", "target": "observed availability_status <> 'unknown'",
         "events": avail, "dates": avail_dates},
        {"task": "queue prediction", "target": "observed queue_level known",
         "events": queue, "dates": queue_dates},
        {"task": "demand forecasting", "target": "charging sessions/usage events",
         "events": 0, "dates": 0, "note": "no session source exists"},
        {"task": "reliability prediction", "target": "repeated availability labels per station",
         "events": avail, "dates": avail_dates},
        {"task": "price prediction", "target": "temporal price changes",
         "events": 0, "dates": 0, "note": "static inventory only"},
        {"task": "station recommendation", "target": "behavioral usage events",
         "events": _scalar(cur, "SELECT count(*) FROM public.favorites")
                 + _scalar(cur, "SELECT count(*) FROM public.user_reports")
                 + _scalar(cur, "SELECT count(*) FROM public.reviews"),
         "dates": 0, "note": "no temporal behavior yet"},
    ]
    for t in tasks:
        split = split_feasible(t["events"], t["dates"])
        t["trainable_now"] = split["feasible"]
        t["split"] = split
    return tasks


def station_maturity(cur: Any) -> dict[str, Any]:
    """Per-station evidence days (trailing 90d) + total obs -> gate states."""
    rows = _rows(cur,
        "SELECT station_id, count(DISTINCT (observed_at AT TIME ZONE 'UTC')::date) "
        "FILTER (WHERE observed_at >= now() - interval '90 days'), count(*) "
        "FROM public.station_observations GROUP BY station_id")
    states: dict[str, int] = {"COLD": 0, "WARMING": 0, "READY": 0}
    total_st = _scalar(cur, "SELECT count(*) FROM public.stations")
    for _, days90, total in rows:
        states[classify_station(int(days90 or 0), int(total or 0))] += 1
    with_obs = len(rows)
    states["COLD"] += total_st - with_obs  # never observed: COLD
    overall = "COLD"
    if states["READY"] > 0:
        overall = "READY"
    elif states["WARMING"] > 0:
        overall = "WARMING"
    return {"per_station": states, "overall": overall,
            "gate": {"warming_days_90d": MATURITY_WARMING_DAYS,
                     "ready_days": MATURITY_READY_DAYS,
                     "ready_observations": MATURITY_READY_OBSERVATIONS}}


def leakage_risks() -> list[dict[str, str]]:
    return [
        {"risk": "future station state in features",
         "mitigation": "join facts to the dim version valid at event time, never is_current"},
        {"risk": "post-event moderation state as input",
         "mitigation": "moderation_status/moderated_at are load gates only, never features"},
        {"risk": "current connector inventory as historical truth",
         "mitigation": "no connector history exists; do not backfill"},
        {"risk": "aggregate rows leaking post-prediction information",
         "mitigation": "daily cells derive strictly from same-day-or-earlier grain facts"},
        {"risk": "random train/test splits hiding temporal insufficiency",
         "mitigation": "chronological splits only (split_feasible gate)"},
        {"risk": "OCM operational status as availability label",
         "mitigation": "Phase 2 rule stands: operational status != live availability"},
    ]


def capability_matrix(targets: list[dict[str, Any]], maturity_overall: str) -> list[dict[str, Any]]:
    by_task = {t["task"]: t for t in targets}
    any_temporal = any(t["dates"] > 0 for t in targets)
    return [
        {"capability": "descriptive analytics",
         "state": "AVAILABLE NOW",
         "evidence": "live dims/facts/OLAP queries over real inventory",
         "implement_now": True, "dependency": "none"},
        {"capability": "anomaly detection",
         "state": "NOT AVAILABLE" if not any_temporal else "AVAILABLE BUT SPARSE",
         "evidence": "requires temporal baseline; none exists",
         "implement_now": False, "dependency": "observation history"},
        {"capability": "availability forecasting",
         "state": "TRAINABLE" if by_task["availability forecasting"]["trainable_now"] else "NOT TRAINABLE",
         "evidence": f"{by_task['availability forecasting']['events']} labels",
         "implement_now": by_task["availability forecasting"]["trainable_now"],
         "dependency": "availability label history"},
        {"capability": "queue prediction",
         "state": "TRAINABLE" if by_task["queue prediction"]["trainable_now"] else "NOT TRAINABLE",
         "evidence": f"{by_task['queue prediction']['events']} labels",
         "implement_now": by_task["queue prediction"]["trainable_now"],
         "dependency": "queue label history"},
        {"capability": "demand forecasting",
         "state": "NOT AVAILABLE", "evidence": "no charging-session source",
         "implement_now": False, "dependency": "usage/session telemetry"},
        {"capability": "recommendation",
         "state": "INSUFFICIENT BEHAVIORAL EVIDENCE",
         "evidence": f"{by_task['station recommendation']['events']} behavior events, 0 temporal dates",
         "implement_now": False, "dependency": "temporal behavior history"},
        {"capability": "reliability analysis",
         "state": "TRAINABLE" if by_task["reliability prediction"]["trainable_now"] else "NOT TRAINABLE",
         "evidence": f"{by_task['reliability prediction']['events']} labels",
         "implement_now": by_task["reliability prediction"]["trainable_now"],
         "dependency": "repeated availability labels"},
        {"capability": "warehouse maturity",
         "state": maturity_overall, "evidence": "per-station v1 gate",
         "implement_now": True, "dependency": "none"},
    ]


def build_report(conn: Any) -> dict[str, Any]:
    """Full read-only maturity assessment. No writes, no synthetic data."""
    with conn.cursor() as cur:
        counts = get_counts(cur)
        obs = temporal_profile(cur, "public.station_observations", "observed_at")
        rep = temporal_profile(cur, "public.user_reports", "observed_at")
        rev = temporal_profile(cur, "public.reviews", "created_at")
        daily = temporal_profile(cur, "analytics.fact_station_daily", "created_at") \
            if counts["analytics.fact_station_daily"] else \
            {"count": 0, "earliest": None, "latest": None, "duration_days": None,
             "distinct_dates": 0, "distinct_weeks": 0, "distinct_months": 0,
             "max_gap_days": None, "median_gap_days": None, "regularity": "no evidence"}
        coverage = station_coverage(cur)
        connectors = connector_coverage(cur)
        prices = price_profile(cur)
        behavior = behavior_profile(cur)
        missing = missingness(cur)
        sources = source_coverage(cur)
        ingestion = ingestion_vs_evidence(cur)
        targets = target_assessment(cur)
        maturity = station_maturity(cur)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "temporal": {"observations": obs, "reports": rep, "reviews": rev, "daily": daily},
        "station_coverage": coverage,
        "connector_coverage": connectors,
        "price_profile": prices,
        "behavior_profile": behavior,
        "missingness": missing,
        "source_coverage": sources,
        "ingestion_vs_evidence": ingestion,
        "targets": targets,
        "maturity": maturity,
        "leakage_risks": leakage_risks(),
        "capabilities": capability_matrix(targets, maturity["overall"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ChargePlus data maturity & ML feasibility (5.1, read-only).")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    args = parser.parse_args()

    load_dotenv(".env.local")
    load_dotenv(".env")
    import psycopg2

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not configured.", file=sys.stderr)
        sys.exit(1)
    conn = psycopg2.connect(db_url)
    try:
        report = build_report(conn)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        m = report["maturity"]["overall"]
        print(f"warehouse maturity: {m}")
        print(f"observations: {report['temporal']['observations']['count']}")
        for t in report["targets"]:
            print(f"{t['task']}: {'TRAINABLE' if t['trainable_now'] else 'NOT TRAINABLE'} "
                  f"({t['events']} events, {t['dates']} dates)")
        print("capabilities:")
        for c in report["capabilities"]:
            print(f"  {c['capability']}: {c['state']}")


if __name__ == "__main__":
    main()
