import type { Review, Station } from "./types";

const ARGS = 0.017453292519943295;

export const MUMBAI_CENTER = { lat: 19.076, lng: 72.8777 };

const seed: Station[] = [
  {
    id: "st-andheri-east-1",
    name: "ChargePlus Hub — Andheri East",
    operator: "ChargePlus",
    area: "Andheri East",
    address: "Near Andheri Metro Station, Andheri East",
    lat: 19.1197,
    lng: 72.8468,
    status: "available",
    minutesSinceUpdate: 8,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 120, total: 2, available: 2 },
      { id: "c2", type: "CCS2", powerKw: 60, total: 2, available: 1 },
      { id: "c3", type: "Type 2", powerKw: 22, total: 2, available: 2 },
    ],
    pricePerKwh: 18,
    isFree: false,
    hours: { kind: "24h" },
    rating: 4.4,
    reviewCount: 128,
    busyWindows: ["7 PM – 9 PM"],
  },
  {
    id: "st-bandra-w-1",
    name: "Stilt Charge — Bandra West",
    operator: "Stilt Mobility",
    area: "Bandra West",
    address: "Linking Road, Bandra West",
    lat: 19.0596,
    lng: 72.8295,
    status: "busy",
    minutesSinceUpdate: 14,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 60, total: 1, available: 0 },
      { id: "c2", type: "Type 2", powerKw: 22, total: 2, available: 1 },
    ],
    pricePerKwh: 22,
    isFree: false,
    hours: { kind: "open-close", open: "07:00", close: "23:00" },
    rating: 4.1,
    reviewCount: 64,
    busyWindows: ["6 PM – 10 PM"],
  },
  {
    id: "st-powai-1",
    name: "Ather Grid — Powai",
    operator: "Ather Energy",
    area: "Powai",
    address: "Hiranandani Gardens, Powai",
    lat: 19.117,
    lng: 72.906,
    status: "available",
    minutesSinceUpdate: 3,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 60, total: 2, available: 1 },
      { id: "c2", type: "Type 2", powerKw: 22, total: 1, available: 1 },
    ],
    pricePerKwh: 20,
    isFree: false,
    hours: { kind: "24h" },
    rating: 4.6,
    reviewCount: 92,
    busyWindows: ["8 AM – 10 AM", "7 PM – 9 PM"],
  },
  {
    id: "st-lower-parel-1",
    name: "Tata Power EZ — Lower Parel",
    operator: "Tata Power",
    area: "Lower Parel",
    address: "Senapati Bapat Marg, Lower Parel",
    lat: 19.0,
    lng: 72.829,
    status: "available",
    minutesSinceUpdate: 22,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 150, total: 2, available: 1 },
      { id: "c2", type: "Bharat AC001", powerKw: 15, total: 2, available: 2 },
    ],
    pricePerKwh: 17,
    isFree: false,
    hours: { kind: "24h" },
    rating: 4.3,
    reviewCount: 211,
    busyWindows: ["9 AM – 11 AM"],
  },
  {
    id: "st-worli-1",
    name: "Statiq — Worli Sea Face",
    operator: "Statiq",
    area: "Worli",
    address: "Worli Sea Face, Worli",
    lat: 19.018,
    lng: 72.812,
    status: "broken",
    minutesSinceUpdate: 120,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 60, total: 1, available: 0 },
    ],
    pricePerKwh: 19,
    isFree: false,
    hours: { kind: "24h" },
    rating: 3.2,
    reviewCount: 18,
    busyWindows: [],
  },
  {
    id: "st-juhu-1",
    name: "ChargeZone — Juhu",
    operator: "ChargeZone",
    area: "Juhu",
    address: "Juhu Tara Road, Juhu",
    lat: 19.098,
    lng: 72.826,
    status: "available",
    minutesSinceUpdate: 5,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 60, total: 2, available: 2 },
      { id: "c2", type: "Type 2", powerKw: 22, total: 2, available: 1 },
    ],
    pricePerKwh: 24,
    isFree: false,
    hours: { kind: "24h" },
    rating: 4.5,
    reviewCount: 76,
    busyWindows: ["6 PM – 8 PM"],
  },
  {
    id: "st-malad-1",
    name: "Bolt.Earth — Malad West",
    operator: "Bolt.Earth",
    area: "Malad West",
    address: "Malad West, near station",
    lat: 19.187,
    lng: 72.848,
    status: "available",
    minutesSinceUpdate: 12,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 25, total: 2, available: 2 },
      { id: "c2", type: "Bharat AC001", powerKw: 15, total: 1, available: 1 },
    ],
    pricePerKwh: 15,
    isFree: false,
    hours: { kind: "open-close", open: "06:00", close: "23:00" },
    rating: 4.0,
    reviewCount: 39,
    busyWindows: [],
  },
  {
    id: "st-goregaon-1",
    name: "Goregaon FastCharge",
    operator: "ChargePlus",
    area: "Goregaon East",
    address: "Western Express Highway, Goregaon East",
    lat: 19.166,
    lng: 72.852,
    status: "busy",
    minutesSinceUpdate: 28,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 120, total: 2, available: 0 },
      { id: "c2", type: "CCS2", powerKw: 60, total: 2, available: 1 },
    ],
    pricePerKwh: 21,
    isFree: false,
    hours: { kind: "24h" },
    rating: 4.2,
    reviewCount: 47,
    busyWindows: ["5 PM – 8 PM"],
  },
  {
    id: "st-thane-1",
    name: "Tata Power — Thane",
    operator: "Tata Power",
    area: "Thane West",
    address: "Ghodbunder Road, Thane West",
    lat: 19.218,
    lng: 72.978,
    status: "unknown",
    minutesSinceUpdate: null,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 60, total: 1, available: 0 },
    ],
    pricePerKwh: null,
    isFree: null,
    hours: { kind: "unknown" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  },
  {
    id: "st-cbd-1",
    name: "BKC Plaza Charge",
    operator: "Statiq",
    area: "Bandra Kurla Complex",
    address: "BKC, Bandra East",
    lat: 19.07,
    lng: 72.87,
    status: "available",
    minutesSinceUpdate: 9,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 150, total: 2, available: 2 },
      { id: "c2", type: "Type 2", powerKw: 22, total: 2, available: 2 },
    ],
    pricePerKwh: 19,
    isFree: false,
    hours: { kind: "open-close", open: "00:00", close: "24:00" },
    rating: 4.7,
    reviewCount: 142,
    busyWindows: ["10 AM – 12 PM"],
  },
  {
    id: "st-marine-1",
    name: "Marine Drive Slow Charge",
    operator: "ChargePlus",
    area: "Marine Drive",
    address: "Marine Drive, Churchgate",
    lat: 18.943,
    lng: 72.823,
    status: "available",
    minutesSinceUpdate: 15,
    connectors: [
      { id: "c1", type: "Bharat AC001", powerKw: 15, total: 4, available: 4 },
    ],
    pricePerKwh: 0,
    isFree: true,
    hours: { kind: "24h" },
    rating: 4.1,
    reviewCount: 22,
    busyWindows: [],
  },
  {
    id: "st-kurla-1",
    name: "Kurla Junction Charge",
    operator: "Bolt.Earth",
    area: "Kurla",
    address: "LBS Marg, Kurla West",
    lat: 19.072,
    lng: 72.879,
    status: "busy",
    minutesSinceUpdate: 18,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 60, total: 1, available: 0 },
      { id: "c2", type: "Type 2", powerKw: 22, total: 1, available: 0 },
    ],
    pricePerKwh: 18,
    isFree: false,
    hours: { kind: "open-close", open: "06:00", close: "22:00" },
    rating: 3.9,
    reviewCount: 33,
    busyWindows: ["7 PM – 10 PM"],
  },
  {
    id: "st-vashi-1",
    name: "Vashi Hub Charge",
    operator: "Ather Energy",
    area: "Vashi",
    address: "Sector 17, Vashi",
    lat: 19.077,
    lng: 73.003,
    status: "available",
    minutesSinceUpdate: 6,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 60, total: 2, available: 1 },
    ],
    pricePerKwh: 20,
    isFree: false,
    hours: { kind: "24h" },
    rating: 4.3,
    reviewCount: 55,
    busyWindows: ["9 AM – 11 AM"],
  },
  {
    id: "st-chembur-1",
    name: "Chembur Fast Charge",
    operator: "ChargeZone",
    area: "Chembur",
    address: "Sion Trombay Road, Chembur",
    lat: 19.062,
    lng: 72.9,
    status: "available",
    minutesSinceUpdate: 25,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 60, total: 1, available: 1 },
    ],
    pricePerKwh: 21,
    isFree: false,
    hours: { kind: "open-close", open: "08:00", close: "22:00" },
    rating: 4.0,
    reviewCount: 14,
    busyWindows: [],
  },
  {
    id: "st-ghatkopar-1",
    name: "Ghatkopar East Charge",
    operator: "Statiq",
    area: "Ghatkopar East",
    address: "LBS Marg, Ghatkopar East",
    lat: 19.086,
    lng: 72.908,
    status: "unknown",
    minutesSinceUpdate: null,
    connectors: [
      { id: "c1", type: "CCS2", powerKw: 60, total: 1, available: 0 },
    ],
    pricePerKwh: 19,
    isFree: false,
    hours: { kind: "unknown" },
    rating: null,
    reviewCount: 0,
    busyWindows: [],
  },
  {
    id: "st-colaba-1",
    name: "Colaba Causeway Charge",
    operator: "ChargePlus",
    area: "Colaba",
    address: "Colaba Causeway",
    lat: 18.906,
    lng: 72.831,
    status: "available",
    minutesSinceUpdate: 11,
    connectors: [
      { id: "c1", type: "Type 2", powerKw: 22, total: 2, available: 2 },
    ],
    pricePerKwh: null,
    isFree: null,
    hours: { kind: "open-close", open: "09:00", close: "21:00" },
    rating: 3.8,
    reviewCount: 9,
    busyWindows: [],
  },
];

