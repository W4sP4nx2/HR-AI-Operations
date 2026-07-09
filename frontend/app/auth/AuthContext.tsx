"use client";

/**
 * Auth context: holds the current user and exposes login/register/logout.
 *
 * On mount it (1) captures a `?token=` param from the Google OAuth redirect,
 * (2) restores any stored token, and (3) resolves the current user via
 * `/auth/me`. When the backend runs in advisory mode (no AUTH_ENFORCE), `/auth/me`
 * returns the anonymous viewer, so the app stays fully usable without logging in.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, tokenStore, type AuthUser, type Role } from "../../lib/api";

interface AuthState {
  user: AuthUser | null;
  loading: boolean;
  isAuthed: boolean; // a real (non-anonymous) account
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name?: string) => Promise<void>;
  switchRole: (role: Role) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    // 1) Capture token from the Google redirect (?token=...) and clean the URL.
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const t = params.get("token");
      if (t) {
        tokenStore.set(t);
        params.delete("token");
        const clean = window.location.pathname + (params.toString() ? `?${params}` : "");
        window.history.replaceState({}, "", clean);
      }
    }
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      const session = await api.login(email, password);
      tokenStore.set(session.token);
      setUser(session.user);
    },
    []
  );

  const register = useCallback(
    async (email: string, password: string, name = "") => {
      const session = await api.register(email, password, name);
      tokenStore.set(session.token);
      setUser(session.user);
    },
    []
  );

  const switchRole = useCallback(async (role: Role) => {
    const session = await api.switchPersona(role);
    tokenStore.set(session.token);
    setUser(session.user);
  }, []);

  const logout = useCallback(() => {
    tokenStore.clear();
    refresh();
  }, [refresh]);

  const isAuthed = !!user && user.id !== "anon";

  return (
    <AuthCtx.Provider value={{ user, loading, isAuthed, login, register, switchRole, logout, refresh }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
