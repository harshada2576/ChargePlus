"use client";

import { useEffect, useId, useRef } from "react";
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
  ariaLabel?: string;
};

export function BottomSheet({
  open,
  onClose,
  title,
  children,
  placement = "bottom",
  showHandle = true,
  className,
  ariaLabel,
}: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  // Kept in a ref so an inline onClose closure cannot re-arm the focus effect
  // on every parent render (that would yank focus back to the first control).
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const focusable = () =>
      ref.current?.querySelector<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
    requestAnimationFrame(() => (focusable() ?? ref.current)?.focus());
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCloseRef.current();
      if (e.key !== "Tab" || !ref.current) return;
      const items = Array.from(
        ref.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      );
      if (items.length === 0) {
        e.preventDefault();
        ref.current.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      previousFocus?.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? titleId : undefined}
      aria-label={!title ? ariaLabel : undefined}
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
        tabIndex={-1}
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
            <h2 id={titleId} className="text-[16px] font-semibold text-ink-900">
              {title}
            </h2>
          </div>
        )}
        <div className="overflow-y-auto px-5 pb-6 pt-1 thin-scroll">{children}</div>
      </div>
    </div>
  );
}
