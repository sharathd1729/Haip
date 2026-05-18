"use client";

import { useEffect } from "react";

export function PWARegister() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;

    // Register immediately — the sw.js is at public root
    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then((reg) => {
        if (process.env.NODE_ENV === "development") {
          console.log("[HAIP SW] registered, scope:", reg.scope);
        }
      })
      .catch((err) => {
        if (process.env.NODE_ENV === "development") {
          console.warn("[HAIP SW] registration failed:", err);
        }
      });
  }, []);

  return null;
}
