"""ChargePlus — Explainable station recommendations (Phase 5/6, Step 5.8).

Scores use ONLY real static evidence plus explicitly-available dynamic
signals. Unknown never penalizes: missing attributes contribute 0 with an
honest explanation entry. Prediction-dependent signals (availability
forecasts, reliability scores) are UNAVAILABLE until validated models
exist — they contribute nothing and say so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

EARTH_KM = 6371.0


def haversine_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> Optional[float]:
    for v in (a_lat, a_lng, b_lat, b_lng):
        if not isinstance(v, (int, float)) or math.isnan(v):
            return None
    d_lat = math.radians(b_lat - a_lat)
    d_lng = math.radians(b_lng - a_lng)
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(d_lng / 2) ** 2)
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


@dataclass
class ScoredStation:
    station_id: str
    score: float
    reasons: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    unavailable_signals: list[str] = field(default_factory=list)


def score_stations(stations: list[dict[str, Any]],
                   user: dict[str, Any]) -> list[ScoredStation]:
    """Transparent additive scoring. Higher is better; ties keep input order.

    stations: [{"id","latitude","longitude","connector_types":[...],
                "max_power_kw" or None, "operator_name"...}].
    user: {"latitude","longitude","connector_type" or None,
           "fast_only": bool, "max_distance_km" or None}.
    """
    u_lat, u_lng = user.get("latitude"), user.get("longitude")
    want_conn = user.get("connector_type")
    out: list[ScoredStation] = []
    for s in stations:
        reasons, unknowns, unavailable = [], [], ["availability forecast: NO_MODEL",
                                                  "reliability score: NO_MODEL"]
        score = 0.0
        dist = (haversine_km(u_lat, u_lng, s.get("latitude"), s.get("longitude"))
                if isinstance(u_lat, (int, float)) and isinstance(u_lng, (int, float)) else None)
        max_d = user.get("max_distance_km")
        if dist is None:
            unknowns.append("distance unknown (missing coordinates)")
        else:
            if max_d is not None and dist > max_d:
                continue  # outside requested radius: excluded, not down-ranked
            score += max(0.0, 10.0 - dist)  # nearer is better, 10km saturates
            reasons.append(f"{dist:.1f} km away")
        types = s.get("connector_types") or []
        if want_conn:
            if want_conn in types:
                score += 5.0
                reasons.append(f"compatible connector ({want_conn})")
            elif not types:
                unknowns.append("connector compatibility unknown")
            else:
                score -= 5.0
                reasons.append(f"no {want_conn} connector reported")
        pkw = s.get("max_power_kw")
        if pkw is None:
            unknowns.append("charging speed unknown")
        else:
            if user.get("fast_only") and pkw < 50:
                score -= 3.0
                reasons.append(f"below fast-charging threshold ({pkw} kW)")
            elif pkw >= 50:
                score += 3.0
                reasons.append(f"fast charging ({pkw} kW)")
        out.append(ScoredStation(station_id=str(s.get("id")), score=score,
                                reasons=reasons, unknowns=unknowns,
                                unavailable_signals=unavailable))
    out.sort(key=lambda r: r.score, reverse=True)
    return out
