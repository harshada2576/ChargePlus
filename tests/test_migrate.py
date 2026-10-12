"""
tests/test_migrate.py
Unit tests for backend/warehouse/migrate.py migration runner.
"""

from pathlib import Path
import pytest
from unittest.mock import MagicMock
from backend.warehouse.migrate import (
    get_migration_files,
    ensure_migrations_table,
    get_applied_migrations,
    run_migrations,
    MIGRATIONS_DIR
)
from tests.db_target_guard import UnsafeDatabaseTarget


def test_get_migration_files_count_and_order():
    files = get_migration_files()
    assert len(files) == 14
    names = [f.name for f in files]
    assert names == sorted(names)
    assert names[0] == "20260918000001_step_1_3_core_operational_schema.sql"
    assert names[-1] == "20260928000001_phase4_dim_connector_null_power.sql"


def test_migrate_guard_rejects_placeholder_url():
    placeholder_url = "postgresql://postgres:postgres@your-project-ref.supabase.co:5432/postgres"
    with pytest.raises(UnsafeDatabaseTarget):
        run_migrations(placeholder_url, check_disposable=True)


def test_migrate_guard_rejects_empty_url():
    with pytest.raises(ValueError):
        run_migrations("", check_disposable=True)


def test_ensure_migrations_table_and_get_applied():
    mock_cursor = MagicMock()
    ensure_migrations_table(mock_cursor)
    mock_cursor.execute.assert_called_once()
    assert "CREATE TABLE IF NOT EXISTS public._schema_migrations" in mock_cursor.execute.call_args[0][0]

    mock_cursor.fetchall.return_value = [("20260918000001_step_1_3_core_operational_schema.sql",)]
    applied = get_applied_migrations(mock_cursor)
    assert applied == {"20260918000001_step_1_3_core_operational_schema.sql"}
