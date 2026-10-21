import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { mapDbStationToStation, mapDbConnectorToConnector, type DbStationRow, type DbConnectorRow } from "@/data/stationAdapter";
import { distanceKm } from "@/data/stations";
import { isValidCoordinate } from "@/lib/util";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(50, Math.max(1, parseInt(searchParams.get("limit") || "20", 10)));
    const offset = Math.max(0, parseInt(searchParams.get("offset") || "0", 10));
    const query = (searchParams.get("q") || "").trim().toLowerCase();
    const sort = searchParams.get("sort") || "nearest";
    const connectorType = searchParams.get("connectorType") || "";
    const minPowerKw = parseFloat(searchParams.get("minPowerKw") || "0");
    const maxPrice = parseFloat(searchParams.get("maxPrice") || "0");
    const freeOnly = searchParams.get("freeOnly") === "true";
    const availableOnly = searchParams.get("availableOnly") === "true";
    const fastCharging = searchParams.get("fastCharging") === "true";
    const openNow = searchParams.get("openNow") === "true";

    const userLatStr = searchParams.get("userLat");
    const userLngStr = searchParams.get("userLng");
    const userLoc =
      userLatStr && userLngStr
        ? { lat: parseFloat(userLatStr), lng: parseFloat(userLngStr) }
        : null;

    // Build Supabase query on canonical view
    let dbQuery = supabase.from("v_station_current_state").select("*");

    if (availableOnly) {
      dbQuery = dbQuery.eq("latest_availability_status", "available");
    }
    if (freeOnly) {
      dbQuery = dbQuery.eq("min_price_per_kwh", 0);
    }
    if (fastCharging) {
      dbQuery = dbQuery.gte("max_power_kw", 50);
    } else if (minPowerKw > 0) {
      dbQuery = dbQuery.gte("max_power_kw", minPowerKw);
    }
    if (maxPrice > 0) {
      dbQuery = dbQuery.lte("min_price_per_kwh", maxPrice);
    }
    if (openNow) {
      dbQuery = dbQuery.eq("is_24_hours", true);
    }

    const { data: rawRows, error } = await dbQuery;
    if (error) {
      console.error("API /api/stations query error:", error);
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    let allMatching: DbStationRow[] = rawRows || [];

    // Filter by text search across full database matching records
    if (query) {
      allMatching = allMatching.filter((s) => {
        const name = (s.name || "").toLowerCase();
        const op = (s.operator_name || "").toLowerCase();
        const city = (s.city || "").toLowerCase();
        const loc = (s.locality || "").toLowerCase();
        const addr = (s.address_line || "").toLowerCase();
        return (
          name.includes(query) ||
          op.includes(query) ||
          city.includes(query) ||
          loc.includes(query) ||
          addr.includes(query)
        );
      });
    }

    // Filter by connector type if provided
    if (connectorType && connectorType !== "Unknown") {
      allMatching = allMatching.filter((s) =>
        (s.connector_types || []).includes(connectorType)
      );
    }

    // Sort matching stations stably
    allMatching.sort((a, b) => {
      if (sort === "nearest" && userLoc) {
        const aLat = typeof a.latitude === "number" ? a.latitude : parseFloat(a.latitude || "0");
        const aLng = typeof a.longitude === "number" ? a.longitude : parseFloat(a.longitude || "0");
        const bLat = typeof b.latitude === "number" ? b.latitude : parseFloat(b.latitude || "0");
        const bLng = typeof b.longitude === "number" ? b.longitude : parseFloat(b.longitude || "0");
        const distA = isValidCoordinate(aLat, aLng)
          ? distanceKm(userLoc, { lat: aLat, lng: aLng })
          : Number.POSITIVE_INFINITY;
        const distB = isValidCoordinate(bLat, bLng)
          ? distanceKm(userLoc, { lat: bLat, lng: bLng })
          : Number.POSITIVE_INFINITY;
        return distA - distB || (a.name || "").localeCompare(b.name || "") || a.id.localeCompare(b.id);
      }
      if (sort === "speed") {
        const pA = a.max_power_kw ?? 0;
        const pB = b.max_power_kw ?? 0;
        return pB - pA || (a.name || "").localeCompare(b.name || "") || a.id.localeCompare(b.id);
      }
      if (sort === "price") {
        const prA = a.min_price_per_kwh ?? Number.POSITIVE_INFINITY;
        const prB = b.min_price_per_kwh ?? Number.POSITIVE_INFINITY;
        return prA - prB || (a.name || "").localeCompare(b.name || "") || a.id.localeCompare(b.id);
      }
      if (sort === "available") {
        const avA = a.latest_availability_status === "available" ? 0 : 1;
        const avB = b.latest_availability_status === "available" ? 0 : 1;
        return avA - avB || (a.name || "").localeCompare(b.name || "") || a.id.localeCompare(b.id);
      }
      // default / name sort
      return (a.name || "").localeCompare(b.name || "") || a.id.localeCompare(b.id);
    });

    const total = allMatching.length;
    // Strictly bounded slice for the current page (default 20 stations)
    const pageRows = allMatching.slice(offset, offset + limit);

    // Fetch connectors only for the stations in the current page
    const pageIds = pageRows.map((s) => s.id);
    let pageConnectors: DbConnectorRow[] = [];
    if (pageIds.length > 0) {
      const { data: conns, error: connErr } = await supabase
        .from("v_station_connectors")
        .select("*")
        .in("station_id", pageIds);

      if (connErr) {
        console.error("API /api/stations connectors error:", connErr);
      } else {
        pageConnectors = conns || [];
      }
    }

    const connsByStation = new Map<string, DbConnectorRow[]>();
    for (const c of pageConnectors) {
      const list = connsByStation.get(c.station_id) ?? [];
      list.push(c);
      connsByStation.set(c.station_id, list);
    }

    const stations = pageRows.map((st) =>
      mapDbStationToStation(st, connsByStation.get(st.id) ?? [])
    );

    // Lightweight map marker representations for all matching stations
    const markers = allMatching
      .filter((s) => {
        const lat = typeof s.latitude === "number" ? s.latitude : parseFloat(s.latitude || "0");
        const lng = typeof s.longitude === "number" ? s.longitude : parseFloat(s.longitude || "0");
        return isValidCoordinate(lat, lng);
      })
      .map((s) => {
        const lat = typeof s.latitude === "number" ? s.latitude : parseFloat(s.latitude || "0");
        const lng = typeof s.longitude === "number" ? s.longitude : parseFloat(s.longitude || "0");
        return {
          id: s.id,
          name: s.name,
          operator: s.operator_name || "Unknown Operator",
          lat,
          lng,
          status: (s.latest_availability_status || "unknown") as any,
          pricePerKwh: s.min_price_per_kwh,
          isFree: s.min_price_per_kwh === 0,
          rating: s.avg_rating,
        };
      });

    return NextResponse.json({
      stations,
      total,
      offset,
      limit,
      hasMore: offset + limit < total,
      markers,
    });
  } catch (err: any) {
    console.error("API /api/stations unexpected error:", err);
    return NextResponse.json(
      { error: err?.message || "Internal server error" },
      { status: 500 }
    );
  }
}
