import { checkRateLimit, clientKey } from "@/lib/rateLimit";
import {
  executeOlapRollup,
  executeOlapDrilldown,
  executeOlapSlice,
  executeOlapDice,
  executeOlapCube,
  executeOlapWindowRanking,
  type OlapOperation,
} from "@/lib/olap";

export const dynamic = "force-dynamic";

const RATE_LIMIT = { limit: 120, windowMs: 60_000 };

export async function GET(request: Request) {
  const rate = checkRateLimit(clientKey(request), RATE_LIMIT);
  if (!rate.allowed) {
    return Response.json({ ok: false, error: "Rate limit exceeded" }, { status: 429 });
  }

  const { searchParams } = new URL(request.url);
  const op = (searchParams.get("op") || "rollup") as OlapOperation;

  try {
    switch (op) {
      case "rollup": {
        const mode = searchParams.get("mode") === "calendar" ? "calendar" : "weekly";
        const result = await executeOlapRollup(mode);
        return Response.json({ ok: true, result });
      }
      case "drilldown": {
        const city = searchParams.get("city") || "Mumbai";
        const locality = searchParams.get("locality") || undefined;
        const result = await executeOlapDrilldown(city, locality);
        return Response.json({ ok: true, result });
      }
      case "slice": {
        const operator = searchParams.get("operator") || "Tata Power";
        const result = await executeOlapSlice(operator);
        return Response.json({ ok: true, result });
      }
      case "dice": {
        const opsParam = searchParams.get("operators");
        const locsParam = searchParams.get("localities");
        const dayType = (searchParams.get("dayType") as "all" | "weekend" | "weekday") || "all";
        const operators = opsParam ? opsParam.split(",") : ["Tata Power", "Jio-bp"];
        const localities = locsParam ? locsParam.split(",") : ["Bandra Kurla Complex", "Lower Parel"];
        const result = await executeOlapDice(operators, localities, dayType);
        return Response.json({ ok: true, result });
      }
      case "cube": {
        const result = await executeOlapCube();
        return Response.json({ ok: true, result });
      }
      case "window_ranking": {
        const topN = parseInt(searchParams.get("topN") || "3", 10);
        const result = await executeOlapWindowRanking(isNaN(topN) ? 3 : topN);
        return Response.json({ ok: true, result });
      }
      default: {
        return Response.json(
          { ok: false, error: `Invalid operation: ${op}` },
          { status: 400 }
        );
      }
    }
  } catch {
    return Response.json(
      { ok: false, error: "Failed to execute OLAP query" },
      { status: 500 }
    );
  }
}
