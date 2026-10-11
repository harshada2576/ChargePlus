"""ChargePlus — Canonical Deduplication & Source Merging Unit Tests.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.7 (Canonical Deduplication Decision Layer & Source Merging)

Verifies all 36 mandatory deduplication & survivorship test requirements across 11 sections:
Section A: Basic Identity (Tests 1-3)
Section B: Validation Gating (Tests 4-7)
Section C: Field Survivorship (Tests 8-12)
Section D: Coordinates (Tests 13-15)
Section E: Connectors (Tests 16-18)
Section F: Operators (Tests 19-21)
Section G: Pricing (Tests 22-24)
Section H: Multi-Source Clusters (Tests 25-27)
Section I: Existing Canonical Stations (Tests 28-30)
Section J: Determinism & Idempotence (Tests 31-33)
Section K: Provenance & Architecture (Tests 34-36)
"""

import copy
import json
import random
import unittest
from typing import Optional

from backend.ingestion.constants import (
    OperationalStatus,
    PricingType,
    StandardConnectorType,
    ValidationOutcome,
)
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedStationRecord,
)
from backend.ingestion.deduplication import (
    CanonicalDecisionState,
    CanonicalDeduplicationEngine,
    CanonicalResolutionDecision,
    ExistingCanonicalStation,
    FieldSurvivorshipDecision,
    FieldSurvivorshipPolicy,
    SurvivorshipStrategy,
)
from backend.ingestion.validation import (
    DataQualityValidator,
    QualityFinding,
    QualityRuleCategory,
    QualitySeverity,
    ValidationResult,
)


def _make_record(
    source_id: str,
    source_station_id: str,
    name: str = "BKC Charging Hub",
    latitude: float = 19.0657,
    longitude: float = 72.8688,
    operator_name: Optional[str] = "Tata Power EZ Charge",
    operator_slug: Optional[str] = "tata-power",
    address_line: Optional[str] = "G Block BKC",
    locality: Optional[str] = "Bandra Kurla Complex",
    postal_code: Optional[str] = "400051",
    connectors: Optional[list[NormalizedConnectorRecord]] = None,
    extra_metadata: Optional[dict] = None,
) -> NormalizedStationRecord:
    """Constructs a normalized station record for testing."""
    if connectors is None:
        connectors = [
            NormalizedConnectorRecord(
                connector_type=StandardConnectorType.CCS2.value,
                raw_connector_type="CCS (Type 2)",
                power_kw=60.0,
                quantity=2,
                pricing_type=PricingType.PAID,
                price_per_kwh=18.5,
            )
        ]

    return NormalizedStationRecord(
        source_id=source_id,
        source_station_id=source_station_id,
        name=name,
        operator_name=operator_name,
        operator_slug=operator_slug,
        latitude=latitude,
        longitude=longitude,
        address_line=address_line,
        locality=locality,
        postal_code=postal_code,
        city="Mumbai",
        state="Maharashtra",
        country="India",
        connectors=connectors,
        extra_metadata=extra_metadata or {},
    )


