"""Fail-closed target guard for database-writing tests (Docker-free workflow).

Any test that writes to PostgreSQL must call require_disposable_target()
with its DATABASE_URL *before* connecting. The guard evaluates the live
environment at call time (never at import), so `load_dotenv` ordering and
test ordering cannot bypass it: whatever URL is configured when the test
runs is the URL that gets checked.

Pass rules (all-or-nothing per tier):
- Loopback hosts (localhost, 127.0.0.1, ::1) always pass: loopback cannot
  be production. No extra intent required.
- Any other host must satisfy ALL of: (a) exact entry in
  CHARGEPLUS_TEST_DB_HOSTS (an allowlist is a restriction, never proof),
  (b) CHARGEPLUS_DISPOSABLE_DB=1 (explicit disposable-test intent), and
  (c) for Supabase-pattern hosts, the project reference in the hostname
  (or, for pooler hostnames, in the username) must exactly equal
  CHARGEPLUS_DISPOSABLE_PROJECT_REF. Safety is never inferred from a
  hostname merely looking like Supabase.
- Placeholder hostnames (your-project-ref, example.*, changeme, ...) are
  always refused, even if allowlisted.
- Missing/empty URLs and malformed URLs (no hostname) always raise: callers
  keep their own "unset means skip" check before calling; reaching the guard
  with no usable URL is a fail-closed error.

Errors name only the host (and test id). The URL, username, password, port,
and query parameters are never included.
"""
from __future__ import annotations
import os
import sys
from urllib.parse import urlparse

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Hostname fragments that prove a URL is a template, not a real target.
_PLACEHOLDER_FRAGMENTS = frozenset({
    "your-project-ref", "example.com", "example.org", "example.net",
    "changeme", "placeholder", "your-project", "localhost.localdomain",
})

_SUPABASE_HOST_SUFFIX = ".supabase.co"
_SUPABASE_POOLER_SUFFIX = ".pooler.supabase.com"


class UnsafeDatabaseTarget(RuntimeError):
    """Raised when a database URL is not positively a disposable test target."""


def _project_ref_from_parts(host, username):
    """Best-effort Supabase project ref, or None for non-Supabase hosts."""
    if host.endswith(_SUPABASE_HOST_SUFFIX) and host.startswith("db."):
        inner = host[len("db."):-len(_SUPABASE_HOST_SUFFIX)]
        return inner.split(".")[0] or None
    if host.endswith(_SUPABASE_POOLER_SUFFIX) and username and "." in username:
        return username.split(".", 1)[1] or None
    return None


def _is_placeholder(host):
    return any(frag in host for frag in _PLACEHOLDER_FRAGMENTS)


def require_disposable_target(db_url, *, test_id):
    """Return the verified hostname, or raise UnsafeDatabaseTarget."""
    host = (urlparse(db_url or "").hostname or "").lower()
    if not host:
        raise UnsafeDatabaseTarget(
            "Refusing %s: DATABASE_URL is missing or has no parseable hostname. "
            "Configure a disposable test target; refusing to proceed." % (test_id,)
        )
    if _is_placeholder(host):
        raise UnsafeDatabaseTarget(
            "Refusing %s against placeholder database host %r: replace it with a "
            "real disposable target. Production/staging targets are never valid." % (test_id, host)
        )
    if host in _LOOPBACK_HOSTS:
        return host
    allowlisted = {h.strip().lower() for h in os.getenv("CHARGEPLUS_TEST_DB_HOSTS", "").split(",") if h.strip()}
    if not host or host not in allowlisted:
        raise UnsafeDatabaseTarget(
            "Refusing %s against unverified database host %r: allowlist its host via "
            "CHARGEPLUS_TEST_DB_HOSTS *and* set CHARGEPLUS_DISPOSABLE_DB=1 with "
            "CHARGEPLUS_DISPOSABLE_PROJECT_REF for Supabase targets. "
            "Production/staging targets are never valid." % (test_id, host)
        )
    if os.getenv("CHARGEPLUS_DISPOSABLE_DB") != "1":
        raise UnsafeDatabaseTarget(
            "Refusing %s against host %r: allowlisted but explicit disposable-test "
            "intent (CHARGEPLUS_DISPOSABLE_DB=1) is missing. An allowlist alone is "
            "not proof of disposability." % (test_id, host)
        )
    ref = _project_ref_from_parts(host, urlparse(db_url).username or "")
    if ref is not None and ref != os.getenv("CHARGEPLUS_DISPOSABLE_PROJECT_REF", ""):
        raise UnsafeDatabaseTarget(
            "Refusing %s against host %r: Supabase project reference does not match "
            "CHARGEPLUS_DISPOSABLE_PROJECT_REF. Never infer safety from the hostname." % (test_id, host)
        )
    return host


