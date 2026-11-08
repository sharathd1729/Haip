// Cookie-banner tags for a live HAIP site (sites app components/Consent.tsx; website phase 2). Lives here, not in the
// sites app, so the frontend's vitest covers it (sync-blocks copies it into sites/src/site-blocks).
//
// Google Consent Mode v2, BASIC mode: consent defaults (all four signals denied) are the first thing on the dataLayer,
// set before any Google tag, and NOTHING from Google (gtag.js) loads until the visitor taps Accept. Accept = update to
// granted, then gtag.js loads; "Only necessary" = update to denied (stays denied, nothing loads). Advanced mode (gtag.js
// loading before consent and sending cookieless pings while denied) is an owner/counsel decision under DPDP: do not
// switch to it without one. Meta's pixel is unchanged: it loads only on Accept and has no consent-mode signals.
//
// Google Ads (website growth #5): the same gtag.js also carries the Ads tag ("AW-..."); after Accept, Lead and
// InitiateCheckout fire the owner's "enquiry" / "begin checkout" conversion labels with the server's event id as
// transaction_id. Bookings have no browser tag: HAIP uploads them (google_ads_conversions). Click ids (gclid / gbraid /
// wbraid) from the landing URL stay in memory until Accept, then in localStorage for 90 days; "Only necessary" drops
// them. A WhatsApp button tap with a kept click adds an 8-letter code to its "(Ref ...)" text and tells HAIP
// code -> click ids, so the chat's lead gets them too.

export const CHOICE_KEY = "haip_cookie_choice";
export type Choice = "all" | "necessary";

type Signals = { ad_storage: string; analytics_storage: string; ad_user_data: string; ad_personalization: string };
const signals = (v: "granted" | "denied"): Signals =>
  ({ ad_storage: v, analytics_storage: v, ad_user_data: v, ad_personalization: v });
export const DENIED = signals("denied");
export const GRANTED = signals("granted");

