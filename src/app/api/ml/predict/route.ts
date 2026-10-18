import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mlArtifactDir, pythonBin, validatePredictInput, validatePredictResult } from "@/lib/ml";
import { checkRateLimit, clientKey } from "@/lib/rateLimit";

export const dynamic = "force-dynamic";

const execFileAsync = promisify(execFile);

// Each request spawns a Python subprocess; cap per-client rate so inference
// cannot be used as a process-spawning amplifier. Mirrors the health route.
const PREDICT_RATE_LIMIT = { limit: 60, windowMs: 60_000 };

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
  // A prediction request is a few hundred bytes of features; refuse
  // oversized bodies before parsing so a flood cannot exhaust memory on the
  // way to a subprocess-spawning endpoint.
  const declaredLength = Number(request.headers.get("content-length") ?? 0);
  if (Number.isFinite(declaredLength) && declaredLength > 65_536) {
    return Response.json(
      { success: false, reason: "FEATURE_SCHEMA_MISMATCH", message: "Request body too large." },
      { status: 413 },
    );
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json(
      { success: false, reason: "FEATURE_SCHEMA_MISMATCH", message: "Body must be valid JSON." },
      { status: 400 },
    );
  }
  // Backstop for chunked bodies without a declared length: a prediction
  // request is a few hundred bytes of features.
  if (JSON.stringify(body)?.length > 65_536) {
    return Response.json(
      { success: false, reason: "FEATURE_SCHEMA_MISMATCH", message: "Request body too large." },
      { status: 413 },
    );
  }

  const rate = checkRateLimit(clientKey(request), PREDICT_RATE_LIMIT);
  if (!rate.allowed) {
    return Response.json(
      { success: false, reason: "NO_MODEL", message: "Too many requests. Retry shortly." },
      { status: 429 },
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
    if (result.success === true) {
      // Trust boundary: the out-of-process CLI result must satisfy the
      // serving contract before it is returned as a prediction.
      const checked = validatePredictResult(result);
      if (!checked.ok) {
        return Response.json(
          { success: false, reason: checked.reason, message: checked.message },
          { status: 502 },
        );
      }
      return Response.json({
        ...result,
        probability: checked.value.probability,
        model_version: checked.value.modelVersion,
      });
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
