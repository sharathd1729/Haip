// Small helpers shared by the interactive site pieces.
import { CHOICE_KEY, storedClick, type Click } from "./consent";
export async function readError(r: Response, fallback: string): Promise<string> {
  try {
    const j = await r.json();
    return j?.detail?.message || fallback;
  } catch {
    return fallback;
  }
}

// Measurement (website phase 2). The sites app defines window.haipTrack only after the visitor accepts the cookie banner
// (sites/src/components/Consent.tsx); before that, and in the editor/previews, these do nothing. The event id comes from
// the server, which sends the same event to Meta's Conversions API, so Meta counts the pair once.
type Tracker = (name: "Lead" | "InitiateCheckout" | "Purchase", eventId: string, data?: { value?: number; currency?: string }) => void;

export function track(name: Parameters<Tracker>[0], eventId: string | undefined, data?: Parameters<Tracker>[2]) {
  if (!eventId || typeof window === "undefined") return;
  try { (window as unknown as { haipTrack?: Tracker }).haipTrack?.(name, eventId, data); } catch { /* never break a booking */ }
}

/** Meta's _fbp / _fbc cookies (set by the pixel, so only after consent), sent with forms for the server-side event.
 *  Plus the cookie-banner choice and GA4's client id ("GA1.1.<random>.<seconds>" -> "<random>.<seconds>"), so the
 *  server's GA4 purchase joins the browser's visit, and goes only when the visitor tapped Accept. Plus the Google Ads
 *  click ids kept after Accept (consent.ts), so the lead (and later its booking upload) carries the ad click. */
type AdIds = { fbp?: string; fbc?: string; analytics_consent?: boolean; ga_client_id?: string } & Click;
export function adIds(): AdIds {
  if (typeof document === "undefined") return {};
  const get = (k: string) => document.cookie.split("; ").find(c => c.startsWith(k + "="))?.slice(k.length + 1)?.slice(0, 200);
  const out: AdIds = {};
  const fbp = get("_fbp"), fbc = get("_fbc");
  if (fbp) out.fbp = fbp;
  if (fbc) out.fbc = fbc;
  let choice: string | null = null;
  try { choice = window.localStorage.getItem(CHOICE_KEY); } catch { /* private mode: no consent recorded */ }
  if (choice === "all") {
    out.analytics_consent = true;
    const cid = get("_ga")?.match(/^GA\d\.\d\.(\d{1,20}\.\d{1,20})$/)?.[1];
    if (cid) out.ga_client_id = cid;
    Object.assign(out, storedClick());
  }
  return out;
}
