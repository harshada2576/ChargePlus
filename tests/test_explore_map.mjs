import test from "node:test";
import assert from "node:assert/strict";
import {
  distanceKm,
  getMaxPowerKw,
  getTotalChargers,
  getAvailableChargers,
  fetchStations,
  fetchStationById,
  CANONICAL_STATIONS,
} from "../src/data/stations.ts";
import { isValidCoordinate, escapeHtml } from "../src/lib/util.ts";
import {
  mapDbStationToStation,
  mapDbConnectorToConnector,
  parseStationCoord,
} from "../src/data/stationAdapter.ts";
import {
  DEFAULT_EXPLORE_FILTERS,
  filterAndSortStations,
  mappableStations,
  toStationGeoJSON,
  resolveSelectedStation,
  stationDetailHref,
  exploreLoadState,
  rankAvailability,
} from "../src/data/exploreQuery.ts";

function baseStation(overrides = {}) {
  return mapDbStationToStation({
    id: "st-base",
    name: "Base Station",
    latitude: 19.076,
    longitude: 72.877,
    operational_status: "operational",
    latest_availability_status: null,
    min_price_per_kwh: null,
    avg_rating: null,
    review_count: 0,
    ...overrides,
  });
}

function mockClient({
  stationsError = null,
  connectorsError = null,
  stations = [],
  connectors = [],
  stationById = null,
} = {}) {
  return {
    from(table) {
      const isStations = table === "v_station_current_state";
      const error = isStations ? stationsError : connectorsError;
      const data = isStations ? stations : connectors;
      const result = { data: error ? null : data, error };
      const eq = (_column, value) => {
        if (isStations) {
          const row = error
            ? null
            : (stationById && stationById.id === value ? stationById : null);
          const eqResult = { data: row, error };
          return Object.assign(Promise.resolve(eqResult), {
            maybeSingle: () => Promise.resolve(eqResult),
          });
        }
        const rows = error
          ? null
          : connectors.filter((c) => c.station_id === value);
        return Object.assign(Promise.resolve({ data: rows, error }), {
          maybeSingle: () => Promise.resolve({ data: rows?.[0] ?? null, error }),
        });
      };
      return {
        select: () =>
          Object.assign(Promise.resolve(result), {
            eq,
          }),
      };
    },
  };
}

test("1. Explore loads canonical station data and renders the returned stations", async () => {
  const row = {
    id: "live-id-1",
    name: "Canonical Live Station",
    latitude: 19.1,
    longitude: 72.9,
    operator_name: "Tata Power",
    locality: "Andheri",
    operational_status: "operational",
    latest_availability_status: null,
    min_price_per_kwh: null,
  };
  const loaded = await fetchStations(
    mockClient({
      stations: [row],
      connectors: [
        {
          id: "c1",
          station_id: "live-id-1",
          connector_type: "CCS2",
          power_kw: 120,
          total_quantity: 2,
          latest_available_connectors: null,
        },
      ],
    })
  );
  assert.equal(loaded.length, 1);
  assert.equal(loaded[0].id, "live-id-1");
  assert.equal(loaded[0].name, "Canonical Live Station");
  assert.equal(loaded[0].connectors[0].type, "CCS2");
  const filtered = filterAndSortStations(loaded, { filters: DEFAULT_EXPLORE_FILTERS });
  assert.equal(filtered[0].id, loaded[0].id);
  assert.equal(exploreLoadState(false, null, filtered.length), "ready");
});

test("2. Successful empty response renders the empty state, not the error state", async () => {
  const loaded = await fetchStations(mockClient({ stations: [], connectors: [] }));
  assert.deepEqual(loaded, []);
  assert.equal(exploreLoadState(false, null, loaded.length), "empty");
  assert.notEqual(exploreLoadState(false, null, loaded.length), "error");
});

test("3. Failed query renders an error state and does not load mock data", async () => {
  await assert.rejects(
    () =>
      fetchStations(
        mockClient({ stationsError: { message: "connection refused" } })
      ),
    /fetchStations error: connection refused/
  );
  const state = exploreLoadState(false, "fetchStations error: connection refused", 0);
  assert.equal(state, "error");
  assert.notEqual(state, "empty");
});

test("4. Retry attempts to fetch canonical data again", async () => {
  let attempts = 0;
  function flakyClient() {
    attempts += 1;
    if (attempts === 1) {
      return mockClient({ stationsError: { message: "Transient network failure" } });
    }
    return mockClient({
      stations: [
        {
          id: "st-retry-success",
          name: "Recovered Station",
          latitude: 19.07,
          longitude: 72.87,
        },
      ],
    });
  }

  await assert.rejects(() => fetchStations(flakyClient()), /Transient network failure/);
  const recovered = await fetchStations(flakyClient());
  assert.equal(attempts, 2);
  assert.equal(recovered.length, 1);
  assert.equal(recovered[0].id, "st-retry-success");
  assert.ok(!CANONICAL_STATIONS.some((s) => s.id === "st-retry-success"));
});

