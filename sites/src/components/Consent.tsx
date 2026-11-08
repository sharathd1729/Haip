"use client";
// DPDP cookie banner + Meta Pixel + GA4 (website phase 2). Shown only when the site has a pixel or GA4 id. NOTHING loads
// until the visitor taps "Accept"; "Only necessary" keeps the site cookie-less (the page-view beacon never sets a cookie).
// The choice stays in this browser (localStorage) and can be changed from the "Cookie choices" link in the corner.
// After consent, window.haipTrack fires Lead / InitiateCheckout / Purchase with the server's event id (site-blocks track()).
// Google Consent Mode v2 (basic mode; advanced mode is an owner/counsel decision): defaults denied before any Google
// tag, updated on the banner's choice. The tag logic is site-blocks/consent.ts (tested in the frontend).
import { useEffect, useState } from "react";
import { applyChoice, CHOICE_KEY, consentDefaults, loadTags, type TagWindow } from "@/site-blocks/consent";

function read(): string | null {
  try { return window.localStorage.getItem(CHOICE_KEY); } catch { return null; }
}
function write(v: string) {
  try { window.localStorage.setItem(CHOICE_KEY, v); } catch { /* private mode: ask again next time */ }
}

export function Consent({ pixel, ga4 }: { pixel?: string; ga4?: string }) {
  const [ask, setAsk] = useState(false);
  useEffect(() => {
    if (!pixel && !ga4) return;
    const w = window as TagWindow;
    if (ga4) consentDefaults(w);   // denied, before any Google tag; loads nothing
    const v = read();
    if (v === "all") loadTags(w, pixel, ga4);
    else if (v === "necessary") applyChoice(w, "necessary", pixel, ga4);
    else setAsk(true);
  }, [pixel, ga4]);
  if (!pixel && !ga4) return null;
  const choose = (v: "all" | "necessary") => {
    write(v);
    setAsk(false);
    if (applyChoice(window as TagWindow, v, pixel, ga4)) window.location.reload();   // switching off: drop loaded tags
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
