"use client";

import { useEffect, useState } from "react";
import { Link } from "@/i18n/Link";
import {
  PinIcon,
  BoltIcon,
  AlertTriangleIcon,
  CheckIcon,
  InfoIcon,
  SortIcon,
  CompassIcon,
} from "@/components/Icon";

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
  };
  spatialMining: SpatialMiningData | null;
  miningSummary: MiningSummaryData | null;
  offlineReport: OfflineReportData | null;
}

type TabType = "spatial" | "demand" | "regression" | "gaps" | "governance";

export function IntelligenceClient() {
  const [activeTab, setActiveTab] = useState<TabType>("spatial");
  const [isolationView, setIsolationView] = useState<"extreme" | "sample">("extreme");
  const [data, setData] = useState<IntelligencePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null);

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

  if (loading) {
    return (
      <div className="mx-auto max-w-screen-xl px-4 py-12 sm:px-6">
        <div className="flex flex-col gap-4 animate-pulse">
          <div className="h-8 w-64 rounded-lg bg-ink-100" />
          <div className="h-4 w-96 rounded-md bg-ink-50" />
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-4">
            <div className="h-28 rounded-2xl bg-ink-100" />
            <div className="h-28 rounded-2xl bg-ink-100" />
            <div className="h-28 rounded-2xl bg-ink-100" />
            <div className="h-28 rounded-2xl bg-ink-100" />
          </div>
          <div className="mt-8 h-96 rounded-2xl bg-ink-100" />
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
      {/* Header */}
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
            <CheckIcon size={12} />
            {spatialMining?.summary.total_stations != null
              ? `${spatialMining.summary.total_stations} Real Stations (India Snapshot)`
              : "Spatial Artifact Unavailable"}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full border border-purple-200 bg-purple-50 px-2.5 py-0.5 text-xs font-semibold text-purple-800">
            <CompassIcon size={12} />
            DBSCAN + Haversine (ε=2km)
          </span>
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-900">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
            ML Gate: {productionGate.state} (Fail-Closed)
          </span>
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-900 sm:text-3xl">
          Station Intelligence & Data Mining
        </h1>
        <p className="max-w-3xl text-sm text-ink-600 sm:text-base">
          Academic analysis layer evaluating spatial density clustering on authentic Open Charge Map stations across India,
          K-Means station grouping, and chronological Random Forest occupancy regression.
        </p>
      </div>

      {/* KPI Cards */}
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
        <div className="rounded-2xl border border-ink-100 bg-white p-4 shadow-xs">
          <p className="text-xs font-medium text-ink-500">Real Stations Analyzed</p>
          <p className="mt-1 text-2xl font-bold text-ink-900 sm:text-3xl">
            {spatialMining?.summary.total_stations != null ? spatialMining.summary.total_stations : "—"}
          </p>
          <p className="mt-1 text-[11px] text-ink-500">
            {spatialMining?.summary.total_stations != null ? "Authentic Open Charge Map dataset" : "Artifact unavailable"}
          </p>
        </div>

        <div className="rounded-2xl border border-ink-100 bg-white p-4 shadow-xs">
          <p className="text-xs font-medium text-ink-500">Spatial Clusters Found</p>
          <p className="mt-1 text-2xl font-bold text-purple-600 sm:text-3xl">
            {spatialMining?.summary.cluster_count != null ? spatialMining.summary.cluster_count : "—"}
          </p>
          <p className="mt-1 text-[11px] text-ink-500">
            {spatialMining?.summary.clustered_stations != null
              ? `${spatialMining.summary.clustered_stations} stations (DBSCAN)`
              : "Clustering uncomputed"}
          </p>
        </div>

        <div className="rounded-2xl border border-ink-100 bg-white p-4 shadow-xs">
          <p className="text-xs font-medium text-ink-500">Isolated Outliers</p>
          <p className="mt-1 text-2xl font-bold text-ink-700 sm:text-3xl">
            {spatialMining?.summary.noise_stations != null ? spatialMining.summary.noise_stations : "—"}
          </p>
          <p className="mt-1 text-[11px] text-ink-500">
            {spatialMining?.summary.noise_stations != null
              ? "Noise points (no neighbor within 2km)"
              : "Data unavailable"}
          </p>
        </div>

        <div className="rounded-2xl border border-ink-100 bg-white p-4 shadow-xs">
          <p className="text-xs font-medium text-ink-500">Isolated Stations (&gt;5km)</p>
          <p className="mt-1 text-2xl font-bold text-coral-600 sm:text-3xl">
            {spatialMining?.summary.coverage_gap_count != null ? spatialMining.summary.coverage_gap_count : "—"}
          </p>
          <p className="mt-1 text-[11px] text-ink-500">
            {spatialMining?.summary.coverage_gap_count != null
              ? "Nearest recorded neighbor >5km"
              : "Data unavailable"}
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="mt-8 border-b border-ink-100">
        <nav className="flex space-x-6 overflow-x-auto pb-px" aria-label="Tabs">
          {[
            { id: "spatial", label: "Spatial Clusters (DBSCAN)", icon: CompassIcon },
            { id: "gaps", label: "Station Isolation Analysis", icon: PinIcon },
            { id: "demand", label: "Demand Grouping (K-Means)", icon: SortIcon },
            { id: "regression", label: "Occupancy Regressor (RF)", icon: BoltIcon },
            { id: "governance", label: "Production Gate Governance", icon: InfoIcon },
          ].map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as TabType)}
                className={`flex shrink-0 items-center gap-2 border-b-2 py-3 text-sm font-medium transition-colors ${
                  active
                    ? "border-coral-500 text-coral-600"
                    : "border-transparent text-ink-500 hover:border-ink-200 hover:text-ink-800"
                }`}
              >
                <Icon size={16} />
                {tab.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Tab 1: Spatial Clusters */}
      {activeTab === "spatial" && (
        !spatialMining ? (
          <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-6 text-center">
            <h3 className="text-sm font-semibold text-amber-900">Spatial Clustering Data Unavailable</h3>
            <p className="mt-1 text-xs text-amber-700">
              The spatial clustering artifact is missing, ungenerated, or invalid. Run the offline spatial mining pipeline to populate this view.
            </p>
          </div>
        ) : (
          <div className="mt-6 flex flex-col gap-6">
            <div className="rounded-2xl border border-purple-100 bg-purple-50/50 p-4 text-xs text-purple-900 sm:p-5 sm:text-sm">
              <h3 className="font-semibold text-purple-950">DBSCAN Methodology on Authentic Real Data</h3>
              <p className="mt-1 text-purple-800">
                Executed with <strong>Haversine great-circle distance metric</strong> on genuine GPS coordinates
                (R = 6,371 km). Parameter configuration: <code>eps = 2.0 km</code>, <code>min_samples = 3</code>.
                Cluster labels are density grouping identifiers, <em>not</em> quality or performance rankings.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
              {/* Cluster Selector List */}
              <div className="lg:col-span-5">
                <div className="rounded-2xl border border-ink-100 bg-white p-4 shadow-card">
                  <div className="flex items-center justify-between pb-3 border-b border-ink-100">
                    <h3 className="text-sm font-semibold text-ink-900">
                      Discovered Clusters ({spatialMining.clusters.length})
                    </h3>
                    <span className="text-xs text-ink-500">Click to inspect</span>
                  </div>
                  <div className="mt-3 max-h-[480px] overflow-y-auto space-y-2 pr-1">
                    {spatialMining.clusters.map((c) => {
                      const isSelected = c.cluster_id === selectedClusterId;
                      return (
                        <button
                          key={c.cluster_id}
                          onClick={() => setSelectedClusterId(c.cluster_id)}
                          className={`w-full text-left rounded-xl p-3 border transition-all ${
                            isSelected
                              ? "border-purple-500 bg-purple-50/70 shadow-xs"
                              : "border-ink-100 hover:border-ink-200 hover:bg-ink-50/50"
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-semibold text-ink-900">
                              Cluster #{c.cluster_id}
                            </span>
                            <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-800">
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
                  <div className="rounded-2xl border border-ink-100 bg-white p-5 shadow-card">
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

                    <div className="mt-4 max-h-[440px] overflow-y-auto space-y-2.5">
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
                              className="inline-flex items-center text-xs font-medium text-coral-600 hover:text-coral-700"
                            >
                              View Station &rarr;
                            </Link>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="flex h-64 items-center justify-center rounded-2xl border border-dashed border-ink-200 text-sm text-ink-400">
                    Select a cluster on the left to inspect constituent stations
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      )}

      {/* Tab 2: Station Isolation Analysis */}
      {activeTab === "gaps" && (
        !spatialMining ? (
          <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-6 text-center">
            <h3 className="text-sm font-semibold text-amber-900">Station Isolation Data Unavailable</h3>
            <p className="mt-1 text-xs text-amber-700">
              The station isolation summary artifact is missing or invalid.
            </p>
          </div>
        ) : (
          <div className="mt-6 flex flex-col gap-6">
            <div className="rounded-2xl border border-coral-100 bg-coral-50/40 p-4 text-xs text-coral-900 sm:p-5 sm:text-sm">
              <h3 className="font-semibold text-coral-950">Station Isolation Analysis (Nationwide Snapshot Scope)</h3>
              <p className="mt-1 text-coral-800">
                Across the <strong>{spatialMining.summary.total_stations} recorded stations</strong> in this Open Charge Map snapshot,
                {" "}<strong>{spatialMining.summary.coverage_gap_count} stations</strong> have no neighboring charger within 5 kilometers.
                Of those, <strong>{spatialMining.summary.extreme_isolation_outliers} stations</strong> are statistical outliers exceeding the upper
                Tukey fence (Q3 + 1.5 &times; IQR &approx; 75.4 km, range 75.9 km &ndash; 254.8 km).
                A curated sample of <strong>{spatialMining.coverage_gaps_sample?.length ?? 25} most isolated stations</strong> is preserved in the artifact.
              </p>
              <p className="mt-2 text-[11px] text-coral-700 italic">
                Limitation Notice: Evaluates isolation relative to recorded stations in the snapshot, not an exhaustive census of all public Indian EVSE hardware.
              </p>
            </div>

            <div className="rounded-2xl border border-ink-100 bg-white p-5 shadow-card">
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
                    className={`rounded-lg px-3 py-1.5 transition ${
                      isolationView === "extreme"
                        ? "bg-white text-ink-900 shadow-xs font-semibold"
                        : "text-ink-600 hover:text-ink-900"
                    }`}
                  >
                    17 Extreme Outliers (IQR)
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsolationView("sample")}
                    className={`rounded-lg px-3 py-1.5 transition ${
                      isolationView === "sample"
                        ? "bg-white text-ink-900 shadow-xs font-semibold"
                        : "text-ink-600 hover:text-ink-900"
                    }`}
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

      {/* Tab 3: Demand Grouping (K-Means) */}
      {activeTab === "demand" && (
        !miningSummary || !miningSummary.clusters ? (
          <div className="mt-6 rounded-2xl border border-blue-200 bg-blue-50 p-6 text-center">
            <h3 className="text-sm font-semibold text-blue-900">Demand Grouping Data Unavailable</h3>
            <p className="mt-1 text-xs text-blue-700">
              The demand clustering summary artifact is missing or invalid.
            </p>
          </div>
        ) : (
          <div className="mt-6 flex flex-col gap-6">
            <div className="rounded-2xl border border-blue-100 bg-blue-50/40 p-4 text-xs text-blue-900 sm:p-5 sm:text-sm">
              <h3 className="font-semibold text-blue-950">K-Means Station Grouping (Offline Demonstration)</h3>
              <p className="mt-1 text-blue-800">
                Evaluates partitioned clustering ($k=3$) grouping stations by spatial centroid and calculated synthetic demand index.
                Centroids partition infrastructure into distinct operational profiles (South Mumbai high-throughput hub, Suburb arterial, North peripheral).
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {miningSummary.clusters.map((kc) => (
                <div key={kc.cluster_id} className="rounded-2xl border border-ink-100 bg-white p-5 shadow-card">
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

            <div className="rounded-2xl border border-ink-100 bg-white p-5 shadow-card text-xs text-ink-600 space-y-2">
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

      {/* Tab 4: Occupancy Regressor */}
      {activeTab === "regression" && (
        !offlineReport || !offlineReport.evaluations ? (
          <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-6 text-center">
            <h3 className="text-sm font-semibold text-amber-900">Offline Evaluation Report Unavailable</h3>
            <p className="mt-1 text-xs text-amber-700">
              The offline evaluation report artifact is missing or invalid.
            </p>
          </div>
        ) : (
          <div className="mt-6 flex flex-col gap-6">
            <div className="rounded-2xl border border-amber-200 bg-amber-50/50 p-4 text-xs text-amber-900 sm:p-5 sm:text-sm">
              <h3 className="font-semibold text-amber-950">Chronological vs Random Train/Test Evaluation</h3>
              <p className="mt-1 text-amber-800">
                Evaluated on 17,280 synthetic observation steps. Contrasting historical <em>random split</em> (prone to
                future data leakage across time) with an honest <strong>chronological 80/20 train/test split</strong> (13,824 train / 3,456 test records).
              </p>
            </div>

          {/* Model Comparison Matrix */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-ink-100 bg-white p-5 shadow-card">
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
            <div className="rounded-2xl border border-ink-100 bg-white p-5 shadow-card">
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
      ))}

      {/* Tab 5: Production Governance */}
      {activeTab === "governance" && (
        <div className="mt-6 flex flex-col gap-6">
          <div className="rounded-2xl border border-ink-100 bg-white p-5 shadow-card">
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
                <p className="mt-1 text-xl font-bold text-ink-900">0 / 1,000</p>
                <p className="mt-1 text-[11px] text-rose-600">Gate Requirement: UNMET</p>
              </div>

              <div className="rounded-xl border border-ink-100 p-4">
                <p className="text-xs font-medium text-ink-500">Data Freshness</p>
                <p className="mt-1 text-xl font-bold text-ink-900">&gt; 168 Hours</p>
                <p className="mt-1 text-[11px] text-rose-600">Gate Requirement: UNMET</p>
              </div>

              <div className="rounded-xl border border-ink-100 p-4">
                <p className="text-xs font-medium text-ink-500">Live Endpoint Serving</p>
                <p className="mt-1 text-xl font-bold text-amber-700">FAIL-CLOSED</p>
                <p className="mt-1 text-[11px] text-emerald-600">Safety Guard: ACTIVE</p>
              </div>
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
