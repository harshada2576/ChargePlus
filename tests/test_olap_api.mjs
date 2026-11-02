import test from "node:test";
import assert from "node:assert/strict";

const { GET } = await import("../src/app/api/intelligence/olap/route.ts");

function createReq(url) {
  return new Request(url, {
    headers: { "x-forwarded-for": "10.0.0.1" },
  });
}

test("GET /api/intelligence/olap?op=rollup returns 200 with weekly rollup", async () => {
  const req = createReq("http://localhost/api/intelligence/olap?op=rollup&mode=weekly");
  const res = await GET(req);
  assert.equal(res.status, 200);
  const json = await res.json();
  assert.equal(json.ok, true);
  assert.equal(json.result.operation, "rollup");
  assert.ok(json.result.rows.length >= 5);
});

test("GET /api/intelligence/olap?op=drilldown returns 200 with localities", async () => {
  const req = createReq("http://localhost/api/intelligence/olap?op=drilldown&city=Mumbai");
  const res = await GET(req);
  assert.equal(res.status, 200);
  const json = await res.json();
  assert.equal(json.ok, true);
  assert.equal(json.result.operation, "drilldown");
});

test("GET /api/intelligence/olap?op=slice returns 200 with operator slice", async () => {
  const req = createReq("http://localhost/api/intelligence/olap?op=slice&operator=Tata%20Power");
  const res = await GET(req);
  assert.equal(res.status, 200);
  const json = await res.json();
  assert.equal(json.ok, true);
  assert.equal(json.result.operation, "slice");
});

test("GET /api/intelligence/olap?op=invalid returns 400 bad request", async () => {
  const req = createReq("http://localhost/api/intelligence/olap?op=nonexistent");
  const res = await GET(req);
  assert.equal(res.status, 400);
  const json = await res.json();
  assert.equal(json.ok, false);
});

