import test from "node:test";
import assert from "node:assert/strict";
import { addFavorite, listFavorites, removeFavorite } from "../src/lib/favorites.ts";

function mockDb({ rows = [], error = null, calls = null } = {}) {
  return {
    from(table) {
      return {
        select: () => ({
          eq: () => ({
            order: async () => {
              calls?.push(["select", table]);
              if (error) return { data: null, error };
              return { data: rows, error: null };
            },
          }),
        }),
        insert: async (row) => {
          calls?.push(["insert", table, row]);
          return { error };
        },
        delete: () => ({
          eq: () => ({
            eq: async () => {
              calls?.push(["delete", table]);
              return { error };
            },
          }),
        }),
      };
    },
  };
}

test("list returns saved ids in order, empty when none", async () => {
  const ids = await listFavorites(
    mockDb({ rows: [{ station_id: "b" }, { station_id: "a" }] }),
    "u1"
  );
  assert.deepEqual(ids, ["b", "a"]);
  assert.deepEqual(await listFavorites(mockDb({ rows: [] }), "u1"), []);
  assert.deepEqual(await listFavorites(mockDb({}), ""), []);
});

test("list failures throw instead of faking an empty list", async () => {
  await assert.rejects(listFavorites(mockDb({ error: { message: "rls" } }), "u1"), /rls/);
});

test("add writes the caller user id and station id", async () => {
  const calls = [];
  await addFavorite(mockDb({ calls }), "u1", "st-1");
  assert.deepEqual(calls, [["insert", "favorites", { user_id: "u1", station_id: "st-1" }]]);
  await assert.rejects(addFavorite(mockDb({}), "", "st-1"), /signed-in user/);
  await assert.rejects(
    addFavorite(mockDb({ error: { message: "fk" } }), "u1", "st-1"),
    /fk/
  );
});

test("duplicate saves are idempotent, never errors", async () => {
  await addFavorite(mockDb({ error: { message: "duplicate", code: "23505" } }), "u1", "st-1");
});

test("remove scopes to the caller and tolerates non-saved stations", async () => {
  const calls = [];
  await removeFavorite(mockDb({ calls }), "u1", "st-1");
  assert.deepEqual(calls, [["delete", "favorites"]]);
  await assert.rejects(
    removeFavorite(mockDb({ error: { message: "denied" } }), "u1", "st-1"),
    /denied/
  );
});
