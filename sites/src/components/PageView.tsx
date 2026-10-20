"use client";
// One beacon per page view: path and where the visitor came from (utm_source or the referring site). No cookies.
import { useEffect } from "react";

export function PageView({ path }: { path: string }) {
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    let source = q.get("utm_source") || "";
    if (!source && document.referrer) {
      try { const h = new URL(document.referrer).hostname; if (h !== window.location.hostname) source = h.replace(/^www\./, ""); } catch { /* ignore */ }
    }
    const body = JSON.stringify({ path, source: source || "direct" });
    if (navigator.sendBeacon) navigator.sendBeacon("/_haip/api/views", new Blob([body], { type: "application/json" }));
    else fetch("/_haip/api/views", { method: "POST", headers: { "content-type": "application/json" }, body, keepalive: true }).catch(() => {});
  }, [path]);
  return null;
}
