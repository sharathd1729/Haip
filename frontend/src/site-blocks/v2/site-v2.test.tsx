import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import type { SiteEnv } from "../types";
import { SiteRendererV2 } from "./SiteRendererV2";
import { CATALOGUE, findPageV2, isV2, type Bound, type LiveDataV2, type SectionType, type SectionV2 } from "./types";

const PHOTO = "asset:11111111-1111-1111-1111-111111111111";
const wa = (code: string) => ({ code, href: `https://wa.me/919845000000?text=Hi%20(Ref%20${code})` });
const TYPES = Object.keys(CATALOGUE.sections) as SectionType[];

function boundFor(t: SectionType, id: string, grounded: boolean): Bound {
  const base = { wa: wa(`WW-HOME-${id.replace(/[^a-z0-9]/gi, "").toUpperCase()}`) };
  switch (t) {
    case "hero": return { ...base, media: PHOTO };
    case "booking": return { ...base, items: [{ id: "p1", name: "Ratha 1", sleeps: 4 }, { id: "p2", name: "Ratha 2", sleeps: 4 }] };
    case "stays": return { ...base, items: [
      { id: "p1", name: "Ratha 1", summary: "Sleeps four with an ensuite.", sleeps: 4, bedrooms: 1, amenities: ["Ensuite", "Kitchenette"], photo: PHOTO },
      { id: "p2", name: "Ratha 2", summary: "", sleeps: 4, bedrooms: null, amenities: [], photo: "https://cdn.example.com/r2.jpg" }] };
    case "packages": return { ...base, items: [
      { key: "weekend", name: "Weekend Escape", summary: "Two nights in the hills.", length: "2 nights / 3 days", inclusions: ["Driver-host", "Breakfast"],
        days: ["Into the hills", "Estate walk", "Home"], destinations: ["Misty Hills"], max_guests: 4,
        price: grounded ? { amount: "38000", label: "2 adults, 2 nights from 8 Nov, incl. GST (live quote)" } : null,
        price_label: grounded ? null : "Get the price on WhatsApp", wa: base.wa },
      { key: "sunset", name: "Sunset Overnight", summary: "", length: "1 night / 2 days", inclusions: [], days: [], destinations: [], max_guests: 2,
        price: null, price_label: "Get the price on WhatsApp", wa: base.wa }] };
    case "itinerary": return { ...base, itinerary: { name: "Misty Hills Loop", nights: 2, destination: "Misty Hills", about: "Coffee and mist.",
      packages: ["Weekend Escape"], days: [{ day: 1, title: "Into the hills", stops: ["Bengaluru", "Camp"], overnight: "Camp", notes: "" },
        { day: 2, title: "Waterfall", stops: ["Falls"], overnight: "", notes: "Swim if the water is calm." }] } };
    case "gallery": return { ...base, media: [PHOTO] };
    case "reviews": return { ...base, items: [{ quote: "Waking up by the river was magic.", name: "Meera", rating: 5, source: "google", date: "2026-09" }],
      count: 12, average: 4.8 };
    case "faq": return { ...base, items: [{ q: "Are pets allowed?", a: "Yes, small dogs are welcome." }] };
    default: return base;
  }
}

