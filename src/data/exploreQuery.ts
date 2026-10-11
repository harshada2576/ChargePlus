import type { FiltersState, SortKey, Station } from "./types";
import {
  distanceKm,
  getMaxPowerKw,
  getTotalChargers,
} from "./stations";
import { isValidCoordinate } from "@/lib/util";

export const DEFAULT_EXPLORE_FILTERS: FiltersState = {
  distanceKm: 0,
  connectorTypes: [],
  minPowerKw: 0,
  openNow: false,
  availableOnly: false,
  fastCharging: false,
  freeOnly: false,
  lessBusy: false,
  maxPrice: 0,
  minChargers: 0,
};

/**
 * Unknown-data filter policy (explicit, never guessed):
 * - availableOnly: matches status === "available" only. unknown/busy/broken are excluded.
 * - freeOnly: matches isFree === true only. null isFree is unknown, not free.
 * - maxPrice: unknown pricePerKwh is excluded (cannot prove it is under the cap).
 * - minPowerKw / fastCharging: unknown-only power (getMaxPowerKw === 0 from nulls) does not meet a positive kW threshold.
 * - minChargers: unknown quantity (null) is excluded; never treated as 1 charger.
 *   A station with zero connector records has known-zero chargers (0) and matches
 *   only a zero threshold (i.e. the filter off); a station whose connectors all have
 *   unknown quantity is excluded from any positive threshold.
 * - connectorTypes: Unknown connector types do not match CCS2/Type 2/etc. Selecting a
 *   specific connector type therefore excludes unknown-type stations.
 * - openNow: hours.kind === "unknown" does not match. Hours are evaluated in the
 *   device-local timezone; station-local timezone is not modeled (limitation).
 * - lessBusy: empty busyWindows (cold start) does not match.
 * - distanceKm: invalid/missing coordinates yield Infinity and fail a finite radius check.
 */
export function isOpenNow(s: Station, now: Date = new Date()): boolean {
  if (s.hours.kind === "24h") return true;
  if (s.hours.kind === "unknown") return false;
  const cur = now.getHours() * 60 + now.getMinutes();
  const [oh, om] = s.hours.open.split(":").map(Number);
  const [ch, cm] = s.hours.close.split(":").map(Number);
  const open = oh * 60 + om;
  const close = ch * 60 + cm;
  if (close <= open) return cur >= open || cur < close;
  return cur >= open && cur < close;
}

export function rankAvailability(s: Station): number {
  if (s.status === "available") return 0;
  if (s.status === "busy") return 1;
  if (s.status === "broken") return 2;
  return 3;
}

export type ExploreQueryInput = {
  query?: string;
  filters?: FiltersState;
  sort?: SortKey;
  userLoc?: { lat: number; lng: number } | null;
  now?: Date;
};

/**
 * Filter and sort a copy of the canonical collection.
 * Never mutates `stations`.
 */
