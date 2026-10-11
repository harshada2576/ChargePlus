/**
 * Operations-console data access (Step 3.12).
 *
 * Everything here is gated twice: the console renders only for sessions whose
 * canonical profile role is "admin" (Step 3.7 overlay), and every query/write
 * is additionally enforced by RLS admin policies (profiles.role = 'admin').
 * Non-admin callers receive RLS denials or empty sets — never admin data.
 * Placeholder metrics with no source (model accuracy, pool stats, uptime) are
 * intentionally absent: the dashboard renders honest unavailable states.
 */

export type AdminClient = {
  from: (table: string) => any;
};

export type PendingReport = {
  id: string;
  stationId: string;
  status: string;
  queue: string | null;
  note: string | null;
  createdAt: string | null;
};

export type PendingReview = {
  id: string;
  stationId: string;
  rating: number;
  comment: string | null;
  createdAt: string | null;
};

export type IngestionRun = {
  id: string;
  sourceName: string;
  scope: string;
  state: string;
  startedAt: string | null;
  durationSeconds: number | null;
  recordsFetched: number;
  recordsAccepted: number;
  stationsPersisted: number;
  errorSummary: string | null;
};

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function reqUuid(id: string, what: string): void {
  if (!UUID_RE.test(id)) throw new Error(`Valid ${what} id is required.`);
}

/** Pending community reports (moderation queue), newest first. */
export async function listPendingReports(client: AdminClient): Promise<PendingReport[]> {
  const { data, error } = await client
    .from("user_reports")
    .select("id,station_id,availability_status,queue_level,comment,created_at")
    .eq("moderation_status", "pending")
    .order("created_at", { ascending: false })
    .limit(50);
  if (error) {
    throw new Error(`listPendingReports error: ${error.message}`);
  }
  return ((data ?? []) as any[]).map((r) => ({
    id: String(r.id),
    stationId: String(r.station_id),
    status: String(r.availability_status),
    queue: typeof r.queue_level === "string" ? r.queue_level : null,
    note: typeof r.comment === "string" && r.comment.length > 0 ? r.comment : null,
    createdAt: typeof r.created_at === "string" ? r.created_at : null,
  }));
}

/** Pending reviews (moderation queue), newest first. */
export async function listPendingReviews(client: AdminClient): Promise<PendingReview[]> {
  const { data, error } = await client
    .from("reviews")
    .select("id,station_id,rating,comment,created_at")
    .eq("moderation_status", "pending")
    .order("created_at", { ascending: false })
    .limit(50);
  if (error) {
    throw new Error(`listPendingReviews error: ${error.message}`);
  }
  return ((data ?? []) as any[]).map((r) => ({
    id: String(r.id),
    stationId: String(r.station_id),
    rating: Number(r.rating),
    comment: typeof r.comment === "string" && r.comment.length > 0 ? r.comment : null,
    createdAt: typeof r.created_at === "string" ? r.created_at : null,
  }));
}

/** Approve (true) or reject (false) a report. Moderator identity is recorded. */
export async function moderateReport(
  client: AdminClient,
  input: { id: string; approved: boolean; moderatorId: string }
): Promise<void> {
  reqUuid(input.id, "report");
  reqUuid(input.moderatorId, "moderator");
  const { error } = await client
    .from("user_reports")
    .update({
      moderation_status: input.approved ? "approved" : "rejected",
      moderated_by: input.moderatorId,
      moderated_at: new Date().toISOString(),
    })
    .eq("id", input.id);
  if (error) {
    throw new Error(`moderateReport error: ${error.message}`);
  }
}

/** Publish (true) or hide (false) a review. Moderator identity is recorded. */
export async function moderateReview(
  client: AdminClient,
  input: { id: string; approved: boolean; moderatorId: string }
): Promise<void> {
  reqUuid(input.id, "review");
  reqUuid(input.moderatorId, "moderator");
  const { error } = await client
    .from("reviews")
    .update({
      moderation_status: input.approved ? "approved" : "rejected",
      moderated_by: input.moderatorId,
      moderated_at: new Date().toISOString(),
    })
    .eq("id", input.id);
  if (error) {
    throw new Error(`moderateReview error: ${error.message}`);
  }
}

/** Latest ingestion runs for operations monitoring, newest first. */
export async function listIngestionRuns(
  client: AdminClient,
  limit = 5
): Promise<IngestionRun[]> {
  const { data, error } = await client
    .from("ingestion_runs")
    .select(
      "id,source_name,scope,state,started_at,duration_seconds,records_fetched,records_accepted,stations_persisted,error_summary"
    )
    .order("started_at", { ascending: false })
    .limit(limit);
  if (error) {
    throw new Error(`listIngestionRuns error: ${error.message}`);
  }
  return ((data ?? []) as any[]).map((r) => ({
    id: String(r.id),
    sourceName: String(r.source_name),
    scope: String(r.scope),
    state: String(r.state),
    startedAt: typeof r.started_at === "string" ? r.started_at : null,
    durationSeconds: r.duration_seconds != null ? Number(r.duration_seconds) : null,
    recordsFetched: Number(r.records_fetched ?? 0),
    recordsAccepted: Number(r.records_accepted ?? 0),
    stationsPersisted: Number(r.stations_persisted ?? 0),
    errorSummary:
      typeof r.error_summary === "string" && r.error_summary.length > 0 ? r.error_summary : null,
  }));
}

/** Exact count of approved (published) reviews. Null when unmeasurable. */
export async function countApprovedReviews(client: AdminClient): Promise<number | null> {
  const { count, error } = await client
    .from("reviews")
    .select("id", { count: "exact", head: true })
    .eq("moderation_status", "approved");
  if (error) return null;
  return count ?? 0;
}
