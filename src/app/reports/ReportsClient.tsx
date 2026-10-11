"use client";

import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { getStation } from "@/data/stations";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/Button";
import { InboxIcon, ExploreIcon, ClockIcon } from "@/components/Icon";
import { Link } from "@/i18n/Link";
import { AuthPrompt } from "../saved/SavedClient";

export function ReportsClient() {
  const { t } = useI18n();
  const { reports, isAuthed } = useSession();

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

      {reports.length === 0 ? (
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
            const station = getStation(r.stationId);
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
                      href={`/station/${r.stationId}`}
                      className="text-[15px] font-semibold text-ink-900 hover:underline"
                    >
                      {station?.name ?? "Charging Station"}
                    </Link>
                    <p className="mt-0.5 text-[12.5px] text-ink-600">
                      {station?.area ?? "Mumbai"}
                    </p>
                  </div>
                  <StatusBadge status={r.status} size="sm" />
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-ink-700">
                  <span className="inline-flex items-center gap-1 text-ink-500">
                    <ClockIcon size={13} />
                    {dateStr}
                  </span>
                  {r.queue && r.queue !== "none" && (
                    <span className="rounded-full bg-apricot-100 px-2 py-0.5 text-[11px] font-medium text-ink-800">
                      Queue: {r.queue}
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
