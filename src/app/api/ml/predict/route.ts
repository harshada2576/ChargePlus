import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mlArtifactDir, pythonBin, validatePredictInput } from "@/lib/ml";

export const dynamic = "force-dynamic";

const execFileAsync = promisify(execFile);

/**
 * POST /api/ml/predict — busy-probability inference via the approved model.
 *
 * Body: { features: {hour_of_day, day_of_week, is_weekend, month,
 *         station_connector_count?}, latest_observation_at?: ISO string }
 *
 * The Python CLI (backend/ml/cli.py) does the scoring; this route validates
 * input, enforces a timeout, and passes the typed result through. Without an
 * approved model it returns success:false with a typed reason (HTTP 200 —
 * "no prediction" is a valid answer, not a server error). Station discovery
 * never depends on this endpoint.
 *
 * Server-side only: artifact directory and Python runtime never reach clients.
 */
export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json(
      { success: false, reason: "FEATURE_SCHEMA_MISMATCH", message: "Body must be valid JSON." },
      { status: 400 },
    );
  }

  const validated = validatePredictInput(body);
  if (!validated.ok) {
    return Response.json(
      { success: false, reason: validated.reason, message: validated.message },
      { status: 400 },
    );
  }

  const cliArgs = [
    "-m",
    "backend.ml.cli",
    "predict",
    "--artifact-dir",
    mlArtifactDir(),
    "--features",
    JSON.stringify(validated.features),
  ];
  if (validated.latestObservationAt) {
    cliArgs.push("--latest-observation-at", validated.latestObservationAt);
  }

  try {
    const { stdout } = await execFileAsync(pythonBin(), cliArgs, {
      timeout: 20000,
      maxBuffer: 1024 * 1024,
      cwd: process.cwd(),
    });
    const result = JSON.parse(stdout) as Record<string, unknown>;
    if (typeof result.success !== "boolean") {
      throw new Error("Inference CLI returned a malformed payload.");
    }
    return Response.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // Missing Python runtime or missing registry both mean the same honest
    // thing to callers: no prediction is available right now.
    const isTimeout =
      typeof err === "object" && err !== null && "killed" in err &&
      (err as { killed?: boolean }).killed === true;
    return Response.json(
      {
        success: false,
        reason: "NO_MODEL",
        message: isTimeout
          ? "Inference timed out; no prediction available."
          : `Inference backend unavailable (${message.slice(0, 200)}); no prediction available.`,
      },
      { status: 503 },
    );
  }
}
