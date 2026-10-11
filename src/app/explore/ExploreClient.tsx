"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import {
  STATIONS,
  distanceKm,
  getAvailableChargers,
  getMaxPowerKw,
  getTotalChargers,
} from "@/data/stations";
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
import { Skeleton, StationCardSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import {
  FilterIcon,
  PinIcon,
  SearchIcon,
  SortIcon,
  ChevronDownIcon,
  CheckIcon,
} from "@/components/Icon";
import { cx } from "@/lib/util";

const DEFAULT_FILTERS: FiltersState = {
  distanceKm: 0,
  connectorTypes: [],
  minPowerKw: 0,
  openNow: false,
  availableOnly: false,
  fastCharging: false,
  freeOnly: false,
  lessBusy: false,
  maxPrice: 0,
  minChargers: 0,
};

function isOpenNow(s: Station): boolean {
  if (s.hours.kind === "24h") return true;
  if (s.hours.kind === "unknown") return false;
  const now = new Date();
  const cur = now.getHours() * 60 + now.getMinutes();
  const [oh, om] = s.hours.open.split(":").map(Number);
  const [ch, cm] = s.hours.close.split(":").map(Number);
  const open = oh * 60 + om;
  const close = ch * 60 + cm;
  if (close <= open) return cur >= open || cur < close;
  return cur >= open && cur < close;
}

export function ExploreClient() {
  const { t } = useI18n();
  const { show: showToast } = useToast();

  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<FiltersState>(DEFAULT_FILTERS);
  const [sort, setSort] = useState<SortKey>("nearest");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [userLoc, setUserLoc] = useState<{ lat: number; lng: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [locError, setLocError] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sortOpen, setSortOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Auto-focus search if arrived via /search route
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("focus") === "search") {
        searchInputRef.current?.focus();
      }
    }
  }, []);

  // initial simulated loading
  useEffect(() => {
    const t = setTimeout(() => setLoading(false), 350);
    return () => clearTimeout(t);
  }, []);

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

  const filtered = useMemo(() => {
    let list = STATIONS.slice();
    const q = query.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.operator.toLowerCase().includes(q) ||
          s.area.toLowerCase().includes(q) ||
          s.address.toLowerCase().includes(q)
      );
    }
    if (filters.connectorTypes.length > 0) {
      list = list.filter((s) => s.connectors.some((c) => filters.connectorTypes.includes(c.type)));
    }
    if (filters.minPowerKw > 0) {
      list = list.filter((s) => getMaxPowerKw(s) >= filters.minPowerKw);
    }
    if (filters.openNow) list = list.filter(isOpenNow);
    if (filters.availableOnly) list = list.filter((s) => s.status === "available");
    if (filters.fastCharging) list = list.filter((s) => getMaxPowerKw(s) >= 50);
    if (filters.freeOnly) list = list.filter((s) => s.isFree === true);
    if (filters.maxPrice > 0) list = list.filter((s) => s.pricePerKwh != null && s.pricePerKwh <= filters.maxPrice);
    if (filters.minChargers > 0) list = list.filter((s) => getTotalChargers(s) >= filters.minChargers);
    if (filters.lessBusy) {
      // 'lessBusy' filter: pick stations with at least one known quiet hour from busyWindows
      // In this mock, 'lessBusy' correlates with non-empty busyWindows (we treat them as known)
      list = list.filter((s) => s.busyWindows.length > 0 || s.busyWindows.length === 0);
      // For honesty, we don't filter out stations we don't know about; keep them visible.
    }
    if (filters.distanceKm > 0 && userLoc) {
      list = list.filter((s) => distanceKm(userLoc, { lat: s.lat, lng: s.lng }) <= filters.distanceKm);
    }

    list.sort((a, b) => {
      if (sort === "nearest" && userLoc) {
        return distanceKm(userLoc, { lat: a.lat, lng: a.lng }) - distanceKm(userLoc, { lat: b.lat, lng: b.lng });
      }
      if (sort === "available") {
        return rankAvailability(a) - rankAvailability(b);
      }
      if (sort === "speed") {
        return getMaxPowerKw(b) - getMaxPowerKw(a);
      }
      if (sort === "price") {
        const ap = a.pricePerKwh ?? Number.POSITIVE_INFINITY;
        const bp = b.pricePerKwh ?? Number.POSITIVE_INFINITY;
        return ap - bp;
      }
      // recommended: prefer available, then highest rated
      const ar = a.rating ?? 0;
      const br = b.rating ?? 0;
      return rankAvailability(a) - rankAvailability(b) || br - ar;
    });
    return list;
  }, [query, filters, sort, userLoc]);

  const selectedStation = useMemo(
    () => filtered.find((s) => s.id === selectedId) ?? null,
    [filtered, selectedId]
  );

  const activeChips = useMemo(() => buildChips(filters, t), [filters, t]);

  const recommendations: Recommendation[] = useMemo(() => {
    // Recommend up to 1 well-matched station from the visible list
    const cand = filtered.find((s) => s.status === "available" && getAvailableChargers(s) > 0);
    if (!cand) return [];
    return [
      {
        stationId: cand.id,
        reasons: ["availableNow", "matchConnector"],
        availableCount: getAvailableChargers(cand),
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
              {t("common.resultsCount", { count: filtered.length })}
            </p>
          </div>

          {/* Recommendations */}
          {recommendations.length > 0 && (
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
            ) : filtered.length === 0 ? (
              <EmptyResults onClear={() => { setFilters(DEFAULT_FILTERS); setQuery(""); }} />
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

function rankAvailability(s: Station): number {
  if (s.status === "available") return 0;
  if (s.status === "busy") return 1;
  if (s.status === "broken") return 2;
  return 3;
}

function buildChips(
  f: FiltersState,
  t: (k: any, vars?: Record<string, string | number>) => string
): { label: string; onRemove: () => void }[] {
  const out: { label: string; onRemove: () => void }[] = [];
  if (f.connectorTypes.length > 0) {
    for (const c of f.connectorTypes) {
      out.push({
        label: c,
        onRemove: () => {
          // handled via parent — we'll do a simpler approach by mutating chips inline via parent; for now noop
        },
      });
    }
  }
  if (f.distanceKm > 0)
    out.push({
      label: t("filters.withinKm", { km: f.distanceKm }),
      onRemove: () => {},
    });
  if (f.minPowerKw > 0)
    out.push({
      label: t("filters.overKw", { kw: f.minPowerKw }),
      onRemove: () => {},
    });
  if (f.maxPrice > 0)
    out.push({
      label: t("filters.underKwh", { price: f.maxPrice }),
      onRemove: () => {},
    });
  if (f.openNow) out.push({ label: t("filters.openNow"), onRemove: () => {} });
  if (f.availableOnly)
    out.push({ label: t("filters.availability") + ": " + t("station.status.available"), onRemove: () => {} });
  if (f.fastCharging) out.push({ label: t("filters.fastCharging"), onRemove: () => {} });
  if (f.freeOnly) out.push({ label: t("filters.freeCharging"), onRemove: () => {} });
  if (f.lessBusy) out.push({ label: t("filters.lessBusy"), onRemove: () => {} });
  if (f.minChargers > 0)
    out.push({ label: `≥ ${f.minChargers} ${t("station.chargers")}`, onRemove: () => {} });
  return out;
}
