/**
 * Server-persisted favorites (Step 3.8). Rows live in public.favorites keyed by
 * (user_id, station_id); the composite PK makes double-saves impossible and RLS
 * restricts every operation to auth.uid(). The caller passes its session user id;
 * RLS independently rejects anything that does not match the authenticated user.
 */

export type FavoritesClient = {
  from: (table: string) => any;
};

/** All station ids the user saved, newest first. Empty (not error) when none. */
export async function listFavorites(
  client: FavoritesClient,
  userId: string
): Promise<string[]> {
  if (!userId) return [];
  const { data, error } = await client
    .from("favorites")
    .select("station_id")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) {
    throw new Error(`listFavorites error: ${error.message}`);
  }
  const rows = (data ?? []) as Array<{ station_id: string }>;
  return rows.map((r) => r.station_id).filter((id) => typeof id === "string");
}

/**
 * Save a station. A duplicate (unique violation) is treated as already saved —
 * idempotent, never an error to the caller.
 */
export async function addFavorite(
  client: FavoritesClient,
  userId: string,
  stationId: string
): Promise<void> {
  if (!userId || !stationId) {
    throw new Error("A signed-in user and a station are required.");
  }
  const { error } = await client.from("favorites").insert({ user_id: userId, station_id: stationId });
  if (error && (error as { code?: string }).code !== "23505") {
    throw new Error(`addFavorite error: ${error.message}`);
  }
}

/** Remove a saved station. Removing a non-saved station is a no-op success. */
export async function removeFavorite(
  client: FavoritesClient,
  userId: string,
  stationId: string
): Promise<void> {
  if (!userId || !stationId) {
    throw new Error("A signed-in user and a station are required.");
  }
  const { error } = await client
    .from("favorites")
    .delete()
    .eq("user_id", userId)
    .eq("station_id", stationId);
  if (error) {
    throw new Error(`removeFavorite error: ${error.message}`);
  }
}
