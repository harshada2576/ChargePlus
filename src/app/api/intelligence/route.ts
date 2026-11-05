import { NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";
import { checkRateLimit, clientKey } from "@/lib/rateLimit";
import { ML_GATE_THRESHOLDS } from "@/lib/ml";

export const dynamic = "force-dynamic";

const RATE_LIMIT = { limit: 120, windowMs: 60_000 };

function safeParseJson<T>(filePath: string): T | null {
  try {
    if (!fs.existsSync(filePath)) return null;
    const content = fs.readFileSync(filePath, "utf-8");
    return JSON.parse(content) as T;
  } catch {
    // Malformed JSON or unreadable file returns null safely without path exposure
    return null;
  }
}

export async function GET(request: Request) {
  const rate = checkRateLimit(clientKey(request), RATE_LIMIT);
  if (!rate.allowed) {
    return NextResponse.json({ ok: false, error: "Rate limit exceeded" }, { status: 429 });
  }

  try {
    const dataDir = path.resolve(process.cwd(), "data", "ml");

    // 1. Spatial DBSCAN summary with validation
    const spatialRaw = safeParseJson<any>(path.join(dataDir, "spatial_mining_summary.json"));
    let spatialMining = null;
    if (
      spatialRaw &&
      typeof spatialRaw === "object" &&
      spatialRaw.summary &&
      typeof spatialRaw.summary.total_stations === "number" &&
      Array.isArray(spatialRaw.clusters)
    ) {
      spatialMining = spatialRaw;
      if (!spatialMining.top_coverage_gaps) {
        spatialMining.top_coverage_gaps =
          spatialMining.extreme_isolation_anomalies ||
          spatialMining.coverage_gaps_sample ||
          [];
      }
    }

    // 2. Demand mining summary (K-Means + Random Forest) with validation
    const miningRaw = safeParseJson<any>(path.join(dataDir, "mining_summary.json"));
    let miningSummary = null;
    if (
      miningRaw &&
      typeof miningRaw === "object" &&
      Array.isArray(miningRaw.clusters) &&
      miningRaw.metrics
    ) {
      miningSummary = miningRaw;
    }

    // 3. Offline evaluation report (chronological vs random benchmark) with validation
    const offlineRaw = safeParseJson<any>(path.join(dataDir, "offline_evaluation_report.json"));
    let offlineReport = null;
    if (
      offlineRaw &&
      typeof offlineRaw === "object" &&
      offlineRaw.metadata &&
      offlineRaw.evaluations
    ) {
      offlineReport = offlineRaw;
    }

    return NextResponse.json({
      ok: true,
      timestamp: new Date().toISOString(),
      productionGate: {
        state: "COLD",
        reason: "NO_MODEL",
        policy: "Fail-Closed: Live production predictions require verified Indian CPO streaming telemetry.",
        isPredictionServing: false,
        requiredObservations: ML_GATE_THRESHOLDS.minTotalObservations,
        maxFeatureStalenessHours: ML_GATE_THRESHOLDS.maxFeatureStalenessHours,
        currentRealObservations: 0,
        warmingMinObservations: ML_GATE_THRESHOLDS.warmingMinObservations,
      },
      spatialMining,
      miningSummary,
      offlineReport,
    });
  } catch {
    // Sanitary, non-leaking generic error response
    return NextResponse.json(
      { ok: false, error: "Failed to load intelligence data" },
      { status: 500 }
    );
  }
}
