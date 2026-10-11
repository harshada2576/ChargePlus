import test from "node:test";
import assert from "node:assert/strict";
import { submitReport, listReports, validateReport } from "../src/lib/reports.ts";

const UID = "11111111-1111-1111-1111-111111111111";
const ST = "22222222-2222-2222-2222-222222222222";

function mockDb({ row = null, rows = [], error = null, calls = null } = {}) {
  return {
    from(table) {
      return {
        insert: (payload) => ({
          select: () => ({
            maybeSingle: async () => {
              calls?.push(["insert", table, payload]);
              return { data: error ? null : (row ?? payload), error };
            },
          }),
        }),
        select: () => ({
          eq: () => ({
            order: async () => {
              calls?.push(["select", table]);
              return { data: error ? null : rows, error };
            },
          }),
        }),
      };
    },
  };
}

test("validation rejects bad input before any network call", () => {
  const calls = [];
  const bad = [
    { userId: "", stationId: ST, status: "busy", queue: "short" },
    { userId: UID, stationId: "nope", status: "busy", queue: "short" },
    { userId: UID, stationId: ST, status: "unknown", queue: "short" },
    { userId: UID, stationId: ST, status: "busy", queue: "huge" },
  ];
  for (const input of bad) assert.throws(() => validateReport(input), Error);
  assert.equal(validateReport({ userId: UID, stationId: ST, status: "busy", queue: "short", note: "  hi  " }).comment, "hi");
  assert.equal(validateReport({ userId: UID, stationId: ST, status: "busy", queue: "none" }).comment, null);
  return submitReport(mockDb({ calls }), { userId: "", stationId: ST, status: "busy", queue: "none" })
    .then(() => assert.fail("should throw"), () => assert.deepEqual(calls, []));
});

test("submit writes a pending-by-default observation row", async () => {
  const calls = [];
  const out = await submitReport(
    mockDb({ calls, row: { id: "r1", station_id: ST, availability_status: "busy", queue_level: "short", comment: "q", created_at: "2026-10-04T00:00:00Z", moderation_status: "pending" } }),
    { userId: UID, stationId: ST, status: "busy", queue: "short", note: "q" },
    "2026-10-04T00:00:00Z"
  );
  assert.equal(out.id, "r1");
  assert.equal(out.moderationStatus, "pending");
  const [, , payload] = calls[0];
  assert.equal(payload.user_id, UID);
  assert.equal(payload.observed_at, "2026-10-04T00:00:00Z");
  assert.ok(!("moderation_status" in payload) && !("is_flagged" in payload));
});

test("submit failures never fake success", async () => {
  await assert.rejects(
    submitReport(mockDb({ error: { message: "rls denied" } }), { userId: UID, stationId: ST, status: "busy", queue: "none" }),
    /rls denied/
  );
});

test("list returns newest-first own rows with honest fallbacks", async () => {
  const rows = [
    { id: "r2", station_id: ST, availability_status: "available", queue_level: "none", comment: null, created_at: "t2", moderation_status: "approved" },
    { id: "r1", station_id: ST, availability_status: "weird", queue_level: "weird", comment: "", created_at: null, moderation_status: null },
  ];
  const out = await listReports(mockDb({ rows }), UID);
  assert.equal(out.length, 2);
  assert.equal(out[0].status, "available");
  assert.equal(out[1].status, "unknown"); // never coerced to busy
  assert.equal(out[1].queue, "unknown"); // never coerced to none
  assert.equal(out[1].note, null);
  assert.equal(out[1].submittedAt, null);
  assert.deepEqual(await listReports(mockDb({ rows: [] }), UID), []);
  assert.deepEqual(await listReports(mockDb({}), ""), []);
  await assert.rejects(listReports(mockDb({ error: { message: "down" } }), UID), /down/);
});
