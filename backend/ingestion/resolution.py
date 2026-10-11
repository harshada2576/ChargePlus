"""ChargePlus — Cross-Source Entity Resolution Engine.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.4 (Cross-Source Entity Resolution — Candidate Generation & Evidence Fusion)

Determines whether station records from different legitimate external sources
(e.g., OpenChargeMap, OpenStreetMap, government registries, CPO feeds) COULD refer
to the same physical EV charging station.

ARCHITECTURAL PRINCIPLES (Step 2.4 Boundary):
1. EVIDENCE GENERATION ONLY:
   Step 2.4 computes and structures evidence across spatial, lexical, organizational,
   and electrical dimensions. It does NOT merge canonical records, mutate public.stations,
   or decide authoritative survivorship (deferred to Step 2.7).
2. MULTI-SIGNAL EVIDENCE FUSION:
   Proximity alone does NOT prove identity. Identity decisions require multi-signal concordance.
3. THREE-VALUED MATCH STATES:
   Outcomes are explicitly MATCH, NON_MATCH, or AMBIGUOUS. Ambiguity is preserved, never forced.
4. "MISSING != DISAGREEMENT":
   Missing attributes (e.g. unknown operator or missing connector count) are scored as UNKNOWN,
   never penalizing a candidate as a negative mismatch.
5. DETERMINISM & PURITY:
   Pure computational layer. Zero random thresholds, zero external network calls, zero LLMs.
   100% deterministic given identical inputs and configuration.
6. SOURCE IDENTITY INDEPENDENCE:
   External source identifiers remain intact throughout evidence evaluation and are never
   overwritten with ChargePlus canonical station UUIDs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any, Optional, Sequence
import unicodedata

from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedStationRecord,
)

# Mean Earth radius in meters (WGS 84 mean spherical radius)
EARTH_RADIUS_METERS = 6371000.0

# Regex for word tokenization
TOKEN_SPLIT_REGEX = re.compile(r"[\s\-_/,.:;()\[\]{}]+")

# Common charging stop words that provide low distinguishing value
COMMON_STOP_WORDS = {
    "ev", "charging", "station", "charger", "point", "hub", "charge",
    "limited", "ltd", "pvt", "private", "the", "and", "at", "in", "near", "opp",
    "opposite", "behind", "road", "rd", "street", "st", "lane", "nagar", "complex",
}

# Regional / Mumbai domain acronyms and synonym mappings
MUMBAI_ACRONYMS: dict[str, list[str]] = {
    "bkc": ["bandra", "kurla", "complex"],
    "weh": ["western", "express", "highway"],
    "eeh": ["eastern", "express", "highway"],
    "jvlr": ["jogeshwari", "vikhroli", "link", "road"],
    "sclr": ["santacruz", "chembur", "link", "road"],
}


class MatchState(str, Enum):
    """Authoritative outcome of cross-source entity evidence fusion."""
    MATCH = "MATCH"
    NON_MATCH = "NON_MATCH"
    AMBIGUOUS = "AMBIGUOUS"


class EvidenceSignal(str, Enum):
    """Individual signal concordance classification."""
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GeoProximityEvidence:
    """Geodetic proximity evaluation between two physical locations."""
    distance_meters: float
    threshold_meters: float
    is_within_threshold: bool
    proximity_score: float  # 1.0 at 0m, decaying to 0.0 at threshold_meters


@dataclass(frozen=True)
class NameSimilarityEvidence:
    """Lexical and token similarity analysis between station names."""
    raw_name_a: str
    raw_name_b: str
    normalized_name_a: str
    normalized_name_b: str
    token_sort_ratio: float
    jaccard_token_ratio: float
    similarity_score: float  # Blended deterministic similarity in [0.0, 1.0]
    signal: EvidenceSignal


@dataclass(frozen=True)
class OperatorEvidence:
    """Organizational ownership reconciliation."""
    operator_name_a: Optional[str]
    operator_name_b: Optional[str]
    operator_slug_a: Optional[str]
    operator_slug_b: Optional[str]
    signal: EvidenceSignal
    confidence: float
    details: str


@dataclass(frozen=True)
class ConnectorEvidence:
    """Electrical connector signature compatibility."""
    types_a: list[str]
    types_b: list[str]
    matching_types: list[str]
    powers_a: list[float]
    powers_b: list[float]
    power_compatibility: Optional[bool]
    signal: EvidenceSignal
    confidence: float
    details: str


@dataclass(frozen=True)
class AddressEvidence:
    """Geographic postal code and locality overlap analysis."""
    postal_code_a: Optional[str]
    postal_code_b: Optional[str]
    locality_a: Optional[str]
    locality_b: Optional[str]
    pin_match: Optional[bool]
    locality_similarity: float
    signal: EvidenceSignal
    details: str


@dataclass(frozen=True)
class EntityResolutionCandidate:
    """Complete, transparent evidence dossier for a candidate pair of source records."""
    source_a: str
    source_station_id_a: str
    name_a: str
    source_b: str
    source_station_id_b: str
    name_b: str
    distance_meters: float
    geo_evidence: GeoProximityEvidence
    name_evidence: NameSimilarityEvidence
    operator_evidence: OperatorEvidence
    connector_evidence: ConnectorEvidence
    address_evidence: AddressEvidence
    overall_confidence: float  # Evaluated evidence score in [0.0, 1.0]
    match_state: MatchState
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Converts evidence dossier to JSON-serializable dictionary."""
        return {
            "source_a": self.source_a,
            "source_station_id_a": self.source_station_id_a,
            "name_a": self.name_a,
            "source_b": self.source_b,
            "source_station_id_b": self.source_station_id_b,
            "name_b": self.name_b,
            "distance_meters": round(self.distance_meters, 2),
            "match_state": self.match_state.value,
            "overall_confidence": round(self.overall_confidence, 3),
            "reasons": self.reasons,
            "evidence": {
                "geo": {
                    "distance_meters": round(self.geo_evidence.distance_meters, 2),
                    "is_within_threshold": self.geo_evidence.is_within_threshold,
                    "proximity_score": round(self.geo_evidence.proximity_score, 3),
                },
                "name": {
                    "similarity_score": round(self.name_evidence.similarity_score, 3),
                    "token_sort_ratio": round(self.name_evidence.token_sort_ratio, 3),
                    "jaccard_token_ratio": round(self.name_evidence.jaccard_token_ratio, 3),
                    "signal": self.name_evidence.signal.value,
                },
                "operator": {
                    "signal": self.operator_evidence.signal.value,
                    "confidence": round(self.operator_evidence.confidence, 3),
                    "details": self.operator_evidence.details,
                },
                "connector": {
                    "signal": self.connector_evidence.signal.value,
                    "matching_types": self.connector_evidence.matching_types,
                    "power_compatibility": self.connector_evidence.power_compatibility,
                    "details": self.connector_evidence.details,
                },
                "address": {
                    "signal": self.address_evidence.signal.value,
                    "pin_match": self.address_evidence.pin_match,
                    "locality_similarity": round(self.address_evidence.locality_similarity, 3),
                    "details": self.address_evidence.details,
                },
            },
        }


