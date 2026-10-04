import test from "node:test";
import assert from "node:assert/strict";
import { toDbAlertType, toUiAlertType, listAlerts, setAlert } from "../src/lib/alerts.ts";

const UID = "11111111-1111-1111-1111-111111111111";
const ST = "22222222-2222-2222-2222-222222222222";

function mockDb({ rows = [], error = null, insertRow = { id: "al-1" }, insertError = null, calls = null } = {}) {
  return {
    from(table) {
      return {
        select: () => ({
          eq: () => ({
            order: async () => {
              calls?.push(["select", table]);
              return { data: error ? null : rows, error };
            },
          }),
        }),
        insert: (payload) => ({
          select: () => ({
            maybeSingle: async () => {
              calls?.push(["insert", table, payload]);
              return { data: insertError ? null : { ...insertRow, ...payload }, error: insertError };
            },
          }),
        }),
        update: (patch) => ({
          eq: () => ({
            eq: async () => {
              calls?.push(["update", table, patch]);
              return { error };
            },
          }),
        }),
      };
    },
  };
}

test("UI alert types map to canonical DB types explicitly", () => {
  assert.equal(toDbAlertType("available"), "station_available");
  assert.equal(toDbAlertType("lessBusy"), "congestion_threshold");
  assert.equal(toUiAlertType("station_available"), "available");
  assert.equal(toUiAlertType("congestion_threshold"), "lessBusy");
  assert.equal(toUiAlertType("station_status_change"), null); // no UI toggle claims it
  assert.equal(toUiAlertType(null), null);
});

test("list maps rows honestly and fails loudly", async () => {
  const rows = [
    { id: "a", station_id: ST, alert_type: "station_available", is_enabled: true },
    { id: "b", station_id: ST, alert_type: "station_status_change", is_enabled: true },
    { id: "c", station_id: null, alert_type: "congestion_threshold", is_enabled: false },
  ];
  const out = await listAlerts(mockDb({ rows }), UID);
  assert.deepEqual(out[0], { id: "a", stationId: ST, uiType: "available", enabled: true });
  assert.equal(out[1].uiType, null);
  assert.equal(out[2].stationId, null);
  assert.deepEqual(await listAlerts(mockDb({ rows: [] }), UID), []);
  assert.deepEqual(await listAlerts(mockDb({}), ""), []);
  await assert.rejects(listAlerts(mockDb({ error: { message: "down" } }), UID), /down/);
});

test("enabling a new condition inserts a whitelisted row", async () => {
  const calls = [];
  const out = await setAlert(
    mockDb({ calls }), { userId: UID, stationId: ST, uiType: "available", enabled: true }, []
  );
  assert.equal(out.enabled, true);
  assert.equal(out.uiType, "available");
  const [, , payload] = calls[0];
  assert.equal(payload.user_id, UID);
  assert.equal(payload.alert_type, "station_available");
  assert.ok(!("last_triggered_at" in payload));
});

test("toggling an existing condition updates instead of duplicating", async () => {
  const calls = [];
  const existing = [{ id: "a", stationId: ST, uiType: "available", enabled: true }];
  const out = await setAlert(
    mockDb({ calls }), { userId: UID, stationId: ST, uiType: "available", enabled: false }, existing
  );
  assert.equal(out.enabled, false);
  assert.ok(calls.some(([op]) => op === "update"));
  assert.ok(!calls.some(([op]) => op === "insert"));
  const same = await setAlert(
    mockDb({ calls }), { userId: UID, stationId: ST, uiType: "available", enabled: false }, existing
  );
  assert.equal(same.enabled, false); // no-op success, no write needed beyond update path
});

test("disabling an unconfigured condition persists nothing", async () => {
  const calls = [];
  const out = await setAlert(
    mockDb({ calls }), { userId: UID, stationId: ST, uiType: "lessBusy", enabled: false }, []
  );
  assert.equal(out.enabled, false);
  assert.deepEqual(calls, []);
});

test("validation and failures never fake success", async () => {
  await assert.rejects(setAlert(mockDb({}), { userId: "", stationId: ST, uiType: "available", enabled: true }), /signed-in/);
  await assert.rejects(setAlert(mockDb({}), { userId: UID, stationId: "bad", uiType: "available", enabled: true }), /valid station/);
  await assert.rejects(
    setAlert(mockDb({ insertError: { message: "denied" } }), { userId: UID, stationId: ST, uiType: "available", enabled: true }, []),
    /denied/
  );
});
