"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import { fetchStations, getAvailableChargers } from "@/data/stations";
import {
  DEFAULT_EXPLORE_FILTERS,
  filterAndSortStations,
  resolveSelectedStation,
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

export function ExploreClient() {
  const { t } = useI18n();
  const { show: showToast } = useToast();

  const [stations, setStations] = useState<Station[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<FiltersState>(DEFAULT_EXPLORE_FILTERS);
  const [sort, setSort] = useState<SortKey>("nearest");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [userLoc, setUserLoc] = useState<{ lat: number; lng: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [locError, setLocError] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sortOpen, setSortOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [retryNonce, setRetryNonce] = useState(0);
  const loadStations = useCallback(() => {
    // Sync state reset lives in the event handler (not the effect below).
    setLoading(true);
    setError(null);
    setRetryNonce((n) => n + 1);
  }, []);

  // Auto-focus search if arrived via /search route
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("focus") === "search") {
        searchInputRef.current?.focus();
      }
    }
  }, []);

  useEffect(() => {
    let active = true;
    fetchStations()
      .then((data) => {
        if (!active) return;
        setStations(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        console.error("ExploreClient failed to load stations:", err);
        const msg = err instanceof Error ? err.message : "Failed to load stations";
        setError(msg);
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [retryNonce]);

  function requestLocation() {
    if (!navigator.geolocation) {
      setLocError(true);
      showToast(t("errors.location.body"));
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserLoc({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setLocating(false);
        showToast("Using your location");
      },
      () => {
        setLocError(true);
        setLocating(false);
        showToast(t("errors.location.body"));
      },
      { timeout: 8000 }
    );
  }

  const filtered = useMemo(
    () => filterAndSortStations(stations, { query, filters, sort, userLoc }),
    [stations, query, filters, sort, userLoc]
  );

  const selectedStation = useMemo(
    () => resolveSelectedStation(selectedId, filtered, stations),
    [filtered, stations, selectedId]
  );

  const activeChips = useMemo(() => buildChips(filters, setFilters, t), [filters, t]);

  const recommendations: Recommendation[] = useMemo(() => {
    // Recommend up to 1 well-matched station from the visible list
    const cand = filtered.find((s) => s.status === "available" && (getAvailableChargers(s) ?? 0) > 0);
    if (!cand) return [];
    return [
      {
        stationId: cand.id,
        reasons: ["availableNow", "matchConnector"],
        availableCount: getAvailableChargers(cand) ?? undefined,
      },
    ];
  }, [filtered]);

  const sortLabels: Record<SortKey, string> = {
    nearest: t("common.sort.nearest"),
    available: t("common.sort.available"),
    speed: t("common.sort.speed"),
    price: t("common.sort.price"),
    recommended: t("common.sort.recommended"),
  };

  return (
    <div className="bg-ink-50">
      {/* Mobile search & filter row */}
      <div className="sticky top-14 z-20 border-b border-ink-100 bg-white/95 px-3 pb-3 pt-3 backdrop-blur md:hidden">
        <SearchBar
          value={query}
          onChange={setQuery}
          onUseLocation={requestLocation}
          locating={locating}
          placeholder={t("common.searchPlaceholder")}
          inputRef={searchInputRef}
        />
        <div className="mt-2.5 flex items-center gap-2">
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
        {activeChips.length > 0 && (
          <div className="no-scrollbar mt-2 flex gap-1.5 overflow-x-auto">
            {activeChips.map((c, i) => (
              <Chip key={i} label={c.label} onRemove={c.onRemove} />
            ))}
          </div>
        )}
      </div>

      <div className="mx-auto flex max-w-screen-xl flex-col lg:flex-row">
        {/* Map (mobile + desktop) */}
        <div className="relative px-3 pt-3 md:px-6 md:pt-6 lg:flex-1">
          <div className="h-[44vh] min-h-[320px] lg:h-[calc(100vh-9rem)] lg:min-h-[560px] lg:max-h-[760px]">
            <MapLibreMap
              stations={filtered}
              selectedId={selectedId}
              onSelect={(id) => setSelectedId(id)}
              userLocation={userLoc}
            />
          </div>
          {locError && (
            <div className="mt-2 rounded-[12px] border border-amber-200 bg-amber-50 px-3 py-2 text-[12.5px] text-[#8A4E14]">
              {t("errors.location.body")}
            </div>
          )}
        </div>

        {/* Right list / desktop search */}
        <aside className="px-3 pb-4 pt-3 md:px-6 md:pt-6 lg:w-[460px] lg:shrink-0 xl:w-[500px]">
          <div className="hidden md:block">
            <SearchBar
              value={query}
              onChange={setQuery}
              onUseLocation={requestLocation}
              locating={locating}
              placeholder={t("common.searchPlaceholder")}
              inputRef={searchInputRef}
            />
            <div className="mt-3 flex items-center gap-2">
              <Button
                variant="secondary"
                size="md"
                iconLeft={<FilterIcon size={16} />}
                onClick={() => setFiltersOpen(true)}
              >
                {t("common.filters")}
                {activeChips.length > 0 && (
                  <span className="ml-1.5 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-coral-600 px-1.5 text-[11px] font-medium text-white">
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
            {activeChips.length > 0 && (
              <div className="no-scrollbar mt-2.5 flex gap-1.5 overflow-x-auto">
                {activeChips.map((c, i) => (
                  <Chip key={i} label={c.label} onRemove={c.onRemove} />
                ))}
              </div>
            )}
          </div>

          <div className="mt-4 flex items-center justify-between">
            <p className="text-[12.5px] text-ink-600">
              {loading
                ? t("common.loading")
                : error
                ? t("common.unavailable")
                : t("common.resultsCount", { count: filtered.length })}
            </p>
          </div>

          {/* Recommendations */}
          {recommendations.length > 0 && !loading && !error && (
            <div className="mt-3">
              <h3 className="px-1 text-[12px] font-semibold uppercase tracking-wider text-ink-600">
                {t("station.rec.title")}
              </h3>
              <div className="mt-2 space-y-2">
                {recommendations.map((r) => {
                  const st = filtered.find((s) => s.id === r.stationId)!;
                  return (
                    <button
                      key={r.stationId}
                      onClick={() => setSelectedId(r.stationId)}
                      className="block w-full text-left"
                    >
                      <div className="rounded-[16px] border border-coral-200 bg-coral-50 p-3 shadow-card hover:shadow-card-hover">
                        <div className="flex items-center justify-between">
                          <p className="text-[14px] font-semibold text-ink-900">{st.name}</p>
                          <span className="inline-flex h-6 items-center rounded-full bg-white px-2 text-[10.5px] font-semibold text-coral-700">
                            {t("common.recommended")}
                          </span>
                        </div>
                        <ul className="mt-1.5 space-y-1 text-[12.5px] text-ink-700">
                          <li className="inline-flex items-center gap-1.5">
                            <CheckIcon size={13} className="text-coral-600" />
                            {t("station.rec.matchConnector")}
                          </li>
                          {r.availableCount != null && (
                            <li className="inline-flex items-center gap-1.5">
                              <CheckIcon size={13} className="text-coral-600" />
                              {t("station.rec.availableNow", { n: r.availableCount })}
                            </li>
                          )}
                          <li className="inline-flex items-center gap-1.5">
                            <CheckIcon size={13} className="text-coral-600" />
                            {t("station.rec.lessBusyNow")}
                          </li>
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
                <h3 className="mt-3 text-[15.5px] font-semibold text-ink-900">
                  {t("errors.network.title")}
                </h3>
                <p className="mt-1 text-[13px] text-ink-600">
                  {t("errors.network.body")}
                </p>
                <div className="mt-4">
                  <Button variant="primary" size="md" onClick={loadStations}>
                    {t("common.tryAgain")}
                  </Button>
                </div>
              </div>
            ) : filtered.length === 0 ? (
              <EmptyResults onClear={() => { setFilters(DEFAULT_EXPLORE_FILTERS); setQuery(""); }} />
            ) : (
              filtered.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setSelectedId(s.id)}
                  className="block w-full text-left"
                  aria-pressed={selectedId === s.id}
                >
                  <div
                    className={cx(
                      "rounded-[18px]",
                      selectedId === s.id && "ring-2 ring-coral-600 ring-offset-2 ring-offset-ink-50"
                    )}
                  >
                    <StationCard station={s} userLocation={userLoc} />
                  </div>
                </button>
              ))
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
          className="h-11 w-full rounded-full border border-ink-200 bg-white pl-9 pr-4 text-[14px] text-ink-900 placeholder:text-ink-500 focus-visible:border-coral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-coral-600/30"
        />
      </label>
      <button
        type="button"
        onClick={onUseLocation}
        disabled={locating}
        aria-label={t("common.useMyLocation")}
        className="inline-flex h-11 shrink-0 items-center gap-1.5 rounded-full bg-coral-600 px-3.5 text-[13px] font-medium text-white shadow-card hover:bg-coral-700 disabled:bg-coral-300"
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
        className="inline-flex h-10 items-center gap-1.5 rounded-full border border-ink-200 bg-white px-3.5 text-[13px] font-medium text-ink-800 hover:bg-ink-50"
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
                onClick={() => {
                  onChange(k);
                  setOpen(false);
                }}
                className={cx(
                  "flex w-full items-center justify-between px-3 py-2 text-left text-[13.5px] hover:bg-ink-50",
                  value === k && "bg-apricot-50 text-coral-700"
                )}
              >
                {options[k]}
                {value === k && (
                  <CheckIcon size={14} className="text-coral-600" />
                )}
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
      <h3 className="mt-3 text-[15.5px] font-semibold text-ink-900">
        {t("explore.noResults.title")}
      </h3>
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
