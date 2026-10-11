"use client";

import { useEffect } from "react";
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

  const widthClass =
    size === "sm" ? "max-w-sm" : size === "lg" ? "max-w-lg" : "max-w-md";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="absolute inset-0 cursor-default bg-ink-900/40 backdrop-blur-[2px] animate-fade-in"
        tabIndex={-1}
      />
      <div
        className={cx(
          "relative z-10 w-full overflow-hidden rounded-[22px] bg-white shadow-pop animate-pop-in",
          widthClass
        )}
      >
        {title && (
          <div className="flex items-center justify-between gap-3 border-b border-ink-100 px-5 py-4">
            <h2 className="text-[16px] font-semibold text-ink-900">{title}</h2>
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
