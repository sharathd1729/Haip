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
      applicationServerKey: urlBase64ToUint8Array(public_key),
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

    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then(async (reg) => {
        if (process.env.NODE_ENV === "development") {
          console.log("[HAIP SW] registered, scope:", reg.scope);
        }

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
