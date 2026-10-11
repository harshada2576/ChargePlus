"""Tests for the shared upstream transport (backend/ingestion/base.py).

Covers request_with_retry (bounded retries, exponential backoff with jitter,
Retry-After support) and validate_endpoint_url (SSRF guard). All external
transport is mocked — no network calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests as req

from backend.ingestion import base as base_mod
from backend.ingestion.base import request_with_retry, validate_endpoint_url


def _ok_response(payload=None):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = payload or {}
    return mock_response


def _status_response(status, headers=None):
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.headers = headers or {}
    return mock_response


class TestRequestWithRetry:
    def test_01_success_first_try_no_sleep(self):
        with patch("requests.get", return_value=_ok_response()) as mock_get, \
             patch("backend.ingestion.base._default_sleep") as mock_sleep:
            resp = request_with_retry("get", "https://example.com/api")
        assert resp.status_code == 200
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    def test_02_recovers_after_transient_500(self):
        with patch(
            "requests.get",
            side_effect=[_status_response(500), _ok_response()],
        ) as mock_get, patch(
            "backend.ingestion.base._default_sleep"
        ) as mock_sleep:
            resp = request_with_retry("get", "https://example.com/api")
        assert resp.status_code == 200
        assert mock_get.call_count == 2
        assert mock_sleep.call_count == 1

    def test_03_exhaustion_raises_server_error(self):
        with patch(
            "requests.get", return_value=_status_response(503)
        ), patch("backend.ingestion.base._default_sleep"):
            with pytest.raises(RuntimeError, match="server error"):
                request_with_retry("get", "https://example.com/api", max_attempts=3)

    def test_04_429_exhaustion_mentions_rate_limit(self):
        with patch(
            "requests.get",
            return_value=_status_response(429, {"Retry-After": "1"}),
        ), patch("backend.ingestion.base._default_sleep"):
            with pytest.raises(RuntimeError, match="rate limit"):
                request_with_retry("get", "https://example.com/api", max_attempts=2)

    def test_05_retry_after_header_honored(self):
        sleeps: list[float] = []
        with patch(
            "requests.get",
            side_effect=[_status_response(429, {"Retry-After": "3"}), _ok_response()],
        ):
            request_with_retry(
                "get", "https://example.com/api", sleep_fn=sleeps.append
            )
        assert len(sleeps) == 1
        assert sleeps[0] >= 3.0  # server directive respected, not just base backoff

    def test_06_retry_after_capped_at_max_delay(self):
        sleeps: list[float] = []
        with patch(
            "requests.get",
            side_effect=[_status_response(429, {"Retry-After": "3600"}), _ok_response()],
        ):
            request_with_retry(
                "get", "https://example.com/api",
                max_delay_sec=5.0, sleep_fn=sleeps.append,
            )
        assert len(sleeps) == 1
        assert sleeps[0] <= 5.0

    def test_07_timeout_retried_then_reraised_as_timeout(self):
        with patch(
            "requests.get", side_effect=req.exceptions.Timeout("slow")
        ), patch("backend.ingestion.base._default_sleep"):
            with pytest.raises(TimeoutError):
                request_with_retry("get", "https://example.com/api", max_attempts=3)

    def test_08_connection_error_retried_then_reraised(self):
        with patch(
            "requests.get", side_effect=req.exceptions.ConnectionError("down")
        ), patch("backend.ingestion.base._default_sleep"):
            with pytest.raises(ConnectionError):
                request_with_retry("get", "https://example.com/api", max_attempts=2)

    def test_09_401_returned_without_retry(self):
        with patch(
            "requests.get", return_value=_status_response(401)
        ) as mock_get, patch(
            "backend.ingestion.base._default_sleep"
        ) as mock_sleep:
            resp = request_with_retry("get", "https://example.com/api")
        assert resp.status_code == 401
        assert mock_get.call_count == 1  # auth errors must not burn retries
        mock_sleep.assert_not_called()

    def test_10_post_method_supported(self):
        with patch("requests.post", return_value=_ok_response()) as mock_post:
            resp = request_with_retry("post", "https://example.com/api", data={"a": "b"})
        assert resp.status_code == 200
        assert mock_post.call_count == 1

    def test_11_invalid_method_rejected(self):
        with pytest.raises(ValueError, match="get.*post"):
            request_with_retry("put", "https://example.com/api")

    def test_12_invalid_max_attempts_rejected(self):
        with pytest.raises(ValueError, match="max_attempts"):
            request_with_retry("get", "https://example.com/api", max_attempts=0)

    def test_13_backoff_grows_with_attempts(self):
        sleeps: list[float] = []
        with patch("requests.get", return_value=_status_response(500)):
            with pytest.raises(RuntimeError, match="server error"):
                request_with_retry(
                    "get", "https://example.com/api",
                    max_attempts=3, base_delay_sec=1.0,
                    max_delay_sec=60.0, sleep_fn=sleeps.append,
                )
        assert len(sleeps) == 2
        # Exponential growth dominates jitter: second sleep exceeds first.
        assert sleeps[1] > sleeps[0]


class TestValidateEndpointUrl:
    def test_20_https_accepted(self):
        assert (
            validate_endpoint_url("https://overpass-api.de/api/interpreter")
            == "https://overpass-api.de/api/interpreter"
        )

    def test_21_non_http_scheme_rejected(self):
        with pytest.raises(ValueError, match="http"):
            validate_endpoint_url("file:///etc/passwd")

    def test_22_embedded_credentials_rejected(self):
        with pytest.raises(ValueError, match="credentials"):
            validate_endpoint_url("https://user:pass@example.com/api")

    def test_23_plain_http_rejected_for_remote_host(self):
        with pytest.raises(ValueError, match="https"):
            validate_endpoint_url("http://example.com/api")

    def test_24_plain_http_allowed_for_loopback(self):
        assert (
            validate_endpoint_url("http://localhost:8080/simulator")
            == "http://localhost:8080/simulator"
        )
        assert (
            validate_endpoint_url("http://127.0.0.1:8080/simulator")
            == "http://127.0.0.1:8080/simulator"
        )

    def test_25_empty_and_hostless_rejected(self):
        with pytest.raises(ValueError):
            validate_endpoint_url("")
        with pytest.raises(ValueError):
            validate_endpoint_url("https://")

    def test_26_retry_helper_validates_url_before_sending(self):
        with patch("requests.get") as mock_get:
            with pytest.raises(ValueError, match="http"):
                request_with_retry("get", "file:///etc/passwd")
        mock_get.assert_not_called()
