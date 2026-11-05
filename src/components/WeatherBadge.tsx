"use client";

import { useEffect, useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";

interface WeatherData {
  available: boolean;
  temperature?: number;
  temperatureUnit?: string;
  humidity?: number;
  conditionEn?: string;
  conditionHi?: string;
  conditionMr?: string;
  windSpeed?: number;
  windSpeedUnit?: string;
  timestamp?: string;
  provider?: string;
  error?: string;
}

export function WeatherBadge({
  lat,
  lng,
  className = "",
}: {
  lat: number | null | undefined;
  lng: number | null | undefined;
  className?: string;
}) {
  const { lang } = useI18n();
  const [data, setData] = useState<WeatherData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (lat == null || lng == null || isNaN(lat) || isNaN(lng)) return;

    let active = true;
    Promise.resolve().then(() => {
      if (active) setLoading(true);
    });

    fetch(`/api/weather?lat=${lat}&lng=${lng}`)
      .then((res) => res.json())
      .then((json: WeatherData) => {
        if (!active) return;
        setData(json);
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        setData({ available: false, error: err?.message || "Failed to load weather" });
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [lat, lng]);

  if (lat == null || lng == null) return null;

  if (loading) {
    return (
      <div className={`inline-flex items-center gap-1.5 rounded-full border border-ink-100 bg-white/80 px-2.5 py-1 text-[11.5px] text-ink-500 backdrop-blur ${className}`}>
        <span className="inline-block h-2 w-2 rounded-full bg-coral-400 animate-pulse" />
        <span>Weather...</span>
      </div>
    );
  }

  if (!data || !data.available || data.temperature == null) {
    return null;
  }

  const condition =
    lang === "hi"
      ? data.conditionHi || data.conditionEn
      : lang === "mr"
      ? data.conditionMr || data.conditionEn
      : data.conditionEn;

  return (
    <div
      title={`Live Weather via ${data.provider || "Open-Meteo"} at ${data.timestamp ? new Date(data.timestamp).toLocaleTimeString() : ""}`}
      className={`inline-flex items-center gap-1.5 rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-[11.5px] font-medium text-sky-900 shadow-sm ${className}`}
    >
      <span className="text-[13px]" aria-hidden="true">
        ⛅
      </span>
      <span>
        {Math.round(data.temperature)}
        {data.temperatureUnit || "°C"}
      </span>
      <span className="text-sky-300">·</span>
      <span className="truncate max-w-[120px]">{condition}</span>
    </div>
  );
}
