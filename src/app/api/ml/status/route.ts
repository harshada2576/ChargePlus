import { pool } from "@/db";
import { ML_GATE_THRESHOLDS } from "@/lib/ml";

export const dynamic = "force-dynamic";

interface MaturityEvidence {
  totalRealObservations: number;
  stationsWithObservations: number;
  observationDaysCovered: number;
  latestObservation: string | null;
}

interface ActiveModel {
  model_version: string;
  trained_at: string | null;
  model_mae: number | null;
  baseline_mae: number | null;
  model_beats_baseline: boolean | null;
}

/**
 * GET /api/ml/status — model status + data-maturity gate for product surfaces.
 *
 * Read-only, server-side. Returns whether inference is available, the active
 * model version (if any), and the typed reason when unavailable. Observed
 * station discovery never depends on this endpoint.
 */
export async function GET() {
  const required = {
    min_total_observations: ML_GATE_THRESHOLDS.minTotalObservations,
    min_stations_with_observations: ML_GATE_THRESHOLDS.minStationsWithObservations,
    min_observation_days: ML_GATE_THRESHOLDS.minObservationDays,
    min_observations_per_station: ML_GATE_THRESHOLDS.minObservationsPerStation,
    max_feature_staleness_hours: ML_GATE_THRESHOLDS.maxFeatureStalenessHours,
  };

  let evidence: MaturityEvidence = {
    totalRealObservations: 0,
    stationsWithObservations: 0,
    observationDaysCovered: 0,
    latestObservation: null,
  };
  let activeModel: ActiveModel | null = null;
  let storeError: string | null = null;

  try {
    const maturity = await pool.query(
      `SELECT COUNT(*)::int AS total,
              COUNT(DISTINCT station_id)::int AS stations,
              COUNT(DISTINCT (observed_at AT TIME ZONE 'UTC')::date)::int AS days,
              MAX(observed_at) AS latest
         FROM public.station_observations`,
    );
    const row = maturity.rows[0] as {
      total: number;
      stations: number;
      days: number;
      latest: Date | string | null;
    };
    evidence = {
      totalRealObservations: row.total ?? 0,
      stationsWithObservations: row.stations ?? 0,
      observationDaysCovered: row.days ?? 0,
      latestObservation:
        row.latest instanceof Date
          ? row.latest.toISOString()
          : typeof row.latest === "string"
            ? row.latest
            : null,
    };

    const models = await pool.query(
      `SELECT version_str, trained_at, status, data_maturity
         FROM ml.model_versions
        WHERE status = 'ready'
        ORDER BY trained_at DESC NULLS LAST, created_at DESC
        LIMIT 1`,
    );
    if (models.rows.length > 0) {
      const modelKey = (models.rows[0] as { version_str: string }).version_str;
      const metrics = await pool.query(
        `SELECT metric_name, metric_value, split
           FROM ml.metrics
          WHERE model_key = (
            SELECT model_key FROM ml.model_versions WHERE version_str = $1 LIMIT 1
          )
          AND split = 'validation'`,
        [modelKey],
      );
      const metricMap = new Map(
        (metrics.rows as { metric_name: string; metric_value: string | null }[]).map(
          (m) => [m.metric_name, m.metric_value === null ? null : Number(m.metric_value)],
        ),
      );
      const m = models.rows[0] as {
        version_str: string;
        trained_at: Date | string | null;
      };
      activeModel = {
        model_version: m.version_str,
        trained_at:
          m.trained_at instanceof Date
            ? m.trained_at.toISOString()
            : typeof m.trained_at === "string"
              ? m.trained_at
              : null,
        model_mae: metricMap.get("mae") ?? null,
        baseline_mae: metricMap.get("baseline_mae") ?? null,
        model_beats_baseline:
          metricMap.get("mae") !== undefined &&
          metricMap.get("baseline_mae") !== undefined &&
          metricMap.get("mae") !== null &&
          metricMap.get("baseline_mae") !== null
            ? (metricMap.get("mae") as number) < (metricMap.get("baseline_mae") as number)
            : null,
      };
    }
  } catch (err) {
    // Fail-closed: an unreachable store is reported honestly, never as a model.
    storeError = err instanceof Error ? err.message : String(err);
  }

  const failedCriteria: string[] = [];
  if (evidence.totalRealObservations < required.min_total_observations) {
    failedCriteria.push("insufficient_observations");
  }
  if (evidence.stationsWithObservations < required.min_stations_with_observations) {
    failedCriteria.push("insufficient_station_coverage");
  }
  if (evidence.observationDaysCovered < required.min_observation_days) {
    failedCriteria.push("insufficient_temporal_coverage");
  }
  let stale = false;
  if (evidence.latestObservation) {
    const ageHours =
      (Date.now() - new Date(evidence.latestObservation).getTime()) / 3600000;
    if (ageHours > required.max_feature_staleness_hours) {
      failedCriteria.push("stale_features");
      stale = true;
    }
  } else if (evidence.totalRealObservations === 0) {
    failedCriteria.push("no_observations");
  }

  const gatePassed = failedCriteria.length === 0;
  const warming =
    !gatePassed &&
    evidence.totalRealObservations >= ML_GATE_THRESHOLDS.warmingMinObservations &&
    evidence.stationsWithObservations >= ML_GATE_THRESHOLDS.warmingMinStations &&
    evidence.observationDaysCovered >= ML_GATE_THRESHOLDS.warmingMinDays;
  const state = gatePassed ? "READY" : warming ? "WARMING" : "COLD";

  let reason: string | null = null;
  if (!gatePassed) {
    reason = state === "WARMING" ? "DATA_MATURITY_WARMING" : "DATA_MATURITY_COLD";
    if (stale && evidence.totalRealObservations > 0) reason = "STALE_FEATURES";
  } else if (!activeModel) {
    reason = "NO_MODEL";
  }

  return Response.json({
    inference_available: gatePassed && activeModel !== null && storeError === null,
    reason,
    state,
    gate: { passed: gatePassed, failed_criteria: failedCriteria, evidence, required },
    active_model: activeModel,
    ...(storeError ? { store_error: "status store unreachable; reporting unavailable" } : {}),
  });
}
