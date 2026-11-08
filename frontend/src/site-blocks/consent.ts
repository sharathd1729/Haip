// Cookie-banner tags for a live HAIP site (sites app components/Consent.tsx; website phase 2). Lives here, not in the
// sites app, so the frontend's vitest covers it (sync-blocks copies it into sites/src/site-blocks).
//
// Google Consent Mode v2, BASIC mode: consent defaults (all four signals denied) are the first thing on the dataLayer,
// set before any Google tag, and NOTHING from Google (gtag.js) loads until the visitor taps Accept. Accept = update to
// granted, then gtag.js loads; "Only necessary" = update to denied (stays denied, nothing loads). Advanced mode (gtag.js
// loading before consent and sending cookieless pings while denied) is an owner/counsel decision under DPDP: do not
// switch to it without one. Meta's pixel is unchanged: it loads only on Accept and has no consent-mode signals.

export const CHOICE_KEY = "haip_cookie_choice";
export type Choice = "all" | "necessary";

type Signals = { ad_storage: string; analytics_storage: string; ad_user_data: string; ad_personalization: string };
const signals = (v: "granted" | "denied"): Signals =>
  ({ ad_storage: v, analytics_storage: v, ad_user_data: v, ad_personalization: v });
export const DENIED = signals("denied");
export const GRANTED = signals("granted");

export type TagWindow = Window & { fbq?: (...a: unknown[]) => void; _fbq?: unknown; dataLayer?: unknown[];
  gtag?: (...a: unknown[]) => void; haipGa4Loaded?: boolean;
  haipTrack?: (name: string, id: string, data?: { value?: number; currency?: string }) => void };

function addScript(src: string) {
  const s = document.createElement("script");
  s.async = true;
  s.src = src;
  document.head.appendChild(s);
}

/** The dataLayer + gtag queue with Consent Mode defaults denied. Loads nothing; safe before any choice. */
export function consentDefaults(w: TagWindow) {
  if (w.gtag) return;
  w.dataLayer = w.dataLayer || [];
  w.gtag = function gtag() { (w.dataLayer as unknown[]).push(arguments); };   // gtag.js reads the arguments object
  w.gtag("consent", "default", DENIED);
}

const GA4_EVENTS: Record<string, string> = { Lead: "generate_lead", InitiateCheckout: "begin_checkout", Purchase: "purchase" };

/** Accept: consent granted, then the tags load. Only ever called after the visitor tapped Accept. */
export function loadTags(w: TagWindow, pixel?: string, ga4?: string) {
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
  if (ga4 && !w.haipGa4Loaded) {
    consentDefaults(w);
    const gtag = w.gtag!;
    gtag("consent", "update", GRANTED);
    gtag("js", new Date());
    gtag("config", ga4, { anonymize_ip: true });
    addScript(`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(ga4)}`);
    w.haipGa4Loaded = true;
  }
  w.haipTrack = (name, id, data) => {
    if (w.fbq && pixel) w.fbq("track", name, data || {}, { eventID: id });
    if (w.haipGa4Loaded && w.gtag && ga4) w.gtag("event", GA4_EVENTS[name] || name, { ...(data || {}), transaction_id: name === "Purchase" ? id : undefined });
  };
}

/** The banner's choice. Returns true when tags were already loaded and the page must reload to drop them. */
export function applyChoice(w: TagWindow, choice: Choice, pixel?: string, ga4?: string): boolean {
  if (choice === "all") {
    loadTags(w, pixel, ga4);
    return false;
  }
  if (ga4) {
    consentDefaults(w);
    w.gtag!("consent", "update", DENIED);
  }
  return Boolean(w.fbq || w.haipGa4Loaded);
}
