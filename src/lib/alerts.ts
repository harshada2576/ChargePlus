/**
 * Watch-condition alerts against public.alerts (Step 3.11).
 *
 * The UI offers two toggles per saved station; they map to canonical alert
 * types explicitly (never invented): "available" → station_available,
 * "lessBusy" → congestion_threshold. Rows persist the *preference* only —
 * there is no delivery mechanism yet (schema comment, notification deferred),
 * and nothing here claims a notification was sent.
 *
 * Station-scoped rows are unique per (user, station, type) at the
 * database layer (uq_alerts_user_station_type, pre-Phase-4 R7), so writes
 * are list-then-write with 23505 recovery: update the matching row,
 * insert when absent, and on a concurrent-insert race re-read and update
 * the winner. Callers still serialize toggles per station (pending lock)
 * to keep the common path race-free.
 */

export type UiAlertType = "available" | "lessBusy";
export type DbAlertType =
  | "station_available"
  | "station_status_change"
  | "congestion_threshold"
  | "nearby_station_change";

export type AlertRecord = {
  id: string;
  stationId: string | null;
  uiType: UiAlertType | null;
  enabled: boolean;
};

export type AlertsClient = {
  from: (table: string) => any;
};

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const UI_TO_DB: Record<UiAlertType, DbAlertType> = {
  available: "station_available",
  lessBusy: "congestion_threshold",
};

const DB_TO_UI: Partial<Record<DbAlertType, UiAlertType>> = {
  station_available: "available",
  congestion_threshold: "lessBusy",
};

export function toDbAlertType(ui: UiAlertType): DbAlertType {
  return UI_TO_DB[ui];
}

export function toUiAlertType(db: string | null | undefined): UiAlertType | null {
  if (!db) return null;
  return DB_TO_UI[db as DbAlertType] ?? null;
}

/** The caller's own alert rows, newest first. */
export async function listAlerts(
  client: AlertsClient,
  userId: string
): Promise<AlertRecord[]> {
  if (!userId) return [];
  const { data, error } = await client
    .from("alerts")
    .select("id,station_id,alert_type,is_enabled")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) {
    throw new Error(`listAlerts error: ${error.message}`);
  }
  return ((data ?? []) as any[]).map((r) => ({
    id: String(r.id),
    stationId: typeof r.station_id === "string" ? r.station_id : null,
    uiType: toUiAlertType(r.alert_type),
    enabled: r.is_enabled === true,
  }));
}

/**
 * Set one watch condition. Updates the matching row or inserts it; enabling an
 * already-enabled (or disabling an already-absent) condition is a no-op
 * success. Only whitelisted columns are written; user scoping is enforced by
 * RLS on top of the explicit userId parameter.
 */
export async function setAlert(
  client: AlertsClient,
  input: { userId: string; stationId: string; uiType: UiAlertType; enabled: boolean },
  existing: AlertRecord[] | null = null
): Promise<AlertRecord> {
  if (!input.userId) {
    throw new Error("A signed-in user is required for alerts.");
  }
  if (!UUID_RE.test(input.stationId)) {
    throw new Error("A valid station is required for alerts.");
  }
  const dbType = toDbAlertType(input.uiType);
  const known = existing ?? (await listAlerts(client, input.userId));
  const match = known.find((a) => a.stationId === input.stationId && a.uiType === input.uiType);

  if (match) {
    if (match.enabled === input.enabled) return { ...match, enabled: input.enabled };
    const { error } = await client
      .from("alerts")
      .update({ is_enabled: input.enabled, updated_at: new Date().toISOString() })
      .eq("id", match.id)
      .eq("user_id", input.userId);
    if (error) {
      throw new Error(`setAlert error: ${error.message}`);
    }
    return { ...match, enabled: input.enabled };
  }

  if (!input.enabled) {
    // Disabling a condition that was never configured: nothing to persist.
    return { id: "", stationId: input.stationId, uiType: input.uiType, enabled: false };
  }
  const { data, error } = await client
    .from("alerts")
    .insert({
      user_id: input.userId,
      station_id: input.stationId,
      alert_type: dbType,
      params: {},
      is_enabled: true,
    })
    .select("id,station_id,alert_type,is_enabled")
    .maybeSingle();
  if (error && (error as { code?: string }).code === "23505") {
    // Concurrent insert won the race for (user, station, type):
    // re-read and update the winning row instead of duplicating it.
    const raced = await listAlerts(client, input.userId);
    const winner = raced.find(
      (a) => a.stationId === input.stationId && a.uiType === input.uiType
    );
    if (!winner || !winner.id) {
      throw new Error(`setAlert error: ${error.message}`);
    }
    return setAlert(client, input, raced);
  }
  if (error || !data) {
    throw new Error(`setAlert error: ${error?.message ?? "no record returned"}`);
  }
  return {
    id: String((data as any).id),
    stationId: input.stationId,
    uiType: input.uiType,
    enabled: true,
  };
}