function live(grounded: boolean, over: Partial<Record<SectionType, Partial<Bound>>> = {}): LiveDataV2 {
  const sections: SectionV2[] = TYPES.flatMap(t => CATALOGUE.sections[t].variants.map(v => ({
    id: `${t}-${v}`, type: t, variant: v, source: CATALOGUE.sections[t].source,
    slots: { eyebrow: "Coorg", heading: `${t} ${v}`, headline: "Wake up where the *road* ends", cta_label: "Plan my trip", show_map: true, limit: 6 },
  })));
  const bound: Record<string, Bound> = {};
  for (const s of sections) bound[s.id] = { ...boundFor(s.type, s.id, grounded), ...(over[s.type] || {}) };
  return {
    spec_version: 2,
    site: { id: "s1", name: "Wanderwheel", status: "live", preview: false, booking_mode: "request", deposit_percent: 30, show_prices: grounded,
      hold_minutes: 20, min_nights: 1, prices_include_gst: false, today: "2026-11-01" },
    version: { id: "v2", number: 2, sha256: "x" },
    doc: { spec_version: 2, site: { name: "Wanderwheel Caravans", tagline: "Road trips, slowly", ref_prefix: "WW",
      contact: { phone: "+91 98450 00000", whatsapp: "+91 98450 00000", email: "hi@example.com", address: "Madikeri, Coorg" }, social: {} },
      tokens: { palette: { name: "forest-amber", ink: "#1B2420", surface: "#F5F1E8", primary: "#2F5D46", accent: "#A8641C" }, display: "fraunces",
        body: "figtree", radius: "soft", motion: "calm" },
      pages: [{ slug: "/", title: "Home", nav: false, seo: { title: "", description: "" }, sections },
        { slug: "/journeys", title: "Journeys", nav: true, seo: { title: "", description: "" }, sections: sections.slice(0, 1) }] },
    theme: { vars: { "--v-primary": "#2F5D46", "--v-surface": "#F5F1E8" }, motion: "calm", scheme: "light",
      fonts_href: "https://fonts.googleapis.com/css2?family=Fraunces&family=Figtree&display=swap" },
    price_mode: grounded ? "grounded" : "handoff",
    bound, page_wa: { "/": wa("WW-HOME-NAV"), "/journeys": wa("WW-JOURNEYS-NAV") },
    assets: { "11111111-1111-1111-1111-111111111111": { src: "/_haip/media/11111111-1111-1111-1111-111111111111", alt: "Caravan at dawn", w: 1600, h: 1067 } },
    legal: { legal_name: "Wanderwheel LLP", gstin: null, address: null },
  };
}

const env = (l: LiveDataV2): SiteEnv => ({ mode: "live", base: "", apiBase: "/_haip/api", query: {},
  assets: Object.fromEntries(Object.entries(l.assets).map(([k, a]) => [k, { src: a.src, alt: a.alt }])) });
const html = (l: LiveDataV2, slug = "/") => renderToString(<SiteRendererV2 live={l} page={findPageV2(l, slug)!} env={env(l)} />);
const PRICE = /(₹|Rs\.?\s?|INR\s?)\s*\d/;

describe("v2 site renderer", () => {
  it.each([["handoff", false], ["grounded", true]])("renders all 8 sections x 3 variants in %s mode", (_mode, grounded) => {
    const out = html(live(grounded));
    for (const t of TYPES) for (const v of CATALOGUE.sections[t].variants) expect(out).toContain(`data-variant="${v}"`);
    expect(out).toContain('<em class="sv-em">road</em>');
    expect(out).toContain('data-wa-ref="WW-HOME-HEROSPLIT"');
    expect(out).toContain('data-wa-ref="WW-HOME-NAV"');
    expect(out).toContain("/_haip/media/11111111-1111-1111-1111-111111111111");
    expect(out).toContain("Into the hills");
    expect(out).toContain("Are pets allowed?");
    expect(out).toContain('name="phone"');                     // the inline enquiry form
  });

  it("handoff mode shows no price figure anywhere, only the WhatsApp ask", () => {
    const out = html(live(false));
    expect(out).not.toMatch(PRICE);
    expect(out).toContain("Get the price on WhatsApp");
  });

  it("grounded mode shows the live quote with what it covers", () => {
    const out = html(live(true));
    expect(out).toContain("₹38,000");
    expect(out).toContain("live quote");
  });

  it("hides a section HAIP has no data for and keeps one h1", () => {
    const out = html(live(false, { packages: { items: [] }, faq: { items: [] }, itinerary: { itinerary: null }, gallery: { media: [] },
      reviews: { items: [], average: null, count: 0 } }));
    for (const t of ["packages", "faq", "itinerary", "gallery", "reviews"]) expect(out).not.toContain(`data-section="${t}"`);
    expect(out.match(/<h1/g)?.length).toBe(1);
  });

  it("finds v2 pages by slug, tells v2 from v1, and applies the theme and motion preset", () => {
    const l = live(false);
    expect(isV2(l)).toBe(true);
    expect(findPageV2(l, "journeys/")?.title).toBe("Journeys");
    expect(findPageV2(l, "/nope")).toBeNull();
    const out = html(l, "/journeys");
    expect(out).toContain('data-motion="calm"');
    expect(out).toContain("--v-primary:#2F5D46");
    expect(out).toContain('aria-current="page"');
  });
});
