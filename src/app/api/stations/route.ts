import { fetchStations } from "@/data/stations";
import {
  filterAndSortStations,
  mappableStations,
} from "@/data/exploreQuery";
import type { ConnectorType, FiltersState, SortKey } from "@/data/types";
import { isValidCoordinate } from "@/lib/util";
import { checkRateLimit, clientKey } from "@/lib/rateLimit";

export const dynamic = "force-dynamic";

/**
 * In-memory rate limiting for /api/stations.
 * Abuse friction on server route; multi-instance clusters rely on edge-level rate limiting.
 */
const STATIONS_RATE_LIMIT = { limit: 120, windowMs: 60_000 };

export async function GET(request: Request) {
  const rate = checkRateLimit(clientKey(request), STATIONS_RATE_LIMIT);
  if (!rate.allowed) {
    return Response.json(
      { error: "Rate limit exceeded" },
      {
        status: 429,
        headers: {
          "Retry-After": Math.ceil(rate.retryAfterMs / 1000).toString(),
        },
      }
    );
  }

  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(100, Math.max(1, parseInt(searchParams.get("limit") || "20", 10)));
    const offset = Math.max(0, parseInt(searchParams.get("offset") || "0", 10));
    const query = (searchParams.get("q") || "").trim();
    const sort = (searchParams.get("sort") || "nearest") as SortKey;

    // Parse connector types (support multiple selected types with OR semantics)
    const connectorTypesParam = searchParams.get("connectorTypes");
    const connectorTypeAll = searchParams.getAll("connectorType");
    let connectorTypes: ConnectorType[] = [];
    if (connectorTypesParam) {
      connectorTypes = connectorTypesParam
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s && s !== "Unknown") as ConnectorType[];
    } else if (connectorTypeAll.length > 0) {
      connectorTypes = connectorTypeAll
        .flatMap((s) => s.split(","))
        .map((s) => s.trim())
        .filter((s) => s && s !== "Unknown") as ConnectorType[];
    }

    const minPowerKw = parseFloat(searchParams.get("minPowerKw") || "0");
    const maxPrice = parseFloat(searchParams.get("maxPrice") || "0");
    const distanceKm = parseFloat(searchParams.get("distanceKm") || "0");
    const minChargers = parseInt(searchParams.get("minChargers") || "0", 10);
    const freeOnly = searchParams.get("freeOnly") === "true";
    const availableOnly = searchParams.get("availableOnly") === "true";
    const fastCharging = searchParams.get("fastCharging") === "true";
    const openNow = searchParams.get("openNow") === "true";
    const lessBusy = searchParams.get("lessBusy") === "true";

    const userLatStr = searchParams.get("userLat");
    const userLngStr = searchParams.get("userLng");
    const parsedLat = userLatStr ? parseFloat(userLatStr) : NaN;
    const parsedLng = userLngStr ? parseFloat(userLngStr) : NaN;
    const userLoc = isValidCoordinate(parsedLat, parsedLng)
      ? { lat: parsedLat, lng: parsedLng }
      : null;

    // Fetch canonical stations (freshness-decayed and paged across 1,000-row PostgREST limits)
    const allStations = await fetchStations();

    const filters: FiltersState = {
      distanceKm: Math.max(0, isNaN(distanceKm) ? 0 : distanceKm),
      connectorTypes,
      minPowerKw: Math.max(0, isNaN(minPowerKw) ? 0 : minPowerKw),
      openNow,
      availableOnly,
      fastCharging,
      freeOnly,
      lessBusy,
      maxPrice: Math.max(0, isNaN(maxPrice) ? 0 : maxPrice),
      minChargers: Math.max(0, isNaN(minChargers) ? 0 : minChargers),
    };

    // Apply authoritative, tested filter and sort rules
    const allMatching = filterAndSortStations(allStations, {
      query,
      filters,
      sort,
      userLoc,
      now: new Date(),
    });

    const total = allMatching.length;
    const pageRows = allMatching.slice(offset, offset + limit);

    // Mappable markers derived from matching stations
    const markers = mappableStations(allMatching).map((s) => ({
      id: s.id,
      name: s.name,
      operator: s.operator,
      lat: s.lat,
      lng: s.lng,
      status: s.status,
      pricePerKwh: s.pricePerKwh,
      isFree: s.isFree,
      rating: s.rating,
    }));

    return Response.json({
      stations: pageRows,
      total,
      offset,
      limit,
      hasMore: offset + limit < total,
      markers,
    });
  } catch (err: any) {
    console.error("API /api/stations unexpected error:", err);
    return Response.json(
      { error: err?.message || "Internal server error" },
      { status: 500 }
    );
  }
}
