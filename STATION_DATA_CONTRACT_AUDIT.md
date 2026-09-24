# ChargePlus Frontend Data Contract Audit

**Project:** ChargePlus — EV charging platform  
**Phase:** 1/6 Step 1.3/10 — Core operational schema  
**Status:** READ ONLY — Frontend is LOCKED

This report identifies all fields the existing frontend expects for a station, categorized by semantic domain, with guidance on database placement. The goal is to prevent Step 1.3 database design from breaking the locked frontend.

---

## Station Type Definition (src/data/types.ts)

```ts
export type Station = {
  id: string;
  name: string;
  operator: string;
  area: string;
  address: string;
  lat: number;
  lng: number;
  status: StationStatus;
  minutesSinceUpdate: number | null;
  connectors: Connector[];
  pricePerKwh: number | null;
  isFree: boolean | null;
  hours: { kind: "24h" | "open-close" | "unknown"; open?: string; close?: string };
  rating: number | null;
  reviewCount: number;
  busyWindows: string[];
};

export type Connector = {
  id: string;
  type: ConnectorType;
  powerKw: number;
  total: number;
  available: number;
};
```

---

## 1. Station-level identity

| Field | Where Used | DB Placement |
|-------|-----------|--------------|
| `id` | StationCard (link href), StationDetail (Link href, nav), StationPreviewSheet (link href), Admin (table ID/Name column), Profile (Row link), Explore (selectedId, filtered find), MapLibreMap (station key) | **stations** |
| `name` | StationCard (link text, h1), StationDetail (h1), StationPreviewSheet (h3), Admin (table), Profile (implicit), i18n labels | **stations** |

---

## 2. Address/location

| Field | Where Used | DB Placement |
|-------|-----------|--------------|
| `address` | StationDetail (p tag under area), StationCard (implicit in operator·area line), StationPreviewSheet (not directly but in map nav) | **stations** |
| `lat` | StationDetail (MapLibreMap), StationCard (distanceKm calc), StationPreviewSheet (distanceKm calc), Explore (distance filtering & sorting), MapLibreMap (map positioning), StationDetail (navigate to) | **stations** |
| `lng` | Same as `lat` | **stations** |

---

## 3. Operator

| Field | Where Used | DB Placement |
|-------|-----------|--------------|
| `operator` | StationCard (operator · area p tag), StationDetail (p.operator · p.area), StationPreviewSheet (p.operator), Admin (table Operator column), Profile (profile page) | **stations** |

---

## 4. Connector information

| Field | Where Used | DB Placement |
|-------|-----------|--------------|
| `connectors[]` (array) | StationCard (connectors.map, max 2 types shown, kW, available count), StationDetail (connectors.map with type, power, available), StationPreviewSheet (connectors.map), Admin (table Connectors column, `s.connectors.map((c) => c.type).join(", ")`) | **connectors** (child of stations) authenticated views in Step 1.8 |

> **Repair note (Phase 1 Step 1.6, 23 Sep 2026):** the tail of this file was corrupted
> (binary/garbage content plus a pasted `<tool_call>` block on lines 75–79) and has been
> truncated back to this point. Any content originally lost here should be re-derived from
> the implemented schema — see `docs/data_dictionary.md` and `docs/step_1_6_constraints_indexes_audit.md`.