@dataclass
class EntityResolutionConfig:
    """Configurable evidence thresholds and weights for entity resolution."""
    # Spatial Proximity
    candidate_radius_meters: float = 50.0

    # Name Similarity Thresholds
    high_name_similarity_threshold: float = 0.75
    moderate_name_similarity_threshold: float = 0.55
    low_name_similarity_threshold: float = 0.35

    # Overall Confidence Gates
    match_confidence_threshold: float = 0.70
    non_match_confidence_threshold: float = 0.38

    # Multi-Signal Weights (Sum to 1.0)
    weight_proximity: float = 0.30
    weight_name: float = 0.30
    weight_operator: float = 0.15
    weight_connector: float = 0.15
    weight_address: float = 0.10


# ------------------------------------------------------------------------------
# String & Math Normalization Helpers
# ------------------------------------------------------------------------------

def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes exact great-circle distance between two WGS 84 points using Haversine formula."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    # Numerical stability clamp for identical coordinates
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


def normalize_string_for_matching(text: Optional[str]) -> str:
    """Normalizes string: NFKD unicode normalization, lowercasing, punctuation removal."""
    if not text:
        return ""
    # Normalize unicode accents
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("utf-8")
    norm = norm.lower()
    # Replace non-alphanumeric with spaces
    norm = re.sub(r"[^a-z0-9\s]", " ", norm)
    # Collapse multiple whitespaces
    return " ".join(norm.split())


