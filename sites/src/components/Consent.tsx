"use client";
// DPDP cookie banner + Meta Pixel + GA4 (website phase 2). Shown only when the site has a pixel or GA4 id. NOTHING loads
// until the visitor taps "Accept"; "Only necessary" keeps the site cookie-less (the page-view beacon never sets a cookie).
// The choice stays in this browser (localStorage) and can be changed from the "Cookie choices" link in the corner.
// After consent, window.haipTrack fires Lead / InitiateCheckout / Purchase with the server's event id (site-blocks track()).
import { useEffect, useState } from "react";

const KEY = "haip_cookie_choice";
type W = Window & { fbq?: (...a: unknown[]) => void; _fbq?: unknown; dataLayer?: unknown[]; gtag?: (...a: unknown[]) => void;
  haipTrack?: (name: string, id: string, data?: { value?: number; currency?: string }) => void };

function read(): string | null {
  try { return window.localStorage.getItem(KEY); } catch { return null; }
}
function write(v: string) {
  try { window.localStorage.setItem(KEY, v); } catch { /* private mode: ask again next time */ }
}

function addScript(src: string) {
  const s = document.createElement("script");
  s.async = true;
  s.src = src;
  document.head.appendChild(s);
}

const GA4_EVENTS: Record<string, string> = { Lead: "generate_lead", InitiateCheckout: "begin_checkout", Purchase: "purchase" };

function load(pixel?: string, ga4?: string) {
  const w = window as W;
  if (pixel && !w.fbq) {
    // Meta's standard stub: calls queue until fbevents.js loads and sets callMethod.
    type Fbq = ((...a: unknown[]) => void) & { callMethod?: (...a: unknown[]) => void; queue: unknown[][]; push?: unknown;
      loaded?: boolean; version?: string };
    const fbq = function (this: unknown, ...a: unknown[]) {
      if (fbq.callMethod) fbq.callMethod.apply(fbq, a); else fbq.queue.push(a);
    } as Fbq;
    Object.assign(fbq, { queue: [], push: fbq, loaded: true, version: "2.0" });
    w.fbq = w._fbq = fbq;
    addScript("https://connect.facebook.net/en_US/fbevents.js");
    w.fbq("init", pixel);
    w.fbq("track", "PageView");
  }
  if (ga4 && !w.gtag) {
    w.dataLayer = w.dataLayer || [];
    w.gtag = function gtag() { (w.dataLayer as unknown[]).push(arguments); };   // gtag.js reads the arguments object
    w.gtag("js", new Date());
    w.gtag("config", ga4, { anonymize_ip: true });
    addScript(`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(ga4)}`);
  }
  w.haipTrack = (name, id, data) => {
    if (w.fbq && pixel) w.fbq("track", name, data || {}, { eventID: id });
    if (w.gtag && ga4) w.gtag("event", GA4_EVENTS[name] || name, { ...(data || {}), transaction_id: name === "Purchase" ? id : undefined });
  };
}

export function Consent({ pixel, ga4 }: { pixel?: string; ga4?: string }) {
  const [ask, setAsk] = useState(false);
  useEffect(() => {
    if (!pixel && !ga4) return;
    const v = read();
    if (v === "all") load(pixel, ga4);
    else if (v !== "necessary") setAsk(true);
  }, [pixel, ga4]);
  if (!pixel && !ga4) return null;
  const choose = (v: "all" | "necessary") => {
    write(v);
    setAsk(false);
    if (v === "all") load(pixel, ga4);
    else if ((window as W).fbq || (window as W).gtag) window.location.reload();   // switching off: drop loaded tags
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
