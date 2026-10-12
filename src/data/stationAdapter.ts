import type { Connector, ConnectorType, FreshnessState, SourceCategory, Station, StationStatus } from "./types";

export type DbStationRow = {
  id: string;
  slug?: string | null;
  name: string;
  operator_id?: string | null;
  operator_name?: string | null;
  operator_slug?: string | null;
  operator_website?: string | null;
  operator_phone?: string | null;
  address_line?: string | null;
  locality?: string | null;
  city?: string | null;
  state?: string | null;
  postal_code?: string | null;
  country?: string | null;
  latitude: number | string | null;
  longitude: number | string | null;
  geom?: string | null;
  is_24_hours?: boolean | null;
  opening_time?: string | null;
  closing_time?: string | null;
  access_type?: string | null;
  operational_status?: string | null;
  phone?: string | null;
  website_url?: string | null;
  last_verified_at?: string | null;
  updated_at?: string | null;
  total_connector_types?: number | null;
  total_plugs?: number | null;
  max_power_kw?: number | null;
  min_price_per_kwh?: number | null;
  connector_types?: string[] | null;
  latest_observation_id?: string | null;
  latest_availability_status?: string | null;
  latest_queue_level?: string | null;
  latest_available_connectors?: number | null;
  latest_observed_total_connectors?: number | null;
  latest_observed_at?: string | null;
  minutes_since_observation?: number | null;
  avg_rating?: number | null;
  review_count?: number | null;
  source_id?: string | null;
  source_name?: string | null;
  is_simulated?: boolean | null;
};

export type DbConnectorRow = {
  id: string;
  station_id: string;
  connector_type: string;
  charging_standard?: string | null;
  power_kw?: number | null;
  total_quantity?: number | null;
  pricing_type?: string | null;
  price_per_kwh?: number | null;
  price_per_session?: number | null;
  currency?: string | null;
  latest_observation_id?: string | null;
  latest_availability_status?: string | null;
  latest_available_connectors?: number | null;
  latest_observed_at?: string | null;
  minutes_since_observation?: number | null;
  source_id?: string | null;
  source_name?: string | null;
  is_simulated?: boolean | null;
};

/**
 * Normalizes raw connector string to known standards without fabricating unsupported types.
 * Unrecognized or missing types return "Unknown".
 */
export function normalizeConnectorType(raw: string | null | undefined): ConnectorType {
  if (!raw || !raw.trim()) return "Unknown";
  const upper = raw.trim().toUpperCase();

  if (upper.includes("CCS2") || upper.includes("CCS 2") || upper.includes("COMBO 2") || upper.includes("62196-3")) {
    return "CCS2";
  }
  if (upper.includes("CCS1") || upper.includes("CCS 1") || upper.includes("COMBO 1")) {
    return "CCS1";
  }
  if (upper.includes("CHADEMO")) {
    return "CHAdeMO";
  }
  if (upper.includes("TYPE 2") || upper.includes("MENNEKES") || upper.includes("62196-2")) {
    return "Type 2";
  }
  if (upper.includes("TYPE 1") || upper.includes("J1772")) {
    return "Type 1";
  }
  if (upper.includes("BHARAT") || upper.includes("AC001") || upper.includes("AC 001")) {
    return "Bharat AC001";
  }

  if (["CCS2", "CCS1", "CHAdeMO", "Type 2", "Type 1", "Bharat AC001"].includes(raw.trim())) {
    return raw.trim() as ConnectorType;
  }

  return "Unknown";
}

/**
 * Evaluates the categorical freshness state of an observation.
 * Follows Step 2.9 Invariants: fresh <= 30m, aging <= 120m, stale > 120m, unknown if missing/invalid.
 */
export function deriveFreshnessState(
  minutesSinceObservation: number | null | undefined,
  staleThresholdMinutes = 120
): FreshnessState {
  if (minutesSinceObservation == null || isNaN(Number(minutesSinceObservation))) {
    return "unknown";
  }
  const mins = Number(minutesSinceObservation);
  if (mins < 0) return "unknown";
  if (mins <= 30) return "fresh";
  if (mins <= staleThresholdMinutes) return "aging";
  return "stale";
}

/**
 * Maps provenance signals to one of the 5 authoritative source categories.
 */
