"""OCM fetch_raw transport on shared retry (Agent 2).

Pins that OpenChargeMapAdapter.fetch_raw uses backend.ingestion.base
request_with_retry: transient 429/5xx are retried with backoff, auth
failures (401/403) fail fast as PermissionError, timeouts surface as
TimeoutError, and malformed payloads as ValueError. All transport mocked.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from backend.ingestion.adapters.openchargemap import OpenChargeMapAdapter


def _adapter():
    return OpenChargeMapAdapter()


def _ok(payload=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload if payload is not None else []
    return resp


def _status(status, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    return resp


class TestOcmFetchRawTransport:
    def test_01_recovers_after_transient_500(self):
        with patch(
            "requests.get",
            side_effect=[_status(500), _ok([{"ID": 1}])],
        ) as mock_get, patch("backend.ingestion.base._default_sleep"):
            records = _adapter().fetch_raw(api_key="DUMMY")
        assert records == [{"ID": 1}]
        assert mock_get.call_count == 2

    def test_02_429_exhaustion_mentions_rate_limit(self):
        with patch(
            "requests.get",
            return_value=_status(429, {"Retry-After": "1"}),
        ), patch("backend.ingestion.base._default_sleep"):
            with pytest.raises(RuntimeError, match="rate limit"):
                _adapter().fetch_raw(api_key="DUMMY", timeout_sec=5)

    def test_03_500_exhaustion_mentions_server_error(self):
        with patch(
            "requests.get", return_value=_status(503)
        ), patch("backend.ingestion.base._default_sleep"):
            with pytest.raises(RuntimeError, match="server error"):
                _adapter().fetch_raw(api_key="DUMMY", timeout_sec=5)

    def test_04_401_raises_permission_error_without_retry(self):
        with patch(
            "requests.get", return_value=_status(401)
        ) as mock_get, patch(
            "backend.ingestion.base._default_sleep"
        ) as mock_sleep:
            with pytest.raises(PermissionError, match="authentication failed"):
                _adapter().fetch_raw(api_key="DUMMY")
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    def test_05_timeout_retried_then_reraised(self):
        import requests as req

        with patch(
            "requests.get", side_effect=req.exceptions.Timeout("slow")
        ), patch("backend.ingestion.base._default_sleep"):
            with pytest.raises(TimeoutError):
                _adapter().fetch_raw(api_key="DUMMY", timeout_sec=5)

    def test_06_malformed_json_raises_value_error(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch("requests.get", return_value=resp):
            with pytest.raises(ValueError, match="Malformed JSON"):
                _adapter().fetch_raw(api_key="DUMMY")

    def test_07_non_list_payload_rejected(self):
        with patch("requests.get", return_value=_ok({"unexpected": "dict"})):
            with pytest.raises(ValueError, match="Expected list"):
                _adapter().fetch_raw(api_key="DUMMY")

    def test_08_missing_key_raises_without_network(self):
        with patch.dict(os.environ, {"OPENCHARGEMAP_API_KEY": ""}):
            with patch("requests.get") as mock_get:
                with pytest.raises(ValueError, match="API key required"):
                    _adapter().fetch_raw(api_key=None)
        mock_get.assert_not_called()
