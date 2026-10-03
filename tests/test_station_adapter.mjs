import test from "node:test";
import assert from "node:assert/strict";
import {
  deriveStationStatus,
  derivePricing,
  deriveHours,
  deriveArea,
  deriveAddress,
  mapDbConnectorToConnector,
  mapDbStationToStation,
  normalizeConnectorType,
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
