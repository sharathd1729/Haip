import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyChoice, consentDefaults, DENIED, GRANTED, loadTags, type TagWindow } from "./consent";
import { adIds } from "./util";

const w = () => window as TagWindow;
const googleScripts = () => [...document.querySelectorAll("script")].filter(s => s.src.includes("googletagmanager"));
// gtag pushes the arguments object; compare as plain arrays.
const layer = () => (w().dataLayer || []).map(a => Array.from(a as ArrayLike<unknown>));

function reset() {
  const win = w();
  delete win.dataLayer; delete win.gtag; delete win.fbq; delete win._fbq; delete win.haipGa4Loaded; delete win.haipTrack;
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
