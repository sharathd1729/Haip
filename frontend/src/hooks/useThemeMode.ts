"use client";
import { useState, useEffect, useCallback } from "react";

export type ColorScheme = "light" | "dark";

const LS_KEY = "haip_color_scheme";

function getSystemScheme(): ColorScheme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useThemeMode() {
  const [mode, setMode] = useState<ColorScheme>("dark");

  useEffect(() => {
    const saved = localStorage.getItem(LS_KEY) as ColorScheme | null;
    const resolved: ColorScheme = saved ?? getSystemScheme();
    setMode(resolved);
    applyClass(resolved);

    // Track system changes when no explicit preference is saved
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => {
      if (!localStorage.getItem(LS_KEY)) {
        const next: ColorScheme = e.matches ? "dark" : "light";
        setMode(next);
        applyClass(next);
      }
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
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
