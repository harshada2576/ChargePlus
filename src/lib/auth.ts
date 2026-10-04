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

function safeMessage(err: { message?: string } | null | undefined, fallback: string): string {
  const msg = err?.message?.trim();
  if (!msg) return fallback;
  // Provider messages are user-safe (no tokens); cap length defensively.
  return msg.length > 200 ? fallback : msg;
}

/** Send an OTP via the configured provider. Throws on validation or provider error. */
export async function sendOtp(
  client: AuthClient,
  kind: OtpKind,
  raw: string | null | undefined
): Promise<AuthContact> {
  const normalized = normalizeContact(kind, raw);
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
  rawCode: string | null | undefined
): Promise<{ userId: string; contact: AuthContact }> {
  const contact = normalizeContact(kind, rawContact);
  const token = normalizeCode(rawCode);
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