export function deriveSourceCategory(params: {
  isSimulated?: boolean;
  hasObservation: boolean;
  freshness: FreshnessState;
  sourceName?: string | null;
}): SourceCategory {
  if (params.isSimulated) {
    return "simulated";
  }
  if (!params.hasObservation) {
    return "unknown";
  }
  if (params.freshness === "stale") {
    return "historical";
  }
  if (params.sourceName && /cpo|ocpi|oicp|live|verified/i.test(params.sourceName)) {
    return "verified_live";
  }
  return "recent_observation";
}

/**
 * Derives operational status. Telemetry observations take strict precedence.
 * Without telemetry, operational stations resolve to "unknown" (Rule 5: static != live).
 * Expired observations (> 120 min) are marked unknown to prevent projecting false availability (Rule 4).
 */
export function deriveStationStatus(
  latestAvailabilityStatus: string | null | undefined,
  operationalStatus: string | null | undefined,
  minutesSinceObservation?: number | null,
  staleThresholdMinutes = 120
): StationStatus {
  // If observation is explicitly stale (> threshold), it cannot guarantee current availability
  if (
    minutesSinceObservation != null &&
    !isNaN(Number(minutesSinceObservation)) &&
    Number(minutesSinceObservation) > staleThresholdMinutes
  ) {
    const op = (operationalStatus || "").trim().toLowerCase();
    if (op === "temporarily_unavailable" || op === "decommissioned" || op === "out_of_service") {
      return "broken";
    }
    return "unknown";
  }

  if (latestAvailabilityStatus) {
    const s = latestAvailabilityStatus.trim().toLowerCase();
    if (s === "available") return "available";
    if (s === "busy" || s === "in_use" || s === "occupied") return "busy";
    if (s === "broken" || s === "out_of_service" || s === "offline" || s === "faulted") return "broken";
    return "unknown";
  }

  const op = (operationalStatus || "").trim().toLowerCase();
  if (op === "temporarily_unavailable" || op === "decommissioned" || op === "out_of_service") {
    return "broken";
  }

  return "unknown";
}

/**
 * Composes physical address from explicit source fields only.
 * Does not synthesize addresses or presume cities.
 */
export function deriveAddress(row: DbStationRow): string {
  const parts = [
    row.address_line,
    row.locality,
    row.city,
    row.state,
    row.postal_code,
    row.country,
  ]
    .map((s) => s?.trim())
    .filter((s): s is string => Boolean(s && s.length > 0));

  const uniqueParts: string[] = [];
  for (const part of parts) {
    if (!uniqueParts.some((p) => p.toLowerCase() === part.toLowerCase())) {
      uniqueParts.push(part);
    }
  }

  if (uniqueParts.length > 0) {
    return uniqueParts.join(", ");
  }
  return "Address unavailable";
}

/**
 * Derives locality/area descriptor from explicit location hierarchy.
 * Never invents a presumed city when unstated.
 */
export function deriveArea(row: DbStationRow): string {
  if (row.locality && row.locality.trim().length > 0) {
    return row.locality.trim();
  }
  if (row.city && row.city.trim().length > 0) {
    return row.city.trim();
  }
  if (row.state && row.state.trim().length > 0) {
    return row.state.trim();
  }
  return "Area unknown";
}

export function deriveHours(row: DbStationRow): Station["hours"] {
  if (row.is_24_hours === true) {
    return { kind: "24h" };
  }
  if (row.opening_time && row.closing_time) {
    return {
      kind: "open-close",
      open: String(row.opening_time).slice(0, 5),
      close: String(row.closing_time).slice(0, 5),
    };
  }
  return { kind: "unknown" };
}

export function derivePricing(row: DbStationRow): {
  pricePerKwh: number | null;
  isFree: boolean | null;
} {
  if (row.min_price_per_kwh != null && !isNaN(Number(row.min_price_per_kwh))) {
    const price = Number(row.min_price_per_kwh);
    return {
      pricePerKwh: price,
      isFree: price === 0,
    };
  }
  return {
    pricePerKwh: null,
    isFree: null,
  };
}

/**
 * Maps connector row to domain entity without claiming unsupported physical counts or availability.
 * Missing power is null, missing total quantity is null, unobserved availability is null.
 */
