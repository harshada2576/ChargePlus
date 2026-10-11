import test from "node:test";
import assert from "node:assert/strict";
import {
  distanceKm,
  getMaxPowerKw,
  getTotalChargers,
  fetchStations,
} from "../src/data/stations.ts";
import { mapDbStationToStation } from "../src/data/stationAdapter.ts";
import {
  DEFAULT_EXPLORE_FILTERS,
  filterAndSortStations,
  mappableStations,
  toStationGeoJSON,
  resolveSelectedStation,
  visibleSelection,
  exploreLoadState,
  isOpenNow,
} from "../src/data/exploreQuery.ts";

function mockClient({ stationsError = null, stations = [] } = {}) {
  return {
    from(table) {
      const error = table === "v_station_current_state" ? stationsError : null;
      const data = table === "v_station_current_state" ? stations : [];
      const result = { data: error ? null : data, error };
      return { select: () => Promise.resolve(result) };
    },
  };
}

function conn(id, stationId, overrides = {}) {
  return {
    id,
    station_id: stationId,
    connector_type: "CCS2",
    power_kw: 60,
    total_quantity: 2,
    latest_available_connectors: null,
    ...overrides,
  };
}

function mkStation(row, connectors = []) {
  return mapDbStationToStation(row, connectors);
}

// Canonical-shaped fixtures (live view row shapes, honest unknowns).
const ROW_A = {
  id: "sf-a",
  name: "Andheri Fast Hub",
  operator_name: "Tata Power",
  locality: "Andheri",
  address_line: "Link Road",
  city: "Mumbai",
  latitude: 19.076,
  longitude: 72.877,
  operational_status: "operational",
  latest_availability_status: "available",
  min_price_per_kwh: 18,
  is_24_hours: true,
  avg_rating: 4.5,
  review_count: 10,
};
const ROW_B = {
  id: "sf-b",
  name: "Bandra Unknown Stop",
  operator_name: null,
  locality: "Bandra",
  address_line: null,
  city: "Mumbai",
  latitude: 19.0596,
  longitude: 72.8295,
  operational_status: "operational",
  latest_availability_status: null,
  min_price_per_kwh: null,
  avg_rating: null,
  review_count: 0,
};
const ROW_C = {
  id: "sf-c",
  name: "CINEMAX Kalyan",
  operator_name: "ChargeZone",
  locality: "Khadakpada",
  address_line: "Tycoons Residency",
  city: "Kalyan",
  latitude: 19.2436,
  longitude: 73.1347,
  operational_status: "operational",
  latest_availability_status: "busy",
  min_price_per_kwh: 0,
  opening_time: "08:00:00",
  closing_time: "22:00:00",
  avg_rating: 4.5,
  review_count: 4,
};
const ROW_D = {
  id: "sf-d",
  name: "Vikhroli Depot",
  operator_name: "Tata & Sons",
  locality: null,
  address_line: null,
  city: null,
  state: null,
  latitude: null,
  longitude: null,
  operational_status: "temporarily_unavailable",
  latest_availability_status: null,
  min_price_per_kwh: null,
  avg_rating: null,
  review_count: 0,
};

function catalog() {
  return [
    mkStation(ROW_A, [conn("c-a1", "sf-a")]),
    mkStation(ROW_B, [conn("c-b1", "sf-b", { connector_type: "Type 2", power_kw: null, total_quantity: null })]),
    mkStation(ROW_C, [conn("c-c1", "sf-c", { connector_type: "CHAdeMO", power_kw: 50, total_quantity: 1 })]),
    mkStation(ROW_D, []),
  ];
}

const NOON = new Date(2026, 5, 15, 12, 0, 0);
const NIGHT = new Date(2026, 5, 15, 23, 30, 0);

test("1. Search is case-insensitive", () => {
  const all = catalog();
  for (const q of ["cinemax", "CINEMAX", "CiNeMaX"]) {
    const out = filterAndSortStations(all, { query: q });
    assert.equal(out.length, 1);
    assert.equal(out[0].id, "sf-c");
  }
});

