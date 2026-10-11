"""Persistent accounting for non-mutating warehouse pipeline stages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from backend.ingestion.persistence import IngestionPersistenceService, _scrub_secrets
from backend.ingestion.scheduling import IngestionRun, IngestionRunState


def record_stage_run(
    conn: Any,
    *,
    source_name: str,
    scope: str,
    started_at: datetime,
    state: IngestionRunState,
    error_summary: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    """Record a warehouse stage without pretending it is source ingestion."""
    completed_at = datetime.now(timezone.utc)
    run = IngestionRun(
        run_id=str(uuid.uuid4()),
        source_id=None,
        source_name=source_name,
        scope=scope,
        state=state,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=(completed_at - started_at).total_seconds(),
        attempt_count=1,
        error_summary=_scrub_secrets(error_summary),
        metadata={"pipeline_stage": source_name, **(metadata or {})},
    )
    recorded_id = IngestionPersistenceService(conn).persist_ingestion_run(run, dry_run=False)
    if recorded_id is None:
        # persist_ingestion_run swallows the database error and returns None;
        # a stage run that was never recorded must never be reported as done.
        raise RuntimeError(
            f"Stage accounting failed: no public.ingestion_runs row persisted for '{scope}'."
        )
    return recorded_id
