import test from "node:test";
import assert from "node:assert/strict";
import {
  deriveStationStatus,
  derivePricing,
  deriveHours,
  deriveArea,
  deriveAddress,
  deriveFreshnessState,
  deriveSourceCategory,
  mapDbConnectorToConnector,
  mapDbStationToStation,
  normalizeConnectorType,
  parseStationCoord,
} from "../src/data/stationAdapter.ts";
import { escapeHtml } from "../src/lib/util.ts";

test("deriveStationStatus enforces telemetry priority and Rule 5 (static != availability)", () => {
  // Telemetry present
  assert.equal(deriveStationStatus("available", "operational"), "available");
  assert.equal(deriveStationStatus("busy", "operational"), "busy");
  assert.equal(deriveStationStatus("in_use", "operational"), "busy");
  assert.equal(deriveStationStatus("broken", "operational"), "broken");
  assert.equal(deriveStationStatus("offline", "operational"), "broken");
  assert.equal(deriveStationStatus("unknown", "operational"), "unknown");

  // No telemetry: static operational status must NOT become available (Rule 5)
  assert.equal(deriveStationStatus(null, "operational"), "unknown");
  assert.equal(deriveStationStatus(undefined, "operational"), "unknown");
  assert.equal(deriveStationStatus("", "operational"), "unknown");

  // Decommissioned or broken stations are broken
  assert.equal(deriveStationStatus(null, "temporarily_unavailable"), "broken");
  assert.equal(deriveStationStatus(null, "decommissioned"), "broken");
  assert.equal(deriveStationStatus(null, "out_of_service"), "broken");
});

test("derivePricing handles null, zero, and positive prices honestly without fabricating free rates", () => {
  // Missing price is unknown (null), NOT free
  assert.deepEqual(derivePricing({ id: "1", name: "S1", latitude: 19, longitude: 72 }), {
    pricePerKwh: null,
    isFree: null,
  });

  // Explicit zero price is free
  assert.deepEqual(
    derivePricing({ id: "1", name: "S1", latitude: 19, longitude: 72, min_price_per_kwh: 0 }),
    { pricePerKwh: 0, isFree: true }
  );

  // Positive price is not free
  assert.deepEqual(
    derivePricing({ id: "1", name: "S1", latitude: 19, longitude: 72, min_price_per_kwh: 18.5 }),
    { pricePerKwh: 18.5, isFree: false }
  );
});

test("deriveHours formats 24h, open-close, and unknown hours", () => {
  assert.deepEqual(
    deriveHours({ id: "1", name: "S1", latitude: 19, longitude: 72, is_24_hours: true }),
    { kind: "24h" }
  );
  assert.deepEqual(
    deriveHours({
      id: "1",
      name: "S1",
      latitude: 19,
      longitude: 72,
      opening_time: "08:00:00",
      closing_time: "22:00:00",
    }),
    { kind: "open-close", open: "08:00", close: "22:00" }
  );
  assert.deepEqual(
    deriveHours({ id: "1", name: "S1", latitude: 19, longitude: 72 }),
    { kind: "unknown" }
  );
});

test("deriveArea and deriveAddress handle missing location honestly without presuming Mumbai", () => {
  // Locality precedence
  assert.equal(deriveArea({ id: "1", name: "S1", latitude: 19, longitude: 72, locality: "Vikhroli" }), "Vikhroli");
  // City fallback
  assert.equal(deriveArea({ id: "1", name: "S1", latitude: 19, longitude: 72, city: "Thane" }), "Thane");
  // State fallback
  assert.equal(deriveArea({ id: "1", name: "S1", latitude: 19, longitude: 72, state: "Maharashtra" }), "Maharashtra");
  // Missing location must NOT invent Mumbai
  assert.equal(deriveArea({ id: "1", name: "S1", latitude: 19, longitude: 72 }), "Area unknown");

  // Address composition from available parts
  assert.equal(
    deriveAddress({
      id: "1",
      name: "S1",
      latitude: 19,
      longitude: 72,
      address_line: "Line 1",
      locality: "Area",
      city: "Thane",
      postal_code: "400601",
    }),
    "Line 1, Area, Thane, 400601"
  );

  // Missing address must NOT invent "${name}, Mumbai, Maharashtra"
  assert.equal(
    deriveAddress({
      id: "1",
      name: "S1",
      latitude: 19,
      longitude: 72,
    }),
    "Address unavailable"
  );
});

