"""ChargePlus — Freshness Engine, Observation Provenance & Staleness Decay.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.9 (Record Freshness/Provenance & Observation Freshness Decay)

Authoritative, pure-computational, deterministic freshness and provenance layer.
Evaluates the temporal relevance of station metadata and live telemetry observations
against configurable, domain-explicit operational policies.

CORE ARCHITECTURAL INVARIANTS:
1. STALE != UNAVAILABLE:
   An aging or stale observation remains valid historical evidence.
   It is NEVER rewritten into "unavailable" or "broken" merely because time elapsed.
2. UNKNOWN FRESHNESS != UNAVAILABLE:
   Missing timestamps evaluate to UNKNOWN freshness, never assumed unavailable.
3. MISSING TIMESTAMP != CURRENT:
   Missing timestamps are NEVER defaulted to datetime.now() or assumed fresh.
4. PURE DETERMINISM & REPRODUCIBILITY:
   Zero hidden `datetime.now()` calls inside evaluation logic. Every evaluation
   requires an explicit `as_of` reference time, enabling deterministic backfills,
   audits, tests, and future ML feature engineering.
5. METADATA FRESHNESS != OBSERVATION FRESHNESS:
   Static station attributes and dynamic connector telemetry have distinct
   update cadences and are evaluated independently.
6. TRANSPARENT AGE OVER ARBITRARY FORMULAS:
   Raw observation age (seconds, minutes) is always preserved. Mathematical decay
   curves (linear, exponential, step) are configurable operational policies,
   never claimed as external scientific truth.
7. TIME IDENTITY PRESERVATION:
   Strictly distinguishes the four critical timestamps:
   A. Observation / Event Time (when reality occurred)
   B. Source Updated Time (when upstream source updated its record)
   C. Retrieval Time (when ChargePlus fetched the record)
   D. Ingestion / Persistence Time (when ChargePlus processed/persisted the record)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, validator

from backend.ingestion.constants import AvailabilityStatus, OperationalStatus
from backend.ingestion.contracts import (
    NormalizedObservationRecord,
    NormalizedStationRecord,
    RawSourceRecord,
)


# ==============================================================================
# 1. Authoritative Enumerations
# ==============================================================================

class FreshnessState(str, Enum):
    """Categorical temporal status of an operational entity or observation."""
    FRESH = "FRESH"      # Within the applicable fresh window
    AGING = "AGING"      # Exceeded fresh window but within allowable stale threshold
    STALE = "STALE"      # Exceeded stale threshold; historical evidence only
    UNKNOWN = "UNKNOWN"  # Cannot establish freshness reliably (missing/malformed timestamp)


class FreshnessBasis(str, Enum):
    """Identifies the exact authoritative timestamp utilized for freshness evaluation."""
    OBSERVATION_TIME = "OBSERVATION_TIME"    # Operational event/telemetry timestamp
    SOURCE_UPDATED_AT = "SOURCE_UPDATED_AT"  # Timestamp reported by upstream provider
    RETRIEVED_AT = "RETRIEVED_AT"            # ChargePlus adapter retrieval timestamp (fallback only)
    UNKNOWN = "UNKNOWN"                      # No defensible timestamp could be resolved


class InformationType(str, Enum):
    """Broad category of charging information with distinct natural update cadences."""
    LIVE_TELEMETRY = "LIVE_TELEMETRY"          # Port availability, occupancy snapshots
    OPERATIONAL_STATUS = "OPERATIONAL_STATUS"  # Physical site status (operational, closed)
    STATIC_METADATA = "STATIC_METADATA"        # Address, coordinates, operator, access rules
    PRICING = "PRICING"                        # Tariffs, per-kWh rates, connection fees
    HOURS = "HOURS"                            # Operating schedule, 24x7 flags


class DecayCurve(str, Enum):
    """Mathematical decay curve applied to calculate continuous freshness scores [0.0, 1.0]."""
    NONE = "NONE"                # No continuous decay score (decay_score is None)
    LINEAR = "LINEAR"            # Linear degradation from 1.0 (fresh) down to 0.0 (stale)
    EXPONENTIAL = "EXPONENTIAL"  # Continuous half-life decay
    STEP = "STEP"                # Discrete step function (1.0 for fresh, 0.5 for aging, 0.0 for stale)


# ==============================================================================
# 2. Configurable Freshness Policy
# ==============================================================================

class FreshnessPolicy(BaseModel):
    """Configurable operational policy governing temporal thresholds and decay rules.
    
    IMPORTANT: Thresholds represent ChargePlus operational policy for discovery
    and display, NOT universal physical truth. Different feeds and information
    types use dedicated policy instances.
    """
    policy_id: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Unique, stable policy identifier (e.g. 'chargeplus_live_telemetry_v1')"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable policy name"
    )
    description: str = Field(
        default="",
        description="Detailed description of applicability, rationale, and SLA assumptions"
    )
    information_type: InformationType = Field(
        ...,
        description="Category of EV charging data governed by this policy"
    )
    fresh_window_seconds: float = Field(
        ...,
        ge=0.0,
        description="Duration in seconds during which information is considered fully FRESH"
    )
    stale_window_seconds: float = Field(
        ...,
        ge=0.0,
        description="Duration in seconds after which information transitions from AGING to STALE"
    )
    allow_retrieval_fallback: bool = Field(
        default=False,
        description="If True, permits falling back to ChargePlus retrieval time when source time is omitted"
    )
    future_skew_tolerance_seconds: float = Field(
        default=5.0,
        ge=0.0,
        description="Permissible clock skew in seconds before a future timestamp is flagged as anomalous"
    )
    decay_curve: DecayCurve = Field(
        default=DecayCurve.NONE,
        description="Mathematical function used to calculate normalized decay score [0.0, 1.0]"
    )
    decay_half_life_seconds: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Half-life parameter in seconds for EXPONENTIAL decay curve"
    )
    min_decay_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum bound for computed decay score"
    )
    max_decay_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Maximum bound for computed decay score"
    )

    class Config:
        frozen = True
        extra = "forbid"

    @validator("stale_window_seconds")
    def validate_windows(cls, v: float, values: dict[str, Any]) -> float:
        fresh_win = values.get("fresh_window_seconds")
        if fresh_win is not None and v < fresh_win:
            raise ValueError(
                f"stale_window_seconds ({v}) must be greater than or equal to fresh_window_seconds ({fresh_win})"
            )
        return v

    @validator("max_decay_score")
    def validate_decay_bounds(cls, v: float, values: dict[str, Any]) -> float:
        min_score = values.get("min_decay_score")
        if min_score is not None and v < min_score:
            raise ValueError(
                f"max_decay_score ({v}) must be >= min_decay_score ({min_score})"
            )
        return v


# ==============================================================================
# 3. Evaluation Result Models
# ==============================================================================

class FreshnessEvaluationResult(BaseModel):
    """Complete, auditable outcome of evaluating the freshness of an entity or observation.
    
    CRITICAL INVARIANT:
    `retained_status` strictly preserves the original reported operational or
    availability status. It is NEVER modified to 'unavailable' or 'broken'
    as a consequence of becoming STALE.
    """
    state: FreshnessState = Field(
        ...,
        description="Discrete freshness classification: FRESH, AGING, STALE, UNKNOWN"
    )
    basis: FreshnessBasis = Field(
        ...,
        description="The exact timestamp field used to determine age"
    )
    basis_timestamp: Optional[datetime] = Field(
        default=None,
        description="Normalized UTC timestamp that served as the evaluation basis"
    )
    as_of: datetime = Field(
        ...,
        description="Reference UTC timestamp against which age was calculated"
    )
    age_seconds: Optional[float] = Field(
        default=None,
        description="Raw age in seconds relative to as_of (None if basis is UNKNOWN)"
    )
    age_minutes: Optional[float] = Field(
        default=None,
        description="Raw age in minutes rounded to 2 decimal places"
    )
    policy_id: str = Field(
        ...,
        description="Identifier of the FreshnessPolicy applied during evaluation"
    )
    decay_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Normalized freshness/confidence score [0.0, 1.0] if policy defines a decay curve"
    )
    decay_curve: DecayCurve = Field(
        default=DecayCurve.NONE,
        description="The decay curve applied"
    )
    is_future: bool = Field(
        default=False,
        description="True if basis_timestamp was in the future beyond acceptable clock skew tolerance"
    )
    future_skew_seconds: Optional[float] = Field(
        default=None,
        description="Magnitude of future skew in seconds if is_future is True"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Diagnostic notices (e.g. clock skew, missing source timestamp, fallback used)"
    )
    retained_status: Optional[Any] = Field(
        default=None,
        description="Unaltered operational or availability status passed in for non-destructive preservation"
    )

    class Config:
        frozen = True
        extra = "forbid"

    @property
    def is_usable_for_live_display(self) -> bool:
        """True if the information is fresh enough for active driver discovery/routing."""
        return self.state in (FreshnessState.FRESH, FreshnessState.AGING)

    def to_dict(self) -> dict[str, Any]:
        """Converts result to a clean dictionary representation."""
        return {
            "state": self.state.value,
            "basis": self.basis.value,
            "basis_timestamp": self.basis_timestamp.isoformat() if self.basis_timestamp else None,
            "as_of": self.as_of.isoformat(),
            "age_seconds": round(self.age_seconds, 2) if self.age_seconds is not None else None,
            "age_minutes": self.age_minutes,
            "policy_id": self.policy_id,
            "decay_score": round(self.decay_score, 4) if self.decay_score is not None else None,
            "decay_curve": self.decay_curve.value,
            "is_future": self.is_future,
            "future_skew_seconds": round(self.future_skew_seconds, 2) if self.future_skew_seconds is not None else None,
            "warnings": list(self.warnings),
            "retained_status": str(self.retained_status) if self.retained_status is not None else None,
            "is_usable_for_live_display": self.is_usable_for_live_display,
        }


class StationFreshnessSummary(BaseModel):
    """Dual-facet freshness evaluation separating static station metadata from dynamic telemetry.
    
    Enforces Section 14: Station profile metadata can be recent while telemetry
    is stale or absent, and vice versa.
    """
    station_id: Optional[str] = Field(
        default=None,
        description="ChargePlus canonical station UUID if assigned"
    )
    source_id: str = Field(
        ...,
        description="External data source identifier"
    )
    source_station_id: str = Field(
        ...,
        description="Provider primary record key"
    )
    as_of: datetime = Field(
        ...,
        description="Reference UTC timestamp used for evaluations"
    )
    metadata_freshness: FreshnessEvaluationResult = Field(
        ...,
        description="Freshness evaluation of static station attributes"
    )
    observation_freshness: Optional[FreshnessEvaluationResult] = Field(
        default=None,
        description="Freshness evaluation of live telemetry observation, or None if no observation exists"
    )
    has_live_observation: bool = Field(
        default=False,
        description="True if record included genuine automated telemetry"
    )
    raw_payload_hash: Optional[str] = Field(
        default=None,
        description="Layer 1 SHA-256 payload digest"
    )
    contract_version: Optional[str] = Field(
        default=None,
        description="ChargePlus contract version"
    )

    class Config:
        frozen = True
        extra = "forbid"

    def to_dict(self) -> dict[str, Any]:
        """Converts summary to dictionary."""
        return {
            "station_id": self.station_id,
            "source_id": self.source_id,
            "source_station_id": self.source_station_id,
            "as_of": self.as_of.isoformat(),
            "has_live_observation": self.has_live_observation,
            "metadata_freshness": self.metadata_freshness.to_dict(),
            "observation_freshness": self.observation_freshness.to_dict() if self.observation_freshness else None,
            "raw_payload_hash": self.raw_payload_hash,
            "contract_version": self.contract_version,
        }


# ==============================================================================
# 4. Standard Operational Policies & Registry
# ==============================================================================

# Standard ChargePlus Operational Policies (Configurable Defaults)

DEFAULT_LIVE_TELEMETRY_POLICY = FreshnessPolicy(
    policy_id="chargeplus_live_telemetry_v1",
    name="ChargePlus Live Telemetry Default Policy",
    description=(
        "Standard policy for automated dynamic connector occupancy feeds. "
        "FRESH <= 5m (300s); AGING 5m-15m (300s-900s); STALE > 15m (900s). "
        "Linear decay score from 1.0 down to 0.0 at 15 minutes. "
        "Retrieval fallback disallowed: live telemetry must have authentic observation timestamp."
    ),
    information_type=InformationType.LIVE_TELEMETRY,
    fresh_window_seconds=300.0,       # 5 minutes
    stale_window_seconds=900.0,       # 15 minutes
    allow_retrieval_fallback=False,   # Strictly disallow pretending fetch time is observation time
    future_skew_tolerance_seconds=5.0,
    decay_curve=DecayCurve.LINEAR,
    min_decay_score=0.0,
    max_decay_score=1.0,
)

DEFAULT_OPERATIONAL_STATUS_POLICY = FreshnessPolicy(
    policy_id="chargeplus_operational_status_v1",
    name="ChargePlus Operational Status Default Policy",
    description=(
        "Policy for physical station operational status (operational, maintenance, decommissioned). "
        "FRESH <= 1 hour (3600s); AGING 1h-24h (3600s-86400s); STALE > 24 hours (86400s). "
        "Retrieval fallback disallowed."
    ),
    information_type=InformationType.OPERATIONAL_STATUS,
    fresh_window_seconds=3600.0,      # 1 hour
    stale_window_seconds=86400.0,     # 24 hours
    allow_retrieval_fallback=False,
    future_skew_tolerance_seconds=5.0,
    decay_curve=DecayCurve.LINEAR,
    min_decay_score=0.0,
    max_decay_score=1.0,
)

DEFAULT_STATIC_METADATA_POLICY = FreshnessPolicy(
    policy_id="chargeplus_static_metadata_v1",
    name="ChargePlus Static Metadata Default Policy",
    description=(
        "Policy for physical site metadata (address, coordinates, operator, connector specs). "
        "FRESH <= 7 days (604800s); AGING 7d-30d (604800s-2592000s); STALE > 30 days (2592000s). "
        "Retrieval fallback explicitly allowed when source does not provide explicit last-modified header."
    ),
    information_type=InformationType.STATIC_METADATA,
    fresh_window_seconds=604800.0,    # 7 days
    stale_window_seconds=2592000.0,   # 30 days
    allow_retrieval_fallback=True,    # Retrieval timestamp permitted as documented fallback
    future_skew_tolerance_seconds=5.0,
    decay_curve=DecayCurve.NONE,      # Discrete states without artificial fractional score
)

DEFAULT_PRICING_POLICY = FreshnessPolicy(
    policy_id="chargeplus_pricing_v1",
    name="ChargePlus Pricing Tariff Policy",
    description=(
        "Policy for charging tariffs and per-kWh rates. "
        "FRESH <= 24 hours (86400s); AGING 24h-7d (86400s-604800s); STALE > 7 days (604800s). "
        "Retrieval fallback disallowed."
    ),
    information_type=InformationType.PRICING,
    fresh_window_seconds=86400.0,     # 24 hours
    stale_window_seconds=604800.0,    # 7 days
    allow_retrieval_fallback=False,
    future_skew_tolerance_seconds=5.0,
    decay_curve=DecayCurve.NONE,
)

# Source-Specific Policies (OpenChargeMap)

OCM_LIVE_TELEMETRY_POLICY = FreshnessPolicy(
    policy_id="ocm_live_telemetry_v1",
    name="OpenChargeMap Live Telemetry Policy",
    description=(
        "OCM StatusTypeID 10/20 telemetry freshness. "
        "FRESH <= 5m (300s); AGING 5m-15m; STALE > 15m. "
        "Decay curve: LINEAR."
    ),
    information_type=InformationType.LIVE_TELEMETRY,
    fresh_window_seconds=300.0,
    stale_window_seconds=900.0,
    allow_retrieval_fallback=False,
    future_skew_tolerance_seconds=5.0,
    decay_curve=DecayCurve.LINEAR,
)

OCM_STATIC_METADATA_POLICY = FreshnessPolicy(
    policy_id="ocm_static_metadata_v1",
    name="OpenChargeMap Static Metadata Policy",
    description=(
        "OCM station identity & equipment metadata. Evaluated against DateLastStatusUpdate / DateCreated. "
        "FRESH <= 7 days (604800s); AGING 7d-30d; STALE > 30 days. "
        "Retrieval fallback permitted."
    ),
    information_type=InformationType.STATIC_METADATA,
    fresh_window_seconds=604800.0,
    stale_window_seconds=2592000.0,
    allow_retrieval_fallback=True,
    future_skew_tolerance_seconds=5.0,
    decay_curve=DecayCurve.NONE,
)


class FreshnessPolicyRegistry:
    """Registry maintaining available FreshnessPolicy definitions.
    
    Permits runtime lookup by policy_id or by (source_id, information_type).
    """

    def __init__(self) -> None:
        self._policies: dict[str, FreshnessPolicy] = {}
        self._source_type_map: dict[tuple[str, InformationType], FreshnessPolicy] = {}
        self._type_defaults: dict[InformationType, FreshnessPolicy] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Populates baseline ChargePlus operational policies."""
        # Generic type defaults
        self.register(DEFAULT_LIVE_TELEMETRY_POLICY, is_type_default=True)
        self.register(DEFAULT_OPERATIONAL_STATUS_POLICY, is_type_default=True)
        self.register(DEFAULT_STATIC_METADATA_POLICY, is_type_default=True)
        self.register(DEFAULT_PRICING_POLICY, is_type_default=True)

        # Source-specific configurations
        self.register(OCM_LIVE_TELEMETRY_POLICY)
        self.bind_source("openchargemap", InformationType.LIVE_TELEMETRY, OCM_LIVE_TELEMETRY_POLICY)
        self.register(OCM_STATIC_METADATA_POLICY)
        self.bind_source("openchargemap", InformationType.STATIC_METADATA, OCM_STATIC_METADATA_POLICY)

    def register(self, policy: FreshnessPolicy, is_type_default: bool = False) -> None:
        """Registers a policy in the registry."""
        self._policies[policy.policy_id] = policy
        if is_type_default or policy.information_type not in self._type_defaults:
            self._type_defaults[policy.information_type] = policy

    def bind_source(
        self, source_id: str, info_type: InformationType, policy: FreshnessPolicy
    ) -> None:
        """Binds a specific policy to a source_id and information_type pair."""
        self.register(policy)
        self._source_type_map[(source_id.lower().strip(), info_type)] = policy

    def get_policy(self, policy_id: str) -> Optional[FreshnessPolicy]:
        """Resolves a policy by its unique policy_id."""
        return self._policies.get(policy_id)

    def resolve_policy(
        self,
        info_type: InformationType,
        source_id: Optional[str] = None,
        explicit_policy: Optional[Union[FreshnessPolicy, str]] = None,
    ) -> FreshnessPolicy:
        """Resolves the appropriate policy using hierarchy:
        1. Explicit policy object or policy_id string passed by caller
        2. Source-specific policy bound to (source_id, info_type)
        3. Generic default policy for info_type
        """
        if isinstance(explicit_policy, FreshnessPolicy):
            return explicit_policy
        if isinstance(explicit_policy, str):
            resolved = self.get_policy(explicit_policy)
            if resolved:
                return resolved

        if source_id:
            bound = self._source_type_map.get((source_id.lower().strip(), info_type))
            if bound:
                return bound

        default_policy = self._type_defaults.get(info_type)
        if default_policy:
            return default_policy

        # Fallback to static metadata policy if no exact type match
        return DEFAULT_STATIC_METADATA_POLICY


