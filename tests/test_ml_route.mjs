import test from "node:test";
import assert from "node:assert/strict";
import { mock } from "node:test";
import { resetRateLimits } from "../src/lib/rateLimit.ts";

// Subprocess boundary mock: no real Python is ever spawned. Behavior is
// driven per test via `cliBehavior`; all invocations are recorded in `calls`.
const calls = [];
let cliBehavior = (bin, args, opts, cb) => cb(new Error("cliBehavior not set"));
mock.module("node:child_process", {
  namedExports: {
    execFile: (bin, args, opts, cb) => {
      calls.push({ bin, args });
      cliBehavior(bin, args, opts, cb);
    },
  },
});

const { POST } = await import("../src/app/api/ml/predict/route.ts");

const FEATURES = { hour_of_day: 18, day_of_week: 4, is_weekend: 0, month: 10 };

function req(body, ip = "10.9.0.1") {
  return new Request("http://test/api/ml/predict", {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": ip },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function okCli(payload) {
  cliBehavior = (bin, args, opts, cb) => cb(null, { stdout: JSON.stringify(payload) });
}

function fresh() {
  resetRateLimits();
  calls.length = 0;
  cliBehavior = (bin, args, opts, cb) => cb(new Error("cliBehavior not set"));
}

test("valid prediction returns the established success response", async () => {
  fresh();
  okCli({ success: true, probability: 0.42, model_version: "v3", horizon: "current" });
  const res = await POST(req({ features: FEATURES }));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.success, true);
  assert.equal(body.probability, 0.42);
  assert.equal(body.model_version, "v3");
  assert.equal(calls.length, 1);
  assert.ok(calls[0].args.includes("backend.ml.cli"));
});

test("out-of-range probability is refused with 502 typed error", async () => {
  fresh();
  okCli({ success: true, probability: 1.5, model_version: "v3" });
  const res = await POST(req({ features: FEATURES }));
  assert.equal(res.status, 502);
  const body = await res.json();
  assert.equal(body.success, false);
  assert.equal(body.reason, "MODEL_ARTIFACT_INVALID");
});

test("non-finite, missing and malformed inference output is rejected safely", async () => {
  const badPayloads = [
    { success: true, probability: null, model_version: "v3" },
    { success: true, probability: "0.5", model_version: "v3" },
    { success: true, probability: -0.2, model_version: "v3" },
    { success: true, probability: 0.5 },
    { success: true, probability: 0.5, model_version: "" },
  ];
  for (const [i, payload] of badPayloads.entries()) {
    fresh();
    okCli(payload);
    const res = await POST(req({ features: FEATURES }, `10.9.1.${i + 1}`));
    assert.equal(res.status, 502, `payload ${i} must yield 502`);
    assert.equal((await res.json()).reason, "MODEL_ARTIFACT_INVALID");
  }

  // Malformed JSON stdout and non-boolean envelopes surface as unavailable,
  // never as a prediction.
  fresh();
  cliBehavior = (bin, args, opts, cb) => cb(null, { stdout: "not-json{{{" });
  const res = await POST(req({ features: FEATURES }));
  assert.equal(res.status, 503);
  assert.equal((await res.json()).reason, "NO_MODEL");

  fresh();
  okCli({ success: "yes", probability: 0.5, model_version: "v3" });
  const nonBoolean = await POST(req({ features: FEATURES }));
  assert.equal(nonBoolean.status, 503);
  assert.equal((await nonBoolean.json()).reason, "NO_MODEL");
});

test("subprocess failure yields 503 without leaking unbounded internals", async () => {
  fresh();
  const secret = `INTERNAL-DB-SECRET-${"x".repeat(500)}`;
  cliBehavior = (bin, args, opts, cb) => cb(new Error(`connect failed: ${secret}`));
  const res = await POST(req({ features: FEATURES }));
  assert.equal(res.status, 503);
  const body = await res.json();
  assert.equal(body.success, false);
  assert.equal(body.reason, "NO_MODEL");
  assert.ok(body.message.includes("no prediction available"));
  assert.ok(!body.message.includes(secret));

  // Timeout maps to the explicit timeout message.
  fresh();
  cliBehavior = (bin, args, opts, cb) =>
    cb(Object.assign(new Error("timeout of 20000ms exceeded"), { killed: true }));
  const timeoutRes = await POST(req({ features: FEATURES }));
  assert.equal(timeoutRes.status, 503);
  assert.equal((await timeoutRes.json()).message, "Inference timed out; no prediction available.");
});

test("invalid request bodies are rejected before spawning inference", async () => {
  fresh();
  okCli({ success: true, probability: 0.5, model_version: "v3" });
  const res = await POST(req({ features: { hour_of_day: 99, day_of_week: 1, is_weekend: 0, month: 1 } }));
  assert.equal(res.status, 400);
  assert.equal(calls.length, 0);

  const badJson = new Request("http://test/api/ml/predict", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{{{",
  });
  assert.equal((await POST(badJson)).status, 400);
  assert.equal(calls.length, 0);
});

test("oversized bodies are refused before spawning inference", async () => {
  fresh();
  okCli({ success: true, probability: 0.5, model_version: "v3" });
  const big = await POST(
    new Request("http://test/api/ml/predict", {
      method: "POST",
      headers: { "content-type": "application/json", "x-forwarded-for": "10.9.4.1" },
      body: JSON.stringify({ features: FEATURES, pad: "x".repeat(70_000) }),
    })
  );
  assert.equal(big.status, 413);
  assert.equal(calls.length, 0);
});

test("rate limit returns 429 after the configured budget is exceeded", async () => {
  fresh();
  okCli({ success: true, probability: 0.1, model_version: "v3" });
  const ip = "10.9.2.7";
  for (let i = 0; i < 60; i++) {
    const res = await POST(req({ features: FEATURES }, ip));
    assert.equal(res.status, 200, `request ${i} must succeed`);
  }
  const limited = await POST(req({ features: FEATURES }, ip));
  assert.equal(limited.status, 429);
  const body = await limited.json();
  assert.equal(body.success, false);
  assert.ok(body.message.includes("Too many requests"));
});

test("rate-limit keys distinguish clients by trusted identification", async () => {
  fresh();
  okCli({ success: true, probability: 0.1, model_version: "v3" });
  // Exhaust client A via multi-value forwarded header (first IP wins).
  for (let i = 0; i < 60; i++) {
    await POST(req({ features: FEATURES }, "10.9.3.1, 10.9.3.99"));
  }
  assert.equal((await POST(req({ features: FEATURES }, "10.9.3.1"))).status, 429);
  // Client B on a different IP is unaffected.
  assert.equal((await POST(req({ features: FEATURES }, "10.9.3.2"))).status, 200);
});
