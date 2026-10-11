import test from "node:test";
import assert from "node:assert/strict";
import {
  validateReview,
  submitReview,
  listApprovedReviews,
  listOwnReviews,
} from "../src/lib/reviews.ts";

const UID = "11111111-1111-1111-1111-111111111111";
const ST = "22222222-2222-2222-2222-222222222222";

function mockDb({ insertRow = { id: "rv1" }, insertError = null, updateError = null, rows = [], error = null, calls = null } = {}) {
  return {
    from(table) {
      return {
        insert: (payload) => ({
          select: () => ({
            maybeSingle: async () => {
              calls?.push(["insert", table, payload]);
              return { data: insertError ? null : insertRow, error: insertError };
            },
          }),
        }),
        update: (patch) => ({
          eq: () => ({
            eq: async () => {
              calls?.push(["update", table, patch]);
              return { error: updateError };
            },
          }),
        }),
        select: () => ({
          eq: () => ({
            order: () => ({
              limit: async () => {
                calls?.push(["select-view", table]);
                return { data: error ? null : rows, error };
              },
            }),
          }),
        }),
      };
    },
  };
}

function mockOwnDb({ rows = [], error = null } = {}) {
  return {
    from(table) {
      return {
        select: () => ({
          eq: () => ({
            order: async () => ({ data: error ? null : rows, error }),
          }),
        }),
      };
    },
  };
}

test("validation enforces rating, station, and user", () => {
  for (const bad of [
    { userId: "", stationId: ST, rating: 5 },
    { userId: UID, stationId: "bad", rating: 5 },
    { userId: UID, stationId: ST, rating: 0 },
    { userId: UID, stationId: ST, rating: 6 },
    { userId: UID, stationId: ST, rating: 2.5 },
  ]) assert.throws(() => validateReview(bad), Error);
  assert.equal(validateReview({ userId: UID, stationId: ST, rating: 5, comment: "  great  " }).comment, "great");
  assert.equal(validateReview({ userId: UID, stationId: ST, rating: 4 }).comment, null);
});

test("first submit inserts and reports no update", async () => {
  const calls = [];
  const out = await submitReview(mockDb({ calls }), { userId: UID, stationId: ST, rating: 5, comment: "fast" });
  assert.deepEqual(out, { updated: false });
  const [, , payload] = calls[0];
  assert.equal(payload.user_id, UID);
  assert.ok(!("moderation_status" in payload));
});

test("duplicate submits update the own row instead of failing", async () => {
  const calls = [];
  const out = await submitReview(
    mockDb({ calls, insertError: { message: "dup", code: "23505" } }),
    { userId: UID, stationId: ST, rating: 3 }
  );
  assert.deepEqual(out, { updated: true });
  assert.ok(calls.some(([op]) => op === "update"));
});

test("genuine failures never fake success", async () => {
  await assert.rejects(
    submitReview(mockDb({ insertError: { message: "rls" } }), { userId: UID, stationId: ST, rating: 4 }),
    /rls/
  );
  await assert.rejects(
    submitReview(
      mockDb({ insertError: { code: "23505", message: "dup" }, updateError: { message: "denied" } }),
      { userId: UID, stationId: ST, rating: 4 }
    ),
    /denied/
  );
});

test("approved list is sanitized and honest", async () => {
  const rows = [
    { id: "a", station_id: ST, rating: 5, comment: "good", author_display_name: "Asha", created_at: "t" },
    { id: "b", station_id: ST, rating: 2, comment: "", author_display_name: "  ", created_at: null },
  ];
  const out = await listApprovedReviews(mockDb({ rows }), ST);
  assert.equal(out[0].author, "Asha");
  assert.equal(out[1].comment, null);
  assert.equal(out[1].author, "A driver");
  assert.equal(out[1].createdAt, null);
  assert.ok(!("user_id" in out[0]) && !("moderation_status" in out[0]));
  assert.deepEqual(await listApprovedReviews(mockDb({ rows: [] }), ST), []);
  assert.deepEqual(await listApprovedReviews(mockDb({}), "nope"), []);
  await assert.rejects(listApprovedReviews(mockDb({ error: { message: "down" } }), ST), /down/);
});

test("own list carries moderation status for honesty", async () => {
  const rows = [
    { id: "a", station_id: ST, rating: 5, comment: "x", created_at: "t", moderation_status: "pending" },
  ];
  const out = await listOwnReviews(mockOwnDb({ rows }), UID);
  assert.equal(out[0].moderationStatus, "pending");
  assert.deepEqual(await listOwnReviews(mockOwnDb({}), ""), []);
  await assert.rejects(listOwnReviews(mockOwnDb({ error: { message: "down" } }), UID), /down/);
});
