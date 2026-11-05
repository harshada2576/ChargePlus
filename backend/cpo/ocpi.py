"""ChargePlus — OCPI 2.2.1 CPO Integration (Locations pull subset).

Implements the ingestion-relevant subset of the Open Charge Point Interface
2.2.1 (https://github.com/ocpi/ocpi) for pulling public charging inventory
from a bilateral CPO partner:

  - Versions negotiation (requires 2.2.1; other versions are refused, not
    silently downgraded).
  - Credentials-handshake payload builders (registration + version listing).
  - Locations module pull: date_from incremental, offset/limit pagination via
    RFC5988 Link headers, X-Total-Count/X-Limit observability.
  - Canonical mapping Location → NormalizedStationRecord (+ live EVSE-status
    observation, tariff mapping helper).

Out of scope (require partner contracts beyond inventory pull): Commands,
Sessions, CDRs, Tokens, SmartCharging, HubClientInfo. The mapping helpers for
tariffs are implemented and tested so pricing is never guessed when tariff
pulls are enabled later.

Every partner record flows through BaseSourceAdapter → canonical validation,
so malformed partner payloads are isolated per record, never batch-fatal.

Auth: `Authorization: Token <partner token>` (server-side env only).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

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

from backend.cpo.partners import PartnerConfig, PartnerCredentialError

logger = logging.getLogger("chargeplus.cpo.ocpi")

OCPI_VERSION = "2.2.1"
OCPI_SUCCESS_CODE = 1000
DEFAULT_PAGE_SIZE = 100


class OcpiVersionError(ValueError):
    """Negotiated OCPI version unsupported (PERMANENT: retry will not help)."""
    pass


class OcpiClientError(ValueError):
    """OCPI 2xxx application error (PERMANENT for the same request)."""
    pass


# Transport seam: module-global default keeps request patching working, and
# per-call `send=` injection lets the deterministic simulator drive the real
# pull/mapping code without any network.
_default_send = request_with_retry


def _sender(send: Optional[Callable] = None) -> Callable:
    return send if send is not None else _default_send


def _auth_headers(config: PartnerConfig) -> dict[str, str]:
    config.require_usable()
    token = config.token or ""
    return {"Authorization": f"Token {token}"}


# ---------------------------------------------------------------------------
# Versions negotiation + credentials handshake (pure builders/parsers)
# ---------------------------------------------------------------------------

def select_version_url(versions_payload: list[dict[str, Any]]) -> str:
    """Selects the OCPI 2.2.1 endpoint URL from a versions list.

    Refuses anything else: silently talking a different protocol version to a
    partner is a data-contract violation, not a fallback.
    """
    if not isinstance(versions_payload, list):
        raise OcpiVersionError("OCPI versions payload is not a list")
    for entry in versions_payload:
        if str(entry.get("version")) == OCPI_VERSION and entry.get("url"):
            return str(entry["url"])
    available = [str(e.get("version")) for e in versions_payload if isinstance(e, dict)]
    raise OcpiVersionError(
        f"Partner does not offer OCPI {OCPI_VERSION} (offers: {available or 'none'}). "
        "Refusing to negotiate a different version without a contract."
    )


def find_module_url(version_detail: dict[str, Any], identifier: str) -> str:
    """Finds a module endpoint URL (e.g. 'locations') in version details."""
    endpoints = version_detail.get("endpoints") or []
    if not isinstance(endpoints, list):
        raise OcpiClientError("OCPI version detail has no endpoints list")
    for ep in endpoints:
        if str(ep.get("identifier")).lower() == identifier.lower() and ep.get("url"):
            return str(ep["url"])
    available = [str(e.get("identifier")) for e in endpoints if isinstance(e, dict)]
    raise OcpiClientError(
        f"Partner version detail offers no '{identifier}' module "
        f"(offers: {available or 'none'})"
    )


def build_credentials_registration(
    token_a: str, versions_url: str, roles: list[dict[str, str]]
) -> dict[str, Any]:
    """Builds the OCPI credentials-registration POST body (TOKEN_A → TOKEN_C)."""
    if not token_a or not versions_url or not roles:
        raise ValueError("token_a, versions_url, and roles are all required")
    return {"token": token_a, "url": versions_url, "roles": roles}


def check_ocpi_response(body: Any, *, context: str) -> Any:
    """Validates an OCPI response envelope; returns the data payload.

    OCPI returns HTTP 200 with application status codes: 1000 = success,
    2xxx = client error (do not retry the same request), 3xxx/4xxx = server
    error (retryable at run level).
    """
    if not isinstance(body, dict) or "status_code" not in body:
        raise OcpiClientError(f"{context}: not an OCPI response envelope")
    code = body.get("status_code")
    if code == OCPI_SUCCESS_CODE:
        return body.get("data")
    message = body.get("status_message") or body.get("user_message") or "no detail"
    if isinstance(code, int) and 2000 <= code < 3000:
        raise OcpiClientError(f"{context}: OCPI error {code}: {message}")
    raise RuntimeError(f"{context}: OCPI server error (code {code}): {message}")


def parse_link_header(value: Any) -> dict[str, str]:
    """Parses an RFC5988 Link header into {rel: url}."""    """Parses an RFC5988 Link header into {rel: url}."""
    links: dict[str, str] = {}
    if not value or not isinstance(value, str):
        return links
    for part in value.split(","):
        segments = [s.strip() for s in part.split(";")]
        if not segments or not segments[0].startswith("<"):
            continue
        url = segments[0][1:].split(">", 1)[0]
        for param in segments[1:]:
            if "=" in param:
                key, _, val = param.partition("=")
                if key.strip().lower() == "rel":
                    links[val.strip().strip('"').lower()] = url
    return links


# ---------------------------------------------------------------------------
# Pull primitives (parameterized, bounded, paginated)
# ---------------------------------------------------------------------------

def _response_json(response: Any, *, context: str) -> Any:
    """Extracts JSON, raising a clear error on malformed payloads."""
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError(f"{context}: malformed JSON payload: {exc}") from exc


def fetch_versions(
    config: PartnerConfig, *, send: Optional[Callable] = None
) -> list[dict[str, Any]]:
    """GETs the partner versions endpoint and returns the raw versions list."""
    sender = _sender(send)
    response = sender(
        "get", str(config.endpoint).rstrip("/") + "/versions",
        headers=_auth_headers(config), timeout_sec=30,
    )
    response.raise_for_status()
    return check_ocpi_response(_response_json(response, context="OCPI versions"), context="OCPI versions")


def fetch_version_detail(
    config: PartnerConfig, version_url: str, *, send: Optional[Callable] = None
) -> dict[str, Any]:
    """GETs one OCPI version detail document."""
    sender = _sender(send)
    response = sender(
        "get", version_url, headers=_auth_headers(config), timeout_sec=30,
    )
    response.raise_for_status()
    data = check_ocpi_response(_response_json(response, context="OCPI version detail"), context="OCPI version detail")
    if not isinstance(data, dict):
        raise OcpiClientError("OCPI version detail payload is not an object")
    return data


def pull_locations(
    config: PartnerConfig,
    locations_url: str,
    *,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_records: int = 5000,
    send: Optional[Callable] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pulls OCPI Location objects with offset/limit pagination.

    Follows RFC5988 `rel="next"` links; stops at max_records, empty pages, or
    a repeated/absolute URL (loop guard). Returns (locations, pull_metadata).
    """
    sender = _sender(send)
    headers = _auth_headers(config)
    params: dict[str, Any] = {"offset": 0, "limit": min(page_size, 1000)}
    if date_from is not None:
        params["date_from"] = date_from.astimezone(timezone.utc).isoformat()
    if date_to is not None:
        params["date_to"] = date_to.astimezone(timezone.utc).isoformat()

    locations: list[dict[str, Any]] = []
    pages = 0
    seen_urls: set[str] = set()
    next_url: Optional[str] = None
    total_count: Optional[int] = None

    while len(locations) < max_records:
        pages += 1
        if pages > 1000:  # loop guard: never page forever
            logger.warning("OCPI pull stopped after 1000 pages (loop guard)")
            break
        if next_url is None:
            request_url = locations_url
            request_params: Any = dict(params)
        else:
            if next_url in seen_urls:
                logger.warning("OCPI pull stopped: repeated next URL (loop guard)")
                break
            seen_urls.add(next_url)
            request_url, request_params = next_url, None
        response = sender(
            "get", request_url,
            params=request_params, headers=headers, timeout_sec=30,
        )
        response.raise_for_status()
        page = check_ocpi_response(_response_json(response, context="OCPI locations"), context="OCPI locations")
        if not isinstance(page, list):
            raise OcpiClientError("OCPI locations payload is not a list")
        if not page:
            break
        locations.extend(page)
        try:
            total_count = int(response.headers.get("X-Total-Count"))  # type: ignore
        except (TypeError, ValueError, AttributeError):
            pass
        links = parse_link_header(
            (response.headers.get("Link") if hasattr(response.headers, "get") else None)
        )
        next_url = links.get("next")
        if next_url is None:
            # Offset fallback when the partner sends no Link header.
            params["offset"] = params.get("offset", 0) + len(page)
            if len(page) < params.get("limit", page_size):
                break
            next_url = None  # stay on the base URL with advanced offset
            # Re-loop with the same URL would trip the seen-guard, so reset:
            seen_urls.clear()

    return locations[:max_records], {
        "pages_fetched": pages,
        "records_returned": len(locations[:max_records]),
        "total_count_header": total_count,
    }


