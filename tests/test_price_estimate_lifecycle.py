"""ChargePlus — Pricing-estimate lifecycle offline regression tests (contract 1.1.0).

Covers the full operational lifecycle of the three unverified-estimate fields
(price_estimate_per_kwh / _raw / _source) without any database connection:

  A. Insert a valid OCM estimate (verified fields untouched, warehouse clean).
  B. Refresh a valid OCM estimate (replace, verified untouched).
  C. Clear an obsolete OCM estimate (all three fields, no stale/new pairing).
  D. Preserve an estimate on unrelated updates with no new pricing.
  E. Verified tariff supersedes a stale estimate.
  F. Explicit FREE status supersedes a stale paid estimate.
  G. Warehouse isolation (estimates never mirrored).

The purpose-built fake below exercises the real production SQL-building path
(IngestionPersistenceService._reconcile_and_persist_connectors) and transcribes
the production UPDATE CASE branch-for-branch. A static test pins the SQL branch
structure so any production drift fails loudly instead of silently diverging
from the fake. No live services or databases are contacted.
"""

from __future__ import annotations

import inspect
import unittest
import uuid
from pathlib import Path

from backend.ingestion.constants import PricingType
from backend.ingestion.contracts import NormalizedConnectorRecord, NormalizedStationRecord
from backend.ingestion.deduplication import CanonicalDecisionState, CanonicalResolutionDecision
from backend.ingestion.persistence import IngestionPersistenceService

OCM_SOURCE = "ocm_usage_cost"