test("normalizeConnectorType does not fabricate CCS2 for missing or unknown types", () => {
  assert.equal(normalizeConnectorType("CCS2"), "CCS2");
  assert.equal(normalizeConnectorType("IEC 62196-3"), "CCS2");
  assert.equal(normalizeConnectorType("Type 2"), "Type 2");
  assert.equal(normalizeConnectorType("IEC 62196-2"), "Type 2");
  assert.equal(normalizeConnectorType("Type 1"), "Type 1");
  assert.equal(normalizeConnectorType("CHAdeMO"), "CHAdeMO");
  assert.equal(normalizeConnectorType("Bharat AC001"), "Bharat AC001");

  // Missing or invalid must return "Unknown", NEVER "CCS2"
  assert.equal(normalizeConnectorType(null), "Unknown");
  assert.equal(normalizeConnectorType(undefined), "Unknown");
  assert.equal(normalizeConnectorType(""), "Unknown");
  assert.equal(normalizeConnectorType("Proprietary Socket"), "Unknown");
});

test("mapDbConnectorToConnector preserves missing quantity and unobserved availability as null", () => {
  // Missing total_quantity must remain null (NOT defaulted to 1)
  // Missing latest_available_connectors must remain null (NOT 0, NOT total)
  const cMissing = mapDbConnectorToConnector({
    id: "conn-1",
    station_id: "st-1",
    connector_type: "CCS2",
    power_kw: null,
    total_quantity: null,
    latest_available_connectors: null,
  }, "available"); // Even if stationStatus is "available", connector availability is NOT fabricated!

  assert.equal(cMissing.powerKw, null); // Rule 3: Unknown power is null
  assert.equal(cMissing.total, null);   // Unknown quantity is null (never defaulted to 1)
  assert.equal(cMissing.available, null); // Unobserved availability is null (never defaulted to total or 0)

  // With explicit quantity and availability
  const cExplicit = mapDbConnectorToConnector({
    id: "conn-2",
    station_id: "st-1",
    connector_type: "Type 2",
    power_kw: 22,
    total_quantity: 3,
    latest_available_connectors: 2,
  }, "available");

  assert.equal(cExplicit.powerKw, 22);
  assert.equal(cExplicit.total, 3);
  assert.equal(cExplicit.available, 2);
});

test("mapDbConnectorToConnector keeps verified tariff separate from unverified estimate", () => {
  const conn = mapDbConnectorToConnector({
    id: "conn-price-estimate",
    station_id: "st-price-estimate",
    connector_type: "CCS2",
    price_per_kwh: null,
    price_per_session: 50,
    price_estimate_per_kwh: 18.5,
    price_estimate_raw: "₹18.50 per kWh + GST",
    price_estimate_source: "ocm_usage_cost",
  });
  assert.equal(conn.pricePerKwh, null);
  assert.equal(conn.pricePerSession, 50);
  assert.equal(conn.priceEstimatePerKwh, 18.5);
  assert.equal(conn.priceEstimateRaw, "₹18.50 per kWh + GST");
  assert.equal(conn.priceEstimateSource, "ocm_usage_cost");

  const verified = mapDbConnectorToConnector({
    id: "conn-verified-price",
    station_id: "st-price-estimate",
    connector_type: "CCS2",
    price_per_kwh: 20,
    price_estimate_per_kwh: 18.5,
  });
  assert.equal(verified.pricePerKwh, 20);
  assert.equal(verified.priceEstimatePerKwh, 18.5);
});

test("mapDbStationToStation does not invent operator, address, or busy windows", () => {
  const station = mapDbStationToStation({
    id: "st-test-1",
    name: "Test Station",
    operator_name: null, // Missing operator must NOT become "Independent"
    locality: null,
    city: null,
    latitude: 19.05,
    longitude: 72.83,
    operational_status: "operational",
    latest_availability_status: null,
    min_price_per_kwh: null,
    avg_rating: null,
    review_count: 0,
  });

  assert.equal(station.id, "st-test-1");
  assert.equal(station.name, "Test Station");
  assert.equal(station.operator, "Unknown Operator"); // Never "Independent"
  assert.equal(station.area, "Area unknown");          // Never "Mumbai"
  assert.equal(station.address, "Address unavailable"); // Never fabricated
  assert.equal(station.status, "unknown");             // Rule 5: static operational != available
  assert.equal(station.pricePerKwh, null);
  assert.equal(station.isFree, null);
  assert.equal(station.rating, null);
  assert.equal(station.reviewCount, 0);
  assert.deepEqual(station.busyWindows, []);            // Cold-start empty
  assert.deepEqual(station.connectors, []);
});

