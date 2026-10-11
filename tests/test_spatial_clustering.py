"""Tests for Phase 5 Spatial Clustering & Geographic Coverage Gap Mining."""

import math
import json
import pytest

from backend.ml.spatial_clustering import (
    haversine_distance_km,
    cluster_stations_dbscan,
    find_coverage_gaps,
)


def test_haversine_known_distances():
    # Mumbai CST (18.9401, 72.8354) to Gateway of India (18.9220, 72.8347) is approx 2.0 km
    dist = haversine_distance_km(18.9401, 72.8354, 18.9220, 72.8347)
    assert 1.9 < dist < 2.2

    # Zero distance
    assert haversine_distance_km(19.076, 72.877, 19.076, 72.877) == 0.0


def test_spatial_clustering_empty():
    res = cluster_stations_dbscan([])
    assert res.total_stations == 0
    assert res.cluster_count == 0
    assert len(res.clusters) == 0


def test_spatial_clustering_dense_and_isolated():
    # 3 stations close together in Bandra (within ~500m)
    # 1 station far away in Thane (25km away)
    stations = [
        {"id": "b1", "name": "Bandra 1", "latitude": 19.055, "longitude": 72.830},
        {"id": "b2", "name": "Bandra 2", "latitude": 19.057, "longitude": 72.832},
        {"id": "b3", "name": "Bandra 3", "latitude": 19.056, "longitude": 72.831},
        {"id": "t1", "name": "Thane Isolated", "latitude": 19.218, "longitude": 72.978},
    ]

    res = cluster_stations_dbscan(stations, eps_km=1.0, min_samples=2)

    assert res.total_stations == 4
    assert res.cluster_count == 1
    assert res.clustered_stations_count == 3
    assert res.noise_stations_count == 1
    assert "t1" in res.noise_station_ids

    cluster = res.clusters[0]
    assert cluster.station_count == 3
    assert set(cluster.station_ids) == {"b1", "b2", "b3"}
    assert 19.055 <= cluster.center_lat <= 19.057
    assert 72.830 <= cluster.center_lng <= 72.832
    assert cluster.radius_km < 1.0


def test_coverage_gap_detection():
    stations = [
        {"id": "s1", "name": "Station 1", "latitude": 19.055, "longitude": 72.830},
        {"id": "s2", "name": "Station 2", "latitude": 19.056, "longitude": 72.831},
        {"id": "s_isolated", "name": "Isolated Station", "latitude": 19.300, "longitude": 73.000},
    ]

    gaps = find_coverage_gaps(stations, isolation_threshold_km=5.0)
    assert len(gaps) == 1
    assert gaps[0].station_id == "s_isolated"
    assert gaps[0].nearest_distance_km > 20.0


def test_canonical_dataset_spatial_clustering():
    with open("data/canonical_stations.json") as f:
        stations = json.load(f)

    # In Greater Mumbai canonical stations, minimum pairwise distance is 3.06 km.
    # eps_km=5.0 correctly clusters urban corridors while identifying peripheral stations as noise.
    res = cluster_stations_dbscan(stations, eps_km=5.0, min_samples=2)
    assert res.total_stations == len(stations)
    assert res.cluster_count == 3
    assert res.clustered_stations_count == 9
    assert res.noise_stations_count == 3
    for c in res.clusters:
        assert c.station_count >= 2
