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
  refreshStationsSource,
  createMapLoadWatchdog,
  getStationPointLayerFilter,
  recommendStations,
  resolveSelectedStation,
  visibleSelection,
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

function recStation(id, lat, lng, { status = "unknown", connectors = null, price = null } = {}) {
  const s = baseStation({ id, name: `Station ${id}`, latitude: lat, longitude: lng });
  s.status = status;
  s.connectors =
    connectors ??
    [{ id: `${id}-c1`, type: "CCS2", powerKw: 60, total: 1, available: null }];
  s.pricePerKwh = price;
  return s;
}

test("13. Valid coordinates generate station GeoJSON features with [lng, lat]", () => {
  const stations = [
    recStation("g1", 19.076, 72.877),
    recStation("g2", 19.1, 72.9),
  ];
  const geo = toStationGeoJSON(stations);
  assert.equal(geo.type, "FeatureCollection");
  assert.equal(geo.features.length, 2);
  assert.deepEqual(geo.features[0].geometry.coordinates, [72.877, 19.076]);
  assert.equal(geo.features[0].properties.id, "g1");
  assert.equal(geo.features[1].properties.id, "g2");
});

test("14. Invalid coordinates are excluded without fabrication, including (0, 0)", () => {
  const stations = [
    recStation("ok", 19.076, 72.877),
    recStation("null-island", 0, 0),
    recStation("nan", NaN, 72.877),
    recStation("missing", null, undefined),
    recStation("out-of-range", 91, 200),
  ];
  const geo = toStationGeoJSON(stations);
  assert.equal(geo.features.length, 1);
  assert.equal(geo.features[0].properties.id, "ok");
  for (const f of geo.features) {
    assert.deepEqual(f.geometry.coordinates[0] === 0 && f.geometry.coordinates[1] === 0, false);
  }
});

test("15. Late station data updates an existing map source; missing source is a safe no-op", () => {
  const seen = [];
  const fakeMap = {
    getSource: (id) => {
      assert.equal(id, "stations");
      return { setData: (data) => seen.push(data) };
    },
  };
  const stations = [recStation("late", 19.076, 72.877)];
  assert.equal(refreshStationsSource(fakeMap, stations), true);
  assert.equal(seen.length, 1);
  assert.equal(seen[0].features.length, 1);
  assert.equal(seen[0].features[0].properties.id, "late");

  // Source not yet created (style still loading): no throw, caller retries later.
  assert.equal(refreshStationsSource({ getSource: () => undefined }, stations), false);
});

test("16. Recommendations are produced when every station has unknown availability", () => {
  const stations = [
    recStation("r1", 19.076, 72.877),
    recStation("r2", 19.08, 72.88),
    recStation("r3", 19.09, 72.89),
  ];
  const recs = recommendStations(stations);
  assert.ok(recs.length >= 1 && recs.length <= 3);
  for (const r of recs) {
    assert.ok(stations.some((s) => s.id === r.stationId)); // genuine records only
    assert.ok(!r.reasons.includes("availableNow")); // unknown is never "available now"
    assert.ok(!r.reasons.includes("lessBusyNow")); // unknown busy windows never qualify
    assert.ok(r.reasons.includes("availabilityUnknown"));
    assert.equal(r.availableCount, undefined);
  }
});

test("17. Recommendation reasons use only evidence-backed labels", () => {
  const full = recStation("full", 19.076, 72.877, { price: 18.5 });
  const recs = recommendStations([full], { connectorTypes: ["CCS2"] });
  assert.equal(recs.length, 1);
  const reasons = recs[0].reasons;
  assert.ok(reasons.includes("matchConnector")); // required connector known and matched
  assert.ok(reasons.includes("knownPower")); // verified 60 kW connector
  assert.ok(reasons.includes("priceAvailable")); // verified tariff present
  assert.ok(reasons.includes("availabilityUnknown"));

  // Connector filter that matches nothing known yields no matchConnector reason.
  const noMatch = recommendStations([full], { connectorTypes: ["CHAdeMO"] });
  assert.ok(!noMatch[0].reasons.includes("matchConnector"));

  // Nearby only with user location in range.
  const near = recommendStations([full], { userLoc: { lat: 19.077, lng: 72.878 } });
  assert.ok(near[0].reasons.includes("nearby"));
  const far = recommendStations([full], {});
  assert.ok(!far[0].reasons.includes("nearby"));
});

test("18. Genuine live availability keeps an honest availableNow reason", () => {
  const live = mapDbStationToStation({
    id: "live-avail",
    name: "Live Station",
    latitude: 19.076,
    longitude: 72.877,
    operational_status: "operational",
    latest_availability_status: "available",
    min_price_per_kwh: null,
    avg_rating: null,
    review_count: 0,
  }, [
    {
      id: "c1",
      station_id: "live-avail",
      connector_type: "CCS2",
      power_kw: 60,
      total_quantity: 2,
      latest_available_connectors: 1,
      latest_availability_status: "available",
    },
  ]);
  assert.equal(live.status, "available");
  const recs = recommendStations([live]);
  assert.equal(recs.length, 1);
  assert.ok(recs[0].reasons.includes("availableNow"));
  assert.equal(recs[0].availableCount, 1);
});

