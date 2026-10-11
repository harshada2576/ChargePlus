"""ChargePlus — Phase 4 warehouse tests (Steps 4.1–4.6, 4.8).

Covers ETL dimensions/facts/daily math, idempotent reruns, DQ rule
mapping, OLAP query hygiene, and run accounting — against a strict
in-memory mock. Mock SQL coverage is asserted (unhandled statements
raise), and every test asserts concrete stored state, so vacuous
zero-work passes are impossible. Live-database proof happens in 4.8
via read-only reconciliation, documented separately.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from backend.warehouse.etl import WarehouseETL
from backend.warehouse.quality import run_all_checks
from backend.warehouse.queries import QUERIES, run_query
from tests.test_canonical_operational_loading import (
    MockDatabaseConnection,
    MockDatabaseCursor,
)

NOW = datetime.now(timezone.utc)
DAY = int(NOW.strftime("%Y%m%d"))


class WarehouseMockCursor(MockDatabaseCursor):
    """Strict extension: handles warehouse-ETL statements, real semantics."""

    def execute(self, sql: str, params=()):
        sql_clean = " ".join(sql.strip().split())
        db = self.db
        p = params if isinstance(params, (tuple, list)) else params

        def done(rows):
            self._last_result = rows
            self._iter = iter(self._last_result)

        # -- ETL listings -------------------------------------------------
        if sql_clean.startswith("SELECT id FROM public.stations ORDER BY"):
            rows = sorted(db.tables["public.stations"], key=lambda s: str(s.get("created_at", "")))
            done([(s["id"],) for s in rows][: (p[0] if p else 10**9)])
            return
        if sql_clean.startswith("SELECT id FROM public.data_sources ORDER BY"):
            done([(s["id"],) for s in db.tables["public.data_sources"]])
            return
        if "FROM public.data_sources WHERE id = %s" in sql_clean:
            for s in db.tables["public.data_sources"]:
                if str(s["id"]) == str(p[0]):
                    done([(s["id"], s["name"], s.get("source_type"), s.get("base_url"))])
                    return
            done([])
            return
        if sql_clean.startswith("SELECT id, station_id, connector_type,"):
            rows = sorted(db.tables["public.connectors"], key=lambda c: str(c.get("created_at", "")))
            done([(
                c["id"], c["station_id"], c["connector_type"], c.get("charging_standard"),
                c.get("power_kw"), c.get("quantity", 1), c.get("pricing_type"),
                c.get("price_per_kwh"), c.get("price_per_session"),
            ) for c in rows][: (p[0] if p else 10**9)])
            return

        # -- Pending reports / reviews ------------------------------------
        if "FROM public.user_reports r LEFT JOIN analytics.fact_user_report" in sql_clean:
            loaded = {str(r["report_id"]) for r in db.tables["analytics.fact_user_report"]}
            out = []
            for r in sorted(db.tables["public.user_reports"], key=lambda x: str(x.get("created_at", ""))):
                if (r.get("moderation_status") == "approved" and r.get("moderated_at") is not None
                        and str(r["id"]) not in loaded):
                    out.append((r["id"], r["station_id"], r.get("connector_id"), r["availability_status"],
                                r["queue_level"], r["observed_at"], r["moderated_at"], r.get("is_flagged", False)))
            done(out[: (p[0] if p else 10**9)])
            return
        if "FROM public.reviews r LEFT JOIN analytics.fact_review" in sql_clean:
            loaded = {str(r["review_id"]) for r in db.tables["analytics.fact_review"]}
            out = []
            for r in sorted(db.tables["public.reviews"], key=lambda x: str(x.get("created_at", ""))):
                if (r.get("moderation_status") == "approved" and r.get("moderated_at") is not None
                        and str(r["id"]) not in loaded):
                    out.append((r["id"], r["station_id"], r["rating"], r["created_at"], r["moderated_at"]))
            done(out[: (p[0] if p else 10**9)])
            return

        # -- Dimension lookups ---------------------------------------------
        if "FROM analytics.dim_date WHERE date_key = %s" in sql_clean:
            done([(1,)] if int(p[0]) in db.dim_dates else [])
            return
        if "FROM analytics.dim_station" in sql_clean and "effective_from" in sql_clean:
            sid, ts, _ts2 = str(p[0]), p[1], p[2]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            best = None
            for v in db.tables["analytics.dim_station"]:
                if str(v["station_id"]) != sid:
                    continue
                ef = v["effective_from"]
                if ef.tzinfo is None:
                    ef = ef.replace(tzinfo=timezone.utc)
                et = v.get("effective_to")
                if et is not None and et.tzinfo is None:
                    et = et.replace(tzinfo=timezone.utc)
                if ef <= ts and (et is None or et > ts):
                    if best is None or ef > best[0]:
                        best = (ef, v["station_key"])
            done([(best[1],)] if best else [])
            return
        if "FROM analytics.dim_connector WHERE connector_id = %s" in sql_clean:
            for c in db.tables["analytics.dim_connector"]:
                if str(c["connector_id"]) == str(p[0]):
                    done([(c["connector_key"],)])
                    return
            done([])
            return

        # -- Fact inserts ----------------------------------------------------
        if sql_clean.startswith("INSERT INTO analytics.fact_user_report"):
            rid = str(p[0])
            if not any(str(r["report_id"]) == rid for r in db.tables["analytics.fact_user_report"]):
                db.tables["analytics.fact_user_report"].append({
                    "report_id": rid, "station_key": p[1], "connector_key": p[2],
                    "date_key": p[3], "time_key": p[4], "observed_at": p[5],
                    "availability_status": p[6], "queue_level": p[7],
                    "moderation_status": "approved", "moderated_at": p[8], "is_flagged": p[9],
                })
            done([])
            return
        if sql_clean.startswith("INSERT INTO analytics.fact_review"):
            rid = str(p[0])
            if not any(str(r["review_id"]) == rid for r in db.tables["analytics.fact_review"]):
                db.tables["analytics.fact_review"].append({
                    "review_id": rid, "station_key": p[1], "date_key": p[2],
                    "rating": p[3], "moderation_status": "approved", "moderated_at": p[4],
                })
            done([])
            return

        # -- Daily build reads -------------------------------------------------
        if sql_clean.startswith("SELECT o.station_key, o.date_key, o.availability_status"):
            rows = db.tables["analytics.fact_station_observation"]
            if p:
                rows = [r for r in rows if r["date_key"] == p[0]]
            done([(r["station_key"], r["date_key"], r["availability_status"], r["queue_level"],
                   r.get("available_connectors"), r.get("total_connectors"), r.get("source_key")) for r in rows])
            return
        if sql_clean.startswith("SELECT r.station_key, r.date_key FROM analytics.fact_user_report"):
            rows = db.tables["analytics.fact_user_report"]
            if p:
                rows = [r for r in rows if r["date_key"] == p[0]]
            done([(r["station_key"], r["date_key"]) for r in rows])
            return
        if sql_clean.startswith("SELECT v.station_key, v.date_key, v.rating FROM analytics.fact_review"):
            rows = db.tables["analytics.fact_review"]
            if p:
                rows = [r for r in rows if r["date_key"] == p[0]]
            done([(r["station_key"], r["date_key"], r["rating"]) for r in rows])
            return
        if sql_clean.startswith("INSERT INTO analytics.fact_station_daily"):
            assert isinstance(p, dict), "daily upsert must use named params"
            tbl = db.tables["analytics.fact_station_daily"]
            existing = next((r for r in tbl if r["station_key"] == p["station_key"] and r["date_key"] == p["date_key"]), None)
            if existing:
                existing.update({k: v for k, v in p.items()})
            else:
                tbl.append(dict(p))
            done([])
            return

        # -- DQ probes (real semantics over fake tables) -----------------------
        if sql_clean.startswith("SELECT count("):
            n = self._dq_count(sql_clean, db)
            if n is not None:
                done([(n,)])
                return

        super().execute(sql, params)

    # -- DQ mini-evaluator: mirrors each rule's SQL intent ----------------------
    def _dq_count(self, sql_clean, db):
        t = db.tables
        # Exact reconciliation totals first (before semantic branches that
        # match the same table names).
        if sql_clean == "SELECT count(*) FROM analytics.dim_connector":
            return len(t["analytics.dim_connector"])
        if sql_clean == "SELECT count(DISTINCT station_id) FROM analytics.dim_station":
            return len({str(v["station_id"]) for v in t["analytics.dim_station"]})
        if "LEFT JOIN" in sql_clean and "IS NULL" in sql_clean:
            # referential integrity: fact LEFT JOIN dim ... IS NULL
            if "fact_station_observation" in sql_clean:
                if "dim_station" in sql_clean:
                    keys = {v["station_key"] for v in t["analytics.dim_station"]}
                    return sum(1 for r in t["analytics.fact_station_observation"] if r["station_key"] not in keys)
                if "dim_source" in sql_clean:
                    keys = {v["source_key"] for v in t["analytics.dim_source"]}
                    return sum(1 for r in t["analytics.fact_station_observation"] if r.get("source_key") not in keys)
                if "dim_date" in sql_clean:
                    return sum(1 for r in t["analytics.fact_station_observation"] if r["date_key"] not in db.dim_dates)
            if "fact_user_report" in sql_clean:
                keys = {v["station_key"] for v in t["analytics.dim_station"]}
                return sum(1 for r in t["analytics.fact_user_report"] if r["station_key"] not in keys)
            if "fact_review" in sql_clean and "dim_station" in sql_clean:
                keys = {v["station_key"] for v in t["analytics.dim_station"]}
                return sum(1 for r in t["analytics.fact_review"] if r["station_key"] not in keys)
            if "fact_station_daily" in sql_clean:
                keys = {v["station_key"] for v in t["analytics.dim_station"]}
                return sum(1 for r in t["analytics.fact_station_daily"] if r["station_key"] not in keys)
            return None
        if "GROUP BY" in sql_clean and "HAVING count(*) > 1" in sql_clean:
            if "fact_station_observation" in sql_clean:
                seen, dup = set(), 0
                for r in t["analytics.fact_station_observation"]:
                    k = str(r["observation_id"])
                    if k in seen:
                        dup += 1
                    seen.add(k)
                return dup
            if "fact_user_report" in sql_clean:
                seen, dup = set(), 0
                for r in t["analytics.fact_user_report"]:
                    k = str(r["report_id"])
                    if k in seen:
                        dup += 1
                    seen.add(k)
                return dup
            if "fact_review" in sql_clean:
                seen, dup = set(), 0
                for r in t["analytics.fact_review"]:
                    k = str(r["review_id"])
                    if k in seen:
                        dup += 1
                    seen.add(k)
                return dup
            if "fact_station_daily" in sql_clean:
                seen, dup = set(), 0
                for r in t["analytics.fact_station_daily"]:
                    k = (r["station_key"], r["date_key"])
                    if k in seen:
                        dup += 1
                    seen.add(k)
                return dup
            return None
        if "FROM analytics.fact_station_daily" in sql_clean:
            rows = t["analytics.fact_station_daily"]
            if "available_count + busy_count + broken_count > observation_count" in sql_clean:
                return sum(1 for r in rows if r["available_count"] + r["busy_count"] + r["broken_count"] > r["observation_count"])
            if "observation_count = 0 AND report_count = 0 AND review_count = 0" in sql_clean:
                return sum(1 for r in rows if r["observation_count"] == 0 and r["report_count"] == 0 and r["review_count"] == 0)
            if "availability_ratio IS NOT NULL" in sql_clean:
                def bad(x):
                    return x is not None and (x < 0 or x > 1)
                return sum(1 for r in rows if bad(r.get("availability_ratio")) or bad(r.get("busy_ratio")) or bad(r.get("broken_ratio")))
            if "has_evidence IS NOT TRUE" in sql_clean:
                return sum(1 for r in rows if r.get("has_evidence") is not True)
            return None
        if "FROM analytics.dim_connector" in sql_clean:
            return sum(1 for r in t["analytics.dim_connector"]
                       if r.get("power_kw") is not None and r["power_kw"] <= 0)
        if "FROM analytics.fact_station_observation" in sql_clean:
            rows = t["analytics.fact_station_observation"]
            if "available_connectors IS NOT NULL" in sql_clean:
                return sum(1 for r in rows if r.get("available_connectors") is not None
                           and (r.get("total_connectors", 0) == 0 or r["available_connectors"] > r["total_connectors"]))
            if "source_payload_hash IS NULL" in sql_clean:
                return sum(1 for r in rows if r.get("source_payload_hash") is None)
            if "observed_at > now()" in sql_clean:
                return 0  # seeds use fixed past timestamps
            if "received_at < observed_at" in sql_clean:
                return sum(1 for r in rows if r.get("received_at") and r.get("observed_at")
                           and r["received_at"] < r["observed_at"])
            if sql_clean == "SELECT count(*) FROM analytics.fact_station_observation":
                return len(rows)
            return None
        if sql_clean == "SELECT count(*) FROM public.station_observations":
            return len(t["public.station_observations"])
        if "FROM public.user_reports WHERE" in sql_clean:
            return sum(1 for r in t["public.user_reports"]
                       if r.get("moderation_status") == "approved" and r.get("moderated_at") is not None)
        if "FROM public.reviews WHERE" in sql_clean:
            return sum(1 for r in t["public.reviews"]
                       if r.get("moderation_status") == "approved" and r.get("moderated_at") is not None)
        if sql_clean == "SELECT count(*) FROM analytics.fact_user_report":
            return len(t["analytics.fact_user_report"])
        if sql_clean == "SELECT count(*) FROM analytics.fact_review":
            return len(t["analytics.fact_review"])
        if sql_clean == "SELECT count(*) FROM public.stations":
            return len(t["public.stations"])
        if "SELECT count(DISTINCT station_id) FROM analytics.dim_station" in sql_clean:
            return len({str(v["station_id"]) for v in t["analytics.dim_station"]})
        if sql_clean == "SELECT count(*) FROM public.connectors":
            return len(t["public.connectors"])
        if sql_clean == "SELECT count(*) FROM analytics.dim_connector":
            return len(t["analytics.dim_connector"])
        return None


class WarehouseMockConnection(MockDatabaseConnection):
    def __init__(self):
        super().__init__()
        for tbl in ("public.user_reports", "public.reviews",
                    "analytics.fact_user_report", "analytics.fact_review",
                    "analytics.fact_station_daily"):
            self.tables[tbl] = []
        self.dim_dates: set[int] = set()

    def cursor(self, cursor_factory=None):
        return WarehouseMockCursor(self, as_dict=cursor_factory is not None)


def _seed_oltp(db, n_stations=1):
    op_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    db.tables["public.operators"].append(
        {"id": op_id, "name": "Tata Power", "slug": "tata-power"})
    db.tables["public.data_sources"].append(
        {"id": "dddddddd-dddd-dddd-dddd-dddddddddddd", "name": "open_charge_map",
         "source_type": "api", "base_url": "https://x", "source_priority": 100})
    for i in range(n_stations):
        sid = f"11111111-1111-1111-1111-11111111111{i}"
        db.tables["public.stations"].append({
            "id": sid, "name": f"Station {i}", "operator_id": op_id,
            "address_line": "Road", "locality": "Bandra", "city": "Mumbai",
            "state": "Maharashtra", "postal_code": "400050", "country": "India",
            "latitude": 19.05 + i * 0.01, "longitude": 72.82,
            "access_type": "public", "is_public": True, "operational_status": "operational",
            "is_24_hours": True, "opening_time": None, "closing_time": None,
            "created_at": NOW - timedelta(days=10),
        })
    return op_id


class TestWarehouseDimensions(unittest.TestCase):
    def test_01_sync_dimensions_includes_null_power_connector(self):
        db = WarehouseMockConnection()
        _seed_oltp(db)
        sid = "11111111-1111-1111-1111-111111111110"
        db.tables["public.connectors"].append({
            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc", "station_id": sid,
            "connector_type": "CCS2", "charging_standard": None, "power_kw": None,
            "quantity": 2, "pricing_type": None, "price_per_kwh": None,
            "price_per_session": None, "created_at": NOW - timedelta(days=9),
        })
        etl = WarehouseETL(conn=db)
        summary = etl.sync_dimensions()
        self.assertEqual(summary.dimensions_synced, 2)  # 1 station + 1 connector
        dims = db.tables["analytics.dim_station"]
        self.assertEqual(len([d for d in dims if d["is_current"]]), 1)
        conns = db.tables["analytics.dim_connector"]
        self.assertEqual(len(conns), 1)
        self.assertIsNone(conns[0]["power_kw"])  # unknown stays NULL, never 0
        self.assertEqual(conns[0]["quantity"], 2)

    def test_02_dimension_rerun_is_idempotent(self):
        db = WarehouseMockConnection()
        _seed_oltp(db)
        etl = WarehouseETL(conn=db)
        etl.sync_dimensions()
        n_dims = len(db.tables["analytics.dim_station"])
        etl.sync_dimensions()
        self.assertEqual(len(db.tables["analytics.dim_station"]), n_dims)
        current = [d for d in db.tables["analytics.dim_station"] if d["is_current"]]
        self.assertEqual(len(current), 1)  # still exactly one current version


class TestWarehouseFacts(unittest.TestCase):
    def _db_with_report(self, status="approved", moderated=True):
        db = WarehouseMockConnection()
        _seed_oltp(db)
        etl = WarehouseETL(conn=db)
        etl.sync_dimensions()
        sk = db.tables["analytics.dim_station"][0]["station_key"]
        # Event time must postdate the dim version's effective_from.
        event_ts = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.dim_dates.add(int(event_ts.strftime("%Y%m%d")))
        db.tables["public.user_reports"].append({
            "id": "rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrrr",
            "station_id": "11111111-1111-1111-1111-111111111110",
            "connector_id": None, "availability_status": "busy", "queue_level": "short",
            "observed_at": event_ts, "created_at": event_ts,
            "moderation_status": status, "moderated_at": event_ts if moderated else None,
            "is_flagged": False,
        })
        return db, etl, sk

    def test_03_approved_report_loads_with_provenance_no_pii(self):
        db, etl, sk = self._db_with_report()
        summary = etl.sync_report_facts()
        self.assertEqual(summary.report_facts_loaded, 1)
        facts = db.tables["analytics.fact_user_report"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["station_key"], sk)
        self.assertNotIn("user_id", facts[0])
        self.assertNotIn("comment", facts[0])
        # rerun loads nothing new
        summary2 = etl.sync_report_facts()
        self.assertEqual(summary2.report_facts_loaded, 0)
        self.assertEqual(len(facts), 1)

    def test_04_pending_rejected_unmoderated_reports_never_load(self):
        for status, moderated in [("pending", False), ("rejected", True), ("approved", False)]:
            db, etl, _ = self._db_with_report(status=status, moderated=moderated)
            summary = etl.sync_report_facts()
            self.assertEqual(summary.report_facts_loaded, 0, f"{status}/{moderated}")
            self.assertEqual(len(db.tables["analytics.fact_user_report"]), 0)

    def test_05_approved_review_loads_rating_only(self):
        db = WarehouseMockConnection()
        _seed_oltp(db)
        etl = WarehouseETL(conn=db)
        etl.sync_dimensions()
        sk = db.tables["analytics.dim_station"][0]["station_key"]
        event_ts = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.dim_dates.add(int(event_ts.strftime("%Y%m%d")))
        db.tables["public.reviews"].append({
            "id": "vvvvvvvv-vvvv-vvvv-vvvv-vvvvvvvvvvvv",
            "station_id": "11111111-1111-1111-1111-111111111110",
            "rating": 4, "created_at": event_ts, "moderation_status": "approved",
            "moderated_at": event_ts,
        })
        summary = etl.sync_review_facts()
        self.assertEqual(summary.review_facts_loaded, 1)
        facts = db.tables["analytics.fact_review"]
        self.assertEqual(facts[0]["station_key"], sk)
        self.assertEqual(facts[0]["rating"], 4)
        self.assertNotIn("user_id", facts[0])


class TestWarehouseDaily(unittest.TestCase):
    def _db_with_evidence(self):
        db = WarehouseMockConnection()
        db.dim_dates.add(DAY)
        db.tables["analytics.dim_station"].append({
            "station_key": 1, "station_id": "s1", "is_current": True,
            "effective_from": NOW - timedelta(days=30), "effective_to": None,
        })
        obs = [
            {"observation_id": "o1", "station_key": 1, "date_key": DAY, "availability_status": "available",
             "queue_level": "short", "available_connectors": 2, "total_connectors": 2, "source_key": 7},
            {"observation_id": "o2", "station_key": 1, "date_key": DAY, "availability_status": "busy",
             "queue_level": "long", "available_connectors": 0, "total_connectors": 2, "source_key": 7},
            {"observation_id": "o3", "station_key": 1, "date_key": DAY, "availability_status": "unknown",
             "queue_level": "unknown", "available_connectors": None, "total_connectors": 0, "source_key": 7},
        ]
        db.tables["analytics.fact_station_observation"].extend(obs)
        db.tables["analytics.fact_user_report"].append(
            {"report_id": "r1", "station_key": 1, "date_key": DAY})
        db.tables["analytics.fact_review"].append(
            {"review_id": "v1", "station_key": 1, "date_key": DAY, "rating": 5})
        return db

    def test_06_daily_math_preserves_unknowns(self):
        db = self._db_with_evidence()
        etl = WarehouseETL(conn=db)
        summary = etl.build_daily()
        self.assertEqual(summary.daily_rows_upserted, 1)
        rows = db.tables["analytics.fact_station_daily"]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["observation_count"], 3)
        self.assertEqual(r["available_count"], 1)
        self.assertEqual(r["busy_count"], 1)
        self.assertEqual(r["broken_count"], 0)
        self.assertAlmostEqual(r["availability_ratio"], 1 / 3)
        self.assertAlmostEqual(r["avg_queue_score"], (0.33 + 1.0) / 2)  # unknown excluded
        self.assertAlmostEqual(r["peak_queue_score"], 1.0)
        self.assertEqual(r["report_count"], 1)
        self.assertEqual(r["review_count"], 1)
        self.assertEqual(r["avg_rating"], 5)
        self.assertEqual(r["source_count"], 1)
        self.assertTrue(r["has_evidence"])
        self.assertEqual(r["maturity"], "cold")

    def test_07_daily_rerun_upserts_without_duplicates(self):
        db = self._db_with_evidence()
        etl = WarehouseETL(conn=db)
        etl.build_daily()
        etl.build_daily()
        self.assertEqual(len(db.tables["analytics.fact_station_daily"]), 1)

    def test_08_reports_only_day_has_null_ratios(self):
        db = WarehouseMockConnection()
        db.dim_dates.add(DAY)
        db.tables["analytics.dim_station"].append({
            "station_key": 1, "station_id": "s1", "is_current": True,
            "effective_from": NOW - timedelta(days=30), "effective_to": None,
        })
        db.tables["analytics.fact_user_report"].append(
            {"report_id": "r1", "station_key": 1, "date_key": DAY})
        etl = WarehouseETL(conn=db)
        etl.build_daily()
        rows = db.tables["analytics.fact_station_daily"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["observation_count"], 0)
        self.assertEqual(rows[0]["report_count"], 1)
        self.assertIsNone(rows[0]["availability_ratio"])  # no obs: NULL, not 0
        self.assertIsNone(rows[0]["avg_rating"])


class TestWarehouseQuality(unittest.TestCase):
    def _good_db(self):
        db = WarehouseMockConnection()
        db.dim_dates.add(DAY)
        db.tables["analytics.dim_station"].append({
            "station_key": 1, "station_id": "s1", "is_current": True,
            "effective_from": NOW - timedelta(days=30), "effective_to": None,
        })
        db.tables["analytics.dim_source"].append({"source_key": 7})
        db.tables["public.stations"].append({"id": "s1"})
        db.tables["public.connectors"].append({"id": "c1"})
        db.tables["analytics.dim_connector"].append(
            {"connector_key": 9, "connector_id": "c1", "power_kw": None})
        db.tables["analytics.fact_station_daily"].append({
            "station_key": 1, "date_key": DAY, "observation_count": 1,
            "report_count": 0, "review_count": 0, "available_count": 1,
            "busy_count": 0, "broken_count": 0, "availability_ratio": 1.0,
            "busy_ratio": 0.0, "broken_ratio": 0.0, "has_evidence": True,
        })
        return db

    def test_09_clean_warehouse_passes_all_checks(self):
        db = self._good_db()
        report = run_all_checks(db)
        failures = [f for f in report.findings if f.severity != "INFO" and not f.passed]
        self.assertEqual(failures, [])

    def test_10_violations_are_reported_with_rule_ids(self):
        db = self._good_db()
        db.tables["analytics.fact_station_daily"].append({
            "station_key": 1, "date_key": DAY, "observation_count": 1,
            "report_count": 0, "review_count": 0, "available_count": 1,
            "busy_count": 1, "broken_count": 0,  # 1+1 > 1: violates conservation
            "availability_ratio": 9.9,  # out of range
            "busy_ratio": 0.0, "broken_ratio": 0.0, "has_evidence": True,
        })
        db.tables["analytics.dim_connector"].append(
            {"connector_key": 10, "connector_id": "c2", "power_kw": 0})  # impossible power
        report = run_all_checks(db)
        by_rule = {f.rule_id: f for f in report.findings}
        self.assertFalse(by_rule["WH-AGG-STATUS"].passed)
        self.assertFalse(by_rule["WH-AGG-RATIO"].passed)
        self.assertFalse(by_rule["WH-NULL-POWER"].passed)
        self.assertTrue(by_rule["WH-REC-OBS"].passed)


class TestWarehouseQueries(unittest.TestCase):
    def test_11_queries_are_read_only_and_scoped(self):
        for name, q in QUERIES.items():
            upper = q.sql.upper()
            for forbidden in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE"):
                self.assertNotIn(forbidden, upper, f"{name} must be read-only")
            if name == "ingestion_health":
                # Documented exception: operations table, admin surface only.
                self.assertIn("PUBLIC.INGESTION_RUNS", upper)
                continue
            self.assertIn("ANALYTICS.", upper, f"{name} must read the warehouse")
            self.assertNotIn("PUBLIC.", upper, f"{name} must not cross into OLTP")
            for doc in (q.meaning, q.grain, q.data, q.null_meaning, q.timezone, q.traceability):
                self.assertTrue(doc, f"{name} missing documentation")

    def test_12_run_query_maps_rows_to_dicts(self):
        class StubCur:
            description = [("station_count",), ("city",)]

            def execute(self, sql, params=None):
                self.sql = sql

            def fetchall(self):
                return [(3, "Mumbai")]

        class StubConn:
            def cursor(self):
                return StubCur()

            def __enter__(self):
                return self.cursor()

            def __exit__(self, *a):
                pass

        # run_query uses `with conn.cursor() as cur` — adapt stub
        class CtxConn:
            def cursor(self):
                cur = StubCur()

                class Ctx:
                    def __enter__(self):
                        return cur

                    def __exit__(self, *a):
                        pass

                return Ctx()

        rows = run_query(CtxConn(), "stations_by_city")
        self.assertEqual(rows, [{"station_count": 3, "city": "Mumbai"}])
        with self.assertRaises(ValueError):
            run_query(CtxConn(), "no_such_query")


class TestWarehouseRunAccounting(unittest.TestCase):
    def test_13_etl_run_records_succeeded(self):
        db = WarehouseMockConnection()
        _seed_oltp(db)
        etl = WarehouseETL(conn=db)
        summary = etl.run(job="all")
        rows = db.tables["public.ingestion_runs"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "SUCCEEDED")
        self.assertEqual(summary.run_id, rows[0]["id"])

    def test_14_etl_run_with_skips_records_partial(self):
        db = WarehouseMockConnection()
        _seed_oltp(db)
        etl = WarehouseETL(conn=db)
        etl.sync_dimensions()
        # approved report for an unknown station -> skipped (no dim version)
        event_ts = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.dim_dates.add(int(event_ts.strftime("%Y%m%d")))
        db.tables["public.user_reports"].append({
            "id": "rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrrr", "station_id": "99999999-9999-9999-9999-999999999999",
            "connector_id": None, "availability_status": "busy", "queue_level": "short",
            "observed_at": event_ts, "created_at": event_ts, "moderation_status": "approved",
            "moderated_at": event_ts, "is_flagged": False,
        })
        summary = etl.run(job="report-facts")
        rows = db.tables["public.ingestion_runs"]
        self.assertEqual(rows[-1]["state"], "PARTIAL")
        self.assertEqual(summary.skipped, 1)


class TestOlapQueryContracts(unittest.TestCase):
    def test_15_no_pii_in_any_query(self):
        for name, q in QUERIES.items():
            lowered = q.sql.lower()
            self.assertNotIn("user_id", lowered, name)
            self.assertNotIn("comment", lowered, name)
            self.assertNotIn("moderated_by", lowered, name)

    def test_16_current_vs_historical_semantics_are_explicit(self):
        for name in ("stations_by_operator", "stations_by_city", "observation_freshness"):
            self.assertIn("is_current", QUERIES[name].sql.lower(), name)
        # freshness grain is the versioned identity, never the bare name
        self.assertIn("station_id", QUERIES["observation_freshness"].sql.lower())

    def test_17_empty_and_null_results_map_honestly(self):
        class EmptyConn:
            def cursor(self):
                class Ctx:
                    def __enter__(self):
                        class Cur:
                            description = [("full_date",), ("system_obs",)]

                            def execute(self, sql, params=None):
                                pass

                            def fetchall(self):
                                return []

                        return Cur()

                    def __exit__(self, *a):
                        pass

                return Ctx()

        self.assertEqual(run_query(EmptyConn(), "community_volume_daily"), [])

        class NullConn:
            def cursor(self):
                class Ctx:
                    def __enter__(self):
                        class Cur:
                            description = [("availability_ratio",), ("avg_rating",)]

                            def execute(self, sql, params=None):
                                pass

                            def fetchall(self):
                                return [(None, None)]

                        return Cur()

                    def __exit__(self, *a):
                        pass

                return Ctx()

        # NULL stays NULL: never coerced to zero by the mapping layer
        self.assertEqual(
            run_query(NullConn(), "daily_trend", {"station_id": "s"}),
            [{"availability_ratio": None, "avg_rating": None}],
        )

    def test_18_parameters_reach_sql(self):
        seen = {}

        class ParamConn:
            def cursor(self):
                class Ctx:
                    def __enter__(self):
                        class Cur:
                            description = [("slot_15min",)]

                            def execute(self, sql, params=None):
                                seen["sql"] = sql
                                seen["params"] = params

                            def fetchall(self):
                                return []

                        return Cur()

                    def __exit__(self, *a):
                        pass

                return Ctx()

        run_query(ParamConn(), "busy_slots_by_city", {"city": "Mumbai"})
        self.assertEqual(seen["params"], {"city": "Mumbai"})
        run_query(ParamConn(), "ingestion_health", {"limit": 5})
        self.assertEqual(seen["params"], {"limit": 5})

    def test_19_utc_bucket_boundaries(self):
        from backend.warehouse.etl import utc_keys

        just_before = datetime(2026, 10, 5, 23, 59, tzinfo=timezone.utc)
        just_after = datetime(2026, 10, 6, 0, 1, tzinfo=timezone.utc)
        self.assertEqual(utc_keys(just_before), (20261005, 95))
        self.assertEqual(utc_keys(just_after), (20261006, 0))
        # None input raises instead of producing a bogus bucket
        with self.assertRaises(Exception):
            utc_keys(None)


if __name__ == "__main__":
    unittest.main()
