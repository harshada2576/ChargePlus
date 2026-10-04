import test from "node:test";
import assert from "node:assert/strict";
import {
  fetchStations,
  fetchStationById,
  getReviewsForStation,
} from "../src/data/stations.ts";
import { mapDbStationToStation } from "../src/data/stationAdapter.ts";
import {
  escapeHtml,
  isValidCoordinate,
  externalMapUrl,
} from "../src/lib/util.ts";
import { stationDetailHref } from "../src/data/exploreQuery.ts";

function mockClient({
  stationsError = null,
  connectorsError = null,
  stations = [],
  connectors = [],
  stationById = null,
  calls = null,
} = {}) {
  return {
    from(table) {
      if (calls) calls.push(table);
      const isStations = table === "v_station_current_state";
      const error = isStations ? stationsError : connectorsError;
      const eq = (_column, value) => {
        if (isStations) {
          const row = error
            ? null
            : stationById && stationById.id === value
              ? stationById
              : null;
          const eqResult = { data: row, error };
          return Object.assign(Promise.resolve(eqResult), {
            maybeSingle: () => Promise.resolve(eqResult),
          });
        }
        const rows = error ? null : connectors.filter((c) => c.station_id === value);
        return Object.assign(Promise.resolve({ data: rows, error }), {
          maybeSingle: () => Promise.resolve({ data: rows?.[0] ?? null, error }),
        });
      };
      const result = { data: error ? null : isStations ? stations : connectors, error };
      return { select: () => Object.assign(Promise.resolve(result), { eq }) };
    },
  };
}

const ROW = {
  id: "2979dde1-c576-437b-b881-3bea4c43a70d",
  name: "Tata Power Receiving Station",
  operator_name: "(Business Owner at Location)",
  address_line: "3, Vikhroli Village Road",
  locality: "Vikhroli",
  city: "Mumbai",
  state: "Maharashtra",
  postal_code: "400077",
  latitude: 19.0957956,
  longitude: 72.9260109,
  operational_status: "operational",
  latest_availability_status: null,
  min_price_per_kwh: null,
  avg_rating: null,
  review_count: 0,
};
const CONN = {
  id: "c163be25-b6b6-46f7-9404-41cb5eee6a92",
  station_id: ROW.id,
  connector_type: "Type 1",
  power_kw: null,
  total_quantity: 3,
  latest_available_connectors: null,
};

test("1. A valid canonical station ID loads the correct station", async () => {
  const st = await fetchStationById(ROW.id, mockClient({ stationById: ROW, connectors: [CONN] }));
  assert.ok(st);
  assert.equal(st.id, ROW.id);
  assert.equal(st.name, ROW.name);
  assert.equal(st.connectors.length, 1);
  assert.equal(st.connectors[0].id, CONN.id);
});

test("2. A nonexistent station returns null (notFound downstream)", async () => {
  const st = await fetchStationById(
    "00000000-0000-0000-0000-000000000000",
    mockClient({ stationById: ROW, connectors: [] })
  );
  assert.equal(st, null);
});

test("3. A query failure throws and never fabricates a station", async () => {
  await assert.rejects(
    () => fetchStationById(ROW.id, mockClient({ stationsError: { message: "db down" } })),
    /fetchStationById error: db down/
  );
  await assert.rejects(
    () => fetchStationById(ROW.id, mockClient({ stationById: ROW, connectorsError: { message: "conn down" } })),
    /conn down/
  );
});

test("3b. A malformed ID returns null without querying", async () => {
  const calls = [];
  const st = await fetchStationById("not-a-uuid", mockClient({ calls }));
  assert.equal(st, null);
  assert.deepEqual(calls, []);
});

test("4. Unknown address, operator, and location render honestly", () => {
  const st = mapDbStationToStation({ id: "x", name: "X", latitude: 19.1, longitude: 72.9 });
  assert.equal(st.operator, "Unknown Operator");
  assert.equal(st.area, "Area unknown");
  assert.equal(st.address, "Address unavailable");
  assert.ok(!st.address.includes("Mumbai") && !st.area.includes("Mumbai"));
});

test("5. Missing coordinates disable directions and map actions", () => {
  const st = mapDbStationToStation({ id: "x", name: "X", latitude: null, longitude: null });
  assert.ok(Number.isNaN(st.lat) && Number.isNaN(st.lng));
  assert.equal(isValidCoordinate(st.lat, st.lng), false);
  assert.equal(externalMapUrl("google", st), null);
  assert.equal(externalMapUrl("apple", st), null);
  assert.equal(externalMapUrl("geo", st), null);
  const ok = { lat: 19.076, lng: 72.8777, name: "Andheri" };
  assert.ok(externalMapUrl("google", ok)?.includes("19.076,72.8777"));
});

