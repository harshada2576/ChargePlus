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
import { supabase } from "@/lib/supabase";
import { fetchProfile } from "@/lib/profiles";
import { addFavorite, listFavorites, removeFavorite } from "@/lib/favorites";

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

  savedIds: Set<string>;
  /** Server-persisted toggle. Unauthenticated callers get "login-required". */
  toggleSaved: (id: string) => Promise<"saved" | "removed" | "login-required" | "error">;
  isSaved: (id: string) => boolean;
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

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let active = true;

    async function reloadFavorites(userId: string | null) {
      if (!active || !userId) {
        if (active) setSavedIds(new Set());
        return;
      }
      try {
        const ids = await listFavorites(supabase, userId);
        if (active) setSavedIds(new Set(ids));
      } catch {
        if (active) setSavedIds(new Set());
      }
    }

    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (!active) return;
        const u = data.session?.user;
        setUser(u ? toAuthUser(u.id, u.email, u.phone) : null);
        setHydrated(true);
        if (u) {
          void applyCanonicalProfile(u.id);
          void reloadFavorites(u.id);
        } else {
          setSavedIds(new Set());
        }
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
        void reloadFavorites(u.id);
      } else {
        // Sign-out: drop favorites so the next device user never sees them.
        setUser(null);
        setSavedIds(new Set());
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

  const toggleSaved = useCallback(
    async (stationId: string): Promise<"saved" | "removed" | "login-required" | "error"> => {
      const {
        data: { user: authUser },
      } = await supabase.auth.getUser();
      if (!authUser) return "login-required";
      try {
        if (savedIds.has(stationId)) {
          await removeFavorite(supabase, authUser.id, stationId);
          setSavedIds((prev) => {
            const next = new Set(prev);
            next.delete(stationId);
            return next;
          });
          return "removed";
        }
        await addFavorite(supabase, authUser.id, stationId);
        setSavedIds((prev) => new Set(prev).add(stationId));
        return "saved";
      } catch {
        return "error";
      }
    },
    [savedIds]
  );

  const value = useMemo<Ctx>(
    () => ({
      isAuthed: !!user,
      isAdmin: user?.role === "admin",
      user,
      signOut,
      refreshProfile,
      savedIds: hydrated ? savedIds : new Set<string>(),
      toggleSaved,
      isSaved,
    }),
    [user, hydrated, savedIds, signOut, refreshProfile, toggleSaved, isSaved]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
