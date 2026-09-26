"""ChargePlus — Ingestion Persistence Service.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.3 (Connect First Legitimate Station Data Source)

Implements the database persistence boundary for normalized canonical station records,
connectors, source provenance links, and time-series observations.

ARCHITECTURAL PRINCIPLES:
1. Adapters are strictly non-persistent; persistence logic resides exclusively here.
2. External source IDs NEVER become ChargePlus station UUIDs (idempotent mapping via public.station_source_link).
3. "Missing means missing" (no fake prices, 0 kW power, or invented availability).
4. Operational state (public.stations) is decoupled from time-series observations (analytics.fact_station_observation).
5. Dry-run capability allows executing full pipelines with ZERO database mutations.
6. Record-level error isolation: individual record failure never aborts the whole batch.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import re
from typing import Any, Optional, Union
import uuid

import psycopg2
from psycopg2.extras import RealDictCursor

from backend.ingestion.constants import (
    AvailabilityStatus,
    OperationalStatus,
    QueueLevel,
    StandardConnectorType,
)
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedObservationRecord,
    NormalizedStationRecord,
    RawSourceRecord,
)
from backend.ingestion.deduplication import (
    CanonicalDecisionState,
    CanonicalResolutionDecision,
    ExistingCanonicalStation,
    FieldSurvivorshipDecision,
)
import time

logger = logging.getLogger(__name__)

# Valid connector types supported by public.connectors check constraint
ALLOWED_DB_CONNECTOR_TYPES = {
    "CCS2",
    "CHAdeMO",
    "Type 2",
    "Type 1",
    "GB/T",
    "Bharat AC001",
    "Bharat DC001",
}

# Regex to validate standard 6-digit Indian PIN code
INDIAN_PIN_REGEX = re.compile(r"^[1-9][0-9]{5}$")

# Regex to sanitize slugs for stations and operators
SLUG_CLEAN_REGEX = re.compile(r"[^a-zA-Z0-9_-]+")


class PersistenceStatus(str, Enum):
    """Outcome of attempting to persist a station record."""
    INSERTED = "INSERTED"
    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass
class StationPersistenceResult:
    """Detailed result of a single station persistence operation."""
    status: PersistenceStatus
    station_id: Optional[uuid.UUID] = None
    source_station_id: Optional[str] = None
    is_new: bool = False
    is_updated: bool = False
    is_unchanged: bool = False
    connectors_persisted: int = 0
    connectors_skipped: int = 0
    observation_persisted: bool = False
    observation_id: Optional[uuid.UUID] = None
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------
# Phase 2 Step 2.8: Canonical Persistence Results & Enums
# ------------------------------------------------------------------------------

class CanonicalPersistenceStatus(str, Enum):
    """Authoritative outcome of persisting a Step 2.7 canonical decision."""
    INSERTED = "INSERTED"            # Brand new canonical station created
    UPDATED = "UPDATED"              # Existing canonical station updated with new survivorship attributes
    UNCHANGED = "UNCHANGED"          # State already identical in database (idempotent no-op)
    LINKED = "LINKED"                # Source record(s) linked to established canonical station
    REVIEW_SKIPPED = "REVIEW_SKIPPED"# Decision was REVIEW; safely skipped from operational persistence
    BLOCKED_SKIPPED = "BLOCKED_SKIPPED"# Decision was blocked (validation rejection/quarantine); skipped
    FAILED = "FAILED"                # Atomic mutation failed and was rolled back


@dataclass
class CanonicalPersistenceResult:
    """Detailed result of persisting a single canonical decision."""
    cluster_id: str
    decision_state: CanonicalDecisionState
    status: CanonicalPersistenceStatus
    station_id: Optional[uuid.UUID] = None
    is_new: bool = False
    is_updated: bool = False
    is_unchanged: bool = False
    is_linked: bool = False
    is_review_skipped: bool = False
    is_blocked_skipped: bool = False
    source_links_created: int = 0
    source_links_updated: int = 0
    connectors_created: int = 0
    connectors_updated: int = 0
    connectors_persisted: int = 0
    connectors_skipped: int = 0
    observations_persisted: int = 0
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "decision_state": self.decision_state.value if hasattr(self.decision_state, "value") else str(self.decision_state),
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "station_id": str(self.station_id) if self.station_id else None,
            "is_new": self.is_new,
            "is_updated": self.is_updated,
            "is_unchanged": self.is_unchanged,
            "is_linked": self.is_linked,
            "is_review_skipped": self.is_review_skipped,
            "is_blocked_skipped": self.is_blocked_skipped,
            "source_links_created": self.source_links_created,
            "source_links_updated": self.source_links_updated,
            "connectors_created": self.connectors_created,
            "connectors_updated": self.connectors_updated,
            "connectors_persisted": self.connectors_persisted,
            "connectors_skipped": self.connectors_skipped,
            "observations_persisted": self.observations_persisted,
            "error": self.error,
            "warnings": self.warnings,
            "details": self.details,
        }


@dataclass
class BatchCanonicalPersistenceReport:
    """Structured report summarizing the persistence of a batch of canonical decisions."""
    total_decisions: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    linked: int = 0
    review_skipped: int = 0
    blocked_skipped: int = 0
    failed: int = 0
    total_stations_created: int = 0
    total_stations_updated: int = 0
    total_source_links_created: int = 0
    total_source_links_updated: int = 0
    total_connectors_persisted: int = 0
    total_observations_persisted: int = 0
    results: list[CanonicalPersistenceResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_decisions": self.total_decisions,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "linked": self.linked,
            "review_skipped": self.review_skipped,
            "blocked_skipped": self.blocked_skipped,
            "failed": self.failed,
            "total_stations_created": self.total_stations_created,
            "total_stations_updated": self.total_stations_updated,
            "total_source_links_created": self.total_source_links_created,
            "total_source_links_updated": self.total_source_links_updated,
            "total_connectors_persisted": self.total_connectors_persisted,
            "total_observations_persisted": self.total_observations_persisted,
            "errors_count": len(self.errors),
            "duration_seconds": round(self.duration_seconds, 2),
        }


def _scrub_secrets(text: Optional[str]) -> Optional[str]:
    """Sanitizes text by removing database passwords, tokens, and API keys."""
    if not text:
        return text
    # Mask postgresql://user:password@host
    s = re.sub(r"://([^:]+):([^@]+)@", r"://:***@", text)
    # Mask api_key=..., apikey=...
    s = re.sub(r"(api[_-]?key=)[^&\s'\"]+", r"***", s, flags=re.IGNORECASE)
    # Mask token=..., secret=...
    s = re.sub(r"(secret|token|password)=[^&\s'\"]+", r"=***", s, flags=re.IGNORECASE)
    return s


def _sanitize_slug(text: Optional[str], fallback: str = "item") -> str:
    """Produces a clean slug conforming to ^[a-zA-Z0-9][a-zA-Z0-9_-]*$."""
    if not text:
        return f"{fallback}-{uuid.uuid4().hex[:8]}"
    cleaned = SLUG_CLEAN_REGEX.sub("-", text.strip().lower()).strip("-")
    if not cleaned or not re.match(r"^[a-zA-Z0-9]", cleaned):
        return f"{fallback}-{uuid.uuid4().hex[:8]}"
    return cleaned[:180]


class IngestionPersistenceService:
    """Manages transactional database operations for the ChargePlus ingestion pipeline."""

    def __init__(self, db_conn_or_url: Optional[Union[str, Any]] = None):
        """Initializes service with a PostgreSQL connection, connection string, or None for dry-run."""
        if db_conn_or_url is None:
            self.conn = None
            self._owns_connection = False
        elif isinstance(db_conn_or_url, str):
            self.conn = psycopg2.connect(db_conn_or_url)
            self._owns_connection = True
        else:
            self.conn = db_conn_or_url
            self._owns_connection = False

    def close(self) -> None:
        """Closes the underlying database connection if owned by this service."""
        if self._owns_connection and self.conn and not self.conn.closed:
            self.conn.close()

    def __enter__(self) -> "IngestionPersistenceService":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # --------------------------------------------------------------------------
    # 1. Feed Registry & Operator Resolution
    # --------------------------------------------------------------------------

    def get_or_create_data_source(
        self,
        name: str = "open_charge_map",
        source_type: str = "api",
        base_url: Optional[str] = "https://api.openchargemap.io/v3/poi/",
        source_priority: int = 100,
        dry_run: bool = False,
        commit: bool = True,
    ) -> uuid.UUID:
        """Resolves or registers an external data source in public.data_sources."""
        if self.conn is None or dry_run:
            return uuid.uuid4()
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM public.data_sources WHERE name = %s;", (name,))
            row = cur.fetchone()
            if row:
                source_id = uuid.UUID(str(row["id"]))
            else:
                if dry_run:
                    return uuid.uuid4()
                source_id = uuid.uuid4()
                cur.execute(
                    """
                    INSERT INTO public.data_sources (id, name, source_type, base_url, source_priority, is_active)
                    VALUES (%s, %s, %s, %s, %s, true)
                    ON CONFLICT (name) DO UPDATE SET base_url = EXCLUDED.base_url
                    RETURNING id;
                    """,
                    (str(source_id), name, source_type, base_url, source_priority),
                )
                source_id = uuid.UUID(str(cur.fetchone()["id"]))
                if commit:
                    self.conn.commit()

            # Ensure mirrored in analytics.dim_source if not dry_run
            if not dry_run:
                self._ensure_dim_source(source_id, name, source_type, base_url, source_priority, commit=commit)

            return source_id

    def _ensure_dim_source(
        self,
        source_id: uuid.UUID,
        name: str,
        source_type: str,
        base_url: Optional[str],
        source_priority: int,
        commit: bool = True,
    ) -> None:
        """Mirrors public.data_sources row into analytics.dim_source for warehouse lookups."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analytics.dim_source (source_id, name, source_type, source_priority, is_active, base_url)
                VALUES (%s, %s, %s, %s, true, %s)
                ON CONFLICT (source_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    source_type = EXCLUDED.source_type,
                    base_url = EXCLUDED.base_url,
                    updated_at = now();
                """,
                (str(source_id), name, source_type, source_priority, base_url),
            )
            if commit:
                self.conn.commit()

    def get_or_create_operator(
        self,
        operator_name: Optional[str],
        operator_slug: Optional[str] = None,
        website_url: Optional[str] = None,
        support_phone: Optional[str] = None,
        dry_run: bool = False,
        commit: bool = True,
    ) -> uuid.UUID:
        """Resolves or registers a charging network operator in public.operators."""
        name = (operator_name or "Unknown Operator").strip()[:200]
        slug = _sanitize_slug(operator_slug or name, fallback="operator")

        if self.conn is None or dry_run:
            return uuid.uuid4()

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM public.operators WHERE slug = %s;", (slug,))
            row = cur.fetchone()
            if row:
                return uuid.UUID(str(row["id"]))

            # Fallback search by exact name if slug differed
            cur.execute("SELECT id FROM public.operators WHERE name = %s LIMIT 1;", (name,))
            row = cur.fetchone()
            if row:
                return uuid.UUID(str(row["id"]))

            if dry_run:
                return uuid.uuid4()

            op_id = uuid.uuid4()
            cur.execute(
                """
                INSERT INTO public.operators (id, name, slug, website_url, support_phone)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
                """,
                (str(op_id), name, slug, website_url, support_phone),
            )
            created_id = uuid.UUID(str(cur.fetchone()["id"]))
            if commit:
                self.conn.commit()
            return created_id

    # --------------------------------------------------------------------------
    # 2. Source-Link / Provenance Lookup
    # --------------------------------------------------------------------------

    def find_source_link(
        self,
        source_id: uuid.UUID,
        source_station_id: str,
    ) -> Optional[dict[str, Any]]:
        """Queries public.station_source_link to check if this source record was previously ingested."""
        if self.conn is None:
            return None
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, station_id, source_id, source_station_id, source_payload_hash, first_seen_at
                FROM public.station_source_link
                WHERE source_id = %s AND source_station_id = %s;
                """,
                (str(source_id), str(source_station_id)),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            return None

    # --------------------------------------------------------------------------
    # 3. Canonical Station & Connectors Persistence
    # --------------------------------------------------------------------------

    def persist_station(
        self,
        station: NormalizedStationRecord,
        raw_record: RawSourceRecord,
        data_source_id: uuid.UUID,
        dry_run: bool = False,
    ) -> StationPersistenceResult:
        """Persists or updates a normalized station record and its connectors idempotently."""
        warnings: list[str] = []
        source_station_id = station.source_station_id

        # 1. Check idempotency via station_source_link
        existing_link = self.find_source_link(data_source_id, source_station_id)
        current_hash = raw_record.payload_hash

        # Case A: Identical payload previously ingested -> UNCHANGED
        if existing_link and existing_link.get("source_payload_hash") == current_hash:
            station_id = uuid.UUID(str(existing_link["station_id"]))
            if not dry_run:
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.station_source_link
                        SET last_seen_at = now()
                        WHERE source_id = %s AND source_station_id = %s;
                        """,
                        (str(data_source_id), str(source_station_id)),
                    )
                    self.conn.commit()

            return StationPersistenceResult(
                status=PersistenceStatus.UNCHANGED,
                station_id=station_id,
                source_station_id=source_station_id,
                is_unchanged=True,
                connectors_persisted=len(station.connectors),
                warnings=warnings,
            )

        # Resolve operator
        operator_id = self.get_or_create_operator(
            operator_name=station.operator_name,
            operator_slug=station.operator_slug,
            dry_run=dry_run,
        )

        # Sanitize attributes to conform strictly with database check constraints
        postal_code: Optional[str] = None
        if station.postal_code and INDIAN_PIN_REGEX.match(station.postal_code.strip()):
            postal_code = station.postal_code.strip()
        elif station.postal_code:
            warnings.append(
                f"Postal code '{station.postal_code}' does not match Indian 6-digit PIN; stored as NULL in public.stations"
            )

        # Enforce chk_stations_hours: if 24_hours is true, opening/closing times MUST be NULL
        is_24_hours = bool(station.is_24_hours) if station.is_24_hours is not None else False
        is_public = bool(station.is_public) if station.is_public is not None else True
        opening_time = None if is_24_hours else station.opening_time
        closing_time = None if is_24_hours else station.closing_time

        # Map operational status to allowed database constraint enum
        op_status = station.operational_status.value if station.operational_status else "unknown"
        if op_status not in ("unknown", "operational", "temporarily_unavailable", "permanently_closed"):
            op_status = "unknown"

        # Case B: Existing station updated at source -> UPDATE
        if existing_link:
            station_id = uuid.UUID(str(existing_link["station_id"]))
            if dry_run:
                return StationPersistenceResult(
                    status=PersistenceStatus.UPDATED,
                    station_id=station_id,
                    source_station_id=source_station_id,
                    is_updated=True,
                    connectors_persisted=len(station.connectors),
                    warnings=warnings,
                )

            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.stations
                    SET
                        name = %s,
                        operator_id = %s,
                        address_line = %s,
                        locality = %s,
                        city = %s,
                        state = %s,
                        postal_code = %s,
                        country = %s,
                        latitude = %s,
                        longitude = %s,
                        opening_time = %s,
                        closing_time = %s,
                        is_24_hours = %s,
                        access_type = %s,
                        is_public = %s,
                        operational_status = %s,
                        phone = %s,
                        website_url = %s,
                        last_verified_at = %s,
                        updated_at = now()
                    WHERE id = %s;
                    """,
                    (
                        station.name[:300],
                        str(operator_id),
                        station.address_line,
                        station.locality,
                        (station.city or "Mumbai")[:120],
                        (station.state or "Maharashtra")[:120],
                        postal_code,
                        (station.country or "India")[:120],
                        station.latitude,
                        station.longitude,
                        opening_time,
                        closing_time,
                        is_24_hours,
                        station.access_type,
                        is_public,
                        op_status,
                        station.phone,
                        station.website_url,
                        raw_record.source_timestamp,
                        str(station_id),
                    ),
                )

                # Synchronize connectors: update existing or insert new capacity groups
                conn_persisted, conn_skipped = self._sync_connectors(cur, station_id, station.connectors, warnings)

                # Update provenance link
                cur.execute(
                    """
                    UPDATE public.station_source_link
                    SET
                        source_payload_hash = %s,
                        last_ingested_at = now(),
                        last_seen_at = now(),
                        updated_at = now()
                    WHERE id = %s;
                    """,
                    (current_hash, str(existing_link["id"])),
                )
                self.conn.commit()

            return StationPersistenceResult(
                status=PersistenceStatus.UPDATED,
                station_id=station_id,
                source_station_id=source_station_id,
                is_updated=True,
                connectors_persisted=conn_persisted,
                connectors_skipped=conn_skipped,
                warnings=warnings,
            )

        # Case C: New station from this source -> INSERT
        station_id = uuid.uuid4()
        station_slug = f"{_sanitize_slug(station.name, fallback='station')}-{station_id.hex[:8]}"

        if dry_run:
            return StationPersistenceResult(
                status=PersistenceStatus.INSERTED,
                station_id=station_id,
                source_station_id=source_station_id,
                is_new=True,
                connectors_persisted=len(station.connectors),
                warnings=warnings,
            )

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.stations (
                    id, slug, name, operator_id, address_line, locality, city, state, postal_code, country,
                    latitude, longitude, opening_time, closing_time, is_24_hours, access_type, is_public,
                    operational_status, phone, website_url, last_verified_at, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, now(), now()
                );
                """,
                (
                    str(station_id),
                    station_slug,
                    station.name[:300],
                    str(operator_id),
                    station.address_line,
                    station.locality,
                    (station.city or "Mumbai")[:120],
                    (station.state or "Maharashtra")[:120],
                    postal_code,
                    (station.country or "India")[:120],
                    station.latitude,
                    station.longitude,
                    opening_time,
                    closing_time,
                    is_24_hours,
                    station.access_type,
                    is_public,
                    op_status,
                    station.phone,
                    station.website_url,
                    raw_record.source_timestamp,
                ),
            )

            # Insert connectors
            conn_persisted, conn_skipped = self._sync_connectors(cur, station_id, station.connectors, warnings)

            # Insert source provenance link
            cur.execute(
                """
                INSERT INTO public.station_source_link (
                    station_id, source_id, source_station_id, source_url,
                    first_seen_at, last_seen_at, last_ingested_at, source_payload_hash, is_active
                ) VALUES (%s, %s, %s, %s, now(), now(), now(), %s, true);
                """,
                (
                    str(station_id),
                    str(data_source_id),
                    str(source_station_id),
                    raw_record.source_url,
                    current_hash,
                ),
            )
            self.conn.commit()

        return StationPersistenceResult(
            status=PersistenceStatus.INSERTED,
            station_id=station_id,
            source_station_id=source_station_id,
            is_new=True,
            connectors_persisted=conn_persisted,
            connectors_skipped=conn_skipped,
            warnings=warnings,
        )

    def _sync_connectors(
        self,
        cur: Any,
        station_id: uuid.UUID,
        connectors: list[NormalizedConnectorRecord],
        warnings: list[str],
    ) -> tuple[int, int]:
        """Synchronizes connector capacity groups into public.connectors while enforcing database constraints."""
        # Aggregate identical capacity groups (connector_type, power_kw, charging_standard)
        # to satisfy uq_connectors_station_type_power
        grouped: dict[tuple[str, float, str], int] = {}
        persisted_count = 0
        skipped_count = 0

        for idx, c in enumerate(connectors):
            # Enforce database check constraint on connector_type
            if c.connector_type not in ALLOWED_DB_CONNECTOR_TYPES:
                warnings.append(
                    f"Connector [{idx}] type '{c.connector_type}' not in database enum {ALLOWED_DB_CONNECTOR_TYPES}; skipped"
                )
                skipped_count += 1
                continue

            # Enforce NOT NULL and positive power_kw without inventing power
            if c.power_kw is None or c.power_kw <= 0:
                warnings.append(
                    f"Connector [{idx}] missing or non-positive power_kw ({c.power_kw}); skipped to prevent inventing power"
                )
                skipped_count += 1
                continue

            key = (c.connector_type, float(c.power_kw), (c.charging_standard or ""))
            qty = max(1, c.quantity)
            grouped[key] = grouped.get(key, 0) + qty

        # Delete existing connectors for this station before re-inserting reconciled set
        cur.execute("DELETE FROM public.connectors WHERE station_id = %s;", (str(station_id),))

        for (c_type, p_kw, std), total_qty in grouped.items():
            cur.execute(
                """
                INSERT INTO public.connectors (
                    id, station_id, connector_type, charging_standard, power_kw, quantity, currency
                ) VALUES (%s, %s, %s, %s, %s, %s, 'INR');
                """,
                (
                    str(uuid.uuid4()),
                    str(station_id),
                    c_type,
                    std or None,
                    p_kw,
                    total_qty,
                ),
            )
            persisted_count += total_qty

        return persisted_count, skipped_count

    # --------------------------------------------------------------------------
    # 4. Observation Persistence (Operational Log & Canonical Warehouse Fact)
    # --------------------------------------------------------------------------

    def persist_observation(
        self,
        station_id: uuid.UUID,
        data_source_id: uuid.UUID,
        obs: NormalizedObservationRecord,
        total_connectors: int,
        raw_payload_hash: Optional[str] = None,
        dry_run: bool = False,
    ) -> Optional[uuid.UUID]:
        """Persists a legitimate point-in-time observation to public.station_observations

        and mirrors it to analytics.fact_station_observation.
        """
        obs_id = uuid.uuid4()
        if dry_run:
            return obs_id

        # 1. Operational Table: public.station_observations
        avail_status = obs.availability_status.value if obs.availability_status else "unknown"
        if avail_status not in ("available", "busy", "broken", "unknown"):
            avail_status = "unknown"

        q_level = obs.queue_level.value if obs.queue_level else "unknown"
        if q_level not in ("none", "short", "medium", "long", "unknown"):
            q_level = "unknown"

        tot_conn = max(0, total_connectors)
        avail_conn = obs.available_connectors
        if avail_conn is not None:
            avail_conn = min(max(0, avail_conn), tot_conn)

        obs_time = obs.observed_at if obs.observed_at.tzinfo else obs.observed_at.replace(tzinfo=timezone.utc)
        if obs.retrieved_at:
            retrieved_utc = obs.retrieved_at if obs.retrieved_at.tzinfo else obs.retrieved_at.replace(tzinfo=timezone.utc)
        else:
            retrieved_utc = datetime.now(timezone.utc)
        recv_time = max(obs_time, retrieved_utc)  # Enforce chk_observations_causal_time (received_at >= observed_at)

        with self.conn.cursor() as cur:
            # 1. Idempotency check: Skip duplicate insertion of identical observation
            if raw_payload_hash:
                cur.execute(
                    """
                    SELECT id FROM public.station_observations
                    WHERE station_id = %s AND observed_at = %s AND source_payload_hash = %s
                    LIMIT 1;
                    """,
                    (str(station_id), obs_time, raw_payload_hash),
                )
                if cur.fetchone():
                    return None

            cur.execute(
                """
                INSERT INTO public.station_observations (
                    id, station_id, source_id, availability_status, queue_level,
                    available_connectors, total_connectors, observed_at, received_at,
                    source_payload_hash, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now());
                """,
                (
                    str(obs_id),
                    str(station_id),
                    str(data_source_id),
                    avail_status,
                    q_level,
                    avail_conn,
                    tot_conn,
                    obs_time,
                    recv_time,
                    raw_payload_hash,
                ),
            )

            # 2. Canonical Warehouse Fact: analytics.fact_station_observation
            self._persist_warehouse_observation(
                cur=cur,
                obs_id=obs_id,
                station_id=station_id,
                source_id=data_source_id,
                obs_time=obs_time,
                recv_time=recv_time,
                avail_status=avail_status,
                q_level=q_level,
                avail_conn=avail_conn,
                tot_conn=tot_conn,
                raw_payload_hash=raw_payload_hash,
            )

            self.conn.commit()

        return obs_id

    def _persist_warehouse_observation(
        self,
        cur: Any,
        obs_id: uuid.UUID,
        station_id: uuid.UUID,
        source_id: uuid.UUID,
        obs_time: datetime,
        recv_time: datetime,
        avail_status: str,
        q_level: str,
        avail_conn: Optional[int],
        tot_conn: int,
        raw_payload_hash: Optional[str],
    ) -> None:
        """Resolves dimensional foreign keys and inserts into analytics.fact_station_observation."""
        # 1. Resolve source_key
        cur.execute("SELECT source_key FROM analytics.dim_source WHERE source_id = %s;", (str(source_id),))
        source_row = cur.fetchone()
        if not source_row:
            return  # Safety guard if source not mirrored
        source_key = source_row[0]

        # 2. Resolve station_key from analytics.dim_station (or synchronize from public.stations)
        cur.execute(
            "SELECT station_key FROM analytics.dim_station WHERE station_id = %s AND is_current = true;",
            (str(station_id),),
        )
        station_row = cur.fetchone()
        if station_row:
            station_key = station_row[0]
        else:
            station_key = self._sync_dim_station(cur, station_id)
            if not station_key:
                return

        # 3. Calculate deterministic conformed date_key and time_key in UTC
        # date_key = YYYYMMDD
        date_key = int(obs_time.astimezone(timezone.utc).strftime("%Y%m%d"))
        # time_key = 15-min slot index (0..95) = hour * 4 + minute // 15
        time_key = obs_time.astimezone(timezone.utc).hour * 4 + obs_time.astimezone(timezone.utc).minute // 15

        # 4. Insert fact row
        cur.execute(
            """
            INSERT INTO analytics.fact_station_observation (
                observation_id, station_key, date_key, time_key, source_key,
                observed_at, received_at, availability_status, queue_level,
                available_connectors, total_connectors, source_payload_hash, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (observation_id) DO NOTHING;
            """,
            (
                str(obs_id),
                station_key,
                date_key,
                time_key,
                source_key,
                obs_time,
                recv_time,
                avail_status,
                q_level,
                avail_conn,
                tot_conn,
                raw_payload_hash,
            ),
        )

    def _sync_dim_station(self, cur: Any, station_id: uuid.UUID) -> Optional[int]:
        """Synchronizes an operational station into analytics.dim_station (along with dim_operator & dim_location)."""
        # Fetch station attributes
        cur.execute(
            """
            SELECT s.name, s.operator_id, s.address_line, s.locality, s.city, s.state, s.postal_code, s.country,
                   s.latitude, s.longitude, s.access_type, s.is_public, s.operational_status, s.is_24_hours,
                   s.opening_time, s.closing_time, o.name AS operator_name, o.slug AS operator_slug
            FROM public.stations s
            JOIN public.operators o ON s.operator_id = o.id
            WHERE s.id = %s;
            """,
            (str(station_id),),
        )
        row = cur.fetchone()
        if not row:
            return None

        (
            name, op_id, address_line, locality, city, state, postal_code, country,
            lat, lng, access_type, is_pub, op_status, is_24h, open_t, close_t, op_name, op_slug
        ) = row

        # Resolve operator_key in analytics.dim_operator
        cur.execute("SELECT operator_key FROM analytics.dim_operator WHERE operator_id = %s;", (str(op_id),))
        op_row = cur.fetchone()
        if op_row:
            operator_key = op_row[0]
        else:
            cur.execute(
                """
                INSERT INTO analytics.dim_operator (operator_id, operator_name, slug)
                VALUES (%s, %s, %s)
                RETURNING operator_key;
                """,
                (str(op_id), op_name, op_slug),
            )
            operator_key = cur.fetchone()[0]

        # Resolve location_key in analytics.dim_location
        cur.execute(
            """
            SELECT location_key FROM analytics.dim_location
            WHERE country = %s AND state = %s AND city = %s
              AND COALESCE(locality, '') = COALESCE(%s, '')
              AND COALESCE(postal_code, '') = COALESCE(%s, '');
            """,
            (country, state, city, locality, postal_code),
        )
        loc_row = cur.fetchone()
        if loc_row:
            location_key = loc_row[0]
        else:
            cur.execute(
                """
                INSERT INTO analytics.dim_location (country, state, city, locality, postal_code)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING location_key;
                """,
                (country, state, city, locality, postal_code),
            )
            location_key = cur.fetchone()[0]

        is_pub_bool = bool(is_pub) if is_pub is not None else True
        is_24h_bool = bool(is_24h) if is_24h is not None else False

        # Insert into analytics.dim_station
        cur.execute(
            """
            INSERT INTO analytics.dim_station (
                station_id, station_name, operator_key, location_key, latitude, longitude,
                address, access_type, is_public, operational_status, is_24_hours,
                opening_time, closing_time, effective_from, is_current, version
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, now(), true, 1
            )
            RETURNING station_key;
            """,
            (
                str(station_id), name, operator_key, location_key, lat, lng,
                address_line, access_type, is_pub_bool, op_status, is_24h_bool, open_t, close_t
            ),
        )
        return cur.fetchone()[0]

    # --------------------------------------------------------------------------
    # 5. Canonical Operational Loading & Mutation Isolation (Phase 2 Step 2.8)
    # --------------------------------------------------------------------------

    def fetch_existing_canonical_stations(
        self,
        bounding_box: Optional[tuple[float, float, float, float]] = None,
    ) -> list[ExistingCanonicalStation]:
        """Queries operational database for existing canonical stations, connectors, and source links.
        
        Enables Step 2.7 CanonicalDeduplicationEngine to evaluate incoming records
        against already-established operational state without inventing identity links.
        """
        if self.conn is None:
            return []

        sql = """
            SELECT s.id, s.name, s.latitude, s.longitude, s.address_line, s.locality,
                   s.postal_code, o.name AS operator_name, o.slug AS operator_slug
            FROM public.stations s
            LEFT JOIN public.operators o ON s.operator_id = o.id
        """
        params: list[Any] = []
        if bounding_box:
            min_lat, min_lng, max_lat, max_lng = bounding_box
            sql += " WHERE s.latitude BETWEEN %s AND %s AND s.longitude BETWEEN %s AND %s"
            params.extend([min_lat, max_lat, min_lng, max_lng])
        sql += ";"

        stations_list: list[ExistingCanonicalStation] = []
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            for r in rows:
                stn_id = str(r["id"])

                # Query source links for this station
                cur.execute(
                    """
                    SELECT ds.name AS source_id, sl.source_station_id
                    FROM public.station_source_link sl
                    JOIN public.data_sources ds ON sl.source_id = ds.id
                    WHERE sl.station_id = %s;
                    """,
                    (stn_id,),
                )
                link_rows = cur.fetchall()
                links = [(str(link["source_id"]), str(link["source_station_id"])) for link in link_rows]

                # Query connectors for this station
                cur.execute(
                    """
                    SELECT connector_type, charging_standard, power_kw, quantity, pricing_type, price_per_kwh, price_per_session
                    FROM public.connectors
                    WHERE station_id = %s;
                    """,
                    (stn_id,),
                )
                conn_rows = cur.fetchall()
                conns: list[NormalizedConnectorRecord] = []
                for c in conn_rows:
                    conns.append(
                        NormalizedConnectorRecord(
                            connector_type=c["connector_type"],
                            charging_standard=c["charging_standard"],
                            power_kw=float(c["power_kw"]) if c["power_kw"] is not None else None,
                            quantity=c["quantity"],
                            pricing_type=c["pricing_type"] or "unknown",
                            price_per_kwh=float(c["price_per_kwh"]) if c["price_per_kwh"] is not None else None,
                            price_per_session=float(c["price_per_session"]) if c["price_per_session"] is not None else None,
                        )
                    )

                stations_list.append(
                    ExistingCanonicalStation(
                        canonical_station_id=stn_id,
                        name=r["name"],
                        operator_name=r["operator_name"],
                        operator_slug=r["operator_slug"],
                        latitude=float(r["latitude"]),
                        longitude=float(r["longitude"]),
                        address_line=r["address_line"],
                        locality=r["locality"],
                        postal_code=r["postal_code"],
                        connectors=conns,
                        source_links=links,
                    )
                )

        return stations_list

    def persist_canonical_decision(
        self,
        decision: CanonicalResolutionDecision,
        dry_run: bool = False,
    ) -> CanonicalPersistenceResult:
        """Safely and transactionally persists a single CanonicalResolutionDecision into the database.
        
        Guarantees:
        - 2.7 DECIDES. 2.8 PERSISTS. Does not re-evaluate or invent identity matches.
        - Transaction boundary: atomic per decision; complete success or rollback.
        - Idempotency: repeated execution leaves identical database state.
        - REVIEW and BLOCKED decisions never mutate canonical operational state.
        - Preserves external provenance in public.station_source_link.
        """
        warnings: list[str] = []

        # 1. Gating check: Blocked decisions (fatal validation rejection or quarantine)
        if decision.is_blocked:
            return CanonicalPersistenceResult(
                cluster_id=decision.cluster_id,
                decision_state=decision.decision_state,
                status=CanonicalPersistenceStatus.BLOCKED_SKIPPED,
                is_blocked_skipped=True,
                warnings=["Decision is blocked by validation gating; operational persistence skipped."],
                details={"blocking_reasons": decision.blocking_reasons},
            )

        # 2. REVIEW decisions: Cannot automatically mutate canonical operational state
        if decision.decision_state == CanonicalDecisionState.REVIEW:
            return CanonicalPersistenceResult(
                cluster_id=decision.cluster_id,
                decision_state=decision.decision_state,
                status=CanonicalPersistenceStatus.REVIEW_SKIPPED,
                is_review_skipped=True,
                warnings=["Decision marked for human review; operational persistence skipped."],
                details={"conflicts": decision.conflicts, "reasons": decision.reasons},
            )

        # 3. Dry-run execution simulation (zero database writes)
        if dry_run or self.conn is None:
            return self._simulate_decision_dry_run(decision)

        # 4. Transactional execution
        try:
            with self.conn.cursor() as cur:
                if decision.decision_state == CanonicalDecisionState.KEEP_SEPARATE:
                    result = self._persist_keep_separate(cur, decision, warnings)
                elif decision.decision_state == CanonicalDecisionState.MERGE:
                    result = self._persist_merge(cur, decision, warnings)
                elif decision.decision_state == CanonicalDecisionState.LINK_TO_CANONICAL:
                    result = self._persist_link_to_canonical(cur, decision, warnings)
                else:
                    raise ValueError(f"Unsupported decision state: {decision.decision_state}")

            self.conn.commit()
            return result

        except Exception as exc:
            if self.conn is not None and not getattr(self.conn, "closed", False):
                self.conn.rollback()
            err_msg = _scrub_secrets(str(exc))
            logger.error("Failed to persist canonical decision %s: %s", decision.cluster_id, err_msg)
            return CanonicalPersistenceResult(
                cluster_id=decision.cluster_id,
                decision_state=decision.decision_state,
                status=CanonicalPersistenceStatus.FAILED,
                error=err_msg,
                warnings=warnings,
            )

    def persist_canonical_batch(
        self,
        decisions: list[CanonicalResolutionDecision],
        dry_run: bool = False,
    ) -> BatchCanonicalPersistenceReport:
        """Persists a batch of CanonicalResolutionDecisions with record-level transaction isolation."""
        start_time = time.time()
        report = BatchCanonicalPersistenceReport(total_decisions=len(decisions))

        for dec in decisions:
            res = self.persist_canonical_decision(dec, dry_run=dry_run)
            report.results.append(res)

            if res.status == CanonicalPersistenceStatus.INSERTED:
                report.inserted += 1
                report.total_stations_created += 1
            elif res.status == CanonicalPersistenceStatus.UPDATED:
                report.updated += 1
                report.total_stations_updated += 1
            elif res.status == CanonicalPersistenceStatus.UNCHANGED:
                report.unchanged += 1
            elif res.status == CanonicalPersistenceStatus.LINKED:
                report.linked += 1
            elif res.status == CanonicalPersistenceStatus.REVIEW_SKIPPED:
                report.review_skipped += 1
            elif res.status == CanonicalPersistenceStatus.BLOCKED_SKIPPED:
                report.blocked_skipped += 1
            elif res.status == CanonicalPersistenceStatus.FAILED:
                report.failed += 1
                if res.error:
                    report.errors.append(f"Cluster {dec.cluster_id}: {res.error}")

            report.total_source_links_created += res.source_links_created
            report.total_source_links_updated += res.source_links_updated
            report.total_connectors_persisted += res.connectors_persisted
            report.total_observations_persisted += res.observations_persisted

        report.duration_seconds = time.time() - start_time
        return report

    def _persist_keep_separate(
        self,
        cur: Any,
        decision: CanonicalResolutionDecision,
        warnings: list[str],
    ) -> CanonicalPersistenceResult:
        """Persists a distinct, standalone station record idempotently."""
        records = decision.participating_records
        if not records:
            raise ValueError(f"KEEP_SEPARATE decision {decision.cluster_id} contains no participating records")

        rec = records[0]
        data_source_id = self.get_or_create_data_source(name=rec.source_id)

        # Check existing link in public.station_source_link
        cur.execute(
            """
            SELECT id, station_id, source_payload_hash, first_seen_at
            FROM public.station_source_link
            WHERE source_id = %s AND source_station_id = %s;
            """,
            (str(data_source_id), str(rec.source_station_id)),
        )
        existing_link = cur.fetchone()
        link_dict = dict(existing_link) if hasattr(existing_link, "keys") else (
            {"id": existing_link[0], "station_id": existing_link[1], "source_payload_hash": existing_link[2]}
            if existing_link else None
        )

        current_hash = rec.extra_metadata.get("payload_hash") if rec.extra_metadata else None

        # Case A: Identical payload previously ingested -> UNCHANGED
        if link_dict and current_hash and link_dict.get("source_payload_hash") == current_hash:
            stn_id = uuid.UUID(str(link_dict["station_id"]))
            cur.execute(
                """
                UPDATE public.station_source_link
                SET last_seen_at = now()
                WHERE id = %s;
                """,
                (str(link_dict["id"]),),
            )
            return CanonicalPersistenceResult(
                cluster_id=decision.cluster_id,
                decision_state=decision.decision_state,
                status=CanonicalPersistenceStatus.UNCHANGED,
                station_id=stn_id,
                is_unchanged=True,
                source_links_updated=1,
                connectors_persisted=len(rec.connectors),
                warnings=warnings,
            )

        # Case B: Existing station updated -> UPDATED
        if link_dict:
            stn_id = uuid.UUID(str(link_dict["station_id"]))
            attrs = self._extract_canonical_station_attributes(decision, warnings)
            self._update_station_record(cur, stn_id, attrs)
            conn_persisted, conn_created, conn_updated, conn_skipped = self._reconcile_and_persist_connectors(
                cur, stn_id, decision, warnings
            )
            cur.execute(
                """
                UPDATE public.station_source_link
                SET source_payload_hash = %s, last_ingested_at = now(), last_seen_at = now(), updated_at = now()
                WHERE id = %s;
                """,
                (current_hash, str(link_dict["id"])),
            )
            self._sync_dim_station_scd2(cur, stn_id)
            obs_count = self._persist_decision_observations(cur, stn_id, decision)

            return CanonicalPersistenceResult(
                cluster_id=decision.cluster_id,
                decision_state=decision.decision_state,
                status=CanonicalPersistenceStatus.UPDATED,
                station_id=stn_id,
                is_updated=True,
                source_links_updated=1,
                connectors_persisted=conn_persisted,
                connectors_created=conn_created,
                connectors_updated=conn_updated,
                connectors_skipped=conn_skipped,
                observations_persisted=obs_count,
                warnings=warnings,
            )

        # Case C: Brand new standalone station -> INSERTED
        stn_id = uuid.uuid4()
        attrs = self._extract_canonical_station_attributes(decision, warnings)
        self._insert_station_record(cur, stn_id, attrs)
        conn_persisted, conn_created, conn_updated, conn_skipped = self._reconcile_and_persist_connectors(
            cur, stn_id, decision, warnings
        )
        cur.execute(
            """
            INSERT INTO public.station_source_link (
                station_id, source_id, source_station_id, source_url,
                first_seen_at, last_seen_at, last_ingested_at, source_payload_hash, is_active
            ) VALUES (%s, %s, %s, %s, now(), now(), now(), %s, true);
            """,
            (
                str(stn_id),
                str(data_source_id),
                str(rec.source_station_id),
                rec.extra_metadata.get("source_url") if rec.extra_metadata else None,
                current_hash,
            ),
        )
        self._sync_dim_station_scd2(cur, stn_id)
        obs_count = self._persist_decision_observations(cur, stn_id, decision)

        return CanonicalPersistenceResult(
            cluster_id=decision.cluster_id,
            decision_state=decision.decision_state,
            status=CanonicalPersistenceStatus.INSERTED,
            station_id=stn_id,
            is_new=True,
            source_links_created=1,
            connectors_persisted=conn_persisted,
            connectors_created=conn_created,
            connectors_updated=conn_updated,
            connectors_skipped=conn_skipped,
            observations_persisted=obs_count,
            warnings=warnings,
        )

    def _persist_merge(
        self,
        cur: Any,
        decision: CanonicalResolutionDecision,
        warnings: list[str],
    ) -> CanonicalPersistenceResult:
        """Persists a multi-source MERGE cluster into a single canonical station representation."""
        records = decision.participating_records
        if not records:
            raise ValueError(f"MERGE decision {decision.cluster_id} contains no participating records")

        # Check existing links for all participating sources
        existing_links: list[dict[str, Any]] = []
        for src_id_str, src_stn_id in decision.participating_source_identities:
            ds_id = self.get_or_create_data_source(name=src_id_str)
            cur.execute(
                """
                SELECT id, station_id, source_id, source_station_id, source_payload_hash
                FROM public.station_source_link
                WHERE source_id = %s AND source_station_id = %s;
                """,
                (str(ds_id), str(src_stn_id)),
            )
            row = cur.fetchone()
            if row:
                row_dict = dict(row) if hasattr(row, "keys") else {
                    "id": row[0], "station_id": row[1], "source_id": row[2],
                    "source_station_id": row[3], "source_payload_hash": row[4]
                }
                existing_links.append(row_dict)

        # Check for cross-station conflict
        linked_station_ids = {str(link["station_id"]) for link in existing_links}
        if len(linked_station_ids) > 1:
            raise ValueError(
                f"Unsafe multi-canonical bridge in MERGE {decision.cluster_id}: sources are already linked to multiple distinct stations: {sorted(list(linked_station_ids))}"
            )

        is_new = len(linked_station_ids) == 0
        attrs = self._extract_canonical_station_attributes(decision, warnings)

        if is_new:
            stn_id = uuid.uuid4()
            self._insert_station_record(cur, stn_id, attrs)
        else:
            stn_id = uuid.UUID(list(linked_station_ids)[0])
            self._update_station_record(cur, stn_id, attrs)

        # Reconcile connectors (two-level deduplicated connectors from Step 2.7)
        conn_persisted, conn_created, conn_updated, conn_skipped = self._reconcile_and_persist_connectors(
            cur, stn_id, decision, warnings
        )

        # Reconcile source links for all participating identities
        links_created, links_updated = self._reconcile_and_persist_source_links(cur, stn_id, decision)

        # Synchronize dim_station SCD2
        self._sync_dim_station_scd2(cur, stn_id)

        # Observations
        obs_count = self._persist_decision_observations(cur, stn_id, decision)

        status = CanonicalPersistenceStatus.INSERTED if is_new else CanonicalPersistenceStatus.UPDATED

        return CanonicalPersistenceResult(
            cluster_id=decision.cluster_id,
            decision_state=decision.decision_state,
            status=status,
            station_id=stn_id,
            is_new=is_new,
            is_updated=not is_new,
            source_links_created=links_created,
            source_links_updated=links_updated,
            connectors_persisted=conn_persisted,
            connectors_created=conn_created,
            connectors_updated=conn_updated,
            connectors_skipped=conn_skipped,
            observations_persisted=obs_count,
            warnings=warnings,
        )

    def _persist_link_to_canonical(
        self,
        cur: Any,
        decision: CanonicalResolutionDecision,
        warnings: list[str],
    ) -> CanonicalPersistenceResult:
        """Links one or more source records to an established canonical station."""
        if not decision.canonical_station_id:
            raise ValueError(f"LINK_TO_CANONICAL decision {decision.cluster_id} is missing target canonical_station_id")

        stn_id = uuid.UUID(str(decision.canonical_station_id))

        # Verify station exists
        cur.execute("SELECT id FROM public.stations WHERE id = %s;", (str(stn_id),))
        if not cur.fetchone():
            raise ValueError(f"Target canonical station {stn_id} not found in public.stations")

        # Update station attributes using survivorship (without overwriting populated with NULL)
        attrs = self._extract_canonical_station_attributes(decision, warnings)
        self._update_station_record(cur, stn_id, attrs)

        # Reconcile connectors
        conn_persisted, conn_created, conn_updated, conn_skipped = self._reconcile_and_persist_connectors(
            cur, stn_id, decision, warnings
        )

        # Reconcile source links
        links_created, links_updated = self._reconcile_and_persist_source_links(cur, stn_id, decision)

        # Synchronize dim_station SCD2
        self._sync_dim_station_scd2(cur, stn_id)

        # Observations
        obs_count = self._persist_decision_observations(cur, stn_id, decision)

        return CanonicalPersistenceResult(
            cluster_id=decision.cluster_id,
            decision_state=decision.decision_state,
            status=CanonicalPersistenceStatus.LINKED,
            station_id=stn_id,
            is_linked=True,
            source_links_created=links_created,
            source_links_updated=links_updated,
            connectors_persisted=conn_persisted,
            connectors_created=conn_created,
            connectors_updated=conn_updated,
            connectors_skipped=conn_skipped,
            observations_persisted=obs_count,
            warnings=warnings,
        )

    def _extract_canonical_station_attributes(
        self,
        decision: CanonicalResolutionDecision,
        warnings: list[str],
    ) -> dict[str, Any]:
        """Extracts and sanitizes canonical station attributes from decision and participating records."""
        records = decision.participating_records
        r0 = records[0] if records else None

        # 1. Name
        name = None
        if "name" in decision.field_survivorship and decision.field_survivorship["name"].canonical_value:
            name = str(decision.field_survivorship["name"].canonical_value).strip()
        elif r0:
            name = r0.name.strip()
        else:
            name = "Canonical EV Station"

        # 2. Coordinates
        lat, lng = None, None
        if "coordinates" in decision.field_survivorship and decision.field_survivorship["coordinates"].canonical_value:
            lat, lng = decision.field_survivorship["coordinates"].canonical_value
        elif r0:
            lat, lng = r0.latitude, r0.longitude

        # 3. Operator
        op_id = None
        if "operator" in decision.field_survivorship and decision.field_survivorship["operator"].canonical_value:
            op_dict = decision.field_survivorship["operator"].canonical_value
            op_id = self.get_or_create_operator(
                operator_name=op_dict.get("name"),
                operator_slug=op_dict.get("slug"),
                commit=False,
            )
        else:
            # Fallback across participating records
            for r in records:
                if r.operator_name or r.operator_slug:
                    op_id = self.get_or_create_operator(
                        operator_name=r.operator_name,
                        operator_slug=r.operator_slug,
                        commit=False,
                    )
                    break
            if op_id is None:
                op_id = self.get_or_create_operator(operator_name="Unknown Operator", commit=False)

        # 4. Location & Address Fields
        addr = next((r.address_line for r in records if r.address_line), None)
        loc = next((r.locality for r in records if r.locality), None)
        city = next((r.city for r in records if r.city), "Mumbai")
        state = next((r.state for r in records if r.state), "Maharashtra")
        ctry = next((r.country for r in records if r.country), "India")

        raw_pin = next((r.postal_code for r in records if r.postal_code), None)
        postal_code = None
        if raw_pin and INDIAN_PIN_REGEX.match(raw_pin.strip()):
            postal_code = raw_pin.strip()
        elif raw_pin:
            warnings.append(f"Postal code '{raw_pin}' does not match Indian 6-digit PIN; stored as NULL in public.stations")

        # 5. Operating Hours
        has_24h = any(bool(r.is_24_hours) for r in records if r.is_24_hours is not None)
        if has_24h:
            is_24_hours = True
            opening_time = None
            closing_time = None
        else:
            is_24_hours = False
            rec_with_hours = next((r for r in records if r.opening_time and r.closing_time), None)
            if rec_with_hours:
                opening_time = rec_with_hours.opening_time
                closing_time = rec_with_hours.closing_time
            else:
                opening_time = None
                closing_time = None

        # 6. Operational Status
        status_precedence = {"operational": 3, "temporarily_unavailable": 2, "permanently_closed": 1, "unknown": 0}
        best_status = "unknown"
        best_score = -1
        for r in records:
            s_val = r.operational_status.value if hasattr(r.operational_status, "value") else str(r.operational_status or "unknown")
            score = status_precedence.get(s_val, 0)
            if score > best_score:
                best_score = score
                best_status = s_val if s_val in status_precedence else "unknown"

        # 7. Contact & Access
        access_type = next((r.access_type for r in records if r.access_type), None)
        is_public = next((r.is_public for r in records if r.is_public is not None), True)
        phone = next((r.phone for r in records if r.phone), None)
        website_url = next((r.website_url for r in records if r.website_url), None)

        # 8. Last Verified
        last_verified = None
        for r in records:
            meta = getattr(r, "extra_metadata", None) or getattr(r, "raw_source_metadata", None) or {}
            ts = meta.get("source_timestamp") if isinstance(meta, dict) else None
            if ts:
                if last_verified is None or ts > last_verified:
                    last_verified = ts

        return {
            "name": name,
            "latitude": lat,
            "longitude": lng,
            "operator_id": op_id,
            "address_line": addr,
            "locality": loc,
            "city": city,
            "state": state,
            "postal_code": postal_code,
            "country": ctry,
            "is_24_hours": is_24_hours,
            "opening_time": opening_time,
            "closing_time": closing_time,
            "operational_status": best_status,
            "access_type": access_type,
            "is_public": is_public,
            "phone": phone,
            "website_url": website_url,
            "last_verified_at": last_verified,
        }

    def _insert_station_record(
        self,
        cur: Any,
        station_id: uuid.UUID,
        attrs: dict[str, Any],
    ) -> None:
        """Inserts a newly created canonical station row into public.stations."""
        station_slug = f"{_sanitize_slug(attrs['name'], fallback='station')}-{station_id.hex[:8]}"
        cur.execute(
            """
            INSERT INTO public.stations (
                id, slug, name, operator_id, address_line, locality, city, state, postal_code, country,
                latitude, longitude, opening_time, closing_time, is_24_hours, access_type, is_public,
                operational_status, phone, website_url, last_verified_at, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, now(), now()
            );
            """,
            (
                str(station_id), station_slug, attrs["name"][:300], str(attrs["operator_id"]),
                attrs["address_line"], attrs["locality"], (attrs["city"] or "Mumbai")[:120],
                (attrs["state"] or "Maharashtra")[:120], attrs["postal_code"],
                (attrs["country"] or "India")[:120], attrs["latitude"], attrs["longitude"],
                attrs["opening_time"], attrs["closing_time"], attrs["is_24_hours"],
                attrs["access_type"], attrs["is_public"], attrs["operational_status"],
                attrs["phone"], attrs["website_url"], attrs["last_verified_at"],
            ),
        )

    def _update_station_record(
        self,
        cur: Any,
        station_id: uuid.UUID,
        attrs: dict[str, Any],
    ) -> None:
        """Updates only survivorship-selected fields without overwriting populated values with NULL."""
        cur.execute(
            """
            UPDATE public.stations
            SET
                name = COALESCE(%s, name),
                operator_id = COALESCE(%s, operator_id),
                address_line = COALESCE(%s, address_line),
                locality = COALESCE(%s, locality),
                city = COALESCE(%s, city),
                state = COALESCE(%s, state),
                postal_code = COALESCE(%s, postal_code),
                country = COALESCE(%s, country),
                latitude = COALESCE(%s, latitude),
                longitude = COALESCE(%s, longitude),
                opening_time = CASE WHEN %s IS TRUE THEN NULL ELSE COALESCE(%s, opening_time) END,
                closing_time = CASE WHEN %s IS TRUE THEN NULL ELSE COALESCE(%s, closing_time) END,
                is_24_hours = COALESCE(%s, is_24_hours),
                access_type = COALESCE(%s, access_type),
                is_public = COALESCE(%s, is_public),
                operational_status = CASE WHEN %s != 'unknown' THEN %s ELSE operational_status END,
                phone = COALESCE(%s, phone),
                website_url = COALESCE(%s, website_url),
                last_verified_at = COALESCE(%s, last_verified_at),
                updated_at = now()
            WHERE id = %s;
            """,
            (
                attrs["name"][:300] if attrs.get("name") else None,
                str(attrs["operator_id"]) if attrs.get("operator_id") else None,
                attrs.get("address_line"), attrs.get("locality"),
                attrs.get("city"), attrs.get("state"), attrs.get("postal_code"),
                attrs.get("country"), attrs.get("latitude"), attrs.get("longitude"),
                attrs.get("is_24_hours"), attrs.get("opening_time"), attrs.get("closing_time"),
                attrs.get("is_24_hours"), attrs.get("access_type"), attrs.get("is_public"),
                attrs.get("operational_status") or "unknown", attrs.get("operational_status") or "unknown",
                attrs.get("phone"), attrs.get("website_url"), attrs.get("last_verified_at"),
                str(station_id),
            ),
        )

    def _reconcile_and_persist_connectors(
        self,
        cur: Any,
        station_id: uuid.UUID,
        decision: CanonicalResolutionDecision,
        warnings: list[str],
    ) -> tuple[int, int, int, int]:
        """Reconciles canonical connector capacity groups into public.connectors and analytics.dim_connector.
        
        Returns: (persisted_count, created_count, updated_count, skipped_count)
        """
        # Fetch existing connectors for station
        cur.execute(
            """
            SELECT id, connector_type, power_kw, charging_standard, quantity, pricing_type, price_per_kwh, price_per_session
            FROM public.connectors
            WHERE station_id = %s;
            """,
            (str(station_id),),
        )
        existing_rows = cur.fetchall()
        existing_map: dict[tuple[str, float, str], dict[str, Any]] = {}
        for er in existing_rows:
            r_dict = dict(er) if hasattr(er, "keys") else {
                "id": er[0], "connector_type": er[1], "power_kw": er[2], "charging_standard": er[3],
                "quantity": er[4], "pricing_type": er[5], "price_per_kwh": er[6], "price_per_session": er[7],
            }
            k = (r_dict["connector_type"], round(float(r_dict["power_kw"]), 1), r_dict["charging_standard"] or "")
            existing_map[k] = r_dict

        # Extract canonical connectors from decision
        has_explicit_decision = False
        raw_conns: list[dict[str, Any]] = []
        if "connectors" in decision.field_survivorship and decision.field_survivorship["connectors"].canonical_value is not None:
            has_explicit_decision = True
            raw_conns = decision.field_survivorship["connectors"].canonical_value
        else:
            for r in decision.participating_records:
                raw_conns.extend([c.dict() for c in r.connectors])

        # Pricing from decision if available
        p_type, p_kwh, p_sess = None, None, None
        if "pricing" in decision.field_survivorship and decision.field_survivorship["pricing"].canonical_value:
            pv = decision.field_survivorship["pricing"].canonical_value
            p_type = pv.get("pricing_type")
            p_kwh = pv.get("price_per_kwh")
            p_sess = pv.get("price_per_session")

        persisted_count = 0
        created_count = 0
        updated_count = 0
        skipped_count = 0

        for c_data in raw_conns:
            c_type = c_data.get("connector_type")
            if c_type not in ALLOWED_DB_CONNECTOR_TYPES:
                warnings.append(f"Connector type '{c_type}' not in database enum; skipped")
                skipped_count += 1
                continue

            p_kw = c_data.get("power_kw")
            if p_kw is None or p_kw <= 0:
                warnings.append(f"Connector missing or non-positive power_kw ({p_kw}); skipped")
                skipped_count += 1
                continue

            std = c_data.get("charging_standard") or ""
            qty = max(1, c_data.get("quantity", 1))
            key = (c_type, round(float(p_kw), 1), std)

            conn_p_type = c_data.get("pricing_type") or p_type
            conn_p_kwh = c_data.get("price_per_kwh") if c_data.get("price_per_kwh") is not None else p_kwh
            conn_p_sess = c_data.get("price_per_session") if c_data.get("price_per_session") is not None else p_sess

            if key in existing_map:
                # Update existing connector capacity group
                existing_conn = existing_map[key]
                conn_id = uuid.UUID(str(existing_conn["id"]))
                if has_explicit_decision:
                    # 2.7 DECIDES. 2.8 PERSISTS.
                    # Honor the authoritative Step 2.7 canonical survivorship quantity.
                    # The persistence layer must NOT invent an independent survivorship decision.
                    new_qty = qty
                else:
                    # Defensive fallback when no explicit survivorship decision exists
                    new_qty = max(existing_conn["quantity"], qty)
                cur.execute(
                    """
                    UPDATE public.connectors
                    SET
                        quantity = %s,
                        pricing_type = COALESCE(%s, pricing_type),
                        price_per_kwh = COALESCE(%s, price_per_kwh),
                        price_per_session = COALESCE(%s, price_per_session),
                        updated_at = now()
                    WHERE id = %s;
                    """,
                    (new_qty, conn_p_type, conn_p_kwh, conn_p_sess, str(conn_id)),
                )
                updated_count += 1
                persisted_count += new_qty
                final_qty = new_qty
            else:
                # Insert new connector capacity group
                conn_id = uuid.uuid4()
                cur.execute(
                    """
                    INSERT INTO public.connectors (
                        id, station_id, connector_type, charging_standard, power_kw,
                        quantity, pricing_type, price_per_kwh, price_per_session, currency,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'INR', now(), now());
                    """,
                    (
                        str(conn_id), str(station_id), c_type, std or None, p_kw,
                        qty, conn_p_type, conn_p_kwh, conn_p_sess,
                    ),
                )
                created_count += 1
                persisted_count += qty
                final_qty = qty

            # Mirror to analytics.dim_connector
            self._sync_dim_connector(
                cur=cur,
                connector_id=conn_id,
                station_id=station_id,
                connector_type=c_type,
                charging_standard=std or None,
                power_kw=float(p_kw),
                quantity=final_qty,
                pricing_type=conn_p_type,
                price_per_kwh=conn_p_kwh,
                price_per_session=conn_p_sess,
            )

        return persisted_count, created_count, updated_count, skipped_count

    def _reconcile_and_persist_source_links(
        self,
        cur: Any,
        station_id: uuid.UUID,
        decision: CanonicalResolutionDecision,
    ) -> tuple[int, int]:
        """Reconciles external source identity bridges in public.station_source_link."""
        links_created = 0
        links_updated = 0

        # Build map of participating records for payload metadata
        rec_map = {(r.source_id, r.source_station_id): r for r in decision.participating_records}

        for src_id_str, src_stn_id in decision.participating_source_identities:
            ds_id = self.get_or_create_data_source(name=src_id_str, commit=False)
            cur.execute(
                """
                SELECT id, station_id, source_payload_hash
                FROM public.station_source_link
                WHERE source_id = %s AND source_station_id = %s;
                """,
                (str(ds_id), str(src_stn_id)),
            )
            row = cur.fetchone()
            rec = rec_map.get((src_id_str, src_stn_id))
            p_hash = rec.extra_metadata.get("payload_hash") if rec and rec.extra_metadata else None
            s_url = rec.extra_metadata.get("source_url") if rec and rec.extra_metadata else None

            if row:
                r_dict = dict(row) if hasattr(row, "keys") else {"id": row[0], "station_id": row[1], "source_payload_hash": row[2]}
                if str(r_dict["station_id"]) != str(station_id):
                    raise ValueError(
                        f"Unsafe identity mutation: source record '{src_id_str}:{src_stn_id}' is already linked to station '{r_dict['station_id']}', cannot silently reassign to '{station_id}'"
                    )
                cur.execute(
                    """
                    UPDATE public.station_source_link
                    SET last_seen_at = now(), last_ingested_at = now(), source_payload_hash = COALESCE(%s, source_payload_hash), updated_at = now()
                    WHERE id = %s;
                    """,
                    (p_hash, str(r_dict["id"])),
                )
                links_updated += 1
            else:
                cur.execute(
                    """
                    INSERT INTO public.station_source_link (
                        station_id, source_id, source_station_id, source_url,
                        first_seen_at, last_seen_at, last_ingested_at, source_payload_hash, is_active
                    ) VALUES (%s, %s, %s, %s, now(), now(), now(), %s, true);
                    """,
                    (str(station_id), str(ds_id), str(src_stn_id), s_url, p_hash),
                )
                links_created += 1

        return links_created, links_updated

    def _sync_dim_connector(
        self,
        cur: Any,
        connector_id: uuid.UUID,
        station_id: uuid.UUID,
        connector_type: str,
        charging_standard: Optional[str],
        power_kw: float,
        quantity: int,
        pricing_type: Optional[str],
        price_per_kwh: Optional[float],
        price_per_session: Optional[float],
    ) -> None:
        """Mirrors public.connectors into analytics.dim_connector for conformed warehouse lookup."""
        is_fast = (power_kw >= 50.0) if power_kw is not None else None
        cur.execute(
            """
            INSERT INTO analytics.dim_connector (
                connector_id, station_id, connector_type, charging_standard, power_kw,
                quantity, pricing_type, price_per_kwh, price_per_session, currency,
                is_fast_charging, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'INR', %s, now(), now())
            ON CONFLICT (connector_id) DO UPDATE SET
                station_id = EXCLUDED.station_id,
                connector_type = EXCLUDED.connector_type,
                charging_standard = EXCLUDED.charging_standard,
                power_kw = EXCLUDED.power_kw,
                quantity = EXCLUDED.quantity,
                pricing_type = EXCLUDED.pricing_type,
                price_per_kwh = EXCLUDED.price_per_kwh,
                price_per_session = EXCLUDED.price_per_session,
                is_fast_charging = EXCLUDED.is_fast_charging,
                updated_at = now();
            """,
            (
                str(connector_id), str(station_id), connector_type, charging_standard,
                power_kw, quantity, pricing_type, price_per_kwh, price_per_session, is_fast,
            ),
        )

    def _sync_dim_station_scd2(self, cur: Any, station_id: uuid.UUID) -> Optional[int]:
        """Synchronizes an operational station into analytics.dim_station while strictly honoring SCD Type 2."""
        cur.execute(
            """
            SELECT s.name, s.operator_id, s.address_line, s.locality, s.city, s.state, s.postal_code, s.country,
                   s.latitude, s.longitude, s.access_type, s.is_public, s.operational_status, s.is_24_hours,
                   s.opening_time, s.closing_time, o.name AS operator_name, o.slug AS operator_slug
            FROM public.stations s
            LEFT JOIN public.operators o ON s.operator_id = o.id
            WHERE s.id = %s;
            """,
            (str(station_id),),
        )
        stn_row = cur.fetchone()
        if not stn_row:
            return None

        r_stn = dict(stn_row) if hasattr(stn_row, "keys") else {
            "name": stn_row[0], "operator_id": stn_row[1], "address_line": stn_row[2], "locality": stn_row[3],
            "city": stn_row[4], "state": stn_row[5], "postal_code": stn_row[6], "country": stn_row[7],
            "latitude": stn_row[8], "longitude": stn_row[9], "access_type": stn_row[10], "is_public": stn_row[11],
            "operational_status": stn_row[12], "is_24_hours": stn_row[13], "opening_time": stn_row[14],
            "closing_time": stn_row[15], "operator_name": stn_row[16], "operator_slug": stn_row[17],
        }

        # Resolve operator_key
        op_id = r_stn["operator_id"]
        cur.execute("SELECT operator_key FROM analytics.dim_operator WHERE operator_id = %s;", (str(op_id),))
        op_row = cur.fetchone()
        if op_row:
            op_key = op_row[0] if isinstance(op_row, (tuple, list)) else op_row["operator_key"]
        else:
            cur.execute(
                """
                INSERT INTO analytics.dim_operator (operator_id, operator_name, slug)
                VALUES (%s, %s, %s)
                RETURNING operator_key;
                """,
                (str(op_id), r_stn["operator_name"] or "Unknown Operator", r_stn["operator_slug"]),
            )
            created_op = cur.fetchone()
            op_key = created_op[0] if isinstance(created_op, (tuple, list)) else created_op["operator_key"]

        # Resolve location_key
        cur.execute(
            """
            SELECT location_key FROM analytics.dim_location
            WHERE country = %s AND state = %s AND city = %s
              AND COALESCE(locality, '') = COALESCE(%s, '')
              AND COALESCE(postal_code, '') = COALESCE(%s, '');
            """,
            (r_stn["country"], r_stn["state"], r_stn["city"], r_stn["locality"], r_stn["postal_code"]),
        )
        loc_row = cur.fetchone()
        if loc_row:
            loc_key = loc_row[0] if isinstance(loc_row, (tuple, list)) else loc_row["location_key"]
        else:
            cur.execute(
                """
                INSERT INTO analytics.dim_location (country, state, city, locality, postal_code)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING location_key;
                """,
                (r_stn["country"], r_stn["state"], r_stn["city"], r_stn["locality"], r_stn["postal_code"]),
            )
            created_loc = cur.fetchone()
            loc_key = created_loc[0] if isinstance(created_loc, (tuple, list)) else created_loc["location_key"]

        # Check existing current version in analytics.dim_station
        cur.execute(
            """
            SELECT station_key, station_name, operator_key, location_key, latitude, longitude,
                   address, access_type, is_public, operational_status, is_24_hours,
                   opening_time, closing_time, version
            FROM analytics.dim_station
            WHERE station_id = %s AND is_current = true;
            """,
            (str(station_id),),
        )
        dim_row = cur.fetchone()
        is_pub_bool = bool(r_stn["is_public"]) if r_stn["is_public"] is not None else True
        is_24_bool = bool(r_stn["is_24_hours"]) if r_stn["is_24_hours"] is not None else False

        if not dim_row:
            cur.execute(
                """
                INSERT INTO analytics.dim_station (
                    station_id, station_name, operator_key, location_key, latitude, longitude,
                    address, access_type, is_public, operational_status, is_24_hours,
                    opening_time, closing_time, effective_from, is_current, version
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, now(), true, 1
                )
                RETURNING station_key;
                """,
                (
                    str(station_id), r_stn["name"], op_key, loc_key, r_stn["latitude"], r_stn["longitude"],
                    r_stn["address_line"], r_stn["access_type"], is_pub_bool, r_stn["operational_status"],
                    is_24_bool, r_stn["opening_time"], r_stn["closing_time"],
                ),
            )
            created_stn = cur.fetchone()
            return created_stn[0] if isinstance(created_stn, (tuple, list)) else created_stn["station_key"]

        d = dict(dim_row) if hasattr(dim_row, "keys") else {
            "station_key": dim_row[0], "station_name": dim_row[1], "operator_key": dim_row[2],
            "location_key": dim_row[3], "latitude": dim_row[4], "longitude": dim_row[5],
            "address": dim_row[6], "access_type": dim_row[7], "is_public": dim_row[8],
            "operational_status": dim_row[9], "is_24_hours": dim_row[10], "opening_time": dim_row[11],
            "closing_time": dim_row[12], "version": dim_row[13],
        }

        # Check for tracked attribute changes
        name_match = (d["station_name"] == r_stn["name"])
        op_match = (d["operator_key"] == op_key)
        loc_match = (d["location_key"] == loc_key)
        coord_match = (abs(float(d["latitude"]) - float(r_stn["latitude"])) < 1e-5 and
                       abs(float(d["longitude"]) - float(r_stn["longitude"])) < 1e-5)
        addr_match = ((d["address"] or "") == (r_stn["address_line"] or ""))
        access_match = ((d["access_type"] or "") == (r_stn["access_type"] or ""))
        pub_match = (bool(d["is_public"]) == is_pub_bool)
        status_match = (d["operational_status"] == r_stn["operational_status"])
        hours_match = (bool(d["is_24_hours"]) == is_24_bool and
                       str(d["opening_time"] or "") == str(r_stn["opening_time"] or "") and
                       str(d["closing_time"] or "") == str(r_stn["closing_time"] or ""))

        if name_match and op_match and loc_match and coord_match and addr_match and access_match and pub_match and status_match and hours_match:
            # Idempotent no-op
            return d["station_key"]

        # Attributes changed: close current version and open new version
        old_version = d["version"]
        cur.execute(
            """
            UPDATE analytics.dim_station
            SET is_current = false, effective_to = now(), updated_at = now()
            WHERE station_key = %s;
            """,
            (d["station_key"],),
        )

        cur.execute(
            """
            INSERT INTO analytics.dim_station (
                station_id, station_name, operator_key, location_key, latitude, longitude,
                address, access_type, is_public, operational_status, is_24_hours,
                opening_time, closing_time, effective_from, is_current, version
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, now(), true, %s
            )
            RETURNING station_key;
            """,
            (
                str(station_id), r_stn["name"], op_key, loc_key, r_stn["latitude"], r_stn["longitude"],
                r_stn["address_line"], r_stn["access_type"], is_pub_bool, r_stn["operational_status"],
                is_24_bool, r_stn["opening_time"], r_stn["closing_time"], old_version + 1,
            ),
        )
        new_stn = cur.fetchone()
        return new_stn[0] if isinstance(new_stn, (tuple, list)) else new_stn["station_key"]

    def _persist_decision_observations(
        self,
        cur: Any,
        station_id: uuid.UUID,
        decision: CanonicalResolutionDecision,
    ) -> int:
        """Persists legitimate point-in-time observations from participating records."""
        obs_count = 0
        cur.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM public.connectors WHERE station_id = %s;",
            (str(station_id),),
        )
        tot_row = cur.fetchone()
        total_connectors = int(tot_row[0]) if tot_row else 0

        for rec in decision.participating_records:
            if rec.observation is not None:
                data_source_id = self.get_or_create_data_source(name=rec.source_id, commit=False)
                payload_hash = rec.extra_metadata.get("payload_hash") if rec.extra_metadata else None

                if payload_hash:
                    cur.execute(
                        """
                        SELECT id FROM public.station_observations
                        WHERE station_id = %s AND source_id = %s AND source_payload_hash = %s;
                        """,
                        (str(station_id), str(data_source_id), payload_hash),
                    )
                    if cur.fetchone():
                        continue  # Idempotent skip duplicate observation

                obs_id = self.persist_observation(
                    station_id=station_id,
                    data_source_id=data_source_id,
                    obs=rec.observation,
                    total_connectors=total_connectors,
                    raw_payload_hash=payload_hash,
                    dry_run=False,
                )
                if obs_id:
                    obs_count += 1
        return obs_count

    def _simulate_decision_dry_run(
        self,
        decision: CanonicalResolutionDecision,
    ) -> CanonicalPersistenceResult:
        """Simulates the outcome of persisting a decision in dry-run mode without database writes."""
        stn_id = uuid.UUID(str(decision.canonical_station_id)) if decision.canonical_station_id else uuid.uuid4()
        conn_count = len(decision.field_survivorship.get("connectors", {}).canonical_value or [])
        if not conn_count:
            conn_count = sum(len(r.connectors) for r in decision.participating_records)

        obs_count = sum(
            1 for r in decision.participating_records
            if r.observation is not None
        )

        if decision.decision_state == CanonicalDecisionState.LINK_TO_CANONICAL:
            status = CanonicalPersistenceStatus.LINKED
            is_new = False
            is_linked = True
        elif decision.decision_state == CanonicalDecisionState.MERGE:
            status = CanonicalPersistenceStatus.INSERTED
            is_new = True
            is_linked = False
        else:
            status = CanonicalPersistenceStatus.INSERTED
            is_new = True
            is_linked = False

        return CanonicalPersistenceResult(
            cluster_id=decision.cluster_id,
            decision_state=decision.decision_state,
            status=status,
            station_id=stn_id,
            is_new=is_new,
            is_linked=is_linked,
            source_links_created=len(decision.participating_source_identities),
            connectors_persisted=conn_count,
            observations_persisted=obs_count,
        )

    def persist_ingestion_run(self, run: Any, dry_run: bool = False) -> Optional[str]:
        """Persists or updates an IngestionRun audit record in public.ingestion_runs.
        
        Args:
            run: IngestionRun instance.
            dry_run: If True, skips database writes and returns run.run_id.
            
        Returns:
            The run UUID string if recorded, or None if skipped/failed.
        """
        if dry_run or self.conn is None:
            return getattr(run, "run_id", None)

        cur = self.conn.cursor()
        try:
            # 1. Resolve source_id UUID from public.data_sources if possible
            source_uuid = None
            source_name = getattr(run, "source_name", getattr(run, "source_id", "unknown"))
            try:
                cur.execute("SELECT id FROM public.data_sources WHERE name = %s LIMIT 1;", (source_name,))
                row = cur.fetchone()
                if row:
                    source_uuid = row[0]
            except Exception:
                pass

            # 2. Sanitize error summary
            error_summary = _scrub_secrets(getattr(run, "error_summary", None))

            # 3. Upsert into public.ingestion_runs
            metadata_json = json.dumps(getattr(run, "metadata", {}))

            insert_sql = """
                INSERT INTO public.ingestion_runs (
                    id, source_id, source_name, scope, state, started_at, completed_at,
                    duration_seconds, attempt_count, records_fetched, records_parsed,
                    records_accepted, records_accepted_with_warnings, records_quarantined,
                    records_rejected, stations_persisted, stations_updated, stations_unchanged,
                    connectors_persisted, observations_persisted, error_summary, metadata
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    state = EXCLUDED.state,
                    completed_at = EXCLUDED.completed_at,
                    duration_seconds = EXCLUDED.duration_seconds,
                    attempt_count = EXCLUDED.attempt_count,
                    records_fetched = EXCLUDED.records_fetched,
                    records_parsed = EXCLUDED.records_parsed,
                    records_accepted = EXCLUDED.records_accepted,
                    records_accepted_with_warnings = EXCLUDED.records_accepted_with_warnings,
                    records_quarantined = EXCLUDED.records_quarantined,
                    records_rejected = EXCLUDED.records_rejected,
                    stations_persisted = EXCLUDED.stations_persisted,
                    stations_updated = EXCLUDED.stations_updated,
                    stations_unchanged = EXCLUDED.stations_unchanged,
                    connectors_persisted = EXCLUDED.connectors_persisted,
                    observations_persisted = EXCLUDED.observations_persisted,
                    error_summary = EXCLUDED.error_summary,
                    metadata = EXCLUDED.metadata;
            """
            cur.execute(
                insert_sql,
                (
                    run.run_id,
                    source_uuid,
                    source_name,
                    getattr(run, "scope", "default"),
                    getattr(run.state, "value", str(run.state)),
                    getattr(run, "started_at", datetime.now(timezone.utc)),
                    getattr(run, "completed_at", None),
                    getattr(run, "duration_seconds", None),
                    getattr(run, "attempt_count", 1),
                    getattr(run, "records_fetched", 0),
                    getattr(run, "records_parsed", 0),
                    getattr(run, "records_accepted", 0),
                    getattr(run, "records_accepted_with_warnings", 0),
                    getattr(run, "records_quarantined", 0),
                    getattr(run, "records_rejected", 0),
                    getattr(run, "stations_persisted", 0),
                    getattr(run, "stations_updated", 0),
                    getattr(run, "stations_unchanged", 0),
                    getattr(run, "connectors_persisted", 0),
                    getattr(run, "observations_persisted", 0),
                    error_summary,
                    metadata_json,
                ),
            )
            self.conn.commit()
            return str(run.run_id)
        except Exception as ex:
            if self.conn:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
            logger.error("Failed to persist ingestion run: %s", _scrub_secrets(str(ex)))
            return None
        finally:
            cur.close()
