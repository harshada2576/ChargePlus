import test from "node:test";
import assert from "node:assert/strict";
import {
  normalizePhone,
  normalizeEmail,
  normalizeContact,
  normalizeCode,
  safeRedirect,
  sendOtp,
  verifyOtpCode,
  signOut,
  AuthValidationError,
  AuthProviderError,
} from "../src/lib/auth.ts";

function mockAuth({
  sendError = null,
  verifyError = null,
  verifyUser = { id: "uid-1", email: "a@b.in", phone: null },
  calls = null,
} = {}) {
  return {
    auth: {
      signInWithOtp: async (args) => {
        calls?.push(["send", args]);
        return { error: sendError };
      },
      verifyOtp: async (args) => {
        calls?.push(["verify", args]);
        return { data: { user: verifyError ? null : verifyUser }, error: verifyError };
      },
      signOut: async () => {
        calls?.push(["signout", null]);
        return { error: null };
      },
    },
  };
}

test("phone normalization enforces Indian E.164", () => {
  assert.equal(normalizePhone("98765 43210"), "+919876543210");
  assert.equal(normalizePhone("+91-9876543210"), "+919876543210");
  assert.equal(normalizePhone("919876543210"), "+919876543210");
  assert.equal(normalizePhone("09876543210"), "+919876543210");
  assert.equal(normalizePhone("12345"), null);
  assert.equal(normalizePhone("5876543210"), null); // not a mobile series
  assert.equal(normalizePhone(null), null);
  assert.equal(normalizePhone(""), null);
});

test("email normalization trims, lowercases, and validates", () => {
  assert.equal(normalizeEmail("  A@B.in "), "a@b.in");
  assert.equal(normalizeEmail("not-an-email"), null);
  assert.equal(normalizeEmail("a@b"), null);
  assert.equal(normalizeEmail(null), null);
});

test("invalid contacts throw validation errors, never network calls", async () => {
  assert.throws(() => normalizeContact("phone", "123"), AuthValidationError);
  assert.throws(() => normalizeContact("email", "bad"), AuthValidationError);
  assert.throws(() => normalizeCode("12345"), AuthValidationError);
  assert.throws(() => normalizeCode("abcdef"), AuthValidationError);
  assert.equal(normalizeCode("1 2 3 4 5 6"), "123456");
  const calls = [];
  await assert.rejects(sendOtp(mockAuth({ calls }), "phone", "123"), AuthValidationError);
  assert.deepEqual(calls, []);
});

test("send uses the normalized contact and correct channel", async () => {
  const calls = [];
  const out = await sendOtp(mockAuth({ calls }), "phone", "9876543210");
  assert.deepEqual(out, { kind: "phone", contact: "+919876543210" });
  assert.deepEqual(calls, [["send", { phone: "+919876543210" }]]);
  const calls2 = [];
  await sendOtp(mockAuth({ calls: calls2 }), "email", "A@B.in");
  assert.deepEqual(calls2, [["send", { email: "a@b.in" }]]);
});

test("provider failures surface honestly without fake sessions", async () => {
  await assert.rejects(
    sendOtp(mockAuth({ sendError: { message: "SMS provider not configured" } }), "phone", "9876543210"),
    (e) => e instanceof AuthProviderError && /SMS provider/.test(e.message)
  );
  await assert.rejects(
    verifyOtpCode(
      mockAuth({ verifyError: { message: "Token has expired or is invalid" } }),
      "email",
      "a@b.in",
      "123456"
    ),
    (e) => e instanceof AuthProviderError && /expired|invalid/.test(e.message)
  );
});

test("verify maps sms/email types and returns the user id", async () => {
  const calls = [];
  const out = await verifyOtpCode(
    mockAuth({ calls, verifyUser: { id: "uid-9", phone: "+919876543210" } }),
    "phone",
    "9876543210",
    "654321"
  );
  assert.equal(out.userId, "uid-9");
  assert.deepEqual(calls, [["verify", { phone: "+919876543210", token: "654321", type: "sms" }]]);
  const calls2 = [];
  await verifyOtpCode(mockAuth({ calls: calls2 }), "email", "a@b.in", "111111");
  assert.deepEqual(calls2, [["verify", { email: "a@b.in", token: "111111", type: "email" }]]);
});

test("null user after verify never authenticates", async () => {
  await assert.rejects(
    verifyOtpCode(mockAuth({ verifyUser: null }), "email", "a@b.in", "123456"),
    AuthProviderError
  );
});

test("redirects stay internal", () => {
  assert.equal(safeRedirect("/profile"), "/profile");
  assert.equal(safeRedirect("/station/abc"), "/station/abc");
  assert.equal(safeRedirect("//evil.com"), "/profile");
  assert.equal(safeRedirect("https://evil.com"), "/profile");
  assert.equal(safeRedirect(null), "/profile");
  assert.equal(safeRedirect(""), "/profile");
});

test("signOut delegates to the provider", async () => {
  const calls = [];
  await signOut(mockAuth({ calls }));
  assert.deepEqual(calls, [["signout", null]]);
});
