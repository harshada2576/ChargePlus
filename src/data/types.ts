export type StationStatus = "available" | "busy" | "broken" | "unknown";
export type QueueLevel = "none" | "short" | "medium" | "long";

export type SourceCategory =
  | "verified_live"
  | "recent_observation"
  | "historical"
  | "simulated"
  | "unknown";

export type FreshnessState = "fresh" | "aging" | "stale" | "unknown";

export type ConnectorType =
  | "CCS2"
  | "CCS1"
  | "CHAdeMO"
  | "Type 2"
  | "Type 1"
  | "Bharat AC001"
  | "Unknown";

export type Connector = {
  id: string;
  type: ConnectorType;
  /** peak power in kW; null if unknown */
  powerKw: number | null;
  /** number of physical chargers of this type; null if unknown */
  total: number | null;
  /** number currently available; null if unknown */
  available: number | null;
  /** underlying observation id tracing this connector status */
  latestObservationId?: string | null;
  /** observation time when status was captured */
  latestObservedAt?: string | null;
  /** observation age in minutes */
  minutesSinceObservation?: number | null;
  /** temporal freshness classification */
  freshnessState?: FreshnessState;
  /** provenance source category */
  sourceCategory?: SourceCategory;
  /** true when record originates from simulated demo / seed dataset */
  isSimulated?: boolean;
  /** verified connector tariff in INR/kWh; null when not verified/reported */
  pricePerKwh?: number | null;
  /** verified connector tariff in INR/session; null when not verified/reported */
  pricePerSession?: number | null;
  /** explicitly unverified source-derived estimate in INR/kWh */
  priceEstimatePerKwh?: number | null;
  /** original source text supporting the unverified estimate */
  priceEstimateRaw?: string | null;
  /** provenance source identifier for the unverified estimate (e.g. 'ocm_usage_cost') */
  priceEstimateSource?: string | null;
};

export type Station = {
  id: string;
  name: string;
  operator: string;
  area: string;        // e.g. "Andheri East"
  address: string;
  /** real-world lat/lng for mapping and navigation */
  lat: number;
  lng: number;
  status: StationStatus;
  /** minutes since most recent update; null if unknown */
  minutesSinceUpdate: number | null;
  connectors: Connector[];
  /** INR per kWh; null if unknown */
  pricePerKwh: number | null;
  /** True if charging is free; null if unknown. Free is established only by
   * this flag === true or by a validated finite zero pricePerKwh — never by
   * an invalid/missing number (contract lives in src/lib/priceDisplay.ts). */
  isFree: boolean | null;
  /** Opening hours descriptor */
  hours:
    | { kind: "24h" }
    | { kind: "open-close"; open: string; close: string }
    | { kind: "unknown" };
  /** Average rating 0..5, null if no reviews */
  rating: number | null;
  reviewCount: number;
  /** Suggested busy windows — local hours like "7 PM – 9 PM" or empty */
  busyWindows: string[];
  /** underlying station-level observation id */
  latestObservationId?: string | null;
  /** observation event timestamp (ISO-8601) */
  latestObservedAt?: string | null;
  /** provenance feed or upstream provider identifier */
  sourceName?: string | null;
  /** authoritative source category */
  sourceCategory?: SourceCategory;
  /** temporal freshness state */
  freshnessState?: FreshnessState;
  /** true when record originates from simulated demo / seed dataset */
  isSimulated?: boolean;
};

export type Review = {
  id: string;
  stationId: string;
  rating: 1 | 2 | 3 | 4 | 5;
  comment: string;
  author: string;
  /** minutes ago */
  minutesAgo: number;
};

export type UserReport = {
  id: string;
  stationId: string;
  status: Exclude<StationStatus, "unknown">;
  queue: QueueLevel;
  note?: string;
  submittedAt: Date;
};

export type Alert = {
  id: string;
  stationId: string;
  type: "available" | "lessBusy";
  enabled: boolean;
};

export type Recommendation = {
  stationId: string;
  reasons: (
    | "matchConnector"
    | "availableNow"
    | "knownPower"
    | "priceAvailable"
    | "nearby"
    | "availabilityUnknown"
  )[];
  /** number of available chargers (if reason: availableNow) */
  availableCount?: number;
};

export type SortKey =
  | "nearest"
  | "available"
  | "speed"
  | "price"
  | "recommended";

export type FiltersState = {
  /** km; 0 means any */
  distanceKm: number;
  /** empty array means any */
  connectorTypes: ConnectorType[];
  /** min kW; 0 means any */
  minPowerKw: number;
  /** open-now only */
  openNow: boolean;
  /** currently available only */
  availableOnly: boolean;
  /** fast charging only (>= 50 kW) */
  fastCharging: boolean;
  /** free charging only */
  freeOnly: boolean;
  /** usually less busy at this time */
  lessBusy: boolean;
  /** max INR/kWh; 0 means any */
  maxPrice: number;
  /** minimum number of chargers; 0 means any */
  minChargers: number;
};