test("2. Whitespace is trimmed and empty search restores all", () => {
  const all = catalog();
  assert.equal(filterAndSortStations(all, { query: "  andheri  " })[0].id, "sf-a");
  assert.equal(filterAndSortStations(all, { query: "" }).length, 4);
  assert.equal(filterAndSortStations(all, { query: "   " }).length, 4);
});

test("3. Partial name, operator, and location matching", () => {
  const all = catalog();
  assert.equal(filterAndSortStations(all, { query: "andh" })[0].id, "sf-a");
  assert.equal(filterAndSortStations(all, { query: "tata" }).length, 2); // operator Tata Power + Tata & Sons
  assert.equal(filterAndSortStations(all, { query: "khadak" })[0].id, "sf-c");
  assert.equal(filterAndSortStations(all, { query: "no-such-place-xyz" }).length, 0);
});

test("4. Missing searchable fields never crash", () => {
  const all = catalog();
  const sparse = mkStation({ id: "sf-x", name: "Lonely Post", latitude: 19.1, longitude: 72.9 });
  assert.equal(sparse.operator, "Unknown Operator");
  assert.equal(sparse.address, "Address unavailable");
  const out = filterAndSortStations([...all, sparse], { query: "lonely" });
  assert.equal(out.length, 1);
  assert.equal(filterAndSortStations([...all, sparse], { query: "" }).length, 5);
});

test("5. Multiple filters compose on the same collection", () => {
  const all = catalog();
  const out = filterAndSortStations(all, {
    query: "a",
    filters: { ...DEFAULT_EXPLORE_FILTERS, availableOnly: true, maxPrice: 20 },
  });
  assert.equal(out.length, 1);
  assert.equal(out[0].id, "sf-a");
  const combo = filterAndSortStations(all, {
    filters: { ...DEFAULT_EXPLORE_FILTERS, connectorTypes: ["CHAdeMO"], freeOnly: true },
  });
  assert.equal(combo.length, 1);
  assert.equal(combo[0].id, "sf-c");
});

test("6. Connector-type filter never matches Unknown", () => {
  const all = catalog();
  const ccs2 = filterAndSortStations(all, {
    filters: { ...DEFAULT_EXPLORE_FILTERS, connectorTypes: ["CCS2"] },
  });
  assert.deepEqual(ccs2.map((s) => s.id), ["sf-a"]);
  const mixed = mkStation(ROW_A, [
    conn("m1", "sf-a", { connector_type: null }),
    conn("m2", "sf-a", { connector_type: "CCS2" }),
  ]);
  assert.equal(
    filterAndSortStations([mixed], {
      filters: { ...DEFAULT_EXPLORE_FILTERS, connectorTypes: ["CCS2"] },
    }).length,
    1
  ); // station-level some() semantics preserved
});

test("7. Power thresholds ignore null power", () => {
  const fast = mkStation({ ...ROW_A, id: "p-fast" }, [conn("pf", "p-fast", { power_kw: 120 })]);
  const slow = mkStation({ ...ROW_A, id: "p-slow" }, [conn("ps", "p-slow", { power_kw: 22 })]);
  const nullP = mkStation({ ...ROW_A, id: "p-null" }, [conn("pn", "p-null", { power_kw: null })]);
  const all = [fast, slow, nullP];
  assert.equal(getMaxPowerKw(nullP), 0);
  assert.deepEqual(
    filterAndSortStations(all, { filters: { ...DEFAULT_EXPLORE_FILTERS, minPowerKw: 50 } }).map((s) => s.id),
    ["p-fast"]
  );
  assert.deepEqual(
    filterAndSortStations(all, { filters: { ...DEFAULT_EXPLORE_FILTERS, fastCharging: true } }).map((s) => s.id),
    ["p-fast"]
  );
  assert.equal(
    filterAndSortStations(all, { filters: { ...DEFAULT_EXPLORE_FILTERS, minPowerKw: 0 } }).length,
    3
  ); // threshold off disables the filter
});

