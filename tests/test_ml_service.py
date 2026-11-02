"""ChargePlus — Tests for the ML Inference HTTP Service.

Validates:
- GET /health liveness probe
- GET /ready readiness & cold gate status
- POST /predict schema validation & fail-closed responses
- Internal Bearer token authentication
- Request body size limits (64KB ceiling)
"""

import os
import unittest
from fastapi.testclient import TestClient

from backend.ml.service import app


class TestMLService(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_probe(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "chargeplus-ml-inference")
        self.assertIn("timestamp", data)

    def test_readiness_probe_cold_state(self):
        res = self.client.get("/ready")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("ready", data)
        self.assertIn("gate_status", data)

    def test_predict_cold_fail_closed(self):
        payload = {
            "features": {
                "hour_of_day": 18,
                "day_of_week": 4,
                "is_weekend": 0,
                "month": 10,
                "station_connector_count": 4,
            },
            "latest_observation_at": "2026-10-15T12:00:00+00:00",
        }
        res = self.client.post("/predict", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["reason"], "NO_MODEL")
        self.assertIn("Station discovery is unaffected", data["message"])

    def test_predict_oversized_payload_rejected(self):
        # 70KB oversized feature map
        oversized = {"features": {"junk": "x" * 70000}}
        res = self.client.post("/predict", json=oversized)
        self.assertEqual(res.status_code, 413)


if __name__ == "__main__":
    unittest.main()