test("6. Unknown connector type remains unknown", () => {
  const st = mapDbStationToStation(
    { ...ROW, id: "ct", latitude: 19.1, longitude: 72.9 },
    [{ id: "c", station_id: "ct", connector_type: null, power_kw: 22, total_quantity: 1, latest_available_connectors: null }]
  );
  assert.equal(st.connectors[0].type, "Unknown");
});

test("7. Null connector quantity and power remain unknown", () => {
  const st = mapDbStationToStation(
    { ...ROW, id: "pq", latitude: 19.1, longitude: 72.9 },
    [{ id: "c", station_id: "pq", connector_type: "CCS2", power_kw: null, total_quantity: null, latest_available_connectors: null }]
  );
  assert.equal(st.connectors[0].powerKw, null);
  assert.equal(st.connectors[0].total, null);
});

test("8. Unknown connector availability never becomes available or busy", () => {
  const st = mapDbStationToStation(ROW, [CONN]);
  assert.equal(st.connectors[0].available, null);
  const observed = mapDbStationToStation(ROW, [{ ...CONN, latest_available_connectors: 2 }]);
  assert.equal(observed.connectors[0].available, 2);
});

test("9. Unknown price is neither free nor ₹0", () => {
  const st = mapDbStationToStation(ROW, []);
  assert.equal(st.pricePerKwh, null);
  assert.equal(st.isFree, null);
  assert.notEqual(st.isFree, true);
  const free = mapDbStationToStation({ ...ROW, min_price_per_kwh: 0 });
  assert.equal(free.isFree, true);
  assert.equal(free.pricePerKwh, 0);
});

test("10. Unknown hours are not 24/7", () => {
  assert.deepEqual(mapDbStationToStation(ROW, []).hours, { kind: "unknown" });
  assert.deepEqual(
    mapDbStationToStation({ ...ROW, is_24_hours: true }).hours,
    { kind: "24h" }
  );
});

test("11. Static operational status is not live availability", () => {
  assert.equal(mapDbStationToStation(ROW, []).status, "unknown");
  assert.equal(
    mapDbStationToStation({ ...ROW, latest_availability_status: "available" }).status,
    "available"
  );
  assert.equal(
    mapDbStationToStation({ ...ROW, operational_status: "decommissioned" }).status,
    "broken"
  );
});

test("12. Missing freshness creates no timestamp", () => {
  assert.equal(mapDbStationToStation(ROW, []).minutesSinceUpdate, null);
  const fresh = mapDbStationToStation({ ...ROW, minutes_since_observation: 5.4 });
  assert.equal(fresh.minutesSinceUpdate, 5);
});

test("13. Missing ratings and reviews stay empty, never fabricated", () => {
  const st = mapDbStationToStation(ROW, []);
  assert.equal(st.rating, null);
  assert.equal(st.reviewCount, 0);
  assert.deepEqual(st.busyWindows, []);
  assert.deepEqual(getReviewsForStation(st.id), []);
});

test("14. Empty reviews drive the empty state branch", () => {
  const st = mapDbStationToStation(ROW, []);
  const reviews = getReviewsForStation(st.id);
  assert.equal(reviews.length, 0); // detail renders reviews.empty when length is 0
  assert.equal(st.rating == null, true); // rating header hidden when null
});

test("15. Canonical station ID survives navigation", async () => {
  const st = await fetchStationById(ROW.id, mockClient({ stationById: ROW, connectors: [CONN] }));
  assert.equal(stationDetailHref(st.id), `/station/${ROW.id}`);
  const hostile = "a/b?c=d&e=f";
  assert.equal(
    externalMapUrl("geo", { lat: 19.1, lng: 72.9, name: hostile })?.includes(encodeURIComponent(hostile)),
    true
  );
});

test("16. Escaping and URL safety are preserved", () => {
  assert.equal(
    escapeHtml('<script>alert("x")</script>'),
    "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"
  );
  const evil = '<img src=x onerror=alert(1)>';
  const url = externalMapUrl("geo", { lat: 19.1, lng: 72.9, name: evil });
  assert.ok(url && !url.includes("<img"));
  assert.ok(url.startsWith("geo:"));
  assert.ok(externalMapUrl("google", { lat: 19.1, lng: 72.9, name: evil })?.startsWith("https://"));
});

test("17. No prototype fallback is reachable from the detail route", async () => {
  await assert.rejects(() => fetchStations(mockClient({ stationsError: { message: "nope" } })), /nope/);
  const rows = [{ id: ROW.id, name: ROW.name, latitude: 19.0957956, longitude: 72.9260109 }];
  const loaded = await fetchStations(mockClient({ stations: rows, connectors: [CONN] }));
  assert.ok(loaded.every((s) => rows.some((r) => r.id === s.id))); // closed world
  const empty = await fetchStationById(ROW.id, mockClient({ stationById: ROW, connectors: [] }));
  assert.deepEqual(empty.connectors, []); // no equipment invented for connector-less stations
});
