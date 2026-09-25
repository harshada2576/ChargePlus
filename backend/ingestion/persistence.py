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
                self.conn.commit()

            # Ensure mirrored in analytics.dim_source if not dry_run
            if not dry_run:
                self._ensure_dim_source(source_id, name, source_type, base_url, source_priority)

            return source_id

    def _ensure_dim_source(
        self,
        source_id: uuid.UUID,
        name: str,
        source_type: str,
        base_url: Optional[str],
        source_priority: int,
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
            self.conn.commit()

    def get_or_create_operator(
        self,
        operator_name: Optional[str],
        operator_slug: Optional[str] = None,
        website_url: Optional[str] = None,
        support_phone: Optional[str] = None,
        dry_run: bool = False,
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
        now_utc = datetime.now(timezone.utc)
        recv_time = max(obs_time, now_utc)  # Enforce chk_observations_causal_time (received_at >= observed_at)

        with self.conn.cursor() as cur:
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
