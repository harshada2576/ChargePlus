"use client";

import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { CloseIcon } from "./Icon";
import { cx } from "@/lib/util";

type Props = {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  size?: "sm" | "md" | "lg";
};

export function Modal({ open, onClose, title, children, size = "md" }: Props) {
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
    requestAnimationFrame(() => {
      const first = ref.current?.querySelector<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      (first ?? ref.current)?.focus();
    });
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

  const widthClass =
    size === "sm" ? "max-w-sm" : size === "lg" ? "max-w-lg" : "max-w-md";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? titleId : undefined}
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="absolute inset-0 cursor-default bg-ink-900/40 backdrop-blur-[2px] animate-fade-in"
        tabIndex={-1}
      />
      <div
        ref={ref}
        tabIndex={-1}
        className={cx(
          "relative z-10 w-full overflow-hidden rounded-[22px] bg-white shadow-pop animate-pop-in",
          widthClass
        )}
      >
        {title && (
          <div className="flex items-center justify-between gap-3 border-b border-ink-100 px-5 py-4">
            <h2 id={titleId} className="text-[16px] font-semibold text-ink-900">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="inline-flex h-9 w-9 items-center justify-center rounded-full text-ink-700 hover:bg-ink-100"
            >
              <CloseIcon size={18} />
            </button>
          </div>
        )}
        <div className="max-h-[80vh] overflow-y-auto p-5 thin-scroll">{children}</div>
      </div>
    </div>
  );
}

export function ModalShell({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cx("space-y-4", className)}>{children}</div>;
}
