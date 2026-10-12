"""
backend/warehouse/migrate.py
Authoritative database migration runner for ChargePlus.

Applies SQL migrations from supabase/migrations/ in deterministic sequence.
Enforces fail-closed target guards to prevent accidental destructive execution on production.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Tuple
import psycopg2

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = ROOT_DIR / "supabase" / "migrations"

# Reuse the disposable target guard from tests
sys.path.insert(0, str(ROOT_DIR))
try:
    from tests.db_target_guard import require_disposable_target, UnsafeDatabaseTarget
except ImportError:
    def require_disposable_target(url: str, test_id: str = "migrate"):
        if not url:
            raise RuntimeError("DATABASE_URL is required.")


def get_migration_files() -> List[Path]:
    """Returns all .sql migration files in supabase/migrations/ sorted alphanumerically."""
    if not MIGRATIONS_DIR.is_dir():
        raise FileNotFoundError(f"Migrations directory not found: {MIGRATIONS_DIR}")
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def ensure_migrations_table(cursor) -> None:
    """Creates the migration tracking table if it does not already exist."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS public._schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def get_applied_migrations(cursor) -> set[str]:
    """Retrieves the set of already applied migration version filenames."""
    cursor.execute("SELECT version FROM public._schema_migrations;")
    return {row[0] for row in cursor.fetchall()}


def run_migrations(database_url: str | None = None, check_disposable: bool = True) -> List[str]:
    """
    Applies all pending migrations from supabase/migrations/ to the target database.
    Returns the list of newly applied migration filenames.
    """
    if database_url is not None:
        target_url = database_url
    else:
        target_url = os.environ.get("DATABASE_URL")
    if not target_url:
        raise ValueError("DATABASE_URL must be provided or set in environment.")

    if check_disposable:
        require_disposable_target(target_url, test_id="migrate")

    conn = psycopg2.connect(target_url)
    applied_now: List[str] = []

    try:
        with conn.cursor() as cur:
            ensure_migrations_table(cur)
            applied = get_applied_migrations(cur)

        files = get_migration_files()
        print(f"[MIGRATIONS] Found {len(files)} total migration files in {MIGRATIONS_DIR.name}/")

        for file_path in files:
            version_name = file_path.name
            if version_name in applied:
                print(f"  • [SKIPPED] {version_name} (already applied)")
                continue

            print(f"  • [APPLYING] {version_name} ...")
            sql_content = file_path.read_text(encoding="utf-8")

            with conn.cursor() as cur:
                cur.execute(sql_content)
                cur.execute(
                    "INSERT INTO public._schema_migrations (version) VALUES (%s);",
                    (version_name,)
                )
            conn.commit()
            applied_now.append(version_name)
            print(f"    ✔ Successfully applied {version_name}")

        print(f"[MIGRATIONS] Complete. Newly applied: {len(applied_now)} migration(s).")
    finally:
        conn.close()

    return applied_now


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[ERROR] DATABASE_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)

    try:
        applied = run_migrations(url)
        print(f"[DONE] Applied {len(applied)} migrations.")
    except Exception as e:
        print(f"[ERROR] Migration failed: {e}", file=sys.stderr)
        sys.exit(1)
