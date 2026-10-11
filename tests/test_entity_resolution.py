"""ChargePlus — Cross-Source Entity Resolution Unit Tests.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.4 (Cross-Source Entity Resolution — Candidate Generation & Evidence Fusion)

Verifies all 14 mandatory entity-resolution requirements:
1.  Same physical station, strong multi-signal agreement => MATCH
2.  Clearly different stations => NON_MATCH
3.  Close coordinates but conflicting evidence => AMBIGUOUS
4.  Same name but far apart => NON_MATCH / not candidate
5.  Nearby stations with missing connector data => UNKNOWN, not disagreement
6.  Different operators but otherwise strong physical evidence => rebrand/takeover behavior
7.  Coordinate boundary around 50m => deterministic thresholding
8.  Identical coordinates but weak/conflicting metadata => not automatic MATCH
9.  Missing address/PIN => UNKNOWN rather than mismatch
10. Connector signature comparisons (identical, partial, conflicting)
11. Determinism: same inputs produce byte-for-byte identical evidence dossiers
12. Non-destructive guarantee: resolver does not mutate inputs or database
13. Multiple candidates: preserves ambiguity rather than arbitrary selection
14. Source identity preservation: external source IDs never become canonical UUIDs
"""

import copy
import json
import unittest
from typing import Optional

from backend.ingestion.constants import OperationalStatus, StandardConnectorType
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedStationRecord,
)
from backend.ingestion.resolution import (
    AddressEvidence,
    ConnectorEvidence,
    CrossSourceEntityResolver,
    EntityResolutionCandidate,
    EntityResolutionConfig,
    EvidenceSignal,
    GeoProximityEvidence,
    MatchState,
    NameSimilarityEvidence,
    OperatorEvidence,
    calculate_jaccard_similarity,
    calculate_levenshtein_ratio,
    calculate_token_sort_ratio,
    haversine_distance_meters,
    normalize_string_for_matching,
)


