import { createClient } from "@supabase/supabase-js";
import { pool } from "@/db";
import { checkRateLimit, credentialKey } from "@/lib/rateLimit";
import { newRequestId, serverLog } from "@/lib/serverLog";

export const dynamic = "force-dynamic";

// Abuse friction: 60 requests/minute per credential (in-memory, per instance).
const WAREHOUSE_RATE_LIMIT = { limit: 60, windowMs: 60_000 };

/**
 * Admin-only warehouse summary (Phase 4.7).
 *
 * Authorization is enforced HERE, server-side: the caller presents its
 * Supabase session access token; the service-role client validates it and
 * the canonical profiles.role must be 'admin'. The DATABASE_URL pool runs
 * as a privileged role (bypasses RLS), so this route must never be reachable
 * without the admin check below. Responses carry counts only — no PII,
 * no review/report text, no user IDs, no credentials.
 */
export async function GET(request: Request) {
  const requestId = newRequestId();
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceKey) {
    return Response.json(
      { error: "Warehouse analytics is not configured." },
      { status: 503 }
    );
  }

  const authHeader = request.headers.get("authorization") ?? "";
  const token = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : "";
  if (!token) {
    return Response.json({ error: "Sign-in required." }, { status: 401 });
  }
  const rate = checkRateLimit(credentialKey(request), WAREHOUSE_RATE_LIMIT);
  if (!rate.allowed) {
    return Response.json(
      { error: "Too many requests. Retry shortly." },
      { status: 429, headers: { "retry-after": String(Math.ceil(rate.retryAfterMs / 1000)) } }
    );
  }

  try {
    const admin = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const { data: userData, error: userError } = await admin.auth.getUser(token);
    const userId = userData?.user?.id;
    if (userError || !userId) {
      return Response.json({ error: "Invalid session." }, { status: 401 });
    }
    const { data: profile, error: profileError } = await admin
      .from("profiles")
      .select("role")
      .eq("id", userId)
      .maybeSingle();
    if (profileError || (profile as { role?: string } | null)?.role !== "admin") {
      return Response.json({ error: "Restricted." }, { status: 403 });
    }

    const { rows } = await pool.query(
      `SELECT
         (SELECT count(*) FROM analytics.dim_station WHERE is_current) AS stations_current,
         (SELECT count(*) FROM analytics.dim_station) AS station_versions,
         (SELECT count(*) FROM analytics.dim_connector) AS connectors,
         (SELECT count(*) FROM analytics.dim_connector WHERE power_kw IS NULL) AS connectors_unknown_power,
         (SELECT count(*) FROM analytics.dim_operator) AS operators,
         (SELECT count(*) FROM analytics.dim_source) AS sources,
         (SELECT count(*) FROM analytics.fact_station_observation) AS observations,
         (SELECT count(*) FROM analytics.fact_user_report) AS reports,
         (SELECT count(*) FROM analytics.fact_review) AS reviews,
         (SELECT count(*) FROM analytics.fact_station_daily) AS daily_rows,
         (SELECT count(DISTINCT station_key) FROM analytics.fact_station_observation) AS observed_stations,
         (SELECT max(observed_at) FROM analytics.fact_station_observation) AS latest_observed_at,
         (SELECT count(*) FROM analytics.fact_station_daily WHERE maturity = 'cold') AS maturity_cold,
         (SELECT count(*) FROM analytics.fact_station_daily WHERE maturity = 'warming') AS maturity_warming,
         (SELECT count(*) FROM analytics.fact_station_daily WHERE maturity = 'ready') AS maturity_ready`
    );
    const r = rows[0] as Record<string, string | null>;
    const num = (v: string | null) => (v == null ? 0 : Number(v));
    return Response.json({
      stationsCurrent: num(r.stations_current),
      stationVersions: num(r.station_versions),
      connectors: num(r.connectors),
      connectorsUnknownPower: num(r.connectors_unknown_power),
      operators: num(r.operators),
      sources: num(r.sources),
      observations: num(r.observations),
      reports: num(r.reports),
      reviews: num(r.reviews),
      dailyRows: num(r.daily_rows),
      observedStations: num(r.observed_stations),
      latestObservedAt: r.latest_observed_at,
      maturity: {
        cold: num(r.maturity_cold),
        warming: num(r.maturity_warming),
        ready: num(r.maturity_ready),
      },
    });
  } catch {
    serverLog("error", "admin.warehouse.failed", { requestId });
    return Response.json(
      { error: "Warehouse analytics failed to load." },
      { status: 500 }
    );
  }
}
