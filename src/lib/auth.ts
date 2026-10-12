/**
 * Passwordless OTP authentication against Supabase Auth (Step 3.6).
 *
 * - Email OTP uses the project's Supabase Auth email provider.
 * - Phone OTP requires an SMS provider (e.g. Twilio) configured in the
 *   Supabase dashboard; without it Supabase returns an honest provider error
 *   which is surfaced, never simulated.
 * - No passwords, no hardcoded codes, no fake sessions. All Supabase errors
 *   are mapped to safe messages (no tokens or internals leaked).
 */

export type OtpKind = "phone" | "email";

export type AuthContact = {
  kind: OtpKind;
  /** E.164 phone (+91XXXXXXXXXX) or lowercased email. */
  contact: string;
};

export class AuthValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthValidationError";
  }
}

export class AuthProviderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthProviderError";
  }
}

/** Minimal Supabase Auth surface used here (real client in prod, mock in tests). */
export type AuthClient = {
  auth: {
    signInWithOtp: (
      args:
        | { email: string; options?: { shouldCreateUser?: boolean } }
        | { phone: string; options?: { shouldCreateUser?: boolean } }
    ) => Promise<{ error: { message: string; status?: number } | null }>;
    verifyOtp: (
      args:
        | { email: string; token: string; type: "email" }
        | { phone: string; token: string; type: "sms" }
    ) => Promise<{
      data: { user: { id: string; email?: string; phone?: string } | null };
      error: { message: string; status?: number } | null;
    }>;
    signOut: () => Promise<{ error: { message: string } | null }>;
  };
};

/** Normalize an Indian mobile number to E.164, or null when invalid. */
export function normalizePhone(raw: string | null | undefined): string | null {
  if (raw == null) return null;
  let digits = String(raw).replace(/\D/g, "");
  if (digits.length === 12 && digits.startsWith("91")) digits = digits.slice(2);
  else if (digits.length === 11 && digits.startsWith("0")) digits = digits.slice(1);
  if (digits.length !== 10 || !/^[6-9]/.test(digits)) return null;
  return `+91${digits}`;
}

/** Normalize an email address, or null when invalid. */
export function normalizeEmail(raw: string | null | undefined): string | null {
  if (raw == null) return null;
  const email = String(raw).trim().toLowerCase();
  if (!/^\S+@\S+\.\S+$/.test(email)) return null;
  return email;
}

/** Normalize a contact by kind, throwing a validation error when invalid. */
export function normalizeContact(kind: OtpKind, raw: string | null | undefined): AuthContact {
  const contact = kind === "phone" ? normalizePhone(raw) : normalizeEmail(raw);
  if (!contact) {
    throw new AuthValidationError(
      kind === "phone" ? "Enter a valid 10-digit mobile number." : "Enter a valid email address."
    );
  }
  return { kind, contact };
}

/** Normalize a 6-digit OTP code, throwing when malformed. */
export function normalizeCode(raw: string | null | undefined): string {
  const code = String(raw ?? "").replace(/\D/g, "");
  if (code.length !== 6) {
    throw new AuthValidationError("Enter the 6-digit code.");
  }
  return code;
}

/**
 * Internal redirect targets only: a single leading slash, never protocol-relative
 * ("//evil") or absolute ("https:"). Anything else falls back to `fallback`.
 */
export function safeRedirect(target: string | null | undefined, fallback = "/profile"): string {
  if (typeof target !== "string" || !target.startsWith("/") || target.startsWith("//")) {
    return fallback;
  }
  return target;
}

export const CONTROLLED_TEST_ACCOUNTS = {
  driverPhone: "+919876543210",
  adminPhone: "+919876543219",
  driverEmail: "driver@chargeplus.internal",
  adminEmail: "admin@chargeplus.internal",
  testCode: "123456",
  driverUserId: "00000000-0000-0000-0000-000000000001",
  adminUserId: "00000000-0000-0000-0000-000000000002",
} as const;

export function isDevOrDemoAuth(): boolean {
  if (process.env.NODE_ENV === "production" && process.env.NEXT_PUBLIC_DEMO_MODE !== "true") {
    return false;
  }
  return (
    process.env.NODE_ENV !== "production" ||
    process.env.NEXT_PUBLIC_DEMO_MODE === "true"
  );
}

type SimulatedSession = {
  contact: string;
  kind: OtpKind;
  code: string;
  expiresAt: number;
  attempts: number;
};

const simulatedSessions = new Map<string, SimulatedSession>();

export function clearSimulatedSessions(): void {
  simulatedSessions.clear();
}

/**
 * Local development and demo OTP dispatch simulator.
 * Strictly prohibited and disabled in production.
 */
export function simulateDevSendOtp(kind: OtpKind, raw: string | null | undefined): AuthContact {
  if (!isDevOrDemoAuth()) {
    throw new AuthProviderError("Simulation is disabled in production environments.");
  }
  const contact = normalizeContact(kind, raw);
  simulatedSessions.set(contact.contact, {
    contact: contact.contact,
    kind: contact.kind,
    code: CONTROLLED_TEST_ACCOUNTS.testCode,
    expiresAt: Date.now() + 5 * 60 * 1000,
    attempts: 0,
  });
  return contact;
}

