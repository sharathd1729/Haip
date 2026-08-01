"use client";

import { useEffect } from "react";
import { setWaitingWorker, useAppUpdateStore } from "@/store/appUpdate";

// C2: how often to re-check for an update while the tab is open and idle.
// Browsers already do their own occasional SW byte-diff check, but that can
// go a long time on a backgrounded mobile tab -- this plus the
// visibilitychange check are the belt-and-suspenders paths.
const VERSION_POLL_INTERVAL_MS = 15 * 60 * 1000;

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

    const { setUpdateAvailable } = useAppUpdateStore.getState();

    // Once the user clicks "Update now" (or, on the fallback path, once a
    // build-id.json mismatch triggers a plain reload directly) this fires
    // as the new worker actually takes over -- reload so the page picks up
    // the new app shell instead of staying on stale in-memory JS. Guarded
    // so it only ever fires once per page load, not a reload loop.
    let reloadedForUpdate = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (reloadedForUpdate) return;
      reloadedForUpdate = true;
      window.location.reload();
    });

    // C2: a worker sitting in "installed" while something is already
    // controlling this page is a genuine update (as opposed to this being
    // the very first SW install for a brand-new visitor, where there's
    // nothing to update away from and no banner should show).
    function trackForUpdate(worker: ServiceWorker | null) {
      if (!worker) return;
      worker.addEventListener("statechange", () => {
        if (worker.state === "installed" && navigator.serviceWorker.controller) {
          setWaitingWorker(worker);
          setUpdateAvailable(true);
        }
      });
    }

    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then(async (reg) => {
        if (process.env.NODE_ENV === "development") {
          console.log("[HAIP SW] registered, scope:", reg.scope);
        }

        // A worker may already be sitting in "waiting" if it finished
        // installing while this tab was backgrounded/inactive.
        if (reg.waiting && navigator.serviceWorker.controller) {
          setWaitingWorker(reg.waiting);
          setUpdateAvailable(true);
        }
        reg.addEventListener("updatefound", () => trackForUpdate(reg.installing));

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

    // C2 (defense in depth): poll build-id.json directly, for deploys the
    // SW's own updatefound path might miss (e.g. SW registration disabled
    // by browser settings/extensions). Baseline is whatever version this
    // page load itself was served with; a poll that returns something
    // different means a newer deploy exists.
    let baselineVersion: string | null = null;
    async function pollVersion() {
      try {
        const res = await fetch("/build-id.json", { cache: "no-store" });
        if (!res.ok) return;
        const { version } = await res.json();
        if (baselineVersion === null) {
          baselineVersion = version;
          return;
        }
        if (version !== baselineVersion) {
          // No SW "waiting" worker exists for this path -- applyUpdate()
          // falls back to a plain reload when setWaitingWorker was never
          // called for this update.
          setUpdateAvailable(true);
        }
      } catch {
        // Offline or endpoint unreachable -- not worth surfacing, the SW
        // updatefound path is the primary detection mechanism anyway.
      }
    }
    pollVersion();
    const versionInterval = setInterval(pollVersion, VERSION_POLL_INTERVAL_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") pollVersion();
    });

    return () => clearInterval(versionInterval);
  }, []);

  return null;
}
