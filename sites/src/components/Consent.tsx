"use client";
// DPDP cookie banner + Meta Pixel + GA4 + Google Ads tag (website phases 2 + growth #5). Shown only when the site has a
// pixel, GA4 or Google Ads id. NOTHING loads until the visitor taps "Accept"; "Only necessary" keeps the site cookie-less
// (the page-view beacon never sets a cookie). The choice stays in this browser (localStorage) and can be changed from the
// "Cookie choices" link in the corner. After consent, window.haipTrack fires Lead / InitiateCheckout / Purchase with the
// server's event id (site-blocks track()). Google Consent Mode v2 (basic mode; advanced mode is an owner/counsel
// decision): defaults denied before any Google tag, updated on the banner's choice. Google Ads click ids from the URL
// are kept only after Accept; a WhatsApp button tap then adds a code to its Ref (site-blocks/consent.ts, tested).
import { useEffect, useState } from "react";
import { applyChoice, captureClick, CHOICE_KEY, consentDefaults, type Gads, loadTags, onWaTap, type TagWindow } from "@/site-blocks/consent";

function read(): string | null {
  try { return window.localStorage.getItem(CHOICE_KEY); } catch { return null; }
}
function write(v: string) {
  try { window.localStorage.setItem(CHOICE_KEY, v); } catch { /* private mode: ask again next time */ }
}

function onTap(e: MouseEvent) {
  const a = (e.target as Element | null)?.closest?.("a[data-wa-ref]") as HTMLAnchorElement | null;
  const out = a ? onWaTap(a) : null;   // rewrites the link before the browser follows it
  if (!out) return;
  const body = JSON.stringify(out);
  if (!navigator.sendBeacon?.("/_haip/api/wa-click", new Blob([body], { type: "application/json" }))) {
    fetch("/_haip/api/wa-click", { method: "POST", headers: { "content-type": "application/json" }, body, keepalive: true }).catch(() => {});
  }
}

export function Consent({ pixel, ga4, gads }: { pixel?: string; ga4?: string; gads?: Gads }) {
  const [ask, setAsk] = useState(false);
  const on = Boolean(pixel || ga4 || gads);
  useEffect(() => {
    if (!on) return;
    const w = window as TagWindow;
    if (ga4 || gads) consentDefaults(w);   // denied, before any Google tag; loads nothing
    if (gads) captureClick(w, window.location.search);   // in memory; kept only after Accept
    const v = read();
    if (v === "all") loadTags(w, pixel, ga4, gads);
    else if (v === "necessary") applyChoice(w, "necessary", pixel, ga4, gads);
    else setAsk(true);
    if (!gads) return;
    document.addEventListener("click", onTap, true);
    return () => document.removeEventListener("click", onTap, true);
  }, [on, pixel, ga4, gads]);
  if (!on) return null;
  const choose = (v: "all" | "necessary") => {
    write(v);
    setAsk(false);
    if (applyChoice(window as TagWindow, v, pixel, ga4, gads)) window.location.reload();   // switching off: drop loaded tags
  };
  if (!ask) return <button type="button" className="hc-link" onClick={() => setAsk(true)}>Cookie choices</button>;
  return (
    <div className="hc-banner" role="dialog" aria-live="polite" aria-label="Cookie choices">
      <p>We use cookies from Meta and Google to see which ads and posts bring guests to us. They load only if you say yes.
        Booking and enquiries work either way.</p>
      <div className="hc-actions">
        <button type="button" className="hc-btn hc-btn--ghost" onClick={() => choose("necessary")}>Only necessary</button>
        <button type="button" className="hc-btn" onClick={() => choose("all")}>Accept</button>
      </div>
    </div>
  );
}
