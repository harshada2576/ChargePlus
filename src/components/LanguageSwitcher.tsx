"use client";

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import { SUPPORTED_LANGUAGES } from "@/i18n/dictionaries";
import type { LanguageCode } from "@/i18n/types";
import { ChevronDownIcon, GlobeIcon } from "@/components/Icon";
import { cx } from "@/lib/util";

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { lang, setLang } = useI18n();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const current = SUPPORTED_LANGUAGES.find((l) => l.code === lang)!;

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Language"
        className={cx(
          "inline-flex items-center gap-1.5 rounded-full border border-ink-200 bg-white px-3 text-[13px] font-medium text-ink-800 transition-colors hover:bg-ink-50",
          compact ? "h-9" : "h-10"
        )}
      >
        {!compact && <GlobeIcon size={16} aria-hidden />}
        <span>{current.nativeLabel}</span>
        <ChevronDownIcon size={14} aria-hidden />
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label="Language"
          className="absolute right-0 z-50 mt-2 w-40 overflow-hidden rounded-[14px] border border-ink-100 bg-white shadow-pop animate-pop-in"
        >
          {SUPPORTED_LANGUAGES.map((l) => (
            <li key={l.code}>
              <button
                role="option"
                aria-selected={lang === l.code}
                onClick={() => {
                  setLang(l.code as LanguageCode);
                  setOpen(false);
                }}
                className={cx(
                  "flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left text-[13.5px] hover:bg-ink-50",
                  lang === l.code && "bg-apricot-50 text-coral-700"
                )}
              >
                <span>{l.nativeLabel}</span>
                {lang === l.code && (
                  <span className="h-1.5 w-1.5 rounded-full bg-coral-600" aria-hidden />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
