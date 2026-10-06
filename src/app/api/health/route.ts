import { db } from "@/db";
import { sql } from "drizzle-orm";
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
  try {
    await db.execute(sql`select 1`);
    return Response.json({ ok: true });
  } catch {
    serverLog("error", "health.db_unreachable", {});
    return Response.json({ ok: false }, { status: 500 });
  }
}
