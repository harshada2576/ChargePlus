/**
 * Community reports against public.user_reports (Step 3.9).
 *
 * Reports are append-only observations: each submission is an event row, never
 * an overwrite of station facts. Moderation stays server-side — inserts must
 * leave moderation columns at their pending defaults (RLS rejects anything
 * else). Lists return only the caller's own rows (RLS); admins are out of
 * scope for this client path.
 */

export type ReportStatus = "available" | "busy" | "broken";
export type ReportQueue = "none" | "short" | "medium" | "long";

export type ReportInput = {
  userId: string;
  stationId: string;
  status: ReportStatus;
  queue: ReportQueue;
  note?: string;
};

export type ReportRecord = {
  id: string;
  stationId: string;
  /** Includes "unknown": other writers may record it; never coerced to busy. */
  status: ReportStatus | "unknown";
  queue: ReportQueue | "unknown";
  note: string | null;
  submittedAt: string | null;
  moderationStatus: string | null;
};

export type ReportsClient = {
  from: (table: string) => any;
};

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STATUSES: ReportStatus[] = ["available", "busy", "broken"];
const QUEUES: ReportQueue[] = ["none", "short", "medium", "long"];

/** Validate a report before it touches the network. Throws on defect. */
export function validateReport(input: ReportInput): {
  userId: string;
  stationId: string;
  status: ReportStatus;
  queue: ReportQueue;
  comment: string | null;
} {
  if (!input.userId) {
    throw new Error("A signed-in user is required to report.");
  }
  if (!UUID_RE.test(input.stationId)) {
    throw new Error("A valid station is required to report.");
  }
  if (!STATUSES.includes(input.status)) {
    throw new Error("Choose the station status you observed.");
  }
  if (!QUEUES.includes(input.queue)) {
    throw new Error("Choose a valid queue level.");
  }
  const comment = (input.note ?? "").trim().slice(0, 300) || null;
  return { userId: input.userId, stationId: input.stationId, status: input.status, queue: input.queue, comment };
}

/**
 * Persist one observation. Success is reported only after the server confirms
 * the insert; the row enters moderation as pending and never mutates station
 * facts. Append-only by design: retries create separate rows only if the first
 * actually persisted — callers must disable submit while in flight.
 */
export async function submitReport(
  client: ReportsClient,
  input: ReportInput,
  observedAt: string = new Date().toISOString()
): Promise<ReportRecord> {
  const row = validateReport(input);
  const { data, error } = await client
    .from("user_reports")
    .insert({
      user_id: row.userId,
      station_id: row.stationId,
      availability_status: row.status,
      queue_level: row.queue,
      comment: row.comment,
      observed_at: observedAt,
    })
    .select("id,station_id,availability_status,queue_level,comment,created_at,moderation_status")
    .maybeSingle();
  if (error || !data) {
    throw new Error(`submitReport error: ${error?.message ?? "no record returned"}`);
  }
  return toRecord(data);
}

/** Newest-first list of the caller's own reports. */
export async function listReports(
  client: ReportsClient,
  userId: string
): Promise<ReportRecord[]> {
  if (!userId) return [];
  const { data, error } = await client
    .from("user_reports")
    .select("id,station_id,availability_status,queue_level,comment,created_at,moderation_status")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) {
    throw new Error(`listReports error: ${error.message}`);
  }
  return ((data ?? []) as any[]).map(toRecord);
}

function toRecord(row: any): ReportRecord {
  const statuses = [...STATUSES, "unknown"] as const;
  const status: ReportRecord["status"] = (statuses as readonly string[]).includes(
    row.availability_status
  )
    ? row.availability_status
    : "unknown";
  const queues = [...QUEUES, "unknown"] as const;
  const queue: ReportRecord["queue"] = (queues as readonly string[]).includes(row.queue_level)
    ? row.queue_level
    : "unknown";
  return {
    id: String(row.id),
    stationId: String(row.station_id),
    status,
    queue,
    note: typeof row.comment === "string" && row.comment.length > 0 ? row.comment : null,
    submittedAt: typeof row.created_at === "string" ? row.created_at : null,
    moderationStatus: typeof row.moderation_status === "string" ? row.moderation_status : null,
  };
}
