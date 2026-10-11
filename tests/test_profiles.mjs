import test from "node:test";
import assert from "node:assert/strict";
import {
  fetchProfile,
  updateDisplayName,
  validateDisplayName,
} from "../src/lib/profiles.ts";

function mockDb({ profile = null, profileError = null, calls = null } = {}) {
  return {
    from(table) {
      return {
        select: () => ({
          eq: () => ({
            maybeSingle: async () => {
              calls?.push(["select", table]);
              return { data: profile, error: profileError };
            },
          }),
        }),
        update: (patch) => ({
          eq: () => ({
            select: () => ({
              maybeSingle: async () => {
                calls?.push(["update", table, patch]);
                return { data: profileError ? null : { ...(profile ?? {}), ...patch }, error: profileError };
              },
            }),
          }),
        }),
        insert: (row) => {
          calls?.push(["insert", table, row]);
          return Promise.resolve({ data: row, error: profileError });
        },
      };
    },
  };
}

test("profile mapping keeps role server-truthful", async () => {
  const p = await fetchProfile(
    mockDb({ profile: { id: "u1", display_name: "  Asha  ", role: "admin", preferred_language: "hi", home_city: "" } }),
    "u1"
  );
  assert.equal(p.displayName, "Asha");
  assert.equal(p.role, "admin");
  assert.equal(p.preferredLanguage, "hi");
  assert.equal(p.homeCity, null);
  const user = await fetchProfile(
    mockDb({ profile: { id: "u2", display_name: null, role: "superuser" } }),
    "u2"
  );
  assert.equal(user.role, "user"); // unknown roles never escalate
  assert.equal(user.displayName, null);
});

test("absent profile returns null without fabrication", async () => {
  assert.equal(await fetchProfile(mockDb({ profile: null }), "u9"), null);
  assert.equal(await fetchProfile(mockDb({}), ""), null);
});

test("profile query failures throw", async () => {
  await assert.rejects(fetchProfile(mockDb({ profileError: { message: "denied" } }), "u1"), /denied/);
});

test("display-name validation matches the 1-120 CHECK", () => {
  assert.equal(validateDisplayName("  Ravi Kumar  "), "Ravi Kumar");
  assert.throws(() => validateDisplayName(""), /1–120/);
  assert.throws(() => validateDisplayName("   "), /1–120/);
  assert.throws(() => validateDisplayName("x".repeat(121)), /1–120/);
  assert.equal(validateDisplayName("y".repeat(120)).length, 120);
});

test("update writes only whitelisted columns for the caller id", async () => {
  const calls = [];
  const out = await updateDisplayName(
    mockDb({ calls, profile: { id: "u1", display_name: "Old", role: "user" } }),
    "u1",
    "New Name"
  );
  assert.equal(out.displayName, "New Name");
  assert.equal(out.role, "user"); // role untouched
  const [, , patch] = calls.find(([op]) => op === "update");
  assert.deepEqual(Object.keys(patch).sort(), ["display_name", "updated_at"]);
});

test("update failures and missing rows never fake success", async () => {
  await assert.rejects(
    updateDisplayName(mockDb({ profileError: { message: "rls" } }), "u1", "Name"),
    /rls/
  );
  await assert.rejects(updateDisplayName(mockDb({}), "ghost", ""), /1–120/);
});
