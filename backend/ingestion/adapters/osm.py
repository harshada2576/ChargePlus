"""ChargePlus — OpenStreetMap (OSM) Overpass API Ingestion Adapter.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Secondary Source: OpenStreetMap via Overpass API

Implements the OSM source adapter converting Overpass QL responses for
amenity=charging_station into the canonical Step 2.1 contract.

Key Semantic Protections:
  - OSM is static physical inventory ONLY: zero live availability telemetry.
  - Missing means Missing: socket counts, power, operator, fees all default to None.
  - ODbL Attribution: Source is OpenStreetMap contributors (ODbL 1.0).
  - No global extracts: queries are always bounded by a geographic bounding box.
  - Idempotent: repeated imports of identical OSM node produce identical records.
  - Rate-limit aware: respects Overpass public infrastructure limits (max 1 req/s,
    prefer off-peak hours, bounded concurrency).
  - Boundary lock: adapter NEVER writes to Supabase or alters the database.

OSM Tag Mapping:
  Connector types:  socket:type2, socket:ccs, socket:chademo, socket:type1,
                    socket:typee, socket:tesla_supercharger, socket:gbt_dc
  Power:            socket:<type>:output (kW)
  Operator:         operator, brand
  Fees:             fee=yes/no, charge=<value>
  Hours:            opening_hours
  Authentication:   authentication:*=yes/no

License: OpenStreetMap data is © OpenStreetMap contributors, licensed under ODbL 1.0.
         Attribution required. Share-alike applies to derived databases.
         See: https://www.openstreetmap.org/copyright
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from backend.ingestion.base import BaseSourceAdapter, request_with_retry
from backend.ingestion.constants import (
    AvailabilityStatus,
    OperationalStatus,
    PricingType,
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

# ---------------------------------------------------------------------------
# OSM Tag → Canonical Connector Type Mapping
# ---------------------------------------------------------------------------

# socket:<tag> → StandardConnectorType value.
# Keys are the OSM socket type suffixes (after "socket:").
OSM_SOCKET_TAG_MAP: dict[str, str] = {
    "type2": StandardConnectorType.TYPE_2.value,
    "type2_combo": StandardConnectorType.CCS2.value,
    "ccs": StandardConnectorType.CCS2.value,
    "ccs2": StandardConnectorType.CCS2.value,
    "ccs_combo2": StandardConnectorType.CCS2.value,
    "combo2": StandardConnectorType.CCS2.value,
    "type1": StandardConnectorType.TYPE_1.value,
    "type1_combo": StandardConnectorType.CCS1.value,
    "ccs1": StandardConnectorType.CCS1.value,
    "combo1": StandardConnectorType.CCS1.value,
    "j1772": StandardConnectorType.TYPE_1.value,
    "chademo": StandardConnectorType.CHADEMO.value,
    "gbt_ac": StandardConnectorType.GB_T.value,
    "gbt_dc": StandardConnectorType.GB_T.value,
    "gb_t": StandardConnectorType.GB_T.value,
    "gb/t": StandardConnectorType.GB_T.value,
    "bharat_ac001": StandardConnectorType.BHARAT_AC001.value,
    "bharat_dc001": StandardConnectorType.BHARAT_DC001.value,
    "bharat_ac": StandardConnectorType.BHARAT_AC001.value,
    "bharat_dc": StandardConnectorType.BHARAT_DC001.value,
    "tesla_supercharger": StandardConnectorType.OTHER.value,
    "tesla_destination": StandardConnectorType.OTHER.value,
    "nema_5_15": StandardConnectorType.OTHER.value,
    "nema_5_20": StandardConnectorType.OTHER.value,
    "nema_14_30": StandardConnectorType.OTHER.value,
    "nema_14_50": StandardConnectorType.OTHER.value,
    "schuko": StandardConnectorType.OTHER.value,
    "typee": StandardConnectorType.OTHER.value,
}

# Known socket tags that indicate EV charging (for prefix scan)
KNOWN_SOCKET_PREFIXES = frozenset([
    "socket:type2", "socket:ccs", "socket:chademo", "socket:type1",
    "socket:gbt", "socket:bharat", "socket:tesla", "socket:combo",
    "socket:nema", "socket:j1772",
])

# ---------------------------------------------------------------------------
# Overpass API Configuration
# ---------------------------------------------------------------------------

# Public Overpass infrastructure endpoints (rotate if primary is overloaded)
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]

DEFAULT_TIMEOUT_SEC = 60
# Minimum inter-request interval to respect public Overpass infrastructure
MIN_REQUEST_INTERVAL_SEC = 2.0

# Rate limit state (module-level, shared across adapter instances in a process)
_last_request_time: float = 0.0


def _rate_limit_wait() -> None:
    """Enforces minimum inter-request interval for Overpass public infrastructure."""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL_SEC:
        time.sleep(MIN_REQUEST_INTERVAL_SEC - elapsed)
    _last_request_time = time.monotonic()


class OSMOverpassAdapter(BaseSourceAdapter):
    """Source adapter for OpenStreetMap charging stations via Overpass API.

    Queries amenity=charging_station nodes, ways, and relations within a
    geographic bounding box. Always requires an explicit bounding box to prevent
    uncontrolled global extracts.

    Attribution: Data is © OpenStreetMap contributors, ODbL 1.0.
    """

    ATTRIBUTION = "© OpenStreetMap contributors (ODbL 1.0) — https://www.openstreetmap.org/copyright"
    OSM_ATTRIBUTION_URL = "https://www.openstreetmap.org/copyright"

    def __init__(self, endpoint_url: Optional[str] = None) -> None:
        self._endpoint_url = endpoint_url or os.getenv(
            "OSM_OVERPASS_ENDPOINT", OVERPASS_ENDPOINTS[0]
        )

    @property
    def source_id(self) -> str:
        return "osm"

    @property
    def source_priority(self) -> int:
        return 60  # Lower than OCM (70); OSM is community-curated but less structured

    def extract_source_station_id(self, payload: dict[str, Any]) -> str:
        """Extracts a stable OSM identifier: <type>/<id> (e.g. 'node/12345678')."""
        osm_type = payload.get("type")
        osm_id = payload.get("id")
        if osm_type and osm_id is not None:
            return f"{osm_type}/{osm_id}"
        raise ValueError(
            f"OSM payload missing required 'type' and 'id' fields: {list(payload.keys())}"
        )

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _parse_osm_power(self, raw_value: Optional[str]) -> Optional[float]:
        """Parses OSM power output tag into kW float.

        OSM values are strings like '22 kW', '50000 W', '7.4kw', '22'.
        Returns None for unparseable or non-positive values.
        Never fabricates 0 kW for missing power.
        """
        if not raw_value or not isinstance(raw_value, str):
            return None
        clean = raw_value.strip().lower()
        # Remove trailing semicolons (OSM multiple values)
        clean = clean.split(";")[0].strip()
        try:
            # Pattern: optional number, optional unit
            match = re.match(r"^([\d.]+)\s*(kw|w|kwh)?$", clean)
            if not match:
                return None
            value = float(match.group(1))
            unit = (match.group(2) or "kw").lower()
            if unit == "w":
                value = value / 1000.0
            if value <= 0:
                return None
            return round(value, 3)
        except (ValueError, TypeError):
            return None

    def _parse_socket_count(self, raw_value: Optional[str]) -> Optional[int]:
        """Parses OSM socket count tag (e.g. '2', '1;3') → integer or None."""
        if not raw_value or not isinstance(raw_value, str):
            return None
        # Take first numeric value if semicolon-separated
        part = raw_value.split(";")[0].strip()
        try:
            count = int(part)
            return count if count > 0 else None
        except (ValueError, TypeError):
            return None

    def _extract_connectors(self, tags: dict[str, str]) -> list[NormalizedConnectorRecord]:
        """Extracts connector records from OSM tags.

        OSM encodes connectors as:
          socket:<type>=<count>
          socket:<type>:output=<power>

        Each distinct socket type becomes one NormalizedConnectorRecord.
        Missing count and power remain None (never fabricated).
        """
        connectors: list[NormalizedConnectorRecord] = []
        seen_types: set[str] = set()

        # Collect all socket:<type> tags
        for key, value in tags.items():
            if not key.startswith("socket:"):
                continue
            # Skip output/voltage/amperage sub-tags — handled below
            if any(
                key.endswith(f":{suffix}")
                for suffix in ("output", "voltage", "amperage", "current")
            ):
                continue

            socket_suffix = key[len("socket:"):].lower()
            canonical_type = OSM_SOCKET_TAG_MAP.get(socket_suffix, StandardConnectorType.OTHER.value)

            # Avoid duplicate canonical types (deduplicate within this OSM record)
            if canonical_type in seen_types:
                continue
            seen_types.add(canonical_type)

            quantity = self._parse_socket_count(value)
            # Power from socket:<type>:output tag
            output_key = f"{key}:output"
            power_kw = self._parse_power_from_tags(tags, output_key)

            # quantity: contract requires int >= 1; use 1 when count is unknown
            safe_quantity = quantity if quantity is not None else 1
            connectors.append(
                NormalizedConnectorRecord(
                    source_connector_id=None,  # OSM does not assign connector IDs
                    connector_type=canonical_type,
                    raw_connector_type=key,
                    charging_standard=None,
                    power_kw=power_kw,
                    voltage_v=None,
                    amperage_a=None,
                    quantity=safe_quantity,
                    is_aggregated=safe_quantity > 1,
                    pricing_type=PricingType.UNKNOWN,
                    price_per_kwh=None,
                    currency="INR",  # default; OSM has no tariff currency info
                    status=AvailabilityStatus.UNKNOWN,  # OSM has no live availability
                )
            )

        # If no explicit socket tags but station tagged as charging_station,
        # emit a single OTHER connector with unknown count and power
        if not connectors:
            capacity_raw = tags.get("capacity")
            raw_count = self._parse_socket_count(capacity_raw)
            safe_count = raw_count if raw_count is not None else 1
            connectors.append(
                NormalizedConnectorRecord(
                    source_connector_id=None,
                    connector_type=StandardConnectorType.OTHER.value,
                    raw_connector_type="unknown",
                    charging_standard=None,
                    power_kw=None,
                    voltage_v=None,
                    amperage_a=None,
                    quantity=safe_count,
                    is_aggregated=safe_count > 1,
                    pricing_type=PricingType.UNKNOWN,
                    price_per_kwh=None,
                    currency="INR",
                    status=AvailabilityStatus.UNKNOWN,
                )
            )

        return connectors

    def _parse_power_from_tags(
        self, tags: dict[str, str], output_key: str
    ) -> Optional[float]:
        """Looks up power from a specific output tag key."""
        return self._parse_osm_power(tags.get(output_key))

    def _extract_operator(self, tags: dict[str, str]) -> Optional[str]:
        """Returns operator or brand name from OSM tags."""
        op = tags.get("operator") or tags.get("brand") or tags.get("network")
        return op.strip() if op and op.strip() else None

    def _extract_pricing(self, tags: dict[str, str]) -> PricingType:
        """Infers pricing type from OSM fee and charge tags."""
        fee = tags.get("fee", "").lower().strip()
        if fee in ("no", "0", "free"):
            return PricingType.FREE
        if fee in ("yes",):
            return PricingType.PAID
        charge = tags.get("charge", "").lower().strip()
        if charge:
            if charge in ("no", "free", "0"):
                return PricingType.FREE
            if charge:
                return PricingType.PAID
        return PricingType.UNKNOWN

    def _extract_operational_status(self, tags: dict[str, str]) -> OperationalStatus:
        """Maps OSM access / disused tags to OperationalStatus."""
        disused = tags.get("disused:amenity") or tags.get("abandoned:amenity")
        if disused:
            return OperationalStatus.PERMANENTLY_CLOSED
        opening = tags.get("opening_hours", "").strip().lower()
        if opening in ("closed", "permanently closed"):
            return OperationalStatus.PERMANENTLY_CLOSED
        # All others: assume operational; OSM rarely marks temporary closures
        return OperationalStatus.OPERATIONAL

    # ------------------------------------------------------------------
    # Core Normalization
    # ------------------------------------------------------------------

    def normalize_station(self, raw: RawSourceRecord) -> NormalizedStationRecord:
        """Transforms an OSM Overpass node/way/relation into a NormalizedStationRecord."""
        payload = raw.raw_payload
        station_id = raw.source_station_id  # e.g. "node/12345678"
        tags: dict[str, str] = payload.get("tags") or {}

        # --- 1. Coordinates ---
        # For nodes: lat/lon directly on element.
        # For ways/relations: Overpass can return center lat/lon when requested.
        raw_lat = payload.get("lat") or (payload.get("center") or {}).get("lat")
        raw_lon = payload.get("lon") or (payload.get("center") or {}).get("lon")

        try:
            latitude = float(raw_lat) if raw_lat is not None else None
        except (ValueError, TypeError):
            latitude = None

        try:
            longitude = float(raw_lon) if raw_lon is not None else None
        except (ValueError, TypeError):
            longitude = None

        if latitude is None or longitude is None:
            raise ValueError(
                f"OSM element {station_id} missing valid lat/lon coordinates"
            )

        # --- 2. Name ---
        raw_name = (tags.get("name") or tags.get("ref") or "").strip()
        operator_name = self._extract_operator(tags)
        if not raw_name:
            if operator_name:
                raw_name = f"{operator_name} Charging Station"
            else:
                raw_name = f"OSM Charging Station {station_id}"
            name_synthesized = True
        else:
            name_synthesized = False

        # --- 3. Address ---
        address_line = (
            tags.get("addr:street") or tags.get("addr:full") or None
        )
        if address_line and tags.get("addr:housenumber"):
            address_line = f"{tags['addr:housenumber']} {address_line}"

        city = tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:suburb")
        state = tags.get("addr:state") or tags.get("addr:province")
        postal_code = tags.get("addr:postcode")

        # Mumbai pilot fallback (flagged in extra_metadata)
        city_inferred = False
        state_inferred = False
        if not city:
            city = "Mumbai"
            city_inferred = True
        if not state:
            state = "Maharashtra"
            state_inferred = True

        # --- 4. Operator & Status ---
        operator_slug = (
            re.sub(r"[^a-z0-9_-]+", "-", operator_name.strip().lower()).strip("-")
            if operator_name
            else None
        )
        operational_status = self._extract_operational_status(tags)

        # --- 5. Pricing ---
        pricing_type = self._extract_pricing(tags)
        is_public = tags.get("access", "").lower() not in ("private", "customers", "no")

        # --- 6. Opening hours ---
        opening_hours = tags.get("opening_hours")
        is_24_hours = opening_hours == "24/7" if opening_hours else None

        # --- 7. Connectors ---
        connectors = self._extract_connectors(tags)

        # --- 8. OSM Metadata ---
        osm_version = payload.get("version")
        osm_timestamp = payload.get("timestamp")  # e.g. "2024-03-15T10:00:00Z"
        source_timestamp: Optional[datetime] = None
        if osm_timestamp and isinstance(osm_timestamp, str):
            try:
                source_timestamp = datetime.fromisoformat(
                    osm_timestamp.replace("Z", "+00:00")
                )
            except ValueError:
                source_timestamp = None

        extra_metadata: dict[str, Any] = {
            "osm_type": payload.get("type"),
            "osm_id": payload.get("id"),
            "osm_version": osm_version,
            "osm_timestamp": osm_timestamp,
            "osm_changeset": payload.get("changeset"),
            "osm_user": payload.get("user"),
            "attribution": self.ATTRIBUTION,
            "license": "ODbL 1.0",
            "attribution_url": self.OSM_ATTRIBUTION_URL,
            "opening_hours_raw": opening_hours,
            "authentication_tags": {
                k: v for k, v in tags.items() if k.startswith("authentication:")
            },
            "city_inferred": city_inferred,
            "state_inferred": state_inferred,
            "name_synthesized": name_synthesized,
            # Preserve all raw OSM tags for complete provenance
            "osm_tags": dict(tags),
        }

        return NormalizedStationRecord(
            source_id=self.source_id,
            source_station_id=station_id,
            source_url=f"https://www.openstreetmap.org/{station_id}",
            raw_payload_hash=raw.payload_hash,
            name=raw_name,
            raw_name=tags.get("name"),
            operator_name=operator_name,
            operator_slug=operator_slug,
            latitude=latitude,
            longitude=longitude,
            address_line=address_line,
            locality=tags.get("addr:suburb"),
            city=city,
            state=state,
            postal_code=postal_code,
            country="India",
            is_24_hours=is_24_hours,
            opening_time=None,
            closing_time=None,
            access_type="Public" if is_public else "Private",
            is_public=is_public,
            operational_status=operational_status,
            phone=tags.get("phone") or tags.get("contact:phone"),
            website_url=tags.get("website") or tags.get("contact:website"),
            connectors=connectors,
            observation=None,  # OSM NEVER carries live availability telemetry
            extra_metadata=extra_metadata,
        )

    # ------------------------------------------------------------------
    # Network Fetch
    # ------------------------------------------------------------------

    def build_overpass_query(
        self,
        lat_min: float,
        lng_min: float,
        lat_max: float,
        lng_max: float,
    ) -> str:
        """Builds a bounded Overpass QL query for EV charging stations.

        Queries nodes, ways, and relations tagged amenity=charging_station
        within the provided bounding box. Includes way and relation centres
        so that non-point elements still have a representative lat/lon.

        The bounding box is REQUIRED — this adapter refuses to issue unbounded
        global extracts against public Overpass infrastructure.
        """
        bbox = f"{lat_min},{lng_min},{lat_max},{lng_max}"
        return (
            "[out:json][timeout:60];"
            "("
            f"  node[\"amenity\"=\"charging_station\"]({bbox});"
            f"  way[\"amenity\"=\"charging_station\"]({bbox});"
            f"  relation[\"amenity\"=\"charging_station\"]({bbox});"
            ");"
            "out center tags;"
        )

    def fetch_raw(
        self,
        lat_min: Optional[float] = None,
        lng_min: Optional[float] = None,
        lat_max: Optional[float] = None,
        lng_max: Optional[float] = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
        endpoint_url: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Fetches raw OSM Overpass payloads for EV charging stations.

        Bounding box (lat_min, lng_min, lat_max, lng_max) is REQUIRED.
        Raises ValueError if any coordinate is None to prevent global extracts.

        Respects the per-request rate limit for public Overpass infrastructure.
        Handles HTTP 429, 5xx, timeouts, and malformed JSON defensively.

        Attribution: Returned data is © OpenStreetMap contributors (ODbL 1.0).
        """
        if any(c is None for c in (lat_min, lng_min, lat_max, lng_max)):
            raise ValueError(
                "OSM Overpass adapter requires an explicit bounding box "
                "(lat_min, lng_min, lat_max, lng_max). "
                "Unbounded global extracts are prohibited against public Overpass infrastructure."
            )

        url = endpoint_url or self._endpoint_url
        query = self.build_overpass_query(lat_min, lng_min, lat_max, lng_max)

        logger.info(
            "Fetching OSM charging stations from Overpass: bbox=[%s,%s,%s,%s]",
            lat_min, lng_min, lat_max, lng_max,
        )

        # Enforce rate limit before sending
        _rate_limit_wait()

        headers = {
            "User-Agent": (
                "ChargePlus-Ingestion/1.0 "
                "(https://github.com/harshada2576/ChargePlus; "
                "contact via GitHub issues; "
                "respecting Overpass usage policy)"
            ),
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            response = request_with_retry(
                "post",
                url,
                data={"data": query},
                headers=headers,
                timeout_sec=timeout_sec,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"Overpass API request timed out after {timeout_sec}s"
            ) from exc
        except ConnectionError as exc:
            raise ConnectionError(
                f"Failed to connect to Overpass API: {exc}"
            ) from exc
        except RuntimeError as exc:
            # Transport retries (429/5xx with backoff+jitter+Retry-After)
            # exhausted inside request_with_retry; label the source.
            raise RuntimeError(f"Overpass API: {exc}") from exc
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise ValueError(
                f"Malformed JSON response from Overpass API: {exc}"
            ) from exc

        elements = data.get("elements")
        if not isinstance(elements, list):
            raise ValueError(
                f"Unexpected Overpass API response shape: 'elements' missing or not a list. "
                f"Keys: {list(data.keys())}"
            )

        logger.info(
            "OSM Overpass returned %d elements for bbox=[%s,%s,%s,%s]",
            len(elements), lat_min, lng_min, lat_max, lng_max,
        )
        return elements
