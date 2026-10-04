"use client";

import { useCallback, useEffect, useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { fetchStations } from "@/data/stations";
import type { Station } from "@/data/types";
import { supabase } from "@/lib/supabase";
import { listReports, type ReportRecord } from "@/lib/reports";
import { stationDetailHref } from "@/data/exploreQuery";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/Button";
import { InboxIcon, ExploreIcon, ClockIcon, AlertTriangleIcon } from "@/components/Icon";
import { Link } from "@/i18n/Link";
import { AuthPrompt } from "../saved/SavedClient";

export function ReportsClient() {
  const { t } = useI18n();
  const { user, isAuthed, authReady } = useSession();
  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [stations, setStations] = useState<Station[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => {
    // State reset lives in the event handler, not the effect below.
    setLoading(true);
    setError(null);
    setNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    let active = true;
    // Unauthenticated branch renders AuthPrompt; no state reset needed here.
    if (!user) return;
    Promise.all([listReports(supabase, user.id), fetchStations()])
      .then(([mine, all]) => {
        if (!active) return;
        setReports(mine);
        setStations(all);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load reports");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [user, nonce]);

  if (!authReady) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
        <p className="text-center text-[13.5px] text-ink-600">{t("common.loading")}</p>
      </div>
    );
  }

  if (!isAuthed) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
        <AuthPrompt title={t("auth.prompt.title")} body={t("auth.prompt.body")} />
      </div>
    );
  }

  const byId = new Map(stations.map((s) => [s.id, s]));

  if (!isAuthed) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
        <AuthPrompt title={t("auth.prompt.title")} body={t("auth.prompt.body")} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-screen-md px-4 pb-10 pt-4 sm:px-6">
      <h1 className="text-[clamp(1.5rem,3vw,2rem)] font-semibold tracking-[-0.01em] text-ink-900">
        {t("profile.reports")}
      </h1>
      <p className="mt-1 text-[14px] text-ink-600">
        Reports submitted by you to keep community data fresh.
      </p>

      {loading ? (
        <p className="mt-8 text-center text-[13.5px] text-ink-600">{t("common.loading")}</p>
      ) : error ? (
        <div className="mt-8 rounded-[20px] border border-ink-100 bg-white p-8 text-center shadow-card">
          <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-red-50 text-red-600">
            <AlertTriangleIcon size={24} />
          </span>
          <h2 className="mt-3 text-[17px] font-semibold text-ink-900">{t("errors.network.title")}</h2>
          <p className="mt-1 text-[13.5px] text-ink-600">{t("errors.network.body")}</p>
          <div className="mt-5">
            <Button size="md" variant="primary" onClick={reload}>
              {t("common.tryAgain")}
            </Button>
          </div>
        </div>
      ) : reports.length === 0 ? (
        <div className="mt-8 rounded-[20px] border border-ink-100 bg-white p-8 text-center shadow-card">
          <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-coral-50 text-coral-700">
            <InboxIcon size={24} />
          </span>
          <h2 className="mt-3 text-[17px] font-semibold text-ink-900">No reports yet</h2>
          <p className="mt-1 text-[13.5px] text-ink-600">
            When you visit a charging station, report its real-time status and queue to help fellow drivers.
          </p>
          <div className="mt-5">
            <Link href="/explore">
              <Button size="md" variant="primary" iconLeft={<ExploreIcon size={16} />}>
                Find stations to report
              </Button>
            </Link>
          </div>
        </div>
      ) : (
        <ul className="mt-5 space-y-3">
          {reports.map((r) => {
            const station = byId.get(r.stationId);
            const dateStr = r.submittedAt
              ? new Date(r.submittedAt).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "Recently";

            return (
              <li
                key={r.id}
                className="rounded-[18px] border border-ink-100 bg-white p-4 shadow-card transition-shadow hover:shadow-card-hover"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link
                      href={stationDetailHref(r.stationId)}
                      className="text-[15px] font-semibold text-ink-900 hover:underline"
                    >
                      {station?.name ?? "Charging Station"}
                    </Link>
                    <p className="mt-0.5 text-[12.5px] text-ink-600">
                      {station?.area ?? "Area unknown"}
                    </p>
                  </div>
                  <StatusBadge status={r.status} size="sm" />
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-ink-700">
                  <span className="inline-flex items-center gap-1 text-ink-500">
                    <ClockIcon size={13} />
                    {dateStr}
                  </span>
                  {(r.queue === "short" || r.queue === "medium" || r.queue === "long") && (
                    <span className="rounded-full bg-apricot-100 px-2 py-0.5 text-[11px] font-medium text-ink-800">
                      Queue: {r.queue}
                    </span>
                  )}
                  {r.moderationStatus && r.moderationStatus !== "approved" && (
                    <span className="rounded-full bg-ink-100 px-2 py-0.5 text-[11px] font-medium text-ink-600">
                      Under review
                    </span>
                  )}
                </div>

                {r.note && (
                  <p className="mt-2.5 rounded-[12px] bg-ink-50 p-2.5 text-[13px] text-ink-800">
                    “{r.note}”
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
