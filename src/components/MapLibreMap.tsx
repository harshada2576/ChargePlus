"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

if (typeof window !== "undefined") {
  maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");
}
import type { Station } from "@/data/types";
import { MUMBAI_CENTER } from "@/data/stations";
import {
  createMapLoadWatchdog,
  refreshStationsSource,
  toStationGeoJSON,
} from "@/data/exploreQuery";
import { PlusIcon, MinusIcon, CompassIcon, PinIcon, AlertTriangleIcon } from "./Icon";
import { cx, escapeHtml, isValidCoordinate } from "@/lib/util";
import { stationPriceDisplay } from "@/lib/priceDisplay";
import { useI18n } from "@/i18n/I18nProvider";

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

export { isValidCoordinate } from "@/lib/util";

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
  const watchdogRef = useRef<{ resolve: () => void } | null>(null);
  const [mapError, setMapError] = useState(false);
  // Bumped by the error-state retry action to re-run initialization and give
  // a transient style/tile failure another chance. Cleanup below destroys the
  // previous map instance before the re-attempt.
  const [mapAttempt, setMapAttempt] = useState(0);
  const { t } = useI18n();

  useEffect(() => {
    stationsRef.current = stations;
    onSelectRef.current = onSelect;
  });

  // Initialize MapLibre GL
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const center: [number, number] =
      singleStation && isValidCoordinate(singleStation.lat, singleStation.lng)
        ? [singleStation.lng, singleStation.lat]
        : initialCenter || [MUMBAI_CENTER.lng, MUMBAI_CENTER.lat];
    const zoom = singleStation ? 15 : (initialZoom ?? 11);

    let map: maplibregl.Map;
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: TILE_STYLE_URL,
        center,
        zoom,
        attributionControl: false,
        interactive: interactive,
      });
    } catch (err) {
      // Construction itself can throw (e.g. no WebGL context): surface it
      // through the same actionable error state instead of crashing the page.
      console.error("MapLibre map initialization failed:", err);
      // Synchronous mount-failure reporting; the error overlay is this effect's purpose.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMapError(true);
      return;
    }

    mapRef.current = map;

    // Silent stalls (a hanging style/tile request emits no error event) would
    // otherwise leave a blank canvas forever: surface them actionably.
    const watchdog = createMapLoadWatchdog(() => {
      const current = mapRef.current;
      if (!current || !current.isStyleLoaded()) setMapError(true);
    });
    watchdogRef.current = watchdog;

    // A style/tile failure before the style is ready leaves an empty canvas with
    // no feedback, so surface it in the UI instead of failing silently.
    map.on("error", (event) => {
      console.error("MapLibre map error:", event.error);
      if (!map.isStyleLoaded()) setMapError(true);
    });

    // Compact attribution
    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-left"
    );

    // Seed pins on style readiness, not full load: station pins must not wait
    // for (or depend on) base-map tile completion. Late station data is
    // pushed by the refresh effect below.
    map.on("style.load", () => {
      watchdogRef.current?.resolve();
      setMapError(false);
      // Build GeoJSON features for valid stations
      const featureStations = singleStation ? [singleStation] : stationsRef.current;
      const geojson = toStationGeoJSON(featureStations);

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

    // Full load (style + tiles settled) also disarms the watchdog and clears
    // any earlier transient error. Pins do not wait for this event.
    map.on("load", () => {
      watchdogRef.current?.resolve();
      setMapError(false);
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
      watchdogRef.current?.resolve();
      watchdogRef.current = null;
      if (userMarkerRef.current) {
        userMarkerRef.current.remove();
        userMarkerRef.current = null;
      }
      if (popupRef.current) {
        popupRef.current.remove();
        popupRef.current = null;
      }
      map.remove();
      mapRef.current = null;
    };
  }, [singleStation, initialCenter, initialZoom, interactive, mapAttempt]);

  // Update GeoJSON data when station list changes (e.g. the station fetch
  // completes after map initialization). No-op until the style is loaded and
  // the source exists; the load handler above seeds from the latest stations.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    refreshStationsSource(
      map as unknown as Parameters<typeof refreshStationsSource>[0],
      singleStation ? [singleStation] : stations
    );
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
    if (!st || !isValidCoordinate(st.lat, st.lng)) {
      // Selection left the visible set (filtered out or reloaded away):
      // never leave a stale popup behind.
      if (popupRef.current) {
        popupRef.current.remove();
        popupRef.current = null;
      }
      return;
    }

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

    const priceText = escapeHtml(stationPriceDisplay(st, t).text);
    const isSim = st.isSimulated || st.sourceCategory === "simulated";
    const demoBadge = isSim
      ? `<span class="inline-flex items-center rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 border border-amber-200">Demo</span>`
      : "";

    const popupNode = document.createElement("div");
    popupNode.className = "p-2 text-ink-900 font-sans";
    popupNode.setAttribute("role", "group");
    popupNode.setAttribute("aria-label", `${st.name}, ${statusText}`);
    popupNode.innerHTML = `
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-1.5">
          <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-semibold ${statusBadgeClass}">
            ● ${statusText}
          </span>
          ${demoBadge}
        </div>
        <span class="rounded-full bg-ink-100 px-2 py-0.5 text-[11px] font-semibold text-ink-800">
          ${priceText}
        </span>
      </div>
      <p class="mt-1.5 line-clamp-1 text-[13px] font-semibold text-ink-900">${escapeHtml(st.name)}</p>
      <p class="text-[11.5px] text-ink-600">${escapeHtml(st.operator)} · ${escapeHtml(st.area)}</p>
      <div class="mt-2 flex justify-end">
        <a href="/station/${encodeURIComponent(st.id)}" class="inline-flex items-center rounded-full bg-coral-600 px-3 py-1 text-[11px] font-medium text-ink-900 hover:bg-coral-700">
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
  }, [selectedId, stations, singleStation, t]);

  const handleZoomIn = useCallback(() => {
    mapRef.current?.zoomIn({ duration: 300 });
  }, []);

  const handleZoomOut = useCallback(() => {
    mapRef.current?.zoomOut({ duration: 300 });
  }, []);

  const handleRecenter = useCallback(() => {
    if (!mapRef.current) return;
    if (singleStation && isValidCoordinate(singleStation.lat, singleStation.lng)) {
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

      {/* Style/tile load failure — never leave a silent blank map */}
      {mapError && (
        <div
          role="alert"
          className="absolute inset-0 z-0 flex flex-col items-center justify-center gap-1 bg-white/95 px-4 text-center"
        >
          <AlertTriangleIcon size={20} className="text-coral-700" />
          <p className="text-[13px] font-semibold text-ink-900">{t("errors.map.title")}</p>
          <p className="text-[12px] text-ink-600">{t("errors.map.body")}</p>
          <button
            type="button"
            onClick={() => {
              setMapError(false);
              setMapAttempt((a) => a + 1);
            }}
            className="mt-2 inline-flex h-9 items-center rounded-full bg-coral-600 px-4 text-[13px] font-medium text-ink-900 hover:bg-coral-700"
          >
            {t("common.tryAgain")}
          </button>
        </div>
      )}

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
