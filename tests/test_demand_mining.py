"""
tests/test_demand_mining.py
Unit tests for demand_mining.py offline evaluation, leakage mitigation, and report integrity.
"""

import json
import os
import pytest
from backend.ml.demand_mining import load_datasets, run_data_mining
from backend.ml.gates import DEFAULT_GATE_CONFIG, evaluate_gate, DataMaturityEvidence, DataMaturityState, MLUnavailableReason


def test_load_datasets_success():
    stations, observations = load_datasets("data")
    assert len(stations) >= 12
    assert len(observations) >= 8000


def test_load_datasets_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_datasets(str(tmp_path))


def test_load_datasets_empty_files(tmp_path):
    s_path = tmp_path / "canonical_stations.json"
    o_path = tmp_path / "observations.json"
    s_path.write_text("[]", encoding="utf-8")
    o_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_datasets(str(tmp_path))


def test_run_data_mining_end_to_end(tmp_path):
    out_dir = str(tmp_path / "ml_out")
    report = run_data_mining(data_dir="data", output_dir=out_dir)

    # Check report structure
    assert "metadata" in report
    assert report["metadata"]["is_synthetic_demonstration"] is True
    assert report["metadata"]["is_production_forecast"] is False
    assert report["metadata"]["production_gate_status"] == "COLD"

    # Check reproduced legacy metrics
    legacy = report["evaluations"]["legacy_random_split_reproduced"]["metrics"]
    assert legacy["r2_score"] == pytest.approx(0.4105, abs=0.005)
    assert legacy["rf_mae"] == pytest.approx(0.2565, abs=0.005)

    # Check honest chronological metrics
    honest = report["evaluations"]["honest_chronological_split"]["metrics"]
    assert honest["r2_score"] == pytest.approx(0.3956, abs=0.01)
    assert honest["rf_mae"] == pytest.approx(0.2562, abs=0.01)

    # Check summary file
    summary_file = os.path.join(out_dir, "mining_summary.json")
    assert os.path.exists(summary_file)
    with open(summary_file, encoding="utf-8") as f:
        summary_json = json.load(f)
    assert "metrics" in summary_json
    assert summary_json["metrics"]["r2_score"] == 0.4105


def test_offline_synthetic_does_not_promote_production_gate():
    """Ensure that having 8,640 synthetic demo observations does not make production READY."""
    # Build evidence simulating synthetic demo records (0 real observations)
    evidence = DataMaturityEvidence(
        total_real_observations=0,  # Synthetic data does not count!
        stations_with_observations=0,
        observation_days_covered=0,
        notes=["Synthetic demonstration data only"]
    )
    result = evaluate_gate(evidence, DEFAULT_GATE_CONFIG)
    assert result.state == DataMaturityState.COLD
    assert result.passed is False
    assert len(result.failed_criteria) > 0
    assert "Gate COLD" in result.message
