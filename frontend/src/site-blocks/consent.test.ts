import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyChoice, captureClick, CLICK_KEY, consentDefaults, DENIED, GRANTED, loadTags, newCode, onWaTap, storedClick,
  tagWaLink, type TagWindow } from "./consent";
import { adIds } from "./util";

const w = () => window as TagWindow;
const googleScripts = () => [...document.querySelectorAll("script")].filter(s => s.src.includes("googletagmanager"));
// gtag pushes the arguments object; compare as plain arrays.
const layer = () => (w().dataLayer || []).map(a => Array.from(a as ArrayLike<unknown>));

function reset() {
  const win = w();
  delete win.dataLayer; delete win.gtag; delete win.fbq; delete win._fbq; delete win.haipGa4Loaded; delete win.haipTrack; delete win.haipPendingClick;
  document.head.innerHTML = "";
  window.localStorage.clear();
  document.cookie.split("; ").forEach(c => { document.cookie = `${c.split("=")[0]}=; expires=Thu, 01 Jan 1970 00:00:00 GMT`; });
}

describe("Consent Mode v2 (basic)", () => {
  beforeEach(reset);
  afterEach(reset);

  it("sets all four signals denied first and loads nothing from Google", () => {
    consentDefaults(w());
    expect(layer()[0]).toEqual(["consent", "default", DENIED]);
    expect(Object.keys(DENIED).sort()).toEqual(["ad_personalization", "ad_storage", "ad_user_data", "analytics_storage"]);
    expect(googleScripts()).toHaveLength(0);
  });

  it("Accept updates to granted before the GA4 tag and then loads gtag.js", () => {
    consentDefaults(w());
    expect(applyChoice(w(), "all", undefined, "G-TEST123")).toBe(false);
    const l = layer();
    expect(l[0]).toEqual(["consent", "default", DENIED]);
    expect(l[1]).toEqual(["consent", "update", GRANTED]);
    expect(l.findIndex(a => a[0] === "config")).toBeGreaterThan(1);
    expect(googleScripts()).toHaveLength(1);
  });

  it("Only necessary keeps everything denied and loads nothing", () => {
    consentDefaults(w());
    expect(applyChoice(w(), "necessary", "123456789", "G-TEST123")).toBe(false);
    expect(layer()).toEqual([["consent", "default", DENIED], ["consent", "update", DENIED]]);
    expect(googleScripts()).toHaveLength(0);
    expect(w().fbq).toBeUndefined();
  });

  it("switching off after Accept asks for a reload to drop the tags", () => {
    loadTags(w(), undefined, "G-TEST123");
    expect(applyChoice(w(), "necessary", undefined, "G-TEST123")).toBe(true);
    expect(layer().at(-1)).toEqual(["consent", "update", DENIED]);
  });
});

describe("adIds GA4 fields", () => {
  beforeEach(reset);
  afterEach(reset);

  it("sends the _ga client id only after Accept", () => {
    document.cookie = "_ga=GA1.1.1234567890.1699999999";
    expect(adIds()).not.toHaveProperty("analytics_consent");
    expect(adIds()).not.toHaveProperty("ga_client_id");
    window.localStorage.setItem("haip_cookie_choice", "all");
    expect(adIds()).toMatchObject({ analytics_consent: true, ga_client_id: "1234567890.1699999999" });
  });
});

describe("Google Ads (website growth #5)", () => {
  beforeEach(reset);
  afterEach(reset);
  const GADS = { id: "AW-123456789", enquiry: "enqLabel1", checkout: "chkLabel2" };
  const GCLID = "EAIaIQobChMI_test-gclid";

  it("loads nothing before Accept, then fires the enquiry conversion with the server's event id", () => {
    consentDefaults(w());
    expect(applyChoice(w(), "necessary", undefined, undefined, GADS)).toBe(false);
    expect(googleScripts()).toHaveLength(0);
    reset();
    consentDefaults(w());
    applyChoice(w(), "all", undefined, undefined, GADS);
    expect(googleScripts()).toHaveLength(1);
    expect(layer()[1]).toEqual(["consent", "update", GRANTED]);
    w().haipTrack!("Lead", "wl:abc");
    w().haipTrack!("InitiateCheckout", "wc:h1", { value: 9000, currency: "INR" });
    w().haipTrack!("Purchase", "stay:1");   // bookings: HAIP uploads them, no browser tag
    const conv = layer().filter(a => a[0] === "event" && a[1] === "conversion").map(a => a[2]);
    expect(conv).toEqual([
      { send_to: "AW-123456789/enqLabel1", transaction_id: "wl:abc" },
      { send_to: "AW-123456789/chkLabel2", transaction_id: "wc:h1", value: 9000, currency: "INR" },
    ]);
  });

  it("keeps click ids only after Accept and drops them on Only necessary", () => {
    captureClick(w(), `?gclid=${GCLID}&utm_source=google`);
    expect(window.localStorage.getItem(CLICK_KEY)).toBeNull();
    expect(storedClick()).toBeNull();
    expect(adIds()).not.toHaveProperty("gclid");
    window.localStorage.setItem("haip_cookie_choice", "all");
    applyChoice(w(), "all", undefined, undefined, GADS);
    expect(storedClick()).toEqual({ gclid: GCLID });
    expect(adIds()).toMatchObject({ analytics_consent: true, gclid: GCLID });
    window.localStorage.setItem("haip_cookie_choice", "necessary");
    applyChoice(w(), "necessary", undefined, undefined, GADS);
    expect(window.localStorage.getItem(CLICK_KEY)).toBeNull();
  });

  it("ignores junk click ids", () => {
    captureClick(w(), "?gclid=%3Cscript%3E");
    expect(w().haipPendingClick).toBeUndefined();
  });

  it("adds the click code to a WhatsApp button's Ref", () => {
    const href = "https://wa.me/919876543210?text=Hi!%20I'd%20like%20to%20know%20more.%20(Ref%20HV-HOME-BOOK)";
    const out = tagWaLink(href, "K7F2Q9XA")!;
    expect(decodeURIComponent(out.split("text=")[1])).toBe("Hi! I'd like to know more. (Ref HV-HOME-BOOK-K7F2Q9XA)");
    expect(tagWaLink("https://wa.me/919876543210?text=Hello", "K7F2Q9XA")).toBeNull();
    expect(tagWaLink(out, "AAAAAAAA")).toBeNull();   // already tagged
    expect(newCode()).toMatch(/^[A-Z0-9]{8}$/);
  });

  it("tags a tap only with a kept click (after Accept)", () => {
    const a = document.createElement("a");
    a.href = "https://wa.me/91987?text=(Ref%20HV-HOME-HERO)";
    expect(onWaTap(a)).toBeNull();
    window.localStorage.setItem("haip_cookie_choice", "all");
    window.localStorage.setItem(CLICK_KEY, JSON.stringify({ gclid: GCLID, at: Date.now() }));
    const out = onWaTap(a)!;
    expect(out).toMatchObject({ gclid: GCLID });
    expect(decodeURIComponent(a.href)).toContain(`(Ref HV-HOME-HERO-${out.code})`);
    expect(onWaTap(a)).toBeNull();   // once per link
  });
});
