"""Static invariants over supabase/migrations/*.sql. No database, no network.

These tests parse the current migration text and pin the intended final
security/data posture. They catch accidental edits (wrong counts, dropped
assertions, reordered files, new analytics/ml client policies) but they do
NOT prove the sequence applies: execution evidence must come from Route A/B
runs (see supabase/README.md), which remain BLOCKED until actually run.
"""
from __future__ import annotations
import re
import unittest
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"

# Intended application order. If a migration is added/removed/renamed, update
# this list deliberately: order is load-bearing (e.g. R5 must stay last writer
# of ingestion_runs access).
EXPECTED_ORDER = [
    "20260918000001_step_1_3_core_operational_schema.sql",
    "20260922000001_step_1_4_analytics_warehouse_schema.sql",
    "20260922000002_step_1_5_ml_metadata_schema.sql",
    "20260923000001_step_1_6_constraints_indexes.sql",
    "20260924000001_step_1_7_rls_security_policies.sql",
    "20260925000001_step_1_8_views_functions.sql",
    "20260926000001_step_2_10_ingestion_runs.sql",
    "20260926000002_step_2_10_ingestion_runs_grants.sql",
    "20260926000003_step_2_12_connector_unknown_power.sql",
    "20260927000001_pre_phase4_connector_ccs1_vocab.sql",
    "20260927000002_pre_phase4_ingestion_runs_admin.sql",
    "20260927000003_pre_phase4_profiles_role_guard.sql",
    "20260927000004_pre_phase4_alerts_uniqueness.sql",
    "20260928000001_phase4_dim_connector_null_power.sql",
    "20261013000001_step_7_1_connector_price_estimate.sql",
    "20261018000001_demo_provenance.sql",
]

PUBLIC_11 = [
    "profiles", "operators", "stations", "connectors", "data_sources",
    "station_source_link", "station_observations", "user_reports", "reviews",
    "favorites", "alerts",
]
ANALYTICS_12 = [
    "dim_station", "dim_operator", "dim_location", "dim_connector", "dim_date",
    "dim_time", "dim_source", "dim_weather", "fact_station_observation",
    "fact_user_report", "fact_review", "fact_station_daily",
]
ML_6 = ["features", "datasets", "experiments", "model_versions", "metrics", "prediction_runs"]


def read(name):
    return (MIGRATIONS / name).read_text(encoding="utf-8")


def all_sql():
    return {name: read(name) for name in EXPECTED_ORDER}


def strip_sql_comments(sql):
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


class TestMigrationStaticInvariants(unittest.TestCase):
    def test_migration_order_and_inventory(self):
        actual = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
        self.assertEqual(actual, EXPECTED_ORDER)

    def test_policy_counts_derive_from_sql(self):
        s17 = read("20260924000001_step_1_7_rls_security_policies.sql")
        s210 = read("20260926000001_step_2_10_ingestion_runs.sql")
        self.assertEqual(len(re.findall(r"CREATE POLICY", s17)), 29)
        self.assertEqual(len(re.findall(r"CREATE POLICY", s210)), 2)  # admin SELECT + service_role write

    def test_no_client_policies_on_analytics_or_ml(self):
        for name, sql in all_sql().items():
            for m in re.finditer(r"CREATE POLICY\s+\"?([\w]+)\"?\s+ON\s+([\w.]+)", sql):
                target = m.group(2)
                self.assertFalse(
                    target.startswith("analytics.") or target.startswith("ml."),
                    "%s creates client policy on %s" % (name, target),
                )

    def test_step_1_7_enforces_zero_analytics_ml_policies(self):
        s17 = read("20260924000001_step_1_7_rls_security_policies.sql")
        self.assertIn("v_analytics_policy_count", s17)
        self.assertIn("v_ml_policy_count", s17)
        self.assertRegex(
            s17,
            r"IF v_analytics_policy_count <> 0 OR v_ml_policy_count <> 0 THEN\s+RAISE EXCEPTION",
        )

    def test_rls_enabled_for_all_29_owned_tables(self):
        sql = "".join(all_sql().values())
        for schema, tables in (("public", PUBLIC_11), ("analytics", ANALYTICS_12), ("ml", ML_6)):
            for table in tables:
                self.assertRegex(
                    sql,
                    r"ALTER TABLE %s\.%s ENABLE ROW LEVEL SECURITY" % (schema, table),
                    "missing RLS enable for %s.%s" % (schema, table),
                )

    def test_no_cross_layer_foreign_keys(self):
        # Mirrors step_1_7 section 5: FKs sourced in analytics/ml must stay
        # in-schema. public tables may additionally reference auth.users
        # (Supabase auth linkage); anything else across schemas is a defect.
        allowed = {"public": {"public", "auth"}, "analytics": {"analytics"}, "ml": {"ml"}}
        stmt_re = re.compile(r"(?:CREATE TABLE|ALTER TABLE)\s+(?:IF NOT EXISTS\s+|ONLY\s+)?(\w+)\.")
        for name, sql in all_sql().items():
            sql = strip_sql_comments(sql)
            for m in re.finditer(r"REFERENCES\s+(\w+)\.", sql):
                owners = stmt_re.findall(sql[: m.start()])
                self.assertTrue(owners, "%s: FK with no owning statement: %s" % (name, m.group(0)))
                owner = owners[-1]
                self.assertIn(
                    m.group(1),
                    allowed.get(owner, set()),
                    "%s: cross-layer FK %s in %s-owned statement" % (name, m.group(0), owner),
                )

    def test_reference_data_grounded_in_step_1_4(self):
        s14 = read("20260922000001_step_1_4_analytics_warehouse_schema.sql")
        self.assertIn("v_date_cnt <> 3288", s14)
        self.assertIn("DATE '2024-01-01'", s14)
        self.assertIn("DATE '2032-12-31'", s14)
        self.assertIn("exactly 96 rows", s14)

    def test_ingestion_runs_final_posture_is_r5(self):
        writers = [n for n, s in all_sql().items() if "public.ingestion_runs" in s and ("CREATE POLICY" in s or "GRANT" in s or "REVOKE" in s)]
        self.assertEqual(writers[-1], "20260927000002_pre_phase4_ingestion_runs_admin.sql")
        r5 = read(writers[-1])
        self.assertIn('DROP POLICY IF EXISTS "Allow public read access to ingestion_runs"', r5)
        self.assertIn('CREATE POLICY "ingestion_runs_select_admin"', r5)
        self.assertIn("REVOKE SELECT ON public.ingestion_runs FROM anon", r5)
        # R5's own assertions pin the end state; the grants file (position 8)
        # must NOT be replayed after R5 (it re-grants anon SELECT).
        self.assertIn("v_open_count <> 0", r5)
        self.assertIn("v_anon_grants <> 0", r5)

    def test_step_2_10_policies_are_replay_guarded(self):
        s210 = read("20260926000001_step_2_10_ingestion_runs.sql")
        for policy in ("Allow public read access to ingestion_runs", "ingestion_runs_select_admin", "Allow service_role write access to ingestion_runs"):
            if "CREATE POLICY \"%s\"" % policy in s210:
                self.assertIn('DROP POLICY IF EXISTS "%s"' % policy, s210)


if __name__ == "__main__":
    unittest.main()
