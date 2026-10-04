/**
 * Canonical profile access (Step 3.7). Reads/writes public.profiles for the
 * authenticated user only; ownership and the role column are enforced by RLS
 * and column grants (clients cannot self-promote — role is read-only here).
 */

export type CanonicalProfile = {
  id: string;
  displayName: string | null;
  role: "user" | "admin";
  preferredLanguage: string | null;
  homeCity: string | null;
};

export type ProfileClient = {
  from: (table: string) => any;
};

type ProfileRow = {
  id: string;
  display_name?: string | null;
  role?: string | null;
  preferred_language?: string | null;
  home_city?: string | null;
};

function toProfile(row: ProfileRow): CanonicalProfile {
  return {
    id: row.id,
    displayName: row.display_name?.trim() ? row.display_name.trim() : null,
    role: row.role === "admin" ? "admin" : "user",
    preferredLanguage: row.preferred_language ?? null,
    homeCity: row.home_city?.trim() ? (row.home_city as string).trim() : null,
  };
}

/** Fetch the caller's own canonical profile. Null when absent. */
export async function fetchProfile(
  client: ProfileClient,
  userId: string
): Promise<CanonicalProfile | null> {
  if (!userId) return null;
  const { data, error } = await client
    .from("profiles")
    .select("id,display_name,role,preferred_language,home_city")
    .eq("id", userId)
    .maybeSingle();
  if (error) {
    throw new Error(`fetchProfile error: ${error.message}`);
  }
  if (!data) return null;
  return toProfile(data as ProfileRow);
}

/** Validate a display name against the database CHECK (1–120 chars). */
export function validateDisplayName(raw: string | null | undefined): string {
  const name = String(raw ?? "").trim().replace(/\s+/g, " ");
  if (name.length < 1 || name.length > 120) {
    throw new Error("Display name must be 1–120 characters.");
  }
  return name;
}

/** Update the caller's own display name. Only whitelisted columns are written. */
export async function updateDisplayName(
  client: ProfileClient,
  userId: string,
  raw: string | null | undefined
): Promise<CanonicalProfile> {
  const displayName = validateDisplayName(raw);
  const { data, error } = await client
    .from("profiles")
    .update({ display_name: displayName, updated_at: new Date().toISOString() })
    .eq("id", userId)
    .select("id,display_name,role,preferred_language,home_city")
    .maybeSingle();
  if (error) {
    throw new Error(`updateDisplayName error: ${error.message}`);
  }
  if (!data) {
    throw new Error("Profile not found for this user.");
  }
  return toProfile(data as ProfileRow);
}
