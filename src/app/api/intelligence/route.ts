import { NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";
import { checkRateLimit, clientKey } from "@/lib/rateLimit";

export const dynamic = "force-dynamic";

const RATE_LIMIT = { limit: 120, windowMs: 60_000 };

export async function GET(request: Request) {
  const rate = checkRateLimit(clientKey(request), RATE_LIMIT);
  if (!rate.allowed) {
    return NextResponse.json({ ok: false, error: "Rate limit exceeded" }, { status: 429 });
  }

  try {
    const dataDir = path.resolve(process.cwd(), "data", "ml");

    // 1. Spatial DBSCAN summary
    const spatialPath = path.join(dataDir, "spatial_mining_summary.json");
    let spatialMining = null;
    if (fs.existsSync(spatialPath)) {
      spatialMining = JSON.parse(fs.readFileSync(spatialPath, "utf-8"));
    }

    // 2. Demand mining summary (K-Means + Random Forest)
    const miningSummaryPath = path.join(dataDir, "mining_summary.json");
    let miningSummary = null;
    if (fs.existsSync(miningSummaryPath)) {
      miningSummary = JSON.parse(fs.readFileSync(miningSummaryPath, "utf-8"));
    }

    // 3. Offline evaluation report (chronological vs random benchmark)
    const offlineReportPath = path.join(dataDir, "offline_evaluation_report.json");
    let offlineReport = null;
    if (fs.existsSync(offlineReportPath)) {
      offlineReport = JSON.parse(fs.readFileSync(offlineReportPath, "utf-8"));
    }

    return NextResponse.json({
      ok: true,
      timestamp: new Date().toISOString(),
      productionGate: {
        state: "COLD",
        reason: "NO_MODEL",
        policy: "Fail-Closed: Live production predictions require verified Indian CPO streaming telemetry.",
        isPredictionServing: false,
      },
      spatialMining,
      miningSummary,
      offlineReport,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Failed to load intelligence data";
    return NextResponse.json({ ok: false, error: message }, { status: 500 });
  }
}
