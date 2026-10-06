"""ChargePlus — Step 5.1 maturity measurement tests.

Pure-logic tests use fixtures; SQL wiring tests use a strict scripted
fake (unmatched statements raise, so vacuous passes are impossible).
Fixtures never leave this file.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.warehouse.maturity import (
    build_report,
    classify_station,
    gap_stats,
    pct,
    split_feasible,
    station_maturity,
    target_assessment,
    temporal_profile,
)


class FakeCur:
    """Scripted cursor: first substring match wins, else raises."""

    def __init__(self, mapping: list[tuple[str, list]]):
        self.mapping = mapping
        self.seen: list[str] = []

    def execute(self, sql: str, params=()):
        cleaned = " ".join(sql.strip().split())
        self.seen.append(cleaned)
        for substr, rows in self.mapping:
            if substr in cleaned:
                self._rows = list(rows)
                return
        raise AssertionError(f"unmocked SQL: {cleaned[:120]}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, mapping):
        self.mapping = mapping

    def cursor(self):
        cur = FakeCur(self.mapping)

        class Ctx:
            def __enter__(self_inner):
                return cur

            def __exit__(self_inner, *a):
                pass

        return Ctx()


def empty_mapping() -> list[tuple[str, list]]:
    # NOTE: first substring match wins; structural patterns come first.
    return [
        ("SELECT min(", [(None, None)]),
        ("SELECT DISTINCT", []),
        ("GROUP BY station_id", []),
        ("GROUP BY 1, 2", []),
        ("GROUP BY 1", []),
        ("WHERE availability_status <> 'unknown'", [(0,)]),
        ("queue_level NOT IN", [(0,)]),
        ("public.favorites", [(0,)]),
        ("public.user_reports", [(0,)]),
        ("public.reviews", [(0,)]),
        ("public.connectors", [(0,)]),
        ("public.station_observations", [(0,)]),
        ("public.stations", [(0,)]),
        ("public.ingestion_runs", [(0,)]),
        ("public.data_sources", []),
        ("public.alerts", [(0,)]),
        ("analytics.", [(0,)]),
    ]


class TestGapStats(unittest.TestCase):
    def test_01_empty_and_single_are_unknown(self):
        g = gap_stats([])
        self.assertEqual(g["distinct_dates"], 0)
        self.assertIsNone(g["max_gap_days"])
        g1 = gap_stats(["2026-10-01"])
        self.assertEqual(g1["distinct_dates"], 1)
        self.assertIsNone(g1["median_gap_days"])

    def test_02_regular_irregular_sparse(self):
        self.assertEqual(gap_stats(["2026-10-01", "2026-10-02", "2026-10-03"])["regularity"], "regular")
        self.assertEqual(gap_stats(["2026-10-01", "2026-10-05", "2026-10-09"])["regularity"], "irregular")
        g = gap_stats(["2026-10-01", "2026-11-15"])
        self.assertEqual(g["regularity"], "sparse")
        self.assertEqual(g["max_gap_days"], 45)


class TestClassification(unittest.TestCase):
    def test_03_gate_boundaries(self):
        self.assertEqual(classify_station(0, 0), "COLD")
        self.assertEqual(classify_station(6, 500), "COLD")
        self.assertEqual(classify_station(7, 0), "WARMING")
        self.assertEqual(classify_station(30, 199), "WARMING")
        self.assertEqual(classify_station(30, 200), "READY")

    def test_04_split_feasibility(self):
        self.assertFalse(split_feasible(0, 0)["feasible"])
        self.assertFalse(split_feasible(29, 14)["feasible"])
        self.assertFalse(split_feasible(30, 13)["feasible"])
        self.assertTrue(split_feasible(30, 14)["feasible"])

    def test_05_pct_unknown_denominator(self):
        self.assertIsNone(pct(0, 0))
        self.assertEqual(pct(1, 4), 25.0)


class TestEmptyWarehouse(unittest.TestCase):
    def test_06_zero_evidence_profile(self):
        cur = FakeCur(empty_mapping())
        p = temporal_profile(cur, "public.station_observations", "observed_at")
        self.assertEqual(p["count"], 0)
        self.assertIsNone(p["earliest"])
        self.assertEqual(p["regularity"], "no evidence")

    def test_07_empty_maturity_is_cold(self):
        cur = FakeCur(empty_mapping())
        m = station_maturity(cur)
        self.assertEqual(m["overall"], "COLD")
        self.assertEqual(m["per_station"], {"COLD": 0, "WARMING": 0, "READY": 0})

    def test_08_empty_targets_not_trainable(self):
        cur = FakeCur(empty_mapping())
        for t in target_assessment(cur):
            self.assertFalse(t["trainable_now"], t["task"])

    def test_09_full_report_on_empty_is_cold_and_deterministic(self):
        r1 = build_report(FakeConn(empty_mapping()))
        r2 = build_report(FakeConn(empty_mapping()))
        self.assertEqual(r1["maturity"]["overall"], "COLD")
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)  # deterministic apart from the timestamp
        states = {c["capability"]: c["state"] for c in r1["capabilities"]}
        self.assertEqual(states["descriptive analytics"], "AVAILABLE NOW")
        self.assertEqual(states["availability forecasting"], "NOT TRAINABLE")
        self.assertEqual(states["demand forecasting"], "NOT AVAILABLE")


class TestRichFixtures(unittest.TestCase):
    def _rich(self) -> FakeCur:
        daily = ["2026-09-%02d" % d for d in (1, 2, 3, 5, 8, 13, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30)]
        rows = [(f"2026-09-{d:02d}T10:00:00+00:00", f"2026-09-{d:02d}T10:05:00+00:00")
                for d in (1, 2, 3)]
        # NOTE: first substring match wins; most-specific entries come first.
        return FakeCur([
            ("GROUP BY station_id", [("s1", 8, 30), ("s2", 2, 5)]),
            ("GROUP BY 1, 2", [("CCS2", None, 4, 8, 1)]),
            ("count(DISTINCT (observed_at", [(12,)]),
            ("queue_level NOT IN", [(25,)]),
            ("WHERE availability_status <> 'unknown'", [(50,)]),
            ("power_kw IS NULL", [(1,)]),
            ("price_per_kwh IS NULL", [(2,)]),
            ("price_per_kwh = 0", [(0,)]),
            ("o.name = 'Unknown Operator'", [(1,)]),
            ("records_fetched", [(100,)]),
            ("observations_persisted", [(50,)]),
            ("SELECT min(", rows[:1]),
            ("SELECT DISTINCT", [(d,) for d in daily]),
            ("public.favorites", [(5,)]),
            ("public.user_reports", [(2,)]),
            ("public.reviews", [(1,)]),
            ("public.alerts", [(2,)]),
            ("public.ingestion_runs", [(4,)]),
            ("public.data_sources", [("sid", "open_charge_map")]),
            ("public.station_observations", [(50,)]),
            ("public.stations", [(3,)]),
            ("public.connectors", [(4,)]),
            ("analytics.", [(0,)]),
        ])

    def test_10_rich_temporal_profile(self):
        cur = self._rich()
        p = temporal_profile(cur, "public.station_observations", "observed_at")
        self.assertEqual(p["count"], 50)
        self.assertEqual(p["distinct_dates"], 16)
        self.assertEqual(p["regularity"], "irregular")

    def test_11_rich_maturity_promotes(self):
        cur = self._rich()
        m = station_maturity(cur)
        # s1: 8 days/30 obs -> WARMING; s2: 2 days -> COLD; +1 unobserved station (3 total) -> COLD
        self.assertEqual(m["per_station"]["WARMING"], 1)
        self.assertEqual(m["overall"], "WARMING")

    def test_12_connector_unknown_power_preserved(self):
        from backend.warehouse.maturity import connector_coverage
        cur = self._rich()
        cov = connector_coverage(cur)
        self.assertEqual(cov["by_type_standard"][0]["unknown_power_groups"], 1)


if __name__ == "__main__":
    unittest.main()
