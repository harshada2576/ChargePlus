"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import { distanceKm, fetchStationById, formatDistance, getMaxPowerKw } from "@/data/stations";
import {
  DEFAULT_EXPLORE_FILTERS,
  recommendStations,
  resolveSelectedStation,
  visibleSelection,
} from "@/data/exploreQuery";
import type {
  FiltersState,
  Recommendation,
  SortKey,
  Station,
} from "@/data/types";
import { MapLibreMap } from "@/components/MapLibreMap";
import { StationCard } from "@/components/StationCard";
import { StationPreviewSheet } from "@/components/StationPreviewSheet";
import { FiltersPanel } from "@/components/FiltersPanel";
import { StationCardSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import { WeatherBadge } from "@/components/WeatherBadge";
import {
  FilterIcon,
  PinIcon,
  SearchIcon,
  SortIcon,
  ChevronDownIcon,
  CheckIcon,
  AlertTriangleIcon,
} from "@/components/Icon";
import { cx } from "@/lib/util";

export interface MapMarkerSummary {
  id: string;
  name: string;
  operator: string;
  lat: number;
  lng: number;
  status: Station["status"];
  pricePerKwh: number | null;
  isFree: boolean | null;
  rating: number | null;
}

export function ExploreClient() {
  const { t } = useI18n();
  const { show: showToast } = useToast();

  const [stations, setStations] = useState<Station[]>([]);
  const [mapMarkers, setMapMarkers] = useState<MapMarkerSummary[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<FiltersState>(DEFAULT_EXPLORE_FILTERS);
  const [sort, setSort] = useState<SortKey>("nearest");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [userLoc, setUserLoc] = useState<{ lat: number; lng: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [locErrorDetails, setLocErrorDetails] = useState<{
    code: number | "unsupported" | "insecure";
    message: string;
  } | null>(null);

  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sortOpen, setSortOpen] = useState(false);
  const mobileSearchInputRef = useRef<HTMLInputElement>(null);
  const desktopSearchInputRef = useRef<HTMLInputElement>(null);

  const PAGE_LIMIT = 20;

  // Auto-focus search if arrived via /search route
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("focus") === "search") {
        const input = window.matchMedia("(min-width: 768px)").matches
          ? desktopSearchInputRef.current
          : mobileSearchInputRef.current;
        input?.focus();
      }
    }
  }, []);

  // Fetch initial bounded page (limit: 20) with server-side query across full dataset
  const fetchPage = useCallback(
    async (offset: number, append: boolean = false) => {
      if (append) setLoadingMore(true);
      else setLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams();
        params.set("limit", PAGE_LIMIT.toString());
        params.set("offset", offset.toString());
        if (query) params.set("q", query);
        if (sort) params.set("sort", sort);
        if (filters.connectorTypes.length > 0) {
          params.set("connectorTypes", filters.connectorTypes.join(","));
          params.set("connectorType", filters.connectorTypes[0]);
        }
        if (filters.distanceKm > 0) {
          params.set("distanceKm", filters.distanceKm.toString());
        }
        if (filters.minChargers > 0) {
          params.set("minChargers", filters.minChargers.toString());
        }
        if (filters.lessBusy) params.set("lessBusy", "true");
        if (filters.minPowerKw > 0) {
          params.set("minPowerKw", filters.minPowerKw.toString());
        }
        if (filters.maxPrice > 0) {
          params.set("maxPrice", filters.maxPrice.toString());
        }
        if (filters.freeOnly) params.set("freeOnly", "true");
        if (filters.availableOnly) params.set("availableOnly", "true");
        if (filters.fastCharging) params.set("fastCharging", "true");
        if (filters.openNow) params.set("openNow", "true");
        if (userLoc) {
          params.set("userLat", userLoc.lat.toString());
          params.set("userLng", userLoc.lng.toString());
        }

        const res = await fetch(`/api/stations?${params.toString()}`);
        if (!res.ok) {
          throw new Error(`Failed to load stations (HTTP ${res.status})`);
        }
        const data = await res.json();

        if (append) {
          setStations((prev) => {
            const existingIds = new Set(prev.map((s) => s.id));
            const newStations = (data.stations as Station[]).filter(
              (s) => !existingIds.has(s.id)
            );
            return [...prev, ...newStations];
          });
        } else {
          setStations(data.stations || []);
          if (data.markers) setMapMarkers(data.markers);
        }

        setTotalCount(data.total ?? 0);
      } catch (err: unknown) {
        console.error("ExploreClient failed to load stations:", err);
        const msg = err instanceof Error ? err.message : "Failed to load stations";
        setError(msg);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [query, filters, sort, userLoc]
  );

  // Trigger search/filter bounded query on change
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchPage(0, false);
    }, 200);
    return () => clearTimeout(timer);
  }, [fetchPage]);

  // Load more stations handler
  function handleLoadMore() {
    if (loadingMore || stations.length >= totalCount) return;
    fetchPage(stations.length, true);
  }

  // Robust Geolocation with complete permission flow and manual fallbacks
  function requestLocation() {
    if (typeof window !== "undefined" && !window.isSecureContext && window.location.hostname !== "localhost") {
      setLocErrorDetails({
        code: "insecure",
        message: "Geolocation requires a secure connection (HTTPS).",
      });
      showToast("Location requires HTTPS");
      return;
    }

    if (!navigator.geolocation) {
      setLocErrorDetails({
        code: "unsupported",
        message: "Geolocation is not supported by your browser.",
      });
      showToast(t("errors.location.body"));
      return;
    }

    setLocating(true);
    setLocErrorDetails(null);

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserLoc({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setLocating(false);
        setLocErrorDetails(null);
        setSort("nearest");
        showToast("Using your location — sorted by nearest chargers");
      },
      (err) => {
        setLocating(false);
        if (err.code === 1) {
          // PERMISSION_DENIED
          setLocErrorDetails({
            code: 1,
            message:
              "Location permission denied. You can search by area (e.g. Mumbai, Pune) or enable location access in browser settings.",
          });
          showToast("Location permission denied");
        } else if (err.code === 2) {
          // POSITION_UNAVAILABLE
          setLocErrorDetails({
            code: 2,
            message: "Location unavailable. Please search manually by city or station name.",
          });
          showToast("Location unavailable");
        } else if (err.code === 3) {
          // TIMEOUT
          setLocErrorDetails({
            code: 3,
            message: "Location request timed out. Please retry or search manually.",
          });
          showToast("Location request timed out");
        } else {
          setLocErrorDetails({
            code: 0,
            message: t("errors.location.body"),
          });
          showToast(t("errors.location.body"));
        }
      },
      { timeout: 10000, enableHighAccuracy: false, maximumAge: 60000 }
    );
  }

  // On marker select: ensure station is available in stations list so preview opens
  const handleSelectStation = useCallback(
    async (id: string) => {
      setSelectedId(id);
      const exists = stations.some((s) => s.id === id);
      if (!exists) {
        try {
          const st = await fetchStationById(id);
          if (st) {
            setStations((prev) => [st, ...prev]);
          }
        } catch (err) {
          console.warn("Could not fetch station details for selected marker:", err);
        }
      }
    },
    [stations]
  );

  const visibleSelectedId = useMemo(
    () => visibleSelection(selectedId, stations),
    [selectedId, stations]
  );

  const selectedStation = useMemo(
    () => resolveSelectedStation(selectedId, stations, stations),
    [stations, selectedId]
  );

  const activeChips = useMemo(() => buildChips(filters, setFilters, t), [filters, t]);

  // Recommendations: evaluate from the bounded loaded stations
  const recommendations: Recommendation[] = useMemo(() => {
    return recommendStations(stations, {
      userLoc,
      connectorTypes: filters.connectorTypes,
    });
  }, [stations, userLoc, filters.connectorTypes]);

  const sortLabels: Record<SortKey, string> = {
    nearest: t("common.sort.nearest"),
    available: t("common.sort.available"),
    speed: t("common.sort.speed"),
    price: t("common.sort.price"),
    recommended: t("common.sort.recommended"),
  };

  // Convert map markers to MapLibre compatible objects
  const mapStationItems = useMemo(() => {
    if (mapMarkers.length > 0) {
      return mapMarkers.map((m) => ({
        id: m.id,
        name: m.name,
        operator: m.operator,
        area: "",
        address: "",
        lat: m.lat,
        lng: m.lng,
        status: m.status,
        minutesSinceUpdate: null,
        connectors: [],
        pricePerKwh: m.pricePerKwh,
        isFree: m.isFree,
        hours: { kind: "unknown" as const },
        rating: m.rating,
        reviewCount: 0,
        busyWindows: [],
      }));
    }
    return stations;
  }, [mapMarkers, stations]);

  return (
    <div className="bg-ink-50">
      <h1 className="sr-only">{t("explore.title")}</h1>

      {/* Mobile search & filter row */}
      <div className="sticky top-14 z-20 border-b border-ink-100 bg-white/95 px-3 pb-3 pt-3 backdrop-blur md:hidden">
        <SearchBar
          value={query}
          onChange={setQuery}
          onUseLocation={requestLocation}
          locating={locating}
          placeholder={t("common.searchPlaceholder")}
          inputRef={mobileSearchInputRef}
        />
        <div className="mt-2.5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              iconLeft={<FilterIcon size={16} />}
              onClick={() => setFiltersOpen(true)}
            >
              {t("common.filters")}
            </Button>
            <SortMenu
              value={sort}
              onChange={setSort}
              label={sortLabels[sort]}
              open={sortOpen}
              setOpen={setSortOpen}
              options={sortLabels}
            />
          </div>
          <WeatherBadge lat={userLoc ? userLoc.lat : 19.076} lng={userLoc ? userLoc.lng : 72.8777} />
        </div>
        {activeChips.length > 0 && (
          <div className="no-scrollbar mt-2 flex gap-1.5 overflow-x-auto">
            {activeChips.map((c, i) => (
              <Chip key={i} label={c.label} onRemove={c.onRemove} />
            ))}
          </div>
        )}
      </div>

      <div className="mx-auto flex max-w-screen-xl flex-col lg:flex-row">
        {/* Map column (mobile + desktop) */}
        <div className="relative px-3 pt-3 md:px-6 md:pt-6 lg:flex-1">
          <div className="h-[44vh] min-h-[320px] lg:h-[calc(100vh-9rem)] lg:min-h-[560px] lg:max-h-[760px]">
            <MapLibreMap
              stations={mapStationItems}
              selectedId={visibleSelectedId}
              onSelect={handleSelectStation}
              userLocation={userLoc}
            />
          </div>

          {/* Location permission explanation / fallback box */}
          {locErrorDetails && (
            <div className="mt-2.5 rounded-[14px] border border-amber-300 bg-amber-50 p-3 text-[12.5px] text-[#8A4E14] shadow-sm">
              <div className="flex items-start gap-2">
                <AlertTriangleIcon size={16} className="shrink-0 text-amber-700 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold">{locErrorDetails.message}</p>
                  <p className="mt-1 text-[12px] text-amber-800">
                    Quick search fallback:
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setQuery("Mumbai")}
                      className="rounded-full border border-amber-300 bg-white px-2.5 py-1 text-[11.5px] font-medium text-amber-900 hover:bg-amber-100"
                    >
                      Search Mumbai
                    </button>
                    <button
                      type="button"
                      onClick={() => setQuery("Pune")}
                      className="rounded-full border border-amber-300 bg-white px-2.5 py-1 text-[11.5px] font-medium text-amber-900 hover:bg-amber-100"
                    >
                      Search Pune
                    </button>
                    <button
                      type="button"
                      onClick={() => setQuery("Thane")}
                      className="rounded-full border border-amber-300 bg-white px-2.5 py-1 text-[11.5px] font-medium text-amber-900 hover:bg-amber-100"
                    >
                      Search Thane
                    </button>
                    <button
                      type="button"
                      onClick={() => setLocErrorDetails(null)}
                      className="text-[11.5px] text-amber-700 underline hover:text-amber-900 ml-1"
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right list / desktop search */}
        <aside className="px-3 pb-6 pt-3 md:px-6 md:pt-6 lg:w-[460px] lg:shrink-0 xl:w-[500px]">
          <div className="hidden md:block">
            <SearchBar
              value={query}
              onChange={setQuery}
              onUseLocation={requestLocation}
              locating={locating}
              placeholder={t("common.searchPlaceholder")}
              inputRef={desktopSearchInputRef}
            />
            <div className="mt-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="md"
                  iconLeft={<FilterIcon size={16} />}
                  onClick={() => setFiltersOpen(true)}
                >
                  {t("common.filters")}
                  {activeChips.length > 0 && (
                    <span className="ml-1.5 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-coral-600 px-1.5 text-[11px] font-medium text-ink-900">
                      {activeChips.length}
                    </span>
                  )}
                </Button>
                <SortMenu
                  value={sort}
                  onChange={setSort}
                  label={sortLabels[sort]}
                  open={sortOpen}
                  setOpen={setSortOpen}
                  options={sortLabels}
                />
              </div>
              <WeatherBadge lat={userLoc ? userLoc.lat : 19.076} lng={userLoc ? userLoc.lng : 72.8777} />
            </div>
            {activeChips.length > 0 && (
              <div className="no-scrollbar mt-2.5 flex gap-1.5 overflow-x-auto">
                {activeChips.map((c, i) => (
                  <Chip key={i} label={c.label} onRemove={c.onRemove} />
                ))}
              </div>
            )}
          </div>

          <div className="mt-4 flex items-center justify-between">
            <p className="text-[12.5px] font-medium text-ink-600">
              {loading ? (
                t("common.loading")
              ) : error ? (
                t("common.unavailable")
              ) : (
                <span>
                  Showing {stations.length} of {totalCount} stations
                </span>
              )}
            </p>
          </div>

          {/* Genuine, Explainable Recommendations */}
          {!loading && !error && recommendations.length > 0 && (
            <div className="mt-3">
              <h2 className="px-1 text-[12px] font-semibold uppercase tracking-wider text-ink-600">
                {t("station.rec.title")}
              </h2>
              <div className="mt-2 space-y-2">
                {recommendations.map((r) => {
                  const st = stations.find((s) => s.id === r.stationId);
                  if (!st) return null;

                  const dist =
                    userLoc && st.lat != null && st.lng != null
                      ? distanceKm(userLoc, { lat: st.lat, lng: st.lng })
                      : null;
                  const distLabel =
                    dist != null && Number.isFinite(dist)
                      ? `${formatDistance(dist).value} ${formatDistance(dist).unit === "m" ? t("common.m") : t("common.km")}`
                      : null;

                  const maxKw = getMaxPowerKw(st);
                  const matchingConnector = filters.connectorTypes[0] || (st.connectors[0]?.type ?? "CCS2");

                  return (
                    <button
                      key={r.stationId}
                      onClick={() => handleSelectStation(r.stationId)}
                      className="block w-full text-left"
                    >
                      <div className="rounded-[16px] border border-coral-200 bg-coral-50 p-3.5 shadow-card hover:shadow-card-hover transition-all">
                        <div className="flex items-center justify-between">
                          <p className="text-[14px] font-semibold text-ink-900">{st.name}</p>
                          <span className="inline-flex h-6 items-center rounded-full bg-white px-2 text-[10.5px] font-semibold text-coral-700">
                            {t("common.recommended")}
                          </span>
                        </div>
                        <ul className="mt-2 space-y-1 text-[12.5px] text-ink-800">
                          {distLabel && (
                            <li className="inline-flex items-center gap-1.5 font-medium text-ink-900">
                              <CheckIcon size={13} className="text-coral-600 shrink-0" />
                              <span>Closest station — {distLabel} away</span>
                            </li>
                          )}
                          {maxKw > 0 && (
                            <li className="inline-flex items-center gap-1.5">
                              <CheckIcon size={13} className="text-coral-600 shrink-0" />
                              <span>High-power {maxKw} kW charging</span>
                            </li>
                          )}
                          {st.isFree === true ? (
                            <li className="inline-flex items-center gap-1.5">
                              <CheckIcon size={13} className="text-coral-600 shrink-0" />
                              <span className="text-green-700 font-medium">Verified free public charging</span>
                            </li>
                          ) : st.pricePerKwh != null ? (
                            <li className="inline-flex items-center gap-1.5">
                              <CheckIcon size={13} className="text-coral-600 shrink-0" />
                              <span>Verified published tariff: ₹{st.pricePerKwh.toFixed(2)}/kWh</span>
                            </li>
                          ) : null}
                          {filters.connectorTypes.length > 0 && (
                            <li className="inline-flex items-center gap-1.5">
                              <CheckIcon size={13} className="text-coral-600 shrink-0" />
                              <span>Matches your required {matchingConnector} connector</span>
                            </li>
                          )}
                          {r.reasons.includes("availableNow") && r.availableCount != null ? (
                            <li className="inline-flex items-center gap-1.5 text-green-700 font-medium">
                              <CheckIcon size={13} className="text-green-600 shrink-0" />
                              <span>{r.availableCount} charger(s) currently reported available</span>
                            </li>
                          ) : (
                            <li className="inline-flex items-center gap-1.5 text-ink-600">
                              <CheckIcon size={13} className="text-coral-600 shrink-0" />
                              <span>Real-time availability unobserved (telemetry cold start)</span>
                            </li>
                          )}
                        </ul>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* List */}
          <div className="mt-3 space-y-3">
            {loading ? (
              <>
                <StationCardSkeleton />
                <StationCardSkeleton />
                <StationCardSkeleton />
              </>
            ) : error ? (
              <div className="rounded-[18px] border border-ink-100 bg-white p-6 text-center shadow-card">
                <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-red-50 text-red-600">
                  <AlertTriangleIcon size={20} />
                </span>
                <h2 className="mt-3 text-[15.5px] font-semibold text-ink-900">
                  {t("errors.network.title")}
                </h2>
                <p className="mt-1 text-[13px] text-ink-600">
                  {t("errors.network.body")}
                </p>
                <div className="mt-4">
                  <Button variant="primary" size="md" onClick={() => fetchPage(0, false)}>
                    {t("common.tryAgain")}
                  </Button>
                </div>
              </div>
            ) : stations.length === 0 ? (
              <EmptyResults
                onClear={() => {
                  setFilters(DEFAULT_EXPLORE_FILTERS);
                  setQuery("");
                }}
              />
            ) : (
              <>
                {stations.map((s) => (
                  <div
                    key={s.id}
                    role="group"
                    tabIndex={0}
                    aria-label={s.name}
                    onClick={(event) => {
                      if (
                        event.target instanceof Element &&
                        event.target.closest("a,button,input,select,textarea")
                      ) {
                        return;
                      }
                      handleSelectStation(s.id);
                    }}
                    onKeyDown={(event) => {
                      if (
                        (event.key === "Enter" || event.key === " ") &&
                        event.target === event.currentTarget
                      ) {
                        event.preventDefault();
                        handleSelectStation(s.id);
                      }
                    }}
                    className="block w-full text-left cursor-pointer"
                  >
                    <div
                      className={cx(
                        "rounded-[18px] transition-all",
                        visibleSelectedId === s.id &&
                          "ring-2 ring-coral-600 ring-offset-2 ring-offset-ink-50 shadow-md"
                      )}
                    >
                      <StationCard station={s} userLocation={userLoc} />
                    </div>
                  </div>
                ))}

                {/* Show more stations action */}
                {stations.length < totalCount && (
                  <div className="pt-3 pb-6 text-center">
                    <Button
                      variant="secondary"
                      size="md"
                      onClick={handleLoadMore}
                      disabled={loadingMore}
                    >
                      {loadingMore ? (
                        <span>Loading stations…</span>
                      ) : (
                        <span>
                          Show more stations ({stations.length} of {totalCount})
                        </span>
                      )}
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </aside>
      </div>

      <FiltersPanel
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        value={filters}
        onChange={setFilters}
      />
      <StationPreviewSheet
        station={selectedStation}
        onClose={() => setSelectedId(null)}
        userLocation={userLoc}
      />
    </div>
  );
}

function SearchBar({
  value,
  onChange,
  onUseLocation,
  locating,
  placeholder,
  inputRef,
}: {
  value: string;
  onChange: (v: string) => void;
  onUseLocation: () => void;
  locating: boolean;
  placeholder: string;
  inputRef?: React.RefObject<HTMLInputElement | null>;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2">
      <label className="relative flex-1">
        <span className="sr-only">{t("common.search")}</span>
        <SearchIcon
          size={16}
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-500"
        />
        <input
          ref={inputRef}
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="h-11 w-full rounded-full border border-ink-200 bg-white pl-9 pr-4 text-[14px] text-ink-900 placeholder:text-ink-500 focus-visible:border-coral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-coral-600/30 shadow-sm"
        />
      </label>
      <button
        type="button"
        onClick={onUseLocation}
        disabled={locating}
        title="Use your location to discover nearby chargers"
        aria-label={t("common.useMyLocation")}
        className="inline-flex h-11 shrink-0 items-center gap-1.5 rounded-full bg-coral-600 px-3.5 text-[13px] font-medium text-ink-900 shadow-card hover:bg-coral-700 disabled:bg-coral-300 transition-colors"
      >
        {locating ? (
          <span
            className="inline-block h-3.5 w-3.5 rounded-full border-2 border-white border-r-transparent animate-spin"
            aria-hidden
          />
        ) : (
          <PinIcon size={14} />
        )}
        <span className="hidden sm:inline">{t("common.useMyLocation")}</span>
      </button>
    </div>
  );
}

function SortMenu({
  value,
  onChange,
  label,
  open,
  setOpen,
  options,
}: {
  value: SortKey;
  onChange: (v: SortKey) => void;
  label: string;
  open: boolean;
  setOpen: (b: boolean) => void;
  options: Record<SortKey, string>;
}) {
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="inline-flex h-10 items-center gap-1.5 rounded-full border border-ink-200 bg-white px-3.5 text-[13px] font-medium text-ink-800 hover:bg-ink-50 shadow-sm"
      >
        <SortIcon size={14} />
        {label}
        <ChevronDownIcon size={14} />
      </button>
      {open && (
        <ul
          role="listbox"
          className="absolute right-0 z-30 mt-2 w-48 overflow-hidden rounded-[14px] border border-ink-100 bg-white shadow-pop animate-pop-in"
          onMouseLeave={() => setOpen(false)}
        >
          {(Object.keys(options) as SortKey[]).map((k) => (
            <li key={k}>
              <button
                role="option"
                aria-selected={value === k}
                onClick={() => {
                  onChange(k);
                  setOpen(false);
                }}
                className={cx(
                  "flex w-full items-center justify-between px-3 py-2 text-left text-[13.5px] hover:bg-ink-50",
                  value === k && "bg-apricot-50 text-coral-700 font-medium"
                )}
              >
                {options[k]}
                {value === k && <CheckIcon size={14} className="text-coral-600" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-coral-200 bg-coral-50 px-2.5 py-1 text-[11.5px] font-medium text-coral-700">
      {label}
      <button
        type="button"
        aria-label="Remove filter"
        onClick={onRemove}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-white text-coral-700 hover:bg-coral-100"
      >
        ×
      </button>
    </span>
  );
}

function EmptyResults({ onClear }: { onClear: () => void }) {
  const { t } = useI18n();
  return (
    <div className="rounded-[18px] border border-ink-100 bg-white p-6 text-center shadow-card">
      <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-apricot-100 text-coral-700">
        <SearchIcon size={20} />
      </span>
      <h2 className="mt-3 text-[15.5px] font-semibold text-ink-900">
        {t("explore.noResults.title")}
      </h2>
      <p className="mt-1 text-[13px] text-ink-600">{t("explore.noResults.body")}</p>
      <div className="mt-4">
        <Button variant="secondary" size="md" onClick={onClear}>
          {t("common.clearAll")}
        </Button>
      </div>
    </div>
  );
}

function buildChips(
  f: FiltersState,
  setFilters: React.Dispatch<React.SetStateAction<FiltersState>>,
  t: (k: any, vars?: Record<string, string | number>) => string
): { label: string; onRemove: () => void }[] {
  const out: { label: string; onRemove: () => void }[] = [];
  if (f.connectorTypes.length > 0) {
    for (const c of f.connectorTypes) {
      out.push({
        label: c,
        onRemove: () => {
          setFilters((prev) => ({
            ...prev,
            connectorTypes: prev.connectorTypes.filter((x) => x !== c),
          }));
        },
      });
    }
  }
  if (f.distanceKm > 0)
    out.push({
      label: t("filters.withinKm", { km: f.distanceKm }),
      onRemove: () => setFilters((prev) => ({ ...prev, distanceKm: 0 })),
    });
  if (f.minPowerKw > 0)
    out.push({
      label: t("filters.overKw", { kw: f.minPowerKw }),
      onRemove: () => setFilters((prev) => ({ ...prev, minPowerKw: 0 })),
    });
  if (f.maxPrice > 0)
    out.push({
      label: t("filters.underKwh", { price: f.maxPrice }),
      onRemove: () => setFilters((prev) => ({ ...prev, maxPrice: 0 })),
    });
  if (f.openNow)
    out.push({
      label: t("filters.openNow"),
      onRemove: () => setFilters((prev) => ({ ...prev, openNow: false })),
    });
  if (f.availableOnly)
    out.push({
      label: t("filters.availability") + ": " + t("station.status.available"),
      onRemove: () => setFilters((prev) => ({ ...prev, availableOnly: false })),
    });
  if (f.fastCharging)
    out.push({
      label: t("filters.fastCharging"),
      onRemove: () => setFilters((prev) => ({ ...prev, fastCharging: false })),
    });
  if (f.freeOnly)
    out.push({
      label: t("filters.freeCharging"),
      onRemove: () => setFilters((prev) => ({ ...prev, freeOnly: false })),
    });
  if (f.lessBusy)
    out.push({
      label: t("filters.lessBusy"),
      onRemove: () => setFilters((prev) => ({ ...prev, lessBusy: false })),
    });
  if (f.minChargers > 0)
    out.push({
      label: `≥ ${f.minChargers} ${t("station.chargers")}`,
      onRemove: () => setFilters((prev) => ({ ...prev, minChargers: 0 })),
    });
  return out;
}