def preflight(db_url=None):
    """Non-destructive verdict: (allowed: bool, sanitized summary). Never connects."""
    db_url = db_url if db_url is not None else os.getenv("DATABASE_URL", "")
    try:
        host = require_disposable_target(db_url, test_id="preflight")
    except UnsafeDatabaseTarget as e:
        return False, str(e)
    kind = "loopback" if host in _LOOPBACK_HOSTS else "verified disposable remote"
    return True, "target host %r (%s): writes permitted by guard policy." % (host, kind)


def _run_self_check():
    # Meaningful positive and negative cases, no frameworks.
    ok = require_disposable_target("postgresql://u:p@localhost:5432/db", test_id="self")
    assert ok == "localhost", ok
    assert require_disposable_target("POSTGRESQL://U:P@127.0.0.1/db", test_id="self") == "127.0.0.1"
    assert require_disposable_target("postgresql://u:p@[::1]:5432/db", test_id="self") == "::1"
    for bad in ("", "not-a-url", "postgresql://u:p@/db", "postgresql:///db"):
        try:
            require_disposable_target(bad, test_id="self")
        except UnsafeDatabaseTarget:
            pass
        else:
            raise AssertionError("guard accepted malformed URL %r" % bad)
    for bad in ("postgresql://u:p@db.prod.co/db", "postgresql://u:p@staging.internal/db"):
        try:
            require_disposable_target(bad, test_id="self")
        except UnsafeDatabaseTarget:
            pass
        else:
            raise AssertionError("guard accepted unknown host %r" % bad)
    # Allowlisted but no intent -> refuse (allowlist is not proof).
    os.environ["CHARGEPLUS_TEST_DB_HOSTS"] = "db-ci-07.test.invalid"
    try:
        require_disposable_target("postgresql://u:p@db-ci-07.test.invalid/db", test_id="self")
    except UnsafeDatabaseTarget:
        pass
    else:
        raise AssertionError("guard accepted allowlisted host without disposable intent")
    # Allowlist + intent -> pass for non-Supabase hosts.
    os.environ["CHARGEPLUS_DISPOSABLE_DB"] = "1"
    assert require_disposable_target("postgresql://u:p@db-ci-07.test.invalid/db", test_id="self") == "db-ci-07.test.invalid"
    # Supabase host: ref mismatch refuses, ref match passes.
    os.environ["CHARGEPLUS_TEST_DB_HOSTS"] = "db.abcdefghijklmnopqrst.supabase.co"
    os.environ["CHARGEPLUS_DISPOSABLE_PROJECT_REF"] = "otherref"
    try:
        require_disposable_target("postgresql://postgres:pw@db.abcdefghijklmnopqrst.supabase.co:5432/postgres", test_id="self")
    except UnsafeDatabaseTarget:
        pass
    else:
        raise AssertionError("guard accepted Supabase host with mismatched project ref")
    os.environ["CHARGEPLUS_DISPOSABLE_PROJECT_REF"] = "abcdefghijklmnopqrst"
    assert require_disposable_target("postgresql://postgres:pw@db.abcdefghijklmnopqrst.supabase.co:5432/postgres", test_id="self") == "db.abcdefghijklmnopqrst.supabase.co"
    # Pooler hostname carries the ref in the username, never in errors.
    os.environ["CHARGEPLUS_TEST_DB_HOSTS"] = "aws-0-ap-south-1.pooler.supabase.com"
    os.environ["CHARGEPLUS_DISPOSABLE_PROJECT_REF"] = "abcdefghijklmnopqrst"
    assert require_disposable_target("postgresql://postgres.abcdefghijklmnopqrst:pw@aws-0-ap-south-1.pooler.supabase.com:6543/postgres", test_id="self") == "aws-0-ap-south-1.pooler.supabase.com"
    # Placeholders refuse even when allowlisted with intent.
    os.environ["CHARGEPLUS_TEST_DB_HOSTS"] = "db.your-project-ref.supabase.co"
    try:
        require_disposable_target("postgresql://postgres:pw@db.your-project-ref.supabase.co:5432/postgres", test_id="self")
    except UnsafeDatabaseTarget as e:
        assert "your-project-ref" in str(e)  # host only, never credentials
    else:
        raise AssertionError("guard accepted placeholder hostname")
    # Secret redaction: password, username, params must never appear.
    try:
        require_disposable_target("postgresql://admin:SUPER_SECRET_PW@evil.example.com/db?sslmode=require", test_id="self")
    except UnsafeDatabaseTarget as e:
        msg = str(e)
        assert "SUPER_SECRET_PW" not in msg and "sslmode" not in msg and "admin:" not in msg and "admin@" not in msg, msg
    else:
        raise AssertionError("guard accepted unknown host")
    print("db_target_guard self-check: OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--preflight":
        allowed, summary = preflight()
        print(("ALLOW: " if allowed else "DENY: ") + summary)
        sys.exit(0 if allowed else 2)
    _run_self_check()
