"use client";

import { useI18n } from "@/i18n/I18nProvider";
import { BrandMark } from "./BrandMark";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { Link } from "@/i18n/Link";
import { cx } from "@/lib/util";
import { usePathname } from "next/navigation";

import { HEADER_NAV_ITEMS } from "@/data/navigation";

const navItems = HEADER_NAV_ITEMS;

export function SiteHeader() {
  const { t } = useI18n();
  const pathname = usePathname() || "/";

  // Admin route uses its own dedicated layout per Spec §56
  if (pathname.startsWith("/admin")) return null;

  return (
    <header className="sticky top-0 z-40 border-b border-ink-100 bg-white/85 backdrop-blur supports-[backdrop-filter]:bg-white/70">
      <div className="mx-auto flex h-14 max-w-screen-xl items-center justify-between gap-3 px-4 sm:h-16 sm:px-6">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-full focus:bg-white focus:px-4 focus:py-2 focus:text-[13px] focus:font-medium focus:text-ink-900 focus:shadow-card"
        >
          {t("common.skipToContent")}
        </a>
        <div className="flex items-center gap-2.5">
          <Link href="/" className="shrink-0" aria-label={t("brand.name")}>
            <BrandMark size="md" />
          </Link>
          {process.env.NEXT_PUBLIC_DEMO_MODE === "true" && (
            <span
              title="Running in Offline Demo Mode with synthetic seed data"
              className="inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-[11px] font-semibold text-amber-900 shadow-xs"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
              DEMO MODE
            </span>
          )}
        </div>

        {/* Desktop nav */}
        <nav aria-label="Primary" className="hidden flex-1 items-center justify-center md:flex">
          <ul className="flex items-center gap-1">
            {navItems.map((item) => {
              const active = pathname === item.href || pathname.startsWith(item.href + "/");
              return (
                <li key={item.key}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cx(
                      "inline-flex h-9 items-center rounded-full px-3.5 text-[13.5px] font-medium transition-colors",
                      active
                        ? "bg-coral-50 text-coral-700"
                        : "text-ink-700 hover:bg-ink-100 hover:text-ink-900"
                    )}
                  >
                    {t(`nav.${item.key}` as "nav.explore")}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="flex items-center gap-2">
          <LanguageSwitcher compact />
        </div>
      </div>
    </header>
  );
}
