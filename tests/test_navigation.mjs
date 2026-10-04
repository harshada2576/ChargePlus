import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  BOTTOM_NAV_ITEMS,
  HEADER_NAV_ITEMS,
} from "../src/data/navigation.ts";
import {
  DEFAULT_EXPLORE_FILTERS,
  filterAndSortStations,
  resolveSelectedStation,
  visibleSelection,
  stationDetailHref,
} from "../src/data/exploreQuery.ts";
import { fetchStations, fetchStationById } from "../src/data/stations.ts";
import { mapDbStationToStation } from "../src/data/stationAdapter.ts";
import { externalMapUrl } from "../src/lib/util.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = path.join(HERE, "..", "src", "app");

function stA() {
  return mapDbStationToStation(
    {
      id: "nav-a",
      name: "Nav Alpha",
      operator_name: "Tata Power",
      locality: "Andheri",
      latitude: 19.076,
      longitude: 72.877,
      operational_status: "operational",
      latest_availability_status: "available",
      min_price_per_kwh: 18,
    },
    [
      {
        id: "c-a",
        station_id: "nav-a",
        connector_type: "CCS2",
        power_kw: 120,
        total_quantity: 2,
        latest_available_connectors: null,
      },
    ]
  );
}

function stB() {
  return mapDbStationToStation({
    id: "nav-b",
    name: "Nav Beta",
    operator_name: null,
    locality: "Bandra",
    latitude: 19.0596,
    longitude: 72.8295,
    operational_status: "operational",
    latest_availability_status: null,
    min_price_per_kwh: null,
  });
}

function mockClient({ stationsError = null, stations = [], stationById = null } = {}) {
  return {
    from(table) {
      const error = table === "v_station_current_state" ? stationsError : null;
      const eq = (_column, value) => {
        const row = error ? null : stationById && stationById.id === value ? stationById : null;
        const eqResult = { data: row, error };
        return Object.assign(Promise.resolve(eqResult), {
          maybeSingle: () => Promise.resolve(eqResult),
        });
      };
      const data = error ? null : table === "v_station_current_state" ? stations : [];
      return { select: () => Object.assign(Promise.resolve({ data, error }), { eq }) };
    },
  };
}

// Real route inventory: every directory under src/app holding a page.tsx
// (API routes excluded — they are not navigation destinations).
function collectRoutes() {
  const routes = new Set();
  function walk(dir, rel) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const sub = rel ? `${rel}/${entry.name}` : entry.name;
      const full = path.join(dir, entry.name);
      if (entry.name === "api") continue;
      if (fs.existsSync(path.join(full, "page.tsx"))) routes.add(`/${sub}`);
      walk(full, sub);
    }
  }
  if (fs.existsSync(path.join(APP_DIR, "page.tsx"))) routes.add("/");
  walk(APP_DIR, "");
  return routes;
}

function resolves(routes, href) {
  const clean = href.split("?")[0].split("#")[0];
  if (routes.has(clean === "" ? "/" : clean)) return true;
  const segs = clean.split("/").filter(Boolean);
  for (let i = 0; i < segs.length; i++) {
    const dyn = [...segs];
    dyn[i] = "[id]";
    if (routes.has(`/${dyn.join("/")}`)) return true;
  }
  return false;
}

test("1. List selection opens the correct preview", () => {
  const all = [stA(), stB()];
  const filtered = filterAndSortStations(all, {});
  const selectedId = "nav-b"; // list onClick sets the canonical id
  const preview = resolveSelectedStation(visibleSelection(selectedId, filtered), filtered, all);
  assert.equal(preview?.id, "nav-b");
  assert.equal(preview?.name, "Nav Beta");
});

test("2. Marker selection opens the matching preview", () => {
  const all = [stA(), stB()];
  const filtered = filterAndSortStations(all, {});
  const fromMarker = "nav-a"; // map onSelect sets the same canonical id
  const fromList = "nav-a";
  assert.equal(
    resolveSelectedStation(visibleSelection(fromMarker, filtered), filtered, all)?.id,
    resolveSelectedStation(visibleSelection(fromList, filtered), filtered, all)?.id
  );
});

test("3. Preview navigation uses the canonical station ID", () => {
  const id = "2979dde1-c576-437b-b881-3bea4c43a70d";
  assert.equal(stationDetailHref(id), `/station/${id}`);
});

