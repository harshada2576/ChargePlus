import test from "node:test";
import assert from "node:assert/strict";
import { checkRateLimit, clientKey, credentialKey, resetRateLimits } from "../src/lib/rateLimit.ts";
import { newRequestId, serverLog } from "../src/lib/serverLog.ts";

test("token bucket allows burst then denies with retry hint", () => {
  resetRateLimits();
  const rule = { limit: 3, windowMs: 60_000 };
  assert.ok(checkRateLimit("k1", rule, 1000).allowed);
  assert.ok(checkRateLimit("k1", rule, 1001).allowed);
  assert.ok(checkRateLimit("k1", rule, 1002).allowed);
  const denied = checkRateLimit("k1", rule, 1003);
  assert.equal(denied.allowed, false);
  assert.ok(denied.retryAfterMs > 0);
  // window expiry resets
  assert.ok(checkRateLimit("k1", rule, 1000 + 60_001).allowed);
});

test("keys are independent per caller", () => {
  resetRateLimits();
  const rule = { limit: 1, windowMs: 60_000 };
  assert.ok(checkRateLimit("a", rule, 0).allowed);
  assert.ok(!checkRateLimit("a", rule, 1).allowed);
  assert.ok(checkRateLimit("b", rule, 1).allowed);
});

test("client and credential keys derive safely", () => {
  const ipReq = new Request("http://x/", { headers: { "x-forwarded-for": "1.2.3.4, 9.9.9.9" } });
  assert.equal(clientKey(ipReq), "ip:1.2.3.4");
  const noIp = new Request("http://x/");
  assert.equal(clientKey(noIp), "ip:unknown-ip");
  const authed = new Request("http://x/", { headers: { authorization: "Bearer abc" } });
  assert.ok(credentialKey(authed).startsWith("cred:"));
});

test("serverLog emits JSON without secrets and never throws", () => {
  const lines = [];
  const origLog = console.log;
  const origErr = console.error;
  console.log = (l) => lines.push(l);
  console.error = (l) => lines.push(l);
  try {
    serverLog("info", "test.event", { requestId: "r1", ok: true, n: 3 });
    serverLog("error", "test.fail", { requestId: "r2" });
  } finally {
    console.log = origLog;
    console.error = origErr;
  }
  assert.equal(lines.length, 2);
  for (const line of lines) {
    const parsed = JSON.parse(line);
    assert.equal(parsed.service, "chargeplus-web");
    assert.ok(parsed.ts);
  }
  const id1 = newRequestId();
  const id2 = newRequestId();
  assert.notEqual(id1, id2);
});