test("5. List selection and map selection remain synchronized", () => {
  const stationA = baseStation({ id: "st-a", name: "Station A", latest_availability_status: "busy" });
  const stationB = baseStation({
    id: "st-b",
    name: "Station B",
    latitude: 19.08,
    longitude: 72.88,
    latest_availability_status: "available",
  });
  const all = [stationA, stationB];
  const visible = filterAndSortStations(all);

  let selectedId = "st-b";
  assert.equal(resolveSelectedStation(selectedId, visible, all)?.id, "st-b");
  selectedId = "st-a";
  assert.equal(resolveSelectedStation(selectedId, visible, all)?.id, "st-a");
  selectedId = null;
  assert.equal(resolveSelectedStation(selectedId, visible, all), null);
});

test("6. Invalid/missing coordinates do not generate misleading markers or crash rendering", () => {
  assert.equal(isValidCoordinate(0, 0), false);
  assert.equal(Number.isNaN(parseStationCoord(null)), true);
  assert.equal(parseStationCoord(null) === 0, false, "null must not become Equator 0");
  assert.equal(Number.isNaN(parseStationCoord("")), true);

  const missing = mapDbStationToStation({
    id: "s-missing",
    name: "No coords",
    latitude: null,
    longitude: null,
  });
  assert.equal(Number.isNaN(missing.lat), true);
  assert.equal(Number.isNaN(missing.lng), true);

  const stationsWithCorruptedCoords = [
    baseStation({ id: "s1", name: "Valid Station" }),
    missing,
    baseStation({ id: "s3", name: "Null Island", latitude: 0, longitude: 0 }),
    { ...baseStation({ id: "s4", name: "NaN lng" }), lng: NaN },
  ];

  const valid = mappableStations(stationsWithCorruptedCoords);
  assert.equal(valid.length, 1);
  assert.equal(valid[0].id, "s1");

  const geo = toStationGeoJSON(stationsWithCorruptedCoords);
  assert.equal(geo.features.length, 1);
  assert.deepEqual(geo.features[0].geometry.coordinates, [valid[0].lng, valid[0].lat]);
  assert.equal(geo.features[0].geometry.coordinates[0] === 72.8777, false);

  assert.equal(distanceKm(null, { lat: 19.076, lng: 72.877 }), Number.POSITIVE_INFINITY);
});

test("7. Unknown availability is not converted to available or busy", () => {
  const station = baseStation();
  assert.equal(station.status, "unknown");
  const availableOnly = filterAndSortStations([station], {
    filters: { ...DEFAULT_EXPLORE_FILTERS, availableOnly: true },
  });
  assert.equal(availableOnly.length, 0);
  assert.equal(rankAvailability(station), 3);
});

test("8. Unknown prices are not treated as free", () => {
  const nullPrice = baseStation({ id: "st-null-price" });
  const zeroPrice = baseStation({
    id: "st-zero-price",
    min_price_per_kwh: 0,
    latest_availability_status: "available",
  });
  assert.equal(nullPrice.isFree, null);
  assert.equal(nullPrice.pricePerKwh, null);
  assert.equal(
    filterAndSortStations([nullPrice], {
      filters: { ...DEFAULT_EXPLORE_FILTERS, freeOnly: true },
    }).length,
    0
  );
  assert.equal(
    filterAndSortStations([zeroPrice], {
      filters: { ...DEFAULT_EXPLORE_FILTERS, freeOnly: true },
    }).length,
    1
  );
  assert.equal(
    filterAndSortStations([nullPrice], {
      filters: { ...DEFAULT_EXPLORE_FILTERS, maxPrice: 20 },
    }).length,
    0
  );
});

test("9. Unknown connector types and quantities remain unknown", () => {
  const connMissing = mapDbConnectorToConnector({
    id: "c1",
    station_id: "st-conn-test",
    connector_type: null,
    power_kw: null,
    total_quantity: null,
    latest_available_connectors: null,
  }, "available");
  assert.equal(connMissing.type, "Unknown");
  assert.equal(connMissing.powerKw, null);
  assert.equal(connMissing.total, null);
  assert.equal(connMissing.available, null);

  const station = mapDbStationToStation(
    {
      id: "st-conn-test",
      name: "Connector Test Station",
      latitude: 19.076,
      longitude: 72.877,
      operational_status: "operational",
      latest_availability_status: "available",
      min_price_per_kwh: 15,
    },
    [
      {
        id: "c1",
        station_id: "st-conn-test",
        connector_type: null,
        power_kw: null,
        total_quantity: null,
        latest_available_connectors: null,
      },
    ]
  );
  assert.equal(getMaxPowerKw(station), 0);
  assert.equal(getTotalChargers(station), null);
  assert.equal(getAvailableChargers(station), null);
  assert.equal(
    filterAndSortStations([station], {
      filters: { ...DEFAULT_EXPLORE_FILTERS, connectorTypes: ["CCS2"] },
    }).length,
    0
  );
  assert.equal(
    filterAndSortStations([station], {
      filters: { ...DEFAULT_EXPLORE_FILTERS, minChargers: 1 },
    }).length,
    0
  );
  assert.equal(
    filterAndSortStations([station], {
      filters: { ...DEFAULT_EXPLORE_FILTERS, minPowerKw: 22 },
    }).length,
    0
  );
  assert.equal(
    filterAndSortStations([station], {
      filters: { ...DEFAULT_EXPLORE_FILTERS, fastCharging: true },
    }).length,
    0
  );
});

