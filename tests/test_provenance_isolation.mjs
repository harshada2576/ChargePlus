import test from "node:test";
import assert from "node:assert/strict";
import {
  deriveSourceCategory,
  deriveFreshnessState,
  mapDbStationToStation,
  mapDbConnectorToConnector,
} from "../src/data/stationAdapter.ts";
import { fetchStations } from "../src/data/stations.ts";
import { stationPriceDisplay, connectorPriceDisplay } from "../src/lib/priceDisplay.ts";

const t = (k, vars) => {
  if (k === "station.perKwh") return `₹${vars?.price}/kWh`;
  if (k === "station.priceUnavailable") return "Price unavailable";
  if (k === "station.estimateAvailable") return "Estimate available";
  return k;
};

test("provenance: 1. deriveSourceCategory partitions simulated provenance correctly", () => {
  // Simulated flag takes strict priority
  assert.equal(
    deriveSourceCategory({
      isSimulated: true,
      hasObservation: true,
      freshness: "fresh",
      sourceName: "verified_live_feed",
    }),
    "simulated"
  );

  // When not simulated and fresh with observation
  assert.equal(
    deriveSourceCategory({
      isSimulated: false,
      hasObservation: true,
      freshness: "fresh",
      sourceName: "ocpi_live",
    }),
    "verified_live"
  );

  // Stale non-simulated observation becomes historical
  assert.equal(
    deriveSourceCategory({
      isSimulated: false,
      hasObservation: true,
      freshness: "stale",
      sourceName: "ocpi_live",
    }),
    "historical"
  );
});

test("provenance: 2. genuine station with simulated observation preserves station.isSimulated = false", () => {
  const stationRow = {
    id: "st-genuine-1",
    name: "Tata Power Live Station",
    operator_name: "Tata Power",
    is_simulated: false,
    observation_is_simulated: true,
    latest_availability_status: "available",
    latest_observation_id: "obs-sim-99",
    minutes_since_observation: 5,
    latitude: 19.07,
    longitude: 72.87,
  };

  const station = mapDbStationToStation(stationRow, []);
  assert.equal(station.isSimulated, false, "genuine station must remain isSimulated: false");
  assert.equal(station.sourceCategory, "simulated", "simulated observation forces sourceCategory to simulated");
});

test("provenance: 3. simulated station preserves isSimulated: true and sourceCategory: simulated", () => {
  const stationRow = {
    id: "st-sim-1",
    name: "Demo Station 42",
    operator_name: "Demo Operator",
    is_simulated: true,
    observation_is_simulated: true,
    latest_availability_status: "available",
    latest_observation_id: "obs-sim-42",
    minutes_since_observation: 2,
    latitude: 19.12,
    longitude: 72.85,
  };

  const station = mapDbStationToStation(stationRow, []);
  assert.equal(station.isSimulated, true, "simulated station must have isSimulated: true");
  assert.equal(station.sourceCategory, "simulated");
});

test("provenance: 4. connector mapping propagates is_simulated and observation_is_simulated", () => {
  const connRow = {
    id: "conn-sim-1",
    station_id: "st-1",
    connector_type: "CCS2",
    power_kw: 60,
    total_quantity: 2,
    is_simulated: true,
    observation_is_simulated: true,
    latest_availability_status: "available",
    latest_available_connectors: 2,
    minutes_since_observation: 10,
  };

  const conn = mapDbConnectorToConnector(connRow);
  assert.equal(conn.isSimulated, true);
  assert.equal(conn.sourceCategory, "simulated");
});

test("provenance: 5. station connector stub fallback when connectors array is not loaded", () => {
  const stationRow = {
    id: "st-stub-test",
    name: "Stub Fallback Station",
    operator_name: "Jio-bp",
    is_simulated: true,
    total_connector_types: 2,
    total_plugs: 4,
    max_power_kw: 120,
    connector_types: ["CCS2", "CHAdeMO"],
    latitude: 19.05,
    longitude: 72.83,
  };

  const station = mapDbStationToStation(stationRow, []);
  assert.equal(station.connectors.length, 2);
  assert.equal(station.connectors[0].type, "CCS2");
  assert.equal(station.connectors[0].powerKw, 120);
  assert.equal(station.connectors[0].total, 4);
  assert.equal(station.connectors[0].available, null, "unobserved stub availability must remain null");
  assert.equal(station.connectors[0].isSimulated, true);
  assert.equal(station.connectors[1].type, "CHAdeMO");
});

test("provenance: 6. fetchStations with pagination loads all pages across PostgREST 1000 limit", async () => {
  // Mock client that returns 1000 items on page 0 and 500 items on page 1000
  let rangeCalled = false;
  const mockPagingClient = {
    from(table) {
      return {
        select() {
          const firstPage = Array.from({ length: 1000 }, (_, i) => ({
            id: `st-${i}`,
            name: `Station ${i}`,
            latitude: 19.0,
            longitude: 72.8,
            is_simulated: true,
            connector_types: ["CCS2"],
          }));
          return Object.assign(Promise.resolve({ data: firstPage, error: null }), {
            range(from, to) {
              rangeCalled = true;
              if (from === 1000) {
                const secondPage = Array.from({ length: 500 }, (_, i) => ({
                  id: `st-${1000 + i}`,
                  name: `Station ${1000 + i}`,
                  latitude: 19.0,
                  longitude: 72.8,
                  is_simulated: true,
                  connector_types: ["Type 2"],
                }));
                return Promise.resolve({ data: secondPage, error: null });
              }
              return Promise.resolve({ data: [], error: null });
            },
          });
        },
      };
    },
  };

  const result = await fetchStations(mockPagingClient);
  assert.equal(result.length, 1500, "all 1500 stations across 2 pages must be fetched");
  assert.equal(rangeCalled, true, ".range pagination must be invoked for datasets >= 1000");
  assert.equal(result[0].connectors[0].type, "CCS2");
  assert.equal(result[1000].connectors[0].type, "Type 2");
});
