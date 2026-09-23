"use client";

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { cx } from "@/lib/util";

type Props = {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  /** "bottom" for typical sheets, "center" for modal-style on desktop */
  placement?: "bottom" | "center";
  /** Snap points (fraction of viewport height). First one is initial. */
  snapPoints?: number[];
  /** Show the drag handle (only for bottom placement) */
  showHandle?: boolean;
  className?: string;
};

export function BottomSheet({
  open,
  onClose,
  title,
  children,
  placement = "bottom",
  showHandle = true,
  className,
}: Props) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? "bottom-sheet-title" : undefined}
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="absolute inset-0 cursor-default bg-ink-900/30 backdrop-blur-[2px] animate-fade-in"
        tabIndex={-1}
      />
      <div
        ref={ref}
        className={cx(
          "relative z-10 w-full bg-white shadow-sheet",
          placement === "bottom"
            ? "max-h-[92vh] rounded-t-[22px] animate-sheet-up sm:max-w-md sm:rounded-[22px] sm:mb-6"
            : "max-h-[90vh] max-w-md rounded-[22px] mx-4 animate-pop-in",
          className
        )}
      >
        {placement === "bottom" && showHandle && (
          <div className="flex justify-center pt-2.5 pb-1 sm:hidden" aria-hidden>
            <span className="h-1.5 w-10 rounded-full bg-ink-200" />
          </div>
        )}
        {title && (
          <div className="flex items-center justify-between gap-3 px-5 pt-3 pb-2 sm:pt-4">
            <h2 id="bottom-sheet-title" className="text-[16px] font-semibold text-ink-900">
              {title}
            </h2>
          </div>
        )}
        <div className="overflow-y-auto px-5 pb-6 pt-1 thin-scroll">{children}</div>
      </div>
    </div>
  );
}
