/**
 * Canonical in-app navigation destinations (single source of truth).
 * Components attach icons/labels; tests verify every href resolves to a route.
 * Station detail links are built with stationDetailHref, not stored here.
 */
export const BOTTOM_NAV_ITEMS = [
  { key: "home", href: "/" },
  { key: "explore", href: "/explore" },
  { key: "saved", href: "/saved" },
  { key: "alerts", href: "/alerts" },
  { key: "profile", href: "/profile" },
] as const;

export const HEADER_NAV_ITEMS = [
  { key: "explore", href: "/explore" },
  { key: "saved", href: "/saved" },
  { key: "alerts", href: "/alerts" },
] as const;
