import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { dictionaries } from "../src/i18n/dictionaries.ts";
import {
  connectorPriceDisplay,
  isFreeStation,
  isValidPrice,
  stationPriceDisplay,
} from "../src/lib/priceDisplay.ts";
import {
  derivePricing,
  mapDbConnectorToConnector,
  mapDbStationToStation,
} from "../src/data/stationAdapter.ts";
import {
  DEFAULT_EXPLORE_FILTERS,
  evaluateRecommendations,
  filterAndSortStations,
} from "../src/data/exploreQuery.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = (p) => readFileSync(join(root, p), "utf8");

const card = src("src/components/StationCard.tsx");
const sheet = src("src/components/StationPreviewSheet.tsx");
const map = src("src/components/MapLibreMap.tsx");
const detail = src("src/app/station/[id]/StationDetail.tsx");

// Mirrors the production translate lookup (same interpolation the app uses).
const t = (key, vars) => {
  const raw = dictionaries.en[key] ?? key;
  if (!vars) return raw;
  return raw.replace(/\{(\w+)\}/g, (_, name) => String(vars[name]));
};

// Builds a station through the real adapter so tests exercise production data flow.
const row = (id, over = {}) => ({
  id,
  name: `Station ${id}`,
  latitude: 19.1,
  longitude: 72.9,
  operational_status: "operational",
  latest_availability_status: null,
  ...over,
});
const connectorRow = (id, stationId, over = {}) => ({
  id,
  station_id: stationId,
  connector_type: "Type 1",
  ...over,
});

const INVALID_PRICES = [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY];

test("1. perKwh template carries currency, units and {price} (no duplicated strings)", () => {
  assert.match(dictionaries.en["station.perKwh"], /\{price\}/);
  assert.match(dictionaries.en["station.perKwh"], /₹.*kWh/);
  assert.ok(dictionaries.en["station.priceUnavailable"].length > 0);
  assert.ok(dictionaries.en["station.estimateAvailable"].length > 0);
  assert.ok(dictionaries.en["station.priceEstimateLabel"].length > 0);
  assert.ok(dictionaries.en["station.priceEstimateDisclaimer"].length > 0);
});

test("2. production stationPriceDisplay renders verified prices to exactly two decimals", () => {
  const base = { isFree: false, connectors: [] };
  assert.deepEqual(stationPriceDisplay({ ...base, pricePerKwh: 18 }, t), {
    state: "verified",
    text: "₹18.00/kWh",
  });
  assert.deepEqual(stationPriceDisplay({ ...base, pricePerKwh: 18.5 }, t), {
    state: "verified",
    text: "₹18.50/kWh",
  });
  assert.deepEqual(stationPriceDisplay({ ...base, pricePerKwh: 18.567 }, t), {
    state: "verified",
    text: "₹18.57/kWh",
  });
});

test("3. invalid prices are never shown as zero, never NaN/Infinity, never free", () => {
  for (const bad of INVALID_PRICES) {
    const out = stationPriceDisplay({ isFree: null, pricePerKwh: bad, connectors: [] }, t);
    assert.equal(out.state, "unavailable", `price ${String(bad)} must not be a valid price`);
    assert.equal(out.text, t("station.priceUnavailable"));
    assert.ok(!out.text.includes("0.00"));
    assert.ok(!out.text.includes("NaN"));
    assert.ok(!out.text.includes("Infinity"));
    assert.equal(isFreeStation({ isFree: null, pricePerKwh: bad }), false);
    assert.equal(isValidPrice(bad), false);
  }
  // A valid estimate still wins over the invalid verified value.
  const est = { isFree: null, pricePerKwh: Number.POSITIVE_INFINITY, connectors: [{ priceEstimatePerKwh: 21 }] };
  assert.deepEqual(stationPriceDisplay(est, t), {
    state: "estimate",
    text: t("station.estimateAvailable"),
  });
  // isValidPrice accepts only finite numbers (never strings/objects).
  for (const good of [0, 18, 18.5, -1]) assert.equal(isValidPrice(good), true, `${good} is finite`);
  for (const bad of ["18", "0", {}, [], true]) assert.equal(isValidPrice(bad), false, `${String(bad)} is not a number`);
});