# ---------------------------------------------------------------------------
# Mapping: OCPI vocabulary → canonical contracts
# ---------------------------------------------------------------------------

# OCPI 2.2.1 ConnectorType → canonical StandardConnectorType value.
OCPI_CONNECTOR_MAP: dict[str, str] = {
    "chademo": StandardConnectorType.CHADEMO.value,
    "iec_62196_t1": StandardConnectorType.TYPE_1.value,
    "iec_62196_t1_combo": StandardConnectorType.CCS1.value,
    "iec_62196_t2": StandardConnectorType.TYPE_2.value,
    "iec_62196_t2_combo": StandardConnectorType.CCS2.value,
    "tesla_r": StandardConnectorType.OTHER.value,
    "tesla_s": StandardConnectorType.OTHER.value,
    "domestic_a": StandardConnectorType.OTHER.value,
    "domestic_b": StandardConnectorType.OTHER.value,
    "domestic_c": StandardConnectorType.OTHER.value,
    "domestic_d": StandardConnectorType.OTHER.value,
    "domestic_e": StandardConnectorType.OTHER.value,
    "domestic_f": StandardConnectorType.OTHER.value,
    "domestic_g": StandardConnectorType.OTHER.value,
    "domestic_h": StandardConnectorType.OTHER.value,
    "domestic_i": StandardConnectorType.OTHER.value,
    "domestic_j": StandardConnectorType.OTHER.value,
    "domestic_k": StandardConnectorType.OTHER.value,
    "domestic_l": StandardConnectorType.OTHER.value,
    "iec_60309_2_single_16": StandardConnectorType.OTHER.value,
    "iec_60309_2_three_16": StandardConnectorType.OTHER.value,
    "iec_60309_2_three_32": StandardConnectorType.OTHER.value,
    "iec_60309_2_three_64": StandardConnectorType.OTHER.value,
    "gbt": StandardConnectorType.GB_T.value,
}

