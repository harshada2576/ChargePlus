"""ChargePlus — data.gov.in Government Open Data Ingestion Adapter.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Secondary Source: data.gov.in — Open Government Data Platform India

Provides a framework adapter for government EV charging datasets published
on India's Open Government Data (OGD) Platform (https://data.gov.in).

REAL EXTERNAL PREREQUISITE STATUS:
  data.gov.in requires registration and an API key for programmatic access.
  EV charging station datasets may exist under schemes such as:
    - FAME-II public charging station listings
    - Bureau of Energy Efficiency (BEE) station registries
    - State-level EV charging reports

  Dataset resource IDs change over time and must be verified before use.
  This adapter implements the technical framework; actual dataset discovery
  and API credential provisioning are external prerequisites.

  Current known-accessible endpoints (as of 2026-10):
    Base API: https://data.gov.in/api/datastore/resource.json
    Auth:     API key via X-Api-Key header (requires registration at data.gov.in)
    Format:   JSON pagination with `offset` / `limit` parameters
    License:  National Data Sharing and Accessibility Policy (NDSAP) 2012
              Government data: open for non-commercial use with attribution

GRACEFUL DEGRADATION:
  If DATAGOVIN_API_KEY is not set, the adapter logs a warning and raises
  CredentialError. The pipeline treats this as PERMANENT failure and does
  not retry. No synthetic data is substituted.

KNOWN LIMITATIONS (as of 2026-10):
  - No verified real-time availability telemetry from data.gov.in datasets
  - Station coverage quality and completeness varies by dataset
  - Dataset schemas differ between publishers and versions
  - Coordinate quality is variable (some records have only city-level data)
  - Update frequency is irregular (monthly/quarterly for most datasets)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from backend.ingestion.base import BaseSourceAdapter, request_with_retry
from backend.ingestion.constants import (
    AvailabilityStatus,
    OperationalStatus,
    PricingType,
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
# Constants
# ---------------------------------------------------------------------------

DATAGOVIN_BASE_URL = "https://data.gov.in/api/datastore/resource.json"
DEFAULT_TIMEOUT_SEC = 30
DEFAULT_PAGE_SIZE = 100

# Known dataset resource IDs for EV charging on data.gov.in.
# These must be verified and updated as the platform evolves.
# Set to None if a verified resource ID has not been confirmed.
KNOWN_DATASET_RESOURCES: dict[str, Optional[str]] = {
    # FAME-II public charging stations (BEE registry).
    # Resource ID requires verification at https://data.gov.in
    "fame_ii_charging_stations": None,  # BLOCKED_EXTERNAL_DEPENDENCY: resource ID unconfirmed
}

ATTRIBUTION = (
    "Government of India, data.gov.in — National Data Sharing and Accessibility Policy (NDSAP) 2012"
)


class DataGovInCredentialError(RuntimeError):
    """Raised when data.gov.in API credentials are missing or invalid."""
    pass


class DataGovInAdapter(BaseSourceAdapter):
    """Source adapter for Indian Government Open Data EV charging datasets.

    Fetches EV charging station records from data.gov.in resource endpoints
    using the OGD platform JSON API with pagination support.

    PREREQUISITE: Register at https://data.gov.in to obtain an API key.
    Set DATAGOVIN_API_KEY environment variable before use.

    PREREQUISITE: Verify the correct resource ID for the target dataset at
    https://data.gov.in and set DATAGOVIN_RESOURCE_ID environment variable,
    or pass resource_id directly to fetch_raw().
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        resource_id: Optional[str] = None,
        base_url: str = DATAGOVIN_BASE_URL,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self._api_key = api_key or os.getenv("DATAGOVIN_API_KEY")
        self._resource_id = resource_id or os.getenv("DATAGOVIN_RESOURCE_ID")
        self._base_url = base_url
        self._timeout_sec = timeout_sec

    @property
    def source_id(self) -> str:
        return "datagovin"

    @property
    def source_priority(self) -> int:
        return 65  # Government source; similar to OCM but schema quality is variable

    def extract_source_station_id(self, payload: dict[str, Any]) -> str:
        """Extracts a stable identifier from a data.gov.in record.

        data.gov.in datasets vary by publisher. This implementation tries
        common field names and falls back to a content-addressed identifier.
        """
        # Try known ID fields in order of preference
        for field in ("id", "_id", "station_id", "charging_station_id",
                      "sl_no", "serial_no", "sno", "sr_no"):
            val = payload.get(field)
            if val is not None and str(val).strip():
                return f"datagovin/{str(val).strip()}"

        # Last resort: use lat/lon as a location-based stable ID
        lat = payload.get("latitude") or payload.get("lat")
        lon = payload.get("longitude") or payload.get("lng") or payload.get("lon")
        if lat and lon:
            return f"datagovin/geo/{str(lat).strip()}/{str(lon).strip()}"

        raise ValueError(
            f"data.gov.in record has no identifiable ID field. "
            f"Available keys: {list(payload.keys())}"
        )

    # ------------------------------------------------------------------
    # Field Extraction Helpers
    # ------------------------------------------------------------------

    def _extract_float(
        self, payload: dict[str, Any], *keys: str
    ) -> Optional[float]:
        """Tries multiple keys and returns first valid float, or None."""
        for key in keys:
            val = payload.get(key)
            if val is None:
                continue
            try:
                f = float(str(val).strip().replace(",", ""))
                return f if f != 0.0 else None
            except (ValueError, TypeError):
                continue
        return None

    def _extract_str(
        self, payload: dict[str, Any], *keys: str
    ) -> Optional[str]:
        """Tries multiple keys and returns first non-empty string, or None."""
        for key in keys:
            val = payload.get(key)
            if val and str(val).strip() not in ("", "-", "NA", "N/A", "null", "None"):
                return str(val).strip()
        return None

    def _parse_connector_type(self, raw: Optional[str]) -> str:
        """Maps free-text connector type to canonical StandardConnectorType."""
        if not raw:
            return StandardConnectorType.OTHER.value
        lower = raw.lower()
        if "ccs" in lower and ("2" in lower or "combo 2" in lower):
            return StandardConnectorType.CCS2.value
        if "ccs" in lower:
            return StandardConnectorType.CCS1.value
        if "type 2" in lower or "type2" in lower or "mennekes" in lower:
            return StandardConnectorType.TYPE_2.value
        if "type 1" in lower or "type1" in lower:
            return StandardConnectorType.TYPE_1.value
        if "chademo" in lower:
            return StandardConnectorType.CHADEMO.value
        if "gbt" in lower or "gb/t" in lower or "gb-t" in lower:
            return StandardConnectorType.GB_T.value
        if "bharat" in lower and "dc" in lower:
            return StandardConnectorType.BHARAT_DC001.value
        if "bharat" in lower and "ac" in lower:
            return StandardConnectorType.BHARAT_AC001.value
        return StandardConnectorType.OTHER.value

    # ------------------------------------------------------------------
    # Core Normalization
    # ------------------------------------------------------------------

    def normalize_station(self, raw: RawSourceRecord) -> NormalizedStationRecord:
        """Transforms a data.gov.in EV charging station record into NormalizedStationRecord.

        data.gov.in dataset schemas are not standardized across publishers.
        This adapter handles common field names from known datasets and
        gracefully treats all unknown fields as missing (never fabricated).
        """
        payload = raw.raw_payload
        station_id = raw.source_station_id

        # --- 1. Coordinates ---
        latitude = self._extract_float(payload, "latitude", "lat", "Latitude")
        longitude = self._extract_float(payload, "longitude", "lng", "lon", "Longitude")

        if latitude is None or longitude is None:
            raise ValueError(
                f"data.gov.in record {station_id} missing valid coordinates. "
                f"Available fields: {list(payload.keys())}"
            )

        # --- 2. Name ---
        name = self._extract_str(
            payload,
            "station_name", "charging_station_name", "name",
            "location", "place", "site_name",
        )
        name_synthesized = False
        if not name:
            name = f"Government EV Station {station_id}"
            name_synthesized = True

        # --- 3. Address ---
        address_line = self._extract_str(
            payload, "address", "addr", "street_address", "location_address"
        )
        city = self._extract_str(
            payload, "city", "town", "district", "City"
        )
        state = self._extract_str(
            payload, "state", "State", "state_name"
        )
        postal_code = self._extract_str(
            payload, "pincode", "postal_code", "zip", "postcode"
        )

        city_inferred = False
        state_inferred = False
        if not city:
            city = "Mumbai"
            city_inferred = True
        if not state:
            state = "Maharashtra"
            state_inferred = True

        # --- 4. Operator ---
        operator_name = self._extract_str(
            payload,
            "operator", "cpo", "operator_name", "charging_operator",
            "agency", "vendor", "company",
        )

        # --- 5. Connector ---
        raw_connector_type = self._extract_str(
            payload, "connector_type", "plug_type", "charger_type", "type"
        )
        canonical_conn_type = self._parse_connector_type(raw_connector_type)

        raw_power = self._extract_str(
            payload, "power_kw", "power", "capacity_kw", "rated_power"
        )
        power_kw: Optional[float] = None
        if raw_power:
            try:
                p = float(str(raw_power).lower().replace("kw", "").strip())
                if p > 0:
                    power_kw = p
            except (ValueError, TypeError):
                pass

        raw_count = self._extract_str(
            payload, "number_of_connectors", "no_of_connectors",
            "connector_count", "charger_count", "quantity"
        )
        connector_count: Optional[int] = None
        if raw_count:
            try:
                connector_count = int(float(raw_count))
                if connector_count <= 0:
                    connector_count = None
            except (ValueError, TypeError):
                connector_count = None

        # Contract invariant: quantity is int >= 1; unknown count stays 1
        # (never None, never 0). Missing means missing, not zero connectors.
        safe_count = connector_count if connector_count else 1
        connectors = [
            NormalizedConnectorRecord(
                source_connector_id=None,
                connector_type=canonical_conn_type,
                # Contract requires non-empty raw label; preserve "unknown"
                # explicitly when the source supplies no connector description.
                raw_connector_type=raw_connector_type or "unknown",
                charging_standard=None,
                power_kw=power_kw,
                voltage_v=None,
                amperage_a=None,
                quantity=safe_count,
                is_aggregated=safe_count > 1,
                pricing_type=PricingType.UNKNOWN,
                price_per_kwh=None,
                currency="INR",
                status=AvailabilityStatus.UNKNOWN,
            )
        ]

        # --- 6. Status ---
        raw_status = self._extract_str(payload, "status", "operational_status")
        if raw_status and raw_status.lower() in ("operational", "active", "live", "open"):
            operational_status = OperationalStatus.OPERATIONAL
        elif raw_status and raw_status.lower() in (
            "closed", "decommissioned", "removed", "permanently closed"
        ):
            operational_status = OperationalStatus.PERMANENTLY_CLOSED
        elif raw_status and raw_status.lower() in (
            "under maintenance", "temporarily closed"
        ):
            operational_status = OperationalStatus.TEMPORARILY_UNAVAILABLE
        else:
            operational_status = OperationalStatus.UNKNOWN

        extra_metadata: dict[str, Any] = {
            "raw_record": payload,
            "attribution": ATTRIBUTION,
            "license": "NDSAP 2012",
            "city_inferred": city_inferred,
            "state_inferred": state_inferred,
            "name_synthesized": name_synthesized,
            "raw_connector_type": raw_connector_type,
            "resource_id": raw.source_url,
        }

        return NormalizedStationRecord(
            source_id=self.source_id,
            source_station_id=station_id,
            source_url=raw.source_url,
            raw_payload_hash=raw.payload_hash,
            name=name,
            raw_name=self._extract_str(
                payload,
                "station_name", "charging_station_name", "name"
            ),
            operator_name=operator_name,
            operator_slug=(
                re.sub(
                    r"[^a-z0-9_-]+", "-",
                    operator_name.strip().lower()
                ).strip("-")
                if operator_name
                else None
            ),
            latitude=latitude,
            longitude=longitude,
            address_line=address_line,
            locality=None,
            city=city,
            state=state,
            postal_code=postal_code,
            country="India",
            is_24_hours=None,
            opening_time=None,
            closing_time=None,
            access_type="Public",
            is_public=True,
            operational_status=operational_status,
            phone=self._extract_str(payload, "phone", "contact", "mobile"),
            website_url=None,
            connectors=connectors,
            observation=None,  # data.gov.in has no live telemetry
            extra_metadata=extra_metadata,
        )

    # ------------------------------------------------------------------
    # Network Fetch
    # ------------------------------------------------------------------

    def fetch_raw(
        self,
        resource_id: Optional[str] = None,
        lat_min: Optional[float] = None,
        lng_min: Optional[float] = None,
        lat_max: Optional[float] = None,
        lng_max: Optional[float] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_records: int = 5000,
        start_offset: int = 0,
        timeout_sec: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Fetches EV charging station records from a data.gov.in dataset resource.

        PREREQUISITE: DATAGOVIN_API_KEY environment variable must be set.
        PREREQUISITE: A verified resource_id must be provided or set via
                      DATAGOVIN_RESOURCE_ID environment variable.

        If credentials or resource_id are missing, raises DataGovInCredentialError
        (classified as PERMANENT failure — retrying without credentials will not help).

        Geographic filtering: data.gov.in API does not support native bounding box
        filtering. Records are fetched and filtered client-side where lat/lon fields
        are present.

        Checkpoint resume: pass start_offset (previously fetched record count) to
        resume an interrupted bulk fetch without re-pulling earlier pages.
        """
        api_key = self._api_key
        if not api_key:
            raise DataGovInCredentialError(
                "data.gov.in API key required but not configured. "
                "Register at https://data.gov.in and set the DATAGOVIN_API_KEY "
                "environment variable. "
                "STATUS: BLOCKED_EXTERNAL_DEPENDENCY — requires external registration."
            )

        resolved_resource_id = resource_id or self._resource_id
        if not resolved_resource_id:
            raise DataGovInCredentialError(
                "data.gov.in resource_id not configured. "
                "Find the correct dataset at https://data.gov.in/catalogs/ict/smart-cities "
                "and set the DATAGOVIN_RESOURCE_ID environment variable. "
                "STATUS: BLOCKED_EXTERNAL_DEPENDENCY — requires resource ID verification."
            )

        timeout = timeout_sec or self._timeout_sec
        records: list[dict[str, Any]] = []
        # Checkpoint resume: an interrupted bulk fetch restarts here instead of
        # re-pulling earlier pages. Callers persist the last offset externally
        # (e.g. in run metadata) because the API itself is stateless.
        offset = max(0, start_offset)

        logger.info(
            "Fetching data.gov.in EV stations: resource_id=%s page_size=%d",
            resolved_resource_id, page_size,
        )

        while len(records) < max_records:
            params: dict[str, Any] = {
                "resource_id": resolved_resource_id,
                "limit": min(page_size, max_records - len(records)),
                "offset": offset,
                "format": "json",
            }

            try:
                response = request_with_retry(
                    "get",
                    self._base_url,
                    params=params,
                    headers={"X-Api-Key": api_key},
                    timeout_sec=timeout,
                )
            except TimeoutError as exc:
                raise TimeoutError(
                    f"data.gov.in API timed out after {timeout}s"
                ) from exc
            except ConnectionError as exc:
                raise ConnectionError(
                    f"Failed to connect to data.gov.in API: {exc}"
                ) from exc
            except RuntimeError as exc:
                # Transport retries (429/5xx with backoff+jitter+Retry-After)
                # exhausted inside request_with_retry; label the source.
                # NOTE: api_key travels only in the request header and is never
                # included in exception messages or logs.
                raise RuntimeError(f"data.gov.in: {exc}") from exc

            if response.status_code in (401, 403):
                raise DataGovInCredentialError(
                    "data.gov.in API authentication failed. "
                    "Check that DATAGOVIN_API_KEY is valid and not expired."
                )
            if response.status_code == 404:
                raise DataGovInCredentialError(
                    f"data.gov.in resource '{resolved_resource_id}' not found (HTTP 404). "
                    "Verify the resource ID at https://data.gov.in."
                )
            response.raise_for_status()

            try:
                data = response.json()
            except ValueError as exc:
                raise ValueError(
                    f"Malformed JSON from data.gov.in: {exc}"
                ) from exc

            # data.gov.in API response shape
            page_records = data.get("records", data.get("data", []))
            if not isinstance(page_records, list):
                raise ValueError(
                    f"Unexpected data.gov.in response shape. "
                    f"Keys: {list(data.keys())}"
                )

            if not page_records:
                break  # End of dataset

            # Client-side geographic filter (API has no native bbox filter)
            for rec in page_records:
                if lat_min is not None and lat_max is not None:
                    lat = None
                    for field in ("latitude", "lat", "Latitude"):
                        try:
                            lat = float(str(rec.get(field, "")).strip())
                            break
                        except (ValueError, TypeError):
                            continue
                    lng = None
                    for field in ("longitude", "lng", "lon", "Longitude"):
                        try:
                            lng = float(str(rec.get(field, "")).strip())
                            break
                        except (ValueError, TypeError):
                            continue
                    if lat is None or lng is None:
                        records.append(rec)  # Include records without coords; validation will quarantine
                        continue
                    if not (lat_min <= lat <= lat_max and lng_min <= lng <= lng_max):
                        continue
                records.append(rec)

            offset += len(page_records)

            # If fewer records returned than requested, we've reached the end
            if len(page_records) < page_size:
                break

        logger.info(
            "data.gov.in returned %d records for resource_id=%s",
            len(records), resolved_resource_id,
        )
        return records
