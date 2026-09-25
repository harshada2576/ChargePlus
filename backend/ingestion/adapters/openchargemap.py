"""ChargePlus — OpenChargeMap (OCM) Ingestion Adapter.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.2 (Build Source-Specific Adapters)

Implements the OpenChargeMap source adapter converting external OCM POI JSON
records into the canonical Step 2.1 contract:
  - Layer 1: RawSourceRecord (unaltered payload + deterministic SHA-256 hash)
  - Layer 2: NormalizedStationRecord, NormalizedConnectorRecord, NormalizedObservationRecord
  - Layer 2 Data Quality: DataQualityValidator evaluation

Key Semantic Protections:
  - Missing means Missing: Missing prices are None (never ₹0). Missing power is None (never 0 kW).
  - Status Demarcation: Static operational status (StatusTypeID 50 "Operational") is NEVER
    misinterpreted as live connector availability (AvailabilityStatus.UNKNOWN).
  - Telemetry Observations: An observation record is produced ONLY if OCM provides automated
    telemetry (StatusTypeID 10 "Currently Available" or 20 "Currently In Use") with a valid timestamp.
  - Connector Aggregation: If OCM reports quantity > 1 without individual plug IDs, a single
    aggregated connector record is emitted. Synthetic IDs are NEVER fabricated.
  - Boundary Lock: This adapter NEVER writes to Supabase or alters the database.
"""

from __future__ import annotations

import os
import re
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from dateutil import parser as dt_parser

from backend.ingestion.base import BaseSourceAdapter
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

# Standard slugification regex
SLUG_CLEAN_REGEX = re.compile(r"[^a-zA-Z0-9_-]+")

# ------------------------------------------------------------------------------
# Confirmed OpenChargeMap Reference Data Mappings
# Verified against official OCM reference dataset (https://api.openchargemap.io/v3/referencedata)
# ------------------------------------------------------------------------------

# OCM ConnectionTypeID -> Canonical StandardConnectorType value
OCM_CONNECTION_TYPE_MAP: dict[int, str] = {
    33: StandardConnectorType.CCS2.value,             # CCS (Type 2) - IEC 62196-3 Configuration FF
    32: StandardConnectorType.CCS1.value,             # CCS (Type 1) - IEC 62196-3 Configuration EE
    25: StandardConnectorType.TYPE_2.value,           # Type 2 (Socket Only) - IEC 62196-2 Type 2
    1036: StandardConnectorType.TYPE_2.value,         # Type 2 (Tethered Connector) - IEC 62196-2
    1: StandardConnectorType.TYPE_1.value,            # Type 1 (J1772)
    2: StandardConnectorType.CHADEMO.value,           # CHAdeMO - IEC 62196-3 Configuration AA
    1038: StandardConnectorType.GB_T.value,           # GB-T AC - GB/T 20234.2 (Socket)
    1039: StandardConnectorType.GB_T.value,           # GB-T AC - GB/T 20234.2 (Tethered Cable)
    1040: StandardConnectorType.GB_T.value,           # GB-T DC - GB/T 20234.3
    3: StandardConnectorType.OTHER.value,             # BS1363 3 Pin 13 Amp
    22: StandardConnectorType.OTHER.value,            # NEMA 5-15R
    10: StandardConnectorType.OTHER.value,            # NEMA 14-30
    34: StandardConnectorType.BHARAT_AC001.value,     # IEC 60309 3-pin
    0: StandardConnectorType.OTHER.value,             # Unknown / Unspecified
}

# OCM StatusTypeID -> Canonical OperationalStatus
OCM_STATUS_TYPE_MAP: dict[int, OperationalStatus] = {
    50: OperationalStatus.OPERATIONAL,              # Operational
    10: OperationalStatus.OPERATIONAL,              # Currently Available (Automated Status)
    20: OperationalStatus.OPERATIONAL,              # Currently In Use (Automated Status)
    75: OperationalStatus.OPERATIONAL,              # Partly Operational (Mixed)
    30: OperationalStatus.TEMPORARILY_UNAVAILABLE,  # Temporarily Unavailable
    100: OperationalStatus.TEMPORARILY_UNAVAILABLE, # Not Operational
    150: OperationalStatus.UNKNOWN,                 # Planned For Future Date
    200: OperationalStatus.PERMANENTLY_CLOSED,      # Removed (Decommissioned)
    0: OperationalStatus.UNKNOWN,                   # Unknown
}