def extract_meaningful_tokens(normalized_text: str) -> set[str]:
    """Tokenizes normalized text, expands regional acronyms, and filters generic EV charging stop words."""
    raw_tokens = TOKEN_SPLIT_REGEX.split(normalized_text)
    meaningful: set[str] = set()
    for t in raw_tokens:
        if not t or len(t) <= 1:
            continue
        if t in COMMON_STOP_WORDS:
            continue
        meaningful.add(t)
        # Expand known domain acronyms (e.g. 'bkc' -> {'bandra', 'kurla', 'complex'})
        if t in MUMBAI_ACRONYMS:
            for exp in MUMBAI_ACRONYMS[t]:
                if exp not in COMMON_STOP_WORDS:
                    meaningful.add(exp)

    # If all tokens were filtered (e.g. "EV Station"), fallback to non-empty raw tokens
    if not meaningful:
        meaningful = {t for t in raw_tokens if t and len(t) > 1}
    return meaningful


def calculate_overlap_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Calculates Szymkiewicz-Simpson overlap coefficient: |A n B| / min(|A|, |B|)."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    min_len = min(len(set_a), len(set_b))
    return intersection / min_len if min_len > 0 else 0.0


def calculate_jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Calculates Jaccard intersection over union for two token sets."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def calculate_levenshtein_ratio(s1: str, s2: str) -> float:
    """Calculates deterministic normalized Levenshtein similarity ratio in [0.0, 1.0]."""
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    len1, len2 = len(s1), len(s2)
    # Dynamic programming with single previous row for O(min(len1, len2)) space
    if len1 < len2:
        s1, s2 = s2, s1
        len1, len2 = len2, len1

    prev_row = list(range(len2 + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1] * (len2 + 1)
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row[j + 1] = min(insertions, deletions, substitutions)
        prev_row = curr_row

    dist = prev_row[len2]
    max_len = max(len1, len2)
    return max(0.0, 1.0 - (dist / max_len))


def calculate_token_sort_ratio(s1: str, s2: str) -> float:
    """Calculates Levenshtein ratio on sorted tokens to be invariant to word order."""
    tokens1 = sorted(s1.split())
    tokens2 = sorted(s2.split())
    sorted_s1 = " ".join(tokens1)
    sorted_s2 = " ".join(tokens2)
    return calculate_levenshtein_ratio(sorted_s1, sorted_s2)


# ------------------------------------------------------------------------------
# Core Cross-Source Entity Resolver
# ------------------------------------------------------------------------------

class CrossSourceEntityResolver:
    """Evaluates cross-source candidate pairs and produces structured resolution evidence."""

    def __init__(self, config: Optional[EntityResolutionConfig] = None):
        self.config = config or EntityResolutionConfig()

    def evaluate_pair(
        self,
        record_a: NormalizedStationRecord,
        record_b: NormalizedStationRecord,
    ) -> EntityResolutionCandidate:
        """Compares two normalized station records and produces a comprehensive evidence dossier."""
        reasons: list[str] = []

        # ----------------------------------------------------------------------
        # 1. Geographic Proximity Evidence
        # ----------------------------------------------------------------------
        dist_m = haversine_distance_meters(
            record_a.latitude, record_a.longitude,
            record_b.latitude, record_b.longitude,
        )
        is_within_radius = dist_m <= self.config.candidate_radius_meters
        if is_within_radius:
            # Linear decay from 1.0 at 0m to 0.0 at candidate_radius_meters
            prox_score = max(0.0, 1.0 - (dist_m / self.config.candidate_radius_meters))
            reasons.append(f"Physical distance is {dist_m:.1f}m (within <= {self.config.candidate_radius_meters:.0f}m radius)")
        else:
            prox_score = 0.0
            reasons.append(f"Physical distance is {dist_m:.1f}m (exceeds candidate threshold of {self.config.candidate_radius_meters:.0f}m)")

        geo_ev = GeoProximityEvidence(
            distance_meters=dist_m,
            threshold_meters=self.config.candidate_radius_meters,
            is_within_threshold=is_within_radius,
            proximity_score=prox_score,
        )

        # ----------------------------------------------------------------------
        # Fast exit for spatially distant records
        # ----------------------------------------------------------------------
        if not is_within_radius:
            name_ev = self._evaluate_name_similarity(record_a.name, record_b.name)
            op_ev = self._evaluate_operator(record_a, record_b)
            conn_ev = self._evaluate_connectors(record_a.connectors, record_b.connectors)
            addr_ev = self._evaluate_address(record_a, record_b)

            return EntityResolutionCandidate(
                source_a=record_a.source_id,
                source_station_id_a=record_a.source_station_id,
                name_a=record_a.name,
                source_b=record_b.source_id,
                source_station_id_b=record_b.source_station_id,
                name_b=record_b.name,
                distance_meters=dist_m,
                geo_evidence=geo_ev,
                name_evidence=name_ev,
                operator_evidence=op_ev,
                connector_evidence=conn_ev,
                address_evidence=addr_ev,
                overall_confidence=0.0,
                match_state=MatchState.NON_MATCH,
                reasons=reasons,
            )

        # ----------------------------------------------------------------------
        # 2. Name Similarity Evidence
        # ----------------------------------------------------------------------
        name_ev = self._evaluate_name_similarity(record_a.name, record_b.name)
        if name_ev.signal == EvidenceSignal.AGREE:
            reasons.append(f"High name concordance (score: {name_ev.similarity_score:.2f})")
        elif name_ev.signal == EvidenceSignal.DISAGREE:
            reasons.append(f"Low name similarity (score: {name_ev.similarity_score:.2f})")
        else:
            reasons.append(f"Moderate name similarity (score: {name_ev.similarity_score:.2f})")

        # ----------------------------------------------------------------------
        # 3. Operator Evidence
        # ----------------------------------------------------------------------
        op_ev = self._evaluate_operator(record_a, record_b)
        reasons.append(f"Operator evidence: {op_ev.signal.value} ({op_ev.details})")

        # ----------------------------------------------------------------------
        # 4. Connector Evidence
        # ----------------------------------------------------------------------
        conn_ev = self._evaluate_connectors(record_a.connectors, record_b.connectors)
        reasons.append(f"Connector signature: {conn_ev.signal.value} ({conn_ev.details})")

        # ----------------------------------------------------------------------
        # 5. Address / PIN Evidence
        # ----------------------------------------------------------------------
        addr_ev = self._evaluate_address(record_a, record_b)
        reasons.append(f"Address evidence: {addr_ev.signal.value} ({addr_ev.details})")

        # ----------------------------------------------------------------------
        # 6. Evidence Fusion & Match State Decision
        # ----------------------------------------------------------------------
        confidence, match_state = self._fuse_evidence(
            geo_ev=geo_ev,
            name_ev=name_ev,
            op_ev=op_ev,
            conn_ev=conn_ev,
            addr_ev=addr_ev,
            reasons=reasons,
        )

        return EntityResolutionCandidate(
            source_a=record_a.source_id,
            source_station_id_a=record_a.source_station_id,
            name_a=record_a.name,
            source_b=record_b.source_id,
            source_station_id_b=record_b.source_station_id,
            name_b=record_b.name,
            distance_meters=dist_m,
            geo_evidence=geo_ev,
            name_evidence=name_ev,
            operator_evidence=op_ev,
            connector_evidence=conn_ev,
            address_evidence=addr_ev,
            overall_confidence=confidence,
            match_state=match_state,
            reasons=reasons,
        )

    # --------------------------------------------------------------------------
    # Sub-Evaluators
    # --------------------------------------------------------------------------

    def _evaluate_name_similarity(self, name_a: str, name_b: str) -> NameSimilarityEvidence:
        """Evaluates multiple string and token metrics between two station names."""
        norm_a = normalize_string_for_matching(name_a)
        norm_b = normalize_string_for_matching(name_b)

        # 1. Exact normalized match
        if norm_a == norm_b and norm_a:
            return NameSimilarityEvidence(
                raw_name_a=name_a, raw_name_b=name_b,
                normalized_name_a=norm_a, normalized_name_b=norm_b,
                token_sort_ratio=1.0, jaccard_token_ratio=1.0,
                similarity_score=1.0, signal=EvidenceSignal.AGREE,
            )

        # 2. Token metrics on meaningful words
        tokens_a = extract_meaningful_tokens(norm_a)
        tokens_b = extract_meaningful_tokens(norm_b)
        jaccard = calculate_jaccard_similarity(tokens_a, tokens_b)
        overlap = calculate_overlap_similarity(tokens_a, tokens_b)

        # 3. Token Sort Ratio (Levenshtein on alphabetically sorted meaningful tokens)
        sorted_a = " ".join(sorted(tokens_a)) if tokens_a else norm_a
        sorted_b = " ".join(sorted(tokens_b)) if tokens_b else norm_b
        sort_ratio = calculate_levenshtein_ratio(sorted_a, sorted_b)

        # Blended score: 35% token sort ratio, 35% jaccard, 30% overlap coefficient
        blended = (0.35 * sort_ratio) + (0.35 * jaccard) + (0.30 * overlap)

        # Bonus if one full normalized name is completely contained inside the other
        if (norm_a and norm_b) and (norm_a in norm_b or norm_b in norm_a):
            blended = max(blended, 0.85)

        blended = min(1.0, max(0.0, blended))

        if blended >= self.config.high_name_similarity_threshold:
            signal = EvidenceSignal.AGREE
        elif blended <= self.config.low_name_similarity_threshold:
            signal = EvidenceSignal.DISAGREE
        else:
            signal = EvidenceSignal.UNKNOWN

        return NameSimilarityEvidence(
            raw_name_a=name_a, raw_name_b=name_b,
            normalized_name_a=norm_a, normalized_name_b=norm_b,
            token_sort_ratio=sort_ratio, jaccard_token_ratio=jaccard,
            similarity_score=blended, signal=signal,
        )

    def _evaluate_operator(
        self,
        record_a: NormalizedStationRecord,
        record_b: NormalizedStationRecord,
    ) -> OperatorEvidence:
        """Reconciles operator identities, respecting missing values as UNKNOWN."""
        slug_a = record_a.operator_slug or normalize_string_for_matching(record_a.operator_name)
        slug_b = record_b.operator_slug or normalize_string_for_matching(record_b.operator_name)

        # Rule: Missing operator on either source does NOT imply disagreement
        if not slug_a or not slug_b or slug_a in ("unknown", "generic") or slug_b in ("unknown", "generic"):
            return OperatorEvidence(
                operator_name_a=record_a.operator_name,
                operator_name_b=record_b.operator_name,
                operator_slug_a=record_a.operator_slug,
                operator_slug_b=record_b.operator_slug,
                signal=EvidenceSignal.UNKNOWN,
                confidence=0.5,
                details="Operator missing or unknown on one/both sources",
            )

        # Exact slug match or mutual containment
        if slug_a == slug_b or slug_a in slug_b or slug_b in slug_a:
            return OperatorEvidence(
                operator_name_a=record_a.operator_name,
                operator_name_b=record_b.operator_name,
                operator_slug_a=record_a.operator_slug,
                operator_slug_b=record_b.operator_slug,
                signal=EvidenceSignal.AGREE,
                confidence=1.0,
                details=f"Operators concordant ('{slug_a}' == '{slug_b}')",
            )

        # Token overlap for compound operator names
        toks_a = set(slug_a.split("-"))
        toks_b = set(slug_b.split("-"))
        if len(toks_a & toks_b) >= 1 and not (toks_a & toks_b).issubset({"power", "energy", "ev", "charge"}):
            return OperatorEvidence(
                operator_name_a=record_a.operator_name,
                operator_name_b=record_b.operator_name,
                operator_slug_a=record_a.operator_slug,
                operator_slug_b=record_b.operator_slug,
                signal=EvidenceSignal.AGREE,
                confidence=0.8,
                details=f"Operator token match ('{slug_a}' ~ '{slug_b}')",
            )

        # Disagreeing explicit operators
        return OperatorEvidence(
            operator_name_a=record_a.operator_name,
            operator_name_b=record_b.operator_name,
            operator_slug_a=record_a.operator_slug,
            operator_slug_b=record_b.operator_slug,
            signal=EvidenceSignal.DISAGREE,
            confidence=0.9,
            details=f"Conflicting operators ('{slug_a}' != '{slug_b}')",
        )

    def _evaluate_connectors(
        self,
        connectors_a: list[NormalizedConnectorRecord],
        connectors_b: list[NormalizedConnectorRecord],
    ) -> ConnectorEvidence:
        """Compares physical connector signatures without inventing missing values."""
        # Rule: Missing connector details does NOT imply disagreement
        if not connectors_a or not connectors_b:
            return ConnectorEvidence(
                types_a=[c.connector_type for c in connectors_a],
                types_b=[c.connector_type for c in connectors_b],
                matching_types=[],
                powers_a=[c.power_kw for c in connectors_a if c.power_kw],
                powers_b=[c.power_kw for c in connectors_b if c.power_kw],
                power_compatibility=None,
                signal=EvidenceSignal.UNKNOWN,
                confidence=0.5,
                details="Connectors missing on one/both sources",
            )

        types_a = {c.connector_type for c in connectors_a if c.connector_type != "Other"}
        types_b = {c.connector_type for c in connectors_b if c.connector_type != "Other"}

        matching_types = sorted(types_a & types_b)
        powers_a = [c.power_kw for c in connectors_a if c.power_kw]
        powers_b = [c.power_kw for c in connectors_b if c.power_kw]

        # Check power tier compatibility if both report power
        power_compat: Optional[bool] = None
        if powers_a and powers_b:
            # Check if at least one power rating matches within 10% tolerance
            power_compat = any(
                abs(p_a - p_b) <= max(5.0, 0.10 * p_a)
                for p_a in powers_a for p_b in powers_b
            )

        # 1. Type overlap
        if matching_types:
            details = f"Shared connector types: {matching_types}"
            if power_compat is True:
                details += " with compatible power ratings"
            return ConnectorEvidence(
                types_a=sorted(types_a),
                types_b=sorted(types_b),
                matching_types=matching_types,
                powers_a=powers_a,
                powers_b=powers_b,
                power_compatibility=power_compat,
                signal=EvidenceSignal.AGREE,
                confidence=1.0 if power_compat is True else 0.8,
                details=details,
            )

        # 2. Both report explicit connector types, but zero overlap
        if types_a and types_b and not matching_types:
            return ConnectorEvidence(
                types_a=sorted(types_a),
                types_b=sorted(types_b),
                matching_types=[],
                powers_a=powers_a,
                powers_b=powers_b,
                power_compatibility=power_compat,
                signal=EvidenceSignal.DISAGREE,
                confidence=0.85,
                details=f"Incompatible connector types: {sorted(types_a)} vs {sorted(types_b)}",
            )

        return ConnectorEvidence(
            types_a=sorted(types_a),
            types_b=sorted(types_b),
            matching_types=[],
            powers_a=powers_a,
            powers_b=powers_b,
            power_compatibility=power_compat,
            signal=EvidenceSignal.UNKNOWN,
            confidence=0.5,
            details="Generic/unmapped connector types",
        )

    def _evaluate_address(
        self,
        record_a: NormalizedStationRecord,
        record_b: NormalizedStationRecord,
    ) -> AddressEvidence:
        """Compares postal code and locality tokens, treating omissions as UNKNOWN."""
        pin_a = (record_a.postal_code or "").strip()
        pin_b = (record_b.postal_code or "").strip()
        pin_match: Optional[bool] = None

        if pin_a and pin_b:
            pin_match = (pin_a == pin_b)

        loc_a = normalize_string_for_matching(f"{record_a.locality or ''} {record_a.address_line or ''}")
        loc_b = normalize_string_for_matching(f"{record_b.locality or ''} {record_b.address_line or ''}")

        tokens_a = extract_meaningful_tokens(loc_a)
        tokens_b = extract_meaningful_tokens(loc_b)
        loc_sim = calculate_jaccard_similarity(tokens_a, tokens_b)

        # Strong agreement: same PIN and locality token overlap
        if pin_match is True or (loc_sim >= 0.40):
            signal = EvidenceSignal.AGREE
            details = f"Address agreement (PIN match: {pin_match}, locality overlap: {loc_sim:.2f})"
        elif pin_match is False and loc_sim < 0.15:
            # Conflicting explicit PINs in different localities
            signal = EvidenceSignal.DISAGREE
            details = f"Address disagreement (PIN: '{pin_a}' != '{pin_b}', locality overlap: {loc_sim:.2f})"
        else:
            signal = EvidenceSignal.UNKNOWN
            details = f"Address inconclusive (PIN match: {pin_match}, locality overlap: {loc_sim:.2f})"

        return AddressEvidence(
            postal_code_a=record_a.postal_code,
            postal_code_b=record_b.postal_code,
            locality_a=record_a.locality,
            locality_b=record_b.locality,
            pin_match=pin_match,
            locality_similarity=loc_sim,
            signal=signal,
            details=details,
        )

    # --------------------------------------------------------------------------
    # Evidence Fusion Logic
    # --------------------------------------------------------------------------

    def _fuse_evidence(
        self,
        geo_ev: GeoProximityEvidence,
        name_ev: NameSimilarityEvidence,
        op_ev: OperatorEvidence,
        conn_ev: ConnectorEvidence,
        addr_ev: AddressEvidence,
        reasons: list[str],
    ) -> tuple[float, MatchState]:
        """Fuses multi-signal evidence into a deterministic confidence score and MatchState."""
        # 1. Base Proximity Score [0.0..1.0]
        score_prox = geo_ev.proximity_score

        # 2. Name Score [0.0..1.0]
        score_name = name_ev.similarity_score

        # 3. Operator Concordance Score [0.0..1.0] (0.5 for UNKNOWN/missing)
        if op_ev.signal == EvidenceSignal.AGREE:
            score_op = 1.0
        elif op_ev.signal == EvidenceSignal.DISAGREE:
            score_op = 0.0
        else:
            score_op = 0.5  # Neutral

        # 4. Connector Concordance Score [0.0..1.0] (0.5 for UNKNOWN/missing)
        if conn_ev.signal == EvidenceSignal.AGREE:
            score_conn = 1.0
        elif conn_ev.signal == EvidenceSignal.DISAGREE:
            score_conn = 0.0
        else:
            score_conn = 0.5  # Neutral

        # 5. Address / PIN Score [0.0..1.0] (0.5 for UNKNOWN/missing)
        if addr_ev.signal == EvidenceSignal.AGREE:
            score_addr = 1.0
        elif addr_ev.signal == EvidenceSignal.DISAGREE:
            score_addr = 0.0
        else:
            score_addr = 0.5  # Neutral

        # Weighted Evidence Fusion
        confidence = (
            self.config.weight_proximity * score_prox
            + self.config.weight_name * score_name
            + self.config.weight_operator * score_op
            + self.config.weight_connector * score_conn
            + self.config.weight_address * score_addr
        )

        # ----------------------------------------------------------------------
        # Categorical Rules (Multi-Signal Invariants)
        # ----------------------------------------------------------------------

        # Condition 1: Automatic NON_MATCH if distance exceeds threshold
        if not geo_ev.is_within_threshold:
            return 0.0, MatchState.NON_MATCH

        # Count positive confirming signals beyond proximity
        positive_signals = sum([
            name_ev.signal == EvidenceSignal.AGREE,
            op_ev.signal == EvidenceSignal.AGREE,
            conn_ev.signal == EvidenceSignal.AGREE,
            addr_ev.signal == EvidenceSignal.AGREE,
        ])

        # Count hard contradictory signals
        negative_signals = sum([
            name_ev.signal == EvidenceSignal.DISAGREE,
            op_ev.signal == EvidenceSignal.DISAGREE,
            conn_ev.signal == EvidenceSignal.DISAGREE,
            addr_ev.signal == EvidenceSignal.DISAGREE,
        ])

        # Rule A: Strong Concordant MATCH
        # Requires close proximity + high name similarity + at least one other confirming positive signal
        # AND zero strong negative signals (or only operator difference when physical evidence is overwhelming)
        is_strong_name = name_ev.similarity_score >= self.config.high_name_similarity_threshold
        is_very_close = geo_ev.distance_meters <= 25.0

        if is_strong_name and positive_signals >= 2 and negative_signals == 0:
            reasons.append("Multi-signal positive concordance achieved (high name similarity + agreeing attributes)")
            return max(confidence, self.config.match_confidence_threshold), MatchState.MATCH

        # Rule A2: Very close physical site with identical name and agreeing operator
        if is_very_close and is_strong_name and op_ev.signal == EvidenceSignal.AGREE:
            reasons.append("High name concordance and matching operator in close proximity")
            return max(confidence, self.config.match_confidence_threshold), MatchState.MATCH

        # Rule A3: Operator disagreement alone does not block match if ALL physical evidence is identical
        # (e.g. site changed hands / rebranded, but name, address, connectors, and exact location agree)
        if (
            is_very_close and is_strong_name
            and conn_ev.signal == EvidenceSignal.AGREE
            and addr_ev.signal == EvidenceSignal.AGREE
            and negative_signals == 1 and op_ev.signal == EvidenceSignal.DISAGREE
        ):
            reasons.append("Physical site identity confirmed despite operator divergence (potential rebrand/takeover)")
            return max(confidence, self.config.match_confidence_threshold), MatchState.MATCH

        # Rule B: AMBIGUOUS
        # Within the candidate radius (<= 50m), when multi-signal positive concordance is not fully achieved,
        # or when attributes conflict / are partial / missing: preserve ambiguity. Never force a match or non-match.
        # This leaves authoritative arbitration to Step 2.7.
        reasons.append("Evidence is mixed, partial, or conflicting within candidate radius; preserving ambiguity without forcing match")
        return confidence, MatchState.AMBIGUOUS

    # --------------------------------------------------------------------------
    # Batch / Search APIs
    # --------------------------------------------------------------------------

    def find_candidates_for_record(
        self,
        record: NormalizedStationRecord,
        corpus: Sequence[NormalizedStationRecord],
        filter_same_source: bool = True,
    ) -> list[EntityResolutionCandidate]:
        """Finds and evaluates all candidate matches for a single station within a corpus.

        Preserves all candidates rather than arbitrarily discarding runners-up.
        """
        candidates: list[EntityResolutionCandidate] = []
        for other in corpus:
            # Skip comparing record to itself
            if other.source_id == record.source_id and other.source_station_id == record.source_station_id:
                continue
            # Optionally filter records from the exact same source (handled by idempotency)
            if filter_same_source and other.source_id == record.source_id:
                continue

            cand = self.evaluate_pair(record, other)
            # Only include candidates within the spatial candidate radius
            if cand.geo_evidence.is_within_threshold:
                candidates.append(cand)

        # Sort candidates deterministically: highest confidence first, then ascending distance, then source ID
        candidates.sort(
            key=lambda c: (-c.overall_confidence, c.distance_meters, c.source_b, c.source_station_id_b)
        )
        return candidates

    def find_all_candidates(
        self,
        corpus_a: Sequence[NormalizedStationRecord],
        corpus_b: Sequence[NormalizedStationRecord],
    ) -> list[EntityResolutionCandidate]:
        """Discovers and evaluates all cross-source candidate pairs between two distinct source corpora."""
        all_candidates: list[EntityResolutionCandidate] = []
        for rec_a in corpus_a:
            cands = self.find_candidates_for_record(rec_a, corpus_b, filter_same_source=False)
            all_candidates.extend(cands)

        # Deterministic sorting
        all_candidates.sort(
            key=lambda c: (-c.overall_confidence, c.distance_meters, c.source_a, c.source_station_id_a, c.source_station_id_b)
        )
        return all_candidates
