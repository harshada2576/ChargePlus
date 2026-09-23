export type StationStatus = "available" | "busy" | "broken" | "unknown";
export type QueueLevel = "none" | "short" | "medium" | "long";

export type ConnectorType = "CCS2" | "CCS1" | "CHAdeMO" | "Type 2" | "Type 1" | "Bharat AC001";

export type Connector = {
  id: string;
  type: ConnectorType;
  /** peak power in kW */
  powerKw: number;
  /** number of physical chargers of this type */
  total: number;
  /** number currently available (we use only for 'available' stations) */
  available: number;
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
  /** True if charging is free; null if unknown */
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
  reasons: ("matchConnector" | "availableNow" | "lessBusyNow")[];
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
