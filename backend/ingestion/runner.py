"""ChargePlus — Ingestion Orchestrator & CLI Runner.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.3 (Connect First Legitimate Station Data Source)

Orchestrates the end-to-end ingestion pipeline:
FETCH -> PARSE -> NORMALIZE -> VALIDATE -> PERSIST OPERATIONAL STATE -> PERSIST OBSERVATION

COMMAND LINE USAGE:
    # 1. Dry run against OpenChargeMap API (Zero database writes)
    python -m backend.ingestion.runner --dry-run --limit 10

    # 2. Controlled live production ingestion for Mumbai pilot
    python -m backend.ingestion.runner --limit 10

    # 3. Offline execution against representative test fixtures
    python -m backend.ingestion.runner --use-fixtures --dry-run
"""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
import sys
import time
from typing import Any, Optional

from dotenv import load_dotenv

from backend.ingestion.adapters.openchargemap import OpenChargeMapAdapter
from backend.ingestion.constants import (
    MUMBAI_LAT_MAX,
    MUMBAI_LAT_MIN,
    MUMBAI_LNG_MAX,
    MUMBAI_LNG_MIN,
    ValidationOutcome,
)
from backend.ingestion.persistence import (
    IngestionPersistenceService,
    PersistenceStatus,
)
from backend.ingestion.scheduling import (
    IngestionRun,
    PollingDaemon,
    RetryPolicy,
    ScheduleConfig,
    ScheduledIngestionOrchestrator,
)

# Configure structured logging without dumping sensitive tokens
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chargeplus.ingestion.runner")


