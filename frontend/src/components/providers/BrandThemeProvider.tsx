"use client";

/**
 * BrandThemeProvider
 *
 * Injects brand CSS variables into :root on first mount (client-side).
 * 1. Immediately applies the theme saved in localStorage (no flash).
 * 2. Then fetches the server-persisted theme from /api/v1/tenants/me/branding
 *    and re-applies if it differs.
 *
 * Exports a useBrandTheme() hook so any component can read / update the theme.
 */

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import {
  BrandTheme,
  DEFAULT_THEME,
  applyTheme,
  loadSavedTheme,
  saveThemeLocally,
  withCurrentDefaultLogo,
} from "@/lib/brandTheme";
import api from "@/lib/api";

interface BrandThemeContextValue {
  theme: BrandTheme;
  setTheme: (t: BrandTheme) => void;
  saveTheme: (t: BrandTheme) => Promise<void>;
  isSaving: boolean;
}

const BrandThemeContext = createContext<BrandThemeContextValue>({
  theme: DEFAULT_THEME,
  setTheme: () => {},
  saveTheme: async () => {},
  isSaving: false,
});

export function useBrandTheme() {
  return useContext(BrandThemeContext);
}

export function BrandThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<BrandTheme>(DEFAULT_THEME);
  const [isSaving, setIsSaving] = useState(false);

  // On mount: apply localStorage theme immediately, then sync from server
  useEffect(() => {
    const local = loadSavedTheme();
    setThemeState(local);
    applyTheme(local);

    // Try to fetch server-persisted branding
    api.get("/tenants/me/branding")
      .then(res => {
        // Strip null / undefined fields so they don't overwrite DEFAULT_THEME values
        // (backend returns nulls when the tenant hasn't saved branding yet)
        const raw = res.data ?? {};
        const clean = Object.fromEntries(
          Object.entries(raw).filter(([, v]) => v !== null && v !== undefined && v !== "")
        );
        const server: BrandTheme = withCurrentDefaultLogo({ ...DEFAULT_THEME, ...local, ...clean });
        setThemeState(server);
        applyTheme(server);
        saveThemeLocally(server);
      })
      .catch(() => {
        // No branding endpoint yet or not authenticated — keep local
      });
  }, []);

  const setTheme = useCallback((t: BrandTheme) => {
    setThemeState(t);
    applyTheme(t);           // instant preview
    saveThemeLocally(t);     // persist for next page load
  }, []);

  const saveTheme = useCallback(async (t: BrandTheme) => {
    setIsSaving(true);
    setTheme(t);
    try {
      await api.patch("/tenants/me/branding", t);
    } catch {
      // Graceful — theme is still applied locally even if backend is down
    } finally {
      setIsSaving(false);
    }
  }, [setTheme]);

  return (
    <BrandThemeContext.Provider value={{ theme, setTheme, saveTheme, isSaving }}>
      {children}
    </BrandThemeContext.Provider>
  );
}