test("4. Switching stations updates preview identity", () => {
  const all = [stA(), stB()];
  const filtered = filterAndSortStations(all, {});
  let selectedId = "nav-a";
  assert.equal(resolveSelectedStation(visibleSelection(selectedId, filtered), filtered, all)?.id, "nav-a");
  selectedId = "nav-b"; // selecting another station replaces the first
  assert.equal(resolveSelectedStation(visibleSelection(selectedId, filtered), filtered, all)?.id, "nav-b");
});

test("5. Closing the preview reconciles selection", () => {
  const all = [stA(), stB()];
  const filtered = filterAndSortStations(all, {});
  assert.equal(resolveSelectedStation(visibleSelection(null, filtered), filtered, all), null);
});

test("6. Filtering out the selection clears the preview", () => {
  const all = [stA(), stB()];
  const narrowed = filterAndSortStations(all, {
    filters: { ...DEFAULT_EXPLORE_FILTERS, availableOnly: true },
  });
  assert.equal(visibleSelection("nav-b", narrowed), null);
  assert.equal(resolveSelectedStation(visibleSelection("nav-b", narrowed), narrowed, all), null);
});

test("7. A missing station never falls back to a hardcoded station", async () => {
  const row = { id: "nav-a", name: "Nav Alpha", latitude: 19.076, longitude: 72.877 };
  const st = await fetchStationById("11111111-1111-1111-1111-111111111111", mockClient({ stationById: row }));
  assert.equal(st, null);
});

test("8. Malformed IDs follow not-found behavior", async () => {
  assert.equal(await fetchStationById("", mockClient({})), null);
  assert.equal(await fetchStationById("station-3", mockClient({})), null);
});

test("9. Query failures stay distinguishable from missing records", async () => {
  await assert.rejects(
    () =>
      fetchStationById(
        "2979dde1-c576-437b-b881-3bea4c43a70d",
        mockClient({ stationsError: { message: "timeout" } })
      ),
    /timeout/
  );
});

test("10. The Explore return route exists", () => {
  assert.ok(resolves(collectRoutes(), "/explore"));
});

test("11. Primary navigation links resolve to real routes", () => {
  const routes = collectRoutes();
  assert.ok(routes.size > 10);
  for (const item of [...BOTTOM_NAV_ITEMS, ...HEADER_NAV_ITEMS]) {
    assert.ok(resolves(routes, item.href), `dead navigation href: ${item.href}`);
  }
  assert.ok(resolves(routes, stationDetailHref("nav-a")));
});

test("12. URL encoding keeps unusual identifiers safe", () => {
  const weird = "a/b?c=d e&f=g";
  const href = stationDetailHref(weird);
  assert.ok(!href.includes("?") && !href.includes(" "));
  assert.equal(decodeURIComponent(href.split("/station/")[1]), weird);
});

test("13. External map links require valid coordinates", () => {
  const good = { lat: 19.076, lng: 72.877, name: "A" };
  assert.ok(externalMapUrl("google", good)?.startsWith("https://www.google.com/"));
  assert.ok(externalMapUrl("apple", good)?.startsWith("https://maps.apple.com/"));
  assert.ok(externalMapUrl("geo", good)?.startsWith("geo:"));
  for (const bad of [
    { lat: NaN, lng: 72.8, name: "A" },
    { lat: 19.1, lng: NaN, name: "A" },
    { lat: 0, lng: 0, name: "A" },
    { lat: 91, lng: 72.8, name: "A" },
  ]) {
    assert.equal(externalMapUrl("google", bad), null);
    assert.equal(externalMapUrl("apple", bad), null);
    assert.equal(externalMapUrl("geo", bad), null);
  }
});

test("14. Selection transitions are stable and single-pathed", () => {
  const all = [stA(), stB()];
  const filtered = filterAndSortStations(all, {});
  const seq = ["nav-a", "nav-a", "nav-b", null].map(
    (id) => resolveSelectedStation(visibleSelection(id, filtered), filtered, all)?.id ?? null
  );
  assert.deepEqual(seq, ["nav-a", "nav-a", "nav-b", null]);
});

test("16. No prototype data enters the discovery journey", async () => {
  const rows = [
    { id: "nav-a", name: "Nav Alpha", latitude: 19.076, longitude: 72.877 },
    { id: "nav-b", name: "Nav Beta", latitude: 19.0596, longitude: 72.8295 },
  ];
  const loaded = await fetchStations(mockClient({ stations: rows }));
  const visible = filterAndSortStations(loaded, { query: "nav" });
  const ids = new Set(loaded.map((s) => s.id));
  for (const s of visible) assert.ok(ids.has(s.id));
});
