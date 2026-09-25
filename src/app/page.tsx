"use client";

import { Button } from "@/components/Button";
import { BrandMark } from "@/components/BrandMark";
import {
  BoltIcon,
  CompassIcon,
  CheckIcon,
  HeartIcon,
  BellIcon,
  PinIcon,
  ClockIcon,
} from "@/components/Icon";
import { Link } from "@/i18n/Link";
import { useI18n } from "@/i18n/I18nProvider";

export default function HomePage() {
  const { t } = useI18n();

  const features = [
    {
      Icon: PinIcon,
      title: t("home.features.find.title"),
      body: t("home.features.find.body"),
    },
    {
      Icon: CheckIcon,
      title: t("home.features.availability.title"),
      body: t("home.features.availability.body"),
    },
    {
      Icon: BoltIcon,
      title: t("home.features.compare.title"),
      body: t("home.features.compare.body"),
    },
    {
      Icon: HeartIcon,
      title: t("home.features.save.title"),
      body: t("home.features.save.body"),
    },
    {
      Icon: BellIcon,
      title: t("home.features.alerts.title"),
      body: t("home.features.alerts.body"),
    },
  ];

  return (
    <div className="bg-ink-50">
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div
          aria-hidden
          className="absolute inset-x-0 top-0 -z-10 h-[640px] bg-gradient-to-b from-apricot-100 via-apricot-50 to-transparent"
        />
        <div className="mx-auto max-w-screen-xl px-4 pb-12 pt-12 sm:px-6 sm:pb-16 sm:pt-16 lg:pt-20">
          <div className="grid items-center gap-10 lg:grid-cols-12">
            <div className="lg:col-span-7">
              <span className="inline-flex items-center gap-2 rounded-full border border-coral-200 bg-white/80 px-3 py-1 text-[12px] font-medium text-coral-700">
                <span className="h-1.5 w-1.5 rounded-full bg-coral-600" />
                {t("home.hero.eyebrow")}
              </span>
              <h1 className="mt-4 text-[clamp(2.1rem,5vw,3.4rem)] font-semibold leading-[1.05] tracking-[-0.02em] text-ink-900">
                {t("home.hero.title")}
              </h1>
              <p className="mt-4 max-w-xl text-[15.5px] leading-relaxed text-ink-700">
                {t("home.hero.subtitle")}
              </p>
              <div className="mt-7 flex flex-wrap items-center gap-3">
                <Link href="/explore">
                  <Button size="lg" variant="primary">
                    <PinIcon size={18} />
                    {t("home.hero.ctaPrimary")}
                  </Button>
                </Link>
                <Link href="/explore">
                  <Button size="lg" variant="secondary">
                    <CompassIcon size={18} />
                    {t("home.hero.ctaSecondary")}
                  </Button>
                </Link>
              </div>

              <ul className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12.5px] text-ink-600">
                <li className="inline-flex items-center gap-1.5">
                  <CheckIcon size={14} className="text-coral-600" />
                  No login required to search
                </li>
                <li className="inline-flex items-center gap-1.5">
                  <CheckIcon size={14} className="text-coral-600" />
                  Available in English, हिन्दी, मराठी
                </li>
                <li className="inline-flex items-center gap-1.5">
                  <CheckIcon size={14} className="text-coral-600" />
                  Mumbai pilot
                </li>
              </ul>
            </div>

            {/* Hero visual */}
            <div className="lg:col-span-5">
              <HeroVisual />
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-screen-xl px-4 py-12 sm:px-6 sm:py-16">
        <div className="max-w-2xl">
          <h2 className="text-[clamp(1.6rem,3vw,2.1rem)] font-semibold tracking-[-0.01em] text-ink-900">
            {t("home.features.title")}
          </h2>
          <p className="mt-2 text-[15px] text-ink-700">
            {t("home.features.subtitle")}
          </p>
        </div>
        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => (
            <article
              key={f.title}
              className="group rounded-[20px] border border-ink-100 bg-white p-5 shadow-card transition-shadow hover:shadow-card-hover"
            >
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-[12px] bg-coral-50 text-coral-700">
                <f.Icon size={20} />
              </span>
              <h3 className="mt-3 text-[15.5px] font-semibold text-ink-900">{f.title}</h3>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-700">{f.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* Trust */}
      <section className="mx-auto max-w-screen-xl px-4 pb-16 sm:px-6">
        <div className="overflow-hidden rounded-[24px] border border-ink-100 bg-white px-6 py-8 shadow-card sm:px-10 sm:py-10">
          <div className="grid items-center gap-8 md:grid-cols-2">
            <div>
              <h2 className="text-[clamp(1.4rem,2.5vw,1.8rem)] font-semibold tracking-[-0.01em] text-ink-900">
                {t("home.trust.title")}
              </h2>
              <p className="mt-2 text-[14.5px] text-ink-700">{t("home.trust.body")}</p>
              <p className="mt-3 inline-flex items-center gap-2 rounded-full bg-apricot-100 px-3 py-1.5 text-[12.5px] font-medium text-ink-800">
                <ClockIcon size={14} />
                {t("home.trust.area")}
              </p>
            </div>
            <div className="grid grid-cols-3 gap-3 text-center">
              {[
                { v: "16+", k: "Stations in pilot" },
                { v: "100%", k: "No login to search" },
                { v: "3", k: "Languages" },
              ].map((s) => (
                <div
                  key={s.k}
                  className="rounded-[16px] border border-ink-100 bg-apricot-50/60 p-4"
                >
                  <div className="text-[24px] font-semibold text-coral-700">{s.v}</div>
                  <div className="mt-1 text-[11.5px] text-ink-600">{s.k}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function HeroVisual() {
  return (
    <div className="relative mx-auto w-full max-w-md">
      <div className="absolute -left-6 -top-6 h-24 w-24 rounded-full bg-coral-200 blur-2xl opacity-60" aria-hidden />
      <div className="absolute -bottom-6 -right-6 h-28 w-28 rounded-full bg-apricot-200 blur-2xl opacity-70" aria-hidden />
      <div className="relative rounded-[24px] border border-ink-100 bg-white p-3 shadow-pop">
        <div className="relative h-[300px] overflow-hidden rounded-[18px] map-dot-bg">
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="xMidYMid slice"
            className="absolute inset-0 h-full w-full"
            aria-hidden
          >
            <path className="map-park" d="M0 65 Q15 55 30 60 T60 60 L60 100 L0 100 Z" />
            <path className="map-water" d="M70 70 Q85 65 100 75 L100 100 L60 100 Z" />
            <path className="map-road-major" d="M0 35 L100 50" />
            <path className="map-road-major" d="M50 0 L40 100" />
            <path className="map-road" d="M5 80 Q40 70 60 85 T100 75" />
            {/* markers */}
            {[
              { x: 35, y: 38, status: "available" },
              { x: 55, y: 30, status: "busy" },
              { x: 30, y: 60, status: "available" },
              { x: 60, y: 70, status: "broken" },
              { x: 78, y: 40, status: "available" },
              { x: 70, y: 55, status: "unknown" },
            ].map((m, i) => {
              const fill =
                m.status === "available"
                  ? "#2F9E6E"
                  : m.status === "busy"
                  ? "#D9822B"
                  : m.status === "broken"
                  ? "#C8443A"
                  : "#6B615E";
              return (
                <g key={i} transform={`translate(${m.x} ${m.y})`}>
                  <circle r={3.2} fill="#fff" />
                  <circle r={2.4} fill={fill} />
                  <circle r={1.1} fill="#fff" />
                </g>
              );
            })}
          </svg>
        </div>

        <div className="space-y-2 px-1 pb-1 pt-3">
          {[
            { name: "ChargePlus Hub — Andheri East", status: "available", price: "₹18/kWh" },
            { name: "Ather Grid — Powai", status: "available", price: "₹20/kWh" },
            { name: "Stilt Charge — Bandra West", status: "busy", price: "₹22/kWh" },
          ].map((s) => (
            <div
              key={s.name}
              className="flex items-center justify-between rounded-[12px] border border-ink-100 bg-white px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-[13.5px] font-medium text-ink-900">{s.name}</p>
                <p className="text-[11.5px] text-ink-600">{s.price}</p>
              </div>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                  s.status === "available"
                    ? "bg-status-available-bg text-[#1F6B4A]"
                    : "bg-status-busy-bg text-[#8A4E14]"
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    s.status === "available" ? "bg-status-available" : "bg-status-busy"
                  }`}
                />
                {s.status === "available" ? "Available" : "Busy"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
