"use client";

import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { STATIONS, getStation } from "@/data/stations";
import { BellIcon, CheckIcon } from "@/components/Icon";
import { Link } from "@/i18n/Link";
import { cx } from "@/lib/util";
import { AuthPrompt } from "../saved/SavedClient";

export function AlertsClient() {
  const { t } = useI18n();
  const { isAuthed, alerts, setAlertEnabled } = useSession();

  if (!isAuthed) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
        <AuthPrompt title={t("auth.prompt.title")} body={t("auth.prompt.body")} />
      </div>
    );
  }

  // Show toggleable alerts per saved station, defaulting to OFF for any station not yet configured.
  const savedIds = JSON.parse(
    typeof window !== "undefined" ? localStorage.getItem("chargeplus:saved") || "[]" : "[]"
  ) as string[];

  const myStations = savedIds.length > 0
    ? savedIds.map(getStation).filter(Boolean) as typeof STATIONS
    : STATIONS.slice(0, 4);

  return (
    <div className="mx-auto max-w-screen-md px-4 pb-10 pt-4 sm:px-6">
      <h1 className="text-[clamp(1.5rem,3vw,2rem)] font-semibold tracking-[-0.01em] text-ink-900">
        {t("alerts.title")}
      </h1>
      <p className="mt-1 text-[14px] text-ink-700">{t("alerts.subtitle")}</p>

      {myStations.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="mt-5 space-y-4">
          {myStations.map((s) => (
            <li
              key={s.id}
              className="rounded-[18px] border border-ink-100 bg-white p-4 shadow-card"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link href={`/station/${s.id}`} className="block">
                    <h3 className="truncate text-[14.5px] font-semibold text-ink-900 hover:underline">
                      {s.name}
                    </h3>
                  </Link>
                  <p className="text-[12.5px] text-ink-600">{s.area}</p>
                </div>
                <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-coral-50 text-coral-700">
                  <BellIcon size={14} />
                </span>
              </div>

              <div className="mt-3 space-y-2">
                <AlertToggle
                  label={t("alerts.type.available")}
                  desc={t("alerts.type.availableDesc")}
                  enabled={isEnabled(alerts, s.id, "available")}
                  onChange={(v) => setAlertEnabled(s.id, "available", v)}
                />
                <AlertToggle
                  label={t("alerts.type.lessBusy")}
                  desc={t("alerts.type.lessBusyDesc")}
                  enabled={isEnabled(alerts, s.id, "lessBusy")}
                  onChange={(v) => setAlertEnabled(s.id, "lessBusy", v)}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function isEnabled(
  alerts: ReturnType<typeof useSession>["alerts"],
  stationId: string,
  type: "available" | "lessBusy"
) {
  return alerts.find((a) => a.id === `${stationId}:${type}`)?.enabled ?? false;
}

function AlertToggle({
  label,
  desc,
  enabled,
  onChange,
}: {
  label: string;
  desc: string;
  enabled: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-[14px] border border-ink-100 bg-ink-50/40 px-3.5 py-3">
      <div className="min-w-0">
        <p className="text-[13.5px] font-medium text-ink-900">{label}</p>
        <p className="text-[12px] text-ink-600">{desc}</p>
      </div>
      <span
        role="switch"
        aria-checked={enabled}
        tabIndex={0}
        onClick={() => onChange(!enabled)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onChange(!enabled);
          }
        }}
        className={cx(
          "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors",
          enabled ? "bg-coral-600" : "bg-ink-200"
        )}
      >
        <span
          className={cx(
            "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-card transition-transform",
            enabled ? "translate-x-5" : "translate-x-0.5"
          )}
        />
      </span>
    </div>
  );
}

function EmptyState() {
  const { t } = useI18n();
  return (
    <div className="mt-8 rounded-[20px] border border-ink-100 bg-white p-8 text-center shadow-card">
      <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-coral-50 text-coral-700">
        <BellIcon size={22} />
      </span>
      <h2 className="mt-3 text-[17px] font-semibold text-ink-900">{t("alerts.empty.title")}</h2>
      <p className="mt-1 text-[13.5px] text-ink-600">{t("alerts.empty.body")}</p>
      <div className="mt-5 flex justify-center">
        <Link href="/explore" className="inline-flex items-center gap-1.5 text-[13.5px] font-medium text-coral-700">
          <CheckIcon size={14} /> {t("nav.findCharger")}
        </Link>
      </div>
    </div>
  );
}
