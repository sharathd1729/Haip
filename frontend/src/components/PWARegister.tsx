"use client";

import { useEffect } from "react";

// Convert VAPID public key (base64url) to Uint8Array for pushManager.subscribe
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

async function subscribeToPush(reg: ServiceWorkerRegistration): Promise<void> {
  try {
    // Already subscribed?
    const existing = await reg.pushManager.getSubscription();
    if (existing) return;

    // Fetch VAPID public key — if server has none, push is disabled
    const res = await fetch("/api/v1/push/vapid-public-key");
    if (!res.ok) return;
    const { public_key } = await res.json();
    if (!public_key) return;

    const subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key) as unknown as ArrayBuffer,
    });

    const json = subscription.toJSON();
    const token = typeof window !== "undefined"
      ? document.cookie.match(/access_token=([^;]+)/)?.[1]
      : null;

    await fetch("/api/v1/push/subscribe", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        endpoint: json.endpoint,
        keys: { p256dh: json.keys?.p256dh ?? "", auth: json.keys?.auth ?? "" },
      }),
    });
  } catch (err) {
    if (process.env.NODE_ENV === "development") {
      console.warn("[HAIP Push] subscribe failed:", err);
    }
  }
}

export function PWARegister() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;

    // A new service worker calling skipWaiting()/clients.claim() (see
    // sw.js) fires this once it takes control -- reload so the page picks
    // up the new app shell instead of staying on stale in-memory JS.
    // Guarded so it only ever fires once per page load, not a reload loop.
    let reloadedForUpdate = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (reloadedForUpdate) return;
      reloadedForUpdate = true;
      window.location.reload();
    });

    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then(async (reg) => {
        if (process.env.NODE_ENV === "development") {
          console.log("[HAIP SW] registered, scope:", reg.scope);
        }

        // Browsers only check for a new sw.js occasionally on their own
        // (and can go a long time on mobile with backgrounded tabs) --
        // force a check now and whenever the tab becomes visible again,
        // so users don't get stuck on an old version for hours/days.
        reg.update();
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState === "visible") reg.update();
        });

        // Request notification permission and subscribe to push
        if ("Notification" in window && "PushManager" in window) {
          const permission = await Notification.requestPermission();
          if (permission === "granted") {
            await subscribeToPush(reg);
          }
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