# OCM UsageTypeID -> Public accessibility flag
OCM_PUBLIC_USAGE_IDS = {1, 4, 5, 7}  # 1: Public, 4: Public - Membership, 5: Public - Pay, 7: Public - Notice
OCM_PRIVATE_USAGE_IDS = {2, 3, 6}   # 2: Private, 3: Privately Owned, 6: Private - Staff/Visitors


class OpenChargeMapAdapter(BaseSourceAdapter):
    """Source adapter for the OpenChargeMap (OCM) POI API and dataset."""

    DEFAULT_BASE_URL = "https://api.openchargemap.io/v3/poi/"
    DEFAULT_TIMEOUT_SEC = 15

    @property
    def source_id(self) -> str:
        return "open_charge_map"

    @property
    def source_priority(self) -> int:
        return 70  # High priority community registry

    def extract_source_station_id(self, payload: dict[str, Any]) -> str:
        """Extracts the unique OCM station identifier.
        
        Prefers integer ID; falls back to UUID if ID is missing or non-positive.
        """
        raw_id = payload.get("ID")
        if raw_id is not None and str(raw_id).strip() and str(raw_id).strip() != "0":
            return str(raw_id).strip()

        raw_uuid = payload.get("UUID")
        if raw_uuid and str(raw_uuid).strip():
            return str(raw_uuid).strip()

        raise ValueError("Payload missing required OpenChargeMap 'ID' and 'UUID' identifiers")

    def _parse_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        """Parses an ISO 8601 timestamp string into timezone-aware UTC datetime."""
        if not ts_str or not isinstance(ts_str, str):
            return None
        try:
            dt = dt_parser.isoparse(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except Exception:
            return None

    def _slugify(self, text: Optional[str]) -> Optional[str]:
        """Generates an alphanumeric-safe slug token for operator mapping."""
        if not text:
            return None
        cleaned = SLUG_CLEAN_REGEX.sub("-", text.strip().lower()).strip("-")
        return cleaned or None

    def _map_connector_type(
        self,
        conn_type_id: Optional[int],
        title: Optional[str],
        formal_name: Optional[str]
    ) -> tuple[str, str]:
        """Maps OCM connection type to canonical standard string and returns (normalized, raw_label)."""
        raw_label = title or formal_name or (f"OCM-Type-{conn_type_id}" if conn_type_id is not None else "Unknown")
        
        # 1. Exact ID mapping
        if conn_type_id is not None and conn_type_id in OCM_CONNECTION_TYPE_MAP:
            return OCM_CONNECTION_TYPE_MAP[conn_type_id], raw_label

        # 2. Text heuristics fallback for unmapped or custom IDs
        label_lower = raw_label.lower()
        if "ccs" in label_lower and ("2" in label_lower or "combo 2" in label_lower):
            return StandardConnectorType.CCS2.value, raw_label
        if "ccs" in label_lower and "1" in label_lower:
            return StandardConnectorType.CCS1.value, raw_label
        if "type 2" in label_lower or "mennekes" in label_lower:
            return StandardConnectorType.TYPE_2.value, raw_label
        if "type 1" in label_lower or "j1772" in label_lower:
            return StandardConnectorType.TYPE_1.value, raw_label
        if "chademo" in label_lower:
            return StandardConnectorType.CHADEMO.value, raw_label
        if "gb/t" in label_lower or "gb-t" in label_lower or "gbt" in label_lower:
            return StandardConnectorType.GB_T.value, raw_label
        if "bharat" in label_lower and "dc" in label_lower:
            return StandardConnectorType.BHARAT_DC001.value, raw_label
        if "bharat" in label_lower and "ac" in label_lower:
            return StandardConnectorType.BHARAT_AC001.value, raw_label
        if "3 pin" in label_lower or "wall" in label_lower or "bs1363" in label_lower:
            return StandardConnectorType.OTHER.value, raw_label

        return StandardConnectorType.OTHER.value, raw_label


    def normalize_station(self, raw: RawSourceRecord) -> NormalizedStationRecord:
        """Transforms an OpenChargeMap Layer 1 record into a canonical NormalizedStationRecord."""
        payload = raw.raw_payload
        station_id = raw.source_station_id

        # ----------------------------------------------------------------------
        # 1. Address & Geographic Coordinates
        # ----------------------------------------------------------------------
        addr = payload.get("AddressInfo")
        if not isinstance(addr, dict):
            addr = {}

        # Coordinate extraction: do not default to 0.0 or Mumbai if missing
        raw_lat = addr.get("Latitude")
        raw_lng = addr.get("Longitude")
        try:
            latitude = float(raw_lat) if raw_lat is not None else None
        except (ValueError, TypeError):
            latitude = None

        try:
            longitude = float(raw_lng) if raw_lng is not None else None
        except (ValueError, TypeError):
            longitude = None

        if latitude is None or longitude is None:
            raise ValueError(f"Station {station_id} missing valid numerical Latitude/Longitude coordinates")

        # Name extraction & cleaning
        raw_title = addr.get("Title") or payload.get("GeneralComments") or ""
        clean_name = re.sub(r"\s+", " ", str(raw_title)).strip()
        if not clean_name:
            clean_name = f"OCM Charging Station {station_id}"

        # Address components
        address_line = addr.get("AddressLine1")
        locality = addr.get("AddressLine2")
        city = addr.get("Town") or "Mumbai"
        state = addr.get("StateOrProvince") or "Maharashtra"
        postal_code = str(addr.get("Postcode")).strip() if addr.get("Postcode") is not None else None

        # Country normalization
        country_obj = addr.get("Country")
        if isinstance(country_obj, dict):
            country_name = country_obj.get("Title") or country_obj.get("ISOCode") or "India"
        else:
            country_name = "India"

        # ----------------------------------------------------------------------
        # 2. Operator & Network
        # ----------------------------------------------------------------------
        op_info = payload.get("OperatorInfo")
        operator_name: Optional[str] = None
        operator_slug: Optional[str] = None
        if isinstance(op_info, dict) and op_info.get("Title"):
            operator_name = str(op_info["Title"]).strip()
            operator_slug = self._slugify(operator_name)

        # ----------------------------------------------------------------------
        # 3. Operational Status & Public Access
        # ----------------------------------------------------------------------
        status_id = payload.get("StatusTypeID")
        if status_id is None and isinstance(payload.get("StatusType"), dict):
            status_id = payload["StatusType"].get("ID")

        operational_status = OCM_STATUS_TYPE_MAP.get(status_id, OperationalStatus.UNKNOWN)

        # Public access
        usage_id = payload.get("UsageTypeID")
        if usage_id is None and isinstance(payload.get("UsageType"), dict):
            usage_id = payload["UsageType"].get("ID")

        if usage_id in OCM_PRIVATE_USAGE_IDS:
            is_public = False
            access_type = "Private / Restricted"
        elif usage_id in OCM_PUBLIC_USAGE_IDS:
            is_public = True
            access_type = "Public"
        else:
            is_public = True
            access_type = "Public"

        # Contact & URL
        phone = addr.get("ContactTelephone1") or addr.get("ContactEmail")
        website_url = addr.get("RelatedURL") or (op_info.get("WebsiteURL") if isinstance(op_info, dict) else None)
        canonical_source_url = f"https://openchargemap.org/site/poi/details/{station_id}"

        # ----------------------------------------------------------------------
        # 4. Connectors
        # ----------------------------------------------------------------------
        connectors: list[NormalizedConnectorRecord] = []
        raw_conns = payload.get("Connections")

        if isinstance(raw_conns, list):
            for conn in raw_conns:
                if not isinstance(conn, dict):
                    continue

                conn_id_val = conn.get("ID")
                source_conn_id = str(conn_id_val).strip() if conn_id_val is not None else None

                # Quantity (Aggregation Support)
                try:
                    raw_qty = conn.get("Quantity")
                    quantity = int(raw_qty) if raw_qty is not None and int(raw_qty) > 0 else 1
                except (ValueError, TypeError):
                    quantity = 1

                # If quantity > 1 without distinct individual plug IDs, it is an aggregated specification
                is_aggregated = quantity > 1 and source_conn_id is None

                # Connector Type
                c_type_id = conn.get("ConnectionTypeID")
                c_type_obj = conn.get("ConnectionType") if isinstance(conn.get("ConnectionType"), dict) else {}
                title = c_type_obj.get("Title")
                formal_name = c_type_obj.get("FormalName")
                norm_conn_type, raw_label = self._map_connector_type(c_type_id, title, formal_name)

                # Power (kW) — Never default to 0.0 kW
                power_kw: Optional[float] = None
                raw_power = conn.get("PowerKW")
                if raw_power is not None:
                    try:
                        p_val = float(raw_power)
                        if p_val > 0.0:
                            power_kw = p_val
                    except (ValueError, TypeError):
                        power_kw = None

                # Voltage (V) & Amperage (A)
                voltage_v: Optional[float] = None
                if conn.get("Voltage") is not None:
                    try:
                        v_val = float(conn["Voltage"])
                        if v_val > 0.0:
                            voltage_v = v_val
                    except (ValueError, TypeError):
                        voltage_v = None

                amperage_a: Optional[float] = None
                if conn.get("Amps") is not None:
                    try:
                        a_val = float(conn["Amps"])
                        if a_val > 0.0:
                            amperage_a = a_val
                    except (ValueError, TypeError):
                        amperage_a = None

                # Current Type (AC / DC)
                current_type_obj = conn.get("CurrentType") if isinstance(conn.get("CurrentType"), dict) else {}
                current_type_id = conn.get("CurrentTypeID") or current_type_obj.get("ID")
                charging_standard: Optional[str] = formal_name

                # Pricing per connector / station usage cost
                usage_cost = payload.get("UsageCost")
                pricing_type = PricingType.UNKNOWN
                price_per_kwh: Optional[float] = None

                if usage_cost and isinstance(usage_cost, str):
                    cost_lower = usage_cost.lower()
                    if "free" in cost_lower or cost_lower.strip() in ("0", "0.0", "0.00", "no charge"):
                        pricing_type = PricingType.FREE
                    elif any(k in cost_lower for k in ("pay", "tariff", "kwh", "rs", "₹", "inr", "fee")):
                        pricing_type = PricingType.PAID

                # Connector-level availability (only if specifically reported on connector)
                conn_status_id = conn.get("StatusTypeID")
                if conn_status_id == 10:
                    conn_availability = AvailabilityStatus.AVAILABLE
                elif conn_status_id == 20:
                    conn_availability = AvailabilityStatus.BUSY
                elif conn_status_id in (30, 100):
                    conn_availability = AvailabilityStatus.BROKEN
                else:
                    conn_availability = AvailabilityStatus.UNKNOWN

                connectors.append(
                    NormalizedConnectorRecord(
                        source_connector_id=source_conn_id,
                        connector_type=norm_conn_type,
                        raw_connector_type=raw_label,
                        charging_standard=charging_standard,
                        power_kw=power_kw,
                        voltage_v=voltage_v,
                        amperage_a=amperage_a,
                        quantity=quantity,
                        is_aggregated=is_aggregated,
                        pricing_type=pricing_type,
                        price_per_kwh=price_per_kwh,
                        currency="INR",
                        status=conn_availability,
                    )
                )

        # ----------------------------------------------------------------------
        # 5. Telemetry Observation (Strict Semantics)
        # ----------------------------------------------------------------------
        # An observation is produced ONLY when OCM provides genuine automated telemetry
        # (StatusTypeID 10 "Currently Available" or 20 "Currently In Use") with a timestamp.
        observation: Optional[NormalizedObservationRecord] = None
        source_updated_str = payload.get("DateLastStatusUpdate") or payload.get("DateCreated")
        observed_time = self._parse_timestamp(source_updated_str)

        if status_id in (10, 20) and observed_time is not None:
            observed_availability = (
                AvailabilityStatus.AVAILABLE if status_id == 10 else AvailabilityStatus.BUSY
            )
            observation = NormalizedObservationRecord(
                source_id=self.source_id,
                source_station_id=station_id,
                source_connector_id=None,
                observed_at=observed_time,
                retrieved_at=raw.retrieval_timestamp,
                availability_status=observed_availability,
                queue_level=QueueLevel.UNKNOWN,  # OCM does not measure vehicle queue counts
                available_connectors=None,
                total_connectors=len(connectors) if connectors else None,
                raw_status_label=payload.get("StatusType", {}).get("Title") if isinstance(payload.get("StatusType"), dict) else None,
                confidence_score=0.90,  # High confidence automated feed
                source_payload_hash=raw.payload_hash,
            )

        # ----------------------------------------------------------------------
        # 6. Source-Specific Extra Metadata (Layer 1 Preservation)
        # ----------------------------------------------------------------------
        extra_metadata: dict[str, Any] = {
            "ocm_uuid": payload.get("UUID"),
            "data_provider": payload.get("DataProvider"),
            "number_of_points": payload.get("NumberOfPoints"),
            "general_comments": payload.get("GeneralComments"),
            "usage_cost_raw": payload.get("UsageCost"),
            "date_last_status_update": payload.get("DateLastStatusUpdate"),
            "date_created": payload.get("DateCreated"),
            "submission_status_type_id": payload.get("SubmissionStatusTypeID"),
        }

        return NormalizedStationRecord(
            source_id=self.source_id,
            source_station_id=station_id,
            source_url=canonical_source_url,
            raw_payload_hash=raw.payload_hash,
            name=clean_name,
            raw_name=str(raw_title) if raw_title else None,
            operator_name=operator_name,
            operator_slug=operator_slug,
            latitude=latitude,
            longitude=longitude,
            address_line=address_line,
            locality=locality,
            city=city,
            state=state,
            postal_code=postal_code,
            country=country_name,
            is_24_hours=None,
            opening_time=None,
            closing_time=None,
            access_type=access_type,
            is_public=is_public,
            operational_status=operational_status,
            phone=phone,
            website_url=website_url,
            connectors=connectors,
            observation=observation,
            extra_metadata=extra_metadata,
        )

    def fetch_raw(
        self,
        country_code: str = "IN",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        distance_km: Optional[float] = None,
        bounding_box: Optional[tuple[float, float, float, float]] = None,
        max_results: int = 100,
        api_key: Optional[str] = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> list[dict[str, Any]]:
        """Fetches raw charging station payloads from the OpenChargeMap v3 REST API.
        
        Requires an OpenChargeMap API key via OPENCHARGEMAP_API_KEY environment variable
        or direct api_key argument.
        
        Supports bounding box filtering (lat_min, lng_min, lat_max, lng_max) or point + distance.
        Isolates network transport and handles timeouts, rate limits, and authentication errors.
        """
        resolved_key = api_key or os.getenv("OPENCHARGEMAP_API_KEY")
        if not resolved_key:
            raise ValueError(
                "OpenChargeMap API key required. Provide 'api_key' argument or set 'OPENCHARGEMAP_API_KEY' environment variable."
            )

        headers = {
            "User-Agent": "ChargePlus-Ingestion/1.0 (https://github.com/harshada2576/ChargePlus)",
            "X-API-Key": resolved_key,
        }

        params: dict[str, Any] = {
            "output": "json",
            "verbose": "false",
            "compact": "false",  # Return full reference objects and connection specs
            "maxresults": min(max(1, max_results), 500),
            "countrycode": country_code,
        }

        if bounding_box is not None:
            lat_min, lng_min, lat_max, lng_max = bounding_box
            params["boundingbox"] = f"({lat_min},{lng_min}),({lat_max},{lng_max})"
        elif latitude is not None and longitude is not None:
            params["latitude"] = latitude
            params["longitude"] = longitude
            if distance_km is not None:
                params["distance"] = distance_km
                params["distanceunit"] = "KM"

        try:
            response = requests.get(
                self.DEFAULT_BASE_URL,
                headers=headers,
                params=params,
                timeout=timeout_sec,
            )

            if response.status_code == 401 or response.status_code == 403:
                raise PermissionError("OpenChargeMap API authentication failed (invalid or missing API key)")
            elif response.status_code == 429:
                raise RuntimeError("OpenChargeMap API rate limit exceeded. Please back off before retrying.")
            elif response.status_code >= 500:
                raise RuntimeError(f"OpenChargeMap upstream server error (HTTP {response.status_code})")

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, list):
                raise ValueError(f"Expected list of POI records from OpenChargeMap, got {type(data).__name__}")

            return data

        except requests.exceptions.Timeout as e:
            logger.error("Timeout fetching from OpenChargeMap API: %s", e)
            raise TimeoutError(f"OpenChargeMap API request timed out after {timeout_sec}s") from e
        except requests.exceptions.RequestException as e:
            logger.error("HTTP error fetching from OpenChargeMap API: %s", e)
            raise ConnectionError(f"Failed to connect to OpenChargeMap API: {e}") from e