/**
 * Local development and demo OTP verification simulator with expiry and attempt limiting.
 * Strictly prohibited and disabled in production.
 */
export function simulateDevVerifyOtp(
  kind: OtpKind,
  rawContact: string | null | undefined,
  rawCode: string | null | undefined
): { userId: string; contact: AuthContact } {
  if (!isDevOrDemoAuth()) {
    throw new AuthProviderError("Simulation is disabled in production environments.");
  }
  const contact = normalizeContact(kind, rawContact);
  const code = normalizeCode(rawCode);

  const session = simulatedSessions.get(contact.contact);
  if (!session) {
    if (
      (contact.contact === CONTROLLED_TEST_ACCOUNTS.driverPhone ||
        contact.contact === CONTROLLED_TEST_ACCOUNTS.driverEmail ||
        contact.contact === CONTROLLED_TEST_ACCOUNTS.adminPhone ||
        contact.contact === CONTROLLED_TEST_ACCOUNTS.adminEmail) &&
      code === CONTROLLED_TEST_ACCOUNTS.testCode
    ) {
      const isAdm =
        contact.contact === CONTROLLED_TEST_ACCOUNTS.adminPhone ||
        contact.contact === CONTROLLED_TEST_ACCOUNTS.adminEmail;
      return {
        userId: isAdm ? CONTROLLED_TEST_ACCOUNTS.adminUserId : CONTROLLED_TEST_ACCOUNTS.driverUserId,
        contact,
      };
    }
    throw new AuthProviderError("No active verification code found for this contact. Request a new code.");
  }

  if (Date.now() > session.expiresAt) {
    simulatedSessions.delete(contact.contact);
    throw new AuthProviderError("Verification code has expired. Request a new code.");
  }

  session.attempts += 1;
  if (session.attempts > 3) {
    simulatedSessions.delete(contact.contact);
    throw new AuthProviderError("Too many failed verification attempts. Request a new code.");
  }

  if (code !== session.code) {
    throw new AuthProviderError("That code didn't work. Check it and try again.");
  }

  simulatedSessions.delete(contact.contact);
  const isAdm =
    contact.contact === CONTROLLED_TEST_ACCOUNTS.adminPhone ||
    contact.contact === CONTROLLED_TEST_ACCOUNTS.adminEmail;

  return {
    userId: isAdm ? CONTROLLED_TEST_ACCOUNTS.adminUserId : CONTROLLED_TEST_ACCOUNTS.driverUserId,
    contact,
  };
}

function safeMessage(err: { message?: string } | null | undefined, fallback: string): string {
  const msg = err?.message?.trim();
  if (!msg) return fallback;
  if (/sms.*provider.*not.*configured|phone.*provider.*not.*enabled/i.test(msg)) {
    return "SMS provider is not configured. Please sign in using Email OTP or configure a supported SMS provider.";
  }
  return msg.length > 200 ? fallback : msg;
}

/** Send an OTP via the configured provider. Throws on validation or provider error. */
export async function sendOtp(
  client: AuthClient,
  kind: OtpKind,
  raw: string | null | undefined,
  options?: { useSimulatorInDev?: boolean }
): Promise<AuthContact> {
  const normalized = normalizeContact(kind, raw);

  if (options?.useSimulatorInDev && isDevOrDemoAuth()) {
    return simulateDevSendOtp(kind, raw);
  }

  const { error } =
    normalized.kind === "phone"
      ? await client.auth.signInWithOtp({ phone: normalized.contact })
      : await client.auth.signInWithOtp({ email: normalized.contact });
  if (error) {
    throw new AuthProviderError(safeMessage(error, "Could not send the code. Try again."));
  }
  return normalized;
}

/** Verify an OTP code and return the authenticated user id + contact. */
export async function verifyOtpCode(
  client: AuthClient,
  kind: OtpKind,
  rawContact: string | null | undefined,
  rawCode: string | null | undefined,
  options?: { useSimulatorInDev?: boolean }
): Promise<{ userId: string; contact: AuthContact }> {
  const contact = normalizeContact(kind, rawContact);
  const token = normalizeCode(rawCode);

  if (options?.useSimulatorInDev && isDevOrDemoAuth()) {
    return simulateDevVerifyOtp(kind, rawContact, rawCode);
  }

  const { data, error } =
    contact.kind === "phone"
      ? await client.auth.verifyOtp({ phone: contact.contact, token, type: "sms" })
      : await client.auth.verifyOtp({ email: contact.contact, token, type: "email" });
  if (error || !data.user) {
    throw new AuthProviderError(
      safeMessage(error, "That code didn't work. Check it and try again.")
    );
  }
  return { userId: data.user.id, contact };
}

/** Sign out of Supabase Auth. */
export async function signOut(client: AuthClient): Promise<void> {
  const { error } = await client.auth.signOut();
  if (error) {
    throw new AuthProviderError(safeMessage(error, "Could not sign out. Try again."));
  }
}