class LifecycleFakeCursor:
    """Minimal offline cursor modelling only the connector reconcile path.

    Handles exactly the statements issued by
    _reconcile_and_persist_connectors + _sync_dim_connector:
      - SELECT existing connector capacity groups (8 columns, production order)
      - INSERT INTO public.connectors (12 params, production order)
      - UPDATE public.connectors (23 params, production order)
      - INSERT INTO analytics.dim_connector (captured for warehouse assertions)
    """

    def __init__(self, store: dict):
        self.store = store
        self._last: list = []

    def execute(self, sql: str, params: tuple = ()):
        sql_clean = " ".join(sql.strip().split())
        self._last = []

        if sql_clean.startswith("SELECT") and "FROM public.connectors" in sql_clean:
            stn_id = str(params[0])
            for c in self.store["connectors"]:
                if str(c["station_id"]) == stn_id:
                    self._last.append((
                        c["id"], c["connector_type"], c.get("power_kw"),
                        c.get("charging_standard"), c.get("quantity"),
                        c.get("pricing_type"), c.get("price_per_kwh"),
                        c.get("price_per_session"),
                    ))
        elif sql_clean.startswith("INSERT INTO public.connectors"):
            # Production order: id, station_id, type, standard, power, qty,
            # pricing_type, price_per_kwh, price_per_session, est, raw, src.
            assert len(params) == 12, f"expected 12 INSERT params, got {len(params)}"
            (cid, stn_id, ctype, std, pkw, qty, p_type, p_kwh, p_sess,
             est, raw, src) = params
            self.store["connectors"].append({
                "id": str(cid), "station_id": str(stn_id), "connector_type": ctype,
                "charging_standard": std, "power_kw": pkw, "quantity": qty,
                "pricing_type": p_type, "price_per_kwh": p_kwh,
                "price_per_session": p_sess,
                "price_estimate_per_kwh": est, "price_estimate_raw": raw,
                "price_estimate_source": src,
            })
        elif sql_clean.startswith("UPDATE public.connectors"):
            # Production order: qty, ptype, pkwh, psess, then per estimate
            # column (verified_kwh, pricing_str, est_src, est_val, incoming,
            # est_src), then row id. Transcribes the production CASE branches:
            #   1. verified tariff or explicit FREE  -> clear all three
            #   2. OCM source + parseable estimate   -> store incoming triple
            #   3. OCM source without estimate       -> clear all three
            #   4. otherwise                         -> preserve existing
            assert len(params) == 23, f"expected 23 UPDATE params, got {len(params)}"
            new_qty, p_type, p_kwh, p_sess = params[0], params[1], params[2], params[3]
            conn_id = str(params[-1])
            v_kwh, p_str = params[4], params[5]
            p_str_val = p_str.value if hasattr(p_str, "value") else p_str
            e_src, e_val = params[6], params[7]
            for c in self.store["connectors"]:
                if str(c["id"]) != conn_id:
                    continue
                c["quantity"] = new_qty
                if p_type is not None:
                    c["pricing_type"] = p_type
                if p_kwh is not None:
                    c["price_per_kwh"] = p_kwh
                if p_sess is not None:
                    c["price_per_session"] = p_sess
                if v_kwh is not None or p_str_val == "free":
                    c["price_estimate_per_kwh"] = None
                    c["price_estimate_raw"] = None
                    c["price_estimate_source"] = None
                elif e_src == OCM_SOURCE and e_val is not None:
                    # Incoming positions mirror the production tuple layout:
                    # value at 8, raw at 14, source at 20.
                    c["price_estimate_per_kwh"] = params[8]
                    c["price_estimate_raw"] = params[14]
                    c["price_estimate_source"] = params[20]
                elif e_src == OCM_SOURCE:
                    c["price_estimate_per_kwh"] = None
                    c["price_estimate_raw"] = None
                    c["price_estimate_source"] = None
                # else: preserve existing estimate fields
                break
        elif "INSERT INTO analytics.dim_connector" in sql_clean:
            self.store["dim_connector"].append(tuple(params))
        else:  # pragma: no cover - reconcile path issues no other statements
            raise AssertionError(f"unexpected statement in lifecycle fake: {sql_clean[:80]}")

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class LifecycleFakeConnection:
    """Offline connection backing the lifecycle fake (zero writes elsewhere)."""

    def __init__(self):
        self.store: dict = {"connectors": [], "dim_connector": []}
        self.closed = False
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return LifecycleFakeCursor(self.store)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _connector(
    pricing_type=PricingType.UNKNOWN,
    price_per_kwh=None,
    price_per_session=None,
    est=None,
    est_raw=None,
    est_src=None,
    power_kw=60.0,
    ctype="CCS2",
) -> NormalizedConnectorRecord:
    return NormalizedConnectorRecord(
        connector_type=ctype,
        raw_connector_type=ctype,
        power_kw=power_kw,
        pricing_type=pricing_type,
        price_per_kwh=price_per_kwh,
        price_per_session=price_per_session,
        price_estimate_per_kwh=est,
        price_estimate_raw=est_raw,
        price_estimate_source=est_src,
    )


def _ocm_estimate_connector(est=18.50, raw="₹18.50 per kWh + GST") -> NormalizedConnectorRecord:
    """Connector as normalize_station_record produces it for valid OCM UsageCost."""
    return _connector(
        pricing_type=PricingType.PAID, est=est, est_raw=raw, est_src=OCM_SOURCE,
    )


def _station(conn: NormalizedConnectorRecord, source_id="open_charge_map") -> NormalizedStationRecord:
    return NormalizedStationRecord(
        source_id=source_id,
        source_station_id="lifecycle-1",
        name="Lifecycle Station",
        latitude=19.05,
        longitude=72.85,
        connectors=[conn],
    )


def _decision(station: NormalizedStationRecord) -> CanonicalResolutionDecision:
    return CanonicalResolutionDecision(
        decision_state=CanonicalDecisionState.KEEP_SEPARATE,
        cluster_id="cluster-lifecycle",
        participating_records=[station],
    )


def _reconcile(conn: LifecycleFakeConnection, station_id: uuid.UUID,
               station: NormalizedStationRecord):
    service = IngestionPersistenceService(conn)
    warnings: list[str] = []
    with conn.cursor() as cur:
        result = service._reconcile_and_persist_connectors(
            cur, station_id, _decision(station), warnings,
        )
    return result


