"use client";

import type { Station } from "@/data/types";
import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { BottomSheet } from "./BottomSheet";
import { Button } from "./Button";
import { StatusBadge } from "./StatusBadge";
import { HeartIcon, HeartFilledIcon } from "./Icon";
import { Link } from "@/i18n/Link";
import {
  distanceKm,
  formatDistance,
  getMaxPowerKw,
  getTotalChargers,
} from "@/data/stations";

export function StationPreviewSheet({
  station,
  userLocation,
  onClose,
}: {
  station: Station | null;
  userLocation?: { lat: number; lng: number } | null;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { toggleSaved, isSaved } = useSession();
  if (!station) return null;

  const saved = isSaved(station.id);
  const dist = userLocation
    ? distanceKm(userLocation, { lat: station.lat, lng: station.lng })
    : null;
  const maxKw = getMaxPowerKw(station);
  const chargers = getTotalChargers(station);

  return (
    <BottomSheet open={!!station} onClose={onClose} placement="bottom">
      <div className="-mt-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="line-clamp-2 text-[17px] font-semibold text-ink-900">
            {station.name}
          </h3>
          <p className="mt-0.5 truncate text-[13px] text-ink-600">
            {station.operator}
          </p>
        </div>
        <button
          type="button"
          onClick={() => toggleSaved(station.id)}
          aria-label={saved ? t("common.remove") : t("common.save")}
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-ink-200 bg-white text-ink-700 hover:bg-ink-50"
        >
          {saved ? <HeartFilledIcon size={18} /> : <HeartIcon size={18} />}
        </button>
      </div>

      <div className="mt-4 space-y-2 text-[13.5px] text-ink-700">
        {dist != null && (
          <p>
            <span className="font-semibold text-ink-900">
              {formatDistance(dist).value}{" "}
              {formatDistance(dist).unit === "m" ? t("common.m") : t("common.km")} away
            </span>
          </p>
        )}
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-medium text-ink-900">
            {station.connectors.map((c) => c.type).join(" · ")}
          </span>
          <span className="text-ink-300">·</span>
          <span>{maxKw} kW</span>
        </p>
        <p>
          <span className="font-medium text-ink-900">
            {t("station.chargerCount", { n: chargers })}
          </span>
        </p>
        <p className="text-[15px] font-semibold text-ink-900">
          {station.isFree
            ? "Free"
            : station.pricePerKwh == null
            ? t("station.priceUnavailable")
            : t("station.perKwh", { price: station.pricePerKwh })}
        </p>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <StatusBadge status={station.status} />
        <span className="text-[12px] text-ink-600">
          {station.minutesSinceUpdate == null
            ? t("station.availabilityUnavailable")
            : t("station.updatedMinutesAgo", { n: station.minutesSinceUpdate })}
        </span>
      </div>

      <div className="mt-5">
        <Link href={`/station/${station.id}`} onClick={onClose} className="block">
          <Button block size="lg" variant="primary">
            {t("common.viewStation")}
          </Button>
        </Link>
      </div>
    </BottomSheet>
  );
}
