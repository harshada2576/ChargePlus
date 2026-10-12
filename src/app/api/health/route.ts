import { pool } from "@/db";

import { checkRateLimit, clientKey } from "@/lib/rateLimit";
import { serverLog } from "@/lib/serverLog";

export const dynamic = "force-dynamic";

// Generous ceiling so health checks and normal browsing never trip;
// floods still get a 429 instead of unbounded database pings.
const HEALTH_RATE_LIMIT = { limit: 300, windowMs: 60_000 };

export async function GET(request: Request) {
  const rate = checkRateLimit(clientKey(request), HEALTH_RATE_LIMIT);
  if (!rate.allowed) {
    return Response.json({ ok: false, throttled: true }, { status: 429 });
  }
  const mode = process.env.NEXT_PUBLIC_DEMO_MODE === "true" ? "demo" : "production";
  try {
    await pool.query("select 1");
    return Response.json({ ok: true, status: "healthy", mode, database: "connected" });
  } catch (err) {
    serverLog("error", "health.db_unreachable", { error: err instanceof Error ? err.message : String(err) });
    return Response.json(
      {
        ok: false,
        status: "unhealthy",
        mode,
        database: "disconnected",
        error: "Database unreachable or DATABASE_URL unconfigured",
      },
      { status: 503 }
    );
  }
}