class TestPriceEstimateLifecycle(unittest.TestCase):
    def setUp(self):
        self.conn = LifecycleFakeConnection()
        self.station_id = uuid.uuid4()

    def _seed(self, est=18.50, raw="₹18.50 per kWh + GST", src=OCM_SOURCE,
              pricing_type="paid", price_per_kwh=None):
        row_id = str(uuid.uuid4())
        self.conn.store["connectors"].append({
            "id": row_id, "station_id": str(self.station_id),
            "connector_type": "CCS2", "charging_standard": None,
            "power_kw": 60.0, "quantity": 1,
            "pricing_type": pricing_type, "price_per_kwh": price_per_kwh,
            "price_per_session": None,
            "price_estimate_per_kwh": est, "price_estimate_raw": raw,
            "price_estimate_source": src,
        })
        return row_id

    def _row(self):
        self.assertEqual(len(self.conn.store["connectors"]), 1)
        return self.conn.store["connectors"][0]

    # A. Insert a valid estimate -------------------------------------------
    def test_a_insert_valid_estimate(self):
        _reconcile(self.conn, self.station_id, _station(_ocm_estimate_connector()))
        row = self._row()
        self.assertEqual(row["price_estimate_per_kwh"], 18.50)
        self.assertEqual(row["price_estimate_raw"], "₹18.50 per kWh + GST")
        self.assertEqual(row["price_estimate_source"], OCM_SOURCE)
        # Verified tariff fields are not populated from the estimate.
        self.assertIsNone(row["price_per_kwh"])
        self.assertIsNone(row["price_per_session"])

    def test_a_invalid_ocm_text_inserts_no_estimate(self):
        # Normalization output for unparseable OCM text: (None, raw, ocm).
        conn = _connector(pricing_type=PricingType.PAID, est=None,
                          est_raw="Contact operator", est_src=OCM_SOURCE)
        _reconcile(self.conn, self.station_id, _station(conn))
        row = self._row()
        self.assertIsNone(row["price_estimate_per_kwh"])
        self.assertIsNone(row["price_estimate_raw"])
        self.assertIsNone(row["price_estimate_source"])

    # B. Refresh a valid estimate -------------------------------------------
    def test_b_refresh_replaces_estimate(self):
        self._seed(est=18.50, raw="₹18.50 per kWh + GST")
        _reconcile(self.conn, self.station_id,
                   _station(_ocm_estimate_connector(est=25.00, raw="Rs. 25 per kWh")))
        row = self._row()
        self.assertEqual(row["price_estimate_per_kwh"], 25.00)
        self.assertEqual(row["price_estimate_raw"], "Rs. 25 per kWh")
        self.assertEqual(row["price_estimate_source"], OCM_SOURCE)
        self.assertIsNone(row["price_per_kwh"])

    # C. Clear an obsolete estimate ------------------------------------------
    def test_c_ocm_refresh_without_estimate_clears_all_three_fields(self):
        self._seed(est=18.50, raw="₹18.50 per kWh + GST")
        conn = _connector(pricing_type=PricingType.PAID, est=None,
                          est_raw="Contact operator", est_src=OCM_SOURCE)
        _reconcile(self.conn, self.station_id, _station(conn))
        row = self._row()
        self.assertIsNone(row["price_estimate_per_kwh"])
        # A failed parse must not leave an old numeric paired with new raw
        # text, nor retain a stale provenance marker without an estimate.
        self.assertIsNone(row["price_estimate_raw"])
        self.assertIsNone(row["price_estimate_source"])

    def test_c_missing_usage_cost_clears_all_three_fields(self):
        self._seed(est=18.50, raw="₹18.50 per kWh + GST")
        conn = _connector(pricing_type=PricingType.UNKNOWN, est=None,
                          est_raw=None, est_src=OCM_SOURCE)
        _reconcile(self.conn, self.station_id, _station(conn))
        row = self._row()
        self.assertIsNone(row["price_estimate_per_kwh"])
        self.assertIsNone(row["price_estimate_raw"])
        self.assertIsNone(row["price_estimate_source"])

    # D. Preserve estimate on unrelated updates -------------------------------
    def test_d_unrelated_update_without_pricing_preserves_estimate(self):
        self._seed(est=18.50, raw="₹18.50 per kWh + GST")
        conn = _connector()  # UNKNOWN pricing, no prices, no estimates
        _reconcile(self.conn, self.station_id, _station(conn, source_id="other_source"))
        row = self._row()
        self.assertEqual(row["price_estimate_per_kwh"], 18.50)
        self.assertEqual(row["price_estimate_raw"], "₹18.50 per kWh + GST")
        self.assertEqual(row["price_estimate_source"], OCM_SOURCE)

    def test_d_null_verified_price_alone_does_not_clear(self):
        # An update carrying only a session fee (no per-kWh tariff) preserves.
        self._seed(est=18.50, raw="₹18.50 per kWh + GST")
        conn = _connector(pricing_type=PricingType.PAID, price_per_session=50.0)
        _reconcile(self.conn, self.station_id, _station(conn, source_id="other_source"))
        row = self._row()
        self.assertEqual(row["price_estimate_per_kwh"], 18.50)
        self.assertEqual(row["price_estimate_source"], OCM_SOURCE)

    # E. Verified tariff supersedes -------------------------------------------
    def test_e_verified_tariff_supersedes_stale_estimate(self):
        self._seed(est=18.50, raw="₹18.50 per kWh + GST")
        conn = _connector(pricing_type=PricingType.PAID, price_per_kwh=22.00)
        _reconcile(self.conn, self.station_id, _station(conn, source_id="other_source"))
        row = self._row()
        self.assertEqual(row["price_per_kwh"], 22.00)
        self.assertIsNone(row["price_estimate_per_kwh"])
        self.assertIsNone(row["price_estimate_raw"])
        self.assertIsNone(row["price_estimate_source"])

    # F. Explicit FREE supersedes ------------------------------------------------
    def test_f_free_status_supersedes_stale_paid_estimate(self):
        self._seed(est=18.50, raw="₹18.50 per kWh + GST")
        # Established explicit-free representation: FREE + 0.0 tariff.
        conn = _connector(pricing_type=PricingType.FREE, price_per_kwh=0.0)
        _reconcile(self.conn, self.station_id, _station(conn, source_id="other_source"))
        row = self._row()
        self.assertEqual(row["pricing_type"], PricingType.FREE)
        self.assertEqual(row["price_per_kwh"], 0.0)
        self.assertIsNone(row["price_estimate_per_kwh"])
        self.assertIsNone(row["price_estimate_raw"])
        self.assertIsNone(row["price_estimate_source"])

    def test_f_free_without_price_also_supersedes(self):
        self._seed(est=18.50, raw="₹18.50 per kWh + GST")
        conn = _connector(pricing_type=PricingType.FREE)
        _reconcile(self.conn, self.station_id, _station(conn, source_id="other_source"))
        row = self._row()
        self.assertIsNone(row["price_estimate_per_kwh"])
        self.assertIsNone(row["price_estimate_raw"])
        self.assertIsNone(row["price_estimate_source"])

    # G. Warehouse isolation ----------------------------------------------------
    def test_g_warehouse_mirror_receives_verified_pricing_only(self):
        _reconcile(self.conn, self.station_id, _station(_ocm_estimate_connector()))
        self.assertEqual(len(self.conn.store["dim_connector"]), 1)
        mirrored = self.conn.store["dim_connector"][0]
        # Production _sync_dim_connector binds exactly 10 verified-only params.
        self.assertEqual(len(mirrored), 10)
        self.assertNotIn(18.50, mirrored)
        self.assertNotIn("₹18.50 per kWh + GST", mirrored)
        self.assertNotIn(OCM_SOURCE, mirrored)

    def test_g_warehouse_mirror_source_has_no_estimate_references(self):
        source = inspect.getsource(IngestionPersistenceService._sync_dim_connector)
        self.assertNotIn("price_estimate", source)