test("escapeHtml sanitizes untrusted markup to prevent HTML injection", () => {
  assert.equal(escapeHtml('<script>alert("xss")</script>'), '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;');
  assert.equal(escapeHtml("Tom & Jerry's \"Charger\""), 'Tom &amp; Jerry&#039;s &quot;Charger&quot;');
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(undefined), "");
});

test("parseStationCoord does not coerce missing values to 0", () => {
  assert.equal(Number.isNaN(parseStationCoord(null)), true);
  assert.equal(Number.isNaN(parseStationCoord(undefined)), true);
  assert.equal(Number.isNaN(parseStationCoord("")), true);
  assert.equal(parseStationCoord(19.076), 19.076);
  assert.equal(parseStationCoord("72.877"), 72.877);
});

test("deriveFreshnessState enforces operational decay boundaries", () => {
  assert.equal(deriveFreshnessState(null), "unknown");
  assert.equal(deriveFreshnessState(undefined), "unknown");
  assert.equal(deriveFreshnessState(-5), "unknown");
  assert.equal(deriveFreshnessState(0), "fresh");
  assert.equal(deriveFreshnessState(30), "fresh");
  assert.equal(deriveFreshnessState(31), "aging");
  assert.equal(deriveFreshnessState(120), "aging");
  assert.equal(deriveFreshnessState(121), "stale");
  assert.equal(deriveFreshnessState(1440), "stale");
});

test("deriveSourceCategory partitions source provenance correctly", () => {
  // Simulated flag takes absolute precedence
  assert.equal(deriveSourceCategory({ isSimulated: true, hasObservation: true, freshness: "fresh" }), "simulated");
  // Missing observation resolves to unknown
  assert.equal(deriveSourceCategory({ hasObservation: false, freshness: "unknown" }), "unknown");
  // Stale observation is classified as historical evidence
  assert.equal(deriveSourceCategory({ hasObservation: true, freshness: "stale" }), "historical");
  // Verified live feed (CPO/OCPI/OICP)
  assert.equal(deriveSourceCategory({ hasObservation: true, freshness: "fresh", sourceName: "Tata Power OCPI Feed" }), "verified_live");
  // Recent observation from other sources
  assert.equal(deriveSourceCategory({ hasObservation: true, freshness: "fresh", sourceName: "Community Driver Report" }), "recent_observation");
});

test("deriveStationStatus marks stale observations as unknown to prevent projecting false availability", () => {
  // Fresh observation is available
  assert.equal(deriveStationStatus("available", "operational", 15), "available");
  // Stale observation (> 120 min) cannot claim live availability
  assert.equal(deriveStationStatus("available", "operational", 180), "unknown");
  // But a broken or out_of_service station remains broken even if stale
  assert.equal(deriveStationStatus("broken", "operational", 180), "unknown");
  assert.equal(deriveStationStatus("available", "out_of_service", 180), "broken");
});

test("mapDbConnectorToConnector and mapDbStationToStation retain observation IDs and provenance", () => {
  const conn = mapDbConnectorToConnector({
    id: "c-101",
    station_id: "s-101",
    connector_type: "CCS2",
    power_kw: 60,
    total_quantity: 2,
    latest_available_connectors: 1,
    latest_observation_id: "obs-abc-123",
    latest_observed_at: "2026-10-12T12:00:00Z",
    minutes_since_observation: 15,
    source_name: "Live OCPI",
  });

  assert.equal(conn.latestObservationId, "obs-abc-123");
  assert.equal(conn.latestObservedAt, "2026-10-12T12:00:00Z");
  assert.equal(conn.freshnessState, "fresh");
  assert.equal(conn.sourceCategory, "verified_live");

  const st = mapDbStationToStation({
    id: "s-101",
    name: "Hub Station",
    latitude: 19.1,
    longitude: 72.8,
    latest_observation_id: "obs-station-root",
    latest_observed_at: "2026-10-12T12:00:00Z",
    minutes_since_observation: 15,
    source_name: "Live OCPI",
    latest_availability_status: "available",
  }, [conn]);

  assert.equal(st.latestObservationId, "obs-station-root");
  assert.equal(st.sourceCategory, "verified_live");
  assert.equal(st.freshnessState, "fresh");
  assert.equal(st.connectors[0].latestObservationId, "obs-abc-123");
});

test("connector provenance: isSimulated propagates from db row", () => {
  const c = mapDbConnectorToConnector({ id: "c1", station_id: "s1", connector_type: "Type 2", is_simulated: true });
  assert.equal(c.isSimulated, true);
  const c2 = mapDbConnectorToConnector({ id: "c2", station_id: "s1", connector_type: "Type 2", is_simulated: false });
  assert.equal(c2.isSimulated, false);
});