class TestCanonicalDeduplication(unittest.TestCase):
    """ChargePlus Step 2.7 Canonical Deduplication Suite."""

    # ==========================================================================
    # Section A: Basic Identity (Tests 1-3)
    # ==========================================================================

    def test_01_strong_pairwise_match_merges(self):
        """1. Strong pairwise match across sources produces MERGE."""
        rec_ocm = _make_record("open_charge_map", "ocm_1001", name="Tata Power BKC", latitude=19.06570, longitude=72.86880)
        rec_osm = _make_record("open_street_map", "osm_2001", name="Tata Power BKC Hub", latitude=19.06572, longitude=72.86882)

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec_ocm, rec_osm])
        self.assertEqual(len(decisions), 1)
        d = decisions[0]
        self.assertEqual(d.decision_state, CanonicalDecisionState.MERGE)
        self.assertEqual(len(d.participating_source_identities), 2)
        self.assertFalse(d.is_blocked)
        self.assertIn("concordance", d.reasons[0].lower())

    def test_02_clear_geographic_separation_keeps_separate(self):
        """2. Clear geographic separation (> 200m) keeps records distinct."""
        rec_bkc = _make_record("open_charge_map", "ocm_bkc", name="Tata Power BKC", latitude=19.0657, longitude=72.8688)
        rec_andheri = _make_record("open_street_map", "osm_andheri", name="Tata Power Andheri", latitude=19.1197, longitude=72.8464)

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec_bkc, rec_andheri])
        self.assertEqual(len(decisions), 2)
        for d in decisions:
            self.assertEqual(d.decision_state, CanonicalDecisionState.KEEP_SEPARATE)
            self.assertEqual(len(d.participating_source_identities), 1)
            self.assertFalse(d.is_blocked)

    def test_03_ambiguous_identity_triggers_review(self):
        """3. Ambiguous identity resolution evidence yields REVIEW."""
        # Co-located but completely different station names and unknown operator
        rec_a = _make_record("open_charge_map", "ocm_ambig", name="Metro Station Gate 1 Charger", latitude=19.06570, longitude=72.86880, operator_name=None, operator_slug=None)
        rec_b = _make_record("open_street_map", "osm_ambig", name="Hotel Parking EV Point", latitude=19.06580, longitude=72.86885, operator_name=None, operator_slug=None)

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec_a, rec_b])
        # Should be grouped as candidate and flagged for REVIEW due to ambiguous match
        ambig_decision = [d for d in decisions if d.decision_state == CanonicalDecisionState.REVIEW]
        self.assertTrue(len(ambig_decision) >= 1)
        self.assertTrue(any("ambiguous" in c.lower() for c in ambig_decision[0].conflicts + ambig_decision[0].reasons))

    # ==========================================================================
    # Section B: Validation Gating (Tests 4-7)
    # ==========================================================================

    def test_04_reject_record_cannot_merge(self):
        """4. REJECT records cannot participate in canonical merging and are blocked."""
        rec_valid = _make_record("open_charge_map", "ocm_valid", name="BKC Supercharger", latitude=19.0657, longitude=72.8688)
        rec_invalid = _make_record("open_street_map", "osm_invalid", name="BKC Supercharger", latitude=19.0657, longitude=72.8688)

        # Explicitly inject REJECT result
        val_map = {
            ("open_charge_map", "ocm_valid"): ValidationResult(
                outcome=ValidationOutcome.ACCEPT, is_valid=True, quality_score=1.0
            ),
            ("open_street_map", "osm_invalid"): ValidationResult(
                outcome=ValidationOutcome.REJECT, is_valid=False, quality_score=0.0,
                errors=["Station name too short"]
            ),
        }

        decisions = CanonicalDeduplicationEngine.evaluate_records(
            [rec_valid, rec_invalid], validation_results=val_map
        )
        self.assertEqual(len(decisions), 2)
        # Invalid must be isolated as KEEP_SEPARATE and blocked
        d_invalid = next(d for d in decisions if ("open_street_map", "osm_invalid") in d.participating_source_identities)
        self.assertTrue(d_invalid.is_blocked)
        self.assertEqual(d_invalid.decision_state, CanonicalDecisionState.KEEP_SEPARATE)
        self.assertIn("rejected", d_invalid.reasons[0].lower())

    def test_05_quarantine_record_cannot_become_canonical(self):
        """5. QUARANTINE records cannot silently become canonical operational data."""
        rec_quar = _make_record("open_charge_map", "ocm_quar", name="BKC Fast Charge")
        val_map = {
            ("open_charge_map", "ocm_quar"): ValidationResult(
                outcome=ValidationOutcome.QUARANTINE, is_valid=False, quality_score=0.4,
                warnings=["Severe coordinate drift suspicion"],
                quarantine_reasons=["Suspicious coordinates"]
            ),
        }

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec_quar], validation_results=val_map)
        self.assertEqual(len(decisions), 1)
        d = decisions[0]
        self.assertEqual(d.decision_state, CanonicalDecisionState.REVIEW)
        self.assertTrue(d.is_blocked)
        self.assertIsNone(d.canonical_station_id)
        self.assertIn("quarantined", d.conflicts[0].lower())

    def test_06_accept_with_warnings_can_merge(self):
        """6. ACCEPT_WITH_WARNINGS records can merge when identity evidence is strong."""
        rec_a = _make_record("open_charge_map", "ocm_warn", name="BKC Charger", latitude=19.0657, longitude=72.8688)
        rec_b = _make_record("open_street_map", "osm_warn", name="BKC Charger", latitude=19.0657, longitude=72.8688)
        val_map = {
            ("open_charge_map", "ocm_warn"): ValidationResult(
                outcome=ValidationOutcome.ACCEPT_WITH_WARNINGS, is_valid=True, quality_score=0.85,
                warnings=["Missing phone number"]
            ),
            ("open_street_map", "osm_warn"): ValidationResult(
                outcome=ValidationOutcome.ACCEPT, is_valid=True, quality_score=1.0
            ),
        }

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec_a, rec_b], validation_results=val_map)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].decision_state, CanonicalDecisionState.MERGE)
        self.assertFalse(decisions[0].is_blocked)

    def test_07_accept_records_merge(self):
        """7. Clean ACCEPT records merge normally."""
        rec_a = _make_record("open_charge_map", "ocm_clean", name="BKC Charger", latitude=19.0657, longitude=72.8688)
        rec_b = _make_record("open_street_map", "osm_clean", name="BKC Charger", latitude=19.0657, longitude=72.8688)

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec_a, rec_b])
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].decision_state, CanonicalDecisionState.MERGE)

    # ==========================================================================
    # Section C: Field Survivorship (Tests 8-12)
    # ==========================================================================

    def test_08_identical_field_values_deterministic_canonical(self):
        """8. Identical field values yield unanimous canonical resolution."""
        rec_a = _make_record("open_charge_map", "ocm_id", name="Tata Power BKC", latitude=19.0657, longitude=72.8688)
        rec_b = _make_record("open_street_map", "osm_id", name="Tata Power BKC", latitude=19.0657, longitude=72.8688)

        name_surv = FieldSurvivorshipPolicy.resolve_name([rec_a, rec_b], {})
        self.assertEqual(name_surv.canonical_value, "Tata Power BKC")
        self.assertEqual(name_surv.strategy_used, SurvivorshipStrategy.UNANIMOUS_AGREEMENT)
        self.assertFalse(name_surv.has_conflict)

        coord_surv = FieldSurvivorshipPolicy.resolve_coordinates([rec_a, rec_b], {})
        self.assertEqual(coord_surv.canonical_value, (19.0657, 72.8688))
        self.assertEqual(coord_surv.strategy_used, SurvivorshipStrategy.UNANIMOUS_AGREEMENT)

    def test_09_one_source_missing_is_non_conflict(self):
        """9. Missing in one source is not a conflict (Missing != Conflict)."""
        rec_a = _make_record("open_charge_map", "ocm_op", operator_name="Tata Power", operator_slug="tata-power")
        rec_b = _make_record("open_street_map", "osm_noop", operator_name=None, operator_slug=None)

        op_surv = FieldSurvivorshipPolicy.resolve_operator([rec_a, rec_b])
        self.assertFalse(op_surv.has_conflict)
        self.assertFalse(op_surv.is_review_required)
        self.assertEqual(op_surv.canonical_value, {"name": "Tata Power", "slug": "tata-power"})
        self.assertEqual(op_surv.strategy_used, SurvivorshipStrategy.SINGLE_REPORTING_SOURCE)

    def test_10_conflicting_field_values_no_precedence_triggers_review(self):
        """10. Conflicting field values with no justified precedence trigger REVIEW."""
        # Source A says ₹15/kWh, Source B says ₹25/kWh (unreconciled paid rates)
        rec_a = _make_record("open_charge_map", "ocm_p1", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", pricing_type=PricingType.PAID, price_per_kwh=15.0)
        ])
        rec_b = _make_record("open_street_map", "osm_p2", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", pricing_type=PricingType.PAID, price_per_kwh=25.0)
        ])

        p_surv = FieldSurvivorshipPolicy.resolve_pricing([rec_a, rec_b])
        self.assertTrue(p_surv.has_conflict)
        self.assertTrue(p_surv.is_review_required)
        self.assertEqual(p_surv.strategy_used, SurvivorshipStrategy.CONFLICT_UNRESOLVED)
        self.assertIsNone(p_surv.canonical_value)

    def test_11_justified_field_policy_deterministic_selection(self):
        """11. Justified field policies select deterministically (e.g. longest name with quality tiebreaker)."""
        rec_short = _make_record("open_charge_map", "ocm_short", name="Tata BKC")
        rec_long = _make_record("open_street_map", "osm_long", name="Tata Power EZ Charge BKC Hub")
        scores = {"open_charge_map:ocm_short": 0.9, "open_street_map:osm_long": 0.95}

        name_surv = FieldSurvivorshipPolicy.resolve_name([rec_short, rec_long], scores)
        self.assertEqual(name_surv.canonical_value, "Tata Power EZ Charge BKC Hub")
        self.assertEqual(name_surv.strategy_used, SurvivorshipStrategy.MOST_COMPLETE_VALUE)
        self.assertEqual(name_surv.contributing_source_id, "open_street_map")

    def test_12_source_provenance_retained(self):
        """12. Field survivorship preserves complete provenance in participating_values."""
        rec_a = _make_record("open_charge_map", "ocm_prov", name="Hub A")
        rec_b = _make_record("open_street_map", "osm_prov", name="Hub B")

        name_surv = FieldSurvivorshipPolicy.resolve_name([rec_a, rec_b], {})
        self.assertIn("open_charge_map:ocm_prov", name_surv.participating_values)
        self.assertIn("open_street_map:osm_prov", name_surv.participating_values)
        self.assertEqual(name_surv.participating_values["open_charge_map:ocm_prov"], "Hub A")
        self.assertEqual(name_surv.participating_values["open_street_map:osm_prov"], "Hub B")

    # ==========================================================================
    # Section D: Coordinates (Tests 13-15)
    # ==========================================================================

    def test_13_close_coordinates_safe_deterministic_handling(self):
        """13. Close coordinates (<= 50m) select deterministically from highest quality source."""
        rec_a = _make_record("open_charge_map", "ocm_c1", latitude=19.06570, longitude=72.86880)
        rec_b = _make_record("open_street_map", "osm_c2", latitude=19.06575, longitude=72.86885) # ~7m away
        scores = {"open_charge_map:ocm_c1": 0.8, "open_street_map:osm_c2": 0.95}

        coord_surv = FieldSurvivorshipPolicy.resolve_coordinates([rec_a, rec_b], scores)
        self.assertFalse(coord_surv.has_conflict)
        self.assertEqual(coord_surv.strategy_used, SurvivorshipStrategy.HIGHEST_QUALITY_SCORE)
        self.assertEqual(coord_surv.canonical_value, (19.06575, 72.86885))
        self.assertEqual(coord_surv.contributing_source_id, "open_street_map")

    def test_14_material_coordinate_conflict_triggers_review(self):
        """14. Material coordinate conflict (> 50m) triggers REVIEW."""
        rec_a = _make_record("open_charge_map", "ocm_far1", latitude=19.06570, longitude=72.86880)
        rec_b = _make_record("open_street_map", "osm_far2", latitude=19.06640, longitude=72.86880) # ~78m away

        coord_surv = FieldSurvivorshipPolicy.resolve_coordinates([rec_a, rec_b], {})
        self.assertTrue(coord_surv.has_conflict)
        self.assertTrue(coord_surv.is_review_required)
        self.assertEqual(coord_surv.strategy_used, SurvivorshipStrategy.CONFLICT_UNRESOLVED)
        self.assertIsNone(coord_surv.canonical_value)

    def test_15_no_unexplained_coordinate_averaging(self):
        """15. Coordinates are never averaged into a synthetic midpoint."""
        lat_a, lon_a = 19.06570, 72.86880
        lat_b, lon_b = 19.06578, 72.86888
        mid_lat = (lat_a + lat_b) / 2.0
        mid_lon = (lon_a + lon_b) / 2.0

        rec_a = _make_record("open_charge_map", "ocm_mid", latitude=lat_a, longitude=lon_a)
        rec_b = _make_record("open_street_map", "osm_mid", latitude=lat_b, longitude=lon_b)

        coord_surv = FieldSurvivorshipPolicy.resolve_coordinates([rec_a, rec_b], {})
        canon_lat, canon_lon = coord_surv.canonical_value
        # Must match either rec_a or rec_b exactly, never midpoint
        self.assertTrue((canon_lat == lat_a and canon_lon == lon_a) or (canon_lat == lat_b and canon_lon == lon_b))
        self.assertNotAlmostEqual(canon_lat, mid_lat, places=7)

    # ==========================================================================
    # Section E: Connectors (Tests 16-18)
    # ==========================================================================

    def test_16_same_connector_not_double_counted(self):
        """16. Identical connector described by multiple sources is not double counted."""
        rec_a = _make_record("open_charge_map", "ocm_conn1", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2)
        ])
        rec_b = _make_record("open_street_map", "osm_conn2", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2)
        ])

        conn_surv = FieldSurvivorshipPolicy.resolve_connectors([rec_a, rec_b])
        self.assertEqual(len(conn_surv.canonical_value), 1)
        self.assertEqual(conn_surv.canonical_value[0]["quantity"], 2) # NOT 4!
        self.assertEqual(conn_surv.strategy_used, SurvivorshipStrategy.DEDUPLICATED_SET)

    def test_17_differing_connector_quantities_do_not_sum(self):
        """17. Differing connector quantities take maximum observed without blind summation."""
        rec_a = _make_record("open_charge_map", "ocm_q2", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2)
        ])
        rec_b = _make_record("open_street_map", "osm_q1", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=1)
        ])

        conn_surv = FieldSurvivorshipPolicy.resolve_connectors([rec_a, rec_b])
        self.assertEqual(len(conn_surv.canonical_value), 1)
        self.assertEqual(conn_surv.canonical_value[0]["quantity"], 2) # max(2, 1) = 2, NEVER 3!

    def test_18_incompatible_connector_evidence_triggers_review(self):
        """18. Incompatible connector signatures (disjoint types or conflicting power) trigger review."""
        rec_a = _make_record("open_charge_map", "ocm_p30", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=30.0, quantity=1)
        ])
        rec_b = _make_record("open_street_map", "osm_p350", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=350.0, quantity=1)
        ])

        conn_surv = FieldSurvivorshipPolicy.resolve_connectors([rec_a, rec_b])
        self.assertTrue(conn_surv.has_conflict)
        self.assertTrue(conn_surv.is_review_required)
        self.assertEqual(conn_surv.strategy_used, SurvivorshipStrategy.CONFLICT_UNRESOLVED)
        self.assertIsNone(conn_surv.canonical_value)

    # ==========================================================================
    # Section F: Operators (Tests 19-21)
    # ==========================================================================

    def test_19_operator_naming_variation_remains_same_station(self):
        """19. Operator naming variations that resolve to the same slug merge cleanly."""
        rec_a = _make_record("open_charge_map", "ocm_op1", operator_name="Tata Power", operator_slug="tata-power")
        rec_b = _make_record("open_street_map", "osm_op2", operator_name="Tata Power EZ Charge", operator_slug="tata-power")

        op_surv = FieldSurvivorshipPolicy.resolve_operator([rec_a, rec_b])
        self.assertFalse(op_surv.has_conflict)
        self.assertEqual(op_surv.canonical_value["slug"], "tata-power")
        self.assertEqual(op_surv.canonical_value["name"], "Tata Power EZ Charge") # picks most descriptive

    def test_20_operator_change_does_not_duplicate_station(self):
        """20. Operator change with temporal recency selects latest operator without duplicating station."""
        rec_old = _make_record("open_charge_map", "ocm_rebrand1", operator_name="Fortum Charge", operator_slug="fortum",
                               extra_metadata={"_temporal_recency_ts": 1650000000})
        rec_new = _make_record("open_street_map", "osm_rebrand2", operator_name="GLIDA", operator_slug="glida",
                               extra_metadata={"_temporal_recency_ts": 1700000000})

        op_surv = FieldSurvivorshipPolicy.resolve_operator([rec_old, rec_new])
        self.assertFalse(op_surv.has_conflict)
        self.assertEqual(op_surv.canonical_value["name"], "GLIDA")
        self.assertEqual(op_surv.strategy_used, SurvivorshipStrategy.EXPLICIT_FIELD_POLICY)

    def test_21_historical_operator_provenance_retained(self):
        """21. Historical operator provenance is preserved across sources."""
        rec_a = _make_record("open_charge_map", "ocm_hist", operator_name="Statiq", operator_slug="statiq")
        rec_b = _make_record("open_street_map", "osm_hist", operator_name="Jio-bp", operator_slug="jio-bp")

        op_surv = FieldSurvivorshipPolicy.resolve_operator([rec_a, rec_b])
        self.assertIn("open_charge_map:ocm_hist", op_surv.participating_values)
        self.assertIn("open_street_map:osm_hist", op_surv.participating_values)
        self.assertEqual(op_surv.participating_values["open_charge_map:ocm_hist"]["name"], "Statiq")
        self.assertEqual(op_surv.participating_values["open_street_map:osm_hist"]["name"], "Jio-bp")

    # ==========================================================================
    # Section G: Pricing (Tests 22-24)
    # ==========================================================================

    def test_22_missing_pricing_remains_unknown(self):
        """22. Missing pricing remains UNKNOWN, never converted to ₹0."""
        rec = _make_record("open_charge_map", "ocm_noprice", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", pricing_type=PricingType.UNKNOWN, price_per_kwh=None)
        ])

        p_surv = FieldSurvivorshipPolicy.resolve_pricing([rec])
        self.assertEqual(p_surv.canonical_value["pricing_type"], PricingType.UNKNOWN.value)
        self.assertIsNone(p_surv.canonical_value["price_per_kwh"])
        self.assertNotIn("0", str(p_surv.canonical_value["price_per_kwh"]))

    def test_23_explicit_free_remains_free(self):
        """23. Explicit FREE pricing is preserved as free."""
        rec = _make_record("open_charge_map", "ocm_free", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", pricing_type=PricingType.FREE, price_per_kwh=0.0)
        ])

        p_surv = FieldSurvivorshipPolicy.resolve_pricing([rec])
        self.assertEqual(p_surv.canonical_value["pricing_type"], PricingType.FREE.value)
        self.assertEqual(p_surv.canonical_value["price_per_kwh"], 0.0)

    def test_24_conflicting_prices_not_silently_resolved(self):
        """24. Conflicting prices (FREE vs PAID) trigger REVIEW and are not silently resolved."""
        rec_free = _make_record("open_charge_map", "ocm_free", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", pricing_type=PricingType.FREE, price_per_kwh=0.0)
        ])
        rec_paid = _make_record("open_street_map", "osm_paid", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", pricing_type=PricingType.PAID, price_per_kwh=18.0)
        ])

        p_surv = FieldSurvivorshipPolicy.resolve_pricing([rec_free, rec_paid])
        self.assertTrue(p_surv.has_conflict)
        self.assertTrue(p_surv.is_review_required)
        self.assertEqual(p_surv.strategy_used, SurvivorshipStrategy.CONFLICT_UNRESOLVED)

    # ==========================================================================
    # Section H: Multi-Source Clusters (Tests 25-27)
    # ==========================================================================

    def test_25_three_sources_concordant_forms_one_cluster(self):
        """25. Three sources (A, B, C) in mutual concordance form a single MERGE cluster."""
        rec_a = _make_record("open_charge_map", "ocm_1", name="BKC Hub", latitude=19.06570, longitude=72.86880)
        rec_b = _make_record("open_street_map", "osm_2", name="BKC Hub", latitude=19.06571, longitude=72.86881)
        rec_c = _make_record("cpo_direct", "cpo_3", name="BKC Charging Hub", latitude=19.06572, longitude=72.86882)

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec_a, rec_b, rec_c])
        self.assertEqual(len(decisions), 1)
        d = decisions[0]
        self.assertEqual(d.decision_state, CanonicalDecisionState.MERGE)
        self.assertEqual(len(d.participating_source_identities), 3)

    def test_26_transitive_contradiction_triggers_review(self):
        """26. Transitive contradiction (A matches B, B matches C, but A and C contradict) triggers REVIEW."""
        # A at origin
        rec_a = _make_record("open_charge_map", "ocm_a", name="Metro Station Hub", latitude=19.06570, longitude=72.86880)
        # B 25 meters east of A
        rec_b = _make_record("open_street_map", "osm_b", name="Metro Station Hub", latitude=19.06570, longitude=72.86905)
        # C 45 meters east of B, but 70 meters east of A (> 50m radius!)
        rec_c = _make_record("cpo_direct", "cpo_c", name="Metro Station Hub", latitude=19.06570, longitude=72.86950)

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec_a, rec_b, rec_c])
        # Multi-source cluster must NOT merge automatically when pair (A, C) contradicts!
        rev_decisions = [d for d in decisions if d.decision_state == CanonicalDecisionState.REVIEW]
        self.assertTrue(len(rev_decisions) >= 1)
        self.assertTrue(any("concordance" in c.lower() or "non-match" in c.lower() or "distance" in c.lower()
                            for c in rev_decisions[0].conflicts + rev_decisions[0].reasons))

    def test_27_deterministic_cluster_formation_independent_of_order(self):
        """27. Cluster formation and decision output are independent of input record ordering."""
        rec_a = _make_record("source_a", "id_1", name="Alpha Hub", latitude=19.0657, longitude=72.8688)
        rec_b = _make_record("source_b", "id_2", name="Alpha Hub", latitude=19.0657, longitude=72.8688)
        rec_c = _make_record("source_c", "id_3", name="Beta Hub", latitude=19.1197, longitude=72.8464)

        order1 = [rec_a, rec_b, rec_c]
        order2 = [rec_c, rec_b, rec_a]
        order3 = [rec_b, rec_a, rec_c]

        d1 = CanonicalDeduplicationEngine.evaluate_records(order1)
        d2 = CanonicalDeduplicationEngine.evaluate_records(order2)
        d3 = CanonicalDeduplicationEngine.evaluate_records(order3)

        self.assertEqual([d.cluster_id for d in d1], [d.cluster_id for d in d2])
        self.assertEqual([d.cluster_id for d in d1], [d.cluster_id for d in d3])
        self.assertEqual([d.decision_state for d in d1], [d.decision_state for d in d2])

    # ==========================================================================
    # Section I: Existing Canonical Stations (Tests 28-30)
    # ==========================================================================

    def test_28_source_record_links_to_existing_canonical(self):
        """28. Source record matching an established canonical station produces LINK_TO_CANONICAL."""
        canon = ExistingCanonicalStation(
            canonical_station_id="11111111-2222-3333-4444-555555555555",
            name="BKC Fast Charger",
            operator_name="Tata Power EZ Charge",
            operator_slug="tata-power",
            latitude=19.06570,
            longitude=72.86880,
            source_links=[("open_charge_map", "ocm_linked")],
        )
        rec = _make_record("open_charge_map", "ocm_linked", name="BKC Fast Charger", latitude=19.06570, longitude=72.86880)

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec], existing_canonical_stations=[canon])
        self.assertEqual(len(decisions), 1)
        d = decisions[0]
        self.assertEqual(d.decision_state, CanonicalDecisionState.LINK_TO_CANONICAL)
        self.assertEqual(d.canonical_station_id, "11111111-2222-3333-4444-555555555555")

    def test_29_ambiguous_between_two_canonical_stations_triggers_review(self):
        """29. Source record ambiguous between two existing canonical stations triggers REVIEW."""
        canon1 = ExistingCanonicalStation(
            canonical_station_id="aaaa1111-0000-0000-0000-000000000001",
            name="BKC Plaza Station A",
            latitude=19.06570,
            longitude=72.86880,
        )
        canon2 = ExistingCanonicalStation(
            canonical_station_id="bbbb2222-0000-0000-0000-000000000002",
            name="BKC Plaza Station B",
            latitude=19.06573,
            longitude=72.86883,
        )
        # Record right in between both (within 10m of both)
        rec = _make_record("open_street_map", "osm_ambig_canon", name="BKC Plaza Station", latitude=19.06571, longitude=72.86881)

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec], existing_canonical_stations=[canon1, canon2])
        self.assertEqual(len(decisions), 1)
        d = decisions[0]
        self.assertEqual(d.decision_state, CanonicalDecisionState.REVIEW)
        self.assertIsNone(d.canonical_station_id)
        self.assertTrue(any("multiple" in c.lower() for c in d.conflicts + d.reasons))

    def test_30_two_existing_canonical_stations_not_silently_collapsed(self):
        """30. Two existing canonical stations are never silently merged together."""
        canon1 = ExistingCanonicalStation(
            canonical_station_id="canon_1",
            name="East Wing Charger",
            latitude=19.06570,
            longitude=72.86880,
            source_links=[("open_charge_map", "ocm_east")],
        )
        canon2 = ExistingCanonicalStation(
            canonical_station_id="canon_2",
            name="West Wing Charger",
            latitude=19.06572,
            longitude=72.86882,
            source_links=[("open_street_map", "osm_west")],
        )
        rec1 = _make_record("open_charge_map", "ocm_east", name="East Wing Charger", latitude=19.06570, longitude=72.86880)
        rec2 = _make_record("open_street_map", "osm_west", name="West Wing Charger", latitude=19.06572, longitude=72.86882)

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec1, rec2], existing_canonical_stations=[canon1, canon2])
        # If clustered or linked, must NOT merge canon_1 and canon_2 into a single canonical station!
        for d in decisions:
            self.assertNotEqual(d.decision_state, CanonicalDecisionState.MERGE)

    # ==========================================================================
    # Section J: Determinism & Idempotence (Tests 31-33)
    # ==========================================================================

    def test_31_identical_input_twice_produces_identical_decision(self):
        """31. Running evaluation twice on identical inputs produces identical decisions."""
        rec_a = _make_record("open_charge_map", "ocm_det1", latitude=19.0657, longitude=72.8688)
        rec_b = _make_record("open_street_map", "osm_det2", latitude=19.0657, longitude=72.8688)

        run1 = CanonicalDeduplicationEngine.evaluate_records([rec_a, rec_b])
        run2 = CanonicalDeduplicationEngine.evaluate_records([rec_a, rec_b])

        self.assertEqual(run1[0].dict(), run2[0].dict())

    def test_32_shuffled_input_produces_identical_decision(self):
        """32. Shuffling input records produces identical cluster IDs and decisions."""
        records = [
            _make_record("source_1", f"stn_{i}", name=f"Hub {i}", latitude=19.0657 + (i * 0.05), longitude=72.8688)
            for i in range(10)
        ]
        shuffled = copy.deepcopy(records)
        random.seed(42)
        random.shuffle(shuffled)

        res_orig = CanonicalDeduplicationEngine.evaluate_records(records)
        res_shuf = CanonicalDeduplicationEngine.evaluate_records(shuffled)

        self.assertEqual([d.cluster_id for d in res_orig], [d.cluster_id for d in res_shuf])
        self.assertEqual([d.decision_state for d in res_orig], [d.decision_state for d in res_shuf])

    def test_33_repeated_execution_is_idempotent(self):
        """33. Repeated execution is completely idempotent with no state mutation."""
        rec = _make_record("open_charge_map", "ocm_idem")
        rec_copy = copy.deepcopy(rec)

        res1 = CanonicalDeduplicationEngine.evaluate_records([rec])
        res2 = CanonicalDeduplicationEngine.evaluate_records([rec])
        res3 = CanonicalDeduplicationEngine.evaluate_records([rec])

        self.assertEqual(res1[0].dict(), res2[0].dict())
        self.assertEqual(res2[0].dict(), res3[0].dict())
        self.assertEqual(rec.dict(), rec_copy.dict()) # Input untouched

    # ==========================================================================
    # Section K: Provenance & Architecture (Tests 34-36)
    # ==========================================================================

    def test_34_external_source_ids_preserved(self):
        """34. Participating external source IDs are preserved exactly in decision output."""
        rec_a = _make_record("open_charge_map", "ocm_ext_999")
        rec_b = _make_record("open_street_map", "osm_ext_888")

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec_a, rec_b])
        d = decisions[0]
        self.assertIn(("open_charge_map", "ocm_ext_999"), d.participating_source_identities)
        self.assertIn(("open_street_map", "osm_ext_888"), d.participating_source_identities)

    def test_35_canonical_identity_remains_distinct_from_source_id(self):
        """35. Canonical station reference is never set to an external source station ID."""
        rec = _make_record("open_charge_map", "ocm_source_key_123")
        decisions = CanonicalDeduplicationEngine.evaluate_records([rec])
        d = decisions[0]
        self.assertNotEqual(d.canonical_station_id, "ocm_source_key_123")
        self.assertIsNone(d.canonical_station_id) # For new records, persistence (2.8) assigns UUID

    def test_36_evidence_and_reasons_retained(self):
        """36. Entity-resolution evidence and structured decision reasons are retained and auditable."""
        rec_a = _make_record("open_charge_map", "ocm_audit_a", latitude=19.0657, longitude=72.8688)
        rec_b = _make_record("open_street_map", "osm_audit_b", latitude=19.0657, longitude=72.8688)

        decisions = CanonicalDeduplicationEngine.evaluate_records([rec_a, rec_b])
        d = decisions[0]
        self.assertTrue(len(d.reasons) > 0)
        self.assertTrue(len(d.pairwise_evidence) > 0)
        self.assertIn("coordinates", d.field_survivorship)
        self.assertIn("name", d.field_survivorship)
        self.assertIn("connectors", d.field_survivorship)
        self.assertTrue(len(d.field_survivorship["coordinates"].explanation) > 0)

    # ==========================================================================
    # Connector Survivorship Deep Audit Tests (Tests 37-39)
    # ==========================================================================

    def test_37_intra_source_multiple_connectors_not_undercounted(self):
        """37. Multiple connectors within one source (distinct IDs/entries) sum and do not collapse."""
        rec = _make_record(
            "open_charge_map",
            "ocm_multi_plug",
            connectors=[
                NormalizedConnectorRecord(
                    source_connector_id="plug_1",
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=120.0,
                    quantity=1,
                ),
                NormalizedConnectorRecord(
                    source_connector_id="plug_2",
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=120.0,
                    quantity=1,
                ),
            ],
        )

        conn_surv = FieldSurvivorshipPolicy.resolve_connectors([rec])
        self.assertEqual(len(conn_surv.canonical_value), 1)
        # Must be 2 (sum of intra-source distinct plugs), NEVER collapsed to 1!
        self.assertEqual(conn_surv.canonical_value[0]["quantity"], 2)

    def test_38_colocated_multi_tier_power_connectors_coexist(self):
        """38. Co-located multi-tier chargers (e.g. 60 kW and 120 kW CCS2) coexist cleanly without false conflict."""
        rec_a = _make_record(
            "open_charge_map",
            "ocm_tiered",
            connectors=[
                NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=1),
                NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=120.0, quantity=1),
            ],
        )
        rec_b = _make_record(
            "open_street_map",
            "osm_tiered",
            connectors=[
                NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=1),
                NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=120.0, quantity=1),
            ],
        )

        conn_surv = FieldSurvivorshipPolicy.resolve_connectors([rec_a, rec_b])
        self.assertFalse(conn_surv.has_conflict)
        self.assertFalse(conn_surv.is_review_required)
        self.assertEqual(len(conn_surv.canonical_value), 2)
        powers = sorted([c["power_kw"] for c in conn_surv.canonical_value])
        self.assertEqual(powers, [60.0, 120.0])

    def test_39_individual_ids_preserved_in_provenance_while_quantities_reconciled(self):
        """39. Source with individual IDs and source with aggregated count reconcile without double counting."""
        # Source A has 2 individually enumerated plugs
        rec_a = _make_record(
            "tata_power_api",
            "tp_hub",
            connectors=[
                NormalizedConnectorRecord(source_connector_id="TP_PLUG_1", connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=1),
                NormalizedConnectorRecord(source_connector_id="TP_PLUG_2", connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=1),
            ],
        )
        # Source B has aggregated description of 2 plugs
        rec_b = _make_record(
            "open_street_map",
            "osm_hub",
            connectors=[
                NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2),
            ],
        )

        conn_surv = FieldSurvivorshipPolicy.resolve_connectors([rec_a, rec_b])
        self.assertFalse(conn_surv.has_conflict)
        self.assertEqual(len(conn_surv.canonical_value), 1)
        self.assertEqual(conn_surv.canonical_value[0]["quantity"], 2) # max(2, 2) = 2, NEVER 4!
        # Provenance retains both individual IDs from Source A
        participating = conn_surv.participating_values
        tp_conns = participating["tata_power_api:tp_hub"]
        self.assertEqual(len(tp_conns), 2)
        self.assertEqual(tp_conns[0]["connector_id"], "TP_PLUG_1")
        self.assertEqual(tp_conns[1]["connector_id"], "TP_PLUG_2")


if __name__ == "__main__":
    unittest.main()