@dataclass
class IngestionSummary:
    """Concise, structured metrics summarizing an ingestion run."""
    source_id: str
    scope: str
    retrieved_at: datetime
    dry_run: bool
    records_fetched: int = 0
    records_parsed: int = 0
    records_accepted: int = 0
    records_accepted_with_warnings: int = 0
    records_quarantined: int = 0
    records_rejected: int = 0
    stations_persisted: int = 0
    stations_updated: int = 0
    stations_unchanged: int = 0
    connectors_persisted: int = 0
    observations_persisted: int = 0
    persistence_errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Converts summary to dictionary."""
        return {
            "source_id": self.source_id,
            "scope": self.scope,
            "retrieved_at": self.retrieved_at.isoformat(),
            "dry_run": self.dry_run,
            "records_fetched": self.records_fetched,
            "records_parsed": self.records_parsed,
            "records_accepted": self.records_accepted,
            "records_accepted_with_warnings": self.records_accepted_with_warnings,
            "records_quarantined": self.records_quarantined,
            "records_rejected": self.records_rejected,
            "stations_persisted": self.stations_persisted,
            "stations_updated": self.stations_updated,
            "stations_unchanged": self.stations_unchanged,
            "connectors_persisted": self.connectors_persisted,
            "observations_persisted": self.observations_persisted,
            "persistence_errors_count": len(self.persistence_errors),
            "duration_seconds": round(self.duration_seconds, 2),
        }

    def print_report(self) -> None:
        """Prints a human-readable data quality & ingestion report."""
        mode_label = "DRY RUN (0 Database Writes)" if self.dry_run else "REAL PERSISTENCE (Supabase PostgreSQL)"
        print("\n" + "=" * 65)
        print(f"CHARGEPLUS INGESTION REPORT — {mode_label}")
        print("=" * 65)
        print(f"  Source Identifier:        {self.source_id}")
        print(f"  Geographic Scope:         {self.scope}")
        print(f"  Run Timestamp (UTC):      {self.retrieved_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  Execution Duration:       {self.duration_seconds:.2f} seconds")
        print("-" * 65)
        print(f"  Raw Records Fetched:      {self.records_fetched}")
        print(f"  Successfully Parsed:      {self.records_parsed}")
        print(f"  Validation Accepted:      {self.records_accepted}")
        print(f"  Accepted with Warnings:   {self.records_accepted_with_warnings}")
        print(f"  Quarantined Records:      {self.records_quarantined} (Excluded from operational state)")
        print(f"  Rejected Records:         {self.records_rejected} (Fatal validation/parsing errors)")
        print("-" * 65)
        print(f"  Stations Inserted (New):  {self.stations_persisted}")
        print(f"  Stations Updated:         {self.stations_updated}")
        print(f"  Stations Unchanged:       {self.stations_unchanged}")
        print(f"  Connectors Persisted:     {self.connectors_persisted}")
        print(f"  Observations Persisted:   {self.observations_persisted}")
        print(f"  Persistence Failures:     {len(self.persistence_errors)}")
        print("=" * 65)
        if self.persistence_errors:
            print("\nPersistence Error Details:")
            for err in self.persistence_errors[:10]:
                print(f"  - {err}")
        print()


class IngestionRunner:
    """Coordinates external source extraction, normalization, validation, and database persistence."""

    def __init__(
        self,
        db_url: Optional[str] = None,
        api_key: Optional[str] = None,
        persistence_service: Optional[IngestionPersistenceService] = None,
    ):
        """Initializes the runner with optional credentials override."""
        load_dotenv(".env.local")
        load_dotenv(".env")

        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.api_key = api_key or os.getenv("OPENCHARGEMAP_API_KEY")
        self.persistence_service = persistence_service
        self.adapter = OpenChargeMapAdapter()

    def run(
        self,
        dry_run: bool = False,
        limit: int = 50,
        mumbai_only: bool = True,
        bounding_box: Optional[tuple[float, float, float, float]] = None,
        fixtures_data: Optional[list[dict[str, Any]]] = None,
    ) -> IngestionSummary:
        """Executes the ingestion pipeline and returns the execution summary."""
        start_time = time.time()
        retrieved_at = datetime.now(timezone.utc)

        # 1. Resolve Geographic Scope
        if bounding_box:
            bbox = bounding_box
            scope_desc = f"Custom Bounding Box {bbox}"
        elif mumbai_only:
            bbox = (MUMBAI_LAT_MIN, MUMBAI_LNG_MIN, MUMBAI_LAT_MAX, MUMBAI_LNG_MAX)
            scope_desc = f"Mumbai Metropolitan Region (MMR) [{MUMBAI_LAT_MIN}, {MUMBAI_LNG_MIN}] to [{MUMBAI_LAT_MAX}, {MUMBAI_LNG_MAX}]"
        else:
            bbox = None
            scope_desc = "India Nationwide (countrycode=IN)"

        summary = IngestionSummary(
            source_id="open_charge_map",
            scope=scope_desc,
            retrieved_at=retrieved_at,
            dry_run=dry_run,
        )

        # 2. Fetch Raw Payloads (or use provided fixtures)
        if fixtures_data is not None:
            logger.info("Using provided in-memory test fixtures (%d records)", len(fixtures_data))
            raw_payloads = fixtures_data[:limit]
            summary.scope = "Offline Representative Test Fixtures"
        else:
            if not self.api_key:
                raise RuntimeError(
                    "OPENCHARGEMAP_API_KEY is not configured in .env.local or environment. "
                    "Cannot perform live API extraction. Use --use-fixtures for offline execution."
                )

            logger.info("Fetching up to %d records from OpenChargeMap API for scope: %s", limit, scope_desc)
            raw_payloads = self.adapter.fetch_raw(
                country_code="IN",
                bounding_box=bbox,
                max_results=limit,
                api_key=self.api_key,
            )

        summary.records_fetched = len(raw_payloads)
        logger.info("Retrieved %d raw source records", summary.records_fetched)

        # 3. Initialize Persistence Service
        if self.persistence_service:
            persistence = self.persistence_service
            owns_persistence = False
        elif dry_run and not self.db_url:
            persistence = IngestionPersistenceService(None)
            owns_persistence = True
        else:
            if not dry_run and not self.db_url:
                raise RuntimeError(
                    "DATABASE_URL is not configured in .env.local or environment. Cannot persist records."
                )
            persistence = IngestionPersistenceService(self.db_url)
            owns_persistence = True
        try:
            data_source_id = persistence.get_or_create_data_source(
                name="open_charge_map",
                source_type="api",
                base_url="https://api.openchargemap.io/v3/poi/",
                dry_run=dry_run,
            )

            # 4. Process Each Record with Record-Level Error Isolation
            for idx, raw_dict in enumerate(raw_payloads):
                try:
                    # A. Parse & Normalize via locked Step 2.2 Adapter
                    adapter_res = self.adapter.process_record(raw_dict, retrieved_at=retrieved_at)
                    if not adapter_res.success:
                        summary.records_rejected += 1
                        summary.persistence_errors.append(
                            f"Record [{idx}] parsing/validation failed: {', '.join(adapter_res.errors)}"
                        )
                        continue

                    summary.records_parsed += 1
                    station = adapter_res.station_record
                    raw_record = adapter_res.raw_record
                    val_result = adapter_res.validation_result

                    # B. Check Data Quality Validation Category
                    if val_result.outcome == ValidationOutcome.REJECT:
                        summary.records_rejected += 1
                        summary.persistence_errors.append(
                            f"Station '{station.source_station_id}' rejected by validator: {', '.join(val_result.errors)}"
                        )
                        continue

                    if val_result.outcome == ValidationOutcome.QUARANTINE:
                        summary.records_quarantined += 1
                        logger.warning(
                            "Station '%s' quarantined (%s); excluded from operational persistence",
                            station.source_station_id,
                            ", ".join(val_result.quarantine_reasons),
                        )
                        continue

                    if val_result.outcome == ValidationOutcome.ACCEPT_WITH_WARNINGS:
                        summary.records_accepted_with_warnings += 1
                    else:
                        summary.records_accepted += 1

                    # C. Persist Canonical Station & Connectors
                    persist_res = persistence.persist_station(
                        station=station,
                        raw_record=raw_record,
                        data_source_id=data_source_id,
                        dry_run=dry_run,
                    )

                    if persist_res.status == PersistenceStatus.INSERTED:
                        summary.stations_persisted += 1
                        summary.connectors_persisted += persist_res.connectors_persisted
                    elif persist_res.status == PersistenceStatus.UPDATED:
                        summary.stations_updated += 1
                        summary.connectors_persisted += persist_res.connectors_persisted
                    elif persist_res.status == PersistenceStatus.UNCHANGED:
                        summary.stations_unchanged += 1

                    # D. Persist Genuine Observations (Operational & Warehouse Fact)
                    if station.observation and persist_res.station_id:
                        total_connectors = sum(max(1, c.quantity) for c in station.connectors)
                        obs_id = persistence.persist_observation(
                            station_id=persist_res.station_id,
                            data_source_id=data_source_id,
                            obs=station.observation,
                            total_connectors=total_connectors,
                            raw_payload_hash=raw_record.payload_hash,
                            dry_run=dry_run,
                        )
                        if obs_id:
                            summary.observations_persisted += 1

                except Exception as ex:
                    # Enforce record-level failure isolation
                    logger.error("Exception processing record index %d: %s", idx, ex)
                    summary.persistence_errors.append(f"Record [{idx}] unexpected failure: {str(ex)}")
                    if not dry_run and persistence.conn:
                        try:
                            persistence.conn.rollback()
                        except Exception:
                            pass

        finally:
            if owns_persistence:
                persistence.close()

        summary.duration_seconds = time.time() - start_time
        return summary

    def run_scheduled(
        self,
        config: ScheduleConfig,
        fixtures_data: Optional[list[dict[str, Any]]] = None,
    ) -> IngestionRun:
        """Executes the pipeline via ScheduledIngestionOrchestrator with retries, locks, and run accounting."""
        orchestrator = ScheduledIngestionOrchestrator(
            runner=self,
            persistence_service=self.persistence_service,
        )
        return orchestrator.execute_scheduled_run(config, fixtures_data=fixtures_data)


def main() -> None:
    """Command-line entrypoint for executing station ingestion."""
    parser = argparse.ArgumentParser(
        description="ChargePlus EV Station Data Ingestion Orchestrator & Polling Daemon (Phase 2 Step 2.10)"
    )
    parser.add_argument(
        "--source",
        type=str,
        default="open_charge_map",
        help="Source identifier to ingest (default: open_charge_map)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute pipeline without performing any database writes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum records to fetch and process (default: 50)",
    )
    parser.add_argument(
        "--all-india",
        action="store_true",
        help="Expand query scope from Mumbai MMR to nationwide India",
    )
    parser.add_argument(
        "--scope",
        type=str,
        default="mumbai",
        help="Custom scope label for run accounting and locking (default: mumbai)",
    )
    parser.add_argument(
        "--use-fixtures",
        action="store_true",
        help="Run against offline representative test fixtures instead of live API",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output summary metrics as machine-readable JSON",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as an ongoing background polling daemon",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Polling interval in seconds for daemon mode (default: 300)",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Execute a single scheduled run through the orchestrator and exit",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum retry attempts for transient errors (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="API request timeout in seconds (default: 30.0)",
    )

    args = parser.parse_args()

    fixtures_data = None
    if args.use_fixtures:
        from tests.fixtures.ocm_fixtures import (
            OCM_FIXTURE_01_VALID_COMPLETE,
            OCM_FIXTURE_02_MULTIPLE_CONNECTORS,
            OCM_FIXTURE_03_AGGREGATED_CONNECTORS,
            OCM_FIXTURE_04_MISSING_OPTIONAL_FIELDS,
            OCM_FIXTURE_13_TELEMETRY_AVAILABLE,
            OCM_FIXTURE_14_STATIC_OPERATIONAL_NOT_AVAILABLE,
            OCM_FIXTURE_15_EXTRA_FIELDS,
        )
        fixtures_data = [
            OCM_FIXTURE_01_VALID_COMPLETE,
            OCM_FIXTURE_02_MULTIPLE_CONNECTORS,
            OCM_FIXTURE_03_AGGREGATED_CONNECTORS,
            OCM_FIXTURE_04_MISSING_OPTIONAL_FIELDS,
            OCM_FIXTURE_13_TELEMETRY_AVAILABLE,
            OCM_FIXTURE_14_STATIC_OPERATIONAL_NOT_AVAILABLE,
            OCM_FIXTURE_15_EXTRA_FIELDS,
        ]

    runner = IngestionRunner()

    # Determine scope description
    scope_name = "india" if args.all_india else args.scope

    # Build retry policy
    retry_policy = RetryPolicy(
        max_attempts=args.max_attempts,
        initial_delay_seconds=1.0,
        max_delay_seconds=args.timeout,
    )

    # Build schedule config
    schedule_config = ScheduleConfig(
        source_id=args.source,
        enabled=True,
        interval_seconds=args.interval,
        limit=args.limit,
        scope=scope_name,
        timeout_seconds=args.timeout,
        retry_policy=retry_policy,
        dry_run=args.dry_run,
    )

    try:
        if args.daemon:
            orchestrator = ScheduledIngestionOrchestrator(runner=runner)
            daemon = PollingDaemon(
                orchestrator=orchestrator,
                schedules=[schedule_config],
            )
            daemon.start(run_once=False)
        elif args.run_once:
            run = runner.run_scheduled(config=schedule_config, fixtures_data=fixtures_data)
            if args.json:
                print(json.dumps(run.to_dict(), indent=2))
            else:
                print(f"Run ID: {run.run_id} | State: {run.state.value} | Fetched: {run.records_fetched} | Persisted: {run.stations_persisted}")
        else:
            summary = runner.run(
                dry_run=args.dry_run,
                limit=args.limit,
                mumbai_only=not args.all_india,
                fixtures_data=fixtures_data,
            )
            if args.json:
                print(json.dumps(summary.to_dict(), indent=2))
            else:
                summary.print_report()

    except Exception as e:
        logger.error("Ingestion failed: %s", _scrub_secrets(str(e)))
        sys.exit(1)


if __name__ == "__main__":
    main()
