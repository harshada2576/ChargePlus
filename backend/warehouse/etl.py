"""ChargePlus — Warehouse ETL (Phase 4/6, Steps 4.2–4.4).

Moves legitimate operational history from public (OLTP) into analytics
(warehouse). Conventions (see docs/data_warehouse.md):

- UTC bucket convention: event timestamps map to (date_key, time_key) in UTC.
- Grain fidelity: one evidence row in -> one fact row out.
- Only APPROVED reports/reviews WITH moderated_at enter facts.
- No-evidence station-days produce NO daily row.
- Unknown stays NULL (never 0/free/unavailable).
- Idempotency: business-key ON CONFLICT guards on every write.
- Run accounting reuses public.ingestion_runs with
  source_name='warehouse_etl' (no competing run table).

Load order: dimensions -> facts -> daily aggregates.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv

from backend.ingestion.persistence import IngestionPersistenceService, _scrub_secrets
from backend.ingestion.scheduling import IngestionRun, IngestionRunState

logger = logging.getLogger("chargeplus.warehouse.etl")

WAREHOUSE_ETL_SOURCE = "warehouse_etl"

# Queue level -> congestion score (documented v1 rule). 'unknown' excluded.
QUEUE_SCORES = {"none": 0.0, "short": 0.33, "medium": 0.66, "long": 1.0}

# Maturity gate v1 (documented; everything live is cold today).
MATURITY_WARMING_DAYS = 7
MATURITY_READY_DAYS = 30
MATURITY_READY_OBSERVATIONS = 200


def utc_keys(ts: datetime) -> tuple[int, int]:
    """Maps an aware timestamp to (date_key YYYYMMDD, time_key 0..95) in UTC."""
    u = ts.astimezone(timezone.utc)
    return int(u.strftime("%Y%m%d")), u.hour * 4 + u.minute // 15


@dataclass
class WarehouseSummary:
    """Structured metrics for one warehouse ETL execution."""

    job: str
    dry_run: bool
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dimensions_synced: int = 0
    report_facts_loaded: int = 0
    review_facts_loaded: int = 0
    daily_rows_upserted: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    run_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job": self.job,
            "dry_run": self.dry_run,
            "started_at": self.started_at.isoformat(),
            "dimensions_synced": self.dimensions_synced,
            "report_facts_loaded": self.report_facts_loaded,
            "review_facts_loaded": self.review_facts_loaded,
            "daily_rows_upserted": self.daily_rows_upserted,
            "skipped": self.skipped,
            "warnings": self.warnings[:10],
            "duration_seconds": round(self.duration_seconds, 2),
            "run_id": self.run_id,
        }


class WarehouseETL:
    """Canonical warehouse pipeline: public operational data -> analytics."""

    def __init__(self, db_url: Optional[str] = None, conn: Any = None):
        load_dotenv(".env.local")
        load_dotenv(".env")
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self._conn = conn
        self._owns_conn = False
        # Reuse canonical dimension sync (SCD2, operator/location/source).
        self._dims: Optional[IngestionPersistenceService] = None

    def _connect(self) -> Any:
        if self._conn is not None:
            return self._conn
        if not self.db_url:
            raise RuntimeError("DATABASE_URL is not configured; warehouse ETL needs the database.")
        import psycopg2

        self._conn = psycopg2.connect(self.db_url)
        self._owns_conn = True
        return self._conn

    def close(self) -> None:
        if self._owns_conn and self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None
        self._owns_conn = False

    # ------------------------------------------------------------------
    # Dimensions (Step 4.1): reuse canonical sync, driven over OLTP state
    # ------------------------------------------------------------------
    def sync_dimensions(self, dry_run: bool = False, limit: Optional[int] = None) -> WarehouseSummary:
        """Ensures every public station/connector/source is mirrored in dims.

        Idempotent: SCD2 no-ops when attributes match; Type 1 upserts by
        business key. Returns counts of touched dimension versions/rows.
        """
        summary = WarehouseSummary(job="dimensions", dry_run=dry_run)
        start = time.time()
        conn = self._connect()
        dims = IngestionPersistenceService(conn)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM public.stations ORDER BY created_at LIMIT %s;", (limit or 1000000,))
                station_ids = [r[0] for r in cur.fetchall()]
                cur.execute("SELECT id FROM public.data_sources ORDER BY name;")
                sources = cur.fetchall()
            for sid in station_ids:
                if dry_run:
                    summary.dimensions_synced += 1
                    continue
                with conn.cursor() as cur:
                    key = dims._sync_dim_station_scd2(cur, sid)
                    conn.commit()
                    if key:
                        summary.dimensions_synced += 1
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, station_id, connector_type, charging_standard, power_kw,"
                    " quantity, pricing_type, price_per_kwh, price_per_session"
                    " FROM public.connectors ORDER BY created_at LIMIT %s;",
                    (limit or 1000000,),
                )
                connectors = cur.fetchall()
            for row in connectors:
                cid, station_id, c_type, std, pkw, qty, p_type, p_kwh, p_sess = (
                    row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8],
                )
                if dry_run:
                    summary.dimensions_synced += 1
                    continue
                with conn.cursor() as cur:
                    dims._sync_dim_connector(
                        cur, cid, station_id, c_type, std,
                        float(pkw) if pkw is not None else None,
                        qty, p_type, p_kwh, p_sess,
                    )
                    conn.commit()
                    summary.dimensions_synced += 1
            if not dry_run:
                with conn.cursor() as cur:
                    for (source_id,) in sources:
                        cur.execute("SELECT id, name, source_type, base_url FROM public.data_sources WHERE id = %s;", (str(source_id),))
                        srow = cur.fetchone()
                        if srow:
                            dims._ensure_dim_source(
                                srow[0], srow[1], srow[2], srow[3],
                                source_priority=100, commit=False,
                            )
                    conn.commit()
        except Exception as ex:
            try:
                conn.rollback()
            except Exception:
                pass
            summary.warnings.append(f"sync_dimensions failed: {_scrub_secrets(str(ex))}")
            raise
        finally:
            summary.duration_seconds = time.time() - start
        return summary

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_station_key_at(cur: Any, station_id: str, ts: datetime) -> Optional[int]:
        """Point-in-time dim_station version for an event timestamp (UTC)."""
        cur.execute(
            "SELECT station_key FROM analytics.dim_station"
            " WHERE station_id = %s AND effective_from <= %s"
            " AND (effective_to IS NULL OR effective_to > %s)"
            " ORDER BY effective_from DESC LIMIT 1;",
            (str(station_id), ts, ts),
        )
        row = cur.fetchone()
        if not row:
            return None
        return row[0] if isinstance(row, (tuple, list)) else row["station_key"]

    @staticmethod
    def _dim_date_exists(cur: Any, date_key: int) -> bool:
        cur.execute("SELECT 1 FROM analytics.dim_date WHERE date_key = %s;", (date_key,))
        return cur.fetchone() is not None

    # ------------------------------------------------------------------
    # Report / review facts (Step 4.2)
    # ------------------------------------------------------------------
    def sync_report_facts(self, dry_run: bool = False, limit: Optional[int] = None) -> WarehouseSummary:
        """Loads APPROVED user_reports (with moderated_at) into fact_user_report.

        Grain: one row = one approved report. No user_id, no comment text.
        Idempotent by report_id business key.
        """
        summary = WarehouseSummary(job="report-facts", dry_run=dry_run)
        start = time.time()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT r.id, r.station_id, r.connector_id, r.availability_status, r.queue_level,"
                    " r.observed_at, r.moderated_at, r.is_flagged"
                    " FROM public.user_reports r LEFT JOIN analytics.fact_user_report f ON f.report_id = r.id"
                    " WHERE r.moderation_status = 'approved' AND r.moderated_at IS NOT NULL"
                    " AND f.report_id IS NULL ORDER BY r.created_at LIMIT %s;",
                    (limit or 1000000,),
                )
                pending = cur.fetchall()
            for row in pending:
                rid, station_id, connector_id, avail, queue, observed_at, moderated_at, flagged = (
                    str(row[0]), str(row[1]), row[2], row[3], row[4], row[5], row[6], bool(row[7]),
                )
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=timezone.utc)
                date_key, time_key = utc_keys(observed_at)
                with conn.cursor() as cur:
                    if not self._dim_date_exists(cur, date_key):
                        summary.skipped += 1
                        summary.warnings.append(f"report {rid}: observed date outside dim_date range; skipped")
                        continue
                    station_key = self._resolve_station_key_at(cur, station_id, observed_at)
                    if not station_key:
                        summary.skipped += 1
                        summary.warnings.append(f"report {rid}: no dim_station version at event time; skipped")
                        continue
                    connector_key = None
                    if connector_id is not None:
                        cur.execute("SELECT connector_key FROM analytics.dim_connector WHERE connector_id = %s;", (str(connector_id),))
                        crow = cur.fetchone()
                        connector_key = (crow[0] if isinstance(crow, (tuple, list)) else crow["connector_key"]) if crow else None
                    if dry_run:
                        summary.report_facts_loaded += 1
                        continue
                    cur.execute(
                        "INSERT INTO analytics.fact_user_report (report_id, station_key, connector_key, date_key,"
                        " time_key, observed_at, availability_status, queue_level, report_count,"
                        " moderation_status, moderated_at, is_flagged)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,'approved',%s,%s)"
                        " ON CONFLICT (report_id) DO NOTHING;",
                        (rid, station_key, connector_key, date_key, time_key, observed_at, avail, queue, moderated_at, flagged),
                    )
                    conn.commit()
                    summary.report_facts_loaded += 1
        except Exception as ex:
            try:
                conn.rollback()
            except Exception:
                pass
            summary.warnings.append(f"sync_report_facts failed: {_scrub_secrets(str(ex))}")
            raise
        finally:
            summary.duration_seconds = time.time() - start
        return summary

    def sync_review_facts(self, dry_run: bool = False, limit: Optional[int] = None) -> WarehouseSummary:
        """Loads APPROVED reviews (with moderated_at) into fact_review.

        Grain: one row = one approved review. Rating only; no user_id, no
        comment text. Idempotent by review_id business key.
        """
        summary = WarehouseSummary(job="review-facts", dry_run=dry_run)
        start = time.time()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT r.id, r.station_id, r.rating, r.created_at, r.moderated_at"
                    " FROM public.reviews r LEFT JOIN analytics.fact_review f ON f.review_id = r.id"
                    " WHERE r.moderation_status = 'approved' AND r.moderated_at IS NOT NULL"
                    " AND f.review_id IS NULL ORDER BY r.created_at LIMIT %s;",
                    (limit or 1000000,),
                )
                pending = cur.fetchall()
            for row in pending:
                rid, station_id, rating, created_at, moderated_at = (
                    str(row[0]), str(row[1]), int(row[2]), row[3], row[4],
                )
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                date_key = int(created_at.astimezone(timezone.utc).strftime("%Y%m%d"))
                with conn.cursor() as cur:
                    if not self._dim_date_exists(cur, date_key):
                        summary.skipped += 1
                        summary.warnings.append(f"review {rid}: date outside dim_date range; skipped")
                        continue
                    station_key = self._resolve_station_key_at(cur, station_id, created_at)
                    if not station_key:
                        summary.skipped += 1
                        summary.warnings.append(f"review {rid}: no dim_station version at event time; skipped")
                        continue
                    if dry_run:
                        summary.review_facts_loaded += 1
                        continue
                    cur.execute(
                        "INSERT INTO analytics.fact_review (review_id, station_key, date_key, rating,"
                        " review_count, moderation_status, moderated_at)"
                        " VALUES (%s,%s,%s,%s,1,'approved',%s)"
                        " ON CONFLICT (review_id) DO NOTHING;",
                        (rid, station_key, date_key, rating, moderated_at),
                    )
                    conn.commit()
                    summary.review_facts_loaded += 1
        except Exception as ex:
            try:
                conn.rollback()
            except Exception:
                pass
            summary.warnings.append(f"sync_review_facts failed: {_scrub_secrets(str(ex))}")
            raise
        finally:
            summary.duration_seconds = time.time() - start
        return summary

    # ------------------------------------------------------------------
    # Daily aggregates (Step 4.3)
    # ------------------------------------------------------------------
    def build_daily(self, dry_run: bool = False, date_key: Optional[int] = None) -> WarehouseSummary:
        """Derives fact_station_daily rows from grain facts (UTC dates).

        Grain: one row = one station_key x date_key WITH evidence.
        No-evidence days produce no row. Upsert by PK (idempotent recompute).
        Ratios/scores are NULL when their denominator has no evidence.
        """
        summary = WarehouseSummary(job="daily", dry_run=dry_run)
        start = time.time()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                date_filter = "AND o.date_key = %s" if date_key else ""
                params: tuple = (date_key,) if date_key else ()
                cur.execute(
                    "SELECT o.station_key, o.date_key, o.availability_status, o.queue_level,"
                    " o.available_connectors, o.total_connectors, o.source_key"
                    f" FROM analytics.fact_station_observation o WHERE 1=1 {date_filter};",
                    params,
                )
                obs_rows = cur.fetchall()
                rep_filter = "AND r.date_key = %s" if date_key else ""
                cur.execute(
                    "SELECT r.station_key, r.date_key FROM analytics.fact_user_report r"
                    f" WHERE 1=1 {rep_filter};",
                    params,
                )
                rep_rows = cur.fetchall()
                cur.execute(
                    "SELECT v.station_key, v.date_key, v.rating FROM analytics.fact_review v"
                    f" WHERE 1=1 {rep_filter};",
                    params,
                )
                rev_rows = cur.fetchall()
            cells: dict[tuple[int, int], dict[str, Any]] = {}

            def cell(sk: int, dk: int) -> dict[str, Any]:
                key = (sk, dk)
                if key not in cells:
                    cells[key] = {"obs": [], "reports": 0, "ratings": [], "sources": set()}
                return cells[key]

            for sk, dk, avail, queue, a_conn, t_conn, s_key in obs_rows:
                c = cell(int(sk), int(dk))
                c["obs"].append({"avail": avail, "queue": queue, "a": a_conn, "t": t_conn})
                if s_key is not None:
                    c["sources"].add(int(s_key))
            for sk, dk in rep_rows:
                cell(int(sk), int(dk))["reports"] += 1
            for sk, dk, rating in rev_rows:
                cell(int(sk), int(dk))["ratings"].append(int(rating))

            for (sk, dk), c in cells.items():
                n_obs = len(c["obs"])
                n_avail = sum(1 for o in c["obs"] if o["avail"] == "available")
                n_busy = sum(1 for o in c["obs"] if o["avail"] == "busy")
                n_broken = sum(1 for o in c["obs"] if o["avail"] == "broken")
                known_q = [QUEUE_SCORES[o["queue"]] for o in c["obs"] if o["queue"] in QUEUE_SCORES]
                complete = [
                    1
                    if (o["avail"] != "unknown" and o["queue"] != "unknown" and (o["t"] or 0) > 0)
                    else 0
                    for o in c["obs"]
                ]
                ratings = c["ratings"]
                row = {
                    "station_key": sk,
                    "date_key": dk,
                    "observation_count": n_obs,
                    "report_count": c["reports"],
                    "review_count": len(ratings),
                    "available_count": n_avail,
                    "busy_count": n_busy,
                    "broken_count": n_broken,
                    "availability_ratio": (n_avail / n_obs) if n_obs else None,
                    "busy_ratio": (n_busy / n_obs) if n_obs else None,
                    "broken_ratio": (n_broken / n_obs) if n_obs else None,
                    "avg_queue_score": (sum(known_q) / len(known_q)) if known_q else None,
                    "peak_queue_score": max(known_q) if known_q else None,
                    "avg_rating": (sum(ratings) / len(ratings)) if ratings else None,
                    "data_completeness_score": (sum(complete) / len(complete)) if complete else None,
                    "source_count": len(c["sources"]),
                    "maturity": "cold",
                    "has_evidence": True,
                }
                if dry_run:
                    summary.daily_rows_upserted += 1
                    continue
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO analytics.fact_station_daily (station_key, date_key, observation_count,"
                        " report_count, review_count, available_count, busy_count, broken_count, availability_ratio,"
                        " busy_ratio, broken_ratio, avg_queue_score, peak_queue_score, avg_rating,"
                        " data_completeness_score, source_count, maturity, has_evidence)"
                        " VALUES (%(station_key)s,%(date_key)s,%(observation_count)s,%(report_count)s,"
                        " %(review_count)s,%(available_count)s,%(busy_count)s,%(broken_count)s,"
                        " %(availability_ratio)s,%(busy_ratio)s,%(broken_ratio)s,%(avg_queue_score)s,"
                        " %(peak_queue_score)s,%(avg_rating)s,%(data_completeness_score)s,"
                        " %(source_count)s,%(maturity)s,%(has_evidence)s)"
                        " ON CONFLICT (station_key, date_key) DO UPDATE SET"
                        " observation_count=EXCLUDED.observation_count, report_count=EXCLUDED.report_count,"
                        " review_count=EXCLUDED.review_count, available_count=EXCLUDED.available_count,"
                        " busy_count=EXCLUDED.busy_count, broken_count=EXCLUDED.broken_count,"
                        " availability_ratio=EXCLUDED.availability_ratio, busy_ratio=EXCLUDED.busy_ratio,"
                        " broken_ratio=EXCLUDED.broken_ratio, avg_queue_score=EXCLUDED.avg_queue_score,"
                        " peak_queue_score=EXCLUDED.peak_queue_score, avg_rating=EXCLUDED.avg_rating,"
                        " data_completeness_score=EXCLUDED.data_completeness_score,"
                        " source_count=EXCLUDED.source_count, maturity=EXCLUDED.maturity,"
                        " has_evidence=EXCLUDED.has_evidence, updated_at=now();",
                        row,
                    )
                    conn.commit()
                    summary.daily_rows_upserted += 1
        except Exception as ex:
            try:
                conn.rollback()
            except Exception:
                pass
            summary.warnings.append(f"build_daily failed: {_scrub_secrets(str(ex))}")
            raise
        finally:
            summary.duration_seconds = time.time() - start
        return summary

    # ------------------------------------------------------------------
    # Orchestration + run accounting (ingestion_runs, source warehouse_etl)
    # ------------------------------------------------------------------
    def run(
        self,
        job: str = "all",
        dry_run: bool = False,
        limit: Optional[int] = None,
        date_key: Optional[int] = None,
    ) -> WarehouseSummary:
        """Executes warehouse jobs in canonical order with run accounting."""
        overall = WarehouseSummary(job=job, dry_run=dry_run)
        start = time.time()
        failed: Optional[Exception] = None
        jobs = ["dimensions", "report-facts", "review-facts", "daily"] if job == "all" else [job]
        try:
            for j in jobs:
                if j == "dimensions":
                    s = self.sync_dimensions(dry_run=dry_run, limit=limit)
                    overall.dimensions_synced += s.dimensions_synced
                elif j == "report-facts":
                    s = self.sync_report_facts(dry_run=dry_run, limit=limit)
                    overall.report_facts_loaded += s.report_facts_loaded
                elif j == "review-facts":
                    s = self.sync_review_facts(dry_run=dry_run, limit=limit)
                    overall.review_facts_loaded += s.review_facts_loaded
                elif j == "daily":
                    s = self.build_daily(dry_run=dry_run, date_key=date_key)
                    overall.daily_rows_upserted += s.daily_rows_upserted
                else:
                    raise ValueError(f"Unknown warehouse job '{j}'")
                overall.skipped += s.skipped
                overall.warnings.extend(s.warnings)
        except Exception as ex:
            failed = ex
        overall.duration_seconds = time.time() - start

        if not dry_run:
            try:
                conn = self._connect()
                dims = IngestionPersistenceService(conn)
                if failed is not None:
                    state = IngestionRunState.FAILED
                elif overall.skipped > 0 or overall.warnings:
                    state = IngestionRunState.PARTIAL
                else:
                    state = IngestionRunState.SUCCEEDED
                run = IngestionRun(
                    run_id=str(uuid.uuid4()),
                    source_id=None,
                    source_name=WAREHOUSE_ETL_SOURCE,
                    scope=f"warehouse:{job}",
                    state=state,
                    started_at=overall.started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=overall.duration_seconds,
                    attempt_count=1,
                    records_fetched=0,
                    records_parsed=0,
                    records_accepted=0,
                    records_accepted_with_warnings=0,
                    records_quarantined=0,
                    records_rejected=0,
                    stations_persisted=overall.dimensions_synced,
                    stations_updated=0,
                    stations_unchanged=0,
                    connectors_persisted=overall.report_facts_loaded + overall.review_facts_loaded,
                    observations_persisted=overall.daily_rows_upserted,
                    persistence_errors=list(overall.warnings),
                    error_summary="; ".join(overall.warnings[:3]) if (failed or overall.warnings) else None,
                    metadata={"job": job, "dry_run": dry_run},
                )
                dims.persist_ingestion_run(run, dry_run=False)
                overall.run_id = run.run_id
            except Exception as ex:
                logger.warning("Warehouse run accounting failed: %s", _scrub_secrets(str(ex)))
        if failed is not None:
            raise failed
        return overall


def main() -> None:
    parser = argparse.ArgumentParser(description="ChargePlus warehouse ETL (Phase 4).")
    parser.add_argument("--job", default="all",
                        choices=["all", "dimensions", "report-facts", "review-facts", "daily"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--date-key", type=int, default=None, help="Restrict daily build to one YYYYMMDD date")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    etl = WarehouseETL()
    try:
        summary = etl.run(job=args.job, dry_run=args.dry_run, limit=args.limit, date_key=args.date_key)
        if args.json:
            print(json.dumps(summary.to_dict(), indent=2))
        else:
            d = summary.to_dict()
            print(f"warehouse:{d['job']} dry_run={d['dry_run']} dims={d['dimensions_synced']}"
                  f" reports={d['report_facts_loaded']} reviews={d['review_facts_loaded']}"
                  f" daily={d['daily_rows_upserted']} skipped={d['skipped']} run={d['run_id']}")
    except Exception as ex:
        logger.error("Warehouse ETL failed: %s", _scrub_secrets(str(ex)))
        sys.exit(1)
    finally:
        etl.close()


if __name__ == "__main__":
    main()
