import test from "node:test";
import assert from "node:assert/strict";
import { mock } from "node:test";
import { resetRateLimits } from "../src/lib/rateLimit.ts";

// Database boundary mock: the status route never touches a real pool.
let dbBehavior = () => {
  throw new Error("dbBehavior not set");
};
mock.module("@/db", {
  namedExports: {
    pool: {
      query: (sql, params) => dbBehavior(sql, params),
    },
  },
});

const { GET } = await import("../src/app/api/ml/status/route.ts");

function req(ip = "10.8.0.1") {
  return new Request("http://test/api/ml/status", {
    headers: { "x-forwarded-for": ip },
  });
}

function healthyDb({ total = 600, stations = 6, days = 40, withModel = true } = {}) {
  dbBehavior = (sql) => {
    if (sql.includes("FROM public.station_observations")) {
      return { rows: [{ total, stations, days, latest: new Date() }] };
    }
    // NOTE: the metrics query embeds a model_versions subquery, so it must
    // be matched before the model_versions branch.
    if (sql.includes("FROM ml.metrics")) {
      return {
        rows: [
          { metric_name: "mae", metric_value: "0.20" },
          { metric_name: "baseline_mae", metric_value: "0.30" },
        ],
      };
    }
    if (sql.includes("FROM ml.model_versions")) {
      return withModel
        ? { rows: [{ version_str: "v3", trained_at: new Date(), status: "ready" }] }
        : { rows: [] };
    }
    throw new Error(`unexpected query: ${String(sql).slice(0, 60)}`);
  };
}

function fresh() {
  resetRateLimits();
  dbBehavior = () => {
    throw new Error("dbBehavior not set");
  };
}

test("ready store reports inference available with model details", async () => {
  fresh();
  healthyDb();
  const res = await GET(req());
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.inference_available, true);
  assert.equal(body.state, "READY");
  assert.equal(body.reason, null);
  assert.equal(body.active_model.model_version, "v3");
  assert.equal(body.active_model.model_beats_baseline, true);
});

test("empty store reports cold with typed reason, not a model", async () => {
  fresh();
  healthyDb({ total: 0, stations: 0, days: 0, withModel: false });
  // latest:null + zero observations -> no_observations path; days check also fails.
  dbBehavior = ((prev) => (sql) => {
    if (sql.includes("FROM public.station_observations")) {
      return { rows: [{ total: 0, stations: 0, days: 0, latest: null }] };
    }
    return prev(sql);
  })(dbBehavior);
  const res = await GET(req());
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.inference_available, false);
  assert.equal(body.state, "COLD");
  assert.equal(body.reason, "DATA_MATURITY_COLD");
  assert.equal(body.active_model, null);
});

test("unreachable store fails closed with an honest error marker", async () => {
  fresh();
  dbBehavior = () => {
    throw new Error("connect ECONNREFUSED 127.0.0.1:5432");
  };
  const res = await GET(req());
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.inference_available, false);
  assert.ok(body.store_error);
  assert.ok(!JSON.stringify(body).includes("ECONNREFUSED"));
});

test("rate limit returns 429 after the configured budget, per client", async () => {
  fresh();
  healthyDb();
  const ip = "10.8.2.9";
  for (let i = 0; i < 300; i++) {
    const res = await GET(req(ip));
    assert.equal(res.status, 200, `request ${i} must succeed`);
  }
  const limited = await GET(req(ip));
  assert.equal(limited.status, 429);
  assert.equal((await limited.json()).throttled, true);
  // Another client is unaffected.
  assert.equal((await GET(req("10.8.2.10"))).status, 200);
});
