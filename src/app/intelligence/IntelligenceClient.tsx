"use client";

import { useCallback, useEffect, useState } from "react";
import { Link } from "@/i18n/Link";
import { useI18n } from "@/i18n/I18nProvider";
import {
  PinIcon,
  BoltIcon,
  AlertTriangleIcon,
  CheckIcon,
  InfoIcon,
  SortIcon,
  CompassIcon,
  ChevronDownIcon,
  SearchIcon,
} from "@/components/Icon";
import { cx } from "@/lib/util";
import type { OlapOperation, OlapResult } from "@/lib/olap";

/* =========================================================================
   Types matching intelligence and offline mining payloads
   ========================================================================= */

interface SpatialClusterStation {
  id: string;
  name: string;
  operator: string;
  lat: number;
  lng: number;
}

interface SpatialCluster {
  cluster_id: number;
  station_count: number;
  center_lat: number;
  center_lng: number;
  radius_km: number;
  stations: SpatialClusterStation[];
}

interface CoverageGap {
  station_id: string;
  station_name: string;
  nearest_distance_km: number;
  nearest_station_id?: string;
  outlier_score?: number;
  latitude?: number;
  longitude?: number;
}

interface SpatialMiningData {
  metadata: {
    generated_at: string;
    algorithm: string;
    distance_metric: string;
    parameters: {
      eps_km: number;
      min_samples: number;
      isolation_threshold_km: number;
    };
    data_provenance: {
      source: string;
      total_records: number;
      is_synthetic: boolean;
      verification_status: string;
    };
  };
  summary: {
    total_stations: number;
    clustered_stations: number;
    noise_stations: number;
    cluster_count: number;
    coverage_gap_count: number;
    isolated_stations_5km_count?: number;
    extreme_isolation_outliers: number;
    coverage_gaps_sample_size?: number;
  };
  clusters: SpatialCluster[];
  top_coverage_gaps?: CoverageGap[];
  extreme_isolation_anomalies?: CoverageGap[];
  coverage_gaps_sample?: CoverageGap[];
}

interface KMeansCluster {
  cluster_id: number;
  station_count: number;
  avg_demand_score: number;
  avg_lat: number;
  avg_lng: number;
}

interface MiningSummaryData {
  clusters: KMeansCluster[];
  metrics: {
    baseline_mae: number;
    rf_mae: number;
    rf_rmse: number;
    r2_score: number;
    improvement_pct: number;
  };
  feature_importance: Record<string, number>;
}

interface OfflineReportData {
  metadata: {
    generated_at: string;
    pipeline: string;
    is_synthetic_demonstration: boolean;
    is_production_forecast: boolean;
    production_gate_status: string;
    production_gate_policy: string;
  };
  dataset_provenance: {
    source_stations: string;
    source_observations: string;
    station_count: number;
    observation_count: number;
    synthetic_generator: string;
    data_limitations: string;
  };
  evaluations: {
    legacy_random_split_reproduced: {
      description: string;
      notes: string;
      metrics: {
        baseline_mae: number;
        baseline_rmse: number;
        rf_mae: number;
        rf_rmse: number;
        r2_score: number;
        improvement_pct: number;
      };
    };
    honest_chronological_split: {
      description: string;
      train_records: number;
      test_records: number;
      metrics: {
        baseline_mae: number;
        baseline_rmse: number;
        rf_mae: number;
        rf_rmse: number;
        r2_score: number;
        improvement_pct: number;
      };
    };
  };
}

interface IntelligencePayload {
  ok: boolean;
  productionGate: {
    state: string;
    reason: string;
    policy: string;
    isPredictionServing: boolean;
    requiredObservations?: number;
    maxFeatureStalenessHours?: number;
    totalObservations?: number;
    featureStalenessHours?: number;
    currentRealObservations?: number;
    warmingMinObservations?: number;
  };
  spatialMining: SpatialMiningData | null;
  miningSummary: MiningSummaryData | null;
  offlineReport: OfflineReportData | null;
}

type MainTab =
  | "overview"
  | "olap"
  | "spatial"
  | "isolation"
  | "demand"
  | "prediction"
  | "governance";

/* =========================================================================
   Intelligence Client Component
   ========================================================================= */

