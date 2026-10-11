import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fetchWarehouseSummary } from "../src/lib/warehouse.ts";

const SUMMARY = {
  stationsCurrent: 16,
  stationVersions: 17,
  connectors: 6,
  connectorsUnknownPower: 3,
  operators: 3,
  sources: 1,
  observations: 0,
  reports: 0,
  reviews: 0,
  dailyRows: 0,
  observedStations: 0,
  latestObservedAt: null,
  maturity: { cold: 0, warming: 0, ready: 0 },
};

function mockClient(token = "tok") {
  return { auth: { getSession: async () => ({ data: { session: token ? { access_token: token } : null } }) } };
}

function mockFetch(body, ok = true, status = 200) {
  return async () => ({ ok, status, json: async () => body });
}

test("ready state maps counts and preserves null latest observation", async () => {
  const out = await fetchWarehouseSummary(mockClient(), mockFetch(SUMMARY));
  assert.equal(out.stationsCurrent, 16);
  assert.equal(out.connectorsUnknownPower, 3);
  assert.equal(out.latestObservedAt, null);
  assert.deepEqual(out.maturity, { cold: 0, warming: 0, ready: 0 });
});

test("non-numeric payloads coerce to honest zeros, null stays null", async () => {
  const out = await fetchWarehouseSummary(
    mockClient(),
    mockFetch({ ...SUMMARY, observations: "many", latestObservedAt: 123 })
  );
  assert.equal(out.observations, 0);
  assert.equal(out.latestObservedAt, null);
});

test("missing session and auth failures never fake a summary", async () => {
  await assert.rejects(fetchWarehouseSummary(mockClient(null), mockFetch(SUMMARY)), /signed-in/);
  await assert.rejects(
    fetchWarehouseSummary(mockClient(), mockFetch({ error: "x" }, false, 401)),
    /signed-in/
  );
  await assert.rejects(
    fetchWarehouseSummary(mockClient(), mockFetch({ error: "x" }, false, 403)),
    /Restricted/
  );
  await assert.rejects(
    fetchWarehouseSummary(mockClient(), async () => { throw new Error("down"); }),
    /failed to load/
  );
});

test("admin warehouse route exposes no PII columns and authorizes server-side", () => {
  const src = readFileSync("src/app/api/admin/warehouse/route.ts", "utf8");
  // The caller's own session token is accepted for validation only: it is
  // never logged, never returned, and never embedded in SQL.
  for (const col of ["user_id", "comment", "moderated_by", "password", "secret"]) {
    assert.ok(!src.toLowerCase().includes(col), `route must not reference ${col}`);
  }
  assert.ok(!src.includes("console.log"), "route must not log auth material");
  assert.ok(src.includes("SUPABASE_SERVICE_ROLE_KEY"), "service key must stay server-side");
  assert.ok(src.includes("profiles"), "role must come from canonical profiles");
  assert.ok(src.includes("status: 401"), "missing/invalid session denied");
  assert.ok(src.includes("status: 403"), "non-admin denied");
  assert.ok(!src.includes("NEXT_PUBLIC_SUPABASE_ANON_KEY"), "no anon key escalation path");
});