test("8. Charger-count filter distinguishes known zero from unknown", () => {
  const two = mkStation({ ...ROW_A, id: "n-two" }, [conn("n1", "n-two", { total_quantity: 2 })]);
  const unknownQty = mkStation({ ...ROW_A, id: "n-unk" }, [conn("n2", "n-unk", { total_quantity: null })]);
  const bare = mkStation({ ...ROW_A, id: "n-bare" }, []);
  assert.equal(getTotalChargers(unknownQty), null);
  assert.equal(getTotalChargers(bare), 0); // known zero: no equipment records
  const all = [two, unknownQty, bare];
  assert.deepEqual(
    filterAndSortStations(all, { filters: { ...DEFAULT_EXPLORE_FILTERS, minChargers: 1 } }).map((s) => s.id),
    ["n-two"]
  );
  assert.deepEqual(
    filterAndSortStations(all, { filters: { ...DEFAULT_EXPLORE_FILTERS, minChargers: 2 } }).map((s) => s.id),
    ["n-two"]
  );
});

test("9. Availability filter needs telemetry evidence", () => {
  const all = catalog();
  const out = filterAndSortStations(all, {
    filters: { ...DEFAULT_EXPLORE_FILTERS, availableOnly: true },
  });
  assert.deepEqual(out.map((s) => s.id), ["sf-a"]);
});

test("10. Free/paid filters never treat unknown price as free", () => {
  const all = catalog();
  assert.deepEqual(
    filterAndSortStations(all, { filters: { ...DEFAULT_EXPLORE_FILTERS, freeOnly: true } }).map((s) => s.id),
    ["sf-c"] // explicit ₹0 only
  );
  assert.deepEqual(
    filterAndSortStations(all, { filters: { ...DEFAULT_EXPLORE_FILTERS, maxPrice: 20 } }).map((s) => s.id).sort(),
    ["sf-a", "sf-c"] // null prices excluded, cannot prove under cap
  );
});

test("11. Open-now excludes unknown hours", () => {
  const all = catalog();
  const open = filterAndSortStations(all, {
    filters: { ...DEFAULT_EXPLORE_FILTERS, openNow: true },
    now: NOON,
  }).map((s) => s.id).sort();
  assert.deepEqual(open, ["sf-a", "sf-c"]); // 24h + open interval; unknown excluded
  assert.equal(isOpenNow(all[1], NOON), false);
  const night = filterAndSortStations(all, {
    filters: { ...DEFAULT_EXPLORE_FILTERS, openNow: true },
    now: NIGHT,
  }).map((s) => s.id);
  assert.deepEqual(night, ["sf-a"]); // 08:00-22:00 closed at 23:30
  const overnight = mkStation(
    { ...ROW_A, id: "sf-night", is_24_hours: false, opening_time: "22:00:00", closing_time: "06:00:00" },
    [conn("on", "sf-night")]
  );
  assert.equal(isOpenNow(overnight, NIGHT), true);
  assert.equal(isOpenNow(overnight, NOON), false);
});

test("12. Invalid coordinates fail radius filters and sort last without crashing", () => {
  const all = catalog();
  const userLoc = { lat: 19.076, lng: 72.877 };
  const near = filterAndSortStations(all, {
    filters: { ...DEFAULT_EXPLORE_FILTERS, distanceKm: 5 },
    userLoc,
  });
  assert.ok(!near.some((s) => s.id === "sf-d")); // Infinity never within radius
  const sorted = filterAndSortStations(all, { sort: "nearest", userLoc });
  assert.equal(sorted[sorted.length - 1].id, "sf-d");
  assert.equal(distanceKm(userLoc, { lat: NaN, lng: NaN }), Number.POSITIVE_INFINITY);
});

test("13. Sorting is deterministic with stable ties", () => {
  const all = catalog();
  const first = filterAndSortStations(all, { sort: "available" }).map((s) => s.id);
  const second = filterAndSortStations(all, { sort: "available" }).map((s) => s.id);
  assert.deepEqual(first, second);
  const twinA = mkStation({ ...ROW_B, id: "tw-a", name: "Twin" });
  const twinB = mkStation({ ...ROW_B, id: "tw-b", name: "Twin" });
  const twins = filterAndSortStations([twinA, twinB], { sort: "recommended" }).map((s) => s.id);
  assert.deepEqual(twins, ["tw-a", "tw-b"]); // equal keys keep input order
  const price = filterAndSortStations(all, { sort: "price" });
  assert.equal(price[price.length - 1].pricePerKwh, null); // unknown prices sort last
});

