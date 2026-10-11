"""CPO partner lifecycle + sync tests (isolated simulator — no network).

Covers PartnerConfig lifecycle, PartnerSync dry-run flows for both protocols,
cursor resume, idempotency, failure accounting, log redaction, and the CLI.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.cpo.cli import main as cpo_main
from backend.cpo.ocpi import OcpiLocationsAdapter
from backend.cpo.partners import (
    PartnerConfig,
    PartnerCredentialError,
    PartnerStatus,
    activation_checklist,
)
from backend.cpo.simulator import (
    SimResponse,
    make_scripted_send,
    ocpi_location,
    ocpi_locations_page,
    ocpi_version_detail,
    ocpi_versions_payload,
    oicp_pull_response_xml,
    oicp_record,
)
from backend.cpo.sync import PartnerSync, SyncState
from backend.ingestion.persistence import IngestionPersistenceService
from backend.ingestion.runner import IngestionRunner

LOC_URL = "https://cpo.example.com/ocpi/2.2.1/locations"
HUB_URL = "https://hub.example.com/eRoamingPullEVSEData"
SECRET = "tok-secret-xyz-123"


def _ocpi_config(**overrides):
    base = {
        "partner_name": "simco", "protocol": "ocpi", "environment": "sandbox",
        "env_prefix": "OCPI_SIMCO_SANDBOX",
        "endpoint": "https://cpo.example.com/ocpi",
        "token": SECRET, "country_code": "IN", "party_id": "TAT",
    }
    base.update(overrides)
    return PartnerConfig(**base)


def _offline_sync():
    runner = IngestionRunner(persistence_service=IngestionPersistenceService(None))
    return PartnerSync(runner=runner)


def _ocpi_routes(locations, **kwargs):
    return {
        "versions": [SimResponse(200, json_body=ocpi_versions_payload())],
        "details": [SimResponse(200, json_body=ocpi_version_detail(LOC_URL))],
        LOC_URL: locations,
    }


class TestPartnerLifecycle:
    def test_01_missing_credentials_not_configured(self):
        config = PartnerConfig(
            partner_name="x", protocol="ocpi", environment="sandbox",
            env_prefix="OCPI_X_SANDBOX",
        )
        assert config.local_status() == PartnerStatus.NOT_CONFIGURED
        with pytest.raises(PartnerCredentialError, match="NOT_CONFIGURED"):
            config.require_usable()

    def test_02_configured_sandbox_ready(self):
        assert _ocpi_config().local_status() == PartnerStatus.SANDBOX_READY

    def test_03_production_prefix_separated(self):
        prod = _ocpi_config(environment="production", env_prefix="OCPI_SIMCO_PROD")
        assert prod.local_status() == PartnerStatus.PRODUCTION_READY
        assert prod.source_id == "ocpi:simco:production"

    def test_04_expired_credential_not_configured(self):
        expired = _ocpi_config(
            token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        assert expired.local_status() == PartnerStatus.NOT_CONFIGURED
        with pytest.raises(PartnerCredentialError, match="expired"):
            expired.require_usable()

    def test_05_malformed_expiry_rejected(self, monkeypatch):
        monkeypatch.setenv("OCPI_BAD_SANDBOX_ENDPOINT", "https://x")
        monkeypatch.setenv("OCPI_BAD_SANDBOX_TOKEN", "t")
        monkeypatch.setenv("OCPI_BAD_SANDBOX_TOKEN_EXPIRES_AT", "not-a-date")
        with pytest.raises(PartnerCredentialError, match="ISO-8601"):
            PartnerConfig.from_env("bad", "ocpi", "sandbox", "OCPI_BAD_SANDBOX")

    def test_06_summary_redacts_token(self, caplog):
        summary = _ocpi_config().safe_summary()
        assert summary["token"] == "<redacted>"
        with caplog.at_level(logging.INFO):
            logging.getLogger("test").info("summary: %s", summary)
        assert SECRET not in caplog.text

    def test_07_checklist_marks_protocol_scope_done(self):
        checklist = activation_checklist(_ocpi_config())
        assert checklist["local_status"] == "SANDBOX_READY"
        scope = next(s for s in checklist["steps"] if s["id"] == "protocol_scope")
        assert scope["locally_complete"] is True
        agreement = next(s for s in checklist["steps"] if s["id"] == "agreement")
        assert agreement["owner"] == "external/partner"

    def test_08_from_env_reads_prefix(self, monkeypatch):
        monkeypatch.setenv("OCPI_SIMCO_SANDBOX_ENDPOINT", "https://cpo.example.com/ocpi")
        monkeypatch.setenv("OCPI_SIMCO_SANDBOX_TOKEN", "t")
        config = PartnerConfig.from_env("simco", "ocpi", "sandbox", "OCPI_SIMCO_SANDBOX")
        assert config.endpoint == "https://cpo.example.com/ocpi"

    def test_09_unsupported_protocol_rejected(self):
        with pytest.raises(ValueError, match="Unsupported protocol"):
            PartnerConfig.from_env("x", "wat", "sandbox", "WAT_X_SANDBOX")


class TestOcpiSync:
    def test_20_dry_run_sync_flow(self, tmp_path):
        state_path = str(tmp_path / "simco.json")
        send = make_scripted_send(
            _ocpi_routes([ocpi_locations_page([ocpi_location("LOC1")])]),
            expect_token=SECRET,
        )
        with patch("requests.get", side_effect=send):
            report = _offline_sync().sync(
                _ocpi_config(), dry_run=True, state_path=state_path
            )
        assert report.errors == []
        assert report.records_pulled == 1
        assert report.records_accepted == 1
        assert report.dry_run is True
        state = SyncState.load(_ocpi_config().source_id, state_path)
        assert state.last_success_at is not None
        assert state.consecutive_failures == 0
        assert "IN/TAT/LOC1" in state.location_cursors

    def test_21_rerun_is_idempotent_via_cursor(self, tmp_path):
        state_path = str(tmp_path / "simco.json")
        send = make_scripted_send(
            _ocpi_routes([ocpi_locations_page([ocpi_location("LOC1")])]),
            expect_token=SECRET,
        )
        sync = _offline_sync()
        with patch("requests.get", side_effect=send):
            first = sync.sync(_ocpi_config(), dry_run=True, state_path=state_path)
            second = sync.sync(_ocpi_config(), dry_run=True, state_path=state_path)
        assert first.records_accepted == 1
        assert second.records_skipped_stale_cursor == 1
        assert second.records_fetched == 0

    def test_22_out_of_order_update_skipped(self, tmp_path):
        state_path = str(tmp_path / "simco.json")
        newer = ocpi_location("LOC1", last_updated="2026-10-11T12:00:00Z")
        older = ocpi_location("LOC1", last_updated="2026-10-11T10:00:00Z")
        sync = _offline_sync()
        with patch("requests.get", side_effect=make_scripted_send(
            _ocpi_routes([ocpi_locations_page([newer])]), expect_token=SECRET
        )):
            sync.sync(_ocpi_config(), dry_run=True, state_path=state_path)
        with patch("requests.get", side_effect=make_scripted_send(
            _ocpi_routes([ocpi_locations_page([older])]), expect_token=SECRET
        )):
            second = sync.sync(_ocpi_config(), dry_run=True, state_path=state_path)
        assert second.records_skipped_stale_cursor == 1

    def test_23_unpublished_never_ingested(self, tmp_path):
        send = make_scripted_send(
            _ocpi_routes([ocpi_locations_page([ocpi_location("HID", publish=False)])]),
            expect_token=SECRET,
        )
        with patch("requests.get", side_effect=send):
            report = _offline_sync().sync(_ocpi_config(), dry_run=True)
        assert report.records_skipped_unpublished == 1
        assert report.records_accepted == 0

    def test_24_unexpected_zero_result_warns(self, tmp_path):
        state_path = str(tmp_path / "simco.json")
        sync = _offline_sync()
        with patch("requests.get", side_effect=make_scripted_send(
            _ocpi_routes([ocpi_locations_page([ocpi_location("LOC1")])]),
            expect_token=SECRET,
        )):
            sync.sync(_ocpi_config(), dry_run=True, state_path=state_path)
        with patch("requests.get", side_effect=make_scripted_send(
            _ocpi_routes([ocpi_locations_page([])]), expect_token=SECRET
        )):
            second = sync.sync(_ocpi_config(), dry_run=True, state_path=state_path)
        assert any("zero-result" in w for w in second.warnings)

    def test_25_auth_failure_recorded_secret_free(self, tmp_path):
        send = make_scripted_send(
            _ocpi_routes([ocpi_locations_page([ocpi_location()])]),
            expect_token="different-token",
        )
        with patch("requests.get", side_effect=send):
            report = _offline_sync().sync(
                _ocpi_config(), dry_run=True,
                state_path=str(tmp_path / "s.json"),
            )
        assert report.records_accepted == 0
        assert len(report.errors) == 1
        assert SECRET not in json.dumps(report.to_dict())
        state = SyncState.load(_ocpi_config().source_id, str(tmp_path / "s.json"))
        assert state.consecutive_failures == 1
        assert state.last_success_at is None

    def test_26_not_configured_fails_closed(self):
        config = _ocpi_config(token=None, endpoint=None)
        report = _offline_sync().sync(config, dry_run=True)
        assert report.records_pulled == 0
        assert any("NOT_CONFIGURED" in e for e in report.errors)

    def test_27_foreign_party_isolated(self, tmp_path):
        send = make_scripted_send(
            _ocpi_routes([ocpi_locations_page([ocpi_location("LOCX", party="JIO")])]),
            expect_token=SECRET,
        )
        with patch("requests.get", side_effect=send):
            report = _offline_sync().sync(_ocpi_config(), dry_run=True)
        assert report.records_accepted == 0
        assert report.records_rejected == 1


class TestOicpSync:
    def test_30_dry_run_sync_flow(self, tmp_path):
        xml = oicp_pull_response_xml([oicp_record(), oicp_record("IN*TAT*E*0002")])
        send = make_scripted_send(
            {HUB_URL: [SimResponse(200, text_body=xml)]}, expect_token="hub-token"
        )
        config = PartnerConfig(
            partner_name="simhub", protocol="oicp", environment="sandbox",
            env_prefix="OICP_SIMHUB_SANDBOX", endpoint=HUB_URL,
            token="hub-token", party_id="TAT",
        )
        with patch("requests.post", side_effect=send):
            report = _offline_sync().sync(
                config, dry_run=True, provider_id="IN-TAT",
                state_path=str(tmp_path / "hub.json"),
            )
        assert report.errors == [], report.errors
        assert report.records_pulled == 2
        assert report.records_accepted == 2

    def test_31_oicp_requires_provider_id(self):
        config = PartnerConfig(
            partner_name="simhub", protocol="oicp", environment="sandbox",
            env_prefix="OICP_SIMHUB_SANDBOX", endpoint=HUB_URL, token="hub-token",
        )
        report = _offline_sync().sync(config, dry_run=True)
        assert any("provider_id" in e for e in report.errors)


class TestCpoCli:
    def test_40_status_not_configured(self, monkeypatch, capsys):
        for var in ("OCPI_NOP_SANDBOX_ENDPOINT", "OCPI_NOP_SANDBOX_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        code = cpo_main(["--partner", "nop", "--protocol", "ocpi",
                         "--env", "sandbox", "status"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["local_status"] == "NOT_CONFIGURED"

    def test_41_sync_without_credentials_refused(self, monkeypatch, capsys):
        for var in ("OCPI_NOP_SANDBOX_ENDPOINT", "OCPI_NOP_SANDBOX_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        code = cpo_main(["--partner", "nop", "--protocol", "ocpi",
                         "--env", "sandbox", "sync", "--dry-run"])
        assert code == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["success"] is False
