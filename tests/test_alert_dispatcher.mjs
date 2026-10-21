import test from "node:test";
import assert from "node:assert/strict";
import {
  MockAlertDispatcher,
  dispatchAlertNotification,
} from "../src/lib/alertDispatcher.ts";

test("MockAlertDispatcher accepts valid notification and records dispatch payload", async () => {
  const dispatcher = new MockAlertDispatcher();
  const payload = {
    alertId: "alert-101",
    userId: "usr-456",
    recipientContact: "driver@example.com",
    channel: "mock",
    stationId: "st-789",
    stationName: "Jio-BP Pulse Bandra",
    alertType: "station_available",
    message: "Jio-BP Pulse Bandra now has 2 CCS2 chargers available.",
    timestamp: new Date().toISOString(),
  };

  const res = await dispatchAlertNotification(payload, dispatcher);
  assert.equal(res.success, true);
  assert.equal(res.channel, "mock");
  assert.ok(res.deliveredAt);
  assert.equal(dispatcher.dispatched.length, 1);
  assert.equal(dispatcher.dispatched[0].stationName, "Jio-BP Pulse Bandra");
});

test("MockAlertDispatcher rejects payloads missing essential identifiers", async () => {
  const dispatcher = new MockAlertDispatcher();
  const invalidPayload = {
    alertId: "alert-102",
    userId: "",
    channel: "mock",
    stationId: "st-789",
    stationName: "Unknown",
    alertType: "station_available",
    message: "Missing user",
    timestamp: new Date().toISOString(),
  };

  const res = await dispatchAlertNotification(invalidPayload, dispatcher);
  assert.equal(res.success, false);
  assert.match(res.error, /Missing required notification fields/);
  assert.equal(dispatcher.dispatched.length, 0);
});
