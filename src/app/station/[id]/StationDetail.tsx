"use client";

import { useState } from "react";
import type { Station } from "@/data/types";
import {
  getAvailableChargers,
  getMaxPowerKw,
  getTotalChargers,
} from "@/data/stations";
import type { ApprovedReview } from "@/lib/reviews";
import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import { IconButton } from "@/components/IconButton";
import { Modal } from "@/components/Modal";
import { BottomSheet } from "@/components/BottomSheet";
import { StatusBadge } from "@/components/StatusBadge";
import { StarFilledIcon, StarIcon, HeartIcon, HeartFilledIcon, NavIcon, CheckIcon } from "@/components/Icon";
import {
  ChevronLeftIcon,
  BoltIcon,
  ClockIcon,
  AlertTriangleIcon,
} from "@/components/Icon";
import { Link } from "@/i18n/Link";
import { cx, externalMapUrl, isValidCoordinate } from "@/lib/util";
import { StationReportForm } from "@/components/StationReportForm";
import { StationReviewForm } from "@/components/StationReviewForm";
import { MapLibreMap } from "@/components/MapLibreMap";

export function StationDetail({ station, reviews }: { station: Station; reviews: ApprovedReview[] }) {
  const { t } = useI18n();
  const { isAuthed, toggleSaved, isSaved } = useSession();
  const { show: showToast } = useToast();

  const [navOpen, setNavOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [authPromptOpen, setAuthPromptOpen] = useState<null | "review" | "report" | "save">(null);

  const saved = isSaved(station.id);
  // Directions (in-app sheet and external map links) require real coordinates.
  // Without them the actions are omitted; area/address text still renders.
  const hasCoords = isValidCoordinate(station.lat, station.lng);

  async function handleSave() {
    if (!isAuthed) {
      setAuthPromptOpen("save");
      return;
    }
    const res = await toggleSaved(station.id);
    if (res === "login-required") {
      setAuthPromptOpen("save");
      return;
    }
    if (res === "error") {
      showToast(t("errors.network.body"));
      return;
    }
    showToast(saved ? t("common.removed") : "Station saved");
  }

  function handleReport() {
    if (!isAuthed) {
      setAuthPromptOpen("report");
      return;
    }
    setReportOpen(true);
  }

  function handleReview() {
    if (!isAuthed) {
      setAuthPromptOpen("review");
      return;
    }
    setReviewOpen(true);
  }

  return (
    <div className="bg-ink-50">
      <div className="mx-auto max-w-screen-lg px-4 pb-16 pt-3 sm:px-6">
        <Link
          href="/explore"
          className="inline-flex h-10 items-center gap-1 rounded-full px-2 text-[13.5px] font-medium text-ink-700 hover:bg-ink-100"
        >
          <ChevronLeftIcon size={16} />
          {t("common.back")}
        </Link>

        {/* Title row */}
        <header className="mt-1 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-[clamp(1.6rem,3.6vw,2.1rem)] font-semibold leading-tight text-ink-900">
              {station.name}
            </h1>
            <p className="mt-1 text-[14px] text-ink-700">
              {station.operator} · {station.area}
            </p>
            {station.rating != null && (
              <div className="mt-2 inline-flex items-center gap-1.5 text-[13px] text-ink-800">
                <span className="inline-flex items-center gap-0.5 text-coral-600">
                  <StarFilledIcon size={14} />
                </span>
                <span className="font-semibold">{station.rating.toFixed(1)}</span>
                <span className="text-ink-500">·</span>
                <span className="text-ink-600">{t("station.reviews.count", { n: station.reviewCount })}</span>
              </div>
            )}
          </div>
          <IconButton
            label={saved ? t("common.remove") : t("common.save")}
            onClick={handleSave}
            variant="subtle"
            size="lg"
          >
            {saved ? <HeartFilledIcon size={20} /> : <HeartIcon size={20} />}
          </IconButton>
        </header>

        {/* Navigate CTA */}
        {hasCoords && (
          <div className="mt-5">
            <Button
              block
              size="lg"
              variant="primary"
              iconLeft={<NavIcon size={18} />}
              onClick={() => setNavOpen(true)}
            >
              {t("station.navigate")}
            </Button>
          </div>
        )}

        {/* Location Mini-Map */}
        <section className="mt-6 overflow-hidden rounded-[20px] border border-ink-100 bg-white p-4 shadow-card">
          <div className="flex items-center justify-between pb-3">
            <div className="min-w-0 pr-2">
              <h2 className="text-[15px] font-semibold text-ink-900">{station.area}</h2>
              <p className="truncate text-[12.5px] text-ink-600">{station.address}</p>
            </div>
            {hasCoords && (
              <button
                onClick={() => setNavOpen(true)}
                className="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-medium text-coral-700 hover:underline"
              >
                <NavIcon size={14} />
                {t("station.navigate")}
              </button>
            )}
          </div>
          {hasCoords && (
            <div className="h-44 w-full overflow-hidden rounded-[14px]">
              <MapLibreMap
                stations={[station]}
                singleStation={station}
                showControls={false}
                interactive={true}
              />
            </div>
          )}
        </section>

        {/* Charging now */}
        <section className="mt-6 rounded-[20px] border border-ink-100 bg-white p-5 shadow-card">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-[15px] font-semibold text-ink-900">
              {t("station.chargingNow")}
            </h2>
            <div className="flex items-center gap-2">
              {station.sourceCategory === "simulated" && (
                <span className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-800 border border-amber-200">
                  Simulated Demo
                </span>
              )}
              {station.sourceCategory === "verified_live" && (
                <span className="inline-flex items-center rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-medium text-emerald-800 border border-emerald-200">
                  Verified Live
                </span>
              )}
              {station.sourceCategory === "historical" && (
                <span className="inline-flex items-center rounded-full bg-ink-100 px-2.5 py-0.5 text-[11px] font-medium text-ink-700 border border-ink-200">
                  Historical
                </span>
              )}
              <StatusBadge status={station.status} />
            </div>
          </div>
          <p className="mt-2 text-[13.5px] text-ink-700">
            {station.status === "unknown" || getAvailableChargers(station) == null || getTotalChargers(station) == null
              ? t("station.availabilityUnavailable")
              : t("station.availableOf", {
                  available: getAvailableChargers(station)!,
                  total: getTotalChargers(station)!,
                })}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-ink-500">
            <span>
              {station.minutesSinceUpdate == null
                ? t("station.availabilityUnavailable")
                : station.minutesSinceUpdate < 1
                ? t("station.updatedJustNow")
                : station.minutesSinceUpdate < 60
                ? t("station.updatedMinutesAgo", { n: station.minutesSinceUpdate })
                : t("station.updatedEarlier")}
            </span>
            {station.sourceName && (
              <>
                <span>•</span>
                <span>Source: {station.sourceName}</span>
              </>
            )}
            {station.latestObservationId && (
              <>
                <span>•</span>
                <span className="font-mono text-[11px]">Obs #{station.latestObservationId.slice(0, 8)}</span>
              </>
            )}
            {station.freshnessState && station.freshnessState !== "unknown" && (
              <span className={`rounded px-1.5 py-0.2 text-[10.5px] font-medium ${
                station.freshnessState === "fresh" ? "bg-emerald-50 text-emerald-700" :
                station.freshnessState === "aging" ? "bg-amber-50 text-amber-700" : "bg-ink-100 text-ink-600"
              }`}>
                {station.freshnessState.toUpperCase()}
              </span>
            )}
          </div>
        </section>

        {/* Chargers */}
        <section className="mt-4 rounded-[20px] border border-ink-100 bg-white p-5 shadow-card">
          <h2 className="text-[15px] font-semibold text-ink-900">{t("station.chargers")}</h2>
          <div className="mt-3 space-y-3">
            {station.connectors.map((c) => (
              <div
                key={c.id}
                className="flex items-center justify-between gap-3 rounded-[14px] border border-ink-100 bg-ink-50/40 px-4 py-3"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[14.5px] font-semibold text-ink-900">{c.type}</p>
                    {c.sourceCategory === "simulated" && (
                      <span className="rounded bg-amber-50 px-1.5 text-[10px] font-medium text-amber-700 border border-amber-200">
                        Demo
                      </span>
                    )}
                    {c.freshnessState === "stale" && (
                      <span className="rounded bg-ink-100 px-1.5 text-[10px] font-medium text-ink-600">
                        Stale
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[12px] text-ink-600">
                    <span className="inline-flex items-center gap-1">
                      <BoltIcon size={12} /> {c.powerKw != null ? `${c.powerKw} kW` : "—"}
                    </span>
                    {c.latestObservationId && (
                      <span className="font-mono text-[10.5px] text-ink-500">
                        Obs #{c.latestObservationId.slice(0, 8)}
                      </span>
                    )}
                  </div>
                </div>
                <p className="text-[13px] text-ink-700">
                  {station.status === "unknown" || c.available == null
                    ? t("station.availabilityUnavailable")
                    : c.available > 0
                    ? `${c.available} ${t("common.open")}`
                    : t("station.status.busy")}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Price */}
        <section className="mt-4 rounded-[20px] border border-ink-100 bg-white p-5 shadow-card">
          <h2 className="text-[15px] font-semibold text-ink-900">{t("station.price")}</h2>
          <p className="mt-2 text-[20px] font-semibold text-ink-900">
            {station.isFree === true
              ? "Free"
              : station.pricePerKwh == null
              ? t("station.priceUnavailable")
              : t("station.perKwh", { price: station.pricePerKwh })}
          </p>
          {station.isFree === true && (
            <p className="mt-1 text-[12.5px] text-ink-600">Public charging — please park considerately.</p>
          )}
        </section>

        {/* Hours */}
        <section className="mt-4 rounded-[20px] border border-ink-100 bg-white p-5 shadow-card">
          <h2 className="text-[15px] font-semibold text-ink-900">{t("station.hours")}</h2>
          <p className="mt-2 inline-flex items-center gap-2 text-[14px] text-ink-800">
            <ClockIcon size={16} className="text-coral-600" />
            {station.hours.kind === "24h"
              ? t("station.open24h")
              : station.hours.kind === "open-close"
              ? `${station.hours.open} – ${station.hours.close}`
              : t("station.hoursUnavailable")}
          </p>
        </section>

        {/* Usually busy */}
        <section className="mt-4 rounded-[20px] border border-ink-100 bg-white p-5 shadow-card">
          <h2 className="text-[15px] font-semibold text-ink-900">{t("station.usuallyBusy.title")}</h2>
          {station.busyWindows.length === 0 ? (
            <p className="mt-2 text-[13.5px] text-ink-700">{t("station.usuallyBusy.empty")}</p>
          ) : (
            <div className="mt-2 space-y-1.5">
              {station.busyWindows.map((w) => (
                <p key={w} className="inline-flex items-center gap-2 rounded-full bg-apricot-100 px-3 py-1.5 text-[12.5px] text-ink-900">
                  <AlertTriangleIcon size={14} className="text-coral-700" />
                  {w}
                </p>
              ))}
              <p className="mt-1 text-[12.5px] text-ink-600">{t("station.usuallyBusy.hint")}</p>
            </div>
          )}
        </section>

        {/* Reviews */}
        <section className="mt-4 rounded-[20px] border border-ink-100 bg-white p-5 shadow-card">
          <div className="flex items-center justify-between">
            <h2 className="text-[15px] font-semibold text-ink-900">{t("station.reviews.title")}</h2>
            <Button variant="secondary" size="sm" onClick={handleReview}>
              {t("station.review.submit")}
            </Button>
          </div>
          {reviews.length === 0 ? (
            <p className="mt-3 text-[13.5px] text-ink-700">{t("station.reviews.empty")}</p>
          ) : (
            <ul className="mt-3 space-y-3">
              {reviews.slice(0, 3).map((r) => (
                <li key={r.id} className="rounded-[14px] border border-ink-100 bg-ink-50/40 p-3.5">
                  <div className="flex items-center gap-1.5 text-coral-600">
                    {[1, 2, 3, 4, 5].map((i) => (
                      <span key={i}>
                        {i <= r.rating ? (
                          <StarFilledIcon size={14} />
                        ) : (
                          <StarIcon size={14} className="text-ink-300" />
                        )}
                      </span>
                    ))}
                  </div>
                  {r.comment && (
                    <p className="mt-2 text-[13.5px] text-ink-800">{r.comment}</p>
                  )}
                  <p className="mt-1.5 text-[12px] text-ink-500">
                    {r.author}
                    {r.createdAt &&
                      ` · ${new Date(r.createdAt).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}`}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Report CTA */}
        <div className="mt-6">
          <Button block size="lg" variant="secondary" onClick={handleReport}>
            {t("station.report.title")}
          </Button>
        </div>
      </div>

      {/* Navigate sheet */}
      {hasCoords && (
        <BottomSheet
          open={navOpen}
          onClose={() => setNavOpen(false)}
          title={t("station.navigateWith")}
          placement="bottom"
        >
          <ul className="space-y-2">
            <NavApp
              label={t("station.navigate.google")}
              onClick={() => openExternalMap("google", station)}
            />
            <NavApp
              label={t("station.navigate.apple")}
              onClick={() => openExternalMap("apple", station)}
            />
            <NavApp
              label={t("station.navigate.other")}
              onClick={() => openExternalMap("geo", station)}
            />
          </ul>
        </BottomSheet>
      )}

      {/* Report */}
      <BottomSheet
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        title={t("station.report.title")}
      >
        <StationReportForm
          stationId={station.id}
          onClose={() => setReportOpen(false)}
        />
      </BottomSheet>

      {/* Review */}
      <BottomSheet
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
        title={t("station.review.submit")}
      >
        <StationReviewForm
          stationId={station.id}
          onClose={() => setReviewOpen(false)}
        />
      </BottomSheet>

      {/* Auth prompt */}
      <Modal
        open={!!authPromptOpen}
        onClose={() => setAuthPromptOpen(null)}
        title={t("auth.prompt.title")}
      >
        <p className="text-[13.5px] text-ink-700">{t("auth.prompt.body")}</p>
        <div className="mt-4 flex gap-3">
          <Button
            variant="secondary"
            size="md"
            block
            onClick={() => setAuthPromptOpen(null)}
          >
            {t("common.notNow")}
          </Button>
          <Button variant="primary" size="md" block href="/login" className="flex-1">
            {t("common.continue")}
          </Button>
        </div>
      </Modal>
    </div>
  );
}

function NavApp({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <li>
      <button
        onClick={onClick}
        className="flex w-full items-center justify-between rounded-[14px] border border-ink-100 bg-white px-4 py-3 text-left hover:bg-ink-50"
      >
        <span className="text-[14.5px] font-medium text-ink-900">{label}</span>
        <CheckIcon size={16} className="text-coral-600" />
      </button>
    </li>
  );
}

function openExternalMap(kind: "google" | "apple" | "geo", s: Station) {
  const url = externalMapUrl(kind, s);
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}
