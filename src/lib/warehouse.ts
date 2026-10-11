/**
 * Warehouse analytics client (Phase 4.7).
 *
 * Fetches the admin-only warehouse summary from the server route, which
 * enforces the admin role itself. The browser never touches analytics
 * tables directly (RLS denies client roles) and never sees credentials.
 * All metrics are counts; no PII flows through this surface.
 */

export type WarehouseSummary = {
  stationsCurrent: number;
  stationVersions: number;
  connectors: number;
  connectorsUnknownPower: number;
  operators: number;
  sources: number;
  observations: number;
  reports: number;
  reviews: number;
  dailyRows: number;
  observedStations: number;
  latestObservedAt: string | null;
  maturity: { cold: number; warming: number; ready: number };
};

export type WarehouseClient = {
  auth: {
    getSession: () => Promise<{
      data: { session: { access_token: string } | null };
    }>;
  };
};

/** Load the warehouse summary; throws a safe message on any failure. */
export async function fetchWarehouseSummary(
  client: WarehouseClient,
  fetcher: typeof fetch = fetch
): Promise<WarehouseSummary> {
  const { data } = await client.auth.getSession();
  const token = data.session?.access_token;
  if (!token) {
    throw new Error("A signed-in admin session is required.");
  }
  let res: Response;
  try {
    res = await fetcher("/api/admin/warehouse", {
      headers: { authorization: `Bearer ${token}` },
    });
  } catch {
    throw new Error("Warehouse analytics failed to load.");
  }
  if (!res.ok) {
    if (res.status === 401) throw new Error("A signed-in admin session is required.");
    if (res.status === 403) throw new Error("Restricted to operations admins.");
    throw new Error("Warehouse analytics failed to load.");
  }
  const body = (await res.json()) as Partial<WarehouseSummary>;
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
  return {
    stationsCurrent: num(body.stationsCurrent),
    stationVersions: num(body.stationVersions),
    connectors: num(body.connectors),
    connectorsUnknownPower: num(body.connectorsUnknownPower),
    operators: num(body.operators),
    sources: num(body.sources),
    observations: num(body.observations),
    reports: num(body.reports),
    reviews: num(body.reviews),
    dailyRows: num(body.dailyRows),
    observedStations: num(body.observedStations),
    latestObservedAt:
      typeof body.latestObservedAt === "string" ? body.latestObservedAt : null,
    maturity: {
      cold: num(body.maturity?.cold),
      warming: num(body.maturity?.warming),
      ready: num(body.maturity?.ready),
    },
  };
}
