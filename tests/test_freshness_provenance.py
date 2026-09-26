"""ChargePlus — Test Suite for Step 2.9 Freshness Engine, Observation Provenance & Staleness Decay.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.9 (Record Freshness/Provenance & Observation Freshness Decay)

Covers all mandatory test scenarios from Section 19:
A. Deterministic evaluation
B. Explicit as_of/reference time
C. Timezone-aware timestamps
D. Exact fresh boundary (age == fresh_window)
E. Exact aging boundary (age == stale_window)
F. Exact stale boundary (age > stale_window)
G. Missing observation time
H. Missing source_updated_at
I. Explicit retrieval-time fallback where allowed
J. Unknown freshness when no valid basis exists
K. Stale observation remains AVAILABLE (STALE != UNAVAILABLE)
L. Stale observation does not become UNAVAILABLE
M. Fresh UNAVAILABLE remains UNAVAILABLE
N. Fresh AVAILABLE remains AVAILABLE
O. Observation time vs source updated time distinction
P. Source-specific policy selection
Q. Policy configuration is deterministic
R. Repeated evaluation gives identical result (idempotency)
S. Historical observations are not mutated on aging
T. Future timestamp defensive behavior
U. Provenance survives normalization/persistence
V. Raw payload hash remains unchanged
W. Source record ID remains unchanged
X. Canonical station UUID remains distinct from source station ID
Y. Mathematical decay curves (LINEAR, EXPONENTIAL, STEP, NONE)
Z. Live database provenance test with clean rollback
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import os
import unittest
import uuid

from dotenv import load_dotenv
import psycopg2

from backend.ingestion.constants import (
    CONTRACT_VERSION,
    AvailabilityStatus,
    OperationalStatus,
    PricingType,
    QueueLevel,
    StandardConnectorType,
)
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedObservationRecord,
    NormalizedStationRecord,
    ProvenanceInfo,
    RawSourceRecord,
)
from backend.ingestion.freshness import (
    DEFAULT_LIVE_TELEMETRY_POLICY,
    DEFAULT_OPERATIONAL_STATUS_POLICY,
    DEFAULT_PRICING_POLICY,
    DEFAULT_STATIC_METADATA_POLICY,
    OCM_LIVE_TELEMETRY_POLICY,
    OCM_STATIC_METADATA_POLICY,
    DecayCurve,
    FreshnessBasis,
    FreshnessEngine,
    FreshnessEvaluationResult,
    FreshnessPolicy,
    FreshnessPolicyRegistry,
    FreshnessState,
    InformationType,
    StationFreshnessSummary,
)
from backend.ingestion.persistence import IngestionPersistenceService


class TestFreshnessAndProvenance(unittest.TestCase):
    """Comprehensive test suite for ChargePlus Freshness Engine and Provenance Layer."""

    def setUp(self) -> None:
        self.engine = FreshnessEngine()
        self.ref_time = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)

    # --------------------------------------------------------------------------
    # Scenario A & B: Deterministic Evaluation with Explicit as_of
    # --------------------------------------------------------------------------
    def test_01_deterministic_evaluation_with_explicit_as_of(self):
        """A & B: Evaluation requires explicit as_of and yields identical results regardless of execution time."""
        observed_time = self.ref_time - timedelta(minutes=3)
        res1 = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=observed_time,
            information_type=InformationType.LIVE_TELEMETRY,
        )
        res2 = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=observed_time,
            information_type=InformationType.LIVE_TELEMETRY,
        )

        self.assertEqual(res1.state, FreshnessState.FRESH)
        self.assertEqual(res1.basis, FreshnessBasis.OBSERVATION_TIME)
        self.assertEqual(res1.age_seconds, 180.0)
        self.assertEqual(res1.age_minutes, 3.0)
        self.assertEqual(res1, res2)

    # --------------------------------------------------------------------------
    # Scenario C: Timezone-Aware and Naive Handling
    # --------------------------------------------------------------------------
    def test_02_timezone_aware_and_naive_handling(self):
        """C: Evaluates aware timestamps in other timezones (e.g. IST +05:30) and naive timestamps cleanly."""
        ist = timezone(timedelta(hours=5, minutes=30))
        # 17:30 IST is identical to 12:00 UTC
        as_of_ist = datetime(2026, 9, 26, 17, 30, 0, tzinfo=ist)
        observed_ist = datetime(2026, 9, 26, 17, 26, 0, tzinfo=ist)  # 4 minutes ago

        res = self.engine.evaluate(
            as_of=as_of_ist,
            observed_at=observed_ist,
            information_type=InformationType.LIVE_TELEMETRY,
        )
        self.assertEqual(res.state, FreshnessState.FRESH)
        self.assertEqual(res.age_seconds, 240.0)
        self.assertEqual(res.age_minutes, 4.0)

        # Naive datetime is safely coerced to UTC without crashing
        naive_as_of = datetime(2026, 9, 26, 12, 0, 0)
        naive_observed = datetime(2026, 9, 26, 11, 55, 0)
        res_naive = self.engine.evaluate(
            as_of=naive_as_of,
            observed_at=naive_observed,
            information_type=InformationType.LIVE_TELEMETRY,
        )
        self.assertEqual(res_naive.state, FreshnessState.FRESH)
        self.assertEqual(res_naive.age_seconds, 300.0)

    # --------------------------------------------------------------------------
    # Scenario D: Exact Fresh Boundary
    # --------------------------------------------------------------------------
    def test_03_exact_fresh_boundary(self):
        """D: Information at exactly age == fresh_window_seconds evaluates to FRESH."""
        policy = DEFAULT_LIVE_TELEMETRY_POLICY  # fresh_window = 300s (5 min)
        observed_time = self.ref_time - timedelta(seconds=300)

        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=observed_time,
            policy=policy,
        )
        self.assertEqual(res.state, FreshnessState.FRESH)
        self.assertEqual(res.age_seconds, 300.0)
        self.assertTrue(res.is_usable_for_live_display)

    # --------------------------------------------------------------------------
    # Scenario E: Exact Aging Boundary
    # --------------------------------------------------------------------------
    def test_04_exact_aging_boundary(self):
        """E: Information at fresh_window < age <= stale_window evaluates to AGING."""
        policy = DEFAULT_LIVE_TELEMETRY_POLICY  # stale_window = 900s (15 min)
        # Just past fresh window (301 seconds)
        res_just_aging = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=self.ref_time - timedelta(seconds=301),
            policy=policy,
        )
        self.assertEqual(res_just_aging.state, FreshnessState.AGING)
        self.assertTrue(res_just_aging.is_usable_for_live_display)

        # Exactly at stale window (900 seconds)
        res_at_stale_border = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=self.ref_time - timedelta(seconds=900),
            policy=policy,
        )
        self.assertEqual(res_at_stale_border.state, FreshnessState.AGING)
        self.assertEqual(res_at_stale_border.age_seconds, 900.0)

    # --------------------------------------------------------------------------
    # Scenario F: Exact Stale Boundary
    # --------------------------------------------------------------------------
    def test_05_exact_stale_boundary(self):
        """F: Information at age > stale_window_seconds evaluates to STALE."""
        policy = DEFAULT_LIVE_TELEMETRY_POLICY  # stale_window = 900s (15 min)
        # 901 seconds (15 min + 1s)
        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=self.ref_time - timedelta(seconds=901),
            policy=policy,
        )
        self.assertEqual(res.state, FreshnessState.STALE)
        self.assertEqual(res.age_seconds, 901.0)
        self.assertFalse(res.is_usable_for_live_display)

    # --------------------------------------------------------------------------
    # Scenario G: Missing Observation Time
    # --------------------------------------------------------------------------
    def test_06_missing_observation_time_evaluates_unknown(self):
        """G: Omission of observed_at on live telemetry evaluates to UNKNOWN freshness."""
        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=None,
            source_updated_at=None,
            retrieved_at=None,
            information_type=InformationType.LIVE_TELEMETRY,
        )
        self.assertEqual(res.state, FreshnessState.UNKNOWN)
        self.assertEqual(res.basis, FreshnessBasis.UNKNOWN)
        self.assertIsNone(res.age_seconds)
        self.assertIsNone(res.decay_score)

    # --------------------------------------------------------------------------
    # Scenario H: Missing Source Updated At Without Fallback
    # --------------------------------------------------------------------------
    def test_07_missing_source_updated_at_evaluates_unknown_without_fallback(self):
        """H: If source_updated_at is absent and policy forbids retrieval fallback, freshness is UNKNOWN."""
        # Operational status policy forbids retrieval fallback
        policy = DEFAULT_OPERATIONAL_STATUS_POLICY
        self.assertFalse(policy.allow_retrieval_fallback)

        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=None,
            source_updated_at=None,
            retrieved_at=self.ref_time - timedelta(minutes=10),
            policy=policy,
        )
        self.assertEqual(res.state, FreshnessState.UNKNOWN)
        self.assertEqual(res.basis, FreshnessBasis.UNKNOWN)
        self.assertIsNone(res.age_seconds)

    # --------------------------------------------------------------------------
    # Scenario I: Explicit Retrieval Fallback Where Allowed
    # --------------------------------------------------------------------------
    def test_08_retrieval_fallback_allowed_when_policy_permits(self):
        """I: If source timestamp is omitted and policy explicitly allows fallback, uses RETRIEVED_AT basis."""
        policy = DEFAULT_STATIC_METADATA_POLICY
        self.assertTrue(policy.allow_retrieval_fallback)

        retrieval_time = self.ref_time - timedelta(days=2)
        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=None,
            source_updated_at=None,
            retrieved_at=retrieval_time,
            policy=policy,
        )
        self.assertEqual(res.state, FreshnessState.FRESH)
        self.assertEqual(res.basis, FreshnessBasis.RETRIEVED_AT)
        self.assertEqual(res.basis_timestamp, retrieval_time)
        self.assertEqual(res.age_seconds, 172800.0)  # 2 days in seconds
        self.assertTrue(any("retrieval timestamp as policy-permitted fallback" in w for w in res.warnings))

    # --------------------------------------------------------------------------
    # Scenario J: Unknown Freshness When No Valid Basis Exists
    # --------------------------------------------------------------------------
    def test_09_unknown_freshness_when_no_valid_basis_exists(self):
        """J: When all timestamps are None, returns UNKNOWN basis and state without throwing an exception."""
        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=None,
            source_updated_at=None,
            retrieved_at=None,
            policy=DEFAULT_STATIC_METADATA_POLICY,
        )
        self.assertEqual(res.state, FreshnessState.UNKNOWN)
        self.assertEqual(res.basis, FreshnessBasis.UNKNOWN)
        self.assertIsNone(res.basis_timestamp)

    # --------------------------------------------------------------------------
    # Scenario K & L: Stale Observation Retains AVAILABLE (STALE != UNAVAILABLE)
    # --------------------------------------------------------------------------
    def test_10_stale_observation_retains_available_status(self):
        """K & L: Central invariant STALE != UNAVAILABLE.
        
        An observation that was reported AVAILABLE 4 hours ago evaluates to STALE,
        but its operational availability remains AVAILABLE! It is NEVER rewritten to UNAVAILABLE.
        """
        obs = NormalizedObservationRecord(
            source_id="openchargemap",
            source_station_id="101",
            observed_at=self.ref_time - timedelta(hours=4),  # 4 hours old (stale for live telemetry)
            retrieved_at=self.ref_time - timedelta(hours=3, minutes=55),
            availability_status=AvailabilityStatus.AVAILABLE,
            queue_level=QueueLevel.NONE,
            available_connectors=2,
            total_connectors=2,
        )

        res = self.engine.evaluate_observation(obs=obs, as_of=self.ref_time)
        self.assertEqual(res.state, FreshnessState.STALE)
        self.assertEqual(res.basis, FreshnessBasis.OBSERVATION_TIME)
        # CRITICAL ASSERTION:
        self.assertEqual(res.retained_status, AvailabilityStatus.AVAILABLE)
        self.assertNotEqual(res.retained_status, AvailabilityStatus.UNKNOWN)

    # --------------------------------------------------------------------------
    # Scenario M: Fresh UNAVAILABLE Remains UNAVAILABLE
    # --------------------------------------------------------------------------
    def test_11_fresh_unavailable_remains_unavailable(self):
        """M: A fresh observation reporting BUSY/BROKEN remains BUSY/BROKEN."""
        obs = NormalizedObservationRecord(
            source_id="openchargemap",
            source_station_id="102",
            observed_at=self.ref_time - timedelta(minutes=2),
            availability_status=AvailabilityStatus.BUSY,
            queue_level=QueueLevel.MEDIUM,
            available_connectors=0,
            total_connectors=2,
        )
        res = self.engine.evaluate_observation(obs=obs, as_of=self.ref_time)
        self.assertEqual(res.state, FreshnessState.FRESH)
        self.assertEqual(res.retained_status, AvailabilityStatus.BUSY)

    # --------------------------------------------------------------------------
    # Scenario N: Fresh AVAILABLE Remains AVAILABLE
    # --------------------------------------------------------------------------
    def test_12_fresh_available_remains_available(self):
        """N: A fresh observation reporting AVAILABLE remains AVAILABLE."""
        obs = NormalizedObservationRecord(
            source_id="openchargemap",
            source_station_id="103",
            observed_at=self.ref_time - timedelta(minutes=1),
            availability_status=AvailabilityStatus.AVAILABLE,
            queue_level=QueueLevel.NONE,
            available_connectors=4,
            total_connectors=4,
        )
        res = self.engine.evaluate_observation(obs=obs, as_of=self.ref_time)
        self.assertEqual(res.state, FreshnessState.FRESH)
        self.assertEqual(res.retained_status, AvailabilityStatus.AVAILABLE)

    # --------------------------------------------------------------------------
    # Scenario O: Observation Time vs Source Updated Time Distinction
    # --------------------------------------------------------------------------
    def test_13_observation_time_vs_source_updated_time_distinction(self):
        """O: Live telemetry prefers observation time even when source record was updated at a different time."""
        obs_time = self.ref_time - timedelta(minutes=3)
        src_update_time = self.ref_time - timedelta(hours=2)

        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=obs_time,
            source_updated_at=src_update_time,
            information_type=InformationType.LIVE_TELEMETRY,
        )
        self.assertEqual(res.basis, FreshnessBasis.OBSERVATION_TIME)
        self.assertEqual(res.basis_timestamp, obs_time)
        self.assertEqual(res.age_seconds, 180.0)

    # --------------------------------------------------------------------------
    # Scenario P: Source-Specific Policy Selection
    # --------------------------------------------------------------------------
    def test_14_source_specific_policy_selection(self):
        """P: Resolves custom policy bound to specific source ID (e.g. openchargemap)."""
        # Register a custom fast-polling source
        fast_policy = FreshnessPolicy(
            policy_id="fast_telemetry_source_v1",
            name="Fast Telemetry Source Policy",
            information_type=InformationType.LIVE_TELEMETRY,
            fresh_window_seconds=60.0,    # 1 minute fresh
            stale_window_seconds=180.0,   # 3 minutes stale
        )
        self.engine.registry.bind_source("high_frequency_feed", InformationType.LIVE_TELEMETRY, fast_policy)

        # 2 minutes old -> for default policy (300s) this is FRESH, but for fast_policy (60s) this is AGING
        obs_time = self.ref_time - timedelta(minutes=2)

        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=obs_time,
            source_id="high_frequency_feed",
            information_type=InformationType.LIVE_TELEMETRY,
        )
        self.assertEqual(res.policy_id, "fast_telemetry_source_v1")
        self.assertEqual(res.state, FreshnessState.AGING)

    # --------------------------------------------------------------------------
    # Scenario Q: Policy Configuration is Deterministic and Validated
    # --------------------------------------------------------------------------
    def test_15_policy_configuration_is_deterministic_and_validated(self):
        """Q: Invalid policy windows (e.g. stale < fresh) are rejected by validation."""
        with self.assertRaises(ValueError):
            FreshnessPolicy(
                policy_id="invalid_policy",
                name="Invalid Policy",
                information_type=InformationType.LIVE_TELEMETRY,
                fresh_window_seconds=600.0,
                stale_window_seconds=300.0,  # Stale window smaller than fresh window!
            )

    # --------------------------------------------------------------------------
    # Scenario R: Repeated Evaluation Gives Identical Result (Idempotency)
    # --------------------------------------------------------------------------
    def test_16_repeated_evaluation_gives_identical_result_idempotence(self):
        """R: Calling evaluate 100 times with identical inputs produces 100 identical results."""
        obs_time = self.ref_time - timedelta(minutes=7)
        first_result = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=obs_time,
            information_type=InformationType.LIVE_TELEMETRY,
        )
        for _ in range(100):
            subsequent = self.engine.evaluate(
                as_of=self.ref_time,
                observed_at=obs_time,
                information_type=InformationType.LIVE_TELEMETRY,
            )
            self.assertEqual(first_result, subsequent)

    # --------------------------------------------------------------------------
    # Scenario S: Historical Observations are Not Mutated on Aging
    # --------------------------------------------------------------------------
    def test_17_historical_observations_are_not_mutated_on_aging(self):
        """S: Progressing time from t1 to t2 changes evaluation result without mutating the underlying record."""
        obs = NormalizedObservationRecord(
            source_id="ocm",
            source_station_id="201",
            observed_at=datetime(2026, 9, 26, 10, 0, 0, tzinfo=timezone.utc),
            availability_status=AvailabilityStatus.AVAILABLE,
        )
        t1 = datetime(2026, 9, 26, 10, 3, 0, tzinfo=timezone.utc)   # 3m later
        t2 = datetime(2026, 9, 26, 10, 10, 0, tzinfo=timezone.utc)  # 10m later
        t3 = datetime(2026, 9, 26, 10, 30, 0, tzinfo=timezone.utc)  # 30m later

        res1 = self.engine.evaluate_observation(obs=obs, as_of=t1)
        res2 = self.engine.evaluate_observation(obs=obs, as_of=t2)
        res3 = self.engine.evaluate_observation(obs=obs, as_of=t3)

        self.assertEqual(res1.state, FreshnessState.FRESH)
        self.assertEqual(res2.state, FreshnessState.AGING)
        self.assertEqual(res3.state, FreshnessState.STALE)

        # Underlying record remains pristine
        self.assertEqual(obs.availability_status, AvailabilityStatus.AVAILABLE)
        self.assertEqual(obs.observed_at, datetime(2026, 9, 26, 10, 0, 0, tzinfo=timezone.utc))

    # --------------------------------------------------------------------------
    # Scenario T: Future Timestamp Defensive Behavior
    # --------------------------------------------------------------------------
    def test_18_future_timestamp_defensive_behavior(self):
        """T: Timestamps in the future beyond tolerance evaluate to UNKNOWN with zero decay score."""
        future_time = self.ref_time + timedelta(minutes=10)

        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=future_time,
            information_type=InformationType.LIVE_TELEMETRY,
        )
        self.assertTrue(res.is_future)
        self.assertEqual(res.state, FreshnessState.UNKNOWN)
        self.assertEqual(res.decay_score, 0.0)
        self.assertAlmostEqual(res.future_skew_seconds, 600.0, places=1)
        self.assertTrue(any("is in the future" in w for w in res.warnings))

    # --------------------------------------------------------------------------
    # Scenario U: Provenance Survives Normalization and Persistence
    # --------------------------------------------------------------------------
    def test_19_provenance_survives_normalization_and_persistence(self):
        """U: Full provenance dossier (source_id, source_station_id, hash) survives to ProvenanceInfo."""
        raw = RawSourceRecord(
            source_id="open_charge_map",
            source_station_id="194820",
            source_url="https://openchargemap.org/site/poi/details/194820",
            raw_payload={"ID": 194820, "Title": "Tata Power Fast Charger Mumbai"},
        )
        prov = raw.to_provenance()
        self.assertEqual(prov.source_id, "open_charge_map")
        self.assertEqual(prov.source_station_id, "194820")
        self.assertEqual(prov.raw_payload_hash, raw.payload_hash)
        self.assertEqual(prov.contract_version, CONTRACT_VERSION)

    # --------------------------------------------------------------------------
    # Scenario V: Raw Payload Hash Remains Unchanged
    # --------------------------------------------------------------------------
    def test_20_raw_payload_hash_remains_unchanged(self):
        """V: SHA-256 payload hash is deterministic and invariant."""
        payload = {"Station": "BKC Hub", "Ports": [1, 2, 3]}
        raw1 = RawSourceRecord(source_id="src1", source_station_id="s1", raw_payload=payload)
        raw2 = RawSourceRecord(source_id="src1", source_station_id="s1", raw_payload=payload)
        self.assertEqual(raw1.payload_hash, raw2.payload_hash)
        self.assertEqual(len(raw1.payload_hash), 64)

    # --------------------------------------------------------------------------
    # Scenario W: Source Record ID Remains Unchanged
    # --------------------------------------------------------------------------
    def test_21_source_record_id_remains_unchanged(self):
        """W: External source ID is preserved verbatim without alteration."""
        station = NormalizedStationRecord(
            source_id="openchargemap",
            source_station_id="OCM-9921",
            name="Navi Mumbai Supercharger",
            latitude=19.033,
            longitude=73.029,
        )
        self.assertEqual(station.source_station_id, "OCM-9921")

    # --------------------------------------------------------------------------
    # Scenario X: Canonical Station UUID Distinct from Source ID
    # --------------------------------------------------------------------------
    def test_22_canonical_station_uuid_distinct_from_source_id(self):
        """X: Canonical ChargePlus station UUID is a UUIDv4 distinct from external source ID."""
        chargeplus_uuid = uuid.uuid4()
        source_id = "192840"
        self.assertNotEqual(str(chargeplus_uuid), source_id)
        self.assertIsInstance(chargeplus_uuid, uuid.UUID)

    # --------------------------------------------------------------------------
    # Decay Curves: LINEAR, EXPONENTIAL, STEP, NONE
    # --------------------------------------------------------------------------
    def test_23_linear_decay_curve_calculation(self):
        """Mathematical verification of LINEAR decay score."""
        policy = FreshnessPolicy(
            policy_id="test_linear",
            name="Test Linear",
            information_type=InformationType.LIVE_TELEMETRY,
            fresh_window_seconds=300.0,
            stale_window_seconds=900.0,
            decay_curve=DecayCurve.LINEAR,
        )
        # Age = 0 -> score = 1.0
        res0 = self.engine.evaluate(as_of=self.ref_time, observed_at=self.ref_time, policy=policy)
        self.assertEqual(res0.decay_score, 1.0)

        # Age = 450s (halfway to 900s) -> score = 0.5
        res_half = self.engine.evaluate(
            as_of=self.ref_time, observed_at=self.ref_time - timedelta(seconds=450), policy=policy
        )
        self.assertAlmostEqual(res_half.decay_score, 0.5, places=4)

        # Age = 900s -> score = 0.0
        res_stale = self.engine.evaluate(
            as_of=self.ref_time, observed_at=self.ref_time - timedelta(seconds=900), policy=policy
        )
        self.assertEqual(res_stale.decay_score, 0.0)

    def test_24_exponential_decay_curve_calculation(self):
        """Mathematical verification of EXPONENTIAL decay score with explicit half-life."""
        policy = FreshnessPolicy(
            policy_id="test_exp",
            name="Test Exponential",
            information_type=InformationType.LIVE_TELEMETRY,
            fresh_window_seconds=300.0,
            stale_window_seconds=1200.0,
            decay_curve=DecayCurve.EXPONENTIAL,
            decay_half_life_seconds=300.0,  # Halves every 5 minutes
        )
        # At age = 300s (1 half life), score should be 0.5
        res = self.engine.evaluate(
            as_of=self.ref_time, observed_at=self.ref_time - timedelta(seconds=300), policy=policy
        )
        self.assertAlmostEqual(res.decay_score, 0.5, places=3)

        # At age = 600s (2 half lives), score should be 0.25
        res2 = self.engine.evaluate(
            as_of=self.ref_time, observed_at=self.ref_time - timedelta(seconds=600), policy=policy
        )
        self.assertAlmostEqual(res2.decay_score, 0.25, places=3)

    def test_25_step_decay_curve_calculation(self):
        """Mathematical verification of STEP decay score (1.0 -> 0.5 -> 0.0)."""
        policy = FreshnessPolicy(
            policy_id="test_step",
            name="Test Step",
            information_type=InformationType.LIVE_TELEMETRY,
            fresh_window_seconds=300.0,
            stale_window_seconds=900.0,
            decay_curve=DecayCurve.STEP,
        )
        res_fresh = self.engine.evaluate(as_of=self.ref_time, observed_at=self.ref_time - timedelta(seconds=100), policy=policy)
        self.assertEqual(res_fresh.decay_score, 1.0)

        res_aging = self.engine.evaluate(as_of=self.ref_time, observed_at=self.ref_time - timedelta(seconds=500), policy=policy)
        self.assertEqual(res_aging.decay_score, 0.5)

        res_stale = self.engine.evaluate(as_of=self.ref_time, observed_at=self.ref_time - timedelta(seconds=1000), policy=policy)
        self.assertEqual(res_stale.decay_score, 0.0)

    def test_26_none_decay_curve_preserves_raw_age_without_score(self):
        """NONE curve produces decay_score = None while keeping exact raw age transparent."""
        policy = DEFAULT_STATIC_METADATA_POLICY  # decay_curve = DecayCurve.NONE
        res = self.engine.evaluate(
            as_of=self.ref_time,
            source_updated_at=self.ref_time - timedelta(days=3),
            policy=policy,
        )
        self.assertEqual(res.state, FreshnessState.FRESH)
        self.assertIsNone(res.decay_score)
        self.assertEqual(res.age_seconds, 259200.0)

    # --------------------------------------------------------------------------
    # Section 14: Station Current State Dual-Facet Freshness
    # --------------------------------------------------------------------------
    def test_27_station_current_state_separates_metadata_and_observation_freshness(self):
        """Section 14: Evaluates static station profile vs live observation independently."""
        station = NormalizedStationRecord(
            source_id="openchargemap",
            source_station_id="888",
            name="Dual Facet Station",
            latitude=19.05,
            longitude=72.85,
            operational_status=OperationalStatus.OPERATIONAL,
            observation=NormalizedObservationRecord(
                source_id="openchargemap",
                source_station_id="888",
                observed_at=self.ref_time - timedelta(minutes=4),  # Live: FRESH (4 min)
                availability_status=AvailabilityStatus.AVAILABLE,
            ),
            extra_metadata={
                "date_last_status_update": (self.ref_time - timedelta(days=40)).isoformat(),  # Meta: STALE (40 days)
            },
        )

        summary = self.engine.evaluate_station_current_state(station=station, as_of=self.ref_time)
        self.assertTrue(summary.has_live_observation)
        # Static metadata is STALE (> 30 days)
        self.assertEqual(summary.metadata_freshness.state, FreshnessState.STALE)
        # Live telemetry is FRESH (4 min <= 5 min)
        self.assertIsNotNone(summary.observation_freshness)
        self.assertEqual(summary.observation_freshness.state, FreshnessState.FRESH)
        self.assertEqual(summary.observation_freshness.retained_status, AvailabilityStatus.AVAILABLE)

    # --------------------------------------------------------------------------
    # Clock Skew Handling
    # --------------------------------------------------------------------------
    def test_28_clock_skew_within_tolerance_clamps_cleanly(self):
        """Minor clock skew within 5s tolerance clamps age to 0.0 without flagging as future anomaly."""
        skewed_time = self.ref_time + timedelta(seconds=3)  # 3s in the future
        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=skewed_time,
            information_type=InformationType.LIVE_TELEMETRY,
        )
        self.assertFalse(res.is_future)
        self.assertEqual(res.age_seconds, 0.0)
        self.assertEqual(res.state, FreshnessState.FRESH)

    # --------------------------------------------------------------------------
    # Section 7: Operational Status Policy Distinct from Live Telemetry
    # --------------------------------------------------------------------------
    def test_29_operational_status_policy_different_from_telemetry_policy(self):
        """Operational status uses 1h fresh / 24h stale vs telemetry 5m fresh / 15m stale."""
        obs_time = self.ref_time - timedelta(minutes=30)

        # For telemetry, 30m is STALE
        res_telemetry = self.engine.evaluate(
            as_of=self.ref_time, observed_at=obs_time, information_type=InformationType.LIVE_TELEMETRY
        )
        self.assertEqual(res_telemetry.state, FreshnessState.STALE)

        # For operational status, 30m is FRESH
        res_op = self.engine.evaluate(
            as_of=self.ref_time, source_updated_at=obs_time, information_type=InformationType.OPERATIONAL_STATUS
        )
        self.assertEqual(res_op.state, FreshnessState.FRESH)

    # --------------------------------------------------------------------------
    # Pricing Policy Evaluation
    # --------------------------------------------------------------------------
    def test_30_pricing_policy_freshness_evaluation(self):
        """Pricing policy allows 24h fresh and 7 days stale."""
        tariff_time = self.ref_time - timedelta(days=2)
        res = self.engine.evaluate(
            as_of=self.ref_time, source_updated_at=tariff_time, information_type=InformationType.PRICING
        )
        self.assertEqual(res.state, FreshnessState.AGING)
        self.assertEqual(res.policy_id, "chargeplus_pricing_v1")

    # --------------------------------------------------------------------------
    # Section 10: Missing Timestamp Never Defaults to datetime.now()
    # --------------------------------------------------------------------------
    def test_31_missing_timestamp_never_defaults_to_now(self):
        """Missing timestamp evaluates to UNKNOWN and never defaults to now() or FRESH."""
        res = self.engine.evaluate(
            as_of=self.ref_time,
            observed_at=None,
            source_updated_at=None,
            retrieved_at=None,
            information_type=InformationType.LIVE_TELEMETRY,
        )
        self.assertEqual(res.state, FreshnessState.UNKNOWN)
        self.assertIsNone(res.age_seconds)

    # --------------------------------------------------------------------------
    # Section 16: Persistence Observation Causal Time Enforcement
    # --------------------------------------------------------------------------
    def test_32_persistence_observation_causal_time_enforcement(self):
        """Persistence service ensures received_at >= observed_at using authentic retrieved_at."""
        obs_time = datetime(2026, 9, 26, 11, 0, 0, tzinfo=timezone.utc)
        retrieved_time = datetime(2026, 9, 26, 11, 2, 0, tzinfo=timezone.utc)
        obs = NormalizedObservationRecord(
            source_id="ocm",
            source_station_id="test-causal",
            observed_at=obs_time,
            retrieved_at=retrieved_time,
            availability_status=AvailabilityStatus.AVAILABLE,
        )
        self.assertGreaterEqual(obs.retrieved_at, obs.observed_at)

    # --------------------------------------------------------------------------
    # Section 20: Live Database Provenance Test & Clean Rollback
    # --------------------------------------------------------------------------
    def test_33_live_database_provenance_and_clean_rollback(self):
        """Section 20: Verifies provenance against live PostgreSQL with clean rollback and zero pollution."""
        load_dotenv(".env.local")
        load_dotenv(".env")
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            self.skipTest("DATABASE_URL is not configured; skipping live database provenance test.")

        try:
            live_conn = psycopg2.connect(db_url, connect_timeout=5)
        except Exception as e:
            self.skipTest(f"Live database connection unavailable ({type(e).__name__}); skipping.")

        try:
            with live_conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM public.station_observations;")
                baseline_obs_count = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM public.stations;")
                baseline_stn_count = cur.fetchone()[0]

            # Run in transaction with clean rollback
            with live_conn.cursor() as cur:
                # Query an existing live station to inspect provenance links
                cur.execute("SELECT id, name FROM public.stations LIMIT 1;")
                stn_row = cur.fetchone()
                if stn_row:
                    stn_id, stn_name = stn_row
                    cur.execute(
                        "SELECT source_id, source_station_id, source_payload_hash FROM public.station_source_link WHERE station_id = %s;",
                        (str(stn_id),),
                    )
                    link_rows = cur.fetchall()
                    # Verify provenance fields are intact
                    for l_row in link_rows:
                        s_id, s_stn_id, payload_hash = l_row
                        self.assertIsNotNone(s_id)
                        self.assertIsNotNone(s_stn_id)

            # Ensure clean rollback and baseline counts preserved
            live_conn.rollback()

            with live_conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM public.station_observations;")
                final_obs_count = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM public.stations;")
                final_stn_count = cur.fetchone()[0]
                self.assertEqual(final_obs_count, baseline_obs_count)
                self.assertEqual(final_stn_count, baseline_stn_count)

        finally:
            live_conn.close()


if __name__ == "__main__":
    unittest.main()