export function mapDbConnectorToConnector(
  row: DbConnectorRow,
  _stationStatus?: StationStatus
): Connector {
  const powerKw =
    row.power_kw != null && !isNaN(Number(row.power_kw))
      ? Number(row.power_kw)
      : null;

  const total =
    row.total_quantity != null &&
    !isNaN(Number(row.total_quantity)) &&
    Number(row.total_quantity) > 0
      ? Number(row.total_quantity)
      : null;

  // Connector availability must strictly originate from explicit observations.
  // Never default to total count or 0 when unobserved.
  let available: number | null = null;
  if (
    row.latest_available_connectors != null &&
    !isNaN(Number(row.latest_available_connectors))
  ) {
    const rawAvail = Number(row.latest_available_connectors);
    available = total != null ? Math.max(0, Math.min(total, rawAvail)) : Math.max(0, rawAvail);
  }

  const minutesSince =
    row.minutes_since_observation != null && !isNaN(Number(row.minutes_since_observation))
      ? Math.round(Number(row.minutes_since_observation))
      : null;

  const freshnessState = deriveFreshnessState(minutesSince);
  const hasObs = row.latest_availability_status != null || row.latest_available_connectors != null;
  const sourceCategory = deriveSourceCategory({
    isSimulated: row.is_simulated === true,
    hasObservation: hasObs,
    freshness: freshnessState,
    sourceName: row.source_name,
  });

  return {
    id: row.id,
    type: normalizeConnectorType(row.connector_type),
    powerKw,
    total,
    available,
    latestObservationId: row.latest_observation_id ?? (row as any).latestObservationId ?? null,
    latestObservedAt: row.latest_observed_at ?? (row as any).latestObservedAt ?? null,
    minutesSinceObservation: minutesSince,
    freshnessState,
    sourceCategory,
  };
}

/**
 * Parse a coordinate without coercing missing values to 0.
 * Number(null) === 0 would place a station on the Equator/Prime Meridian.
 */
export function parseStationCoord(value: unknown): number {
  if (value == null || value === "") return Number.NaN;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : Number.NaN;
}

export function mapDbStationToStation(
  row: DbStationRow,
  connectors: DbConnectorRow[] = []
): Station {
  const minutesSinceUpdate =
    row.minutes_since_observation != null &&
    !isNaN(Number(row.minutes_since_observation))
      ? Math.round(Number(row.minutes_since_observation))
      : null;

  const freshnessState = deriveFreshnessState(minutesSinceUpdate);
  const hasObs = row.latest_availability_status != null || row.latest_observation_id != null;
  const sourceCategory = deriveSourceCategory({
    isSimulated: row.is_simulated === true,
    hasObservation: hasObs,
    freshness: freshnessState,
    sourceName: row.source_name,
  });

  const status = deriveStationStatus(
    row.latest_availability_status,
    row.operational_status,
    minutesSinceUpdate
  );
  const pricing = derivePricing(row);
  const hours = deriveHours(row);
  const area = deriveArea(row);
  const address = deriveAddress(row);

  const mappedConnectors = connectors.map((c) =>
    mapDbConnectorToConnector(c, status)
  );

  const operator = row.operator_name?.trim() || "Unknown Operator";

  return {
    id: row.id,
    name: row.name,
    operator,
    area,
    address,
    lat: parseStationCoord(row.latitude),
    lng: parseStationCoord(row.longitude),
    status,
    minutesSinceUpdate,
    connectors: mappedConnectors,
    pricePerKwh: pricing.pricePerKwh,
    isFree: pricing.isFree,
    hours,
    rating:
      row.avg_rating != null && !isNaN(Number(row.avg_rating))
        ? Number(row.avg_rating)
        : null,
    reviewCount:
      row.review_count != null && !isNaN(Number(row.review_count))
        ? Number(row.review_count)
        : 0,
    busyWindows: [], // Cold start: never fabricate busy windows without ML/temporal evidence
    latestObservationId: row.latest_observation_id ?? null,
    latestObservedAt: row.latest_observed_at ?? null,
    sourceName: row.source_name ?? null,
    sourceCategory,
    freshnessState,
    isSimulated: row.is_simulated === true,
  };
}