test("10. Filtering does not mutate the original canonical collection or corrupt selection state", () => {
  const originalStations = [
    baseStation({
      id: "st-1",
      name: "Andheri Fast Hub",
      latest_availability_status: "available",
      min_price_per_kwh: 12,
      avg_rating: 4.2,
      review_count: 10,
    }),
    baseStation({
      id: "st-2",
      name: "Bandra Slow",
      latitude: 19.0596,
      longitude: 72.8295,
      latest_availability_status: "busy",
      min_price_per_kwh: 20,
      avg_rating: 4.8,
      review_count: 25,
    }),
  ];
  const beforeJson = JSON.stringify(originalStations);
  const filtered = filterAndSortStations(originalStations, {
    query: "andheri",
    filters: { ...DEFAULT_EXPLORE_FILTERS, availableOnly: true },
  });
  assert.equal(filtered.length, 1);
  assert.equal(originalStations.length, 2);
  assert.equal(JSON.stringify(originalStations), beforeJson);
  const selected = resolveSelectedStation("st-2", filtered, originalStations);
  assert.equal(selected?.id, "st-2");
});

test("11. Marker/list navigation uses the correct canonical station ID", async () => {
  const row = {
    id: "2979dde1-c576-437b-b881-3bea4c43a70d",
    name: "Tata Power Receiving Station",
    latitude: 19.0957956,
    longitude: 72.9260109,
  };
  const stations = await fetchStations(mockClient({ stations: [row] }));
  assert.equal(stationDetailHref(stations[0].id), `/station/${stations[0].id}`);
  const fetched = await fetchStationById(
    stations[0].id,
    mockClient({ stationById: row, connectors: [] })
  );
  assert.equal(fetched?.id, stations[0].id);
  const nonexistent = await fetchStationById(
    "00000000-0000-0000-0000-000000000000",
    mockClient({ stationById: row })
  );
  assert.equal(nonexistent, null);
});

test("12. Existing HTML escaping protections remain intact", () => {
  const payload1 = '<script>alert("xss")</script>';
  const payload2 = '" onmouseover="alert(\'attack\')"';
  const payload3 = "Tata & Sons 'Special'";
  assert.equal(escapeHtml(payload1), '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;');
  assert.equal(escapeHtml(payload2), '&quot; onmouseover=&quot;alert(&#039;attack&#039;)&quot;');
  assert.equal(escapeHtml(payload3), 'Tata &amp; Sons &#039;Special&#039;');
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(undefined), "");

  const hostile = baseStation({
    id: '"><img src=x onerror=alert(1)>',
    name: '<script>alert("xss")</script>',
    operator_name: "Tom & Jerry",
    locality: "Andheri\" onclick=\"alert(1)",
  });
  const popup = `<p>${escapeHtml(hostile.name)}</p><p>${escapeHtml(hostile.operator)} · ${escapeHtml(hostile.area)}</p><a href="/station/${encodeURIComponent(hostile.id)}">View</a>`;
  assert.equal(popup.includes("<script>"), false);
  assert.equal(popup.includes(escapeHtml(hostile.name)), true);
  assert.equal(popup.includes(encodeURIComponent(hostile.id)), true);
});

test("live: fetchStations against public anon client when credentials are present", async (t) => {
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
    t.skip("Supabase public credentials not available in this environment");
    return;
  }
  const stations = await fetchStations();
  assert.ok(Array.isArray(stations));
  const visible = filterAndSortStations(stations);
  assert.equal(visible.length, stations.length);
  for (const s of stations) {
    assert.ok(typeof s.id === "string" && s.id.length > 0);
    assert.equal(visible.some((f) => f.id === s.id), true);
  }
  const mapped = mappableStations(visible);
  for (const m of mapped) {
    assert.equal(visible.some((s) => s.id === m.id), true);
    assert.equal(isValidCoordinate(m.lat, m.lng), true);
  }
  const empty = await fetchStations(mockClient({ stations: [], connectors: [] }));
  assert.equal(exploreLoadState(false, null, empty.length), "empty");
  await assert.rejects(
    () => fetchStations(mockClient({ stationsError: { message: "forced" } })),
    /forced/
  );
});
