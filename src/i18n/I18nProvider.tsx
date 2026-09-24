"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { dictionaries, SUPPORTED_LANGUAGES } from "./dictionaries";
import type { Language, LanguageCode, TranslationKey, Translations } from "./types";

const STORAGE_KEY = "chargeplus:lang";

type Ctx = {
  lang: LanguageCode;
  setLang: (l: LanguageCode) => void;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
  languages: Language[];
};

const I18nContext = createContext<Ctx | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<LanguageCode>("en");

  // hydrate from storage
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "en" || stored === "hi" || stored === "mr") {
        queueMicrotask(() => {
          setLangState(stored);
        });
      }
    } catch {}
  }, []);

  const setLang = useCallback((l: LanguageCode) => {
    setLangState(l);
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {}
  }, []);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = lang;
    }
  }, [lang]);

  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => {
      const dict: Translations = dictionaries[lang] ?? dictionaries.en;
      const raw = dict[key] ?? dictionaries.en[key] ?? key;
      if (!vars) return raw;
      return raw.replace(/\{(\w+)\}/g, (_, name) =>
        vars[name] == null ? `{${name}}` : String(vars[name])
      );
    },
    [lang]
  );

  const value = useMemo<Ctx>(
    () => ({ lang, setLang, t, languages: SUPPORTED_LANGUAGES }),
    [lang, setLang, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
