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

test("derivePricing handles null, zero, and positive prices honestly", () => {
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

test("deriveArea and deriveAddress handle fallback and formatting cleanly", () => {
  assert.equal(deriveArea({ id: "1", name: "S1", latitude: 19, longitude: 72, locality: "Vikhroli" }), "Vikhroli");
  assert.equal(deriveArea({ id: "1", name: "S1", latitude: 19, longitude: 72, city: "Thane" }), "Thane");
  assert.equal(deriveArea({ id: "1", name: "S1", latitude: 19, longitude: 72 }), "Mumbai");

  assert.equal(
    deriveAddress({
      id: "1",
      name: "S1",
      latitude: 19,
      longitude: 72,
      address_line: "Line 1",
      locality: "Area",
      city: "Mumbai",
      postal_code: "400001",
    }),
    "Line 1, Area, Mumbai, 400001"
  );
});

test("normalizeConnectorType maps standards and aliases safely", () => {
  assert.equal(normalizeConnectorType("CCS2"), "CCS2");
  assert.equal(normalizeConnectorType("IEC 62196-3 Configuration FF (CCS2)"), "CCS2");
  assert.equal(normalizeConnectorType("Type 2"), "Type 2");
  assert.equal(normalizeConnectorType("IEC 62196-2"), "Type 2");
  assert.equal(normalizeConnectorType("Type 1"), "Type 1");
  assert.equal(normalizeConnectorType("CHAdeMO"), "CHAdeMO");
  assert.equal(normalizeConnectorType("Bharat AC001"), "Bharat AC001");
  assert.equal(normalizeConnectorType(null), "CCS2");
});

test("mapDbConnectorToConnector preserves null power and clamps availability", () => {
  const cNullPower = mapDbConnectorToConnector({
    id: "conn-1",
    station_id: "st-1",
    connector_type: "CCS2",
    power_kw: null,
    total_quantity: 2,
    latest_available_connectors: null,
  }, "unknown");

  assert.equal(cNullPower.powerKw, null); // Rule 3: Unknown connector power is null, never zero
  assert.equal(cNullPower.total, 2);
  assert.equal(cNullPower.available, 0);

  const cWithPower = mapDbConnectorToConnector({
    id: "conn-2",
    station_id: "st-1",
    connector_type: "Type 2",
    power_kw: 22,
    total_quantity: 3,
    latest_available_connectors: 2,
  }, "available");

  assert.equal(cWithPower.powerKw, 22);
  assert.equal(cWithPower.total, 3);
  assert.equal(cWithPower.available, 2);
});

test("mapDbStationToStation creates faithful domain entities with cold-start empty arrays", () => {
  const station = mapDbStationToStation({
    id: "st-test-1",
    name: "Test Station",
    operator_name: "Tata Power",
    locality: "Bandra",
    city: "Mumbai",
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
  assert.equal(station.operator, "Tata Power");
  assert.equal(station.area, "Bandra");
  assert.equal(station.status, "unknown"); // No telemetry -> unknown
  assert.equal(station.pricePerKwh, null);
  assert.equal(station.isFree, null);
  assert.equal(station.rating, null);
  assert.equal(station.reviewCount, 0);
  assert.deepEqual(station.busyWindows, []); // Cold start: empty
  assert.deepEqual(station.connectors, []);
});

test("escapeHtml sanitizes untrusted markup to prevent HTML injection", () => {
  assert.equal(escapeHtml('<script>alert("xss")</script>'), '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;');
  assert.equal(escapeHtml("Tom & Jerry's \"Charger\""), 'Tom &amp; Jerry&#039;s &quot;Charger&quot;');
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(undefined), "");
});