export function filterAndSortStations(
  stations: readonly Station[],
  input: ExploreQueryInput = {}
): Station[] {
  const filters = input.filters ?? DEFAULT_EXPLORE_FILTERS;
  const sort = input.sort ?? "nearest";
  const userLoc = input.userLoc ?? null;
  const now = input.now ?? new Date();
  let list = stations.slice();
  const q = (input.query ?? "").trim().toLowerCase();
  if (q) {
    list = list.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.operator.toLowerCase().includes(q) ||
        s.area.toLowerCase().includes(q) ||
        s.address.toLowerCase().includes(q)
    );
  }
  if (filters.connectorTypes.length > 0) {
    list = list.filter((s) =>
      s.connectors.some((c) => filters.connectorTypes.includes(c.type))
    );
  }
  if (filters.minPowerKw > 0) {
    list = list.filter((s) => getMaxPowerKw(s) >= filters.minPowerKw);
  }
  if (filters.openNow) list = list.filter((s) => isOpenNow(s, now));
  if (filters.availableOnly) list = list.filter((s) => s.status === "available");
  if (filters.fastCharging) list = list.filter((s) => getMaxPowerKw(s) >= 50);
  if (filters.freeOnly) list = list.filter((s) => s.isFree === true);
  if (filters.maxPrice > 0) {
    list = list.filter(
      (s) => s.pricePerKwh != null && s.pricePerKwh <= filters.maxPrice
    );
  }
  if (filters.minChargers > 0) {
    list = list.filter((s) => {
      const c = getTotalChargers(s);
      return c != null && c >= filters.minChargers;
    });
  }
  if (filters.lessBusy) {
    list = list.filter((s) => s.busyWindows.length > 0);
  }
  if (filters.distanceKm > 0 && userLoc) {
    list = list.filter(
      (s) => distanceKm(userLoc, { lat: s.lat, lng: s.lng }) <= filters.distanceKm
    );
  }

  list.sort((a, b) => {
    if (sort === "nearest" && userLoc) {
      return (
        distanceKm(userLoc, { lat: a.lat, lng: a.lng }) -
        distanceKm(userLoc, { lat: b.lat, lng: b.lng })
      );
    }
    if (sort === "available") {
      return rankAvailability(a) - rankAvailability(b);
    }
    if (sort === "speed") {
      return getMaxPowerKw(b) - getMaxPowerKw(a);
    }
    if (sort === "price") {
      const ap = a.pricePerKwh ?? Number.POSITIVE_INFINITY;
      const bp = b.pricePerKwh ?? Number.POSITIVE_INFINITY;
      return ap - bp;
    }
    const ar = a.rating ?? 0;
    const br = b.rating ?? 0;
    return rankAvailability(a) - rankAvailability(b) || br - ar;
  });
  return list;
}

/** Stations that may be drawn as map markers. Missing/invalid coords are omitted, never replaced. */
export function mappableStations(stations: readonly Station[]): Station[] {
  return stations.filter((s) => isValidCoordinate(s.lat, s.lng));
}

export function toStationGeoJSON(stations: readonly Station[]): {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    id: string;
    properties: {
      id: string;
      name: string;
      operator: string;
      area: string;
      status: Station["status"];
      pricePerKwh: number | null;
      isFree: boolean | null;
      rating: number | null;
    };
    geometry: { type: "Point"; coordinates: [number, number] };
  }>;
} {
  return {
    type: "FeatureCollection",
    features: mappableStations(stations).map((s) => ({
      type: "Feature" as const,
      id: s.id,
      properties: {
        id: s.id,
        name: s.name,
        operator: s.operator,
        area: s.area,
        status: s.status,
        pricePerKwh: s.pricePerKwh,
        isFree: s.isFree,
        rating: s.rating,
      },
      geometry: {
        type: "Point" as const,
        coordinates: [s.lng, s.lat] as [number, number],
      },
    })),
  };
}

export function resolveSelectedStation(
  selectedId: string | null,
  filtered: readonly Station[],
  all: readonly Station[]
): Station | null {
  if (!selectedId) return null;
  return filtered.find((s) => s.id === selectedId) ?? all.find((s) => s.id === selectedId) ?? null;
}

/**
 * Visible selection for list/map/preview. When search/filters remove the selected
 * station from the visible set, the visible selection clears (no stale highlight,
 * marker popup, or preview) while the raw selectedId is retained so clearing the
 * search/filter restores it. Pure derivation — no state mutation, no refetch.
 */
export function visibleSelection(
  selectedId: string | null,
  filtered: readonly Station[]
): string | null {
  if (!selectedId) return null;
  return filtered.some((s) => s.id === selectedId) ? selectedId : null;
}

export function stationDetailHref(id: string): string {
  return `/station/${encodeURIComponent(id)}`;
}

export type ExploreLoadState = "loading" | "error" | "empty" | "ready";

export function exploreLoadState(
  loading: boolean,
  error: string | null,
  count: number
): ExploreLoadState {
  if (loading) return "loading";
  if (error) return "error";
  if (count === 0) return "empty";
  return "ready";
}
