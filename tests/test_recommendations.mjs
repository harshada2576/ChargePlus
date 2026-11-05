import test from "node:test";
import assert from "node:assert/strict";
import {
  RECOMMENDER_VERSION,
  RECOMMENDER_WEIGHTS,
  evaluateRecommendations,
  recommendStations,
} from "../src/data/exploreQuery.ts";

function st(id, lat, lng, opts = {}) {
  return {
    id,
    name: `Station ${id}`,
    operator: "Op",
    area: "Area",
    address: "Addr",
    lat,
    lng,
    status: opts.status ?? "unknown",
    minutesSinceUpdate: opts.minutesSinceUpdate ?? null,
    freshnessState: opts.freshnessState,
    connectors: opts.connectors ?? [
      { id: `${id}-c1`, type: "CCS2", powerKw: 60, total: 1, available: null },
    ],
    pricePerKwh: opts.price ?? null,
    isFree: opts.isFree ?? null,
    hours: { kind: "24h" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  };
}

const availConn = (id) => [
  { id: `${id}-c1`, type: "CCS2", powerKw: 60, total: 2, available: 1 },
];

test("verified available vs unknown/busy/broken/stale states", () => {
  const live = st("live", 19.076, 72.877, {
    status: "available",
    connectors: availConn("live"),
  });
  const unknownS = st("unk", 19.077, 72.878);
  const busy = st("busy", 19.078, 72.879, { status: "busy" });
  const broken = st("broken", 19.079, 72.88, { status: "broken" });
  const staleAvail = st("stale", 19.08, 72.881, {
    status: "available",
    freshnessState: "stale",
    minutesSinceUpdate: 180,
    connectors: availConn("stale"),
  });

  const recs = recommendStations([unknownS, busy, live]);
  const byId = new Map(recs.map((r) => [r.stationId, r]));
  assert.equal(recs.length, 3);
  assert.ok(byId.has("live"));
  assert.ok(byId.get("live").reasons.includes("availableNow"));
  assert.equal(byId.get("live").availableCount, 1);
  // Unknown is shown honestly, never as available.
  assert.ok(byId.get("unk").reasons.includes("availabilityUnknown"));
  assert.ok(!byId.get("unk").reasons.includes("availableNow"));
  // Busy is kept but rank-penalized: no availableNow, never availabilityUnknown.
  assert.ok(!byId.get("busy").reasons.includes("availableNow"));
  assert.ok(!byId.get("busy").reasons.includes("availabilityUnknown"));
  // Broken is a hard exclusion.
  assert.deepEqual(recommendStations([broken]), []);
  // Known-stale availability must not earn availableNow.
  const staleRecs = recommendStations([staleAvail, live]);
  const staleById = new Map(staleRecs.map((r) => [r.stationId, r]));
  assert.ok(staleById.has("stale"));
  assert.ok(!staleById.get("stale").reasons.includes("availableNow"));
  // Live availability outranks an otherwise identical busy station.
  const ranked = recommendStations([busy, live]);
  assert.equal(ranked[0].stationId, "live");
  // Internal record pins the exclusion cause.
  const evals = evaluateRecommendations([broken, staleAvail, live]);
  assert.deepEqual(
    evals.find((e) => e.stationId === "broken").exclusionReasons,
    ["broken-status"]
  );
  assert.equal(evals.find((e) => e.stationId === "stale").features.genuinelyAvailable, false);
  assert.equal(evals.find((e) => e.stationId === "live").features.genuinelyAvailable, true);
});

test("verified tariffs rank; unverified estimates never score or leak into reasons", () => {
  const verified = st("ver", 19.076, 72.877, { price: 18.5 });
  const estimateOnly = st("est", 19.076, 72.877, {
    connectors: [
      {
        id: "est-c1",
        type: "CCS2",
        powerKw: 60,
        total: 1,
        available: null,
        priceEstimatePerKwh: 12.5,
        priceEstimateRaw: "Rs. 12.5 per kWh",
      },
    ],
  });
  const recs = recommendStations([estimateOnly, verified]);
  const byId = new Map(recs.map((r) => [r.stationId, r]));
  assert.ok(byId.get("ver").reasons.includes("priceAvailable"));
  assert.ok(!byId.get("est").reasons.includes("priceAvailable"));
  // Verified (+1) outranks an otherwise identical estimate-only station.
  assert.ok(
    recs.findIndex((r) => r.stationId === "ver") <
      recs.findIndex((r) => r.stationId === "est")
  );
  const evals = evaluateRecommendations([estimateOnly, verified]);
  const estEval = evals.find((e) => e.stationId === "est");
  assert.equal(estEval.features.hasVerifiedPrice, false);
  assert.equal(estEval.features.hasUnverifiedEstimateOnly, true);
  assert.equal(estEval.contributions.verifiedPrice, 0);
  assert.equal(estEval.priceState, "unverified-estimate-only");
  assert.equal(evals.find((e) => e.stationId === "ver").priceState, "verified");
});

test("hard exclusions, invalid coords, missing evidence, duplicates, empty", () => {
  const ok = st("ok", 19.076, 72.877);
  const nullIsland = st("ni", 0, 0);
  const nan = st("nan", NaN, 72.877);
  const noEvidence = st("noev", 19.076, 72.877, {
    connectors: [{ id: "u1", type: "Unknown", powerKw: null, total: null, available: null }],
  });
  // Unknown connectors + verified price IS usable evidence.
  const priceOnly = st("priceonly", 19.076, 72.877, {
    price: 20,
    connectors: [{ id: "u2", type: "Unknown", powerKw: null, total: null, available: null }],
  });
  assert.deepEqual(recommendStations([nullIsland, nan, noEvidence]), []);
  assert.equal(recommendStations([priceOnly]).length, 1);

  // Duplicate candidates collapse to one (first occurrence wins).
  const dup = st("dup", 19.076, 72.877);
  const dupRecs = recommendStations([dup, { ...dup }]);
  assert.equal(dupRecs.length, 1);
  assert.equal(
    evaluateRecommendations([dup, { ...dup }]).length,
    1
  );

  // Empty input is an honest empty result, never fabricated.
  assert.deepEqual(recommendStations([]), []);
  assert.deepEqual(evaluateRecommendations([]), []);
});

test("distance ranking, determinism, and count clamp", () => {
  const near = st("near", 19.077, 72.878);
  const far = st("far", 19.5, 73.2);
  const userLoc = { lat: 19.076, lng: 72.877 };
  const recs = recommendStations([far, near], { userLoc });
  assert.equal(recs[0].stationId, "near");
  assert.ok(recs[0].reasons.includes("nearby"));
  assert.ok(!recs[1].reasons.includes("nearby"));

  // Deterministic: identical inputs yield identical outputs (modulo timestamp).
  const input = [near, far, st("mid", 19.08, 72.88)];
  const a = evaluateRecommendations(input, { userLoc }).map(({ evaluatedAt, ...r }) => r);
  const b = evaluateRecommendations(input, { userLoc }).map(({ evaluatedAt, ...r }) => r);
  assert.deepEqual(a, b);
  assert.deepEqual(recommendStations(input, { userLoc }), recommendStations(input, { userLoc }));

  // Count clamps to 1..3.
  const five = ["a", "b", "c", "d", "e"].map((id, i) =>
    st(id, 19.076 + i * 0.001, 72.877)
  );
  assert.equal(recommendStations(five).length, 3);
  assert.equal(recommendStations(five, { count: 99 }).length, 3);
  assert.equal(recommendStations(five, { count: 1 }).length, 1);
});

test("internal explanation is complete and internally consistent", () => {
  const s = st("full", 19.076, 72.877, {
    status: "available",
    price: 18.5,
    connectors: availConn("full"),
  });
  const [e] = evaluateRecommendations([s], {
    userLoc: { lat: 19.077, lng: 72.878 },
  });
  assert.equal(e.recommenderVersion, RECOMMENDER_VERSION);
  assert.equal(e.recommenderVersion, "baseline-v1");
  assert.ok(!Number.isNaN(Date.parse(e.evaluatedAt)));
  assert.equal(e.eligible, true);
  assert.deepEqual(e.exclusionReasons, []);
  assert.equal(e.rank, 1);
  assert.equal(e.availabilityState, "available");
  // Contributions sum to the score; weights match the documented constants.
  const sum =
    e.contributions.knownType +
    e.contributions.knownPower +
    e.contributions.verifiedPrice +
    e.contributions.availability +
    e.contributions.proximity;
  assert.equal(e.score, sum);
  assert.equal(e.contributions.knownType, RECOMMENDER_WEIGHTS.knownType);
  assert.equal(e.contributions.knownPower, RECOMMENDER_WEIGHTS.knownPower);
  assert.equal(e.contributions.verifiedPrice, RECOMMENDER_WEIGHTS.verifiedPrice);
  assert.equal(e.contributions.availability, RECOMMENDER_WEIGHTS.genuinelyAvailable);
  assert.ok(
    e.contributions.proximity >= 0 &&
      e.contributions.proximity <= RECOMMENDER_WEIGHTS.proximityMax
  );
  // Ineligible candidates score 0 with null rank.
  const [bad] = evaluateRecommendations([st("x", 0, 0)]);
  assert.equal(bad.eligible, false);
  assert.equal(bad.score, 0);
  assert.equal(bad.rank, null);
});

test("consumer records expose no internal diagnostics", () => {
  const stations = [
    st("a", 19.076, 72.877, { price: 15 }),
    st("b", 19.08, 72.88),
  ];
  const recs = recommendStations(stations, { userLoc: { lat: 19.076, lng: 72.877 } });
  assert.ok(recs.length > 0);
  const json = JSON.stringify(recs);
  assert.ok(!json.includes("score"));
  assert.ok(!json.includes("weight"));
  assert.ok(!json.includes("unknowns"));
  assert.ok(!json.includes("contribution"));
  for (const r of recs) {
    assert.deepEqual(Object.keys(r).sort(), ["availableCount", "reasons", "stationId"].filter((k) => k in r).sort());
    for (const reason of r.reasons) {
      assert.ok(
        ["matchConnector", "availableNow", "knownPower", "priceAvailable", "nearby", "availabilityUnknown"].includes(reason)
      );
    }
  }
});
