"""ChargePlus — CPO Partner Configuration & Activation Lifecycle.

Server-side only. Credentials come exclusively from environment variables
(or the approved secret manager); they never appear in source, fixtures,
logs, client bundles, or docs. Sandbox and production credentials are
strictly separated by environment prefix.

Per-partner activation states:
  NOT_CONFIGURED → SANDBOX_READY → SANDBOX_VERIFIED → AWAITING_APPROVAL →
  PRODUCTION_READY → PRODUCTION_VERIFIED

State transitions beyond NOT_CONFIGURED require recorded evidence (see
docs/cpo_partners.md). This module computes the *locally knowable* prefix of
the lifecycle (configuration presence + expiry); verification states are set
by operators after real authorized exchanges, never inferred.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("chargeplus.cpo.partners")


class PartnerStatus(str, Enum):
    """Activation lifecycle states for one commercial partner integration."""
    NOT_CONFIGURED = "NOT_CONFIGURED"
    SANDBOX_READY = "SANDBOX_READY"
    SANDBOX_VERIFIED = "SANDBOX_VERIFIED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PRODUCTION_READY = "PRODUCTION_READY"
    PRODUCTION_VERIFIED = "PRODUCTION_VERIFIED"


class PartnerCredentialError(RuntimeError):
    """Missing, malformed, or expired partner credentials (PERMANENT failure)."""
    pass


# Protocols ChargePlus implements, pinned to the versions below. OCPI and
# OICP are NOT interchangeable: OCPI 2.2.1 is the peer-to-peer CPO/eMSP REST
# interface; OICP 2.3 is Hubject's eRoaming roaming-hub interface (SOAP).
SUPPORTED_PROTOCOLS: dict[str, str] = {
    "ocpi": "2.2.1",
    "oicp": "2.3",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def redact_value(value: Any) -> str:
    """Redacts a credential for logs/errors: keeps presence, drops content."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "<missing>"
    return "<redacted>"


@dataclass
class PartnerConfig:
    """Server-side configuration for one CPO partner + environment.

    env_prefix examples: "OCPI_TATAPOWER_SANDBOX", "OICP_HUBJECT_PROD".
    Expected variables under the prefix:
      _ENDPOINT   base URL of the partner interface (required)
      _TOKEN      bearer/API credential (required)
      _TOKEN_EXPIRES_AT  optional ISO-8601 credential expiry
      _COUNTRY_CODE / _PARTY_ID  expected OCPI party scope (optional but
                                 recommended; enforced as partner isolation)
    """
    partner_name: str
    protocol: str  # "ocpi" | "oicp"
    environment: str  # "sandbox" | "production"
    env_prefix: str
    endpoint: Optional[str] = None
    token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    country_code: Optional[str] = None
    party_id: Optional[str] = None
    enabled: bool = True
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_env(
        cls,
        partner_name: str,
        protocol: str,
        environment: str,
        env_prefix: str,
    ) -> "PartnerConfig":
        """Builds config from environment; missing vars stay None (NOT_CONFIGURED)."""
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError(
                f"Unsupported protocol {protocol!r}. Supported: {sorted(SUPPORTED_PROTOCOLS)}"
            )
        endpoint = os.getenv(f"{env_prefix}_ENDPOINT")
        token = os.getenv(f"{env_prefix}_TOKEN")
        expires_raw = os.getenv(f"{env_prefix}_TOKEN_EXPIRES_AT")
        expires_at: Optional[datetime] = None
        if expires_raw and expires_raw.strip():
            try:
                expires_at = datetime.fromisoformat(expires_raw.strip().replace("Z", "+00:00"))
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise PartnerCredentialError(
                    f"{env_prefix}_TOKEN_EXPIRES_AT is not a valid ISO-8601 timestamp"
                ) from exc
        return cls(
            partner_name=partner_name,
            protocol=protocol,
            environment=environment,
            env_prefix=env_prefix,
            endpoint=(endpoint.strip() if endpoint and endpoint.strip() else None),
            token=(token if token else None),
            token_expires_at=expires_at,
            country_code=(os.getenv(f"{env_prefix}_COUNTRY_CODE") or None),
            party_id=(os.getenv(f"{env_prefix}_PARTY_ID") or None),
        )

    @property
    def source_id(self) -> str:
        """Canonical source identifier used in run audit + provenance."""
        return f"{self.protocol}:{self.partner_name}:{self.environment}"

    def local_status(self, as_of: Optional[datetime] = None) -> PartnerStatus:
        """Computes the locally knowable lifecycle prefix.

        Returns NOT_CONFIGURED when endpoint/token are missing, or when the
        credential is expired. Returns SANDBOX_READY / PRODUCTION_READY when
        configuration is complete. Anything beyond (VERIFIED/…) is operator-
        recorded after real exchanges — never inferred here.
        """
        as_of = as_of or _utcnow()
        if not self.enabled:
            return PartnerStatus.NOT_CONFIGURED
        if not self.endpoint or not self.token:
            return PartnerStatus.NOT_CONFIGURED
        if self.token_expires_at is not None and self.token_expires_at <= as_of:
            return PartnerStatus.NOT_CONFIGURED
        return (
            PartnerStatus.SANDBOX_READY
            if self.environment == "sandbox"
            else PartnerStatus.PRODUCTION_READY
        )

    def require_usable(self, as_of: Optional[datetime] = None) -> None:
        """Raises PartnerCredentialError unless the config is usable now."""
        as_of = as_of or _utcnow()
        status = self.local_status(as_of=as_of)
        if status == PartnerStatus.NOT_CONFIGURED:
            if not self.endpoint or not self.token:
                raise PartnerCredentialError(
                    f"Partner {self.partner_name} ({self.environment}) is NOT_CONFIGURED: "
                    f"set {self.env_prefix}_ENDPOINT and {self.env_prefix}_TOKEN. "
                    "See docs/cpo_partners.md."
                )
            if self.token_expires_at is not None and self.token_expires_at <= as_of:
                raise PartnerCredentialError(
                    f"Partner {self.partner_name} ({self.environment}) credential expired at "
                    f"{self.token_expires_at.isoformat()}. Rotate {self.env_prefix}_TOKEN."
                )
            raise PartnerCredentialError(
                f"Partner {self.partner_name} ({self.environment}) is disabled or misconfigured."
            )

    def safe_summary(self) -> dict[str, Any]:
        """Log/audit-safe summary: presence of secrets, never their values."""
        return {
            "partner_name": self.partner_name,
            "protocol": self.protocol,
            "protocol_version": SUPPORTED_PROTOCOLS.get(self.protocol),
            "environment": self.environment,
            "source_id": self.source_id,
            "enabled": self.enabled,
            "endpoint": self.endpoint or "<missing>",
            "token": redact_value(self.token),
            "token_expires_at": (
                self.token_expires_at.isoformat() if self.token_expires_at else None
            ),
            "country_code": self.country_code,
            "party_id": self.party_id,
            "local_status": self.local_status().value,
        }


