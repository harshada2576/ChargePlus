"""ChargePlus — Deterministic CPO Protocol Simulator (isolated, offline).

Builds scripted `requests.get/post` behaviors plus representative protocol
payloads so conformance tests exercise the REAL adapter/pull code (including
the shared retry transport) without any network. Simulator scenarios are
labelled simulated: they prove adapter logic, never a commercial connection.

Usage:
    send = make_scripted_send({"versions": [...], "locations:/cpo/": [...]})
    with patch("requests.get", side_effect=send):
        locations, meta = pull_locations(config, url)
"""

from __future__ import annotations

from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests as req


class SimResponse:
    """Minimal requests.Response double (status/headers/json/text)."""

    def __init__(
        self,
        status_code: int = 200,
        *,
        json_body: Any = None,
        text_body: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self._json_body = json_body
        self._text_body = text_body
        self.headers = headers or {}

    def json(self) -> Any:
        if self._json_body is None:
            raise ValueError("No JSON body")
        if isinstance(self._json_body, Exception):
            raise self._json_body
        return self._json_body

    @property
    def text(self) -> str:
        if self._text_body is not None:
            return self._text_body
        import json as _json

        return _json.dumps(self._json_body)

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            raise req.exceptions.HTTPError(
                f"Simulated HTTP {self.status_code}", response=self
            )


def ocpi_envelope(data: Any, code: int = 1000, message: str = "Success") -> dict:
    return {
        "data": data,
        "status_code": code,
        "status_message": message,
        "timestamp": "2026-10-11T12:00:00Z",
    }


def ocpi_versions_payload(versions: Optional[list[str]] = None) -> dict:
    versions = versions if versions is not None else ["2.2.1"]
    return ocpi_envelope([
        {"version": v, "url": f"https://cpo.example.com/ocpi/{v}/details"}
        for v in versions
    ])


def ocpi_version_detail(locations_url: str = "https://cpo.example.com/ocpi/2.2.1/locations") -> dict:
    return ocpi_envelope({
        "version": "2.2.1",
        "endpoints": [
            {"identifier": "locations", "role": "SENDER", "url": locations_url},
            {"identifier": "tariffs", "role": "SENDER", "url": "https://cpo.example.com/ocpi/2.2.1/tariffs"},
        ],
    })


def ocpi_location(
    loc_id: str = "LOC1",
    *,
    country: str = "IN",
    party: str = "TAT",
    status: str = "AVAILABLE",
    last_updated: str = "2026-10-11T10:00:00Z",
    publish: bool = True,
    connectors: Any = "default",
    name: str = "Sim Hub",
) -> dict:
    if connectors == "default":
        connectors = [
            {
                "id": "1", "standard": "IEC_62196_T2",
                "format": "SOCKET", "power_type": "AC_THREE_PHASE",
                "max_voltage": 400, "max_amperage": 32,
                "max_electric_power": 22, "tariff_ids": None,
                "last_updated": last_updated,
            }
        ]
    return {
        "country_code": country, "party_id": party, "id": loc_id,
        "publish": publish, "name": name,
        "address": "Linking Road", "city": "Mumbai", "postal_code": "400050",
        "country": "India", "coordinates": {"latitude": "19.076", "longitude": "72.877"},
        "time_zone": "Asia/Kolkata",
        "opening_times": {"twentyfourseven": True},
        "owner": {"name": "Sim Owner"},
        "operator": {"name": "Sim Operator"},
        "last_updated": last_updated,
        "evses": [
            {
                "uid": "EVSE1", "evse_id": f"{country}*{party}*E*0001",
                "status": status, "last_updated": last_updated,
                "connectors": connectors,
            }
        ],
    }


def ocpi_locations_page(
    locations: list[dict],
    *,
    link_next: Optional[str] = None,
    total: Optional[int] = None,
) -> SimResponse:
    headers: dict[str, str] = {}
    if link_next:
        headers["Link"] = f'<{link_next}>; rel="next"'
    if total is not None:
        headers["X-Total-Count"] = str(total)
        headers["X-Limit"] = "100"
    return SimResponse(200, json_body=ocpi_envelope(locations), headers=headers)


def oicp_record(
    evse_id: str = "IN*TAT*E*0001",
    *,
    operator: str = "TAT",
    status: str = "Available",
    last_update: str = "2026-10-11T10:00:00Z",
    lat: str = "19.076",
    lon: str = "72.877",
    power: Optional[str] = "22",
) -> dict:
    return {
        "evse_id": evse_id, "operator_id": operator, "operator_name": "Sim Operator",
        "status": status, "last_update": last_update,
        "street": "Linking Road", "house_num": "12", "zip": "400050",
        "city": "Mumbai", "country": "India",
        "latitude": lat, "longitude": lon, "power_kw": float(power) if power else None,
    }


def oicp_pull_response_xml(records: list[dict]) -> str:
    ns = "http://www.hubject.com/b2b/services/v2.3/"
    parts = [
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">',
        "<soap:Body>",
        f'<eRoamingPullEVSEDataResponse xmlns="{ns}">',
    ]
    for r in records:
        parts.append("<EvseDataRecord>")
        parts.append(f"<EvseID>{r['evse_id']}</EvseID>")
        parts.append(f"<OperatorID>{r['operator_id']}</OperatorID>")
        parts.append(f"<OperatorName>{r['operator_name']}</OperatorName>")
        parts.append(f"<Status>{r['status']}</Status>")
        parts.append(f"<LastUpdate>{r['last_update']}</LastUpdate>")
        parts.append("<Address>")
        for key, tag in (("street", "Street"), ("house_num", "HouseNum"),
                         ("zip", "Zip"), ("city", "City"), ("country", "Country")):
            if r.get(key):
                parts.append(f"<{tag}>{r[key]}</{tag}>")
        parts.append("</Address>")
        parts.append("<GeoCoordinates><DecimalDegree>")
        parts.append(f"<Latitude>{r['latitude']}</Latitude>")
        parts.append(f"<Longitude>{r['longitude']}</Longitude>")
        parts.append("</DecimalDegree></GeoCoordinates>")
        if r.get("power_kw"):
            parts.append(
                "<ChargingFacilities><ChargingFacility>"
                f"<Power>{r['power_kw']}</Power>"
                "</ChargingFacility></ChargingFacilities>"
            )
        parts.append("</EvseDataRecord>")
    parts.append("</eRoamingPullEVSEDataResponse></soap:Body></soap:Envelope>")
    return "".join(parts)


def make_scripted_send(
    routes: dict[str, list[Any]],
    *,
    expect_token: Optional[str] = None,
) -> Callable:
    """Builds a requests.get/post side_effect dispatching by URL substring.

    routes maps a URL substring to a queue of SimResponse | Exception. Each
    matching request pops the head (last entry repeats). Unmatched URLs get a
    simulated 404. When expect_token is set, requests with a different
    Authorization header get a simulated 401 (failed-authentication scenario).
    """

    def _send(url: str, *args: Any, **kwargs: Any) -> SimResponse:
        headers = kwargs.get("headers") or {}
        if expect_token is not None:
            auth = headers.get("Authorization", "")
            if auth != f"Token {expect_token}" and auth != f"Bearer {expect_token}":
                return SimResponse(401, json_body={"error": "unauthorized"})
        for substring, queue in routes.items():
            if substring in url:
                if len(queue) > 1:
                    return queue.pop(0)
                return queue[0]
        return SimResponse(404, json_body={"error": f"no simulated route for {urlparse(url).path}"})

    return _send
