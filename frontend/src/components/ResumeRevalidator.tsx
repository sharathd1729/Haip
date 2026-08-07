"use client";

import { useEffect } from "react";
import { getSession } from "next-auth/react";
import { queryClient } from "@/lib/queryClient";

// PWA-blank-data-fix plan, Fix 3: queryClient.ts deliberately sets
// refetchOnWindowFocus/refetchOnReconnect to false (stops a refetch flood on
// plain tab-switch), and the only visibilitychange listener anywhere in the
// frontend was PWARegister's, scoped to service-worker update checks, not
// data. So resuming a backgrounded/killed-and-restored PWA never proactively
// checked anything -- it just sat on whatever was last in memory (or
// nothing, on a cold remount), waiting for a request to eventually fail
// before showing anything was wrong. This is the "make it smooth" half of
// that plan: on resume, always re-check the session first (forces the
// server jwt callback to run/refresh), and if it's fine, quietly refetch
// whatever's on screen -- current data is never cleared first, it just
// updates in place once the response lands.
//
// `pageshow` catches bfcache restores that visibilitychange can miss on
// some mobile browsers; `visibilitychange` catches the more common
// background/foreground cycle. Both can fire for the same resume, hence the
// debounce.
const MIN_RUN_INTERVAL_MS = 5_000;

export function ResumeRevalidator() {
  useEffect(() => {
    if (typeof window === "undefined") return;

    let lastRun = 0;

    async function onResume() {
      // Only meaningful once inside the app -- skip marketing/login/etc.
      if (!window.location.pathname.startsWith("/dashboard")) return;

      const now = Date.now();
      if (now - lastRun < MIN_RUN_INTERVAL_MS) return;
      lastRun = now;

      const session = await getSession();
      const sessionError = (session as { error?: string } | null)?.error;
      if (sessionError) {
        console.warn("[auth] resume revalidation: session.error =", sessionError, "-- redirecting to /login");
        window.location.href = "/login";
        return;
      }

      console.info("[auth] resume revalidation: session ok, invalidating queries");
      queryClient.invalidateQueries();
    }

    function onVisibilityChange() {
      if (document.visibilityState === "visible") onResume();
    }

    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("pageshow", onResume);

    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("pageshow", onResume);
    };
  }, []);

  return null;
}
