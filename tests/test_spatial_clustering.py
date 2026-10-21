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


def test_spatial_isolation_iqr_threshold_invariant():
    """Phase C regression guard: verify threshold k=1.5 on real stations.

    Explicitly verifies the 3 distinct spatial isolation concepts:
    1. DBSCAN noise / unclustered stations (density-based).
    2. Nearest-neighbor distance > 5.0 km (coverage gap indicator).
    3. Tukey IQR extreme isolation outliers with multiplier k=1.5 (statistical outlier).
    """
    from backend.ml.anomaly import iqr_anomalies
    from backend.ml.run_spatial_mining import load_real_stations

    stations = load_real_stations("artifacts/chargeplus-real-dataset/stations.csv")
    assert len(stations) == 541

    gaps = find_coverage_gaps(stations, isolation_threshold_km=5.0)
    assert len(gaps) == 254

    distances = [g.nearest_distance_km for g in gaps if g.nearest_distance_km is not None]
    assert len(distances) == 254

    # Threshold must be k=1.5 producing exactly 17 extreme isolation outliers
    anomalies_k15 = iqr_anomalies(distances, k=1.5)
    assert len(anomalies_k15) == 17, f"Expected 17 outliers for k=1.5, got {len(anomalies_k15)}"

    # If drifted to k=3.0, only 6 far outliers would be found
    anomalies_k30 = iqr_anomalies(distances, k=3.0)
    assert len(anomalies_k30) == 6, f"Expected 6 far-outliers for k=3.0, got {len(anomalies_k30)}"

    # Also verify against committed artifact data/ml/spatial_mining_summary.json
    with open("data/ml/spatial_mining_summary.json", encoding="utf-8") as f:
        artifact = json.load(f)

    summary = artifact["summary"]
    assert summary["total_stations"] == 541
    assert summary["noise_stations"] == 427  # DBSCAN noise
    assert summary["coverage_gap_count"] == 254  # 5km geographic isolation
    assert summary["isolated_stations_5km_count"] == 254
    assert summary["extreme_isolation_outliers"] == 17  # k=1.5 statistical outliers
    assert summary["coverage_gaps_sample_size"] == 25  # Sampled UI preview size

