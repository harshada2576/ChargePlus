/**
 * Community reviews against public.reviews (Step 3.10).
 *
 * Experience feedback only — never availability labels, never station facts.
 * One row per (user, station): resubmitting updates the caller's own review
 * (RLS update-own). Public display reads approved rows only, through the
 * sanitized v_station_approved_reviews view (no user ids, no moderation
 * internals). Pending reviews are visible to their author with their status.
 */

export type ReviewInput = {
  userId: string;
  stationId: string;
  rating: number;
  comment?: string;
};

export type ApprovedReview = {
  id: string;
  stationId: string;
  rating: number;
  comment: string | null;
  author: string;
  createdAt: string | null;
};

export type OwnReview = ApprovedReview & {
  moderationStatus: string | null;
};

export type ReviewsClient = {
  from: (table: string) => any;
};

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Validate a review before it touches the network. Throws on defect. */
export function validateReview(input: ReviewInput): {
  userId: string;
  stationId: string;
  rating: number;
  comment: string | null;
} {
  if (!input.userId) {
    throw new Error("A signed-in user is required to review.");
  }
  if (!UUID_RE.test(input.stationId)) {
    throw new Error("A valid station is required to review.");
  }
  if (!Number.isInteger(input.rating) || input.rating < 1 || input.rating > 5) {
    throw new Error("Choose a rating from 1 to 5 stars.");
  }
  const comment = (input.comment ?? "").trim().slice(0, 500) || null;
  return { userId: input.userId, stationId: input.stationId, rating: input.rating, comment };
}

/**
 * Insert the caller's review, or update it when one already exists for the
 * station (unique user/station). Success is reported only after the server
 * confirms; new rows enter moderation as pending.
 */
export async function submitReview(
  client: ReviewsClient,
  input: ReviewInput
): Promise<{ updated: boolean }> {
  const row = validateReview(input);
  const payload = {
    user_id: row.userId,
    station_id: row.stationId,
    rating: row.rating,
    comment: row.comment,
  };
  const inserted = await client.from("reviews").insert(payload).select("id").maybeSingle();
  if (!inserted.error && inserted.data) return { updated: false };
  if (inserted.error && (inserted.error as { code?: string }).code !== "23505") {
    throw new Error(`submitReview error: ${inserted.error.message}`);
  }
  // Own review already exists — update it (RLS update-own).
  const { error } = await client
    .from("reviews")
    .update({ rating: row.rating, comment: row.comment, updated_at: new Date().toISOString() })
    .eq("user_id", row.userId)
    .eq("station_id", row.stationId);
  if (error) {
    throw new Error(`submitReview error: ${error.message}`);
  }
  return { updated: true };
}

/** Approved public reviews for a station (sanitized view, newest last kept stable). */
export async function listApprovedReviews(
  client: ReviewsClient,
  stationId: string
): Promise<ApprovedReview[]> {
  if (!UUID_RE.test(stationId)) return [];
  const { data, error } = await client
    .from("v_station_approved_reviews")
    .select("id,station_id,rating,comment,author_display_name,created_at")
    .eq("station_id", stationId)
    .order("created_at", { ascending: false })
    .limit(50);
  if (error) {
    throw new Error(`listApprovedReviews error: ${error.message}`);
  }
  return ((data ?? []) as any[]).map((r) => ({
    id: String(r.id),
    stationId: String(r.station_id),
    rating: Number(r.rating),
    comment: typeof r.comment === "string" && r.comment.length > 0 ? r.comment : null,
    author:
      typeof r.author_display_name === "string" && r.author_display_name.trim().length > 0
        ? r.author_display_name
        : "A driver",
    createdAt: typeof r.created_at === "string" ? r.created_at : null,
  }));
}

/** The caller's own reviews across stations, newest first, with status. */
export async function listOwnReviews(
  client: ReviewsClient,
  userId: string
): Promise<OwnReview[]> {
  if (!userId) return [];
  const { data, error } = await client
    .from("reviews")
    .select("id,station_id,rating,comment,created_at,moderation_status")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) {
    throw new Error(`listOwnReviews error: ${error.message}`);
  }
  return ((data ?? []) as any[]).map((r) => ({
    id: String(r.id),
    stationId: String(r.station_id),
    rating: Number(r.rating),
    comment: typeof r.comment === "string" && r.comment.length > 0 ? r.comment : null,
    author: "You",
    createdAt: typeof r.created_at === "string" ? r.created_at : null,
    moderationStatus: typeof r.moderation_status === "string" ? r.moderation_status : null,
  }));
}
