"use client";

import { cx } from "@/lib/util";
import { useI18n } from "@/i18n/I18nProvider";
import type { StationStatus } from "@/data/types";

const styles: Record<
  StationStatus,
  { dot: string; bg: string; text: string; ring: string }
> = {
  available: {
    dot: "bg-status-available",
    bg: "bg-status-available-bg",
    text: "text-[#1F6B4A]",
    ring: "ring-1 ring-inset ring-[#B7E0C7]",
  },
  busy: {
    dot: "bg-status-busy",
    bg: "bg-status-busy-bg",
    text: "text-[#8A4E14]",
    ring: "ring-1 ring-inset ring-[#F0D9A8]",
  },
  broken: {
    dot: "bg-status-broken",
    bg: "bg-status-broken-bg",
    text: "text-[#8A2A22]",
    ring: "ring-1 ring-inset ring-[#F0BAB4]",
  },
  unknown: {
    dot: "bg-status-unknown",
    bg: "bg-status-unknown-bg",
    text: "text-ink-700",
    ring: "ring-1 ring-inset ring-ink-200",
  },
};

export function StatusBadge({
  status,
  size = "md",
  className,
}: {
  status: StationStatus;
  size?: "sm" | "md";
  className?: string;
}) {
  const { t } = useI18n();
  const s = styles[status];
  const label =
    status === "available"
      ? t("station.status.available")
      : status === "busy"
      ? t("station.status.busy")
      : status === "broken"
      ? t("station.status.broken")
      : t("station.status.unknown");
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full font-medium",
        s.bg,
        s.text,
        s.ring,
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-[12px]",
        className
      )}
    >
      <span className={cx("inline-block h-1.5 w-1.5 rounded-full", s.dot)} aria-hidden />
      {label}
    </span>
  );
}
