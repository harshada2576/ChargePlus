import test from "node:test";
import assert from "node:assert/strict";
import {
  listPendingReports,
  listPendingReviews,
  moderateReport,
  moderateReview,
  listIngestionRuns,
  countApprovedReviews,
} from "../src/lib/admin.ts";

const MOD = "11111111-1111-1111-1111-111111111111";
const RID = "22222222-2222-2222-2222-222222222222";

function mockDb({ rows = [], error = null, count = 3, calls = null } = {}) {
  const chainable = {
    eq: () => chainable,
    order: () => chainable,
    limit: async () => {
      calls?.push(["select"]);
      return { data: error ? null : rows, error };
    },
  };
  return {
    from(table) {
      return {
        select: (...args) => {
          calls?.push(["select-cols", table, args]);
          if (args[1]?.count === "exact") {
            return { eq: async () => ({ count: error ? null : count, error }) };
          }
          return chainable;
        },
        update: (patch) => ({
          eq: async () => {
            calls?.push(["update", table, patch]);
            return { error };
          },
        }),
      };
    },
  };
}

test("pending queues map honestly and fail loudly", async () => {
  const repRows = [
    { id: "r1", station_id: "s", availability_status: "busy", queue_level: "short", comment: "q", created_at: "t" },
    { id: "r2", station_id: "s", availability_status: "available", queue_level: "none", comment: "", created_at: null },
  ];
  const reps = await listPendingReports(mockDb({ rows: repRows }));
  assert.equal(reps.length, 2);
  assert.equal(reps[1].note, null);
  assert.equal(reps[1].createdAt, null);
  const revRows = [{ id: "v1", station_id: "s", rating: 2, comment: null, created_at: "t" }];
  const revs = await listPendingReviews(mockDb({ rows: revRows }));
  assert.equal(revs[0].comment, null);
  await assert.rejects(listPendingReports(mockDb({ error: { message: "denied" } })), /denied/);
  await assert.rejects(listPendingReviews(mockDb({ error: { message: "denied" } })), /denied/);
});

test("moderation writes decision, moderator, and timestamp", async () => {
  const calls = [];
  await moderateReport(mockDb({ calls }), { id: RID, approved: true, moderatorId: MOD });
  const [, , patch] = calls.find(([op]) => op === "update");
  assert.equal(patch.moderation_status, "approved");
  assert.equal(patch.moderated_by, MOD);
  assert.ok(typeof patch.moderated_at === "string");
  const calls2 = [];
  await moderateReview(mockDb({ calls: calls2 }), { id: RID, approved: false, moderatorId: MOD });
  assert.equal(calls2.find(([op]) => op === "update")[2].moderation_status, "rejected");
});

test("moderation validates ids and never fakes success", async () => {
  await assert.rejects(moderateReport(mockDb({}), { id: "bad", approved: true, moderatorId: MOD }), /report/);
  await assert.rejects(moderateReview(mockDb({}), { id: RID, approved: true, moderatorId: "" }), /moderator/);
  await assert.rejects(
    moderateReport(mockDb({ error: { message: "not admin" } }), { id: RID, approved: true, moderatorId: MOD }),
    /not admin/
  );
});

test("ingestion runs map with honest nulls", async () => {
  const rows = [
    { id: "run1", source_name: "open_charge_map", scope: "mmr", state: "SUCCEEDED", started_at: "t", duration_seconds: 12.5, records_fetched: 8, records_accepted: 8, stations_persisted: 0, error_summary: null },
    { id: "run2", source_name: "x", scope: "y", state: "FAILED", started_at: null, duration_seconds: null, records_fetched: 0, records_accepted: 0, stations_persisted: 0, error_summary: "boom" },
  ];
  const out = await listIngestionRuns(mockDb({ rows }));
  assert.equal(out[0].durationSeconds, 12.5);
  assert.equal(out[1].startedAt, null);
  assert.equal(out[1].errorSummary, "boom");
  await assert.rejects(listIngestionRuns(mockDb({ error: { message: "denied" } })), /denied/);
});

test("approved count is exact or honestly unknown", async () => {
  assert.equal(await countApprovedReviews(mockDb({ count: 7 })), 7);
  assert.equal(await countApprovedReviews(mockDb({ error: { message: "denied" } })), null);
});
