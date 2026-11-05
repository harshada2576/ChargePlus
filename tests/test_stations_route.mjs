import test from "node:test";
import assert from "node:assert/strict";
import { mock } from "node:test";
import { resetRateLimits } from "../src/lib/rateLimit.ts";

let mockStations = [];
mock.module("@/data/stations", {
  namedExports: {
    fetchStations: async () => mockStations,
    distanceKm: (a, b) => {
      if (!a || !b) return Number.POSITIVE_INFINITY;
      const R = 6371;
      const dLat = ((b.lat - a.lat) * Math.PI) / 180;
      const dLng = ((b.lng - a.lng) * Math.PI) / 180;
      const x =
        Math.sin(dLat / 2) ** 2 +
        Math.sin(dLng / 2) ** 2 *
          Math.cos((a.lat * Math.PI) / 180) *
          Math.cos((b.lat * Math.PI) / 180);
      return 2 * R * Math.asin(Math.sqrt(x));
    },
    getMaxPowerKw: (s) => s.connectors.reduce((m, c) => Math.max(m, c.powerKw ?? 0), 0),
    getTotalChargers: (s) =>
      s.connectors.reduce((sum, c) => (c.total != null ? sum + c.total : sum), 0),
    getAvailableChargers: (s) =>
      s.connectors.reduce((sum, c) => (c.available != null ? sum + c.available : sum), 0),
  },
});

const { GET } = await import("../src/app/api/stations/route.ts");

function req(url = "http://test/api/stations", ip = "10.0.0.1") {
  const reqObj = new Request(url, {
    headers: { "x-forwarded-for": ip },
  });
  return reqObj;
}

function mkStation(overrides = {}) {
  return {
    id: "stn-" + Math.random().toString(36).slice(2, 8),
    name: "Test Station",
    operator: "Test Operator",
    area: "Bandra",
    address: "Bandra West, Mumbai",
    lat: 19.0596,
    lng: 72.8295,
    status: "available",
    minutesSinceUpdate: 10,
    connectors: [
      {
        id: "c-1",
        type: "CCS2",
        powerKw: 60,
        total: 2,
        available: 1,
      },
    ],
    pricePerKwh: 18,
    isFree: false,
    hours: { kind: "24h" },
    rating: 4.5,
    reviewCount: 5,
    busyWindows: [],
    ...overrides,
  };
}

test("/api/stations: rate limit allows normal traffic and throttles bursts with 429", async () => {
  resetRateLimits();
  mockStations = [mkStation()];

  for (let i = 0; i < 120; i++) {
    const res = await GET(req("http://test/api/stations", "192.168.1.10"));
    assert.equal(res.status, 200);
  }
  const throttled = await GET(req("http://test/api/stations", "192.168.1.10"));
  assert.equal(throttled.status, 429);
  assert.ok(throttled.headers.has("Retry-After"));
});

test("/api/stations: supports multiple connector types with OR semantics", async () => {
  resetRateLimits();
  const stnCCS2 = mkStation({
    id: "s-ccs2",
    name: "CCS2 Station",
    connectors: [{ id: "c1", type: "CCS2", powerKw: 60, total: 1, available: 1 }],
  });
  const stnType2 = mkStation({
    id: "s-type2",
    name: "Type 2 Station",
    connectors: [{ id: "c2", type: "Type 2", powerKw: 22, total: 1, available: 1 }],
  });
  const stnChademo = mkStation({
    id: "s-chademo",
    name: "CHAdeMO Station",
    connectors: [{ id: "c3", type: "CHAdeMO", powerKw: 50, total: 1, available: 1 }],
  });
  mockStations = [stnCCS2, stnType2, stnChademo];

  // Requesting connectorTypes=CCS2,Type 2 should match both stnCCS2 and stnType2
  const res = await GET(
    req("http://test/api/stations?connectorTypes=CCS2,Type%202", "10.0.0.2")
  );
  assert.equal(res.status, 200);
  const data = await res.json();
  assert.equal(data.total, 2);
  const ids = data.stations.map((s) => s.id);
  assert.ok(ids.includes("s-ccs2"));
  assert.ok(ids.includes("s-type2"));
  assert.ok(!ids.includes("s-chademo"));
});