test("4. free contract: explicit flag or a validated finite zero tariff, nothing else", () => {
  assert.equal(stationPriceDisplay({ isFree: true, pricePerKwh: null, connectors: [] }, t).state, "free");
  // The explicit flag wins even over a junk price.
  assert.deepEqual(stationPriceDisplay({ isFree: true, pricePerKwh: Number.POSITIVE_INFINITY, connectors: [] }, t), {
    state: "free",
    text: "Free",
  });
  // A finite zero is free even when the flag is absent or false.
  for (const flag of [null, undefined, false]) {
    const out = stationPriceDisplay({ isFree: flag, pricePerKwh: 0, connectors: [] }, t);
    assert.deepEqual(out, { state: "free", text: "Free" });
    assert.equal(isFreeStation({ isFree: flag, pricePerKwh: 0 }), true);
  }
  // isFree:false with a real price stays paid; invalid values never become free.
  assert.equal(stationPriceDisplay({ isFree: false, pricePerKwh: 18.5, connectors: [] }, t).state, "verified");
  assert.equal(isFreeStation({ isFree: false, pricePerKwh: Number.NaN }), false);
});

test("5. StationDetail path: estimate shown when the top-level price is unknown", () => {
  const out = stationPriceDisplay(
    { isFree: null, pricePerKwh: null, connectors: [{ priceEstimatePerKwh: 25 }] },
    t
  );
  assert.equal(out.state, "estimate");
  assert.equal(out.text, t("station.estimateAvailable"));
  assert.notEqual(out.state, "free");
  assert.notEqual(out.text, t("station.priceUnavailable"));
});

test("6. connectorPriceDisplay: verified, estimate, unavailable (null text), invalid fallback", () => {
  assert.deepEqual(connectorPriceDisplay({ pricePerKwh: 18.5, priceEstimatePerKwh: null }, t), {
    state: "verified",
    text: "₹18.50/kWh",
  });
  assert.deepEqual(connectorPriceDisplay({ pricePerKwh: null, priceEstimatePerKwh: 21 }, t), {
    state: "estimate",
    text: "₹21.00/kWh",
  });
  assert.deepEqual(connectorPriceDisplay({ pricePerKwh: null, priceEstimatePerKwh: null, pricePerSession: 50 }, t), {
    state: "verified",
    text: "₹50.00/session",
  });
  assert.deepEqual(connectorPriceDisplay({ pricePerKwh: 18.5, priceEstimatePerKwh: 21, pricePerSession: 50 }, t), {
    state: "verified",
    text: "₹18.50/kWh",
  });
  assert.deepEqual(connectorPriceDisplay({ pricePerKwh: null, priceEstimatePerKwh: 21, pricePerSession: 50 }, t), {
    state: "estimate",
    text: "₹21.00/kWh",
  });
  assert.deepEqual(connectorPriceDisplay({ pricePerKwh: null, priceEstimatePerKwh: null }, t), {
    state: "unavailable",
    text: null,
  });
  // An invalid verified value never formats; a valid estimate takes over.
  const fallback = connectorPriceDisplay({ pricePerKwh: Number.NEGATIVE_INFINITY, priceEstimatePerKwh: 30 }, t);
  assert.deepEqual(fallback, { state: "estimate", text: "₹30.00/kWh" });
});

test("7. derivePricing rejects NaN/Infinity instead of passing them through as prices", () => {
  for (const bad of [Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.NaN, "Infinity", "NaN"]) {
    assert.deepEqual(
      derivePricing({ id: "1", name: "S1", latitude: 19, longitude: 72, min_price_per_kwh: bad }),
      { pricePerKwh: null, isFree: null },
      `min_price_per_kwh=${String(bad)} must be unknown, not a price`
    );
  }
  // Existing honest behavior is preserved.
  assert.deepEqual(derivePricing({ id: "1", name: "S1", latitude: 19, longitude: 72 }), {
    pricePerKwh: null,
    isFree: null,
  });
  assert.deepEqual(derivePricing({ id: "1", name: "S1", latitude: 19, longitude: 72, min_price_per_kwh: 0 }), {
    pricePerKwh: 0,
    isFree: true,
  });
  assert.deepEqual(
    derivePricing({ id: "1", name: "S1", latitude: 19, longitude: 72, min_price_per_kwh: 18.5 }),
    { pricePerKwh: 18.5, isFree: false }
  );
});

