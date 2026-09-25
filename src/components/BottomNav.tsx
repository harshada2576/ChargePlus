"use client";

import { useI18n } from "@/i18n/I18nProvider";
import { Link } from "@/i18n/Link";
import { usePathname } from "next/navigation";
import { cx } from "@/lib/util";
import {
  HomeIcon,
  ExploreIcon,
  SavedIcon,
  BellIcon,
  UserIcon,
} from "./Icon";
import type { ComponentType, SVGProps } from "react";

type NavItem = {
  key: "home" | "explore" | "saved" | "alerts" | "profile";
  href: string;
  Icon: ComponentType<SVGProps<SVGSVGElement> & { size?: number }>;
};

const items: NavItem[] = [
  { key: "home", href: "/", Icon: HomeIcon },
  { key: "explore", href: "/explore", Icon: ExploreIcon },
  { key: "saved", href: "/saved", Icon: SavedIcon },
  { key: "alerts", href: "/alerts", Icon: BellIcon },
  { key: "profile", href: "/profile", Icon: UserIcon },
];

export function BottomNav() {
  const { t } = useI18n();
  const pathname = usePathname() || "/";

  // Admin route uses its own dedicated layout per Spec §56
  if (pathname.startsWith("/admin")) return null;

  return (
    <nav
      aria-label="Primary mobile"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-ink-100 bg-white/95 shadow-[0_-8px_30px_rgba(31,27,26,0.06)] backdrop-blur md:hidden"
    >
      <ul className="grid grid-cols-5">
        {items.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname === item.href || pathname.startsWith(item.href + "/");
          const Icon = item.Icon;
          return (
            <li key={item.key}>
              <Link
                href={item.href}
                className={cx(
                  "flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors",
                  active ? "text-coral-700" : "text-ink-600"
                )}
                aria-current={active ? "page" : undefined}
              >
                <Icon size={22} />
                <span>{t(`nav.${item.key}`)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
