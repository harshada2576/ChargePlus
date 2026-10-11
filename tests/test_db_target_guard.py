"""Deterministic tests for tests/db_target_guard.py. No network, no database."""
from __future__ import annotations
import os
import unittest

from tests.db_target_guard import (
    UnsafeDatabaseTarget,
    preflight,
    require_disposable_target,
)

_MANAGED_VARS = (
    "CHARGEPLUS_TEST_DB_HOSTS",
    "CHARGEPLUS_DISPOSABLE_DB",
    "CHARGEPLUS_DISPOSABLE_PROJECT_REF",
    "DATABASE_URL",
)


class TestDbTargetGuard(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in _MANAGED_VARS}
        for k in _MANAGED_VARS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k in _MANAGED_VARS:
            os.environ.pop(k, None)
            if self._saved[k] is not None:
                os.environ[k] = self._saved[k]

    def assertRefused(self, url, **kw):
        with self.assertRaises(UnsafeDatabaseTarget):
            require_disposable_target(url, test_id="unit", **kw)

    def test_loopback_targets_pass_without_intent(self):
        self.assertEqual(require_disposable_target("postgresql://u:p@localhost:5432/db", test_id="unit"), "localhost")
        self.assertEqual(require_disposable_target("postgresql://u:p@127.0.0.1/db", test_id="unit"), "127.0.0.1")
        self.assertEqual(require_disposable_target("postgresql://u:p@[::1]:5432/db", test_id="unit"), "::1")

    def test_host_is_case_insensitive(self):
        self.assertEqual(require_disposable_target("postgresql://u:p@LOCALHOST/db", test_id="unit"), "localhost")

    def test_missing_and_malformed_urls_refuse(self):
        self.assertRefused("")
        self.assertRefused(None)
        self.assertRefused("not-a-url")
        self.assertRefused("postgresql://u:p@/db")
        self.assertRefused("postgresql:///db")

    def test_unknown_hosts_refuse(self):
        self.assertRefused("postgresql://u:p@db.prod.co/db")
        self.assertRefused("postgresql://u:p@staging.internal/db")

    def test_production_and_staging_looking_hosts_refuse(self):
        self.assertRefused("postgresql://u:p@prod.supabase.co/db")
        self.assertRefused("postgresql://u:p@db.productionabc.supabase.co:5432/postgres")
        self.assertRefused("postgresql://u:p@aws-0-ap-south-1.pooler.supabase.com:6543/postgres")

    def test_allowlisted_without_intent_refuses(self):
        os.environ["CHARGEPLUS_TEST_DB_HOSTS"] = "db-ci-07.test.invalid"
        self.assertRefused("postgresql://u:p@db-ci-07.test.invalid/db")

    def test_allowlisted_with_intent_passes_non_supabase(self):
        os.environ["CHARGEPLUS_TEST_DB_HOSTS"] = "db-ci-07.test.invalid"
        os.environ["CHARGEPLUS_DISPOSABLE_DB"] = "1"
        self.assertEqual(
            require_disposable_target("postgresql://u:p@db-ci-07.test.invalid/db", test_id="unit"),
            "db-ci-07.test.invalid",
        )

    def test_supabase_host_requires_matching_project_ref(self):
        host = "db.abcdefghijklmnopqrst.supabase.co"
        os.environ["CHARGEPLUS_TEST_DB_HOSTS"] = host
        os.environ["CHARGEPLUS_DISPOSABLE_DB"] = "1"
        os.environ["CHARGEPLUS_DISPOSABLE_PROJECT_REF"] = "otherref"
        self.assertRefused("postgresql://postgres:pw@%s:5432/postgres" % host)
        os.environ["CHARGEPLUS_DISPOSABLE_PROJECT_REF"] = "abcdefghijklmnopqrst"
        self.assertEqual(
            require_disposable_target("postgresql://postgres:pw@%s:5432/postgres" % host, test_id="unit"), host
        )

    def test_pooler_host_reads_ref_from_username(self):
        host = "aws-0-ap-south-1.pooler.supabase.com"
        os.environ["CHARGEPLUS_TEST_DB_HOSTS"] = host
        os.environ["CHARGEPLUS_DISPOSABLE_DB"] = "1"
        os.environ["CHARGEPLUS_DISPOSABLE_PROJECT_REF"] = "abcdefghijklmnopqrst"
        url = "postgresql://postgres.abcdefghijklmnopqrst:pw@%s:6543/postgres" % host
        self.assertEqual(require_disposable_target(url, test_id="unit"), host)
        os.environ["CHARGEPLUS_DISPOSABLE_PROJECT_REF"] = "wrongref"
        self.assertRefused(url)

    def test_placeholder_hostnames_always_refuse(self):
        os.environ["CHARGEPLUS_TEST_DB_HOSTS"] = "db.your-project-ref.supabase.co"
        os.environ["CHARGEPLUS_DISPOSABLE_DB"] = "1"
        os.environ["CHARGEPLUS_DISPOSABLE_PROJECT_REF"] = "your-project-ref"
        self.assertRefused("postgresql://postgres:pw@db.your-project-ref.supabase.co:5432/postgres")
        self.assertRefused("postgresql://u:p@app.example.com/db")

    def test_errors_never_contain_credentials(self):
        try:
            require_disposable_target("postgresql://admin:SUPER_SECRET_PW@evil.example.com/db?sslmode=require", test_id="unit")
        except UnsafeDatabaseTarget as e:
            msg = str(e)
        else:
            self.fail("guard accepted unknown host")
        self.assertNotIn("SUPER_SECRET_PW", msg)
        self.assertNotIn("sslmode", msg)
        self.assertNotIn("admin:", msg)
        self.assertNotIn("admin@", msg)

    def test_preflight_allows_loopback_without_connecting(self):
        os.environ["DATABASE_URL"] = "postgresql://u:p@localhost:5432/db"
        allowed, summary = preflight()
        self.assertTrue(allowed)
        self.assertIn("localhost", summary)
        self.assertNotIn("u:p", summary)

    def test_preflight_denies_unverified_target(self):
        os.environ["DATABASE_URL"] = "postgresql://u:p@db.prod.co/db"
        allowed, summary = preflight()
        self.assertFalse(allowed)
        self.assertIn("db.prod.co", summary)

    def test_preflight_denies_missing_url(self):
        allowed, _ = preflight()
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