export const STATIONS: Station[] = seed;

// Reviews
const reviewAuthors = [
  "Aarav S.",
  "Priya M.",
  "Rahul K.",
  "Neha P.",
  "Vikram R.",
  "Sara D.",
  "Aditya J.",
  "Meera B.",
];

const reviewComments = [
  "Great charging station. Easy to access and charging was quick.",
  "Always working when I come here. Helpful staff nearby.",
  "Can get busy in the evening. Mornings are easier.",
  "Clean, well-lit, and the chargers always seem to work.",
  "Good location with parking. Slightly pricey but reliable.",
  "Disappointed — both chargers were occupied when I arrived.",
  "Quick charging, friendly operator. Will come back.",
  "Average experience. One of the chargers was slow.",
];

export const REVIEWS: Review[] = STATIONS.flatMap((s) => {
  const count = Math.min(s.reviewCount, 4);
  const baseMinutes = s.minutesSinceUpdate ?? 60;
  return Array.from({ length: count }).map((_, i) => ({
    id: `${s.id}-r${i}`,
    stationId: s.id,
    rating: ((s.rating ?? 4) > 4.4 ? 5 : s.rating && s.rating > 4 ? 4 : 3) as 1 | 2 | 3 | 4 | 5,
    comment: reviewComments[(s.id.length + i) % reviewComments.length],
    author: reviewAuthors[i % reviewAuthors.length],
    minutesAgo: baseMinutes * 60 + i * 180 + 60,
  }));
});

// Helpers

export function getStation(id: string): Station | undefined {
  return STATIONS.find((s) => s.id === id);
}

export function getReviewsForStation(id: string): Review[] {
  return REVIEWS.filter((r) => r.stationId === id).sort(
    (a, b) => a.minutesAgo - b.minutesAgo
  );
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

export function getTotalChargers(s: Station): number {
  return s.connectors.reduce((acc, c) => acc + c.total, 0);
}

export function getAvailableChargers(s: Station): number {
  return s.connectors.reduce((acc, c) => acc + c.available, 0);
}

export function getMaxPowerKw(s: Station): number {
  return s.connectors.reduce((m, c) => Math.max(m, c.powerKw), 0);
}
