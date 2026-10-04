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
import { supabase } from "@/lib/supabase";
import { fetchProfile } from "@/lib/profiles";

const SAVED_KEY = "chargeplus:saved";
const ALERTS_KEY = "chargeplus:alerts";
const REPORTS_KEY = "chargeplus:reports";

export type AuthUser = {
  /** Supabase Auth user id (auth.uid()). Never client-invented. */
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
  signOut: () => void;
  /** Re-read the canonical profile (e.g. after editing the display name). */
  refreshProfile: () => void;
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

function toAuthUser(id: string, email?: string | null, phone?: string | null): AuthUser | null {
  if (email) return { id, contact: email, kind: "email" };
  if (phone) return { id, contact: phone, kind: "phone" };
  return null;
}

/** Ensure the canonical profiles row exists for a freshly authenticated user. */
async function ensureProfileRow(userId: string): Promise<void> {
  try {
    const { data, error } = await supabase.from("profiles").select("id").eq("id", userId).maybeSingle();
    if (error || data) return;
    await supabase.from("profiles").insert({ id: userId });
  } catch {
    // Profile sync is best-effort here; server writes surface their own errors.
  }
}

function clearLocalPrototypeStores() {
  try {
    localStorage.removeItem(SAVED_KEY);
    localStorage.removeItem(ALERTS_KEY);
    localStorage.removeItem(REPORTS_KEY);
    localStorage.removeItem(`${REPORTS_KEY}:reviews`);
  } catch {}
}

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
    let active = true;
    // Prototype stores stay local until their steps; auth is real Supabase Auth.
    // Synchronous state seeding stays out of the effect body (lint + perf).
    queueMicrotask(() => {
      if (!active) return;
      setSavedIds(loadSet(SAVED_KEY));
      setAlerts(loadJSON<Alert[]>(ALERTS_KEY, []));
      setReports(loadJSON<UserReport[]>(REPORTS_KEY, []));
      setReviews(loadJSON<typeof reviews>(`${REPORTS_KEY}:reviews`, []));
    });

    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (!active) return;
        const u = data.session?.user;
        setUser(u ? toAuthUser(u.id, u.email, u.phone) : null);
        setHydrated(true);
        if (u) void applyCanonicalProfile(u.id);
      })
      .catch(() => {
        if (!active) return;
        setUser(null);
        setHydrated(true);
      });

    // Canonical profile (display name + server-truth role) overlays the session.
    async function applyCanonicalProfile(userId: string) {
      try {
        const profile = await fetchProfile(supabase, userId);
        if (!active || !profile) return;
        setUser((prev) =>
          prev && prev.id === userId
            ? { ...prev, name: profile.displayName ?? prev.name, role: profile.role }
            : prev
        );
      } catch {}
    }

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      const u = session?.user;
      if (u) {
        setUser(toAuthUser(u.id, u.email, u.phone));
        void ensureProfileRow(u.id);
        void applyCanonicalProfile(u.id);
      } else {
        // Sign-out: drop in-memory prototype state so the next device user
        // never sees the previous user's saves, alerts, reports, or reviews.
        setUser(null);
        setSavedIds(new Set());
        setAlerts([]);
        setReports([]);
        setReviews([]);
        clearLocalPrototypeStores();
      }
    });
    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  const signOut = useCallback(() => {
    // Server session ends here; local cleanup follows via onAuthStateChange.
    void supabase.auth.signOut().catch(() => {});
  }, []);

  const refreshProfile = useCallback(() => {
    void supabase.auth.getUser().then(async ({ data }) => {
      const u = data.user;
      if (!u) return;
      try {
        const profile = await fetchProfile(supabase, u.id);
        if (!profile) return;
        setUser((prev) =>
          prev && prev.id === u.id
            ? { ...prev, name: profile.displayName ?? prev.name, role: profile.role }
            : prev
        );
      } catch {}
    });
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

  // Prototype-only admin impersonation for the locked Admin console UI.
  // Removed in Step 3.12 (real role comes from public.profiles via RLS).
  // In-memory only: never persisted, never trusted for authorization.
  const setMockRole = useCallback((role: "user" | "admin") => {
    setUser((prev) => {
      const updated: AuthUser = prev
        ? { ...prev, role }
        : { id: "u-mock-admin", contact: "admin@chargeplus.in", kind: "email", name: "Admin Operator", role };
      return updated;
    });
  }, []);

  const value = useMemo<Ctx>(
    () => ({
      isAuthed: !!user,
      isAdmin: user?.role === "admin",
      user,
      signOut,
      refreshProfile,
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
    [user, hydrated, savedIds, alerts, reports, reviews, signOut, refreshProfile, setMockRole, toggleSaved, isSaved, setAlertEnabled, addReport, addReview]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