# ---------------------------------------------------------------------------
# Activation checklist (local prerequisites; external steps need the partner)
# ---------------------------------------------------------------------------

ACTIVATION_STEPS: list[dict[str, str]] = [
    {"id": "agreement", "owner": "external/partner",
     "step": "Bilateral business/roaming agreement signed with the CPO or hub."},
    {"id": "protocol_scope", "owner": "local",
     "step": "Pin protocol version + roles (OCPI 2.2.1 CPO-pull Locations; OICP 2.3 PullEVSEData subset)."},
    {"id": "sandbox_credentials", "owner": "external/partner",
     "step": "Sandbox endpoint + credentials issued by the partner."},
    {"id": "sandbox_config", "owner": "local",
     "step": "Configure <PREFIX>_ENDPOINT/_TOKEN(/_TOKEN_EXPIRES_AT) sandbox variables; status becomes SANDBOX_READY."},
    {"id": "sandbox_exchange", "owner": "local+partner",
     "step": "Successful authorized sandbox pull (locations/EVSE data) with recorded evidence → SANDBOX_VERIFIED."},
    {"id": "conformance", "owner": "external/partner",
     "step": "Partner conformance/certification completed where required → AWAITING_APPROVAL."},
    {"id": "production_credentials", "owner": "external/partner",
     "step": "Production endpoint + credentials issued (never reuse sandbox credentials) → PRODUCTION_READY."},
    {"id": "production_exchange", "owner": "local+partner",
     "step": "Successful authorized production pull with recorded evidence → PRODUCTION_VERIFIED."},
]


def activation_checklist(config: PartnerConfig) -> dict[str, Any]:
    """Returns the activation checklist annotated with local completion state."""
    status = config.local_status()
    configured = status in (PartnerStatus.SANDBOX_READY, PartnerStatus.PRODUCTION_READY)
    steps = []
    for step in ACTIVATION_STEPS:
        done: Optional[bool] = None
        if step["id"] in ("protocol_scope",):
            done = True  # implemented in this codebase (fixed scope)
        elif step["id"] in ("sandbox_config",):
            done = configured
        steps.append({**step, "locally_complete": done})
    return {
        "partner_name": config.partner_name,
        "protocol": config.protocol,
        "protocol_version": SUPPORTED_PROTOCOLS.get(config.protocol),
        "environment": config.environment,
        "local_status": status.value,
        "steps": steps,
    }