test("/api/stations: supports pagination beyond first page", async () => {
  resetRateLimits();
  mockStations = Array.from({ length: 55 }, (_, i) =>
    mkStation({ id: `p-${i}`, name: `Station ${i}` })
  );

  const resPage1 = await GET(
    req("http://test/api/stations?limit=20&offset=0", "10.0.0.3")
  );
  const data1 = await resPage1.json();
  assert.equal(data1.total, 55);
  assert.equal(data1.stations.length, 20);
  assert.equal(data1.hasMore, true);
  assert.equal(data1.offset, 0);

  const resPage2 = await GET(
    req("http://test/api/stations?limit=20&offset=20", "10.0.0.3")
  );
  const data2 = await resPage2.json();
  assert.equal(data2.stations.length, 20);
  assert.equal(data2.hasMore, true);
  assert.equal(data2.offset, 20);

  const resPage3 = await GET(
    req("http://test/api/stations?limit=20&offset=40", "10.0.0.3")
  );
  const data3 = await resPage3.json();
  assert.equal(data3.stations.length, 15);
  assert.equal(data3.hasMore, false);
});

test("/api/stations: respects observation freshness decay (stale observations are unknown)", async () => {
  resetRateLimits();
  const availableFresh = mkStation({ id: "fresh-avail", status: "available" });
  const staleUnknown = mkStation({ id: "stale-unk", status: "unknown" });
  mockStations = [availableFresh, staleUnknown];

  const res = await GET(
    req("http://test/api/stations?availableOnly=true", "10.0.0.4")
  );
  const data = await res.json();
  assert.equal(data.total, 1);
  assert.equal(data.stations[0].id, "fresh-avail");
});

test("/api/stations: applies distance and minChargers filters accurately", async () => {
  resetRateLimits();
  const nearStation = mkStation({
    id: "near",
    lat: 19.0596,
    lng: 72.8295,
    connectors: [{ id: "c1", type: "CCS2", powerKw: 60, total: 4, available: 2 }],
  });
  const farStation = mkStation({
    id: "far",
    lat: 19.2436,
    lng: 73.1347, // ~35km away
    connectors: [{ id: "c2", type: "CCS2", powerKw: 60, total: 1, available: 1 }],
  });
  mockStations = [nearStation, farStation];

  // 1. Distance filter: 10km radius from Bandra
  const resDist = await GET(
    req(
      "http://test/api/stations?distanceKm=10&userLat=19.0596&userLng=72.8295",
      "10.0.0.5"
    )
  );
  const dataDist = await resDist.json();
  assert.equal(dataDist.total, 1);
  assert.equal(dataDist.stations[0].id, "near");

  // 2. Charger count filter: minChargers=2
  const resChargers = await GET(
    req("http://test/api/stations?minChargers=2", "10.0.0.5")
  );
  const dataChargers = await resChargers.json();
  assert.equal(dataChargers.total, 1);
  assert.equal(dataChargers.stations[0].id, "near");
});

test("/api/stations: lessBusy matches verified available stations and does not return empty list", async () => {
  resetRateLimits();
  const availStation = mkStation({ id: "s-avail", status: "available" });
  const busyStation = mkStation({ id: "s-busy", status: "busy" });
  const unknownStation = mkStation({ id: "s-unk", status: "unknown" });
  mockStations = [availStation, busyStation, unknownStation];

  const res = await GET(
    req("http://test/api/stations?lessBusy=true", "10.0.0.6")
  );
  const data = await res.json();
  assert.equal(data.total, 1);
  assert.equal(data.stations[0].id, "s-avail");
});