export type TagWindow = Window & { fbq?: (...a: unknown[]) => void; _fbq?: unknown; dataLayer?: unknown[];
  gtag?: (...a: unknown[]) => void; haipGa4Loaded?: boolean; haipPendingClick?: Click;
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

/** The site's Google Ads tag id + conversion labels (bootstrap `tracking.gads`). */
export type Gads = { id: string; enquiry?: string; checkout?: string };
const GADS_LABEL: Record<string, "enquiry" | "checkout"> = { Lead: "enquiry", InitiateCheckout: "checkout" };

// ─── Google Ads click ids ─────────────────────────────────────────────────────────────────────────────
export const CLICK_KEY = "haip_gclick";
const CLICK_KEYS = ["gclid", "gbraid", "wbraid"] as const;
const CLICK_MAX_AGE = 90 * 24 * 3600 * 1000;   // Google's longest click-through window
const CLICK_ID = /^[A-Za-z0-9_-]{8,200}$/;
export type Click = Partial<Record<(typeof CLICK_KEYS)[number], string>>;

function savedChoice(): string | null {
  try { return window.localStorage.getItem(CHOICE_KEY); } catch { return null; }
}

/** Remember the landing URL's click ids: in memory now, in this browser only once the visitor accepted. */
export function captureClick(w: TagWindow, search: string) {
  const p = new URLSearchParams(search);
  const c: Click = {};
  for (const k of CLICK_KEYS) { const v = p.get(k); if (v && CLICK_ID.test(v)) c[k] = v; }
  if (!Object.keys(c).length) return;
  w.haipPendingClick = c;
  if (savedChoice() === "all") saveClick(w);
}

export function saveClick(w: TagWindow) {
  if (!w.haipPendingClick) return;
  try { window.localStorage.setItem(CLICK_KEY, JSON.stringify({ ...w.haipPendingClick, at: Date.now() })); } catch { /* private mode */ }
}

export function dropClick(w: TagWindow) {
  delete w.haipPendingClick;
  try { window.localStorage.removeItem(CLICK_KEY); } catch { /* private mode */ }
}

/** The kept click ids, only while the visitor's choice is Accept (and the click is under 90 days old). */
export function storedClick(): Click | null {
  if (savedChoice() !== "all") return null;
  try {
    const j = JSON.parse(window.localStorage.getItem(CLICK_KEY) || "null");
    if (!j || typeof j.at !== "number" || Date.now() - j.at > CLICK_MAX_AGE) return null;
    const c: Click = {};
    for (const k of CLICK_KEYS) if (typeof j[k] === "string" && CLICK_ID.test(j[k])) c[k] = j[k];
    return Object.keys(c).length ? c : null;
  } catch { return null; }
}

/** wa.me link with "-<code>" added to its "(Ref A-B-C)" text, or null when the link carries no plain Ref. */
export function tagWaLink(href: string, code: string): string | null {
  const m = href.match(/[?&]text=([^&]*)/);
  if (!m) return null;
  let text: string;
  try { text = decodeURIComponent(m[1].replace(/\+/g, " ")); } catch { return null; }
  const next = text.replace(/\(Ref ([A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+)\)/, `(Ref $1-${code})`);
  if (next === text) return null;
  return href.replace(/([?&]text=)[^&]*/, (_, p) => p + encodeURIComponent(next));
}

export function newCode(): string {
  const abc = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";   // 32 letters: b % 32 has no bias
  return Array.from(crypto.getRandomValues(new Uint8Array(8)), b => abc[b % abc.length]).join("");
}

/** A tap on a WhatsApp button: with a kept click, tag the link and return {code, ...click} for HAIP (else null). */
export function onWaTap(a: HTMLAnchorElement): ({ code: string } & Click) | null {
  if (a.dataset.haipTagged) return null;
  const click = storedClick();
  if (!click) return null;
  const code = newCode();
  const href = tagWaLink(a.href, code);
  if (!href) return null;
  a.href = href;
  a.dataset.haipTagged = "1";
  return { code, ...click };
}

/** Accept: consent granted, then the tags load. Only ever called after the visitor tapped Accept. */
export function loadTags(w: TagWindow, pixel?: string, ga4?: string, gads?: Gads) {
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
  const first = ga4 || gads?.id;
  if (first && !w.haipGa4Loaded) {   // haipGa4Loaded = Google's tag (GA4 and/or Ads) is loaded
    consentDefaults(w);
    const gtag = w.gtag!;
    gtag("consent", "update", GRANTED);
    gtag("js", new Date());
    if (ga4) gtag("config", ga4, { anonymize_ip: true });
    if (gads) gtag("config", gads.id);
    addScript(`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(first)}`);
    w.haipGa4Loaded = true;
  }
  saveClick(w);
  w.haipTrack = (name, id, data) => {
    if (w.fbq && pixel) w.fbq("track", name, data || {}, { eventID: id });
    if (w.haipGa4Loaded && w.gtag && ga4) w.gtag("event", GA4_EVENTS[name] || name, { ...(data || {}), transaction_id: name === "Purchase" ? id : undefined });
    const label = gads && GADS_LABEL[name] ? gads[GADS_LABEL[name]] : undefined;
    if (w.haipGa4Loaded && w.gtag && gads && label) {
      w.gtag("event", "conversion", { send_to: `${gads.id}/${label}`, transaction_id: id,
        ...(data?.value ? { value: data.value, currency: data.currency || "INR" } : {}) });
    }
  };
}

/** The banner's choice. Returns true when tags were already loaded and the page must reload to drop them. */
export function applyChoice(w: TagWindow, choice: Choice, pixel?: string, ga4?: string, gads?: Gads): boolean {
  if (choice === "all") {
    loadTags(w, pixel, ga4, gads);
    return false;
  }
  dropClick(w);
  if (ga4 || gads) {
    consentDefaults(w);
    w.gtag!("consent", "update", DENIED);
  }
  return Boolean(w.fbq || w.haipGa4Loaded);
}
