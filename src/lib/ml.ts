/**
 * ChargePlus ML API helpers (server-side only).
 *
 * Pure validation/mapping for the /api/ml/* routes. Actual inference runs in
 * Python (backend/ml); these routes never fabricate predictions and never
 * expose model internals, artifacts, or service credentials to clients.
 *
 * Maturity thresholds below MIRROR backend/ml/gates.py MLGateConfig. The
 * Python gate is the source of truth; keep both in sync if thresholds change.
 */

export const ML_GATE_THRESHOLDS = {
  minTotalObservations: 500,
  minStationsWithObservations: 5,
  minObservationDays: 30,
  minObservationsPerStation: 50,
  maxFeatureStalenessHours: 72,
  warmingMinObservations: 50,
  warmingMinStations: 2,
  warmingMinDays: 7,
} as const;

export const ML_FEATURE_NAMES = [
  "hour_of_day",
  "day_of_week",
  "is_weekend",
  "month",
  "station_connector_count",
] as const;

export type MlFeatureName = (typeof ML_FEATURE_NAMES)[number];

export interface MlFeatures {
  hour_of_day: number;
  day_of_week: number;
  is_weekend: number;
  month: number;
  station_connector_count?: number | null;
}

export type MlUnavailableReason =
  | "NO_MODEL"
  | "INSUFFICIENT_HISTORY"
  | "STALE_FEATURES"
  | "FEATURE_SCHEMA_MISMATCH"
  | "MODEL_ARTIFACT_INVALID"
  | "DATA_MATURITY_COLD"
  | "DATA_MATURITY_WARMING"
  | "TRAINING_IN_PROGRESS";

export interface PredictRequestBody {
  features: Partial<Record<MlFeatureName, unknown>>;
  latest_observation_at?: unknown;
  station_id?: unknown;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * Validates a predict request body. Returns sanitized features (known keys
 * only) or a typed refusal. Never throws on malformed input.
 */
export function validatePredictInput(body: unknown): {
  ok: true;
  features: MlFeatures;
  latestObservationAt: string | null;
} | {
  ok: false;
  reason: MlUnavailableReason;
  message: string;
} {
  if (typeof body !== "object" || body === null) {
    return {
      ok: false,
      reason: "FEATURE_SCHEMA_MISMATCH",
      message: "Request body must be a JSON object with 'features'.",
    };
  }
  const { features, latest_observation_at: rawCutoff } = body as PredictRequestBody;
  if (typeof features !== "object" || features === null) {
    return {
      ok: false,
      reason: "FEATURE_SCHEMA_MISMATCH",
      message: `Required feature fields: ${ML_FEATURE_NAMES.join(", ")}.`,
    };
  }

  const get = (name: MlFeatureName): unknown => features[name];
  const hour = get("hour_of_day");
  const dow = get("day_of_week");
  const weekend = get("is_weekend");
  const month = get("month");
  const count = get("station_connector_count");

  if (
    !isFiniteNumber(hour) || hour < 0 || hour > 23 ||
    !isFiniteNumber(dow) || dow < 0 || dow > 6 ||
    !isFiniteNumber(weekend) || (weekend !== 0 && weekend !== 1) ||
    !isFiniteNumber(month) || month < 1 || month > 12
  ) {
    return {
      ok: false,
      reason: "FEATURE_SCHEMA_MISMATCH",
      message:
        "Invalid time features: hour_of_day in [0,23], day_of_week in [0,6], " +
        "is_weekend in {0,1}, month in [1,12].",
    };
  }
  if (
    count !== undefined && count !== null &&
    (!isFiniteNumber(count) || count < 0)
  ) {
    return {
      ok: false,
      reason: "FEATURE_SCHEMA_MISMATCH",
      message: "station_connector_count must be a number >= 0 when provided.",
    };
  }

  let latestObservationAt: string | null = null;
  if (typeof rawCutoff === "string" && rawCutoff.length > 0) {
    const parsed = new Date(rawCutoff);
    if (Number.isNaN(parsed.getTime())) {
      return {
        ok: false,
        reason: "STALE_FEATURES",
        message: "latest_observation_at is not a valid timestamp.",
      };
    }
    latestObservationAt = parsed.toISOString();
  }

  return {
    ok: true,
    features: {
      hour_of_day: hour,
      day_of_week: dow,
      is_weekend: weekend,
      month,
      ...(count === undefined ? {} : { station_connector_count: count }),
    },
    latestObservationAt,
  };
}

export interface ValidatedPredictResult {
  probability: number;
  modelVersion: string;
}

/**
 * Validates an inference-CLI result payload before it is served as trusted
 * output. The CLI runs out-of-process; its stdout must satisfy the serving
 * contract: success:true requires a finite P(busy) in [0,1] and a non-empty
 * model version. Anything else is refused as MODEL_ARTIFACT_INVALID so an
 * invalid probability can never be mistaken for a reliable prediction.
 * success:false payloads pass through untouched (honest "no prediction").
 * Never throws on malformed input.
 */
export function validatePredictResult(result: unknown): {
  ok: true;
  value: ValidatedPredictResult;
} | {
  ok: false;
  reason: Extract<MlUnavailableReason, "MODEL_ARTIFACT_INVALID">;
  message: string;
} {
  const invalid = (message: string) => ({
    ok: false as const,
    reason: "MODEL_ARTIFACT_INVALID" as const,
    message,
  });
  if (typeof result !== "object" || result === null) {
    return invalid("Inference backend returned a malformed payload.");
  }
  const { success, probability, model_version: modelVersion } =
    result as Record<string, unknown>;
  if (success !== true) {
    // Not a prediction; the route handles unavailable reasons separately.
    return invalid("Inference backend did not return a prediction.");
  }
  if (typeof probability !== "number" || !Number.isFinite(probability)) {
    return invalid("Model emitted a non-finite prediction; refusing to serve it.");
  }
  if (probability < 0 || probability > 1) {
    return invalid(`Model emitted out-of-range probability ${probability}; refusing to serve it.`);
  }
  if (typeof modelVersion !== "string" || modelVersion.length === 0) {
    return invalid("Prediction is missing its model version; refusing to serve it.");
  }
  return { ok: true, value: { probability, modelVersion } };
}

/** Resolves the server-side artifact directory (never client-exposed). */
export function mlArtifactDir(): string {
  return process.env.ML_ARTIFACT_DIR ?? "backend/ml/artifacts";
}

/** Resolves the Python executable for the inference CLI. */
export function pythonBin(): string {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;
  return process.platform === "win32" ? "python" : "python3";
}