# OCPI 2.2.1 Status → (AvailabilityStatus, all-evses-down OperationalStatus).
# Station-level availability is aggregated in map_location_observation().
OCPI_STATUS_MAP: dict[str, AvailabilityStatus] = {
    "AVAILABLE": AvailabilityStatus.AVAILABLE,
    "CHARGING": AvailabilityStatus.BUSY,
    "RESERVED": AvailabilityStatus.BUSY,
    "BLOCKED": AvailabilityStatus.BROKEN,
    "INOPERATIVE": AvailabilityStatus.BROKEN,
    "OUTOFORDER": AvailabilityStatus.BROKEN,
    "PLANNED": AvailabilityStatus.UNKNOWN,
    "REMOVED": AvailabilityStatus.UNKNOWN,
    "UNKNOWN": AvailabilityStatus.UNKNOWN,
}


def parse_ocpi_datetime(raw: Any) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def map_connector_standard(raw: Any) -> str:
    if not raw or not isinstance(raw, str):
        return StandardConnectorType.OTHER.value
    return OCPI_CONNECTOR_MAP.get(raw.strip().lower(), StandardConnectorType.OTHER.value)


def map_tariff(
    tariff: Optional[dict[str, Any]],
) -> tuple[PricingType, Optional[float], Optional[str]]:
    """Maps an OCPI Tariff object to (pricing_type, price_per_kwh, currency).

    Only an unambiguous single ENERGY element with a flat price is treated as
    a per-kWh price. Anything else (time/flat/parking composites, multi-
    element structures) stays UNKNOWN — a missing price is never free and a
    complex tariff is never reduced to a guessed number.
    """
    if not tariff or not isinstance(tariff, dict):
        return PricingType.UNKNOWN, None, None
    currency = tariff.get("currency")
    elements = tariff.get("elements")
    if not isinstance(elements, list) or len(elements) != 1:
        return PricingType.UNKNOWN, None, None
    components = (elements[0] or {}).get("price_components")
    if not isinstance(components, list) or len(components) != 1:
        return PricingType.UNKNOWN, None, None
    comp = components[0] or {}
    if str(comp.get("type")).upper() != "ENERGY":
        return PricingType.UNKNOWN, None, None
    try:
        price = float(comp.get("price"))
    except (TypeError, ValueError):
        return PricingType.UNKNOWN, None, None
    if price < 0:
        return PricingType.UNKNOWN, None, None
    if price == 0:
        return PricingType.FREE, 0.0, currency if isinstance(currency, str) else None
    return PricingType.PAID, price, currency if isinstance(currency, str) else None


