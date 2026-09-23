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
import type { Alert, UserReport } from "@/data/types";

const SAVED_KEY = "chargeplus:saved";
const ALERTS_KEY = "chargeplus:alerts";
const REPORTS_KEY = "chargeplus:reports";
const AUTH_KEY = "chargeplus:auth";

export type AuthUser = {
  id: string;
  contact: string;
  kind: "phone" | "email";
  name?: string;
  role?: "user" | "admin";
};

type Ctx = {
  isAuthed: boolean;
  isAdmin: boolean;
  user: AuthUser | null;
  signIn: (contact: string, kind: "phone" | "email", name?: string) => void;
  signOut: () => void;
  setMockRole: (role: "user" | "admin") => void;

  savedIds: Set<string>;
  toggleSaved: (id: string) => void;
  isSaved: (id: string) => boolean;

  alerts: Alert[];
  setAlertEnabled: (id: string, type: Alert["type"], enabled: boolean) => void;

  reports: UserReport[];
  addReport: (r: Omit<UserReport, "id" | "submittedAt">) => void;

  reviews: { id: string; stationId: string; rating: number; comment: string; createdAt?: string }[];
  addReview: (r: { stationId: string; rating: number; comment: string }) => void;
};

const SessionContext = createContext<Ctx | null>(null);

function loadSet(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as string[];
    return new Set(arr);
  } catch {
    return new Set();
  }
}

function loadJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function saveJSON(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {}
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [reports, setReports] = useState<UserReport[]>([]);
  const [reviews, setReviews] = useState<{ id: string; stationId: string; rating: number; comment: string }[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    queueMicrotask(() => {
      setUser(loadJSON<AuthUser | null>(AUTH_KEY, null));
      setSavedIds(loadSet(SAVED_KEY));
      setAlerts(loadJSON<Alert[]>(ALERTS_KEY, []));
      setReports(loadJSON<UserReport[]>(REPORTS_KEY, []));
      setReviews(loadJSON<typeof reviews>(`${REPORTS_KEY}:reviews`, []));
      setHydrated(true);
    });
  }, []);

  const signIn = useCallback((contact: string, kind: "phone" | "email", name?: string) => {
    const u: AuthUser = { id: `u-${Date.now()}`, contact, kind, name };
    setUser(u);
    saveJSON(AUTH_KEY, u);
  }, []);

  const signOut = useCallback(() => {
    setUser(null);
    try { localStorage.removeItem(AUTH_KEY); } catch {}
  }, []);

  const isSaved = useCallback((id: string) => savedIds.has(id), [savedIds]);

  const toggleSaved = useCallback((id: string) => {
    setSavedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      saveJSON(SAVED_KEY, [...next]);
      return next;
    });
  }, []);

  const setAlertEnabled = useCallback(
    (stationId: string, type: Alert["type"], enabled: boolean) => {
      setAlerts((prev) => {
        const id = `${stationId}:${type}`;
        const idx = prev.findIndex((a) => a.id === id);
        let next: Alert[];
        if (idx >= 0) {
          next = prev.slice();
          next[idx] = { ...next[idx], enabled };
        } else {
          next = [...prev, { id, stationId, type, enabled }];
        }
        saveJSON(ALERTS_KEY, next);
        return next;
      });
    },
    []
  );

  const addReport = useCallback((r: Omit<UserReport, "id" | "submittedAt">) => {
    setReports((prev) => {
      const next: UserReport[] = [
        ...prev,
        { ...r, id: `r-${Date.now()}`, submittedAt: new Date() },
      ];
      saveJSON(REPORTS_KEY, next);
      return next;
    });
  }, []);

  const addReview = useCallback((r: { stationId: string; rating: number; comment: string }) => {
    setReviews((prev) => {
      const next = [
        ...prev,
        { id: `rv-${Date.now()}`, ...r, createdAt: new Date().toISOString() },
      ];
      saveJSON(`${REPORTS_KEY}:reviews`, next);
      return next;
    });
  }, []);

  const setMockRole = useCallback((role: "user" | "admin") => {
    setUser((prev) => {
      const updated: AuthUser = prev
        ? { ...prev, role }
        : { id: "u-mock-admin", contact: "admin@chargeplus.in", kind: "email", name: "Admin Operator", role };
      saveJSON(AUTH_KEY, updated);
      return updated;
    });
  }, []);

  const value = useMemo<Ctx>(
    () => ({
      isAuthed: !!user,
      isAdmin: user?.role === "admin",
      user,
      signIn,
      signOut,
      setMockRole,
      savedIds: hydrated ? savedIds : new Set<string>(),
      toggleSaved,
      isSaved,
      alerts: hydrated ? alerts : [],
      setAlertEnabled,
      reports: hydrated ? reports : [],
      addReport,
      reviews: hydrated ? reviews : [],
      addReview,
    }),
    [user, hydrated, savedIds, alerts, reports, reviews, signIn, signOut, setMockRole, toggleSaved, isSaved, setAlertEnabled, addReport, addReview]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