def _make_station(
    source_id: str,
    source_station_id: str,
    name: str,
    latitude: float,
    longitude: float,
    operator_name: Optional[str] = "Tata Power EZ Charge",
    operator_slug: Optional[str] = "tata-power",
    address_line: Optional[str] = "G Block BKC",
    locality: Optional[str] = "Bandra Kurla Complex",
    postal_code: Optional[str] = "400051",
    connectors: Optional[list[NormalizedConnectorRecord]] = None,
) -> NormalizedStationRecord:
    """Helper to construct a valid NormalizedStationRecord for resolution testing."""
    if connectors is None:
        connectors = [
            NormalizedConnectorRecord(
                connector_type=StandardConnectorType.CCS2.value,
                raw_connector_type="CCS (Type 2)",
                power_kw=50.0,
                quantity=2,
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
        operational_status=OperationalStatus.OPERATIONAL,
    )


class TestCrossSourceEntityResolution(unittest.TestCase):
    """Unit test suite for Step 2.4 Cross-Source Entity Resolution."""

    def setUp(self):
        self.resolver = CrossSourceEntityResolver()

    # --------------------------------------------------------------------------
    # Scenario 1: Same physical station, strong multi-signal agreement => MATCH
    # --------------------------------------------------------------------------
    def test_01_same_physical_station_strong_agreement_matches(self):
        """1. High concordance across location, name, operator, connectors, and address."""
        # Station A from OpenChargeMap
        stn_a = _make_station(
            source_id="open_charge_map",
            source_station_id="OCM-101",
            name="Tata Power - Bandra Kurla Complex Hub",
            latitude=19.06570,
            longitude=72.86870,
            operator_name="Tata Power EZ Charge",
            operator_slug="tata-power",
            address_line="Platina Building, G Block",
            locality="Bandra Kurla Complex",
            postal_code="400051",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS-2",
                    power_kw=50.0,
                    quantity=2,
                )
            ],
        )

        # Station B from OpenStreetMap (approx 6 meters away)
        stn_b = _make_station(
            source_id="open_street_map",
            source_station_id="OSM-node-998877",
            name="Tata Power EV Charging Station BKC Platina",
            latitude=19.06574,
            longitude=72.86873,
            operator_name="Tata Power",
            operator_slug="tata-power",
            address_line="Platina, BKC",
            locality="Bandra Kurla Complex",
            postal_code="400051",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="IEC 62196-3 Configuration FF",
                    power_kw=50.0,
                    quantity=2,
                )
            ],
        )

        cand = self.resolver.evaluate_pair(stn_a, stn_b)

        self.assertEqual(cand.match_state, MatchState.MATCH)
        self.assertGreaterEqual(cand.overall_confidence, 0.70)
        self.assertLess(cand.distance_meters, 15.0)
        self.assertTrue(cand.geo_evidence.is_within_threshold)
        self.assertEqual(cand.name_evidence.signal, EvidenceSignal.AGREE)
        self.assertEqual(cand.operator_evidence.signal, EvidenceSignal.AGREE)
        self.assertEqual(cand.connector_evidence.signal, EvidenceSignal.AGREE)
        self.assertEqual(cand.address_evidence.signal, EvidenceSignal.AGREE)
        self.assertTrue(any("Multi-signal positive concordance" in r or "concordance" in r for r in cand.reasons))

    # --------------------------------------------------------------------------
    # Scenario 2: Clearly different stations => NON_MATCH
    # --------------------------------------------------------------------------
    def test_02_clearly_different_stations_non_match(self):
        """2. Clearly different physical stations (separated geographically beyond candidate radius)."""
        # Station A: BKC Tata Power
        stn_a = _make_station(
            source_id="source_a",
            source_station_id="A-1",
            name="Tata Power BKC Fast Charger",
            latitude=19.0657,
            longitude=72.8687,
            operator_name="Tata Power",
            operator_slug="tata-power",
        )

        # Station B: In Andheri East (~5.3 km away), distinct station and operator
        stn_b = _make_station(
            source_id="source_b",
            source_station_id="B-1",
            name="Ather Grid Scooter Swap Point Andheri",
            latitude=19.1136,
            longitude=72.8697,
            operator_name="Ather Energy",
            operator_slug="ather-energy",
            address_line="Chakala, Andheri East",
            locality="Andheri East",
            postal_code="400093",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="Type 2",
                    raw_connector_type="Ather Proprietary / Type 2",
                    power_kw=3.3,
                    quantity=1,
                )
            ],
        )

        cand = self.resolver.evaluate_pair(stn_a, stn_b)

        self.assertEqual(cand.match_state, MatchState.NON_MATCH)
        self.assertFalse(cand.geo_evidence.is_within_threshold)
        self.assertGreater(cand.distance_meters, 50.0)
        self.assertEqual(cand.overall_confidence, 0.0)

    # --------------------------------------------------------------------------
    # Scenario 3: Close coordinates but conflicting evidence => AMBIGUOUS
    # --------------------------------------------------------------------------
    def test_03_close_coordinates_conflicting_evidence_is_ambiguous(self):
        """3. Stations 20m apart with differing names/operators must remain AMBIGUOUS."""
        stn_a = _make_station(
            source_id="source_a",
            source_station_id="A-3",
            name="Jio-bp pulse Commercial Hub",
            latitude=19.06570,
            longitude=72.86870,
            operator_name="Jio-bp pulse",
            operator_slug="jio-bp",
        )

        stn_b = _make_station(
            source_id="source_b",
            source_station_id="B-3",
            name="ChargeGrid Retail Station",
            latitude=19.06585,
            longitude=72.86875,
            operator_name="Magenta ChargeGrid",
            operator_slug="magenta-chargegrid",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=50.0,
                    quantity=1,
                )
            ],
        )

        cand = self.resolver.evaluate_pair(stn_a, stn_b)

        # Proximity is close (~17m), but names and operators conflict
        self.assertEqual(cand.match_state, MatchState.AMBIGUOUS)
        self.assertTrue(cand.geo_evidence.is_within_threshold)
        self.assertTrue(any("ambiguity" in r.lower() for r in cand.reasons))

    # --------------------------------------------------------------------------
    # Scenario 4: Same name but far apart => NON_MATCH / not candidate
    # --------------------------------------------------------------------------
    def test_04_same_name_far_apart_not_candidate(self):
        """4. Identical station names separated by kilometers must NOT be candidate matches."""
        stn_a = _make_station(
            source_id="source_a",
            source_station_id="A-4",
            name="Tata Power EZ Charge",
            latitude=19.0500,  # Bandra
            longitude=72.8300,
        )

        stn_b = _make_station(
            source_id="source_b",
            source_station_id="B-4",
            name="Tata Power EZ Charge",
            latitude=19.2183,  # Thane (~22 km away)
            longitude=72.9781,
        )

        cand = self.resolver.evaluate_pair(stn_a, stn_b)

        self.assertEqual(cand.match_state, MatchState.NON_MATCH)
        self.assertFalse(cand.geo_evidence.is_within_threshold)
        self.assertGreater(cand.distance_meters, 1000.0)
        self.assertEqual(cand.overall_confidence, 0.0)

    # --------------------------------------------------------------------------
    # Scenario 5: Nearby stations with missing connector data => UNKNOWN, not disagreement
    # --------------------------------------------------------------------------
    def test_05_nearby_stations_missing_connector_data_is_unknown(self):
        """5. Missing connector data must evaluate to UNKNOWN and never penalize as disagreement."""
        stn_a = _make_station(
            source_id="source_a",
            source_station_id="A-5",
            name="Fortum Charge & Drive BKC",
            latitude=19.0657,
            longitude=72.8687,
            operator_name="Fortum Charge & Drive",
            operator_slug="fortum",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=60.0,
                    quantity=2,
                )
            ],
        )

        # Source B has no connector details reported
        stn_b = _make_station(
            source_id="source_b",
            source_station_id="B-5",
            name="Fortum Charge & Drive BKC Hub",
            latitude=19.06575,
            longitude=72.86872,
            operator_name="Fortum",
            operator_slug="fortum",
            connectors=[],  # Missing connectors
        )

        cand = self.resolver.evaluate_pair(stn_a, stn_b)

        self.assertEqual(cand.connector_evidence.signal, EvidenceSignal.UNKNOWN)
        self.assertEqual(cand.connector_evidence.matching_types, [])
        self.assertIn("Connectors missing", cand.connector_evidence.details)
        # Because location, name, and operator strongly agree, state should still be MATCH
        self.assertEqual(cand.match_state, MatchState.MATCH)

    # --------------------------------------------------------------------------
    # Scenario 6: Different operators but otherwise strong physical evidence => rebrand/takeover
    # --------------------------------------------------------------------------
    def test_06_different_operators_strong_physical_evidence_matches(self):
        """6. Rebranding / operator acquisition scenario: identical location, name, address, connectors."""
        stn_a = _make_station(
            source_id="source_a",
            source_station_id="A-6",
            name="Phoenix Palladium EV Fast Charging Station",
            latitude=18.99500,
            longitude=72.82500,
            operator_name="Fortum Charge & Drive",
            operator_slug="fortum",
            address_line="462 Senapati Bapat Marg, Lower Parel",
            locality="Lower Parel",
            postal_code="400013",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=60.0,
                    quantity=2,
                )
            ],
        )

        stn_b = _make_station(
            source_id="source_b",
            source_station_id="B-6",
            name="Phoenix Palladium EV Fast Charging Station",
            latitude=18.99503,  # ~4 meters away
            longitude=72.82502,
            operator_name="Jio-bp pulse",  # Rebranded / taken over operator
            operator_slug="jio-bp",
            address_line="462 Senapati Bapat Marg, Lower Parel",
            locality="Lower Parel",
            postal_code="400013",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS2",
                    power_kw=60.0,
                    quantity=2,
                )
            ],
        )

        cand = self.resolver.evaluate_pair(stn_a, stn_b)

        # Operator disagrees
        self.assertEqual(cand.operator_evidence.signal, EvidenceSignal.DISAGREE)
        # But physical site identity is overwhelming => MATCH under Rule A3
        self.assertEqual(cand.match_state, MatchState.MATCH)
        self.assertTrue(any("rebrand" in r.lower() or "takeover" in r.lower() for r in cand.reasons))

    # --------------------------------------------------------------------------
    # Scenario 7: Coordinate boundary around 50m => deterministic thresholding
    # --------------------------------------------------------------------------
    def test_07_coordinate_boundary_at_50m(self):
        """7. Points exactly inside <= 50m are evaluated; points > 50m are immediate NON_MATCH."""
        # Base point in Mumbai (latitude 19.0, longitude 72.8)
        lat_base, lon_base = 19.000000, 72.800000

        # In latitude, 1 degree is ~111,139 meters. 45 meters is ~0.0004049 degrees.
        # 55 meters is ~0.0004948 degrees.
        delta_lat_45m = 45.0 / 111139.0
        delta_lat_55m = 55.0 / 111139.0

        stn_base = _make_station("src_1", "base", "Test Station", lat_base, lon_base)
        stn_inside = _make_station("src_2", "inside", "Test Station", lat_base + delta_lat_45m, lon_base)
        stn_outside = _make_station("src_2", "outside", "Test Station", lat_base + delta_lat_55m, lon_base)

        cand_inside = self.resolver.evaluate_pair(stn_base, stn_inside)
        cand_outside = self.resolver.evaluate_pair(stn_base, stn_outside)

        self.assertLess(cand_inside.distance_meters, 50.0)
        self.assertTrue(cand_inside.geo_evidence.is_within_threshold)
        self.assertEqual(cand_inside.match_state, MatchState.MATCH)

        self.assertGreater(cand_outside.distance_meters, 50.0)
        self.assertFalse(cand_outside.geo_evidence.is_within_threshold)
        self.assertEqual(cand_outside.match_state, MatchState.NON_MATCH)
        self.assertEqual(cand_outside.overall_confidence, 0.0)

    # --------------------------------------------------------------------------
    # Scenario 8: Identical coordinates but weak/conflicting metadata => not automatic MATCH
    # --------------------------------------------------------------------------
    def test_08_identical_coordinates_conflicting_metadata_not_automatic_match(self):
        """8. Identical coordinates (0m) alone must not produce automatic MATCH if metadata conflicts."""
        # Two distinct tenants at the same mall/parking complex
        stn_a = _make_station(
            source_id="source_a",
            source_station_id="A-8",
            name="Inorbit Mall Basment Fleet Charger",
            latitude=19.1725,
            longitude=72.8360,
            operator_name="Lithion Power",
            operator_slug="lithion-power",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="Type 2",
                    raw_connector_type="Type 2 AC",
                    power_kw=7.4,
                    quantity=4,
                )
            ],
        )

        stn_b = _make_station(
            source_id="source_b",
            source_station_id="B-8",
            name="Jio-bp pulse Inorbit Fast DC Hub",
            latitude=19.1725,  # Identical coordinates
            longitude=72.8360,
            operator_name="Jio-bp pulse",
            operator_slug="jio-bp",
            connectors=[
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS-2 DC",
                    power_kw=60.0,
                    quantity=2,
                )
            ],
        )

        cand = self.resolver.evaluate_pair(stn_a, stn_b)

        # Distance is 0.0m
        self.assertEqual(cand.distance_meters, 0.0)
        self.assertEqual(cand.geo_evidence.proximity_score, 1.0)
        # However, names, operators, and connectors diverge
        self.assertNotEqual(cand.match_state, MatchState.MATCH)
        self.assertIn(cand.match_state, [MatchState.AMBIGUOUS, MatchState.NON_MATCH])

    # --------------------------------------------------------------------------
    # Scenario 9: Missing address/PIN => UNKNOWN rather than mismatch
    # --------------------------------------------------------------------------
    def test_09_missing_address_pin_is_unknown(self):
        """9. Omitted address fields evaluate to UNKNOWN and do not trigger negative discord."""
        stn_a = _make_station(
            source_id="source_a",
            source_station_id="A-9",
            name="Tata Power BKC",
            latitude=19.0657,
            longitude=72.8687,
            address_line="Platina Building",
            locality="Bandra Kurla Complex",
            postal_code="400051",
        )

        stn_b = _make_station(
            source_id="source_b",
            source_station_id="B-9",
            name="Tata Power BKC",
            latitude=19.0657,
            longitude=72.8687,
            address_line=None,
            locality=None,
            postal_code=None,
        )

        cand = self.resolver.evaluate_pair(stn_a, stn_b)

        self.assertEqual(cand.address_evidence.signal, EvidenceSignal.UNKNOWN)
        self.assertIsNone(cand.address_evidence.pin_match)
        self.assertIn("inconclusive", cand.address_evidence.details.lower())

    # --------------------------------------------------------------------------
    # Scenario 10: Connector signature comparisons (identical, partial, conflicting)
    # --------------------------------------------------------------------------
    def test_10_connector_signature_comparisons(self):
        """10. Thoroughly tests connector signature compatibility across 3 variants."""
        # 10a. Same type, quantity, and power => AGREE, power_compatibility=True
        conn_10a_1 = [
            NormalizedConnectorRecord(
                connector_type="CCS2",
                raw_connector_type="CCS 2",
                power_kw=50.0,
                quantity=2,
            )
        ]
        conn_10a_2 = [
            NormalizedConnectorRecord(
                connector_type="CCS2",
                raw_connector_type="CCS-2 DC",
                power_kw=50.0,
                quantity=2,
            )
        ]
        ev_10a = self.resolver._evaluate_connectors(conn_10a_1, conn_10a_2)
        self.assertEqual(ev_10a.signal, EvidenceSignal.AGREE)
        self.assertEqual(ev_10a.matching_types, ["CCS2"])
        self.assertTrue(ev_10a.power_compatibility)

        # 10b. Partial data: Type matches, but one source omitted power_kw => AGREE, power_compatibility=None
        conn_10b_1 = [
            NormalizedConnectorRecord(
                connector_type="Type 2",
                raw_connector_type="Type-2 AC",
                power_kw=22.0,
                quantity=1,
            )
        ]
        conn_10b_2 = [
            NormalizedConnectorRecord(
                connector_type="Type 2",
                raw_connector_type="Type 2",
                power_kw=None,  # Power missing
                quantity=1,
            )
        ]
        ev_10b = self.resolver._evaluate_connectors(conn_10b_1, conn_10b_2)
        self.assertEqual(ev_10b.signal, EvidenceSignal.AGREE)
        self.assertEqual(ev_10b.matching_types, ["Type 2"])
        self.assertIsNone(ev_10b.power_compatibility)

        # 10c. Conflicting data: CHAdeMO 50kW vs Type 2 7.4kW => DISAGREE
        conn_10c_1 = [
            NormalizedConnectorRecord(
                connector_type="CHAdeMO",
                raw_connector_type="CHAdeMO",
                power_kw=50.0,
                quantity=1,
            )
        ]
        conn_10c_2 = [
            NormalizedConnectorRecord(
                connector_type="Type 2",
                raw_connector_type="Type 2",
                power_kw=7.4,
                quantity=2,
            )
        ]
        ev_10c = self.resolver._evaluate_connectors(conn_10c_1, conn_10c_2)
        self.assertEqual(ev_10c.signal, EvidenceSignal.DISAGREE)
        self.assertEqual(ev_10c.matching_types, [])

    # --------------------------------------------------------------------------
    # Scenario 11: Determinism
    # --------------------------------------------------------------------------
    def test_11_determinism_repeated_runs_produce_identical_output(self):
        """11. Evaluates pair 10 times; verifies byte-for-byte identical evidence dossiers."""
        stn_a = _make_station(
            source_id="ocm",
            source_station_id="111",
            name="Tata Power BKC Hub",
            latitude=19.0657,
            longitude=72.8687,
        )
        stn_b = _make_station(
            source_id="osm",
            source_station_id="222",
            name="Tata Power Fast Charger BKC",
            latitude=19.06573,
            longitude=72.86872,
        )

        first_dict = self.resolver.evaluate_pair(stn_a, stn_b).to_dict()
        first_json = json.dumps(first_dict, sort_keys=True)

        for _ in range(10):
            cand = self.resolver.evaluate_pair(stn_a, stn_b)
            curr_json = json.dumps(cand.to_dict(), sort_keys=True)
            self.assertEqual(first_json, curr_json)

    # --------------------------------------------------------------------------
    # Scenario 12: Non-destructive behavior
    # --------------------------------------------------------------------------
    def test_12_non_destructive_guarantee(self):
        """12. Proves that resolution execution does not mutate station records or touch DB."""
        stn_a = _make_station("src_a", "ID-A", "Original Name A", 19.065, 72.868)
        stn_b = _make_station("src_b", "ID-B", "Original Name B", 19.065, 72.868)

        stn_a_copy = copy.deepcopy(stn_a)
        stn_b_copy = copy.deepcopy(stn_b)

        cand = self.resolver.evaluate_pair(stn_a, stn_b)

        # Verify input objects remain 100% unaltered
        self.assertEqual(stn_a, stn_a_copy)
        self.assertEqual(stn_b, stn_b_copy)
        # Verify candidate is a pure evaluation object
        self.assertIsInstance(cand, EntityResolutionCandidate)

    # --------------------------------------------------------------------------
    # Scenario 13: Multiple candidates preserved without arbitrary selection
    # --------------------------------------------------------------------------
    def test_13_multiple_candidates_preserved(self):
        """13. When multiple stations exist within radius, all candidates are preserved in sorted order."""
        target = _make_station("src_a", "TGT", "Tata Power BKC", 19.0657, 72.8687)

        # 3 distinct stations at 8m, 22m, and 45m away
        delta_8m = 8.0 / 111139.0
        delta_22m = 22.0 / 111139.0
        delta_45m = 45.0 / 111139.0

        cand_1 = _make_station("src_b", "C1", "Tata Power BKC Hub", 19.0657 + delta_8m, 72.8687)
        cand_2 = _make_station("src_b", "C2", "Jio-bp pulse BKC", 19.0657 + delta_22m, 72.8687)
        cand_3 = _make_station("src_b", "C3", "Ather Grid BKC", 19.0657 + delta_45m, 72.8687)

        corpus = [cand_3, cand_1, cand_2]  # Unordered corpus

        candidates = self.resolver.find_candidates_for_record(target, corpus)

        # All 3 within 50m must be preserved
        self.assertEqual(len(candidates), 3)
        # Must be deterministically ordered by highest confidence first
        self.assertGreaterEqual(candidates[0].overall_confidence, candidates[1].overall_confidence)
        self.assertGreaterEqual(candidates[1].overall_confidence, candidates[2].overall_confidence)
        # Candidate 1 (matching Tata Power name) should rank highest
        self.assertEqual(candidates[0].source_station_id_b, "C1")
        self.assertEqual(candidates[0].match_state, MatchState.MATCH)

    # --------------------------------------------------------------------------
    # Scenario 14: Source identity preservation
    # --------------------------------------------------------------------------
    def test_14_source_identity_preservation(self):
        """14. Source IDs and record keys remain preserved and are never replaced by ChargePlus UUIDs."""
        stn_a = _make_station("open_charge_map", "OCM-9999", "Station A", 19.0657, 72.8687)
        stn_b = _make_station("tata_power_api", "TP-NODE-4321", "Station B", 19.0657, 72.8687)

        cand = self.resolver.evaluate_pair(stn_a, stn_b)

        self.assertEqual(cand.source_a, "open_charge_map")
        self.assertEqual(cand.source_station_id_a, "OCM-9999")
        self.assertEqual(cand.source_b, "tata_power_api")
        self.assertEqual(cand.source_station_id_b, "TP-NODE-4321")

        # Serialized dictionary must also contain external identifiers verbatim
        d = cand.to_dict()
        self.assertEqual(d["source_a"], "open_charge_map")
        self.assertEqual(d["source_station_id_a"], "OCM-9999")
        self.assertEqual(d["source_b"], "tata_power_api")
        self.assertEqual(d["source_station_id_b"], "TP-NODE-4321")

    # --------------------------------------------------------------------------
    # Additional Scenario 15: String & Geodetic Helper Precision Tests
    # --------------------------------------------------------------------------
    def test_15_string_and_geodetic_helpers(self):
        """15. Unit tests for Haversine distance, token sort, and string normalization."""
        # Haversine at 0 distance
        self.assertEqual(haversine_distance_meters(19.0, 72.8, 19.0, 72.8), 0.0)

        # Haversine known distance: Nariman Point (18.926, 72.823) to Bandra (19.055, 72.830) is ~14.3 km
        dist = haversine_distance_meters(18.926, 72.823, 19.055, 72.830)
        self.assertAlmostEqual(dist, 14360.0, delta=200.0)

        # Normalization
        norm = normalize_string_for_matching("Tata-Power / EV Station (Bandra)!")
        self.assertEqual(norm, "tata power ev station bandra")

        # Token sort ratio is order-invariant
        score_1 = calculate_token_sort_ratio("Tata Power Bandra Hub", "Hub Bandra Power Tata")
        self.assertEqual(score_1, 1.0)

        # Jaccard similarity
        jaccard = calculate_jaccard_similarity({"tata", "power", "hub"}, {"bkc", "power", "tata"})
        self.assertAlmostEqual(jaccard, 2.0 / 4.0)


if __name__ == "__main__":
    unittest.main()
