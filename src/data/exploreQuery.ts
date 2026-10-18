import type { FiltersState, Recommendation, SortKey, Station } from "./types";
import {
  distanceKm,
  getAvailableChargers,
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

/**
 * How long to wait for map style readiness before treating a silent stall
 * (no `load`/`style.load` and no `error` event, e.g. a hanging style or tile
 * request) as an actionable map failure instead of a blank canvas.
 */
export const MAP_STYLE_TIMEOUT_MS = 12_000;

/**
 * Watchdog for silent map-style stalls. Resolves (disarms) when the style
 * becomes ready or the map is torn down; otherwise fires `onTimeout` once.
 * Pure timer logic — the map component owns all MapLibre calls.
 */
export function createMapLoadWatchdog(
  onTimeout: () => void,
  timeoutMs: number = MAP_STYLE_TIMEOUT_MS
): { resolve: () => void } {
  let done = false;
  const timer = setTimeout(() => {
    if (!done) {
      done = true;
      onTimeout();
    }
  }, timeoutMs);
  return {
    resolve() {
      done = true;
      clearTimeout(timer);
    },
  };
}

/**
 * Push fresh station data into an already-created map source.
 * Returns true when the source existed and was updated, false when there is
 * no source yet (creation happens on map load). Never throws for a missing
 * source — station fetches routinely complete after map initialization.
 */
export function refreshStationsSource(
  mapLike: { getSource: (id: string) => { setData: (data: unknown) => void } | undefined },
  stations: readonly Station[]
): boolean {
  const source = mapLike.getSource("stations");
  if (!source) return false;
  source.setData(toStationGeoJSON(stations));
  return true;
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

export type RecommendInput = {
  userLoc?: { lat: number; lng: number } | null;
  /** Active connector-type filter = the connector the user requires. */
  connectorTypes?: string[];
  /** Max recommendations; clamped to 1..3. */
  count?: number;
};

/**
 * Baseline recommender version stamped on every internal evaluation.
 * Bump only with architect (Agent 5) sign-off when weights/eligibility change.
 */
export const RECOMMENDER_VERSION = "baseline-v1";

/**
 * Documented additive weights for the deterministic baseline. All features
 * are bounded; missing features contribute 0 (never a penalty, never a guess).
 * - knownType/knownPower (+2 each): real connector evidence exists.
 * - verifiedPrice (+1): verified INR/kWh tariff or explicit free only.
 *   Unverified `priceEstimatePerKwh` NEVER contributes (anti-bias rule).
 * - genuinelyAvailable (+2): fresh explicit `available` + known count > 0 only.
 * - proximity (0..2 within 5 km): linear `2 - dist/5`, 0 beyond 5 km or
 *   without a user location. Straight-line Haversine, not travel time.
 */
export const RECOMMENDER_WEIGHTS = {
  knownType: 2,
  knownPower: 2,
  verifiedPrice: 1,
  genuinelyAvailable: 2,
  proximityMax: 2,
  proximityRadiusKm: 5,
} as const;

/** Machine-readable exclusion causes for the internal audit record. */
export type RecommendationExclusion =
  | "invalid-coordinates"
  | "broken-status"
  | "no-usable-evidence";

/**
 * Internal (never user-facing) per-candidate audit record. Reconstructs the
 * full decision: eligibility, exclusion causes, feature values, per-feature
 * contributions, availability/price evidence, final score and rank.
 * In-memory only — no persistence table approved yet (dependency documented
 * below). Never serialize to the DOM or an unauthenticated API.
 */
export type RecommendationEvaluation = {
  stationId: string;
  eligible: boolean;
  exclusionReasons: RecommendationExclusion[];
  features: {
    hasKnownType: boolean;
    hasKnownPower: boolean;
    /** Verified tariff/free only; estimates are recorded separately and score 0. */
    hasVerifiedPrice: boolean;
    hasUnverifiedEstimateOnly: boolean;
    genuinelyAvailable: boolean;
    availableCount: number | null;
    distanceKm: number | null;
  };
  contributions: {
    knownType: number;
    knownPower: number;
    verifiedPrice: number;
    availability: number;
    proximity: number;
  };
  score: number;
  /** 1-based rank among eligible candidates; null when ineligible. */
  rank: number | null;
  availabilityState: Station["status"];
  priceState: "verified" | "free" | "unverified-estimate-only" | "unavailable";
  recommenderVersion: string;
  evaluatedAt: string;
};

/**
 * Explicit stale guard shared by ranking. A station whose observation is
 * known-stale (freshnessState "stale" or minutesSinceUpdate > 120) must never
 * earn the `availableNow` bonus, even if `status === "available"` on a raw
 * record that bypassed the adapter's demotion. Unknown freshness (null) is
 * not evidence of staleness, so it does not block — absence of evidence
 * neither proves nor disproves availability.
 */
function isKnownStale(s: Station): boolean {
  if (s.freshnessState === "stale") return true;
  return s.minutesSinceUpdate != null && s.minutesSinceUpdate > 120;
}

/**
 * Evaluate every candidate (deduplicated by stationId, first occurrence wins)
 * into the internal audit representation. Ranking is deterministic:
 * score desc, distance asc (Infinity when unknown), id asc.
 *
 * Eligibility (hard, before scoring): valid coords, not broken, and at least
 * one usable evidence signal (known connector type/power OR verified price).
 * Connector-type match, availability, price and proximity are RANKING signals,
 * never eligibility overrides — a high score never resurrects an excluded
 * station. No model is consulted; this is the deterministic baseline.
 */
export function evaluateRecommendations(
  stations: readonly Station[],
  input: RecommendInput = {}
): RecommendationEvaluation[] {
  const userLoc = input.userLoc ?? null;
  const evaluatedAt = new Date().toISOString();
  const seen = new Set<string>();
  const unique: Station[] = [];
  for (const s of stations) {
    if (seen.has(s.id)) continue; // frontend maps DB rows 1:1; recs dedup defensively
    seen.add(s.id);
    unique.push(s);
  }

  const evaluated: RecommendationEvaluation[] = unique.map((s) => {
    const exclusionReasons: RecommendationExclusion[] = [];
    if (!isValidCoordinate(s.lat, s.lng)) exclusionReasons.push("invalid-coordinates");
    if (s.status === "broken") exclusionReasons.push("broken-status");
    const usableConnector = s.connectors.some(
      (c) => c.type !== "Unknown" || c.powerKw != null
    );
    // Verified tariffs only: station pricePerKwh/isFree derive from the
    // verified view column. Connector-level unverified estimates NEVER count.
    const hasVerifiedPrice = s.pricePerKwh != null || s.isFree === true;
    if (
      exclusionReasons.length === 0 &&
      !usableConnector &&
      !hasVerifiedPrice
    ) {
      exclusionReasons.push("no-usable-evidence");
    }
    const eligible = exclusionReasons.length === 0;

    const hasKnownType = s.connectors.some((c) => c.type !== "Unknown");
    const hasKnownPower = s.connectors.some((c) => c.powerKw != null);
    const hasUnverifiedEstimateOnly =
      !hasVerifiedPrice &&
      s.connectors.some((c) => c.priceEstimatePerKwh != null);
    const availableCount =
      s.status === "available" ? getAvailableChargers(s) : null;
    const genuinelyAvailable =
      eligible &&
      s.status === "available" &&
      availableCount != null &&
      availableCount > 0 &&
      !isKnownStale(s);
    const dist = userLoc
      ? distanceKm(userLoc, { lat: s.lat, lng: s.lng })
      : Number.POSITIVE_INFINITY;
    const distanceKmOrNull = userLoc && Number.isFinite(dist) ? dist : null;

    const W = RECOMMENDER_WEIGHTS;
    const contributions = {
      knownType: hasKnownType ? W.knownType : 0,
      knownPower: hasKnownPower ? W.knownPower : 0,
      verifiedPrice: hasVerifiedPrice ? W.verifiedPrice : 0,
      availability: genuinelyAvailable ? W.genuinelyAvailable : 0,
      proximity:
        userLoc && distanceKmOrNull != null && distanceKmOrNull <= W.proximityRadiusKm
          ? Math.max(0, W.proximityMax - distanceKmOrNull / W.proximityRadiusKm)
          : 0,
    };
    const score = eligible
      ? contributions.knownType +
        contributions.knownPower +
        contributions.verifiedPrice +
        contributions.availability +
        contributions.proximity
      : 0;

    const priceState =
      s.isFree === true || (s.pricePerKwh != null && s.pricePerKwh === 0)
        ? "free"
        : s.pricePerKwh != null
          ? "verified"
          : hasUnverifiedEstimateOnly
            ? "unverified-estimate-only"
            : "unavailable";

    return {
      stationId: s.id,
      eligible,
      exclusionReasons,
      features: {
        hasKnownType,
        hasKnownPower,
        hasVerifiedPrice,
        hasUnverifiedEstimateOnly,
        genuinelyAvailable,
        availableCount,
        distanceKm: distanceKmOrNull,
      },
      contributions,
      score,
      rank: null,
      availabilityState: s.status,
      priceState,
      recommenderVersion: RECOMMENDER_VERSION,
      evaluatedAt,
    };
  });

  const order = evaluated
    .filter((e) => e.eligible)
    .sort(
      (a, b) =>
        b.score - a.score ||
        (a.features.distanceKm ?? Number.POSITIVE_INFINITY) -
          (b.features.distanceKm ?? Number.POSITIVE_INFINITY) ||
        (a.stationId < b.stationId ? -1 : a.stationId > b.stationId ? 1 : 0)
    );
  order.forEach((e, i) => {
    e.rank = i + 1;
  });
  return evaluated;
}

/**
 * Recommend 1–3 eligible stations from real fetched records without inventing
 * availability. Works when telemetry is cold: unknown status is never evidence
 * for (or against) a station, and every reason is backed by source data:
 * known connector type, verified power, known price, proximity, or genuine
 * live availability. Stations without valid coordinates or without any usable
 * connector information (known type, known power, or known price) are
 * excluded, as are broken stations. Deterministic: score desc, distance asc,
 * id asc. The input list is expected to be already search/filter-constrained.
 * Consumer-safe projection of evaluateRecommendations — score, weights and
 * unknowns stay internal and never appear in the returned records.
 */
export function recommendStations(
  stations: readonly Station[],
  input: RecommendInput = {}
): Recommendation[] {
  const required = (input.connectorTypes ?? []).filter((c) => c && c !== "Unknown");
  const count = Math.min(3, Math.max(1, Math.floor(input.count ?? 3)));
  const byId = new Map<string, Station>();
  // First occurrence wins on duplicate ids (matches evaluateRecommendations).
  for (const s of stations) {
    if (!byId.has(s.id)) byId.set(s.id, s);
  }

  const evaluated = evaluateRecommendations(stations, input);
  const ranked = evaluated
    .filter((e) => e.eligible)
    .sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0))
    .slice(0, count);

  return ranked.map((e) => {
    const s = byId.get(e.stationId)!;
    const reasons: Recommendation["reasons"] = [];
    if (
      required.length > 0 &&
      s.connectors.some((c) => c.type !== "Unknown" && required.includes(c.type))
    ) {
      reasons.push("matchConnector");
    }
    if (e.features.hasKnownPower) reasons.push("knownPower");
    if (e.features.hasVerifiedPrice) reasons.push("priceAvailable");
    if (
      input.userLoc &&
      e.features.distanceKm != null &&
      e.features.distanceKm <= RECOMMENDER_WEIGHTS.proximityRadiusKm
    ) {
      reasons.push("nearby");
    }
    if (e.features.genuinelyAvailable) {
      reasons.push("availableNow");
    } else if (s.status === "unknown") {
      reasons.push("availabilityUnknown");
    }
    return {
      stationId: s.id,
      reasons,
      ...(e.features.genuinelyAvailable && e.features.availableCount != null
        ? { availableCount: e.features.availableCount }
        : {}),
    } as Recommendation;
  });
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
