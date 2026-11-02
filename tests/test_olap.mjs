import test from "node:test";
import assert from "node:assert/strict";
import {
  executeOlapRollup,
  executeOlapDrilldown,
  executeOlapSlice,
  executeOlapDice,
  executeOlapCube,
  executeOlapWindowRanking,
  OLAP_PROVENANCE,
} from "../src/lib/olap.ts";

test("OLAP Rollup: returns progressive weekly aggregate with totals", async () => {
  const res = await executeOlapRollup("weekly");
  assert.equal(res.operation, "rollup");
  assert.equal(res.provenance.totalFactRows, 360);
  assert.ok(res.rows.length >= 5);
  
  const hasSubtotal = res.rows.some((r) => String(r.calendar_week).includes("TOTAL"));
  assert.ok(hasSubtotal, "Must include weekly subtotal rows");
});

test("OLAP Drilldown: sorts localities and stations by descending utilization", async () => {
  const res = await executeOlapDrilldown("Mumbai");
  assert.equal(res.operation, "drilldown");
  assert.ok(res.rows.length > 0);
  
  const first = Number(res.rows[0].locality_avg_utilization);
  const second = Number(res.rows[1].locality_avg_utilization);
  assert.ok(first >= second, "Drilldown rows must be ordered by descending utilization");
});

test("OLAP Slice: fixes single operator dimension safely", async () => {
  const res = await executeOlapSlice("Tata Power");
  assert.equal(res.operation, "slice");
  assert.ok(res.rows.length > 0);
  for (const row of res.rows) {
    assert.equal(row.operator_name, "Tata Power");
  }
});

test("OLAP Dice: filters across operators, localities, and weekend/weekday", async () => {
  const res = await executeOlapDice(["Tata Power"], ["Bandra Kurla Complex"], "all");
  assert.equal(res.operation, "dice");
  assert.ok(res.rows.length > 0);
  for (const row of res.rows) {
    assert.equal(row.operator_name, "Tata Power");
    assert.equal(row.locality, "Bandra Kurla Complex");
  }
});

test("OLAP Cube: generates multi-dimensional cross-tabulation with grand totals", async () => {
  const res = await executeOlapCube();
  assert.equal(res.operation, "cube");
  assert.ok(res.rows.length > 0);
  
  const grandTotal = res.rows.find(
    (r) => r.operator === "ALL OPERATORS" && r.locality === "ALL LOCALITIES"
  );
  assert.ok(grandTotal, "Cube must include ALL OPERATORS x ALL LOCALITIES grand total");
  assert.equal(grandTotal.days_monitored, 360);
});

test("OLAP Window Ranking: partitions by operator and caps at rank <= topN", async () => {
  const topN = 2;
  const res = await executeOlapWindowRanking(topN);
  assert.equal(res.operation, "window_ranking");
  assert.ok(res.rows.length > 0);
  for (const row of res.rows) {
    assert.ok(Number(row.rank_in_network) <= topN);
  }
});

