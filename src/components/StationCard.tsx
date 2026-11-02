"use client";

import type { Station } from "@/data/types";
import {
  distanceKm,
  formatDistance,
  getMaxPowerKw,
  getTotalChargers,
} from "@/data/stations";
import { stationDetailHref } from "@/data/exploreQuery";
import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { useToast } from "@/components/Toast";
import { useRouter } from "next/navigation";
import { StatusBadge } from "./StatusBadge";
import { Button } from "./Button";
import { HeartIcon, HeartFilledIcon, BoltIcon } from "./Icon";
import { cx } from "@/lib/util";
import { stationPriceDisplay } from "@/lib/priceDisplay";
import { Link } from "@/i18n/Link";

export function StationCard({
  station,
  userLocation,
  compact = false,
}: {
  station: Station;
  userLocation?: { lat: number; lng: number } | null;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const { toggleSaved, isSaved } = useSession();
  const { show: showToast } = useToast();
  const router = useRouter();
  const saved = isSaved(station.id);

  async function handleToggleSaved() {
    const res = await toggleSaved(station.id);
    if (res === "login-required") router.push("/login");
    else if (res === "error") showToast(t("errors.network.body"));
  }

  const dist = userLocation
    ? distanceKm(userLocation, { lat: station.lat, lng: station.lng })
    : null;
  const maxKw = getMaxPowerKw(station);
  const chargers = getTotalChargers(station);
  const priceDisplay = stationPriceDisplay(station, t);

  return (
    <article
      className={cx(
        "group relative flex flex-col rounded-xl border border-ink-200/80 bg-white p-4 shadow-xs transition-all hover:border-coral-300 hover:shadow-card",
        compact && "p-3.5"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="inline-flex items-center rounded-md bg-ink-100/80 px-2 py-0.5 text-[11px] font-medium text-ink-700">
              {station.operator}
            </span>
            <span className="text-[12px] text-ink-500">· {station.area}</span>
          </div>
          <Link
            href={stationDetailHref(station.id)}
            className="mt-1 block line-clamp-2 text-[15px] font-semibold text-ink-900 group-hover:text-coral-700 transition-colors"
          >
            {station.name}
          </Link>
        </div>
        <button
          type="button"
          aria-label={saved ? t("common.remove") : t("common.save")}
          onClick={handleToggleSaved}
          className={cx(
            "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border transition-colors",
            saved
              ? "border-coral-200 bg-coral-50 text-coral-700"
              : "border-ink-200 bg-white text-ink-600 hover:bg-ink-50 hover:text-ink-900"
          )}
        >
          {saved ? <HeartFilledIcon size={16} /> : <HeartIcon size={16} />}
        </button>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink-600">
        {dist != null && (
          <span className="inline-flex items-center gap-1 font-medium text-ink-900 bg-ink-50 rounded px-1.5 py-0.5">
            <span className="text-coral-600">📍</span>
            {formatDistance(dist).value}{" "}
            {formatDistance(dist).unit === "m" ? t("common.m") : t("common.km")}
          </span>
        )}
        <div className="inline-flex items-center gap-1 font-medium text-ink-800">
          <BoltIcon size={13} className="text-coral-600" />
          <span>{maxKw > 0 ? `${maxKw} kW` : "—"}</span>
        </div>
        <span className="text-ink-300">•</span>
        <span>{chargers != null ? t("station.chargerCount", { n: chargers }) : "—"}</span>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {station.connectors.slice(0, 3).map((c) => (
          <span
            key={c.id}
            className="inline-flex items-center rounded-md border border-ink-100 bg-ink-50 px-2 py-0.5 text-[11px] font-medium text-ink-700"
          >
            {c.type}
            {c.powerKw ? ` (${c.powerKw}kW)` : ""}
          </span>
        ))}
      </div>

      <div className="mt-3.5 pt-3 border-t border-ink-100 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[14px] font-semibold tracking-tight text-ink-900">
            {priceDisplay.text}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {(station.isSimulated || station.sourceCategory === "simulated") && (
              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 border border-amber-200">
                Demo
              </span>
            )}
            {station.sourceCategory === "historical" && (
              <span className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-700">
                Historical
              </span>
            )}
            <StatusBadge status={station.status} size="sm" />
            <span className="text-[11px] text-ink-500 truncate max-w-[140px]">
              {station.minutesSinceUpdate == null
                ? t("station.availabilityUnavailable")
                : station.minutesSinceUpdate < 1
                ? t("station.updatedJustNow")
                : station.minutesSinceUpdate < 60
                ? t("station.updatedMinutesAgo", { n: station.minutesSinceUpdate })
                : t("station.updatedEarlier")}
            </span>
          </div>
        </div>
        <Button variant="primary" size="sm" href={stationDetailHref(station.id)}>
          {t("common.viewStation")}
        </Button>
      </div>
    </article>
  );
}