test("14. Filtering never mutates inputs", () => {
  const all = catalog();
  const before = JSON.stringify(all);
  const filtersBefore = JSON.stringify(DEFAULT_EXPLORE_FILTERS);
  filterAndSortStations(all, { query: "a", filters: { ...DEFAULT_EXPLORE_FILTERS, maxPrice: 20 }, sort: "price" });
  assert.equal(JSON.stringify(all), before);
  assert.equal(JSON.stringify(DEFAULT_EXPLORE_FILTERS), filtersBefore);
});

test("15. Counts match the visible set", () => {
  const all = catalog();
  const out = filterAndSortStations(all, { query: "a" });
  assert.equal(out.length, out.filter((s) => s != null).length);
  assert.equal(exploreLoadState(false, null, out.length), "ready");
  assert.equal(exploreLoadState(false, null, 0), "empty");
});

test("16. Map markers mirror the filtered list", () => {
  const all = catalog();
  const out = filterAndSortStations(all, { query: "a", filters: { ...DEFAULT_EXPLORE_FILTERS, maxPrice: 20 } });
  const ids = new Set(out.map((s) => s.id));
  for (const m of mappableStations(out)) assert.ok(ids.has(m.id));
  const geo = toStationGeoJSON(out);
  assert.equal(geo.features.length, mappableStations(out).length);
  assert.ok(!geo.features.some((f) => f.id === "sf-d"));
});

test("17. Selection clears when filtered out and restores on reset", () => {
  const all = catalog();
  const selectedId = "sf-b";
  const narrowed = filterAndSortStations(all, {
    filters: { ...DEFAULT_EXPLORE_FILTERS, availableOnly: true },
  });
  assert.equal(visibleSelection(selectedId, narrowed), null);
  assert.equal(resolveSelectedStation(visibleSelection(selectedId, narrowed), narrowed, all), null);
  assert.equal(selectedId, "sf-b"); // raw id retained, no mutation
  const reset = filterAndSortStations(all, { filters: { ...DEFAULT_EXPLORE_FILTERS } });
  assert.equal(visibleSelection(selectedId, reset), "sf-b");
  assert.equal(resolveSelectedStation(visibleSelection(selectedId, reset), reset, all)?.id, "sf-b");
});

test("18. Default filters restore the full collection", () => {
  const all = catalog();
  assert.deepEqual(DEFAULT_EXPLORE_FILTERS, {
    distanceKm: 0,
    connectorTypes: [],
    minPowerKw: 0,
    openNow: false,
    availableOnly: false,
    fastCharging: false,
    freeOnly: false,
    lessBusy: false,
    maxPrice: 0,
    minChargers: 0,
  });
  assert.equal(filterAndSortStations(all, { filters: { ...DEFAULT_EXPLORE_FILTERS } }).length, all.length);
});

test("19. Empty results are distinct from query failure", () => {
  assert.equal(exploreLoadState(false, null, 0), "empty");
  assert.equal(exploreLoadState(false, "boom", 0), "error");
  assert.notEqual(exploreLoadState(false, null, 0), exploreLoadState(false, "boom", 0));
  return assert.rejects(
    () => fetchStations(mockClient({ stationsError: { message: "db down" } })),
    /db down/
  );
});

test("20. No fabricated stations in the search/filter path", async () => {
  const rows = [
    { id: "live-1", name: "Live One", latitude: 19.1, longitude: 72.9 },
    { id: "live-2", name: "Live Two", latitude: 19.2, longitude: 73.0 },
  ];
  const loaded = await fetchStations(mockClient({ stations: rows }));
  const out = filterAndSortStations(loaded, { query: "live" });
  assert.equal(out.length, 2);
  const inputIds = new Set(loaded.map((s) => s.id));
  for (const s of out) assert.ok(inputIds.has(s.id)); // closed world: nothing invented
});

test("21. Cold-start filters match nothing without evidence", () => {
  const all = catalog();
  assert.equal(
    filterAndSortStations(all, { filters: { ...DEFAULT_EXPLORE_FILTERS, lessBusy: true } }).length,
    0
  ); // busyWindows empty until ML/temporal evidence exists
  const rec = filterAndSortStations(all, { sort: "recommended" });
  assert.ok(rec.length > 0); // ranking still total, unknown ratings treated as 0
});
