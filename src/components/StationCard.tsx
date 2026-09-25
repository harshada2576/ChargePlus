"use client";

import type { Station } from "@/data/types";
import {
  distanceKm,
  formatDistance,
  getMaxPowerKw,
  getTotalChargers,
} from "@/data/stations";
import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { StatusBadge } from "./StatusBadge";
import { Button } from "./Button";
import { HeartIcon, HeartFilledIcon, BoltIcon } from "./Icon";
import { cx } from "@/lib/util";
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
  const saved = isSaved(station.id);

  const dist = userLocation
    ? distanceKm(userLocation, { lat: station.lat, lng: station.lng })
    : null;
  const maxKw = getMaxPowerKw(station);
  const chargers = getTotalChargers(station);

  return (
    <article
      className={cx(
        "group relative flex flex-col rounded-[18px] border border-ink-100 bg-white p-4 shadow-card transition-shadow hover:shadow-card-hover",
        compact && "p-3.5"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/station/${station.id}`}
            className="line-clamp-2 text-[15.5px] font-semibold text-ink-900 hover:underline"
          >
            {station.name}
          </Link>
          <p className="mt-0.5 truncate text-[13px] text-ink-600">
            {station.operator} · {station.area}
          </p>
        </div>
        <button
          type="button"
          aria-label={saved ? t("common.remove") : t("common.save")}
          onClick={() => toggleSaved(station.id)}
          className={cx(
            "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border transition-colors",
            saved
              ? "border-coral-200 bg-coral-50 text-coral-700"
              : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50"
          )}
        >
          {saved ? <HeartFilledIcon size={18} /> : <HeartIcon size={18} />}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-700">
        {dist != null && (
          <span className="font-medium text-ink-900">
            {formatDistance(dist).value}{" "}
            {formatDistance(dist).unit === "m" ? t("common.m") : t("common.km")} away
          </span>
        )}
      </div>

      <div className="mt-3 flex items-center gap-3 text-[13px] text-ink-700">
        <div className="inline-flex items-center gap-1.5">
          <BoltIcon size={14} className="text-coral-600" />
          <span>{maxKw} kW</span>
        </div>
        <span className="text-ink-300">•</span>
        <span>{t("station.chargerCount", { n: chargers })}</span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {station.connectors.slice(0, 2).map((c) => (
          <span
            key={c.id}
            className="inline-flex items-center rounded-full bg-ink-100 px-2.5 py-0.5 text-[11.5px] font-medium text-ink-700"
          >
            {c.type}
          </span>
        ))}
      </div>

      <div className="mt-4 flex items-end justify-between gap-3">
        <div>
          <div className="text-[14px] font-semibold text-ink-900">
            {station.isFree
              ? "Free"
              : station.pricePerKwh == null
              ? t("station.priceUnavailable")
              : t("station.perKwh", { price: station.pricePerKwh })}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <StatusBadge status={station.status} size="sm" />
            <span className="text-[11.5px] text-ink-500">
              {station.minutesSinceUpdate == null
                ? t("station.availabilityUnavailable")
                : station.minutesSinceUpdate < 1
                ? t("station.updatedJustNow")
                : t("station.updatedMinutesAgo", { n: station.minutesSinceUpdate })}
            </span>
          </div>
        </div>
        <Link href={`/station/${station.id}`}>
          <Button variant="primary" size="sm">
            {t("common.viewStation")}
          </Button>
        </Link>
      </div>
    </article>
  );
}
