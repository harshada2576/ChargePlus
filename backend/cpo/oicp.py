"""ChargePlus — OICP 2.3 eRoaming Integration (PullEVSEData subset).

Implements the ingestion-relevant subset of Hubject OICP 2.3 (eRoaming):
pulling EVSE inventory + status records and mapping them to canonical
station records. OICP and OCPI are NOT interchangeable: OICP is Hubject's
roaming-hub SOAP interface, OCPI is the peer-to-peer REST interface.

Scope (pinned; anything else needs a partner contract):
  - eRoamingPullEVSEData request envelope builder (provider + optional
    incremental timestamp).
  - eRoamingPullEVSEData response parser (EvseDataRecord list).
  - Status/operator/location mapping to canonical contracts.
  - Transport: HTTPS POST with the configured partner credential header.
    Partner-specific TLS/client-certificate requirements are onboarding
    items (docs/cpo_partners.md), not code assumptions.

Out of scope: roaming authorization (AuthorizeStart/Stop), session/CDR
data (eRoamingGetChargeDetailRecords), OTP/payment, push (eRoamingPush…
services). Sessions, CDRs, and personal/transaction data are never pulled
or stored by this adapter.

Records flow through BaseSourceAdapter → canonical validation, so malformed
EVSE records are isolated per record, never batch-fatal.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
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

from backend.cpo.partners import PartnerConfig

logger = logging.getLogger("chargeplus.cpo.oicp")

# eRoaming namespace used for OICP 2.3 envelopes handled here. Pinned so both
# builder and parser agree; a partner on a different OICP version needs an
# explicit contract review, not silent parsing.
EROAMING_NS = "http://www.hubject.com/b2b/services/v2.3/"
SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"

# eRoaming EvseStatus → AvailabilityStatus.
OICP_STATUS_MAP: dict[str, AvailabilityStatus] = {
    "Available": AvailabilityStatus.AVAILABLE,
    "Reserved": AvailabilityStatus.BUSY,
    "Occupied": AvailabilityStatus.BUSY,
    "OutOfService": AvailabilityStatus.BROKEN,
    "Unknown": AvailabilityStatus.UNKNOWN,
}

_default_send = request_with_retry


def _sender(send: Optional[Callable] = None) -> Callable:
    return send if send is not None else _default_send


def _qname(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def parse_oicp_datetime(raw: Any) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def map_evse_status(raw: Any) -> AvailabilityStatus:
    if not raw or not isinstance(raw, str):
        return AvailabilityStatus.UNKNOWN
    return OICP_STATUS_MAP.get(raw.strip(), AvailabilityStatus.UNKNOWN)


def build_pull_evse_data_envelope(
    provider_id: str, *, last_update: Optional[datetime] = None
) -> str:
    """Builds a minimal eRoamingPullEVSEData SOAP request envelope."""
    if not provider_id or not provider_id.strip():
        raise ValueError("provider_id is required for eRoamingPullEVSEData")
    envelope = ET.Element(_qname(SOAP_ENV_NS, "Envelope"))
    body = ET.SubElement(envelope, _qname(SOAP_ENV_NS, "Body"))
    request = ET.SubElement(body, _qname(EROAMING_NS, "eRoamingPullEVSEData"))
    ET.SubElement(request, _qname(EROAMING_NS, "ProviderID")).text = provider_id.strip()
    if last_update is not None:
        ET.SubElement(request, _qname(EROAMING_NS, "LastUpdate")).text = (
            last_update.astimezone(timezone.utc).isoformat()
        )
    return ET.tostring(envelope, encoding="unicode")


def _text(parent: ET.Element, local: str) -> Optional[str]:
    child = parent.find(_qname(EROAMING_NS, local))
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def parse_pull_evse_data_response(xml_text: str) -> list[dict[str, Any]]:
    """Parses an eRoamingPullEVSEData SOAP response into EVSE dicts.

    Returns one dict per EvseDataRecord with keys: evse_id, operator_id,
    operator_name, status, last_update, street, house_num, zip, city,
    country, latitude, longitude, power_kw (None when not supplied).
    Raises ValueError on malformed XML or SOAP Fault.
    """
    if not xml_text or not xml_text.strip():
        raise ValueError("Empty eRoaming response")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Malformed eRoaming XML response: {exc}") from exc

    fault = root.find(f".//{_qname(SOAP_ENV_NS, 'Fault')}")
    if fault is not None:
        detail = fault.findtext(".//faultstring") or "unspecified SOAP fault"
        raise RuntimeError(f"eRoaming SOAP fault: {detail}")

    records: list[dict[str, Any]] = []
    for rec in root.findall(f".//{_qname(EROAMING_NS, 'EvseDataRecord')}"):
        address = rec.find(_qname(EROAMING_NS, "Address"))
        geo = rec.find(_qname(EROAMING_NS, "GeoCoordinates"))
        lat = lon = None
        if geo is not None:
            deg = geo.find(_qname(EROAMING_NS, "DecimalDegree"))
            if deg is not None:
                lat = _text(deg, "Latitude")
                lon = _text(deg, "Longitude")
        power: Optional[float] = None
        facilities = rec.find(_qname(EROAMING_NS, "ChargingFacilities"))
        if facilities is not None:
            for facility in facilities.findall(_qname(EROAMING_NS, "ChargingFacility")):
                raw_power = _text(facility, "Power")
                try:
                    candidate = float(raw_power) if raw_power else None
                except (TypeError, ValueError):
                    candidate = None
                if candidate is not None and candidate > 0:
                    power = candidate if power is None else max(power, candidate)
        records.append({
            "evse_id": _text(rec, "EvseID"),
            "operator_id": _text(rec, "OperatorID"),
            "operator_name": _text(rec, "OperatorName"),
            "status": _text(rec, "Status"),
            "last_update": _text(rec, "LastUpdate"),
            "street": _text(address, "Street") if address is not None else None,
            "house_num": _text(address, "HouseNum") if address is not None else None,
            "zip": _text(address, "Zip") if address is not None else None,
            "city": _text(address, "City") if address is not None else None,
            "country": _text(address, "Country") if address is not None else None,
            "latitude": lat,
            "longitude": lon,
            "power_kw": power,
        })
    return records


def pull_evse_data(
    config: PartnerConfig,
    provider_id: str,
    *,
    last_update: Optional[datetime] = None,
    timeout_sec: int = 30,
    send: Optional[Callable] = None,
) -> list[dict[str, Any]]:
    """POSTs eRoamingPullEVSEData and returns parsed EVSE dicts."""
    config.require_usable()
    sender = _sender(send)
    envelope = build_pull_evse_data_envelope(provider_id, last_update=last_update)
    response = sender(
        "post",
        str(config.endpoint),
        data=envelope.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "Authorization": f"Bearer {config.token}",
            "SOAPAction": "eRoamingPullEVSEData",
        },
        timeout_sec=timeout_sec,
    )
    response.raise_for_status()
    try:
        text = response.text if isinstance(response.text, str) else response.json()
    except (ValueError, AttributeError):
        text = None
    if not isinstance(text, str):
        raise ValueError("eRoaming response is not XML text")
    records = parse_pull_evse_data_response(text)
    logger.info("OICP pull returned %d EVSE records for %s", len(records), config.source_id)
    return records


class OicpEvseAdapter(BaseSourceAdapter):
    """Source adapter mapping eRoaming EvseDataRecord dicts to canonical records.

    One adapter instance serves one partner+environment. expected_operator_id
    enforces partner isolation: records from other operators fail at record
    level with an explicit error.
    """

    def __init__(
        self,
        partner_name: str,
        environment: str = "sandbox",
        expected_operator_id: Optional[str] = None,
    ) -> None:
        self._partner_name = partner_name
        self._environment = environment
        self._expected_operator = (
            expected_operator_id.strip() if expected_operator_id else None
        )

    @property
    def source_id(self) -> str:
        return f"oicp:{self._partner_name}:{self._environment}"

    @property
    def source_priority(self) -> int:
        return 80

    def extract_source_station_id(self, payload: dict[str, Any]) -> str:
        evse_id = payload.get("evse_id")
        operator = payload.get("operator_id")
        if not evse_id:
            raise ValueError("eRoaming record missing EvseID")
        if self._expected_operator and operator != self._expected_operator:
            raise ValueError(
                f"Partner isolation: record operator {operator!r} outside "
                f"configured scope {self._expected_operator!r}"
            )
        return f"oicp/{operator or 'unknown'}/{evse_id}"

    def normalize_station(self, raw: RawSourceRecord) -> NormalizedStationRecord:
        payload = raw.raw_payload
        station_id = raw.source_station_id

        try:
            latitude = float(payload["latitude"]) if payload.get("latitude") is not None else None
            longitude = float(payload.get("longitude")) if payload.get("longitude") is not None else None
        except (TypeError, ValueError):
            latitude, longitude = None, None
        if latitude is None or longitude is None:
            raise ValueError(f"eRoaming record {station_id} missing valid coordinates")

        operator_name = payload.get("operator_name") or payload.get("operator_id")
        street = payload.get("street")
        house = payload.get("house_num")
        address_line = (
            f"{street} {house}".strip() if street or house else None
        )
        raw_city = payload.get("city")
        city = raw_city.strip() if isinstance(raw_city, str) and raw_city.strip() else "Mumbai"
        city_inferred = not (isinstance(raw_city, str) and raw_city.strip())
        # eRoaming Address carries no state/province: contract default + flag.
        state, state_inferred = "Maharashtra", True
        country = payload.get("country") or "India"

        power = payload.get("power_kw")
        try:
            power_kw = float(power) if power is not None else None
        except (TypeError, ValueError):
            power_kw = None
        if power_kw is not None and power_kw <= 0:
            power_kw = None

        status = map_evse_status(payload.get("status"))
        last_update = parse_oicp_datetime(payload.get("last_update"))

        observation: Optional[NormalizedObservationRecord] = None
        if last_update is not None:
            observation = NormalizedObservationRecord(
                source_id=self.source_id,
                source_station_id=station_id,
                observed_at=last_update,
                retrieved_at=raw.retrieval_timestamp,
                availability_status=status,
                queue_level=QueueLevel.UNKNOWN,
                available_connectors=1 if status == AvailabilityStatus.AVAILABLE else 0,
                total_connectors=1,
                raw_status_label=str(payload.get("status"))[:200] if payload.get("status") else None,
                confidence_score=0.8,
            )

        if status == AvailabilityStatus.BROKEN:
            operational = OperationalStatus.TEMPORARILY_UNAVAILABLE
        else:
            operational = OperationalStatus.OPERATIONAL

        return NormalizedStationRecord(
            source_id=self.source_id,
            source_station_id=station_id,
            source_url=None,
            raw_payload_hash=raw.payload_hash,
            name=f"{operator_name} {payload.get('evse_id')}" if operator_name else f"OICP Station {station_id}",
            raw_name=None,
            operator_name=operator_name,
            operator_slug=(
                _slugify(operator_name) if operator_name else None
            ),
            latitude=latitude,
            longitude=longitude,
            address_line=address_line,
            locality=None,
            city=city,
            state=state,
            postal_code=payload.get("zip"),
            country=country,
            is_24_hours=None,
            opening_time=None,
            closing_time=None,
            access_type="Public",
            is_public=True,
            operational_status=operational,
            phone=None,
            website_url=None,
            connectors=[
                NormalizedConnectorRecord(
                    source_connector_id=str(payload.get("evse_id")),
                    connector_type=StandardConnectorType.OTHER.value,
                    raw_connector_type="unknown",
                    power_kw=power_kw,
                    voltage_v=None,
                    amperage_a=None,
                    quantity=1,
                    is_aggregated=False,
                    pricing_type=PricingType.UNKNOWN,
                    price_per_kwh=None,
                    currency="INR",
                    status=status,
                )
            ],
            observation=observation,
            extra_metadata={
                "oicp_operator_id": payload.get("operator_id"),
                "oicp_evse_id": payload.get("evse_id"),
                "oicp_last_update": payload.get("last_update"),
                "city_inferred": city_inferred,
                "state_inferred": state_inferred,
                "partner_name": self._partner_name,
            },
        )


def _slugify(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-") or "operator"
