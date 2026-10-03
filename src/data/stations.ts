import type { Station, Review } from "./types";
import {
  mapDbStationToStation,
  type DbStationRow,
  type DbConnectorRow,
} from "./stationAdapter";
import { supabase } from "@/lib/supabase";

export const MUMBAI_CENTER = { lat: 19.076, lng: 72.8777 };

/** Haversine argument conversion factor (degrees to radians) */
const ARGS = Math.PI / 180;

/**
 * Canonical station baseline derived from the authoritative PostgreSQL database.
 * No fabricated availability (connector available is null without telemetry),
 * unknown power preserved as null, and factual physical quantities preserved.
 */
export const CANONICAL_STATIONS: Station[] = [
  {
    id: "2979dde1-c576-437b-b881-3bea4c43a70d",
    name: "Tata Power Receiving Station",
    operator: "(Business Owner at Location)",
    area: "Vikhroli",
    address: "3, Vikhroli Village Road, Vikhroli, Mumbai, Maharashtra, 400077",
    lat: 19.0957956,
    lng: 72.9260109,
    status: "unknown",
    minutesSinceUpdate: null,
    connectors: [
      {
        id: "c163be25-b6b6-46f7-9404-41cb5eee6a92",
        type: "Type 1",
        powerKw: null,
        total: 3,
        available: null,
      },
    ],
    pricePerKwh: null,
    isFree: null,
    hours: { kind: "unknown" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  },
  {
    id: "4ae2adf1-a5fa-4b7d-9920-ffda8ee3f86e",
    name: "Mira Road",
    operator: "Unknown Operator",
    area: "Maharashtra",
    address: "A/1104, Unique Heights, Poonam Garden, Above New India Co-Op Bank, Near S K Stone, Mira Bhayender Road, Near S K Stone, Maharashtra, India, 401107",
    lat: 19.1400060534561,
    lng: 72.8534438284495,
    status: "unknown",
    minutesSinceUpdate: null,
    connectors: [
      {
        id: "2ec5cd42-b0ba-4c9f-a95e-bc61b1ea36e6",
        type: "CCS2",
        powerKw: null,
        total: 1,
        available: null,
      },
    ],
    pricePerKwh: null,
    isFree: null,
    hours: { kind: "unknown" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  },
  {
    id: "862847e0-83fe-43cf-84d9-a6e936451aec",
    name: "SALZER DEVELOPMENT",
    operator: "Salzer NexCharge (IN)",
    area: "Mumbai",
    address: "The Lalit Hotel, Mumbai, Maharashtra",
    lat: 19.105321,
    lng: 72.875887,
    status: "broken",
    minutesSinceUpdate: null,
    connectors: [
      {
        id: "41268dcc-3c36-4c4a-b941-64ef2083211c",
        type: "Type 2",
        powerKw: 7,
        total: 1,
        available: null,
      },
    ],
    pricePerKwh: null,
    isFree: null,
    hours: { kind: "unknown" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  },
  {
    id: "ac24ba32-7db5-4667-85e1-7751110f3882",
    name: "Cinemax",
    operator: "Unknown Operator",
    area: "Khadakpada",
    address: "Tycoons Residency, Khadakpada, Kalyan, Maharashtra, 421301",
    lat: 19.2436515915009,
    lng: 73.1347557220724,
    status: "unknown",
    minutesSinceUpdate: null,
    connectors: [],
    pricePerKwh: null,
    isFree: null,
    hours: { kind: "unknown" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  },
  {
    id: "b2583624-8b43-4088-bfb3-4818cc2cb959",
    name: "MobiLane Saya Grand By Treat",
    operator: "Unknown Operator",
    area: "Thane",
    address: "Off, 606, Mumbai - Nashik Expy, Anjur, Amane, Maharashtra 421311, Thane",
    lat: 19.21916215,
    lng: 73.04392037,
    status: "unknown",
    minutesSinceUpdate: null,
    connectors: [],
    pricePerKwh: null,
    isFree: null,
    hours: { kind: "unknown" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  },
  {
    id: "d4463f95-345f-47bb-8eb0-7b8d6fcb567d",
    name: "MobiLane Equinox Business Park",
    operator: "Unknown Operator",
    area: "Mumbai",
    address: "Equinox Building-3, Equinox Business Park, Ambedkar Nagar, Kurla West, Kurla, Mumbai, Maharashtra 400070",
    lat: 19.071566,
    lng: 72.877213,
    status: "unknown",
    minutesSinceUpdate: null,
    connectors: [],
    pricePerKwh: null,
    isFree: null,
    hours: { kind: "unknown" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  },
  {
    id: "d5f18c9f-7f65-457e-8169-3c9cf9c8aff5",
    name: "Andheri West",
    operator: "Unknown Operator",
    area: "Mumbai",
    address: "Four Bunglows, Mumbai, Maharashtra, 400057",
    lat: 19.1166,
    lng: 72.82927,
    status: "unknown",
    minutesSinceUpdate: null,
    connectors: [
      {
        id: "f8755a9d-e537-4f74-8929-91e153fbe81b",
        type: "CCS2",
        powerKw: 120,
        total: 2,
        available: null,
      },
    ],
    pricePerKwh: null,
    isFree: null,
    hours: { kind: "unknown" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  },
  {
    id: "d7872467-b685-422b-beb0-f2112ecd364f",
    name: "Balasaheb Thackeray Flyover",
    operator: "Unknown Operator",
    area: "Zone 3",
    address: "Balasaheb Thackeray Flyover, Zone 3, Mumbai, Maharashtra, 400029",
    lat: 19.1399508241526,
    lng: 72.8519735974261,
    status: "unknown",
    minutesSinceUpdate: null,
    connectors: [
      {
        id: "bb582586-6707-4ca8-a919-08bcfbbf7be8",
        type: "CCS2",
        powerKw: null,
        total: 1,
        available: null,
      },
    ],
    pricePerKwh: null,
    isFree: null,
    hours: { kind: "unknown" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  },
];

/** Authoritative station export, matching canonical database records */
export const STATIONS: Station[] = CANONICAL_STATIONS;

/** Zero fabricated reviews. Empty array represents honest cold-start state. */
export const REVIEWS: Review[] = [];

/**
 * Fetch all stations and their connectors live from Supabase views.
 * Preserves unknown power as null, unknown connector availability as null,
 * and avoids conflating operational status with availability.
 */
export async function fetchStations(): Promise<Station[]> {
  try {
    const [stationsRes, connectorsRes] = await Promise.all([
      supabase.from("v_station_current_state").select("*"),
      supabase.from("v_station_connectors").select("*"),
    ]);

    if (stationsRes.error) {
      console.error("fetchStations error:", stationsRes.error);
      return CANONICAL_STATIONS;
    }

    const rawStations: DbStationRow[] = (stationsRes.data as DbStationRow[]) || [];
    const rawConnectors: DbConnectorRow[] = (connectorsRes.data as DbConnectorRow[]) || [];

    const connsByStation = new Map<string, DbConnectorRow[]>();
    for (const c of rawConnectors) {
      const list = connsByStation.get(c.station_id) ?? [];
      list.push(c);
      connsByStation.set(c.station_id, list);
    }

    return rawStations.map((st) =>
      mapDbStationToStation(st, connsByStation.get(st.id) ?? [])
    );
  } catch (err) {
    console.error("fetchStations unhandled error:", err);
    return CANONICAL_STATIONS;
  }
}

/**
 * Fetch a single station by UUID and its child connectors live from Supabase views.
 */
export async function fetchStationById(id: string): Promise<Station | null> {
  try {
    const [stationRes, connectorsRes] = await Promise.all([
      supabase.from("v_station_current_state").select("*").eq("id", id).maybeSingle(),
      supabase.from("v_station_connectors").select("*").eq("station_id", id),
    ]);

    if (stationRes.error) {
      console.error("fetchStationById query error:", stationRes.error);
      return CANONICAL_STATIONS.find((s) => s.id === id) ?? null;
    }

    if (!stationRes.data) {
      return null;
    }

    const rawStation = stationRes.data as DbStationRow;
    const rawConnectors = (connectorsRes.data as DbConnectorRow[]) || [];

    return mapDbStationToStation(rawStation, rawConnectors);
  } catch (err) {
    console.error("fetchStationById unhandled error:", err);
    return CANONICAL_STATIONS.find((s) => s.id === id) ?? null;
  }
}

/**
 * Synchronous station lookup from canonical dataset.
 */
export function getStation(id: string): Station | undefined {
  return CANONICAL_STATIONS.find((s) => s.id === id);
}

/**
 * Retrieve reviews for a station (honest zero reviews until Step 3.10).
 */
export function getReviewsForStation(id: string): Review[] {
  return REVIEWS.filter((r) => r.stationId === id);
}

/** Haversine distance in km */
export function distanceKm(
  a: { lat: number; lng: number },
  b: { lat: number; lng: number }
): number {
  const R = 6371;
  const dLat = (b.lat - a.lat) * ARGS;
  const dLng = (b.lng - a.lng) * ARGS;
  const lat1 = a.lat * ARGS;
  const lat2 = b.lat * ARGS;
  const x =
    Math.sin(dLat / 2) ** 2 +
    Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return 2 * R * Math.asin(Math.sqrt(x));
}

export function formatDistance(km: number): { value: string; unit: "m" | "km" } {
  if (km < 1) {
    return { value: `${Math.round(km * 1000)}`, unit: "m" };
  }
  return {
    value: km < 10 ? km.toFixed(1).replace(/\.0$/, "") : `${Math.round(km)}`,
    unit: "km",
  };
}

export function getTotalChargers(s: Station): number | null {
  if (s.connectors.length === 0) return 0;
  const known = s.connectors.map((c) => c.total).filter((n): n is number => n != null);
  if (known.length === 0) return null;
  return known.reduce((acc, n) => acc + n, 0);
}

export function getAvailableChargers(s: Station): number | null {
  if (s.connectors.length === 0) return 0;
  const known = s.connectors.map((c) => c.available).filter((n): n is number => n != null);
  if (known.length === 0) return null;
  return known.reduce((acc, n) => acc + n, 0);
}

export function getMaxPowerKw(s: Station): number {
  return s.connectors.reduce((m, c) => Math.max(m, c.powerKw ?? 0), 0);
}
