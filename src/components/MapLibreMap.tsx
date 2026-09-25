"use client";

import { useEffect, useRef, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Station } from "@/data/types";
import { MUMBAI_CENTER } from "@/data/stations";
import { PlusIcon, MinusIcon, CompassIcon, PinIcon } from "./Icon";
import { cx } from "@/lib/util";

export type MapLibreMapProps = {
  stations: Station[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  userLocation?: { lat: number; lng: number } | null;
  className?: string;
  showControls?: boolean;
  /** If single station mini-map mode */
  singleStation?: Station | null;
  initialCenter?: [number, number]; // [lng, lat]
  initialZoom?: number;
  interactive?: boolean;
};

// MapLibre compatible no-key OpenFreeMap style (as specified in srs.md line 516)
const TILE_STYLE_URL = "https://tiles.openfreemap.org/styles/bright";

export function MapLibreMap({
  stations,
  selectedId,
  onSelect,
  userLocation,
  className,
  showControls = true,
  singleStation,
  initialCenter,
  initialZoom,
  interactive = true,
}: MapLibreMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const userMarkerRef = useRef<maplibregl.Marker | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const stationsRef = useRef(stations);
  const onSelectRef = useRef(onSelect);

  useEffect(() => {
    stationsRef.current = stations;
    onSelectRef.current = onSelect;
  });

  // Initialize MapLibre GL
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const center: [number, number] = singleStation
      ? [singleStation.lng, singleStation.lat]
      : initialCenter || [MUMBAI_CENTER.lng, MUMBAI_CENTER.lat];
    const zoom = singleStation ? 15 : (initialZoom ?? 11);

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: TILE_STYLE_URL,
      center,
      zoom,
      attributionControl: false,
      interactive: interactive,
    });

    mapRef.current = map;

    // Compact attribution
    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-left"
    );

    map.on("load", () => {
      // Build GeoJSON features for all stations
      const featureStations = singleStation ? [singleStation] : stationsRef.current;
      const geojson: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: featureStations.map((s) => ({
          type: "Feature",
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
            type: "Point",
            coordinates: [s.lng, s.lat],
          },
        })),
      };

      // Add clustered GeoJSON source
      map.addSource("stations", {
        type: "geojson",
        data: geojson,
        cluster: !singleStation,
        clusterMaxZoom: 14,
        clusterRadius: 45,
      });

      if (!singleStation) {
        // 1. Cluster circles with brand coral palette
        map.addLayer({
          id: "clusters",
          type: "circle",
          source: "stations",
          filter: ["has", "point_count"],
          paint: {
            "circle-color": [
              "step",
              ["get", "point_count"],
              "#F08080", // coral-600
              5,
              "#D86A6A", // coral-700
              12,
              "#B05454", // coral-800
            ],
            "circle-radius": [
              "step",
              ["get", "point_count"],
              19,
              5,
              25,
              12,
              31,
            ],
            "circle-stroke-width": 3,
            "circle-stroke-color": "#ffffff",
            "circle-opacity": 0.95,
          },
        });

        // 2. Cluster count numbers
        map.addLayer({
          id: "cluster-count",
          type: "symbol",
          source: "stations",
          filter: ["has", "point_count"],
          layout: {
            "text-field": "{point_count_abbreviated}",
            "text-font": ["Noto Sans Bold", "Open Sans Bold"],
            "text-size": 13,
          },
          paint: {
            "text-color": "#ffffff",
          },
        });

        // Tap/click cluster to expand & zoom in
        map.on("click", "clusters", async (e) => {
          const features = map.queryRenderedFeatures(e.point, { layers: ["clusters"] });
          if (!features.length) return;
          const clusterId = features[0].properties?.cluster_id;
          const source = map.getSource("stations") as maplibregl.GeoJSONSource;
          try {
            const zoom = await source.getClusterExpansionZoom(clusterId);
            const coords = (features[0].geometry as any).coordinates.slice();
            map.easeTo({ center: coords, zoom: Math.max(zoom, map.getZoom() + 1.8), duration: 400 });
          } catch (err) {
            console.error("Failed to expand cluster", err);
          }
        });

        map.on("mouseenter", "clusters", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "clusters", () => {
          map.getCanvas().style.cursor = "";
        });
      }

      // 3. Unclustered station points - outer soft halo matching StatusBadge palette
      map.addLayer({
        id: "station-halo",
        type: "circle",
        source: "stations",
        filter: singleStation ? undefined : ["!", ["has", "point_count"]],
        paint: {
          "circle-color": [
            "match",
            ["get", "status"],
            "available", "#8FCDB1", // status-available ring
            "busy", "#F0CC8A",      // status-busy ring
            "broken", "#E89A93",    // status-broken ring
            "#C7BFBD",             // status-unknown ring
          ],
          "circle-radius": 13,
          "circle-opacity": 0.55,
        },
      });

      // 4. Unclustered station points - solid center circle matching StatusBadge colors
      map.addLayer({
        id: "unclustered-point",
        type: "circle",
        source: "stations",
        filter: singleStation ? undefined : ["!", ["has", "point_count"]],
        paint: {
          "circle-color": [
            "match",
            ["get", "status"],
            "available", "#2F9E6E", // status-available
            "busy", "#D9822B",      // status-busy
            "broken", "#C8443A",    // status-broken
            "#6B615E",             // status-unknown
          ],
          "circle-radius": 7.5,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff",
        },
      });

      // Click on unclustered station point
      map.on("click", "unclustered-point", (e) => {
        if (!e.features?.length) return;
        const stationId = e.features[0].properties?.id;
        if (stationId && onSelectRef.current) {
          onSelectRef.current(stationId);
        }
      });

      map.on("mouseenter", "unclustered-point", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "unclustered-point", () => {
        map.getCanvas().style.cursor = "";
      });
    });

    // Resize observer for dynamic layout
    const resizeObserver = new ResizeObserver(() => {
      map.resize();
    });
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      resizeObserver.disconnect();
      if (userMarkerRef.current) {
        userMarkerRef.current.remove();
      }
      if (popupRef.current) {
        popupRef.current.remove();
      }
      map.remove();
      mapRef.current = null;
    };
  }, [singleStation, initialCenter, initialZoom, interactive]);

  // Update GeoJSON data when station list changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const source = map.getSource("stations") as maplibregl.GeoJSONSource | undefined;
    if (!source) return;

    const featureStations = singleStation ? [singleStation] : stations;
    const geojson: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: featureStations.map((s) => ({
        type: "Feature",
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
          type: "Point",
          coordinates: [s.lng, s.lat],
        },
      })),
    };

    source.setData(geojson);
  }, [stations, singleStation]);

  // Update user location marker & recenter map
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (!userLocation) {
      if (userMarkerRef.current) {
        userMarkerRef.current.remove();
        userMarkerRef.current = null;
      }
      return;
    }

    // Create user pin DOM element with animated pulsing halo
    if (!userMarkerRef.current) {
      const el = document.createElement("div");
      el.className = "relative flex items-center justify-center";
      el.style.width = "26px";
      el.style.height = "26px";

      const pulse = document.createElement("div");
      pulse.className = "absolute h-6 w-6 animate-ping rounded-full bg-coral-500 opacity-60";
      const dot = document.createElement("div");
      dot.className = "relative h-4 w-4 rounded-full border-2 border-white bg-coral-600 shadow-md";

      el.appendChild(pulse);
      el.appendChild(dot);

      userMarkerRef.current = new maplibregl.Marker({ element: el })
        .setLngLat([userLocation.lng, userLocation.lat])
        .addTo(map);
    } else {
      userMarkerRef.current.setLngLat([userLocation.lng, userLocation.lat]);
    }

    // Recenter map smoothly onto user's location
    map.flyTo({
      center: [userLocation.lng, userLocation.lat],
      zoom: Math.max(map.getZoom(), 13),
      duration: 1200,
    });
  }, [userLocation]);

  // Handle selected station: easeTo and show styled popup
  useEffect(() => {
    const map = mapRef.current;
    if (!map || singleStation) return;

    if (!selectedId) {
      if (popupRef.current) {
        popupRef.current.remove();
        popupRef.current = null;
      }
      return;
    }

    const st = stations.find((s) => s.id === selectedId);
    if (!st) return;

    map.easeTo({
      center: [st.lng, st.lat],
      zoom: Math.max(map.getZoom(), 13.5),
      duration: 500,
    });

    if (popupRef.current) {
      popupRef.current.remove();
    }

    const statusBadgeClass =
      st.status === "available"
        ? "bg-status-available-bg text-status-available border-status-available/20"
        : st.status === "busy"
        ? "bg-status-busy-bg text-status-busy border-status-busy/20"
        : st.status === "broken"
        ? "bg-status-broken-bg text-status-broken border-status-broken/20"
        : "bg-status-unknown-bg text-status-unknown border-status-unknown/20";

    const statusText =
      st.status === "available"
        ? "Available"
        : st.status === "busy"
        ? "Busy"
        : st.status === "broken"
        ? "Broken"
        : "Unknown";

    const priceText = st.isFree
      ? "Free"
      : st.pricePerKwh != null
      ? `₹${st.pricePerKwh}/kWh`
      : "—";

    const popupNode = document.createElement("div");
    popupNode.className = "p-2 text-ink-900 font-sans";
    popupNode.innerHTML = `
      <div class="flex items-center justify-between gap-2">
        <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-semibold ${statusBadgeClass}">
          ● ${statusText}
        </span>
        <span class="rounded-full bg-ink-100 px-2 py-0.5 text-[11px] font-semibold text-ink-800">
          ${priceText}
        </span>
      </div>
      <p class="mt-1.5 line-clamp-1 text-[13px] font-semibold text-ink-900">${st.name}</p>
      <p class="text-[11.5px] text-ink-600">${st.operator} · ${st.area}</p>
      <div class="mt-2 flex justify-end">
        <a href="/station/${st.id}" class="inline-flex items-center rounded-full bg-coral-600 px-3 py-1 text-[11px] font-medium text-white hover:bg-coral-700">
          View details →
        </a>
      </div>
    `;

    popupRef.current = new maplibregl.Popup({
      offset: 14,
      closeButton: false,
      maxWidth: "240px",
      className: "chargeplus-map-popup",
    })
      .setLngLat([st.lng, st.lat])
      .setDOMContent(popupNode)
      .addTo(map);
  }, [selectedId, stations, singleStation]);

  const handleZoomIn = useCallback(() => {
    mapRef.current?.zoomIn({ duration: 300 });
  }, []);

  const handleZoomOut = useCallback(() => {
    mapRef.current?.zoomOut({ duration: 300 });
  }, []);

  const handleRecenter = useCallback(() => {
    if (!mapRef.current) return;
    if (singleStation) {
      mapRef.current.flyTo({
        center: [singleStation.lng, singleStation.lat],
        zoom: 15,
        duration: 600,
      });
    } else if (userLocation) {
      mapRef.current.flyTo({
        center: [userLocation.lng, userLocation.lat],
        zoom: 13,
        duration: 600,
      });
    } else {
      mapRef.current.flyTo({
        center: [MUMBAI_CENTER.lng, MUMBAI_CENTER.lat],
        zoom: 11,
        duration: 600,
      });
    }
  }, [userLocation, singleStation]);

  return (
    <div
      className={cx(
        "relative isolate h-full w-full overflow-hidden rounded-[18px] border border-ink-100 bg-[#E8ECE9]",
        className
      )}
    >
      <div ref={containerRef} className="h-full w-full" />

      {/* City identification badge */}
      <div className="pointer-events-none absolute left-3 top-3 z-10 inline-flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 text-[11px] font-medium text-ink-700 shadow-card backdrop-blur-sm">
        <PinIcon size={12} />
        {singleStation ? singleStation.area : "Mumbai"}
      </div>

      {/* Floating map action controls */}
      {showControls && (
        <div className="absolute right-3 top-3 z-10 flex flex-col gap-2">
          <MapCtrlBtn label="Zoom in" onClick={handleZoomIn}>
            <PlusIcon size={16} />
          </MapCtrlBtn>
          <MapCtrlBtn label="Zoom out" onClick={handleZoomOut}>
            <MinusIcon size={16} />
          </MapCtrlBtn>
          <MapCtrlBtn label="Recenter" onClick={handleRecenter}>
            <CompassIcon size={16} />
          </MapCtrlBtn>
        </div>
      )}
    </div>
  );
}

function MapCtrlBtn({
  children,
  onClick,
  label,
}: {
  children: React.ReactNode;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-ink-100 bg-white/95 text-ink-700 shadow-card transition-colors hover:bg-ink-50 backdrop-blur-sm"
    >
      {children}
    </button>
  );
}