class TestEstimateUpdateSqlContract(unittest.TestCase):
    """Static pins for the production UPDATE branch structure.

    The lifecycle fake transcribes these branches; if production drifts, the
    param-count assertion in the fake fires. These invariants additionally pin
    branch order: verified/FREE supersede wins over OCM store, OCM store wins
    over OCM clear, and preservation is the final ELSE.
    """

    def test_update_case_branch_structure_and_order(self):
        source = inspect.getsource(
            IngestionPersistenceService._reconcile_and_persist_connectors)
        supersede = "WHEN %s IS NOT NULL OR %s = 'free' THEN NULL"
        ocm_store = "WHEN %s = 'ocm_usage_cost' AND %s IS NOT NULL THEN %s"
        ocm_clear = "WHEN %s = 'ocm_usage_cost' THEN NULL"
        for col in ("price_estimate_per_kwh", "price_estimate_raw", "price_estimate_source"):
            self.assertIn(col, source)
        self.assertEqual(source.count(supersede), 3)
        self.assertEqual(source.count(ocm_store), 3)
        self.assertEqual(source.count(ocm_clear), 3)
        self.assertLess(source.index(supersede), source.index(ocm_store))
        self.assertLess(source.index(ocm_store), source.index(ocm_clear))
        self.assertLess(source.index(ocm_clear), source.index("ELSE price_estimate_per_kwh"))