def map_location_observation(
    location: dict[str, Any],
    *,
    source_id: str,
    source_station_id: str,
    retrieved_at: datetime,
) -> Optional[NormalizedObservationRecord]:
    """Aggregates EVSE statuses into one station-level live observation.

    Aggregation rule (documented, deterministic): any CHARGING/RESERVED EVSE
    → busy; else any AVAILABLE → available; else all INOPERATIVE/OUTOFORDER/
    BLOCKED → broken; else unknown. observed_at = newest EVSE last_updated
    (falls back to location last_updated; None when nothing is timestamped).
    """
    evses = location.get("evses")
    if not isinstance(evses, list) or not evses:
        return None  # static inventory record without live status: no observation

    avail: list[AvailabilityStatus] = []
    available_count = 0
    newest: Optional[datetime] = None
    for evse in evses:
        if not isinstance(evse, dict):
            continue
        status = map_connector_status(evse.get("status"))
        avail.append(status)
        if status == AvailabilityStatus.AVAILABLE:
            available_count += 1
        ts = parse_ocpi_datetime(evse.get("last_updated"))
        if ts is not None and (newest is None or ts > newest):
            newest = ts

    if AvailabilityStatus.BUSY in avail:
        station_status = AvailabilityStatus.BUSY
    elif AvailabilityStatus.AVAILABLE in avail:
        station_status = AvailabilityStatus.AVAILABLE
    elif avail and all(s == AvailabilityStatus.BROKEN for s in avail):
        station_status = AvailabilityStatus.BROKEN
    else:
        station_status = AvailabilityStatus.UNKNOWN

    observed_at = newest or parse_ocpi_datetime(location.get("last_updated"))
    if observed_at is None:
        return None  # live statuses without any timestamp are not observations
    return NormalizedObservationRecord(
        source_id=source_id,
        source_station_id=source_station_id,
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        availability_status=station_status,
        queue_level=QueueLevel.UNKNOWN,
        available_connectors=available_count,
        total_connectors=len([e for e in evses if isinstance(e, dict)]),
        raw_status_label=",".join(sorted({str(e.get("status")) for e in evses if isinstance(e, dict)}))[:200],
        confidence_score=0.8,  # partner-reported telemetry, one hop
    )


