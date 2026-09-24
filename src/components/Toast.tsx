"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

type Toast = { id: number; message: string };

const ToastCtx = createContext<{
  toasts: Toast[];
  show: (msg: string) => void;
} | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const show = useCallback((message: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 2400);
  }, []);

  const value = useMemo(() => ({ toasts, show }), [toasts, show]);

  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-atomic
        className="pointer-events-none fixed inset-x-0 bottom-24 z-[60] flex flex-col items-center gap-2 sm:bottom-8"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto animate-pop-in rounded-full bg-ink-900 px-4 py-2 text-[13px] font-medium text-white shadow-pop"
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
