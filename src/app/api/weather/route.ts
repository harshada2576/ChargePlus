import { NextRequest, NextResponse } from "next/server";

interface WeatherCacheEntry {
  data: any;
  cachedAt: number;
}

const CACHE_TTL_MS = 15 * 60 * 1000; // 15 minutes
const weatherCache = new Map<string, WeatherCacheEntry>();

// WMO Weather interpretation codes (WW)
const WMO_CODES: Record<number, { en: string; hi: string; mr: string }> = {
  0: { en: "Clear sky", hi: "साफ़ आसमान", mr: "निरभ्र आकाश" },
  1: { en: "Mainly clear", hi: "अधिकांशतः साफ़", mr: "मुख्यतः निरभ्र" },
  2: { en: "Partly cloudy", hi: "आंशिक बादल", mr: "अंशतः ढगाळ" },
  3: { en: "Overcast", hi: "बादल छाए हुए", mr: "ढगाळ वातावरण" },
  45: { en: "Foggy", hi: "कोहरा", mr: "धुके" },
  48: { en: "Depositing rime fog", hi: "घना कोहरा", mr: "दाट धुके" },
  51: { en: "Light drizzle", hi: "हल्की बूंदाबांदी", mr: "हलकी रिमझिम" },
  53: { en: "Moderate drizzle", hi: "मध्यम बूंदाबांदी", mr: "मध्यम रिमझिम" },
  55: { en: "Dense drizzle", hi: "तेज़ बूंदाबांदी", mr: "जोरदार रिमझिम" },
  61: { en: "Slight rain", hi: "हल्की बारिश", mr: "हलका पाऊस" },
  63: { en: "Moderate rain", hi: "मध्यम बारिश", mr: "मध्यम पाऊस" },
  65: { en: "Heavy rain", hi: "भारी बारिश", mr: "मुसळधार पाऊस" },
  80: { en: "Rain showers", hi: "बारिश की बौछारें", mr: "पावसाच्या सरी" },
  95: { en: "Thunderstorm", hi: "गरज के साथ तूफ़ान", mr: "वादळी पाऊस" },
};

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const latStr = searchParams.get("lat");
  const lngStr = searchParams.get("lng");

  if (!latStr || !lngStr) {
    return NextResponse.json(
      { available: false, error: "Missing lat/lng coordinates" },
      { status: 400 }
    );
  }

  const lat = parseFloat(latStr);
  const lng = parseFloat(lngStr);

  if (isNaN(lat) || isNaN(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
    return NextResponse.json(
      { available: false, error: "Invalid coordinates range" },
      { status: 400 }
    );
  }

  // Cache key rounded to ~1.1km grid
  const cacheKey = `${lat.toFixed(2)},${lng.toFixed(2)}`;
  const now = Date.now();
  const cached = weatherCache.get(cacheKey);

  if (cached && now - cached.cachedAt < CACHE_TTL_MS) {
    return NextResponse.json(cached.data, {
      headers: {
        "Cache-Control": "public, s-maxage=900, stale-while-revalidate=300",
        "X-Cache": "HIT",
      },
    });
  }

  try {
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lng}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&timezone=auto`;
    const res = await fetch(url, {
      signal: AbortSignal.timeout(5000),
      headers: {
        "User-Agent": "ChargePlus-EV-Platform/2.0 (Open-Data-Integration)",
      },
    });

    if (!res.ok) {
      throw new Error(`Open-Meteo returned HTTP ${res.status}`);
    }

    const json = await res.json();
    const current = json.current;

    if (!current) {
      throw new Error("Invalid response format from Open-Meteo");
    }

    const code = current.weather_code ?? 0;
    const condition = WMO_CODES[code] || { en: "Fair", hi: "सामान्य", mr: "सामान्य" };

    const payload = {
      available: true,
      temperature: current.temperature_2m,
      temperatureUnit: "°C",
      humidity: current.relative_humidity_2m,
      weatherCode: code,
      conditionEn: condition.en,
      conditionHi: condition.hi,
      conditionMr: condition.mr,
      windSpeed: current.wind_speed_10m,
      windSpeedUnit: "km/h",
      timestamp: current.time,
      provider: "Open-Meteo",
    };

    weatherCache.set(cacheKey, { data: payload, cachedAt: now });

    return NextResponse.json(payload, {
      headers: {
        "Cache-Control": "public, s-maxage=900, stale-while-revalidate=300",
        "X-Cache": "MISS",
      },
    });
  } catch (err: any) {
    console.warn("Weather fetch failed (handled gracefully):", err?.message || err);
    return NextResponse.json(
      {
        available: false,
        error: "Weather service unavailable",
        provider: "Open-Meteo",
        timestamp: new Date().toISOString(),
      },
      { status: 200 } // Return 200 with available=false so UI handles gracefully
    );
  }
}