class TestPriceEstimateMigrationStatic(unittest.TestCase):
    """Offline static checks for the additive step_7_1 migration (not executed)."""

    @classmethod
    def setUpClass(cls):
        path = (Path(__file__).resolve().parent.parent / "supabase" / "migrations"
                / "20261013000001_step_7_1_connector_price_estimate.sql")
        cls.sql = path.read_text(encoding="utf-8")

    def test_additive_nullable_columns(self):
        for col in ("price_estimate_per_kwh", "price_estimate_raw", "price_estimate_source"):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {col}", self.sql)
        # No NOT NULL constraint on the added columns (pre-existing view SQL
        # may contain IS NOT NULL predicates; scope the check to ADD COLUMN).
        for line in self.sql.splitlines():
            if "ADD COLUMN" in line:
                self.assertNotIn("NOT NULL", line)

    def test_checks_align_with_contract_and_parser(self):
        # Parser/contract cap: 0 < estimate <= 500; raw <= 500 chars.
        self.assertIn("price_estimate_per_kwh > 0", self.sql)
        self.assertIn("price_estimate_per_kwh <= 500", self.sql)
        self.assertIn("char_length(price_estimate_raw) <= 500", self.sql)
        self.assertIn("price_estimate_source IN ('ocm_usage_cost')", self.sql)

    def test_verified_tariffs_untouched_and_warehouse_excluded(self):
        import re
        code = re.sub(r"--[^\n]*", " ", self.sql)  # ignore header documentation
        self.assertNotIn("price_per_kwh =", code)
        self.assertNotIn("dim_connector", code)

    def test_view_appends_compatibly_and_grants_preserved(self):
        for col in ("price_per_kwh", "price_per_session", "currency",
                    "price_estimate_per_kwh", "price_estimate_raw", "price_estimate_source"):
            self.assertIn(col, self.sql)
        # New estimate columns are appended after existing view columns.
        self.assertLess(self.sql.index("c.currency"), self.sql.index("c.price_estimate_per_kwh"))
        self.assertIn("security_invoker = true", self.sql)
        self.assertIn("REVOKE ALL ON public.v_station_connectors FROM PUBLIC", self.sql)
        self.assertIn("GRANT SELECT ON public.v_station_connectors TO anon, authenticated, service_role",
                      self.sql)


if __name__ == "__main__":
    unittest.main()
