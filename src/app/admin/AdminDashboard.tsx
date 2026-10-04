"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "@/state/SessionProvider";
import { fetchStations } from "@/data/stations";
import type { Station } from "@/data/types";
import { supabase } from "@/lib/supabase";
import { isValidCoordinate } from "@/lib/util";
import {
  countApprovedReviews,
  listIngestionRuns,
  listPendingReports,
  listPendingReviews,
  moderateReport,
  moderateReview,
  type IngestionRun,
  type PendingReport,
  type PendingReview,
} from "@/lib/admin";
import { Link } from "@/i18n/Link";

export function AdminDashboard() {
  const { isAdmin, user, authReady } = useSession();
  const [activeTab, setActiveTab] = useState<string>("all");
  const [selectedStationFilter, setSelectedStationFilter] = useState<string>("all");
  const [stations, setStations] = useState<Station[]>([]);
  const [pendingReports, setPendingReports] = useState<PendingReport[]>([]);
  const [pendingReviews, setPendingReviews] = useState<PendingReview[]>([]);
  const [runs, setRuns] = useState<IngestionRun[]>([]);
  const [approvedCount, setApprovedCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [modPending, setModPending] = useState<Set<string>>(new Set());

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    setNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    let active = true;
    // Console data requires the server-truth admin role; RLS enforces it
    // again on every query below. Non-admins keep the restriction gate.
    if (!isAdmin) return;
    Promise.all([
      fetchStations(),
      listPendingReports(supabase),
      listPendingReviews(supabase),
      listIngestionRuns(supabase),
      countApprovedReviews(supabase),
    ])
      .then(([all, reports, reviews, ingestion, approved]) => {
        if (!active) return;
        setStations(all);
        setPendingReports(reports);
        setPendingReviews(reviews);
        setRuns(ingestion);
        setApprovedCount(approved);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Console data failed to load");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isAdmin, nonce]);

  async function handleModerate(
    kind: "report" | "review",
    id: string,
    approved: boolean
  ) {
    if (!user || modPending.has(id)) return;
    setModPending((prev) => new Set(prev).add(id));
    try {
      if (kind === "report") {
        await moderateReport(supabase, { id, approved, moderatorId: user.id });
        setPendingReports((prev) => prev.filter((r) => r.id !== id));
      } else {
        await moderateReview(supabase, { id, approved, moderatorId: user.id });
        setPendingReviews((prev) => prev.filter((r) => r.id !== id));
      }
    } catch {
      // Row stays queued; the error surfaces in the queue header below.
      setError("A moderation action failed. Retry it from the queue.");
    } finally {
      setModPending((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  // Gate check: If user does not have admin role, display restriction gate.
  // authReady waits for the session; the canonical role overlay lands just
  // after, so a real admin may briefly see the gate before it self-corrects.
  if (!authReady) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4 py-16">
        <p className="font-mono text-xs text-slate-400">Loading console…</p>
      </div>
    );
  }
  if (!isAdmin) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4 py-16">
        <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/90 p-8 shadow-2xl backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-red-500/10 text-red-400 border border-red-500/20">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <span className="rounded-md border border-slate-700 bg-slate-800 px-2.5 py-1 text-xs font-mono font-medium text-slate-400">
              HTTP 403 / RESTRICTED
            </span>
          </div>

          <h1 className="mt-5 text-xl font-bold tracking-tight text-white">
            Operations Console Restricted
          </h1>
          <p className="mt-2 text-sm text-slate-400 leading-relaxed">
            This administrative partition is strictly isolated from the driver application. Verified role permissions are required to access network telemetry, moderation queues, and ingestion pipelines.
          </p>

          <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="flex items-center justify-between text-xs font-mono">
              <span className="text-slate-400">Current User:</span>
              <span className="text-slate-200">{user ? user.contact : "Unauthenticated Guest"}</span>
            </div>
            <div className="mt-2 flex items-center justify-between text-xs font-mono">
              <span className="text-slate-400">Assigned Role:</span>
              <span className="text-amber-400">{user?.role || "standard_driver"}</span>
            </div>
          </div>

          <div className="mt-6 flex flex-col gap-3">
            <Link
              href="/"
              className="inline-flex h-10 w-full items-center justify-center rounded-xl border border-slate-700 bg-slate-800 px-4 text-sm font-medium text-slate-300 transition hover:bg-slate-700"
            >
              ← Return to Driver App
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const filteredStations = selectedStationFilter === "all"
    ? stations
    : stations.filter((s) => s.status === selectedStationFilter);

  if (loading) {
    return (
      <div className="min-h-screen pb-16">
        <main className="mx-auto max-w-7xl px-4 pt-6 sm:px-6">
          <p className="font-mono text-xs text-slate-400">Loading console data…</p>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen pb-16">
      {/* Top Console Navigation Bar */}
      <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="h-2.5 w-2.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="font-mono text-sm font-bold tracking-wider text-white">
                CHARGEPLUS
              </span>
              <span className="rounded bg-coral-500/20 px-1.5 py-0.5 text-[10px] font-mono font-semibold uppercase text-coral-400 border border-coral-500/30">
                OPS CONSOLE
              </span>
            </div>
            <span className="hidden text-xs text-slate-500 sm:inline">|</span>
            <span className="hidden font-mono text-xs text-slate-400 sm:inline">
              MUMBAI REGION (METRO 1)
            </span>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden rounded-full border border-slate-700 bg-slate-900 px-3 py-1 font-mono text-xs text-slate-300 md:flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              <span>Role: admin_operator</span>
            </div>
            <button
              onClick={reload}
              className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-300 hover:bg-slate-800 transition"
              title="Reload console data"
            >
              Reload
            </button>
            <Link
              href="/"
              className="rounded-lg bg-coral-600 px-3 py-1 text-xs font-medium text-white hover:bg-coral-500 transition"
            >
              Exit to Driver App
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 pt-6 sm:px-6">
        {/* KPI Strip — every value is measured; unmeasured phases show unavailable */}
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          <KpiCard label="Network Stations" value={String(stations.length)} sub={`${stations.filter((s) => s.status === "available").length} Available`} status="good" />
          <KpiCard label="Pending Reports" value={String(pendingReports.length)} sub="Awaiting moderation" status={pendingReports.length > 0 ? "warn" : "good"} />
          <KpiCard label="Reviews Approved" value={approvedCount == null ? "—" : String(approvedCount)} sub="Published to drivers" status="neutral" />
          <KpiCard label="Info Quality Score" value="—" sub="Phase 4 analytics" status="neutral" />
          <KpiCard label="Latest Ingestion" value={runs[0]?.state ?? "—"} sub={runs[0] ? `${runs[0].sourceName} · ${runs[0].scope}` : "No runs recorded"} status={runs[0]?.state === "FAILED" ? "warn" : "neutral"} />
          <KpiCard label="Model Status" value="—" sub="No model deployed" status="neutral" />
        </section>
        {error && (
          <p className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 font-mono text-xs text-red-300">
            {error}
          </p>
        )}

        {/* Console Sections Grid covering all 7 Spec §56 areas */}
        <div className="mt-8 space-y-8">
          {/* Section 1: Station Management */}
          <section id="station-management" className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="rounded bg-indigo-500/20 px-2 py-0.5 font-mono text-xs font-semibold text-indigo-400 border border-indigo-500/30">
                    AREA 1
                  </span>
                  <h2 className="text-lg font-bold text-white">Station Management</h2>
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  Directory of charging stations, hardware status, and operator telemetry synchronization.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs font-mono text-slate-400">Status:</span>
                {(["all", "available", "busy", "broken", "unknown"] as const).map((st) => (
                  <button
                    key={st}
                    onClick={() => setSelectedStationFilter(st)}
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium capitalize transition ${
                      selectedStationFilter === st
                        ? "bg-slate-700 text-white"
                        : "bg-slate-800 text-slate-400 hover:bg-slate-700/60"
                    }`}
                  >
                    {st}
                  </button>
                ))}
              </div>
            </div>

            <div className="mt-4 overflow-x-auto rounded-xl border border-slate-800">
              <table className="w-full text-left font-mono text-xs">
                <thead className="border-b border-slate-800 bg-slate-950/60 text-slate-400">
                  <tr>
                    <th className="px-4 py-2.5">ID / Name</th>
                    <th className="px-4 py-2.5">Operator</th>
                    <th className="px-4 py-2.5">Area</th>
                    <th className="px-4 py-2.5">Status</th>
                    <th className="px-4 py-2.5">Connectors</th>
                    <th className="px-4 py-2.5 text-right">Coordinates</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 bg-slate-900/40 text-slate-300">
                  {filteredStations.slice(0, 6).map((s) => (
                    <tr key={s.id} className="hover:bg-slate-800/40 transition">
                      <td className="px-4 py-3 font-semibold text-white truncate max-w-[220px]">
                        {s.name}
                      </td>
                      <td className="px-4 py-3 text-slate-400">{s.operator}</td>
                      <td className="px-4 py-3">{s.area}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium capitalize ${
                          s.status === "available"
                            ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                            : s.status === "busy"
                            ? "bg-amber-500/15 text-amber-400 border border-amber-500/30"
                            : s.status === "broken"
                            ? "bg-red-500/15 text-red-400 border border-red-500/30"
                            : "bg-slate-500/15 text-slate-400 border border-slate-500/30"
                        }`}>
                          {s.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-400">
                        {s.connectors.map((c) => c.type).join(", ")}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-500">
                        {isValidCoordinate(s.lat, s.lng)
                          ? `${s.lat.toFixed(4)}, ${s.lng.toFixed(4)}`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* 2-Column: Report Moderation & Review Moderation */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Section 2: Report Moderation */}
            <section id="report-moderation" className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
              <div className="flex items-center gap-2">
                <span className="rounded bg-amber-500/20 px-2 py-0.5 font-mono text-xs font-semibold text-amber-400 border border-amber-500/30">
                  AREA 2
                </span>
                <h2 className="text-lg font-bold text-white">Report Moderation</h2>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Driver-submitted status updates and crowd queue reports pending verification.
              </p>

              {pendingReports.length === 0 ? (
                <div className="mt-4 rounded-xl border border-dashed border-slate-800 bg-slate-950/40 p-6 text-center">
                  <p className="text-xs font-mono text-slate-500">
                    No pending unmoderated reports in queue.
                  </p>
                  <p className="mt-1 text-[11px] text-slate-600">
                    Driver reports enter moderation as pending after server submission.
                  </p>
                </div>
              ) : (
                <ul className="mt-4 space-y-2.5">
                  {pendingReports.map((r) => (
                    <li key={r.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-mono text-slate-300 font-medium">Station ID: {r.stationId}</span>
                        <span className="font-mono text-slate-500">{r.queue && r.queue !== "none" ? `Queue: ${r.queue}` : r.status}</span>
                      </div>
                      {r.note && <p className="mt-1.5 text-xs text-slate-300 italic">“{r.note}”</p>}
                      <div className="mt-2 flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleModerate("report", r.id, true)}
                          disabled={modPending.has(r.id)}
                          className="rounded bg-emerald-600/20 px-2 py-1 text-[11px] font-medium text-emerald-400 hover:bg-emerald-600/30 border border-emerald-500/30 disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => handleModerate("report", r.id, false)}
                          disabled={modPending.has(r.id)}
                          className="rounded bg-red-600/20 px-2 py-1 text-[11px] font-medium text-red-400 hover:bg-red-600/30 border border-red-500/30 disabled:opacity-50"
                        >
                          Dismiss
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Section 3: Review Moderation */}
            <section id="review-moderation" className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
              <div className="flex items-center gap-2">
                <span className="rounded bg-cyan-500/20 px-2 py-0.5 font-mono text-xs font-semibold text-cyan-400 border border-cyan-500/30">
                  AREA 3
                </span>
                <h2 className="text-lg font-bold text-white">Review Moderation</h2>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Driver commentary, accessibility issues, and ratings quality control.
              </p>

              {pendingReviews.length === 0 ? (
                <div className="mt-4 rounded-xl border border-dashed border-slate-800 bg-slate-950/40 p-6 text-center">
                  <p className="text-xs font-mono text-slate-500">
                    No pending reviews in queue.
                  </p>
                  <p className="mt-1 text-[11px] text-slate-600">
                    Driver reviews enter moderation as pending after server submission.
                  </p>
                </div>
              ) : (
                <ul className="mt-4 space-y-2.5">
                  {pendingReviews.map((rv) => (
                    <li key={rv.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-mono text-slate-300">Station ID: {rv.stationId}</span>
                        <span className="text-amber-400">{"★".repeat(rv.rating)}</span>
                      </div>
                      {rv.comment && <p className="mt-1.5 text-xs text-slate-300">{rv.comment}</p>}
                      <div className="mt-2 flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleModerate("review", rv.id, true)}
                          disabled={modPending.has(rv.id)}
                          className="rounded bg-emerald-600/20 px-2 py-1 text-[11px] font-medium text-emerald-400 hover:bg-emerald-600/30 border border-emerald-500/30 disabled:opacity-50"
                        >
                          Publish
                        </button>
                        <button
                          onClick={() => handleModerate("review", rv.id, false)}
                          disabled={modPending.has(rv.id)}
                          className="rounded bg-slate-800 px-2 py-1 text-[11px] font-medium text-slate-400 hover:bg-slate-700 disabled:opacity-50"
                        >
                          Hide
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          {/* 2-Column: Information Quality & Ingestion Health */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Section 4: Information Quality */}
            <section id="info-quality" className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
              <div className="flex items-center gap-2">
                <span className="rounded bg-emerald-500/20 px-2 py-0.5 font-mono text-xs font-semibold text-emerald-400 border border-emerald-500/30">
                  AREA 4
                </span>
                <h2 className="text-lg font-bold text-white">Information Quality</h2>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Confidence heuristics, stale status detection, and data discrepancy scoring.
              </p>

              <div className="mt-4 space-y-3">
                <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs font-mono">
                  <span className="text-slate-300">Confidence Threshold</span>
                  <span className="text-emerald-400 font-semibold">≥ 85.0% Required</span>
                </div>
                <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs font-mono">
                  <span className="text-slate-300">Stale Telemetry Rule</span>
                  <span className="text-slate-400">&gt; 60 min marks as &apos;Unknown&apos;</span>
                </div>
                <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs font-mono">
                  <span className="text-slate-300">Conflicting Reports</span>
                  <span className="text-slate-400">Not evaluated</span>
                </div>
              </div>
            </section>

            {/* Section 5: Ingestion Health */}
            <section id="ingestion-health" className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
              <div className="flex items-center gap-2">
                <span className="rounded bg-violet-500/20 px-2 py-0.5 font-mono text-xs font-semibold text-violet-400 border border-violet-500/30">
                  AREA 5
                </span>
                <h2 className="text-lg font-bold text-white">Ingestion Health</h2>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Recorded ingestion runs from the operations pipeline (public.ingestion_runs).
              </p>

              <div className="mt-4 space-y-2.5">
                {runs.length === 0 ? (
                  <p className="rounded-xl border border-dashed border-slate-800 bg-slate-950/40 p-4 text-center font-mono text-xs text-slate-500">
                    No ingestion runs recorded.
                  </p>
                ) : (
                  runs.map((run) => (
                    <IngestionRow
                      key={run.id}
                      name={`${run.sourceName} · ${run.scope}`}
                      status={run.state === "SUCCEEDED" ? "Healthy" : run.state === "FAILED" ? "Failed" : run.state}
                      lag={run.durationSeconds != null ? `${run.durationSeconds}s run` : "—"}
                      rate={`${run.recordsAccepted} accepted / ${run.recordsFetched} fetched`}
                    />
                  ))
                )}
              </div>
            </section>
          </div>

          {/* 2-Column: Forecast/Model Status & System Health */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Section 6: Forecast / Model Status */}
            <section id="forecast-status" className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
              <div className="flex items-center gap-2">
                <span className="rounded bg-rose-500/20 px-2 py-0.5 font-mono text-xs font-semibold text-rose-400 border border-rose-500/30">
                  AREA 6
                </span>
                <h2 className="text-lg font-bold text-white">Forecast / Model Status</h2>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Machine learning queue predictions and busy-window inference accuracy.
              </p>

              <div className="mt-4 grid grid-cols-2 gap-3 text-xs font-mono">
                <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
                  <p className="text-slate-500">Model Version</p>
                  <p className="mt-1 font-bold text-slate-200">None deployed</p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
                  <p className="text-slate-500">Inference Acc</p>
                  <p className="mt-1 font-bold text-slate-400">—</p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
                  <p className="text-slate-500">Drift Deviation</p>
                  <p className="mt-1 font-bold text-slate-400">—</p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
                  <p className="text-slate-500">Next Retrain</p>
                  <p className="mt-1 font-bold text-slate-400">—</p>
                </div>
              </div>
              <p className="mt-2 text-[11px] text-slate-600">
                Forecasting ships in Phase 5; no model is deployed or measured.
              </p>
            </section>

            {/* Section 7: System Health */}
            <section id="system-health" className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
              <div className="flex items-center gap-2">
                <span className="rounded bg-teal-500/20 px-2 py-0.5 font-mono text-xs font-semibold text-teal-400 border border-teal-500/30">
                  AREA 7
                </span>
                <h2 className="text-lg font-bold text-white">System Health</h2>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Database connection pools, tile CDN response latency, and service SLA monitors.
              </p>

              <div className="mt-4 space-y-2.5 font-mono text-xs">
                <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/50 p-3">
                  <span className="text-slate-300">PostgreSQL Pool (Drizzle)</span>
                  <span className="text-slate-500">Not monitored</span>
                </div>
                <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/50 p-3">
                  <span className="text-slate-300">OpenFreeMap Vector CDN</span>
                  <span className="text-slate-500">Not monitored</span>
                </div>
                <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/50 p-3">
                  <span className="text-slate-300">Application Uptime</span>
                  <span className="text-slate-500">Not monitored</span>
                </div>
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  status,
}: {
  label: string;
  value: string;
  sub: string;
  status: "good" | "warn" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3.5 shadow">
      <p className="font-mono text-[11px] text-slate-400 truncate">{label}</p>
      <p className={`mt-1 text-xl font-bold font-mono ${
        status === "good" ? "text-white" : status === "warn" ? "text-amber-400" : "text-slate-300"
      }`}>
        {value}
      </p>
      <p className="mt-0.5 text-[11px] text-slate-500 font-mono truncate">{sub}</p>
    </div>
  );
}

function IngestionRow({
  name,
  status,
  lag,
  rate,
}: {
  name: string;
  status: string;
  lag: string;
  rate: string;
}) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-2.5 text-xs font-mono">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${status === "Healthy" ? "bg-emerald-400" : "bg-slate-600"}`} />
        <span className="text-slate-200">{name}</span>
      </div>
      <div className="flex items-center gap-4 text-slate-400">
        <span>Lag: {lag}</span>
        <span className="text-slate-500">{rate}</span>
      </div>
    </div>
  );
}
