"use client";
import { useState, useEffect, useCallback } from "react";

export type ColorScheme = "light" | "dark";

const LS_KEY = "haip_color_scheme";

export function useThemeMode() {
  const [mode, setMode] = useState<ColorScheme>("light");

  // On mount, read saved preference
  useEffect(() => {
    const saved = (localStorage.getItem(LS_KEY) as ColorScheme) ?? "light";
    setMode(saved);
    applyClass(saved);
  }, []);

  const toggle = useCallback(() => {
    setMode(prev => {
      const next: ColorScheme = prev === "light" ? "dark" : "light";
      localStorage.setItem(LS_KEY, next);
      applyClass(next);
      return next;
    });
  }, []);

  return { mode, toggle, isDark: mode === "dark" };
}

function applyClass(scheme: ColorScheme) {
  if (scheme === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}