# ==============================================================================
# 5. Authoritative Freshness Engine
# ==============================================================================

class FreshnessEngine:
    """Authoritative, pure computational engine for EV data freshness & staleness evaluation.
    
    Zero database I/O, zero network requests, zero hidden `datetime.now()` dependencies.
    All evaluations require an explicit `as_of` timestamp.
    """

    def __init__(self, registry: Optional[FreshnessPolicyRegistry] = None) -> None:
        self.registry = registry or FreshnessPolicyRegistry()

    @staticmethod
    def normalize_utc(dt: Optional[datetime]) -> Optional[datetime]:
        """Converts an input datetime into a timezone-aware UTC datetime.
        
        If dt is naive, assumes UTC and attaches timezone.utc to prevent silent calculation skew.
        """
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def calculate_decay_score(
        age_seconds: float,
        policy: FreshnessPolicy,
    ) -> Optional[float]:
        """Calculates normalized decay score [0.0, 1.0] based on the policy's configured curve.
        
        Curves supported:
        - NONE: returns None (no continuous score, raw age is authoritative)
        - LINEAR: degrades linearly from max_score at 0s to min_score at stale_window_seconds
        - EXPONENTIAL: half-life exponential decay: e^(-ln(2) * age / half_life)
        - STEP: discrete 1.0 for FRESH, 0.5 for AGING, 0.0 for STALE
        """
        if policy.decay_curve == DecayCurve.NONE:
            return None

        # Clamp age for score evaluation
        effective_age = max(0.0, age_seconds)

        if policy.decay_curve == DecayCurve.STEP:
            if effective_age <= policy.fresh_window_seconds:
                return policy.max_decay_score
            elif effective_age <= policy.stale_window_seconds:
                return (policy.max_decay_score + policy.min_decay_score) / 2.0
            else:
                return policy.min_decay_score

        elif policy.decay_curve == DecayCurve.LINEAR:
            if policy.stale_window_seconds <= 0.0:
                return policy.min_decay_score
            if effective_age <= 0.0:
                return policy.max_decay_score
            if effective_age >= policy.stale_window_seconds:
                return policy.min_decay_score

            ratio = effective_age / policy.stale_window_seconds
            score = policy.max_decay_score - ratio * (policy.max_decay_score - policy.min_decay_score)
            return max(policy.min_decay_score, min(policy.max_decay_score, score))

        elif policy.decay_curve == DecayCurve.EXPONENTIAL:
            half_life = policy.decay_half_life_seconds or policy.fresh_window_seconds or 300.0
            if half_life <= 0.0:
                half_life = 300.0
            # score = 2^(-age / half_life)
            raw_factor = math.pow(2.0, -effective_age / half_life)
            score = policy.min_decay_score + raw_factor * (policy.max_decay_score - policy.min_decay_score)
            return max(policy.min_decay_score, min(policy.max_decay_score, score))

        return None

    def determine_basis(
        self,
        observed_at: Optional[datetime],
        source_updated_at: Optional[datetime],
        retrieved_at: Optional[datetime],
        policy: FreshnessPolicy,
    ) -> tuple[FreshnessBasis, Optional[datetime], list[str]]:
        """Determines the authoritative basis timestamp according to Section 9 rules:
        
        Priority order:
        1. observed_at: Authoritative for point-in-time observations / live telemetry
        2. source_updated_at: Authoritative for upstream source-managed attributes
        3. retrieved_at: Permitted ONLY if policy.allow_retrieval_fallback is True
        4. UNKNOWN: If no defensible timestamp exists
        """
        warnings: list[str] = []

        if policy.information_type == InformationType.LIVE_TELEMETRY:
            if observed_at is not None:
                return FreshnessBasis.OBSERVATION_TIME, self.normalize_utc(observed_at), warnings
            if source_updated_at is not None:
                warnings.append("Live telemetry missing observed_at; using source_updated_at as secondary basis")
                return FreshnessBasis.SOURCE_UPDATED_AT, self.normalize_utc(source_updated_at), warnings
            if policy.allow_retrieval_fallback and retrieved_at is not None:
                warnings.append("Live telemetry missing source timestamps; fell back to retrieval time")
                return FreshnessBasis.RETRIEVED_AT, self.normalize_utc(retrieved_at), warnings
            return FreshnessBasis.UNKNOWN, None, warnings

        # Static metadata, operational status, pricing, hours
        if source_updated_at is not None:
            return FreshnessBasis.SOURCE_UPDATED_AT, self.normalize_utc(source_updated_at), warnings
        if observed_at is not None:
            return FreshnessBasis.OBSERVATION_TIME, self.normalize_utc(observed_at), warnings
        if policy.allow_retrieval_fallback and retrieved_at is not None:
            warnings.append(
                f"Source omitted last-updated timestamp for {policy.information_type.value}; "
                f"used retrieval timestamp as policy-permitted fallback"
            )
            return FreshnessBasis.RETRIEVED_AT, self.normalize_utc(retrieved_at), warnings

        return FreshnessBasis.UNKNOWN, None, warnings

    def evaluate(
        self,
        as_of: datetime,
        observed_at: Optional[datetime] = None,
        source_updated_at: Optional[datetime] = None,
        retrieved_at: Optional[datetime] = None,
        policy: Optional[Union[FreshnessPolicy, str]] = None,
        information_type: InformationType = InformationType.LIVE_TELEMETRY,
        source_id: Optional[str] = None,
        retained_status: Optional[Any] = None,
    ) -> FreshnessEvaluationResult:
        """Evaluates data freshness deterministically against an explicit reference time.
        
        Args:
            as_of: Mandatory UTC reference time. Zero hidden datetime.now() calls.
            observed_at: Event timestamp when telemetry / status actually occurred.
            source_updated_at: Timestamp reported by provider when record was updated.
            retrieved_at: Timestamp when ChargePlus fetched the record.
            policy: Explicit FreshnessPolicy instance or policy_id string (optional).
            information_type: InformationType category to resolve policy if omitted.
            source_id: External provider ID for source-specific policy lookup.
            retained_status: Original operational or availability status to preserve intact.
            
        Returns:
            FreshnessEvaluationResult with state, basis, age, decay score, and preserved status.
        """
        as_of_utc = self.normalize_utc(as_of)
        if as_of_utc is None:
            raise ValueError("as_of reference datetime is strictly mandatory for freshness evaluation")

        # 1. Resolve applicable policy
        pol = self.registry.resolve_policy(
            info_type=information_type,
            source_id=source_id,
            explicit_policy=policy,
        )

        # 2. Determine basis timestamp
        basis, basis_ts, warnings = self.determine_basis(
            observed_at=observed_at,
            source_updated_at=source_updated_at,
            retrieved_at=retrieved_at,
            policy=pol,
        )

        # 3. Handle missing timestamp
        if basis == FreshnessBasis.UNKNOWN or basis_ts is None:
            return FreshnessEvaluationResult(
                state=FreshnessState.UNKNOWN,
                basis=FreshnessBasis.UNKNOWN,
                basis_timestamp=None,
                as_of=as_of_utc,
                age_seconds=None,
                age_minutes=None,
                policy_id=pol.policy_id,
                decay_score=None,
                decay_curve=pol.decay_curve,
                is_future=False,
                future_skew_seconds=None,
                warnings=warnings + ["Missing authoritative timestamp; freshness cannot be established"],
                retained_status=retained_status,
            )

        # 4. Compute raw age relative to as_of
        age_seconds = (as_of_utc - basis_ts).total_seconds()

        # 5. Defensive check for future timestamps (Section 11)
        is_future = False
        future_skew: Optional[float] = None
        if age_seconds < -pol.future_skew_tolerance_seconds:
            is_future = True
            future_skew = abs(age_seconds)
            warnings.append(
                f"Timestamp {basis_ts.isoformat()} is in the future by {future_skew:.1f}s "
                f"relative to as_of {as_of_utc.isoformat()} (exceeds {pol.future_skew_tolerance_seconds}s tolerance)"
            )
            # Future timestamp evaluated defensibly as UNKNOWN with zero decay score
            return FreshnessEvaluationResult(
                state=FreshnessState.UNKNOWN,
                basis=basis,
                basis_timestamp=basis_ts,
                as_of=as_of_utc,
                age_seconds=age_seconds,
                age_minutes=round(age_seconds / 60.0, 2),
                policy_id=pol.policy_id,
                decay_score=pol.min_decay_score,
                decay_curve=pol.decay_curve,
                is_future=True,
                future_skew_seconds=future_skew,
                warnings=warnings,
                retained_status=retained_status,
            )
        elif age_seconds < 0.0:
            # Minor clock skew within tolerance: clamp age to 0.0
            age_seconds = 0.0

        # 6. Discrete state classification
        if age_seconds <= pol.fresh_window_seconds:
            state = FreshnessState.FRESH
        elif age_seconds <= pol.stale_window_seconds:
            state = FreshnessState.AGING
        else:
            state = FreshnessState.STALE

        # 7. Compute decay score if policy defines a curve
        decay_score = self.calculate_decay_score(age_seconds, pol)

        return FreshnessEvaluationResult(
            state=state,
            basis=basis,
            basis_timestamp=basis_ts,
            as_of=as_of_utc,
            age_seconds=age_seconds,
            age_minutes=round(age_seconds / 60.0, 2),
            policy_id=pol.policy_id,
            decay_score=decay_score,
            decay_curve=pol.decay_curve,
            is_future=is_future,
            future_skew_seconds=future_skew,
            warnings=warnings,
            retained_status=retained_status,
        )

    # --------------------------------------------------------------------------
    # Specialized Record Evaluators
    # --------------------------------------------------------------------------

    def evaluate_observation(
        self,
        obs: NormalizedObservationRecord,
        as_of: datetime,
        policy: Optional[Union[FreshnessPolicy, str]] = None,
    ) -> FreshnessEvaluationResult:
        """Evaluates freshness for a NormalizedObservationRecord.
        
        Strictly preserves `obs.availability_status` as `retained_status`.
        """
        return self.evaluate(
            as_of=as_of,
            observed_at=obs.observed_at,
            retrieved_at=obs.retrieved_at,
            policy=policy,
            information_type=InformationType.LIVE_TELEMETRY,
            source_id=obs.source_id,
            retained_status=obs.availability_status,
        )

    def evaluate_station_metadata(
        self,
        station: NormalizedStationRecord,
        as_of: datetime,
        policy: Optional[Union[FreshnessPolicy, str]] = None,
        retrieval_timestamp: Optional[datetime] = None,
    ) -> FreshnessEvaluationResult:
        """Evaluates freshness for static station metadata.
        
        Extracts source update timestamps from `extra_metadata` where available.
        Strictly preserves `station.operational_status` as `retained_status`.
        """
        source_ts: Optional[datetime] = None
        extra = station.extra_metadata or {}
        raw_update_str = extra.get("date_last_status_update") or extra.get("date_created")
        if isinstance(raw_update_str, datetime):
            source_ts = raw_update_str
        elif isinstance(raw_update_str, str):
            try:
                source_ts = datetime.fromisoformat(raw_update_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                source_ts = None

        return self.evaluate(
            as_of=as_of,
            source_updated_at=source_ts,
            retrieved_at=retrieval_timestamp,
            policy=policy,
            information_type=InformationType.STATIC_METADATA,
            source_id=station.source_id,
            retained_status=station.operational_status,
        )

    def evaluate_raw_record(
        self,
        raw: RawSourceRecord,
        as_of: datetime,
        policy: Optional[Union[FreshnessPolicy, str]] = None,
        information_type: InformationType = InformationType.STATIC_METADATA,
    ) -> FreshnessEvaluationResult:
        """Evaluates freshness directly from a Layer 1 RawSourceRecord."""
        return self.evaluate(
            as_of=as_of,
            source_updated_at=raw.source_timestamp,
            retrieved_at=raw.retrieval_timestamp,
            policy=policy,
            information_type=information_type,
            source_id=raw.source_id,
        )

    def evaluate_station_current_state(
        self,
        station: NormalizedStationRecord,
        as_of: datetime,
        meta_policy: Optional[Union[FreshnessPolicy, str]] = None,
        live_policy: Optional[Union[FreshnessPolicy, str]] = None,
        retrieval_timestamp: Optional[datetime] = None,
        station_id: Optional[str] = None,
    ) -> StationFreshnessSummary:
        """Generates a complete dual-facet freshness summary for a station record.
        
        Evaluates both metadata freshness AND observation freshness independently,
        ensuring that static profile age never corrupts live telemetry status.
        """
        meta_result = self.evaluate_station_metadata(
            station=station,
            as_of=as_of,
            policy=meta_policy,
            retrieval_timestamp=retrieval_timestamp,
        )

        obs_result: Optional[FreshnessEvaluationResult] = None
        has_obs = station.observation is not None
        if has_obs:
            obs_result = self.evaluate_observation(
                obs=station.observation,
                as_of=as_of,
                policy=live_policy,
            )

        return StationFreshnessSummary(
            station_id=station_id,
            source_id=station.source_id,
            source_station_id=station.source_station_id,
            as_of=self.normalize_utc(as_of) or as_of,
            metadata_freshness=meta_result,
            observation_freshness=obs_result,
            has_live_observation=has_obs,
            raw_payload_hash=station.raw_payload_hash,
            contract_version=station.contract_version,
        )
