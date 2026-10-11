"""Stage-accounting and zero-result run-state guarantees.

Covers the reliability contract of the ingestion/warehouse pipeline:
1. record_stage_run must raise — never return a run_id — when the
   public.ingestion_runs write did not happen (persist_ingestion_run
   swallows DB errors and returns None).
2. A zero-result ingestion is PARTIAL with an explanatory error summary,
   never SUCCEEDED, so it is distinguishable from a source outage.
3. quality/maturity CLI mains exit non-zero when stage accounting fails.

Live Supabase data is never touched: every persistence path is mocked.
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from backend.ingestion.persistence import IngestionPersistenceService
from backend.ingestion.runner import IngestionRunner
from backend.ingestion.scheduling import (
    IngestionRunState,
    ScheduleConfig,
    ScheduledIngestionOrchestrator,
)
from backend.warehouse import maturity as maturity_module
from backend.warehouse import quality as quality_module
from backend.warehouse.accounting import record_stage_run
from backend.warehouse.maturity import main as maturity_main
from backend.warehouse.quality import QualityReport, main as quality_main

ZERO_RESULT_MARKER = "zero records"


def _summary(**overrides):
    base = dict(
        source_id="open_charge_map",
        scope="mumbai",
        retrieved_at=datetime.now(timezone.utc),
        dry_run=False,
        records_fetched=1,
        records_parsed=1,
        records_accepted=1,
        stations_persisted=1,
    )
    base.update(overrides)
    from backend.ingestion.runner import IngestionSummary
    return IngestionSummary(**base)


class TestRecordStageRun(unittest.TestCase):
    def test_returns_recorded_run_id(self):
        with patch.object(IngestionPersistenceService, "persist_ingestion_run", return_value="run-123") as persist:
            run_id = record_stage_run(
                MagicMock(),
                source_name="warehouse_dq",
                scope="warehouse:quality",
                started_at=datetime.now(timezone.utc),
                state=IngestionRunState.SUCCEEDED,
            )
        self.assertEqual(run_id, "run-123")
        self.assertTrue(persist.called)

    def test_raises_when_persistence_returns_none(self):
        """A stage run that was never recorded must not be reported as done."""
        with patch.object(IngestionPersistenceService, "persist_ingestion_run", return_value=None):
            with self.assertRaises(RuntimeError):
                record_stage_run(
                    MagicMock(),
                    source_name="warehouse_dq",
                    scope="warehouse:quality",
                    started_at=datetime.now(timezone.utc),
                    state=IngestionRunState.SUCCEEDED,
                )


class TestZeroResultIsNotSuccess(unittest.TestCase):
    def test_orchestrator_zero_fetch_is_partial_with_summary(self):
        runner = MagicMock()
        runner.db_url = None
        runner.persistence_service = None
        runner.last_run_id = None
        runner.run.return_value = _summary(records_fetched=0, records_parsed=0,
                                           records_accepted=0, stations_persisted=0)
        orchestrator = ScheduledIngestionOrchestrator(
            runner=runner, persistence_service=None, sleep_fn=lambda s: None,
        )
        run = orchestrator.execute_scheduled_run(
            ScheduleConfig(source_id="open_charge_map", limit=5, scope="mumbai"),
        )
        self.assertEqual(run.state, IngestionRunState.PARTIAL)
        self.assertIn(ZERO_RESULT_MARKER, run.error_summary.lower())

    def test_runner_accounting_zero_fetch_is_partial(self):
        service = MagicMock()
        runner = IngestionRunner(db_url="postgresql://unused", persistence_service=service)
        runner.run(dry_run=False, fixtures_data=[])
        run_record = service.persist_ingestion_run.call_args[0][0]
        self.assertEqual(run_record.state, IngestionRunState.PARTIAL)
        self.assertIn(ZERO_RESULT_MARKER, run_record.error_summary.lower())

    def test_normal_fetch_still_succeeds(self):
        """A normal non-empty fetch stays SUCCEEDED (regression guard)."""
        from tests.fixtures.ocm_fixtures import OCM_FIXTURE_01_VALID_COMPLETE
        from tests.test_scheduled_ingestion import MockConnection, MockDatabase

        mock_db = MockDatabase()
        persistence = IngestionPersistenceService(None)
        persistence.conn = MockConnection(mock_db)
        persistence._owns_connection = False
        runner = IngestionRunner(persistence_service=persistence)
        orchestrator = ScheduledIngestionOrchestrator(
            runner=runner, persistence_service=persistence, sleep_fn=lambda s: None,
        )
        run = orchestrator.execute_scheduled_run(
            ScheduleConfig(source_id="open_charge_map", limit=5, scope="mumbai"),
            fixtures_data=[OCM_FIXTURE_01_VALID_COMPLETE],
        )
        self.assertEqual(run.state, IngestionRunState.SUCCEEDED)
        self.assertEqual(run.records_fetched, 1)


class TestStageCliFailClosed(unittest.TestCase):
    def _run_main(self, module, main_fn, **patches):
        ctx = [patch.object(sys, "argv", [module.__name__])]
        for target, kwargs in patches.items():
            ctx.append(patch.object(module, target, **kwargs))
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://unused:unused@localhost/db"}):
            for c in ctx:
                c.start()
            try:
                with self.assertRaises(SystemExit) as caught:
                    main_fn()
            finally:
                for c in reversed(ctx):
                    c.stop()
        return caught.exception.code

    def test_quality_main_exits_nonzero_when_accounting_fails(self):
        code = self._run_main(
            quality_module,
            quality_main,
            run_all_checks={"return_value": QualityReport()},
            _record_quality_run={"side_effect": RuntimeError("ingestion_runs write lost")},
            connect_database={"return_value": MagicMock()},
        )
        self.assertEqual(code, 1)

    def test_maturity_main_exits_nonzero_when_accounting_fails(self):
        report = {
            "generated_at": "now",
            "counts": {},
            "temporal": {"observations": {"count": 0}},
            "targets": [],
            "maturity": {"overall": "COLD"},
            "capabilities": [],
        }
        code = self._run_main(
            maturity_module,
            maturity_main,
            build_report={"return_value": report},
            record_stage_run={"side_effect": RuntimeError("ingestion_runs write lost")},
            connect_database={"return_value": MagicMock()},
        )
        self.assertEqual(code, 1)

    def test_maturity_cold_report_is_not_a_failure(self):
        report = {
            "generated_at": "now",
            "counts": {},
            "temporal": {"observations": {"count": 0}},
            "targets": [],
            "maturity": {"overall": "COLD"},
            "capabilities": [],
        }
        out = io.StringIO()
        with redirect_stdout(out), \
             patch.object(maturity_module, "connect_database", return_value=MagicMock()), \
             patch.object(maturity_module, "build_report", return_value=report), \
             patch.object(maturity_module, "record_stage_run", return_value="run-1"), \
             patch.object(sys, "argv", ["maturity"]), \
             patch.dict(os.environ, {"DATABASE_URL": "postgresql://unused:unused@localhost/db"}):
            maturity_main()  # must return normally: COLD is a data outcome, not a failure
        self.assertIn("COLD", out.getvalue())


if __name__ == "__main__":
    unittest.main()
