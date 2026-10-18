import test from "node:test";
import assert from "node:assert/strict";
import { validatePredictInput, validatePredictResult } from "../src/lib/ml.ts";

test("validatePredictInput accepts a complete valid feature vector", () => {
  const res = validatePredictInput({
    features: { hour_of_day: 18, day_of_week: 4, is_weekend: 0, month: 10, station_connector_count: 4 },
    latest_observation_at: "2026-10-11T12:00:00+00:00",
  });
  assert.equal(res.ok, true);
  assert.equal(res.features.hour_of_day, 18);
  assert.ok(res.latestObservationAt.endsWith("Z") || res.latestObservationAt.includes("+00:00"));
});

test("validatePredictInput rejects out-of-range and non-numeric features", () => {
  for (const features of [
    { hour_of_day: 24, day_of_week: 4, is_weekend: 0, month: 10 },
    { hour_of_day: 18, day_of_week: 7, is_weekend: 0, month: 10 },
    { hour_of_day: 18, day_of_week: 4, is_weekend: 2, month: 10 },
    { hour_of_day: 18, day_of_week: 4, is_weekend: 0, month: 13 },
    { hour_of_day: NaN, day_of_week: 4, is_weekend: 0, month: 10 },
    { hour_of_day: 18, day_of_week: 4, is_weekend: 0, month: 10, station_connector_count: -1 },
    { hour_of_day: "18", day_of_week: 4, is_weekend: 0, month: 10 },
  ]) {
    const res = validatePredictInput({ features });
    assert.equal(res.ok, false);
    assert.equal(res.reason, "FEATURE_SCHEMA_MISMATCH");
  }
});

test("validatePredictInput rejects malformed bodies and timestamps", () => {
  assert.equal(validatePredictInput(null).ok, false);
  assert.equal(validatePredictInput({}).ok, false);
  assert.equal(validatePredictInput({ features: null }).ok, false);
  const badTs = validatePredictInput({
    features: { hour_of_day: 1, day_of_week: 1, is_weekend: 0, month: 1 },
    latest_observation_at: "not-a-date",
  });
  assert.equal(badTs.ok, false);
});

test("validatePredictResult accepts a well-formed prediction", () => {
  const res = validatePredictResult({ success: true, probability: 0.42, model_version: "v3" });
  assert.equal(res.ok, true);
  assert.equal(res.value.probability, 0.42);
  assert.equal(res.value.modelVersion, "v3");
});

test("validatePredictResult accepts boundary probabilities 0 and 1", () => {
  assert.equal(validatePredictResult({ success: true, probability: 0, model_version: "v1" }).ok, true);
  assert.equal(validatePredictResult({ success: true, probability: 1, model_version: "v1" }).ok, true);
});

test("validatePredictResult refuses non-finite and out-of-range probabilities", () => {
  for (const probability of [-0.5, 1.5, 2, NaN, Infinity, -Infinity, "0.5", null, undefined, true]) {
    const res = validatePredictResult({ success: true, probability, model_version: "v3" });
    assert.equal(res.ok, false, `probability ${String(probability)} must be refused`);
    assert.equal(res.reason, "MODEL_ARTIFACT_INVALID");
  }
});

test("validatePredictResult refuses missing model version and malformed payloads", () => {
  assert.equal(validatePredictResult({ success: true, probability: 0.5 }).ok, false);
  assert.equal(validatePredictResult({ success: true, probability: 0.5, model_version: "" }).ok, false);
  assert.equal(validatePredictResult(null).ok, false);
  assert.equal(validatePredictResult("ok").ok, false);
  assert.equal(validatePredictResult({ success: false, reason: "NO_MODEL" }).ok, false);
});
