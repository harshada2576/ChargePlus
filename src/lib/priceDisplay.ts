import type { TranslationKey } from "@/i18n/types";

/**
 * Shared price-display contract for every station price surface
 * (StationCard, StationPreviewSheet, MapLibreMap popup, StationDetail).
 *
 * Free: `isFree === true` OR a validated finite zero verified tariff
 * (`pricePerKwh === 0`). This mirrors the free branch exploreQuery already
 * uses for `priceState`. A missing or invalid number (null/undefined/NaN/
 * ±Infinity) never establishes free status; a generic falsy check is never
 * used to infer free.
 *
 * Verified price: a finite number only. Invalid values are never formatted
 * as currency and never coerced to zero — they fall through to
 * estimate / unavailable.
 *
 * "Free" stays a hardcoded English literal here, matching all four surfaces'
 * existing behavior; localizing it is a separate finding.
 */

export type PriceStation = {
  isFree?: boolean | null;
  pricePerKwh?: number | null;
  connectors?: ReadonlyArray<{ priceEstimatePerKwh?: number | null }>;
};

export type PriceConnector = {
  pricePerKwh?: number | null;
  priceEstimatePerKwh?: number | null;
  pricePerSession?: number | null;
};

export type Translate = (
  key: TranslationKey,
  vars?: Record<string, string | number>
) => string;

export type StationPriceState = "free" | "verified" | "estimate" | "unavailable";
export type ConnectorPriceState = "verified" | "estimate" | "unavailable";

/** A displayable verified price: a finite number only (NaN/±Infinity invalid). */
export function isValidPrice(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Free = explicit isFree === true OR a validated finite zero tariff. */
export function isFreeStation(station: PriceStation): boolean {
  return (
    station.isFree === true ||
    (isValidPrice(station.pricePerKwh) && station.pricePerKwh === 0)
  );
}

export type StationPriceDisplay = {
  state: StationPriceState;
  text: string;
};

export function stationPriceDisplay(
  station: PriceStation,
  t: Translate
): StationPriceDisplay {
  if (isFreeStation(station)) return { state: "free", text: "Free" };
  if (isValidPrice(station.pricePerKwh)) {
    return {
      state: "verified",
      text: t("station.perKwh", { price: station.pricePerKwh.toFixed(2) }),
    };
  }
  if ((station.connectors ?? []).some((c) => isValidPrice(c.priceEstimatePerKwh))) {
    return { state: "estimate", text: t("station.estimateAvailable") };
  }
  return { state: "unavailable", text: t("station.priceUnavailable") };
}

export type ConnectorPriceDisplay = {
  state: ConnectorPriceState;
  /** null when nothing should render (no verified price, no eligible estimate). */
  text: string | null;
};

export function connectorPriceDisplay(
  connector: PriceConnector,
  t: Translate
): ConnectorPriceDisplay {
  if (isValidPrice(connector.pricePerKwh)) {
    return {
      state: "verified",
      text: t("station.perKwh", { price: connector.pricePerKwh.toFixed(2) }),
    };
  }
  if (isValidPrice(connector.priceEstimatePerKwh)) {
    return {
      state: "estimate",
      text: t("station.perKwh", { price: connector.priceEstimatePerKwh.toFixed(2) }),
    };
  }
  if (isValidPrice(connector.pricePerSession)) {
    return {
      state: "verified",
      text: t("station.perSession", { price: connector.pricePerSession.toFixed(2) }),
    };
  }
  return { state: "unavailable", text: null };
}
