"""ChargePlus — Canonical Deduplication Decision Layer & Source Merging.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.7 (Canonical Deduplication Decision Layer & Source Merging)

Evaluates cross-source entity-resolution evidence (Step 2.4), normalized representations (Step 2.5),
and data-quality validation classifications (Step 2.6) to produce deterministic, auditable
canonicalization decisions:
- MERGE: Multi-source new cluster unified into a canonical station candidate.
- LINK_TO_CANONICAL: One or more records resolve to an existing canonical station.
- KEEP_SEPARATE: Record represents an independent physical station.
- REVIEW: Ambiguity, multi-canonical conflict, or unresolvable field contradictions.

ARCHITECTURAL INVARIANTS:
1. One physical station = One ChargePlus canonical ID.
2. 2.7 DECIDES. 2.8 PERSISTS. Step 2.7 is strictly non-destructive (zero DB writes).
3. Source identity remains traceable: External source IDs are never overwritten.
4. Never invent source precedence: No universal "CPO > OCM > OSM" assumption.
5. Missing != Conflict: Omission in one source is not a contradiction with another.
6. Connectors are never blindly summed: Multiple sources describing the same plug are deduplicated.
7. Validation gating: REJECT records cannot merge; QUARANTINE cannot silently become canonical.
8. Transitive contradiction protection: Pairwise matches must not cause unsafe multi-source merges.
9. Deterministic & Idempotent: Zero datetime.now() drift, zero random numbers, pure logic.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

from backend.ingestion.constants import (
    CONTRACT_VERSION,
    OperationalStatus,
    PricingType,
    StandardConnectorType,
    ValidationOutcome,
)
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedObservationRecord,
    NormalizedStationRecord,
    ProvenanceInfo,
)
from backend.ingestion.resolution import (
    CrossSourceEntityResolver,
    EntityResolutionCandidate,
    EvidenceSignal,
    MatchState,
    haversine_distance_meters,
)
from backend.ingestion.validation import (
    DataQualityValidator,
    ValidationResult,
)


# ------------------------------------------------------------------------------
# Decision States & Enums
# ------------------------------------------------------------------------------

class CanonicalDecisionState(str, Enum):
    """Authoritative decision state for canonical deduplication."""
    MERGE = "MERGE"                          # Multiple new source records refer to the same physical station
    LINK_TO_CANONICAL = "LINK_TO_CANONICAL"  # Record(s) resolve to an already-established canonical station
    KEEP_SEPARATE = "KEEP_SEPARATE"          # Record represents a distinct, standalone physical station
    REVIEW = "REVIEW"                        # Ambiguity, contradiction, or conflict requiring human review


class SurvivorshipStrategy(str, Enum):
    """Categorical strategy applied to resolve a field value across sources."""
    UNANIMOUS_AGREEMENT = "UNANIMOUS_AGREEMENT"        # All reporting sources agree exactly
    SINGLE_REPORTING_SOURCE = "SINGLE_REPORTING_SOURCE"# Only one source reported the field (missing != conflict)
    HIGHEST_QUALITY_SCORE = "HIGHEST_QUALITY_SCORE"    # Selected from source with highest data-quality score
    MOST_COMPLETE_VALUE = "MOST_COMPLETE_VALUE"        # Selected most informative representation (e.g. longest name)
    EXPLICIT_FIELD_POLICY = "EXPLICIT_FIELD_POLICY"    # Resolved using an explicit, justified domain policy
    DEDUPLICATED_SET = "DEDUPLICATED_SET"              # Structured deduplication (e.g. connector specifications)
    CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"        # Material contradiction with no precedence; flagged for review


# ------------------------------------------------------------------------------
# Existing Canonical Station Reference Model
# ------------------------------------------------------------------------------

class ExistingCanonicalStation(BaseModel):
    """Reference representation of an existing canonical station established in operational DB."""
    canonical_station_id: str = Field(..., description="ChargePlus canonical station UUID")
    name: str
    operator_name: Optional[str] = None
    operator_slug: Optional[str] = None
    latitude: float
    longitude: float
    address_line: Optional[str] = None
    locality: Optional[str] = None
    postal_code: Optional[str] = None
    connectors: list[NormalizedConnectorRecord] = Field(default_factory=list)
    source_links: list[tuple[str, str]] = Field(default_factory=list, description="List of (source_id, source_station_id)")

    class Config:
        extra = "forbid"


# ------------------------------------------------------------------------------
# Field-Level Survivorship Decision Model
# ------------------------------------------------------------------------------

class FieldSurvivorshipDecision(BaseModel):
    """Structured decision explaining how a single canonical attribute survived across sources."""
    field_name: str
    canonical_value: Any = None
    contributing_source_id: Optional[str] = None
    contributing_source_station_id: Optional[str] = None
    participating_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Map of '{source_id}:{source_station_id}' -> observed value",
    )
    has_conflict: bool = False
    is_review_required: bool = False
    strategy_used: SurvivorshipStrategy
    explanation: str

    class Config:
        extra = "forbid"


# ------------------------------------------------------------------------------
# Canonical Deduplication Decision Model
# ------------------------------------------------------------------------------

class CanonicalResolutionDecision(BaseModel):
    """Authoritative Step 2.7 decision dossier for a candidate cluster of source records."""
    decision_state: CanonicalDecisionState
    cluster_id: str = Field(..., description="Deterministic cluster hash derived from participating sources")
    canonical_station_id: Optional[str] = Field(
        default=None,
        description="Target canonical station ID (existing UUID or None if new/unresolved)",
    )
    participating_source_identities: list[tuple[str, str]] = Field(
        default_factory=list,
        description="List of (source_id, source_station_id) pairs included in decision",
    )
    participating_records: list[NormalizedStationRecord] = Field(default_factory=list)
    validation_outcomes: dict[str, str] = Field(
        default_factory=dict,
        description="Map of '{source_id}:{source_station_id}' -> ValidationOutcome string",
    )
    pairwise_evidence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed evidence dossiers from Step 2.4 resolver for candidate pairs",
    )
    field_survivorship: dict[str, FieldSurvivorshipDecision] = Field(
        default_factory=dict,
        description="Field-by-field survivorship outcomes",
    )
    conflicts: list[str] = Field(default_factory=list, description="Material contradictions identified")
    reasons: list[str] = Field(default_factory=list, description="Primary reasons supporting final decision")
    blocking_reasons: list[str] = Field(default_factory=list, description="Fatal blocking issues if any")
    is_blocked: bool = False
    decision_version: str = Field(default=CONTRACT_VERSION)

    class Config:
        extra = "forbid"

    @property
    def is_merge(self) -> bool:
        return self.decision_state in (CanonicalDecisionState.MERGE, CanonicalDecisionState.LINK_TO_CANONICAL)

    @property
    def requires_review(self) -> bool:
        return self.decision_state == CanonicalDecisionState.REVIEW

    def to_dict(self) -> dict[str, Any]:
        """Converts decision to serializable dictionary."""
        return self.dict()


# ------------------------------------------------------------------------------
# Field Survivorship Policy Engine
# ------------------------------------------------------------------------------

class FieldSurvivorshipPolicy:
    """Deterministic, pure-function field survivorship evaluation.
    
    Guarantees:
    - Never uses arbitrary source ranking ("CPO > OCM > OSM" is forbidden).
    - Missing != Conflict: An omitted value in Source B never contradicts a valid value in Source A.
    - Connectors are never blindly summed.
    - Close coordinates (<= 50m) select highest-quality source deterministically; > 50m triggers REVIEW.
    """

    @classmethod
    def resolve_coordinates(
        cls,
        records: list[NormalizedStationRecord],
        quality_scores: dict[str, float],
    ) -> FieldSurvivorshipDecision:
        """Determines canonical coordinates without unexplained geographic averaging."""
        participating: dict[str, Any] = {}
        for r in records:
            key = f"{r.source_id}:{r.source_station_id}"
            participating[key] = (r.latitude, r.longitude)

        if not records:
            return FieldSurvivorshipDecision(
                field_name="coordinates",
                strategy_used=SurvivorshipStrategy.CONFLICT_UNRESOLVED,
                has_conflict=True,
                is_review_required=True,
                explanation="No records available to resolve coordinates",
            )

        if len(records) == 1:
            r = records[0]
            return FieldSurvivorshipDecision(
                field_name="coordinates",
                canonical_value=(r.latitude, r.longitude),
                contributing_source_id=r.source_id,
                contributing_source_station_id=r.source_station_id,
                participating_values=participating,
                has_conflict=False,
                is_review_required=False,
                strategy_used=SurvivorshipStrategy.SINGLE_REPORTING_SOURCE,
                explanation=f"Single source {r.source_id} provides coordinates ({r.latitude}, {r.longitude})",
            )

        # Check maximum pairwise distance across all records in cluster
        max_dist = 0.0
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                d = haversine_distance_meters(
                    records[i].latitude, records[i].longitude,
                    records[j].latitude, records[j].longitude,
                )
                if d > max_dist:
                    max_dist = d

        # Material coordinate conflict threshold (> 50 meters)
        if max_dist > 50.0:
            return FieldSurvivorshipDecision(
                field_name="coordinates",
                canonical_value=None,
                participating_values=participating,
                has_conflict=True,
                is_review_required=True,
                strategy_used=SurvivorshipStrategy.CONFLICT_UNRESOLVED,
                explanation=f"Material coordinate conflict: maximum spread of {max_dist:.1f}m exceeds 50m threshold",
            )

        # Identical coordinates across all reporting sources (< 1mm spread)
        if max_dist < 1e-3:
            r0 = records[0]
            return FieldSurvivorshipDecision(
                field_name="coordinates",
                canonical_value=(r0.latitude, r0.longitude),
                contributing_source_id=r0.source_id,
                contributing_source_station_id=r0.source_station_id,
                participating_values=participating,
                has_conflict=False,
                is_review_required=False,
                strategy_used=SurvivorshipStrategy.UNANIMOUS_AGREEMENT,
                explanation=f"All sources unanimously report identical coordinates ({r0.latitude}, {r0.longitude})",
            )

        # Close coordinates (<= 50m): Select deterministically based on highest quality score,
        # with stable lexicographical tiebreaker on source_id:source_station_id (no averaging)
        best_record = records[0]
        best_key = f"{best_record.source_id}:{best_record.source_station_id}"
        best_score = quality_scores.get(best_key, 0.0)

        for r in records[1:]:
            k = f"{r.source_id}:{r.source_station_id}"
            s = quality_scores.get(k, 0.0)
            if s > best_score:
                best_record = r
                best_key = k
                best_score = s
            elif abs(s - best_score) < 1e-6:
                # Deterministic tie-breaker: lexicographical sort on source identity
                if k < best_key:
                    best_record = r
                    best_key = k
                    best_score = s

        return FieldSurvivorshipDecision(
            field_name="coordinates",
            canonical_value=(best_record.latitude, best_record.longitude),
            contributing_source_id=best_record.source_id,
            contributing_source_station_id=best_record.source_station_id,
            participating_values=participating,
            has_conflict=False,
            is_review_required=False,
            strategy_used=SurvivorshipStrategy.HIGHEST_QUALITY_SCORE,
            explanation=f"Coordinates within {max_dist:.1f}m; selected from {best_record.source_id} (quality score {best_score:.2f}) without averaging",
        )

    @classmethod
    def resolve_name(
        cls,
        records: list[NormalizedStationRecord],
        quality_scores: dict[str, float],
    ) -> FieldSurvivorshipDecision:
        """Selects canonical station display name."""
        participating: dict[str, Any] = {}
        distinct_names: set[str] = set()

        for r in records:
            k = f"{r.source_id}:{r.source_station_id}"
            participating[k] = r.name
            if r.name:
                distinct_names.add(r.name.strip())

        if len(distinct_names) == 1:
            r = records[0]
            return FieldSurvivorshipDecision(
                field_name="name",
                canonical_value=r.name,
                contributing_source_id=r.source_id,
                contributing_source_station_id=r.source_station_id,
                participating_values=participating,
                has_conflict=False,
                is_review_required=False,
                strategy_used=SurvivorshipStrategy.UNANIMOUS_AGREEMENT,
                explanation=f"All sources unanimously report name '{r.name}'",
            )

        # Select the most complete/informative name (longest clean string with quality weighting)
        sorted_candidates = sorted(
            records,
            key=lambda x: (
                len(x.name.strip()),
                quality_scores.get(f"{x.source_id}:{x.source_station_id}", 0.0),
                x.source_id,
                x.source_station_id,
            ),
            reverse=True,
        )
        chosen = sorted_candidates[0]
        return FieldSurvivorshipDecision(
            field_name="name",
            canonical_value=chosen.name,
            contributing_source_id=chosen.source_id,
            contributing_source_station_id=chosen.source_station_id,
            participating_values=participating,
            has_conflict=False,
            is_review_required=False,
            strategy_used=SurvivorshipStrategy.MOST_COMPLETE_VALUE,
            explanation=f"Selected most informative name '{chosen.name}' from {chosen.source_id}",
        )

    @classmethod
    def resolve_operator(
        cls,
        records: list[NormalizedStationRecord],
    ) -> FieldSurvivorshipDecision:
        """Resolves commercial operator identity respecting aliases, recency, and provenance."""
        participating: dict[str, Any] = {}
        ops_present: list[tuple[NormalizedStationRecord, str, Optional[str]]] = []

        for r in records:
            k = f"{r.source_id}:{r.source_station_id}"
            participating[k] = {
                "name": r.operator_name,
                "slug": r.operator_slug,
                "extra": r.extra_metadata.get("_temporal_recency_ts") if r.extra_metadata else None,
            }
            if r.operator_name or r.operator_slug:
                ops_present.append((r, r.operator_name or "Unknown", r.operator_slug))

        # Missing in all sources
        if not ops_present:
            return FieldSurvivorshipDecision(
                field_name="operator",
                canonical_value=None,
                participating_values=participating,
                has_conflict=False,
                is_review_required=False,
                strategy_used=SurvivorshipStrategy.SINGLE_REPORTING_SOURCE,
                explanation="No source reported operator identity; operator remains unknown",
            )

        # Single reporting source
        if len(ops_present) == 1:
            rec, op_name, op_slug = ops_present[0]
            return FieldSurvivorshipDecision(
                field_name="operator",
                canonical_value={"name": op_name, "slug": op_slug},
                contributing_source_id=rec.source_id,
                contributing_source_station_id=rec.source_station_id,
                participating_values=participating,
                has_conflict=False,
                is_review_required=False,
                strategy_used=SurvivorshipStrategy.SINGLE_REPORTING_SOURCE,
                explanation=f"Operator '{op_name}' reported solely by {rec.source_id} (missing != conflict)",
            )

        # Check if all reporting sources agree on normalized slug
        slugs = {op_slug for _, _, op_slug in ops_present if op_slug}
        if len(slugs) == 1:
            # Pick the most complete/descriptive operator display name
            sorted_by_name = sorted(ops_present, key=lambda x: (len(x[1]), x[0].source_id), reverse=True)
            rec, op_name, op_slug = sorted_by_name[0]
            return FieldSurvivorshipDecision(
                field_name="operator",
                canonical_value={"name": op_name, "slug": op_slug},
                contributing_source_id=rec.source_id,
                contributing_source_station_id=rec.source_station_id,
                participating_values=participating,
                has_conflict=False,
                is_review_required=False,
                strategy_used=SurvivorshipStrategy.UNANIMOUS_AGREEMENT,
                explanation=f"Operator agreed across all reporting sources: '{op_name}' (slug '{op_slug}')",
            )

        # Rebranding / Operator change: Check if temporal recency distinguishes them
        # (e.g. metadata indicates a newer retrieval or timestamp)
        records_with_ts = [
            (r, op_name, op_slug, r.extra_metadata.get("_temporal_recency_ts", 0))
            for r, op_name, op_slug in ops_present
            if r.extra_metadata and r.extra_metadata.get("_temporal_recency_ts")
        ]
        if len(records_with_ts) == len(ops_present) and len(records_with_ts) >= 2:
            # Sort by timestamp descending
            records_with_ts.sort(key=lambda x: x[3], reverse=True)
            latest_rec, latest_name, latest_slug, _ = records_with_ts[0]
            return FieldSurvivorshipDecision(
                field_name="operator",
                canonical_value={"name": latest_name, "slug": latest_slug},
                contributing_source_id=latest_rec.source_id,
                contributing_source_station_id=latest_rec.source_station_id,
                participating_values=participating,
                has_conflict=False,
                is_review_required=False,
                strategy_used=SurvivorshipStrategy.EXPLICIT_FIELD_POLICY,
                explanation=f"Operator change reconciled: resolved to latest operator '{latest_name}' based on recency (historical provenance retained)",
            )

        # Conflicting operators across reporting sources without recency policy
        return FieldSurvivorshipDecision(
            field_name="operator",
            canonical_value=None,
            participating_values=participating,
            has_conflict=True,
            is_review_required=True,
            strategy_used=SurvivorshipStrategy.CONFLICT_UNRESOLVED,
            explanation=f"Conflicting operator identities reported across sources: {sorted(list(slugs))}",
        )

    @classmethod
    def resolve_pricing(
        cls,
        records: list[NormalizedStationRecord],
    ) -> FieldSurvivorshipDecision:
        """Resolves pricing semantics honestly without inventing ₹0."""
        participating: dict[str, Any] = {}
        pricing_data: list[tuple[NormalizedStationRecord, PricingType, Optional[float], Optional[float]]] = []

        for r in records:
            k = f"{r.source_id}:{r.source_station_id}"
            first_c = r.connectors[0] if r.connectors else None
            p_type = first_c.pricing_type if first_c else PricingType.UNKNOWN
            p_kwh = first_c.price_per_kwh if first_c else None
            p_session = first_c.price_per_session if first_c else None
            participating[k] = {
                "pricing_type": p_type.value if hasattr(p_type, "value") else str(p_type),
                "price_per_kwh": p_kwh,
                "price_per_session": p_session,
            }
            if p_type != PricingType.UNKNOWN or p_kwh is not None:
                pricing_data.append((r, p_type, p_kwh, p_session))

        # All unknown / missing
        if not pricing_data:
            return FieldSurvivorshipDecision(
                field_name="pricing",
                canonical_value={"pricing_type": PricingType.UNKNOWN.value, "price_per_kwh": None},
                participating_values=participating,
                has_conflict=False,
                is_review_required=False,
                strategy_used=SurvivorshipStrategy.SINGLE_REPORTING_SOURCE,
                explanation="No source reported pricing; tariff remains unknown (never assumed free)",
            )

        # Single reporting source
        if len(pricing_data) == 1:
            rec, p_type, p_kwh, p_session = pricing_data[0]
            return FieldSurvivorshipDecision(
                field_name="pricing",
                canonical_value={"pricing_type": p_type.value, "price_per_kwh": p_kwh, "price_per_session": p_session},
                contributing_source_id=rec.source_id,
                contributing_source_station_id=rec.source_station_id,
                participating_values=participating,
                has_conflict=False,
                is_review_required=False,
                strategy_used=SurvivorshipStrategy.SINGLE_REPORTING_SOURCE,
                explanation=f"Pricing reported solely by {rec.source_id} (missing in other sources is not a conflict)",
            )

        # Multiple reporting sources: Check for contradictions
        types = {p[1] for p in pricing_data}
        rates = {p[2] for p in pricing_data if p[2] is not None}

        # Contradiction: One says FREE, another says PAID
        if PricingType.FREE in types and PricingType.PAID in types:
            return FieldSurvivorshipDecision(
                field_name="pricing",
                canonical_value=None,
                participating_values=participating,
                has_conflict=True,
                is_review_required=True,
                strategy_used=SurvivorshipStrategy.CONFLICT_UNRESOLVED,
                explanation="Material pricing conflict: one source reports FREE charging while another reports PAID",
            )

        # Contradiction: Multiple differing paid rates
        if len(rates) > 1:
            return FieldSurvivorshipDecision(
                field_name="pricing",
                canonical_value=None,
                participating_values=participating,
                has_conflict=True,
                is_review_required=True,
                strategy_used=SurvivorshipStrategy.CONFLICT_UNRESOLVED,
                explanation=f"Material tariff conflict: differing price_per_kwh rates reported ({sorted(list(rates))}) with no precedence policy",
            )

        # Consistent pricing across reporting sources
        rec, p_type, p_kwh, p_session = pricing_data[0]
        strategy = (
            SurvivorshipStrategy.EXPLICIT_FIELD_POLICY
            if p_type == PricingType.FREE
            else SurvivorshipStrategy.UNANIMOUS_AGREEMENT
        )
        return FieldSurvivorshipDecision(
            field_name="pricing",
            canonical_value={"pricing_type": p_type.value, "price_per_kwh": p_kwh, "price_per_session": p_session},
            contributing_source_id=rec.source_id,
            contributing_source_station_id=rec.source_station_id,
            participating_values=participating,
            has_conflict=False,
            is_review_required=False,
            strategy_used=strategy,
            explanation=f"Pricing agreed across reporting sources: {p_type.value}, {p_kwh} INR/kWh",
        )

    @classmethod
    def resolve_connectors(
        cls,
        records: list[NormalizedStationRecord],
    ) -> FieldSurvivorshipDecision:
        """Deduplicates connectors without double-counting quantities across sources,
        while preventing undercounting of multiple distinct connectors within sources.
        
        Principles:
        1. Intra-Source Summation: Within each source record, distinct connector entries of the
           same specification (connector_type, power_bucket) are summed to obtain that source's
           reported total plug count for that specification.
        2. Cross-Source Reconciliation: Across different sources describing the same station,
           the canonical quantity for each specification is the maximum reported by any source:
           canonical_qty = max(source_total for source in records).
           This prevents double-counting overlapping descriptions while never undercounting verified inventory.
        3. Multi-Tier Co-existence: A station having multiple distinct power tiers of the same
           connector type (e.g. 60 kW and 120 kW CCS2) is valid co-located equipment, not a conflict.
        4. Incompatible Signatures: Disjoint connector types across sources that each claim to describe
           the entire site, or single-tier stations where sources contradict on power (e.g. 30 kW vs 350 kW),
           trigger review.
        """
        participating: dict[str, Any] = {}
        for r in records:
            k = f"{r.source_id}:{r.source_station_id}"
            participating[k] = [
                {
                    "connector_id": c.source_connector_id,
                    "type": c.connector_type,
                    "power_kw": c.power_kw,
                    "voltage_v": c.voltage_v,
                    "amperage_a": c.amperage_a,
                    "qty": c.quantity,
                }
                for c in r.connectors
            ]

        if not records:
            return FieldSurvivorshipDecision(
                field_name="connectors",
                canonical_value=[],
                strategy_used=SurvivorshipStrategy.SINGLE_REPORTING_SOURCE,
                explanation="No records to resolve connectors",
            )

        if len(records) == 1:
            r = records[0]
            # Aggregate within the single record by specification to preserve total quantity
            single_grouped: dict[tuple[str, Optional[float]], NormalizedConnectorRecord] = {}
            for c in r.connectors:
                p_bucket = round(c.power_kw, 0) if c.power_kw is not None else None
                key = (c.connector_type, p_bucket)
                if key not in single_grouped:
                    single_grouped[key] = copy.deepcopy(c)
                else:
                    existing = single_grouped[key]
                    existing.quantity += c.quantity
                    if existing.voltage_v is None and c.voltage_v is not None:
                        existing.voltage_v = c.voltage_v
                    if existing.amperage_a is None and c.amperage_a is not None:
                        existing.amperage_a = c.amperage_a

            resolved_single = list(single_grouped.values())
            return FieldSurvivorshipDecision(
                field_name="connectors",
                canonical_value=[c.dict() for c in resolved_single],
                contributing_source_id=r.source_id,
                contributing_source_station_id=r.source_station_id,
                participating_values=participating,
                has_conflict=False,
                is_review_required=False,
                strategy_used=SurvivorshipStrategy.SINGLE_REPORTING_SOURCE,
                explanation=f"Single source {r.source_id} reports {len(resolved_single)} connector specification(s) with total quantity {sum(c.quantity for c in resolved_single)}",
            )

        # Multi-record evaluation
        # 1. Check for completely incompatible connector types (disjoint explicit types)
        record_type_sets: list[set[str]] = [
            {c.connector_type for c in r.connectors if c.connector_type != "Other"}
            for r in records
            if r.connectors
        ]
        if len(record_type_sets) >= 2:
            common_types = set.intersection(*record_type_sets)
            if not common_types and all(len(s) > 0 for s in record_type_sets):
                return FieldSurvivorshipDecision(
                    field_name="connectors",
                    canonical_value=None,
                    participating_values=participating,
                    has_conflict=True,
                    is_review_required=True,
                    strategy_used=SurvivorshipStrategy.CONFLICT_UNRESOLVED,
                    explanation=f"Incompatible connector evidence: sources report completely disjoint connector types ({[sorted(list(s)) for s in record_type_sets]})",
                )

        # 2. Check for single-tier power contradiction between sources:
        # A conflict occurs when two sources each describe only a single power tier
        # for a connector type, but those power ratings contradict materially (e.g. 30 kW vs 350 kW).
        # Multi-tier co-existence (e.g. a site having both 60 kW and 120 kW chargers) is legitimate.
        for c_type in set.union(*record_type_sets) if record_type_sets else set():
            source_powers: list[set[float]] = []
            for r in records:
                p_set = {
                    c.power_kw
                    for c in r.connectors
                    if c.connector_type == c_type and c.power_kw is not None
                }
                if p_set:
                    source_powers.append(p_set)

            if len(source_powers) >= 2:
                # Only flag contradiction if every source claims only a single power tier and they differ significantly
                if all(len(s) == 1 for s in source_powers):
                    p1 = list(source_powers[0])[0]
                    p2 = list(source_powers[1])[0]
                    if abs(p1 - p2) > 20.0 and (max(p1, p2) / max(min(p1, p2), 1.0)) > 1.8:
                        return FieldSurvivorshipDecision(
                            field_name="connectors",
                            canonical_value=None,
                            participating_values=participating,
                            has_conflict=True,
                            is_review_required=True,
                            strategy_used=SurvivorshipStrategy.CONFLICT_UNRESOLVED,
                            explanation=f"Incompatible connector evidence: conflicting single-tier power ratings for {c_type} ({min(p1, p2)} kW vs {max(p1, p2)} kW)",
                        )

        # 3. Two-Level Reconciled Survivorship:
        # Level 1: Intra-source summation: calculate total quantity per specification within each source
        # Level 2: Cross-source survivorship: canonical quantity = max(reported_quantity across sources)
        all_specs: set[tuple[str, Optional[float]]] = set()
        source_totals: dict[str, dict[tuple[str, Optional[float]], int]] = {}
        spec_templates: dict[tuple[str, Optional[float]], NormalizedConnectorRecord] = {}

        for r in records:
            r_key = f"{r.source_id}:{r.source_station_id}"
            source_totals[r_key] = {}
            for c in r.connectors:
                p_bucket = round(c.power_kw, 0) if c.power_kw is not None else None
                key = (c.connector_type, p_bucket)
                all_specs.add(key)

                # Sum quantities of distinct connector records within the same source
                source_totals[r_key][key] = source_totals[r_key].get(key, 0) + c.quantity

                # Keep best template connector record for electrical and pricing details
                if key not in spec_templates:
                    spec_templates[key] = copy.deepcopy(c)
                else:
                    tmpl = spec_templates[key]
                    if tmpl.voltage_v is None and c.voltage_v is not None:
                        tmpl.voltage_v = c.voltage_v
                    if tmpl.amperage_a is None and c.amperage_a is not None:
                        tmpl.amperage_a = c.amperage_a
                    if tmpl.charging_standard is None and c.charging_standard is not None:
                        tmpl.charging_standard = c.charging_standard

        resolved_list: list[NormalizedConnectorRecord] = []
        for key in sorted(all_specs, key=lambda x: (x[0], x[1] if x[1] is not None else -1)):
            max_qty = max(source_totals[r_key].get(key, 0) for r_key in source_totals)
            canonical_conn = copy.deepcopy(spec_templates[key])
            canonical_conn.quantity = max_qty
            canonical_conn.is_aggregated = (max_qty > 1)
            if max_qty > 1:
                canonical_conn.source_connector_id = None
            resolved_list.append(canonical_conn)

        return FieldSurvivorshipDecision(
            field_name="connectors",
            canonical_value=[c.dict() for c in resolved_list],
            participating_values=participating,
            has_conflict=False,
            is_review_required=False,
            strategy_used=SurvivorshipStrategy.DEDUPLICATED_SET,
            explanation=f"Deduplicated {len(resolved_list)} unique connector specification(s) with total quantity {sum(c.quantity for c in resolved_list)}; intra-source distinct plugs preserved, cross-source overlapping descriptions reconciled without double-counting",
        )


# ------------------------------------------------------------------------------
# Canonical Deduplication Decision Engine
# ------------------------------------------------------------------------------

class CanonicalDeduplicationEngine:
    """Deterministic, stateless decision engine implementing ChargePlus Step 2.7.
    
    Transforms entity resolution evidence, normalized fields, and data-quality outcomes
    into authoritative canonical deduplication decisions.
    """

    @classmethod
    def generate_cluster_id(cls, source_identities: list[tuple[str, str]]) -> str:
        """Derives a stable, deterministic cluster identifier from sorted source identities."""
        sorted_keys = sorted([f"{s_id}:{s_stn_id}" for s_id, s_stn_id in source_identities])
        digest = hashlib.sha256(";".join(sorted_keys).encode("utf-8")).hexdigest()[:16]
        return f"cluster_{digest}"

    @classmethod
    def evaluate_records(
        cls,
        records: list[NormalizedStationRecord],
        existing_canonical_stations: Optional[list[ExistingCanonicalStation]] = None,
        validation_results: Optional[dict[tuple[str, str], ValidationResult]] = None,
    ) -> list[CanonicalResolutionDecision]:
        """Main entry point: Generates deterministic canonical decisions for incoming records."""
        if not records:
            return []

        # 1. Deterministic sort of input records to ensure input-order independence
        sorted_records = sorted(records, key=lambda r: (r.source_id, r.source_station_id))

        # 2. Collect or compute ValidationResults for all records
        val_map: dict[tuple[str, str], ValidationResult] = {}
        for r in sorted_records:
            ident = (r.source_id, r.source_station_id)
            if validation_results and ident in validation_results:
                val_map[ident] = validation_results[ident]
            else:
                val_map[ident] = DataQualityValidator.validate_record(r)

        # 3. Gating check: Separate fatally rejected records from merge candidates
        decisions: list[CanonicalResolutionDecision] = []
        eligible_records: list[NormalizedStationRecord] = []

        for r in sorted_records:
            ident = (r.source_id, r.source_station_id)
            val = val_map[ident]

            if val.outcome == ValidationOutcome.REJECT:
                # Fatal rejection: Cannot participate in canonical merging
                cluster_id = cls.generate_cluster_id([ident])
                decisions.append(
                    CanonicalResolutionDecision(
                        decision_state=CanonicalDecisionState.KEEP_SEPARATE,
                        cluster_id=cluster_id,
                        canonical_station_id=None,
                        participating_source_identities=[ident],
                        participating_records=[r],
                        validation_outcomes={f"{r.source_id}:{r.source_station_id}": val.outcome.value},
                        pairwise_evidence=[],
                        field_survivorship={},
                        conflicts=list(val.errors),
                        reasons=["Record rejected by Step 2.6 data quality validator; excluded from canonical merging"],
                        blocking_reasons=list(val.errors),
                        is_blocked=True,
                    )
                )
            else:
                eligible_records.append(r)

        if not eligible_records:
            return decisions

        # 4. Compute pairwise resolution evidence across eligible records
        resolver = CrossSourceEntityResolver()
        pairwise_map: dict[frozenset[tuple[str, str]], EntityResolutionCandidate] = {}
        for i in range(len(eligible_records)):
            for j in range(i + 1, len(eligible_records)):
                rec_i = eligible_records[i]
                rec_j = eligible_records[j]
                cand = resolver.evaluate_pair(rec_i, rec_j)
                key = frozenset([(rec_i.source_id, rec_i.source_station_id), (rec_j.source_id, rec_j.source_station_id)])
                pairwise_map[key] = cand

        # 5. Form candidate clusters using MATCH or AMBIGUOUS pairs
        # (Ambiguous pairs must be evaluated together and flagged for REVIEW, not silently kept separate)
        clusters: list[list[NormalizedStationRecord]] = cls._build_candidate_clusters(
            eligible_records, pairwise_map
        )

        # 6. Evaluate each cluster for multi-source contradictions and survivorship
        for cluster in clusters:
            decision = cls._evaluate_cluster(
                cluster=cluster,
                pairwise_map=pairwise_map,
                validation_map=val_map,
                existing_canonical_stations=existing_canonical_stations,
            )
            decisions.append(decision)

        # Deterministic sort of output decisions by cluster_id
        decisions.sort(key=lambda d: d.cluster_id)
        return decisions

    @classmethod
    def _build_candidate_clusters(
        cls,
        records: list[NormalizedStationRecord],
        pairwise_map: dict[frozenset[tuple[str, str]], EntityResolutionCandidate],
    ) -> list[list[NormalizedStationRecord]]:
        """Groups records that have candidate relationships (MATCH or AMBIGUOUS)."""
        record_map = {(r.source_id, r.source_station_id): r for r in records}
        visited: set[tuple[str, str]] = set()
        clusters: list[list[NormalizedStationRecord]] = []

        # Graph adjacency list for candidate pairs
        adj: dict[tuple[str, str], set[tuple[str, str]]] = {
            (r.source_id, r.source_station_id): set() for r in records
        }

        for (id_a, id_b), cand in pairwise_map.items():
            if cand.match_state in (MatchState.MATCH, MatchState.AMBIGUOUS):
                adj[id_a].add(id_b)
                adj[id_b].add(id_a)

        # Deterministic connected components
        for r in records:
            ident = (r.source_id, r.source_station_id)
            if ident in visited:
                continue

            # BFS traversal
            current_cluster: list[NormalizedStationRecord] = []
            queue = [ident]
            visited.add(ident)

            while queue:
                curr = queue.pop(0)
                current_cluster.append(record_map[curr])
                for neighbor in sorted(adj[curr]):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            # Sort records in cluster deterministically
            current_cluster.sort(key=lambda x: (x.source_id, x.source_station_id))
            clusters.append(current_cluster)

        return clusters

    @classmethod
    def _find_matching_canonical_stations(
        cls,
        record: NormalizedStationRecord,
        canonical_pool: Optional[list[ExistingCanonicalStation]],
    ) -> list[ExistingCanonicalStation]:
        """Finds all established canonical stations matching a normalized record."""
        if not canonical_pool:
            return []

        matched: list[ExistingCanonicalStation] = []

        # 1. Exact external source link match
        for canon in canonical_pool:
            for s_id, s_stn_id in canon.source_links:
                if s_id == record.source_id and s_stn_id == record.source_station_id:
                    if canon not in matched:
                        matched.append(canon)

        # 2. Strict spatial proximity and name alignment
        for canon in canonical_pool:
            if canon in matched:
                continue
            dist = haversine_distance_meters(
                record.latitude, record.longitude,
                canon.latitude, canon.longitude,
            )
            # Ultra-close (< 15 meters) with operator or name concordance
            if dist <= 15.0:
                name_a = record.name.lower().strip()
                name_b = canon.name.lower().strip()
                if name_a in name_b or name_b in name_a or dist <= 5.0:
                    matched.append(canon)

        return matched

    @classmethod
    def _evaluate_cluster(
        cls,
        cluster: list[NormalizedStationRecord],
        pairwise_map: dict[frozenset[tuple[str, str]], EntityResolutionCandidate],
        validation_map: dict[tuple[str, str], ValidationResult],
        existing_canonical_stations: Optional[list[ExistingCanonicalStation]] = None,
    ) -> CanonicalResolutionDecision:
        """Evaluates a candidate cluster for transitive consistency, existing links, and survivorship."""
        source_idents = [(r.source_id, r.source_station_id) for r in cluster]
        cluster_id = cls.generate_cluster_id(source_idents)

        val_outcomes = {
            f"{r.source_id}:{r.source_station_id}": validation_map[(r.source_id, r.source_station_id)].outcome.value
            for r in cluster
        }
        quality_scores = {
            f"{r.source_id}:{r.source_station_id}": validation_map[(r.source_id, r.source_station_id)].quality_score
            for r in cluster
        }

        # Collect pairwise evidence for this cluster
        cluster_pairwise: list[dict[str, Any]] = []
        for i in range(len(cluster)):
            for j in range(i + 1, len(cluster)):
                pair_key = frozenset([
                    (cluster[i].source_id, cluster[i].source_station_id),
                    (cluster[j].source_id, cluster[j].source_station_id),
                ])
                if pair_key in pairwise_map:
                    cluster_pairwise.append(pairwise_map[pair_key].to_dict())

        # GATING: Check for QUARANTINE records in cluster (cannot silently become canonical)
        quarantine_sources = [
            f"{r.source_id}:{r.source_station_id}"
            for r in cluster
            if validation_map[(r.source_id, r.source_station_id)].outcome == ValidationOutcome.QUARANTINE
        ]
        if quarantine_sources:
            return CanonicalResolutionDecision(
                decision_state=CanonicalDecisionState.REVIEW,
                cluster_id=cluster_id,
                canonical_station_id=None,
                participating_source_identities=source_idents,
                participating_records=cluster,
                validation_outcomes=val_outcomes,
                pairwise_evidence=cluster_pairwise,
                field_survivorship={},
                conflicts=[f"Cluster contains quarantined records ({quarantine_sources}) that cannot automatically merge or become canonical"],
                reasons=["Quarantined records cannot silently become canonical operational data; operator review required"],
                blocking_reasons=[f"Quarantined records present: {quarantine_sources}"],
                is_blocked=True,
            )

        # CASE 1: Standalone Single Record
        if len(cluster) == 1:
            r = cluster[0]
            matched_canons = cls._find_matching_canonical_stations(r, existing_canonical_stations)

            if len(matched_canons) == 1:
                linked_canon = matched_canons[0]
                return CanonicalResolutionDecision(
                    decision_state=CanonicalDecisionState.LINK_TO_CANONICAL,
                    cluster_id=cluster_id,
                    canonical_station_id=linked_canon.canonical_station_id,
                    participating_source_identities=source_idents,
                    participating_records=cluster,
                    validation_outcomes=val_outcomes,
                    pairwise_evidence=cluster_pairwise,
                    field_survivorship={
                        "coordinates": FieldSurvivorshipPolicy.resolve_coordinates(cluster, quality_scores),
                        "name": FieldSurvivorshipPolicy.resolve_name(cluster, quality_scores),
                        "operator": FieldSurvivorshipPolicy.resolve_operator(cluster),
                        "pricing": FieldSurvivorshipPolicy.resolve_pricing(cluster),
                        "connectors": FieldSurvivorshipPolicy.resolve_connectors(cluster),
                    },
                    conflicts=[],
                    reasons=[f"Record '{r.source_station_id}' matches established canonical station '{linked_canon.canonical_station_id}'"],
                    blocking_reasons=[],
                    is_blocked=False,
                )

            if len(matched_canons) > 1:
                canon_ids = [c.canonical_station_id for c in matched_canons]
                return CanonicalResolutionDecision(
                    decision_state=CanonicalDecisionState.REVIEW,
                    cluster_id=cluster_id,
                    canonical_station_id=None,
                    participating_source_identities=source_idents,
                    participating_records=cluster,
                    validation_outcomes=val_outcomes,
                    pairwise_evidence=cluster_pairwise,
                    field_survivorship={},
                    conflicts=[f"Record matches multiple existing canonical stations: {canon_ids}"],
                    reasons=["Record is ambiguous between multiple established canonical stations; automated link is unsafe"],
                    blocking_reasons=[f"Ambiguous canonical link between {canon_ids}"],
                    is_blocked=False,
                )

            # Independent distinct station
            return CanonicalResolutionDecision(
                decision_state=CanonicalDecisionState.KEEP_SEPARATE,
                cluster_id=cluster_id,
                canonical_station_id=None,
                participating_source_identities=source_idents,
                participating_records=cluster,
                validation_outcomes=val_outcomes,
                pairwise_evidence=cluster_pairwise,
                field_survivorship={
                    "coordinates": FieldSurvivorshipPolicy.resolve_coordinates(cluster, quality_scores),
                    "name": FieldSurvivorshipPolicy.resolve_name(cluster, quality_scores),
                    "operator": FieldSurvivorshipPolicy.resolve_operator(cluster),
                    "pricing": FieldSurvivorshipPolicy.resolve_pricing(cluster),
                    "connectors": FieldSurvivorshipPolicy.resolve_connectors(cluster),
                },
                conflicts=[],
                reasons=[f"Single source record '{r.source_station_id}' from '{r.source_id}' stands alone as a distinct physical station"],
                blocking_reasons=[],
                is_blocked=False,
            )

        # CASE 2: Multi-Record Cluster (>= 2 records)
        # ----------------------------------------------------------------------
        # Transitive Contradiction & Ambiguity Check (Cluster Consistency)
        # ----------------------------------------------------------------------
        contradictions: list[str] = []
        ambiguities: list[str] = []

        for i in range(len(cluster)):
            for j in range(i + 1, len(cluster)):
                rec_i = cluster[i]
                rec_j = cluster[j]
                pair_key = frozenset([
                    (rec_i.source_id, rec_i.source_station_id),
                    (rec_j.source_id, rec_j.source_station_id),
                ])
                cand = pairwise_map.get(pair_key)

                if cand is None:
                    dist = haversine_distance_meters(rec_i.latitude, rec_i.longitude, rec_j.latitude, rec_j.longitude)
                    contradictions.append(
                        f"Pair ({rec_i.source_id}:{rec_i.source_station_id} <-> {rec_j.source_id}:{rec_j.source_station_id}) "
                        f"was not evaluated (distance: {dist:.1f}m)"
                    )
                elif cand.match_state == MatchState.AMBIGUOUS:
                    ambiguities.append(
                        f"Pair ({rec_i.source_id}:{rec_i.source_station_id} <-> {rec_j.source_id}:{rec_j.source_station_id}) "
                        f"has ambiguous match state (confidence: {cand.overall_confidence:.2f})"
                    )
                elif cand.match_state == MatchState.NON_MATCH:
                    dist = haversine_distance_meters(rec_i.latitude, rec_i.longitude, rec_j.latitude, rec_j.longitude)
                    contradictions.append(
                        f"Pair ({rec_i.source_id}:{rec_i.source_station_id} <-> {rec_j.source_id}:{rec_j.source_station_id}) "
                        f"is non-match (distance: {dist:.1f}m)"
                    )

        if ambiguities:
            return CanonicalResolutionDecision(
                decision_state=CanonicalDecisionState.REVIEW,
                cluster_id=cluster_id,
                canonical_station_id=None,
                participating_source_identities=source_idents,
                participating_records=cluster,
                validation_outcomes=val_outcomes,
                pairwise_evidence=cluster_pairwise,
                field_survivorship={},
                conflicts=ambiguities,
                reasons=["Ambiguous identity resolution evidence between participating records; manual review required"],
                blocking_reasons=ambiguities,
                is_blocked=False,
            )

        if contradictions:
            return CanonicalResolutionDecision(
                decision_state=CanonicalDecisionState.REVIEW,
                cluster_id=cluster_id,
                canonical_station_id=None,
                participating_source_identities=source_idents,
                participating_records=cluster,
                validation_outcomes=val_outcomes,
                pairwise_evidence=cluster_pairwise,
                field_survivorship={},
                conflicts=contradictions,
                reasons=["Transitive contradiction detected across proposed cluster; automated merge is unsafe"],
                blocking_reasons=contradictions,
                is_blocked=False,
            )

        # ----------------------------------------------------------------------
        # Existing Canonical Reconciliation
        # ----------------------------------------------------------------------
        all_linked_canons: list[ExistingCanonicalStation] = []
        for r in cluster:
            canons = cls._find_matching_canonical_stations(r, existing_canonical_stations)
            for c in canons:
                if c.canonical_station_id not in [x.canonical_station_id for x in all_linked_canons]:
                    all_linked_canons.append(c)

        # Case: Cluster matches multiple different existing canonical stations -> REVIEW!
        if len(all_linked_canons) > 1:
            canon_ids = [c.canonical_station_id for c in all_linked_canons]
            return CanonicalResolutionDecision(
                decision_state=CanonicalDecisionState.REVIEW,
                cluster_id=cluster_id,
                canonical_station_id=None,
                participating_source_identities=source_idents,
                participating_records=cluster,
                validation_outcomes=val_outcomes,
                pairwise_evidence=cluster_pairwise,
                field_survivorship={},
                conflicts=[f"Cluster bridges multiple established canonical stations: {canon_ids}"],
                reasons=["Collapsing multiple existing canonical stations is a high-risk operation requiring review"],
                blocking_reasons=[f"Multiple existing canonical stations linked: {canon_ids}"],
                is_blocked=False,
            )

        # ----------------------------------------------------------------------
        # Field-Level Survivorship Computation
        # ----------------------------------------------------------------------
        coord_decision = FieldSurvivorshipPolicy.resolve_coordinates(cluster, quality_scores)
        name_decision = FieldSurvivorshipPolicy.resolve_name(cluster, quality_scores)
        op_decision = FieldSurvivorshipPolicy.resolve_operator(cluster)
        pricing_decision = FieldSurvivorshipPolicy.resolve_pricing(cluster)
        conn_decision = FieldSurvivorshipPolicy.resolve_connectors(cluster)

        field_survivorship = {
            "coordinates": coord_decision,
            "name": name_decision,
            "operator": op_decision,
            "pricing": pricing_decision,
            "connectors": conn_decision,
        }

        # Collect field-level conflicts requiring review
        unresolved_field_conflicts = [
            f"{d.field_name}: {d.explanation}"
            for d in field_survivorship.values()
            if d.is_review_required
        ]

        if unresolved_field_conflicts:
            return CanonicalResolutionDecision(
                decision_state=CanonicalDecisionState.REVIEW,
                cluster_id=cluster_id,
                canonical_station_id=all_linked_canons[0].canonical_station_id if all_linked_canons else None,
                participating_source_identities=source_idents,
                participating_records=cluster,
                validation_outcomes=val_outcomes,
                pairwise_evidence=cluster_pairwise,
                field_survivorship=field_survivorship,
                conflicts=unresolved_field_conflicts,
                reasons=["Field-level survivorship contradictions detected with no established precedence rule"],
                blocking_reasons=unresolved_field_conflicts,
                is_blocked=False,
            )

        # Clean successful merge or link to canonical
        final_state = (
            CanonicalDecisionState.LINK_TO_CANONICAL
            if all_linked_canons
            else CanonicalDecisionState.MERGE
        )
        target_canon_id = all_linked_canons[0].canonical_station_id if all_linked_canons else None

        return CanonicalResolutionDecision(
            decision_state=final_state,
            cluster_id=cluster_id,
            canonical_station_id=target_canon_id,
            participating_source_identities=source_idents,
            participating_records=cluster,
            validation_outcomes=val_outcomes,
            pairwise_evidence=cluster_pairwise,
            field_survivorship=field_survivorship,
            conflicts=[],
            reasons=[
                f"Cluster of {len(cluster)} records shows unanimous concordance across spatial, lexical, and electrical dimensions",
                "Field survivorship resolved cleanly without unverified source precedence",
            ],
            blocking_reasons=[],
            is_blocked=False,
        )