export function IntelligenceClient() {
  const { t } = useI18n();

  const [activeTab, setActiveTab] = useState<MainTab>("overview");
  const [data, setData] = useState<IntelligencePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Spatial cluster selection
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null);

  // Isolation toggle: 17 Extreme Outliers vs 25 Sampled Stations
  const [isolationView, setIsolationView] = useState<"extreme" | "sample">("extreme");

  // OLAP reactive state
  const [olapOp, setOlapOp] = useState<OlapOperation>("rollup");
  const [rollupMode, setRollupMode] = useState<"weekly" | "calendar">("weekly");
  const [drillLocality, setDrillLocality] = useState<string>("");
  const [sliceOp, setSliceOp] = useState<string>("Tata Power");
  const [diceOps, setDiceOps] = useState<string[]>(["Tata Power", "Jio-bp"]);
  const [diceLocs, setDiceLocs] = useState<string[]>(["Bandra Kurla Complex", "Lower Parel"]);
  const [diceDayType, setDiceDayType] = useState<"all" | "weekday" | "weekend">("all");
  const [windowTopN, setWindowTopN] = useState<number>(3);
  const [olapResult, setOlapResult] = useState<OlapResult | null>(null);
  const [olapLoading, setOlapLoading] = useState<boolean>(false);
  const [showSql, setShowSql] = useState<boolean>(false);

  // Fetch initial intelligence offline summary
  useEffect(() => {
    let unmounted = false;
    async function load() {
      try {
        setLoading(true);
        const res = await fetch("/api/intelligence");
        if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch intelligence data`);
        const json = (await res.json()) as IntelligencePayload;
        if (!unmounted) {
          setData(json);
          if (json.spatialMining?.clusters && json.spatialMining.clusters.length > 0) {
            setSelectedClusterId(json.spatialMining.clusters[0].cluster_id);
          }
        }
      } catch (err: unknown) {
        if (!unmounted) {
          setError(err instanceof Error ? err.message : "Error fetching intelligence data");
        }
      } finally {
        if (!unmounted) setLoading(false);
      }
    }
    load();
    return () => {
      unmounted = true;
    };
  }, []);

  // Fetch OLAP query whenever operation or parameters change
  const fetchOlapData = useCallback(async () => {
    setOlapLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("op", olapOp);

      if (olapOp === "rollup") {
        params.set("mode", rollupMode);
      } else if (olapOp === "drilldown") {
        params.set("city", "Mumbai");
        if (drillLocality) params.set("locality", drillLocality);
      } else if (olapOp === "slice") {
        params.set("operator", sliceOp);
      } else if (olapOp === "dice") {
        params.set("operators", diceOps.join(","));
        params.set("localities", diceLocs.join(","));
        params.set("dayType", diceDayType);
      } else if (olapOp === "window_ranking") {
        params.set("topN", String(windowTopN));
      }

      const res = await fetch(`/api/intelligence/olap?${params.toString()}`);
      if (!res.ok) throw new Error(`OLAP query failed with status ${res.status}`);
      const json = await res.json();
      if (json.ok && json.result) {
        setOlapResult(json.result as OlapResult);
      }
    } catch {
      // Fallback handled safely by server API
    } finally {
      setOlapLoading(false);
    }
  }, [olapOp, rollupMode, drillLocality, sliceOp, diceOps, diceLocs, diceDayType, windowTopN]);

  useEffect(() => {
    let ignore = false;
    if (activeTab === "olap") {
      void Promise.resolve().then(() => {
        if (!ignore) {
          void fetchOlapData();
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [activeTab, fetchOlapData]);

  // Safe CSV export for OLAP result table
  const exportOlapCsv = useCallback(() => {
    if (!olapResult || olapResult.rows.length === 0) return;
    const headers = Object.keys(olapResult.rows[0]);
    const csvRows = [
      headers.join(","),
      ...olapResult.rows.map((row) =>
        headers
          .map((h) => {
            const v = row[h];
            const str = v == null ? "" : String(v);
            return str.includes(",") ? `"${str.replace(/"/g, '""')}"` : str;
          })
          .join(",")
      ),
    ];
    const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `chargeplus_${olapResult.operation}_olap.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [olapResult]);

  if (loading) {
    return (
      <div className="mx-auto max-w-screen-xl px-4 py-12 sm:px-6">
        <div className="flex flex-col gap-4 animate-pulse">
          <div className="h-10 w-96 rounded-lg bg-ink-100" />
          <div className="h-5 w-2/3 rounded-md bg-ink-50" />
          <div className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="h-28 rounded-xl bg-ink-100" />
            <div className="h-28 rounded-xl bg-ink-100" />
            <div className="h-28 rounded-xl bg-ink-100" />
            <div className="h-28 rounded-xl bg-ink-100" />
          </div>
          <div className="mt-8 h-96 rounded-xl bg-ink-100" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-16 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-rose-50 text-rose-600">
          <AlertTriangleIcon size={28} />
        </div>
        <h2 className="mt-4 text-xl font-semibold text-ink-900">Unable to Load Intelligence Data</h2>
        <p className="mt-2 text-sm text-ink-600">{error || "Failed to load offline experiment outputs."}</p>
        <button
          onClick={() => window.location.reload()}
          className="mt-6 inline-flex h-11 items-center rounded-full bg-coral-600 px-6 text-sm font-semibold text-ink-900 shadow-sm hover:bg-coral-700 active:bg-coral-700 transition"
        >
          Try Again
        </button>
      </div>
    );
  }

  const { spatialMining, miningSummary, offlineReport, productionGate } = data;
  const selectedCluster = spatialMining?.clusters.find((c) => c.cluster_id === selectedClusterId);

  return (
    <div className="mx-auto max-w-screen-xl px-4 py-8 sm:px-6">
      {/* Editorial Landing Header */}
      <div className="flex flex-col gap-3 border-b border-ink-200/80 pb-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-300/80 bg-emerald-50/70 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
            <CheckIcon size={12} className="text-emerald-700" />
            {spatialMining?.summary.total_stations != null
              ? `${spatialMining.summary.total_stations} Authentic Stations (India Snapshot)`
              : "Dataset Offline"}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-purple-200 bg-purple-50 px-2.5 py-0.5 text-xs font-semibold text-purple-900">
            <CompassIcon size={12} className="text-purple-700" />
            DBSCAN Haversine (ε=2km, min=3)
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-900">
            <SortIcon size={12} className="text-blue-700" />
            Kimball Star Schema (DWDM OLAP)
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-900">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
            ML Gate: {productionGate.state} (Fail-Closed)
          </span>
        </div>

        <h1 className="font-editorial text-3xl font-normal tracking-tight text-ink-900 sm:text-4xl lg:text-[42px] leading-tight">
          {t("intelligence.title")}
        </h1>
        <p className="max-w-3xl text-sm leading-relaxed text-ink-600 sm:text-base">
          {t("intelligence.subtitle")}
        </p>
      </div>

      {/* Primary Analytical Workspace Navigation */}
      <div className="mt-6 border-b border-ink-200/80">
        <nav className="flex space-x-1 sm:space-x-2 overflow-x-auto pb-px no-scrollbar" aria-label="Analytical Tabs">
          {[
            { id: "overview", label: t("intelligence.tabs.overview"), icon: InfoIcon },
            { id: "olap", label: t("intelligence.tabs.olap"), icon: SortIcon },
            { id: "spatial", label: t("intelligence.tabs.spatial"), icon: CompassIcon },
            { id: "isolation", label: t("intelligence.tabs.isolation"), icon: PinIcon },
            { id: "demand", label: t("intelligence.tabs.demand"), icon: BoltIcon },
            { id: "prediction", label: t("intelligence.tabs.prediction"), icon: BoltIcon },
            { id: "governance", label: t("intelligence.tabs.governance"), icon: AlertTriangleIcon },
          ].map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as MainTab)}
                className={cx(
                  "flex shrink-0 items-center gap-2 border-b-2 px-3.5 py-3 text-xs sm:text-sm font-medium transition-all",
                  active
                    ? "border-coral-600 text-coral-700 font-semibold bg-coral-50/40 rounded-t-lg"
                    : "border-transparent text-ink-600 hover:border-ink-300 hover:text-ink-900"
                )}
              >
                <Icon size={15} />
                {tab.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* =========================================================================
          TAB 1: Network Overview & Data Provenance
          ========================================================================= */}
      {activeTab === "overview" && (
        <div className="mt-6 flex flex-col gap-6">
          {/* Key Infrastructure Metrics Cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
            <div className="rounded-xl border border-ink-200/80 bg-white p-4 shadow-xs">
              <p className="text-xs font-medium text-ink-500">Real Stations Snapshot</p>
              <p className="mt-1 font-editorial text-3xl font-normal text-ink-900">
                {spatialMining?.summary.total_stations ?? "—"}
              </p>
              <p className="mt-1 text-[11px] text-ink-500">
                20 Indian states, 293 cities (Open Charge Map)
              </p>
            </div>

            <div className="rounded-xl border border-ink-200/80 bg-white p-4 shadow-xs">
              <p className="text-xs font-medium text-ink-500">Spatial Density Clusters</p>
              <p className="mt-1 font-editorial text-3xl font-normal text-purple-700">
                {spatialMining?.summary.cluster_count ?? "—"}
              </p>
              <p className="mt-1 text-[11px] text-ink-500">
                {spatialMining?.summary.clustered_stations ?? 0} core stations (DBSCAN ε=2km)
              </p>
            </div>

            <div className="rounded-xl border border-ink-200/80 bg-white p-4 shadow-xs">
              <p className="text-xs font-medium text-ink-500">Isolated Stations (&gt;5km)</p>
              <p className="mt-1 font-editorial text-3xl font-normal text-coral-600">
                {spatialMining?.summary.coverage_gap_count ?? "—"}
              </p>
              <p className="mt-1 text-[11px] text-ink-500">
                17 extreme Tukey outliers (&gt;75.4km)
              </p>
            </div>

            <div className="rounded-xl border border-ink-200/80 bg-white p-4 shadow-xs">
              <p className="text-xs font-medium text-ink-500">Warehouse Fact Grain</p>
              <p className="mt-1 font-editorial text-3xl font-normal text-emerald-700">
                360 rows
              </p>
              <p className="mt-1 text-[11px] text-ink-500">
                17,280 observation ticks (Sept 2026)
              </p>
            </div>
          </div>

          {/* Data Provenance & Freshness Box */}
          <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
            <div className="flex items-center justify-between border-b border-ink-100 pb-3">
              <div>
                <h3 className="text-base font-semibold text-ink-900">
                  {t("intelligence.provenance.title")}
                </h3>
                <p className="text-xs text-ink-500 mt-0.5">
                  {t("intelligence.provenance.scope")}
                </p>
              </div>
              <span className="rounded-full bg-ink-100 px-3 py-1 text-xs font-mono font-medium text-ink-700">
                Audit Status: VERIFIED
              </span>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
              <div className="rounded-lg bg-ink-50 p-3">
                <p className="font-semibold text-ink-900">1. Spatial Mining Dataset</p>
                <p className="mt-1 text-ink-600">Source: Open Charge Map India (CC BY 4.0)</p>
                <p className="text-ink-600">Records: 541 validated GPS stations</p>
                <p className="mt-1 font-medium text-emerald-700">Authentic Empirical Data</p>
              </div>

              <div className="rounded-lg bg-ink-50 p-3">
                <p className="font-semibold text-ink-900">2. Warehouse Star Schema</p>
                <p className="mt-1 text-ink-600">Schema: <code>analytics</code> (Kimball)</p>
                <p className="text-ink-600">Grain: Daily aggregates of 15-min ticks</p>
                <p className="mt-1 font-medium text-blue-700">12 Mumbai stations × 30 days</p>
              </div>

              <div className="rounded-lg bg-ink-50 p-3">
                <p className="font-semibold text-ink-900">3. Occupancy ML Experiment</p>
                <p className="mt-1 text-ink-600">Model: Random Forest Regressor</p>
                <p className="text-ink-600">Evaluation: 80/20 chronological holdout</p>
                <p className="mt-1 font-medium text-amber-700">Academic Demo (Synthetic Seed)</p>
              </div>

              <div className="rounded-lg bg-ink-50 p-3">
                <p className="font-semibold text-ink-900">4. Live Production Gate</p>
                <p className="mt-1 text-ink-600">State: <code>COLD / FAIL-CLOSED</code></p>
                <p className="text-ink-600">Required: 500+ verified live CPO events</p>
                <p className="mt-1 font-medium text-rose-700">Driver Safety: No Hallucinations</p>
              </div>
            </div>
          </div>

          {/* Data Storytelling Overview */}
          <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs text-xs sm:text-sm text-ink-700 space-y-3">
            <h3 className="text-sm sm:text-base font-semibold text-ink-900">
              Understanding the Multi-Tiered Architecture of ChargePlus
            </h3>
            <p className="leading-relaxed">
              ChargePlus operates an honest two-tier data architecture designed to bridge consumer utility and academic research rigor:
            </p>
            <ul className="list-disc pl-5 space-y-2 leading-relaxed">
              <li>
                <strong>Operational Consumer Layer (OLTP):</strong> Powers the Explore map, search, and station reviews across genuine Indian EV charging sites with real coordinates, connector configurations, and verified tariffs.
              </li>
              <li>
                <strong>Analytical Research Layer (OLAP & Mining):</strong> Implements a Kimball Star Schema on PostgreSQL (<code>analytics.fact_station_daily</code>), spatial clustering via DBSCAN with Haversine great-circle distance, nearest-neighbor isolation modeling, and chronological machine learning regression.
              </li>
              <li>
                <strong>Fail-Closed Production Discipline:</strong> The platform deliberately refuses to serve synthetic or unverified machine learning occupancy numbers to drivers on the road. In the absence of streaming commercial CPO smart-meter telemetry, the prediction endpoint remains in a safe <code>COLD</code> governance state.
              </li>
            </ul>
          </div>
        </div>
      )}

      {/* =========================================================================
          TAB 2: First-Class Warehouse Analytics & OLAP
          ========================================================================= */}
      {activeTab === "olap" && (
        <div className="mt-6 flex flex-col gap-6">
          {/* OLAP Header Banner */}
          <div className="rounded-xl border border-blue-200/80 bg-gradient-to-r from-blue-50/60 via-indigo-50/40 to-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-blue-800">
                  Kimball Dimensional Modeling · DWDM Syllabus
                </span>
                <h2 className="font-editorial text-2xl font-normal text-ink-900 mt-0.5">
                  {t("intelligence.olap.title")}
                </h2>
                <p className="text-xs sm:text-sm text-ink-600 mt-1 max-w-2xl">
                  {t("intelligence.olap.subtitle")}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={exportOlapCsv}
                  disabled={!olapResult || olapResult.rows.length === 0}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-ink-200 bg-white px-3 py-1.5 text-xs font-semibold text-ink-800 shadow-xs hover:bg-ink-50 disabled:opacity-50 transition"
                >
                  Export CSV
                </button>
                <button
                  type="button"
                  onClick={() => setShowSql(!showSql)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-900 shadow-xs hover:bg-blue-100 transition"
                >
                  {showSql ? "Hide SQL" : "View SQL (Viva)"}
                </button>
              </div>
            </div>
          </div>

          {/* OLAP Operations Selector */}
          <div className="rounded-xl border border-ink-200/80 bg-white p-4 shadow-xs">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 pb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-ink-500">
                Select OLAP Operation
              </span>
              <span className="text-xs text-ink-500">
                Executed against live warehouse table <code>analytics.fact_station_daily</code>
              </span>
            </div>

            <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
              {[
                { id: "rollup", label: "1. Roll-Up", desc: "Hierarchical Time Aggregate" },
                { id: "drilldown", label: "2. Drill-Down", desc: "City → Locality → Station" },
                { id: "slice", label: "3. Slice", desc: "Single Operator Dimension" },
                { id: "dice", label: "4. Dice", desc: "Multi-Filter Subcube" },
                { id: "cube", label: "5. Pivot / CUBE", desc: "Operator × Locality Matrix" },
                { id: "window_ranking", label: "6. Window Ranking", desc: "DENSE_RANK() Top-N" },
              ].map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setOlapOp(item.id as OlapOperation)}
                  className={cx(
                    "flex flex-col text-left p-3 rounded-xl border transition-all",
                    olapOp === item.id
                      ? "border-blue-500 bg-blue-50/70 shadow-xs text-blue-950 font-semibold"
                      : "border-ink-200/70 bg-white hover:border-ink-300 hover:bg-ink-50/50 text-ink-800"
                  )}
                >
                  <span className="text-xs font-bold">{item.label}</span>
                  <span className="text-[11px] text-ink-500 mt-0.5">{item.desc}</span>
                </button>
              ))}
            </div>

            {/* Sub-controls specific to selected OLAP operation */}
            <div className="mt-4 pt-3 border-t border-ink-100 flex flex-wrap items-center gap-3 text-xs">
              {olapOp === "rollup" && (
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink-600">Aggregation Hierarchy:</span>
                  <button
                    type="button"
                    onClick={() => setRollupMode("weekly")}
                    className={cx(
                      "px-2.5 py-1 rounded-md border",
                      rollupMode === "weekly"
                        ? "bg-blue-600 text-white border-blue-600 font-semibold"
                        : "bg-white text-ink-700 border-ink-200 hover:bg-ink-50"
                    )}
                  >
                    Week → Month → Total (Query 1B)
                  </button>
                  <button
                    type="button"
                    onClick={() => setRollupMode("calendar")}
                    className={cx(
                      "px-2.5 py-1 rounded-md border",
                      rollupMode === "calendar"
                        ? "bg-blue-600 text-white border-blue-600 font-semibold"
                        : "bg-white text-ink-700 border-ink-200 hover:bg-ink-50"
                    )}
                  >
                    Month → Year → Total (Query 1A)
                  </button>
                </div>
              )}

              {olapOp === "drilldown" && (
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink-600">Locality Filter:</span>
                  <select
                    value={drillLocality}
                    onChange={(e) => setDrillLocality(e.target.value)}
                    className="rounded-md border border-ink-200 bg-white px-2.5 py-1 text-xs text-ink-800"
                  >
                    <option value="">All Mumbai Localities (10)</option>
                    <option value="Bandra Kurla Complex">Bandra Kurla Complex</option>
                    <option value="Lower Parel">Lower Parel</option>
                    <option value="Goregaon East">Goregaon East</option>
                    <option value="Sahar">Sahar Airport T2</option>
                    <option value="Thane West">Thane West</option>
                    <option value="Dadar East">Dadar East</option>
                    <option value="Chembur">Chembur</option>
                    <option value="Powai">Powai</option>
                    <option value="Andheri East">Andheri East</option>
                    <option value="Vashi">Vashi</option>
                  </select>
                </div>
              )}

              {olapOp === "slice" && (
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink-600">Fixed Operator:</span>
                  {["Tata Power", "Jio-bp", "Statiq", "ChargeZone", "Fortum"].map((op) => (
                    <button
                      key={op}
                      type="button"
                      onClick={() => setSliceOp(op)}
                      className={cx(
                        "px-2.5 py-1 rounded-md border",
                        sliceOp === op
                          ? "bg-blue-600 text-white border-blue-600 font-semibold"
                          : "bg-white text-ink-700 border-ink-200 hover:bg-ink-50"
                      )}
                    >
                      {op}
                    </button>
                  ))}
                </div>
              )}

              {olapOp === "dice" && (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="font-medium text-ink-600">Day Partition:</span>
                  {(["all", "weekday", "weekend"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setDiceDayType(mode)}
                      className={cx(
                        "px-2.5 py-1 rounded-md border capitalize",
                        diceDayType === mode
                          ? "bg-blue-600 text-white border-blue-600 font-semibold"
                          : "bg-white text-ink-700 border-ink-200 hover:bg-ink-50"
                      )}
                    >
                      {mode}
                    </button>
                  ))}
                  <span className="text-ink-400">|</span>
                  <span className="text-ink-600">Operators: Tata Power, Jio-bp · Localities: BKC, Lower Parel</span>
                </div>
              )}

              {olapOp === "window_ranking" && (
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink-600">Top-N per Operator:</span>
                  {[1, 2, 3, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setWindowTopN(n)}
                      className={cx(
                        "px-2.5 py-1 rounded-md border",
                        windowTopN === n
                          ? "bg-blue-600 text-white border-blue-600 font-semibold"
                          : "bg-white text-ink-700 border-ink-200 hover:bg-ink-50"
                      )}
                    >
                      Top {n}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Academic Viva Defense SQL Viewer (Collapsible) */}
          {showSql && olapResult && (
            <div className="rounded-xl border border-ink-800 bg-ink-900 p-4 text-xs font-mono text-emerald-400 shadow-md">
              <div className="flex items-center justify-between pb-2 border-b border-ink-700 text-ink-400">
                <span>SQL Query Executed Against PostgreSQL (`analytics` schema)</span>
                <span className="text-[11px] text-ink-400">DWDM Viva Reference</span>
              </div>
              <pre className="mt-3 overflow-x-auto whitespace-pre leading-relaxed">
                {olapResult.sql}
              </pre>
            </div>
          )}

          {/* Query Results & Interpretation */}
          {olapLoading ? (
            <div className="flex h-48 items-center justify-center rounded-xl border border-ink-100 bg-white">
              <div className="text-center">
                <div className="h-6 w-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto" />
                <p className="mt-2 text-xs text-ink-500">Executing multidimensional OLAP query...</p>
              </div>
            </div>
          ) : olapResult ? (
            <div className="flex flex-col gap-6">
              {/* Business Interpretation Box */}
              <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 text-xs sm:text-sm text-emerald-950">
                <div className="flex items-start gap-2">
                  <CheckIcon size={16} className="text-emerald-700 shrink-0 mt-0.5" />
                  <div>
                    <h4 className="font-bold text-emerald-950">{olapResult.title}</h4>
                    <p className="mt-0.5 text-emerald-900 font-medium">{olapResult.businessQuestion}</p>
                    <p className="mt-2 text-emerald-800 leading-relaxed">{olapResult.interpretation}</p>
                  </div>
                </div>
              </div>

              {/* Visual Presentation (Bar distribution for Rollup/Drilldown, Matrix for Cube) */}
              {olapOp === "rollup" && (
                <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
                  <h4 className="text-sm font-bold text-ink-900">
                    Weekly Telemetry & Utilization Progression
                  </h4>
                  <div className="mt-4 space-y-3">
                    {olapResult.rows.map((r, i) => {
                      const isSubtotal = String(r.calendar_week).includes("TOTAL") || String(r.month_name).includes("TOTAL");
                      const utilPct = Number(r.avg_utilization_pct || r.monthly_avg_utilization_pct || 0);
                      const label = r.calendar_week ? `Week ${r.calendar_week}` : `${r.month_name} ${r.year || ""}`;
                      return (
                        <div key={i} className={cx("text-xs p-2.5 rounded-lg", isSubtotal ? "bg-blue-50/80 font-bold border border-blue-200" : "bg-ink-50")}>
                          <div className="flex justify-between items-center mb-1">
                            <span className="text-ink-900">{label}</span>
                            <span className="font-mono text-ink-800">{utilPct.toFixed(2)}% avg utilization</span>
                          </div>
                          <div className="h-2.5 w-full bg-ink-200/70 rounded-full overflow-hidden">
                            <div
                              className={cx("h-full rounded-full", isSubtotal ? "bg-blue-600" : "bg-coral-500")}
                              style={{ width: `${Math.min(100, utilPct * 2.5)}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {olapOp === "drilldown" && (
                <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
                  <h4 className="text-sm font-bold text-ink-900">
                    Locality Congestion Hotspots (Ranked by Utilization)
                  </h4>
                  <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
                    {olapResult.rows.map((r, i) => {
                      const util = Number(r.locality_avg_utilization || 0);
                      return (
                        <div key={i} className="rounded-lg border border-ink-100 bg-ink-50/50 p-3.5 flex flex-col justify-between">
                          <div>
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-semibold text-ink-900">{r.locality}</span>
                              <span className="rounded bg-coral-50 border border-coral-200 px-2 py-0.5 text-[11px] font-bold text-coral-800">
                                {util}% util
                              </span>
                            </div>
                            <p className="mt-1 text-xs text-ink-600 truncate">{r.station_name}</p>
                            <p className="text-[11px] text-ink-500">{r.operator_name}</p>
                          </div>
                          <div className="mt-2.5 pt-2 border-t border-ink-100/70 flex justify-between text-[11px] text-ink-500">
                            <span>Congestion Events</span>
                            <span className="font-mono font-semibold text-ink-900">{r.total_congestion_events}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {olapOp === "window_ranking" && (
                <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
                  <h4 className="text-sm font-bold text-ink-900">
                    Top Congested Infrastructure by Network (Partitioned Leaderboard)
                  </h4>
                  <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {olapResult.rows.map((r, i) => (
                      <div key={i} className="rounded-lg border border-ink-100 bg-white p-3.5 shadow-xs flex flex-col justify-between">
                        <div>
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-blue-900">{r.operator_name}</span>
                            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-bold text-blue-800">
                              Rank #{r.rank_in_network}
                            </span>
                          </div>
                          <p className="mt-1.5 text-xs font-medium text-ink-900 line-clamp-2">{r.station_name}</p>
                        </div>
                        <div className="mt-3 pt-2 border-t border-ink-100 flex items-center justify-between text-xs">
                          <span className="text-ink-500">Utilization</span>
                          <span className="font-mono font-bold text-coral-700">{r.overall_utilization}%</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Result Table */}
              <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
                <div className="flex items-center justify-between border-b border-ink-100 pb-3">
                  <h4 className="text-sm font-bold text-ink-900">
                    Analytical Result Table ({olapResult.rows.length} rows)
                  </h4>
                  <span className="text-xs font-mono text-ink-500">
                    Dimensions: {olapResult.dimensions.join(", ")}
                  </span>
                </div>

                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-left text-xs text-ink-700">
                    <thead className="border-b border-ink-200 bg-ink-50 text-ink-600">
                      <tr>
                        {Object.keys(olapResult.rows[0] || {}).map((col) => (
                          <th key={col} className="py-2.5 px-3 font-semibold capitalize whitespace-nowrap">
                            {col.replace(/_/g, " ")}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-100">
                      {olapResult.rows.map((row, idx) => {
                        const isSubtotal = Object.values(row).some(
                          (v) => String(v).includes("TOTAL") || String(v).includes("ALL ")
                        );
                        return (
                          <tr
                            key={idx}
                            className={cx(
                              isSubtotal ? "bg-blue-50/60 font-semibold text-blue-950" : "hover:bg-ink-50/50"
                            )}
                          >
                            {Object.entries(row).map(([k, val], cIdx) => (
                              <td key={cIdx} className="py-2.5 px-3 whitespace-nowrap">
                                {val == null ? "NULL" : String(val)}
                              </td>
                            ))}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Data Provenance & Academic Limitations */}
              <div className="rounded-xl border border-ink-200/80 bg-ink-50 p-4 text-xs text-ink-600 space-y-1">
                <p className="font-bold text-ink-900">Warehouse Source & Academic Scope Disclosure:</p>
                <p>
                  Fact Table: <code>{olapResult.provenance.factTable}</code> ({olapResult.provenance.grain}).
                  Spans {olapResult.provenance.totalFactRows} daily fact records across {olapResult.provenance.stationsCount} representative
                  Mumbai stations for {olapResult.provenance.period} ({olapResult.provenance.telemetryTicks.toLocaleString()} total observation ticks).
                </p>
                <p className="italic text-ink-500">
                  Academic Notice: Represents academic coursework demonstration telemetry modeling standard commuter diurnal spikes, not verified live proprietary CPO smart-meter streaming feeds.
                </p>
              </div>
            </div>
          ) : (
            <div className="flex h-36 items-center justify-center rounded-xl border border-ink-100 bg-white text-xs text-ink-500">
              No OLAP data returned for this query configuration.
            </div>
          )}
        </div>
      )}

      {/* =========================================================================
          TAB 3: Spatial Clusters (DBSCAN)
          ========================================================================= */}
      {activeTab === "spatial" && (
        !spatialMining ? (
          <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-6 text-center">
            <h3 className="text-sm font-semibold text-amber-900">Spatial Clustering Data Unavailable</h3>
            <p className="mt-1 text-xs text-amber-700">
              The spatial clustering artifact is missing or invalid.
            </p>
          </div>
        ) : (
          <div className="mt-6 flex flex-col gap-6">
            <div className="rounded-xl border border-purple-200 bg-purple-50/60 p-4 text-xs text-purple-900 sm:p-5 sm:text-sm">
              <h3 className="font-semibold text-purple-950">DBSCAN Methodology on Authentic Real Data</h3>
              <p className="mt-1 text-purple-800 leading-relaxed">
                Executed with <strong>Haversine great-circle distance metric</strong> on genuine GPS coordinates
                (R = 6,371 km). Parameter configuration: <code>eps = 2.0 km</code>, <code>min_samples = 3</code>.
                Cluster labels represent spatial density groupings, <em>not</em> commercial performance rankings.
                DBSCAN noise points are valid standalone stations whose nearest neighbor exceeds 2.0 km.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
              {/* Cluster Selector List */}
              <div className="lg:col-span-5">
                <div className="rounded-xl border border-ink-200/80 bg-white p-4 shadow-xs">
                  <div className="flex items-center justify-between pb-3 border-b border-ink-100">
                    <h3 className="text-sm font-semibold text-ink-900">
                      Discovered Clusters ({spatialMining.clusters.length})
                    </h3>
                    <span className="text-xs text-ink-500">Click to inspect</span>
                  </div>
                  <div className="mt-3 max-h-[500px] overflow-y-auto space-y-2 pr-1 thin-scroll">
                    {spatialMining.clusters.map((c) => {
                      const isSelected = c.cluster_id === selectedClusterId;
                      return (
                        <button
                          key={c.cluster_id}
                          onClick={() => setSelectedClusterId(c.cluster_id)}
                          className={cx(
                            "w-full text-left rounded-xl p-3 border transition-all",
                            isSelected
                              ? "border-purple-500 bg-purple-50/70 shadow-xs"
                              : "border-ink-100 hover:border-ink-200 hover:bg-ink-50/50"
                          )}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-semibold text-ink-900">
                              Cluster #{c.cluster_id}
                            </span>
                            <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-semibold text-purple-800">
                              {c.station_count} stations
                            </span>
                          </div>
                          <div className="mt-1.5 flex items-center justify-between text-xs text-ink-500">
                            <span>
                              Centroid: {c.center_lat.toFixed(3)}, {c.center_lng.toFixed(3)}
                            </span>
                            <span>Radius: {c.radius_km.toFixed(2)} km</span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Cluster Detail View */}
              <div className="lg:col-span-7">
                {selectedCluster ? (
                  <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
                    <div className="flex items-center justify-between border-b border-ink-100 pb-4">
                      <div>
                        <h3 className="text-lg font-bold text-ink-900">
                          Cluster #{selectedCluster.cluster_id} Station Details
                        </h3>
                        <p className="text-xs text-ink-500">
                          Centroid: {selectedCluster.center_lat.toFixed(5)}°N, {selectedCluster.center_lng.toFixed(5)}°E · Max Spread: {selectedCluster.radius_km.toFixed(2)} km
                        </p>
                      </div>
                      <span className="rounded-full bg-emerald-50 border border-emerald-200 px-3 py-1 text-xs font-semibold text-emerald-800">
                        {selectedCluster.station_count} Verified Stations
                      </span>
                    </div>

                    <div className="mt-4 max-h-[460px] overflow-y-auto space-y-2.5 pr-1 thin-scroll">
                      {selectedCluster.stations.map((st, idx) => (
                        <div
                          key={st.id || idx}
                          className="flex flex-col sm:flex-row sm:items-center sm:justify-between rounded-xl border border-ink-100 p-3 hover:bg-ink-50/50"
                        >
                          <div>
                            <p className="text-sm font-semibold text-ink-900">{st.name}</p>
                            <p className="text-xs text-ink-500">{st.operator || "Independent / Commercial CPO"}</p>
                          </div>
                          <div className="mt-2 sm:mt-0 flex items-center gap-3">
                            <span className="text-xs font-mono text-ink-400">
                              {st.lat.toFixed(4)}, {st.lng.toFixed(4)}
                            </span>
                            <Link
                              href={`/station/${st.id}`}
                              className="inline-flex items-center text-xs font-semibold text-coral-600 hover:text-coral-700"
                            >
                              View Station &rarr;
                            </Link>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-ink-200 text-sm text-ink-400">
                    Select a cluster on the left to inspect constituent stations
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      )}

      {/* =========================================================================
          TAB 4: Station Isolation Analysis
          ========================================================================= */}
      {activeTab === "isolation" && (
        !spatialMining ? (
          <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-6 text-center">
            <h3 className="text-sm font-semibold text-amber-900">Station Isolation Data Unavailable</h3>
            <p className="mt-1 text-xs text-amber-700">
              The station isolation summary artifact is missing or invalid.
            </p>
          </div>
        ) : (
          <div className="mt-6 flex flex-col gap-6">
            {/* Statistical Explanatory Panel with Formula */}
            <div className="rounded-xl border border-coral-200 bg-coral-50/40 p-4 text-xs text-coral-900 sm:p-5 sm:text-sm">
              <h3 className="font-semibold text-coral-950">Station Isolation & Statistical Outlier Analysis</h3>
              <p className="mt-1 text-coral-800 leading-relaxed">
                Across the <strong>{spatialMining.summary.total_stations} recorded stations</strong> in this nationwide Open Charge Map snapshot,
                {" "}<strong>{spatialMining.summary.coverage_gap_count} stations</strong> have no neighboring charger within 5 kilometers.
                Of those, <strong>{spatialMining.summary.extreme_isolation_outliers} stations</strong> are statistical outliers exceeding the upper
                Tukey fence:
              </p>
              <div className="my-2.5 rounded-lg bg-white/80 p-2.5 font-mono text-xs text-coral-950 border border-coral-200">
                IQR = Q3 - Q1 &nbsp;|&nbsp; Upper Tukey Fence = Q3 + 1.5 × IQR ≈ 75.4 km (Observed: 75.9 km - 254.8 km)
              </div>
              <p className="text-[11px] text-coral-700 italic">
                Limitation Notice: Evaluates isolation relative to recorded stations in the snapshot, not an exhaustive census of all public Indian EVSE hardware.
              </p>
            </div>

            <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-100 pb-3">
                <div>
                  <h3 className="text-base font-bold text-ink-900">
                    {isolationView === "extreme"
                      ? `Extreme Isolation Outliers (${spatialMining.summary.extreme_isolation_outliers} Stations — IQR Anomalies)`
                      : `Sample of Most Isolated Stations (${spatialMining.coverage_gaps_sample?.length ?? 25} Stations Recorded)`}
                  </h3>
                  <p className="text-xs text-ink-500 mt-0.5">
                    {isolationView === "extreme"
                      ? "Stations exceeding the upper Tukey fence (>75.4 km nearest recorded neighbor) with statistical outlier score"
                      : "Curated sample of stations with the largest nearest-neighbor separation in this snapshot (sorted descending)"}
                  </p>
                </div>
                <div className="inline-flex rounded-xl bg-ink-100 p-1 text-xs font-medium">
                  <button
                    type="button"
                    onClick={() => setIsolationView("extreme")}
                    className={cx(
                      "rounded-lg px-3 py-1.5 transition",
                      isolationView === "extreme"
                        ? "bg-white text-ink-900 shadow-xs font-semibold"
                        : "text-ink-600 hover:text-ink-900"
                    )}
                  >
                    17 Extreme Outliers (IQR)
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsolationView("sample")}
                    className={cx(
                      "rounded-lg px-3 py-1.5 transition",
                      isolationView === "sample"
                        ? "bg-white text-ink-900 shadow-xs font-semibold"
                        : "text-ink-600 hover:text-ink-900"
                    )}
                  >
                    25 Sampled Stations
                  </button>
                </div>
              </div>

              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-left text-xs text-ink-700">
                  <thead className="border-b border-ink-100 bg-ink-50/70 text-ink-500">
                    <tr>
                      <th className="py-2.5 px-3 font-semibold">Station Name</th>
                      <th className="py-2.5 px-3 font-semibold">Nearest Neighbor Distance</th>
                      {isolationView === "extreme" ? (
                        <th className="py-2.5 px-3 font-semibold">IQR Outlier Score</th>
                      ) : (
                        <th className="py-2.5 px-3 font-semibold">Coordinates</th>
                      )}
                      <th className="py-2.5 px-3 font-semibold">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {(isolationView === "extreme"
                      ? (spatialMining.top_coverage_gaps || spatialMining.extreme_isolation_anomalies || [])
                      : (spatialMining.coverage_gaps_sample || spatialMining.top_coverage_gaps || [])
                    ).map((gap) => (
                      <tr key={gap.station_id} className="hover:bg-ink-50/40">
                        <td className="py-3 px-3 font-medium text-ink-900">{gap.station_name}</td>
                        <td className="py-3 px-3 font-mono font-semibold text-coral-600">
                          {gap.nearest_distance_km ? `${gap.nearest_distance_km.toFixed(1)} km` : "N/A"}
                        </td>
                        {isolationView === "extreme" ? (
                          <td className="py-3 px-3">
                            <span className="inline-flex rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                              {gap.outlier_score != null ? gap.outlier_score.toFixed(2) : "N/A"}
                            </span>
                          </td>
                        ) : (
                          <td className="py-3 px-3 font-mono text-ink-500">
                            {gap.latitude != null && gap.longitude != null
                              ? `${gap.latitude.toFixed(3)}°N, ${gap.longitude.toFixed(3)}°E`
                              : "Recorded"}
                          </td>
                        )}
                        <td className="py-3 px-3">
                          <Link
                            href={`/station/${gap.station_id}`}
                            className="font-medium text-coral-600 hover:text-coral-700"
                          >
                            Details &rarr;
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )
      )}

      {/* =========================================================================
          TAB 5: Demand Grouping (K-Means)
          ========================================================================= */}
      {activeTab === "demand" && (
        !miningSummary || !miningSummary.clusters ? (
          <div className="mt-6 rounded-xl border border-blue-200 bg-blue-50 p-6 text-center">
            <h3 className="text-sm font-semibold text-blue-900">Demand Grouping Data Unavailable</h3>
            <p className="mt-1 text-xs text-blue-700">
              The demand clustering summary artifact is missing or invalid.
            </p>
          </div>
        ) : (
          <div className="mt-6 flex flex-col gap-6">
            <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-4 text-xs text-blue-900 sm:p-5 sm:text-sm">
              <h3 className="font-semibold text-blue-950">K-Means Station Grouping (Offline Demonstration)</h3>
              <p className="mt-1 text-blue-800 leading-relaxed">
                Evaluates partitioned clustering (k=3) grouping stations by spatial centroid and calculated synthetic demand index.
                Centroids partition infrastructure into distinct operational profiles (South Mumbai high-throughput hub, Suburb arterial, North peripheral).
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {miningSummary.clusters.map((kc) => (
                <div key={kc.cluster_id} className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-ink-900">Cluster {kc.cluster_id}</span>
                    <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700">
                      {kc.station_count} stations
                    </span>
                  </div>
                  <div className="mt-4 space-y-2 text-xs">
                    <div className="flex justify-between border-b border-ink-50 pb-1.5">
                      <span className="text-ink-500">Avg Demand Score</span>
                      <span className="font-semibold text-ink-900">{kc.avg_demand_score.toFixed(1)} / 100</span>
                    </div>
                    <div className="flex justify-between border-b border-ink-50 pb-1.5">
                      <span className="text-ink-500">Centroid Lat</span>
                      <span className="font-mono text-ink-800">{kc.avg_lat.toFixed(4)}°N</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-ink-500">Centroid Lng</span>
                      <span className="font-mono text-ink-800">{kc.avg_lng.toFixed(4)}°E</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs text-xs text-ink-600 space-y-2">
              <h4 className="font-bold text-ink-900 text-sm">Honest Academic Limitation</h4>
              <p>
                In the absence of commercial CPO proprietary session logs, demand scores are derived from synthetic
                seed observations and connector power characteristics. This demonstrates partitioning mechanics
                accurately but should not be mistaken for empirical consumer transaction data.
              </p>
            </div>
          </div>
        )
      )}

      {/* =========================================================================
          TAB 6: Occupancy Prediction Research
          ========================================================================= */}
      {activeTab === "prediction" && (
        !offlineReport || !offlineReport.evaluations ? (
          <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-6 text-center">
            <h3 className="text-sm font-semibold text-amber-900">Offline Evaluation Report Unavailable</h3>
            <p className="mt-1 text-xs text-amber-700">
              The offline evaluation report artifact is missing or invalid.
            </p>
          </div>
        ) : (
          <div className="mt-6 flex flex-col gap-6">
            <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4 text-xs text-amber-900 sm:p-5 sm:text-sm">
              <h3 className="font-semibold text-amber-950">Chronological vs Random Train/Test Evaluation</h3>
              <p className="mt-1 text-amber-800 leading-relaxed">
                Evaluated on 17,280 synthetic observation steps. Contrasting historical <em>random split</em> (prone to
                future data leakage across time) with an honest <strong>chronological 80/20 train/test split</strong> (13,824 train / 3,456 test records).
              </p>
            </div>

            {/* Model Comparison Matrix */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
                <h3 className="text-sm font-bold text-ink-900">Evaluation Metrics Comparison</h3>
                <p className="text-xs text-ink-500 mt-0.5">Tested on untouched holdout test partition</p>

                <div className="mt-4 space-y-3 text-xs">
                  <div className="flex items-center justify-between rounded-xl bg-ink-50 p-3">
                    <div>
                      <p className="font-semibold text-ink-900">Baseline Predictor (Hour Mean)</p>
                      <p className="text-[11px] text-ink-500">Naive temporal lookup</p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono font-bold text-ink-900">
                        MAE {offlineReport.evaluations.honest_chronological_split.metrics.baseline_mae.toFixed(4)}
                      </p>
                      <p className="text-[11px] text-ink-500">
                        RMSE {offlineReport.evaluations.honest_chronological_split.metrics.baseline_rmse.toFixed(4)}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50/40 p-3">
                    <div>
                      <p className="font-semibold text-emerald-950">Random Forest (Honest Chronological)</p>
                      <p className="text-[11px] text-emerald-700">Strict chronological holdout (3,456 test)</p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono font-bold text-emerald-900">
                        MAE {offlineReport.evaluations.honest_chronological_split.metrics.rf_mae.toFixed(4)}
                      </p>
                      <p className="text-[11px] text-emerald-700">
                        R² = {offlineReport.evaluations.honest_chronological_split.metrics.r2_score.toFixed(4)} (+{offlineReport.evaluations.honest_chronological_split.metrics.improvement_pct.toFixed(2)}%)
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center justify-between rounded-xl border border-ink-100 bg-white p-3">
                    <div>
                      <p className="font-semibold text-ink-700">Legacy Random Split Benchmark</p>
                      <p className="text-[11px] text-ink-400">Random shuffle (contains temporal leakage)</p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono font-bold text-ink-700">
                        MAE {offlineReport.evaluations.legacy_random_split_reproduced.metrics.rf_mae.toFixed(4)}
                      </p>
                      <p className="text-[11px] text-ink-400">
                        R² = {offlineReport.evaluations.legacy_random_split_reproduced.metrics.r2_score.toFixed(4)}
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Feature Importance */}
              <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
                <h3 className="text-sm font-bold text-ink-900">Feature Importance Distribution</h3>
                <p className="text-xs text-ink-500 mt-0.5">Relative Gini importance from trained Random Forest</p>

                <div className="mt-4 space-y-3">
                  {miningSummary?.feature_importance &&
                    Object.entries(miningSummary.feature_importance)
                      .sort(([, a], [, b]) => b - a)
                      .map(([feat, imp]) => (
                        <div key={feat} className="text-xs">
                          <div className="flex justify-between font-medium text-ink-800">
                            <span className="capitalize">{feat.replace(/_/g, " ")}</span>
                            <span className="font-mono">{(imp * 100).toFixed(2)}%</span>
                          </div>
                          <div className="mt-1 h-2 w-full rounded-full bg-ink-100 overflow-hidden">
                            <div
                              className="h-full bg-coral-500 rounded-full"
                              style={{ width: `${Math.min(100, imp * 100)}%` }}
                            />
                          </div>
                        </div>
                      ))}
                </div>

                <div className="mt-4 rounded-xl bg-amber-50 p-3 text-[11px] text-amber-900">
                  <strong>Academic Finding:</strong> Hour-of-day accounts for ~90% of variance because the synthetic
                  seed generator models diurnal commute spikes (8-10 AM and 5-8 PM). Real CPO data exhibits higher
                  variance driven by weather, pricing surges, and charger queueing.
                </div>
              </div>
            </div>
          </div>
        )
      )}

      {/* =========================================================================
          TAB 7: Production Gate Governance
          ========================================================================= */}
      {activeTab === "governance" && (
        <div className="mt-6 flex flex-col gap-6">
          <div className="rounded-xl border border-ink-200/80 bg-white p-5 shadow-xs">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 text-amber-700">
                <AlertTriangleIcon size={20} />
              </div>
              <div>
                <h3 className="text-base font-bold text-ink-900">
                  Production Gate Status: {productionGate.state}
                </h3>
                <p className="text-xs text-ink-500">{productionGate.policy}</p>
              </div>
            </div>

            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-ink-100 p-4">
                <p className="text-xs font-medium text-ink-500">Real Warehouse Events</p>
                <p className="mt-1 text-xl font-bold text-ink-900">
                  {productionGate.totalObservations ?? 0} / {(productionGate.requiredObservations ?? 500).toLocaleString()}
                </p>
                <p className="mt-1 text-[11px] text-rose-600">Gate Requirement: UNMET (Need Real Telemetry)</p>
              </div>

              <div className="rounded-xl border border-ink-100 p-4">
                <p className="text-xs font-medium text-ink-500">Allowed Feature Staleness</p>
                <p className="mt-1 text-xl font-bold text-ink-900">
                  &le; {productionGate.maxFeatureStalenessHours ?? 72} Hours
                </p>
                <p className="mt-1 text-[11px] text-rose-600">Gate Requirement: UNMET (Offline)</p>
              </div>

              <div className="rounded-xl border border-ink-100 p-4">
                <p className="text-xs font-medium text-ink-500">Live Prediction Serving</p>
                <p className="mt-1 text-xl font-bold text-amber-700">FAIL-CLOSED</p>
                <p className="mt-1 text-[11px] text-emerald-600">Driver Safety Guard: ACTIVE</p>
              </div>
            </div>

            {/* Plain-Language Multilingual Driver Disclosure */}
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-4 text-xs text-amber-900 space-y-1.5">
              <p className="font-semibold text-amber-950">Driver Summary / चालक सारांश / वाहन चालकांसाठी माहिती:</p>
              <p>
                <span className="font-medium">English:</span> Real-time occupancy predictions are currently disabled because authentic live hardware feeds are disconnected. No fake wait-times will be shown.
              </p>
              <p>
                <span className="font-medium">हिन्दी:</span> वास्तविक हार्डवेयर डेटा उपलब्ध न होने के कारण लाइव चार्जिंग अनुमान बंद रखे गए हैं। कोई भी कृत्रिम या गलत डेटा नहीं दिखाया जाएगा।
              </p>
              <p>
                <span className="font-medium">मराठी:</span> थेट हार्डवेअर डेटा उपलब्ध नसल्यामुळे रिअल-टाइम अंदाज बंद ठेवण्यात आले आहेत. वाहन चालकांची दिशाभूल टाळण्यासाठी खोटे अंदाज दाखवले जात नाहीत.
              </p>
            </div>

            <div className="mt-6 space-y-3 rounded-xl bg-ink-50 p-4 text-xs text-ink-700">
              <h4 className="font-semibold text-ink-900">Why ChargePlus Employs Fail-Closed Governance</h4>
              <p>
                Many academic and prototype applications silently serve synthetic or hallucinated numbers when
                production models are not available. In ChargePlus, architectural policy mandates that:
              </p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Production models are never trained on synthetic seed data.</li>
                <li>When real streaming hardware telemetry is absent, live prediction routes return <code>COLD / NO_MODEL</code> instead of fabricating occupancy percentages.</li>
                <li>Driver safety and expectation management are prioritized over showing cosmetic predictions.</li>
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