def map_connector_status(raw: Any) -> AvailabilityStatus:
    if not raw or not isinstance(raw, str):
        return AvailabilityStatus.UNKNOWN
    return OCPI_STATUS_MAP.get(raw.strip().upper(), AvailabilityStatus.UNKNOWN)


class OcpiLocationsAdapter(BaseSourceAdapter):
    """Source adapter mapping OCPI 2.2.1 Location objects to canonical records.

    One adapter instance serves one partner+environment (source_id embeds
    both, so sandbox and production provenance never mix). expected_party
    (country_code, party_id) enforces partner isolation: records outside the
    configured scope fail at record level with an explicit error.
    """

    def __init__(
        self,
        partner_name: str,
        environment: str = "sandbox",
        expected_country_code: Optional[str] = None,
        expected_party_id: Optional[str] = None,
    ) -> None:
        self._partner_name = partner_name
        self._environment = environment
        self._expected_country = (
            expected_country_code.upper() if expected_country_code else None
        )
        self._expected_party = (
            expected_party_id.upper() if expected_party_id else None
        )

    @property
    def source_id(self) -> str:
        return f"ocpi:{self._partner_name}:{self._environment}"

    @property
    def source_priority(self) -> int:
        # Bilateral partner data outranks crowdsourced inventory when both are
        # present; conflicts without a justified policy still trigger REVIEW
        # in the dedup engine (no silent precedence).
        return 80

    def extract_source_station_id(self, payload: dict[str, Any]) -> str:
        country = payload.get("country_code")
        party = payload.get("party_id")
        loc_id = payload.get("id")
        if not country or not party or not loc_id:
            raise ValueError(
                "OCPI location missing country_code/party_id/id: "
                f"{sorted(payload.keys())}"
            )
        self._enforce_party_scope(str(country), str(party))
        return f"{country}/{party}/{loc_id}"

    def _enforce_party_scope(self, country: str, party: str) -> None:
        if self._expected_country and country.upper() != self._expected_country:
            raise ValueError(
                f"Partner isolation: location country {country!r} outside "
                f"configured scope {self._expected_country!r}"
            )
        if self._expected_party and party.upper() != self._expected_party:
            raise ValueError(
                f"Partner isolation: location party {party!r} outside "
                f"configured scope {self._expected_party!r}"
            )

    def normalize_station(self, raw: RawSourceRecord) -> NormalizedStationRecord:
        payload = raw.raw_payload
        station_id = raw.source_station_id
        parts = station_id.split("/")
        country_code, party_id = (parts + [None, None])[:2]

        coords = payload.get("coordinates") or {}
        try:
            latitude = float(coords.get("latitude")) if coords.get("latitude") is not None else None
            longitude = float(coords.get("longitude")) if coords.get("longitude") is not None else None
        except (TypeError, ValueError):
            latitude, longitude = None, None
        if latitude is None or longitude is None:
            raise ValueError(f"OCPI location {station_id} missing valid coordinates")

        if payload.get("publish") is False:
            raise ValueError(
                f"OCPI location {station_id} is marked publish=false: "
                "partner does not release it for public use; skipped, not ingested"
            )

        name = (payload.get("name") or "").strip() or f"OCPI Station {station_id}"
        address = payload.get("address") or ""
        raw_city = payload.get("city")
        city = raw_city.strip() if isinstance(raw_city, str) and raw_city.strip() else "Mumbai"
        city_inferred = not (isinstance(raw_city, str) and raw_city.strip())
        # OCPI Location has no state/province field: keep the contract default
        # and flag it inferred (same convention as the OCM adapter).
        state, state_inferred = "Maharashtra", True
        postal = payload.get("postal_code")
        country = payload.get("country") or "India"

        operator = payload.get("operator") or {}
        operator_name = operator.get("name") if isinstance(operator, dict) else None
        owner = payload.get("owner") or {}
        if not operator_name and isinstance(owner, dict):
            operator_name = owner.get("name")

        opening = payload.get("opening_times") or {}
        is_24 = opening.get("twentyfourseven") if isinstance(opening, dict) else None

        connectors = self._extract_connectors(payload.get("evses"))

        last_updated = parse_ocpi_datetime(payload.get("last_updated"))

        return NormalizedStationRecord(
            source_id=self.source_id,
            source_station_id=station_id,
            source_url=None,
            raw_payload_hash=raw.payload_hash,
            name=name,
            raw_name=payload.get("name"),
            operator_name=operator_name,
            operator_slug=(
                _slugify(operator_name) if operator_name else None
            ),
            latitude=latitude,
            longitude=longitude,
            address_line=address or None,
            locality=None,
            city=city,
            state=state,
            postal_code=postal,
            country=country,
            is_24_hours=bool(is_24) if is_24 is not None else None,
            opening_time=None,
            closing_time=None,
            access_type="Public",
            is_public=True,
            operational_status=self._station_operational_status(payload),
            phone=None,
            website_url=None,
            connectors=connectors,
            observation=map_location_observation(
                payload, source_id=self.source_id,
                source_station_id=station_id,
                retrieved_at=raw.retrieval_timestamp,
            ),
            extra_metadata={
                "ocpi_country_code": country_code,
                "ocpi_party_id": party_id,
                "ocpi_location_id": payload.get("id"),
                "ocpi_last_updated": payload.get("last_updated"),
                "ocpi_publish": payload.get("publish"),
                "ocpi_timezone": payload.get("time_zone"),
                "ocpi_parking": payload.get("parking_type"),
                "city_inferred": city_inferred,
                "state_inferred": state_inferred,
                "partner_name": self._partner_name,
            },
        )

    def _extract_connectors(self, evses: Any) -> list[NormalizedConnectorRecord]:
        connectors: list[NormalizedConnectorRecord] = []
        if not isinstance(evses, list):
            return connectors
        for evse in evses:
            if not isinstance(evse, dict):
                continue
            evse_uid = evse.get("evse_id") or evse.get("uid")
            evse_status = map_connector_status(evse.get("status"))
            ocpi_connectors = evse.get("connectors")
            if not isinstance(ocpi_connectors, list) or not ocpi_connectors:
                connectors.append(NormalizedConnectorRecord(
                    source_connector_id=str(evse_uid) if evse_uid else None,
                    connector_type=StandardConnectorType.OTHER.value,
                    raw_connector_type="unknown",
                    power_kw=None, voltage_v=None, amperage_a=None,
                    quantity=1, is_aggregated=False,
                    pricing_type=PricingType.UNKNOWN, price_per_kwh=None,
                    currency="INR", status=evse_status,
                ))
                continue
            for conn in ocpi_connectors:
                if not isinstance(conn, dict):
                    continue
                raw_standard = conn.get("standard")
                power = _positive_float(conn.get("max_electric_power"))
                voltage = _positive_float(conn.get("max_voltage"))
                amperage = _positive_float(conn.get("max_amperage"))
                conn_id = conn.get("id")
                connectors.append(NormalizedConnectorRecord(
                    source_connector_id=(
                        f"{evse_uid}/{conn_id}" if evse_uid and conn_id
                        else (str(evse_uid) if evse_uid else None)
                    ),
                    connector_type=map_connector_standard(raw_standard),
                    raw_connector_type=str(raw_standard) if raw_standard else "unknown",
                    power_kw=power, voltage_v=voltage, amperage_a=amperage,
                    quantity=1, is_aggregated=False,
                    pricing_type=PricingType.UNKNOWN, price_per_kwh=None,
                    currency="INR", status=evse_status,
                ))
        return connectors

    @staticmethod
    def _station_operational_status(payload: dict[str, Any]) -> OperationalStatus:
        evses = payload.get("evses")
        if isinstance(evses, list) and evses:
            statuses = {
                str(e.get("status", "")).upper()
                for e in evses if isinstance(e, dict)
            }
            if statuses and statuses <= {"INOPERATIVE", "OUTOFORDER", "BLOCKED"}:
                return OperationalStatus.TEMPORARILY_UNAVAILABLE
            if statuses == {"REMOVED"}:
                return OperationalStatus.PERMANENTLY_CLOSED
        return OperationalStatus.OPERATIONAL


def _positive_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _slugify(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-") or "operator"