test("19. Search/filter scoping, eligibility, and count limits constrain recommendations", () => {
  const eligible = [
    recStation("e1", 19.076, 72.877),
    recStation("e2", 19.077, 72.878),
    recStation("e3", 19.078, 72.879),
    recStation("e4", 19.079, 72.88),
    recStation("e5", 19.08, 72.881),
  ];
  const recs = recommendStations(eligible);
  assert.equal(recs.length, 3); // capped at 3 even with 5 eligible

  // Ineligible: broken status, invalid coords, no usable connector info.
  const broken = recStation("broken", 19.076, 72.877);
  broken.status = "broken";
  const noCoords = recStation("nocoords", NaN, NaN);
  const noInfo = recStation("noinfo", 19.076, 72.877, { connectors: [] });
  const unknownOnly = recStation("unknownonly", 19.076, 72.877, {
    connectors: [{ id: "u1", type: "Unknown", powerKw: null, total: null, available: null }],
  });
  assert.deepEqual(recommendStations([broken, noCoords, noInfo, unknownOnly]), []);
  assert.deepEqual(recommendStations([]), []);
});

test("20. Recommended-station selection stays synchronized with list, preview, and map", () => {
  const stations = [
    recStation("s1", 19.076, 72.877),
    recStation("s2", 19.08, 72.88),
  ];
  const filtered = filterAndSortStations(stations, { filters: DEFAULT_EXPLORE_FILTERS });
  const recs = recommendStations(filtered);
  assert.ok(recs.length > 0);
  for (const r of recs) {
    // Every recommendation resolves through the same visible-selection path
    // the list, preview sheet, and map popup share.
    assert.equal(r.stationId && filtered.some((s) => s.id === r.stationId), true);
    assert.equal(visibleSelection(r.stationId, filtered), r.stationId);
    assert.equal(resolveSelectedStation(r.stationId, filtered, stations)?.id, r.stationId);
    assert.ok(
      toStationGeoJSON(filtered).features.some((f) => f.properties.id === r.stationId)
    ); // pin exists for the recommendation
  }
});

test("21. Silent style stall fires the watchdog timeout once", async () => {
  let calls = 0;
  const watchdog = createMapLoadWatchdog(() => {
    calls += 1;
  }, 20);
  await new Promise((resolve) => setTimeout(resolve, 60));
  assert.equal(calls, 1); // hanging style/tile request becomes actionable
  watchdog.resolve(); // late resolve after firing never refires
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.equal(calls, 1);
});

test("22. Style readiness disarms the watchdog before the timeout", async () => {
  let calls = 0;
  const watchdog = createMapLoadWatchdog(() => {
    calls += 1;
  }, 20);
  watchdog.resolve(); // style.load / load / unmount path
  await new Promise((resolve) => setTimeout(resolve, 60));
  assert.equal(calls, 0); // no false error overlay on a healthy map
});

test("MapLibre single-station regression: filter property is completely omitted when singleStation is true", () => {
  // When multiple stations are mapped, unclustered points filter out clustered aggregates
  const multiStationFilter = getStationPointLayerFilter(false);
  assert.deepEqual(multiStationFilter, { filter: ["!", ["has", "point_count"]] });

  // When singleStation is true (e.g. StationDetail page where cluster: false),
  // passing filter: undefined causes MapLibre GL style validation to error.
  // The filter property MUST be completely omitted.
  const singleStationFilter = getStationPointLayerFilter(true);
  assert.equal("filter" in singleStationFilter, false, "filter key must not exist on single-station layer spec");
  assert.deepEqual(singleStationFilter, {});

  // Confirm single-station GeoJSON conversion preserves single-station attributes
  const single = baseStation({ id: "solo-1", name: "Solo Station", latitude: 18.5204, longitude: 73.8567 });
  const geo = toStationGeoJSON([single]);
  assert.equal(geo.type, "FeatureCollection");
  assert.equal(geo.features.length, 1);
  assert.equal(geo.features[0].id, "solo-1");
  assert.deepEqual(geo.features[0].geometry.coordinates, [73.8567, 18.5204]);
});

test("live: fetchStations against public anon client when credentials are present", async (t) => {
  if (
    process.env.CHARGEPLUS_LIVE_TESTS !== "1" ||
    !process.env.NEXT_PUBLIC_SUPABASE_URL ||
    !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  ) {
    t.skip("Live Supabase tests require explicit CHARGEPLUS_LIVE_TESTS=1 opt-in");
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
