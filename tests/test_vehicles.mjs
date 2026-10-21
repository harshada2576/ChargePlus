import test from "node:test";
import assert from "node:assert/strict";
import {
  CURATED_INDIAN_VEHICLES,
  checkVehicleCompatibility,
  estimateChargingTime,
} from "../src/data/vehicles.ts";

test("CURATED_INDIAN_VEHICLES contains verified real-world Indian EV models", () => {
  assert.ok(CURATED_INDIAN_VEHICLES.length >= 5);
  const nexon = CURATED_INDIAN_VEHICLES.find((v) => v.id === "tata-nexon-ev-lr");
  assert.ok(nexon);
  assert.equal(nexon.brand, "Tata");
  assert.equal(nexon.usableBatteryKwh, 40.5);
  assert.deepEqual(nexon.compatibleConnectors, ["CCS2", "Type 2"]);
});

test("checkVehicleCompatibility matches compatible connector types accurately", () => {
  const nexon = CURATED_INDIAN_VEHICLES.find((v) => v.id === "tata-nexon-ev-lr");
  const stationConnectors = [
    { type: "CCS2", powerKw: 60 },
    { type: "CHAdeMO", powerKw: 50 },
  ];

  const result = checkVehicleCompatibility(nexon, stationConnectors);
  assert.equal(result.isCompatible, true);
  assert.deepEqual(result.compatibleConnectors, ["CCS2"]);
});

test("checkVehicleCompatibility reports honest failure when no connector matches", () => {
  const ather = CURATED_INDIAN_VEHICLES.find((v) => v.id === "ather-450x-gen3");
  const dcFastOnlyStation = [{ type: "CCS2", powerKw: 120 }];

  const result = checkVehicleCompatibility(ather, dcFastOnlyStation);
  assert.equal(result.isCompatible, false);
  assert.match(result.incompatibleReason, /Station lacks compatible plugs/);
});

test("estimateChargingTime accurately caps charging power at vehicle maximum", () => {
  const nexon = CURATED_INDIAN_VEHICLES.find((v) => v.id === "tata-nexon-ev-lr"); // max DC 50kW
  // 120kW fast charger connected to 50kW vehicle limit:
  const estimate = estimateChargingTime({
    vehicle: nexon,
    chargerType: "CCS2",
    chargerPowerKw: 120,
    startSocPct: 20,
    targetSocPct: 80,
  });

  assert.ok(estimate);
  // effectivePower should cap at 50kW (vehicle limit)
  assert.equal(estimate.effectivePowerKw, 50);
  assert.equal(estimate.limitingFactor, "vehicle");
  assert.equal(estimate.energyNeededKwh, 24.3); // 40.5 * 0.60
  assert.ok(estimate.estimatedMinutes > 0);
  assert.ok(estimate.disclaimer.length > 20);
});

test("estimateChargingTime returns null when charger power is missing or invalid", () => {
  const nexon = CURATED_INDIAN_VEHICLES.find((v) => v.id === "tata-nexon-ev-lr");
  assert.equal(
    estimateChargingTime({ vehicle: nexon, chargerType: "CCS2", chargerPowerKw: null }),
    null
  );
  assert.equal(
    estimateChargingTime({ vehicle: nexon, chargerType: "CCS2", chargerPowerKw: 0 }),
    null
  );
});
