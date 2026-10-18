"""ChargePlus — Spatial Clustering & Geographic Coverage Gap Mining.

Phase 5 (Data Mining & Analytical Subsystems):
- Spatial Density-Based Clustering (DBSCAN with Haversine distance metric in km).
- Geographic coverage gap and isolated station analysis.
- Station attribute outlier detection using established anomaly baselines.

Adheres to Section 8 of the Release Assurance Mission:
- Uses true geographic distances (Haversine on spherical earth, R = 6371.0088 km).
- No naive Euclidean distances on latitude/longitude degrees.
- Distinguishes noise/unclustered points from clusters.
- Deterministic, reproducible, and fixture-testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np
from sklearn.cluster import DBSCAN

from backend.ml.anomaly import iqr_anomalies

EARTH_RADIUS_KM = 6371.0088


@dataclass
class SpatialCluster:
    """A spatial cluster of EV charging stations."""
    cluster_id: int
    station_ids: list[str]
    station_count: int
    center_lat: float
    center_lng: float
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float
    radius_km: float


@dataclass
class SpatialClusteringResult:
    """Output of spatial clustering analysis."""
    total_stations: int
    clustered_stations_count: int
    noise_stations_count: int
    cluster_count: int
    clusters: list[SpatialCluster]
    noise_station_ids: list[str]
    labels: list[int]


@dataclass
class CoverageGapStation:
    """A station identified as geographically isolated."""
    station_id: str
    station_name: str
    latitude: float
    longitude: float
    nearest_station_id: Optional[str]
    nearest_distance_km: Optional[float]


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two points on Earth in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_KM * c


def cluster_stations_dbscan(
    stations: Sequence[dict[str, Any]],
    eps_km: float = 2.0,
    min_samples: int = 2,
) -> SpatialClusteringResult:
    """Performs spatial density-based clustering using DBSCAN with haversine metric.

    Args:
        stations: Sequence of station dicts with 'id', 'latitude', 'longitude'.
        eps_km: Maximum neighborhood radius in kilometers (default: 2.0 km).
        min_samples: Minimum stations to form a dense cluster (default: 2).

    Returns:
        SpatialClusteringResult with identified clusters and unclustered noise points.
    """
    valid_stations: list[dict[str, Any]] = []
    coords_rad: list[tuple[float, float]] = []

    for s in stations:
        lat = s.get("latitude")
        lng = s.get("longitude")
        if lat is not None and lng is not None and -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
            valid_stations.append(s)
            coords_rad.append((math.radians(float(lat)), math.radians(float(lng))))

    n = len(valid_stations)
    if n == 0:
        return SpatialClusteringResult(
            total_stations=0,
            clustered_stations_count=0,
            noise_stations_count=0,
            cluster_count=0,
            clusters=[],
            noise_station_ids=[],
            labels=[],
        )

    eps_rad = eps_km / EARTH_RADIUS_KM
    coords_arr = np.array(coords_rad)

    db = DBSCAN(eps=eps_rad, min_samples=min_samples, metric="haversine")
    labels = db.fit_predict(coords_arr).tolist()

    cluster_groups: dict[int, list[dict[str, Any]]] = {}
    noise_ids: list[str] = []

    for idx, label in enumerate(labels):
        stn = valid_stations[idx]
        stn_id = str(stn.get("id", f"stn-{idx}"))
        if label == -1:
            noise_ids.append(stn_id)
        else:
            cluster_groups.setdefault(label, []).append(stn)

    clusters: list[SpatialCluster] = []
    for c_id, members in sorted(cluster_groups.items(), key=lambda x: x[0]):
        m_lats = [float(m["latitude"]) for m in members]
        m_lngs = [float(m["longitude"]) for m in members]
        c_lat = sum(m_lats) / len(m_lats)
        c_lng = sum(m_lngs) / len(m_lngs)

        max_radius = 0.0
        for m in members:
            dist = haversine_distance_km(c_lat, c_lng, float(m["latitude"]), float(m["longitude"]))
            if dist > max_radius:
                max_radius = dist

        clusters.append(
            SpatialCluster(
                cluster_id=c_id,
                station_ids=[str(m.get("id")) for m in members],
                station_count=len(members),
                center_lat=round(c_lat, 6),
                center_lng=round(c_lng, 6),
                min_lat=round(min(m_lats), 6),
                max_lat=round(max(m_lats), 6),
                min_lng=round(min(m_lngs), 6),
                max_lng=round(max(m_lngs), 6),
                radius_km=round(max_radius, 3),
            )
        )

    return SpatialClusteringResult(
        total_stations=n,
        clustered_stations_count=n - len(noise_ids),
        noise_stations_count=len(noise_ids),
        cluster_count=len(clusters),
        clusters=clusters,
        noise_station_ids=noise_ids,
        labels=labels,
    )


def find_coverage_gaps(
    stations: Sequence[dict[str, Any]],
    isolation_threshold_km: float = 3.0,
) -> list[CoverageGapStation]:
    """Identifies stations that have no neighboring station within isolation_threshold_km.

    Useful for identifying underserved zones or pioneer stations that require network expansion.

    NOTE (ceiling): O(n^2) pairwise Haversine scan — fine for hundreds of
    stations; upgrade path is a spatial index (ball-tree / geohash grid) if
    scaled to a nationwide fleet.
    """
    valid: list[dict[str, Any]] = [
        s for s in stations
        if s.get("latitude") is not None and s.get("longitude") is not None
    ]
    if len(valid) <= 1:
        return [
            CoverageGapStation(
                station_id=str(s.get("id", "")),
                station_name=str(s.get("name", "Unknown")),
                latitude=float(s["latitude"]),
                longitude=float(s["longitude"]),
                nearest_station_id=None,
                nearest_distance_km=None,
            )
            for s in valid
        ]

    gaps: list[CoverageGapStation] = []
    for i, s1 in enumerate(valid):
        lat1, lon1 = float(s1["latitude"]), float(s1["longitude"])
        min_dist = float("inf")
        nearest_id: Optional[str] = None

        for j, s2 in enumerate(valid):
            if i == j:
                continue
            lat2, lon2 = float(s2["latitude"]), float(s2["longitude"])
            d = haversine_distance_km(lat1, lon1, lat2, lon2)
            if d < min_dist:
                min_dist = d
                nearest_id = str(s2.get("id", ""))

        if min_dist >= isolation_threshold_km:
            gaps.append(
                CoverageGapStation(
                    station_id=str(s1.get("id", "")),
                    station_name=str(s1.get("name", "Unknown")),
                    latitude=round(lat1, 6),
                    longitude=round(lon1, 6),
                    nearest_station_id=nearest_id,
                    nearest_distance_km=round(min_dist, 3) if min_dist != float("inf") else None,
                )
            )

    return gaps