test("8. adapter end-to-end: an Infinity tariff never renders as a price", () => {
  const badStation = mapDbStationToStation(row("inv", { min_price_per_kwh: Number.POSITIVE_INFINITY }), []);
  const out = stationPriceDisplay(badStation, t);
  assert.ok(!out.text.includes("Infinity"));
  assert.ok(!out.text.includes("NaN"));
  assert.ok(!out.text.includes("0.00"));
  assert.equal(out.state, "unavailable");

  const badConnector = mapDbConnectorToConnector(
    connectorRow("c1", "inv", { price_per_kwh: Number.POSITIVE_INFINITY })
  );
  assert.equal(badConnector.pricePerKwh, null);
  assert.deepEqual(connectorPriceDisplay(badConnector, t), { state: "unavailable", text: null });
});

test("9. explore free filter and recommender priceState agree with the display contract", () => {
  const stations = [
    mapDbStationToStation(row("free", { min_price_per_kwh: 0 }), []),
    mapDbStationToStation(row("paid", { min_price_per_kwh: 18.5 }), []),
    mapDbStationToStation(row("unknown"), []),
    mapDbStationToStation(row("estimate"), [connectorRow("ce", "estimate", { price_estimate_per_kwh: 21 })]),
    mapDbStationToStation(row("invalid", { min_price_per_kwh: Number.POSITIVE_INFINITY }), []),
  ];

  const freeOnly = filterAndSortStations(stations, {
    filters: { ...DEFAULT_EXPLORE_FILTERS, freeOnly: true },
  });
  const displayFree = stations.filter((s) => stationPriceDisplay(s, t).state === "free");
  assert.deepEqual(
    freeOnly.map((s) => s.id).sort(),
    displayFree.map((s) => s.id).sort(),
    "freeOnly filter must select exactly the stations the UI shows as Free"
  );

  const priceStateToDisplay = {
    free: "free",
    verified: "verified",
    "unverified-estimate-only": "estimate",
    unavailable: "unavailable",
  };
  const evals = new Map(evaluateRecommendations(stations).map((e) => [e.stationId, e.priceState]));
  for (const s of stations) {
    assert.equal(
      priceStateToDisplay[evals.get(s.id)],
      stationPriceDisplay(s, t).state,
      `${s.id}: recommender priceState and UI price display disagree`
    );
  }
});

test("10. all four surfaces delegate to the shared helper (no local price formatting)", () => {
  for (const [name, code] of [
    ["StationCard", card],
    ["StationPreviewSheet", sheet],
    ["MapLibreMap", map],
    ["StationDetail", detail],
  ]) {
    assert.match(code, /stationPriceDisplay\(/, `${name} must use the shared price helper`);
    assert.doesNotMatch(code, /pricePerKwh\.toFixed\(/, `${name} must not format prices locally`);
    assert.doesNotMatch(code, /priceEstimatePerKwh\.toFixed\(/, `${name} must not format estimates locally`);
    assert.doesNotMatch(code, /₹\{/, `${name} must not build raw rupee strings`);
    assert.doesNotMatch(code, /t\("station\.perKwh"/, `${name} must not bypass the shared helper`);
  }
  assert.match(map, /escapeHtml\(stationPriceDisplay\(/, "popup must escape the helper output");
  assert.match(detail, /connectorPriceDisplay\(/, "detail connector rows must use the connector helper");
  assert.match(detail, /priceDisplay\.state === "estimate"/, "detail must flag estimate prices");
  assert.match(detail, /t\("station\.priceEstimateDisclaimer"\)/, "detail estimate must carry its disclaimer");
  assert.match(detail, /priceDisplay\.state === "free"/, "detail must keep the free-parking note");
});
