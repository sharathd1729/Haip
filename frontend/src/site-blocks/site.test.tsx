import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { findPage, SiteRenderer } from "./SiteRenderer";
import { hrefOf, imageOf, SPEC, type LiveData, type SiteEnv } from "./types";
import { addBlock, addPage, moveBlock, newBlock, removeBlock } from "@/components/website/docOps";

function live(over: Partial<LiveData["site"]> = {}): LiveData {
  return {
    site: { id: "s1", name: "Coffee Villas", status: "live", preview: false, booking_mode: "request", deposit_percent: 30, show_prices: false,
      hold_minutes: 20, min_nights: 1, prices_include_gst: false, today: "2026-11-01", ...over },
    version: { id: "v1", number: 3, sha256: "x" },
    doc: {
      schema: 1, theme: { pack: "malnad", personality: "calm" },
      site: { name: "Coffee Villas", tagline: "Two villas in Coorg", logo: "", contact: { phone: "+91 98450 00000", whatsapp: "+91 98450 00000", email: "hi@example.com", address: "Madikeri" }, social: {} },
      pages: [
        { id: "home", key: "home", title: "Home", path: "/", nav: false, seo: { title: "Coffee Villas", description: "" }, content: [
          { type: "Hero", props: { id: "h1", layout: "split", background: "page", kicker: "Coorg", title: "Your *quiet* villa", text: "Hello", chips: ["4.9 ★"], image1: "asset:11111111-1111-1111-1111-111111111111", image2: "", image3: "", cta_label: "Check dates", cta_link: "/book" } },
          { type: "Stays", props: { id: "s1", layout: "cards", background: "page", kicker: "", heading: "Our villas", intro: "", limit: "all" } },
          { type: "Reviews", props: { id: "r1", layout: "grid", background: "page", kicker: "", heading: "Guests say", items: [] } },
        ] },
        { id: "stay", key: "stay", title: "Stay page", path: "/stays/[slug]", nav: false, seo: { title: "{stay}", description: "" }, content: [{ type: "StayDetail", props: { id: "d1", intro: "" } }] },
        { id: "policies", key: "policies", title: "Policies", path: "/policies", nav: false, seo: { title: "", description: "" }, content: [{ type: "Policies", props: { id: "p1", heading: "Policies", extra: "" } }] },
      ],
    },
    stays: [{ id: "pr1", slug: "green-goose", name: "Green Goose", type: "villa", sleeps: 4, max_adults: 4, city: "Coorg", photos: [], amenities: [], summary: "", from_price: "4200" }],
    assets: { "11111111-1111-1111-1111-111111111111": { src: "/_haip/media/11111111-1111-1111-1111-111111111111", alt: "Pool" } },
    policies: { cancellation_policy: { tiers: [{ days_before: 7, refund_percent: 100 }, { days_before: 2, refund_percent: 50 }] } },
    legal: { legal_name: "Coffee Villas LLP", gstin: "29ABCDE1234F1Z5", address: "Madikeri, Karnataka" },
  };
}

const env = (l: LiveData): SiteEnv => ({ mode: "live", base: "", apiBase: "/_haip/api", query: {}, assets: { "11111111-1111-1111-1111-111111111111": { src: "/_haip/media/11111111-1111-1111-1111-111111111111", alt: "Pool" } }, stay: l.stays[0] });

describe("site renderer", () => {
  it("renders the hero with emphasis, the photo and the stays without prices when prices are off", () => {
    const l = live();
    const html = renderToString(<SiteRenderer live={l} page={l.doc.pages[0]} env={env(l)} />);
    expect(html).toContain("<em>quiet</em>");
    expect(html).toContain("/_haip/media/11111111-1111-1111-1111-111111111111");
    expect(html).toContain("Green Goose");
    expect(html).not.toContain("₹4,200");
    expect(html).not.toContain("Guests say");          // an empty Reviews section never shows on the live site
    expect(html).toContain("wa.me/919845000000");
  });

  it("shows prices only when the site does", () => {
    const l = live({ show_prices: true });
    expect(renderToString(<SiteRenderer live={l} page={l.doc.pages[0]} env={env(l)} />)).toContain("₹4,200");
  });

  it("renders the refund table and legal details on the policies page", () => {
    const l = live();
    const html = renderToString(<SiteRenderer live={l} page={l.doc.pages[2]} env={env(l)} />);
    expect(html).toContain("7 or more days before arrival");
    expect(html).toContain("29ABCDE1234F1Z5");
  });

  it("finds pages by path and stay pages by slug", () => {
    const l = live();
    expect(findPage(l, "/")?.page.id).toBe("home");
    expect(findPage(l, "/stays/green-goose")?.slug).toBe("green-goose");
    expect(findPage(l, "/stays/nope")).toBeNull();
    expect(findPage(l, "/stays/[slug]")).toBeNull();
  });

  it("prefixes links in a preview and resolves only known photos", () => {
    const e: SiteEnv = { mode: "preview", base: "/_haip/preview/tok", apiBase: null, assets: { a: { src: "/x", alt: "" } } };
    expect(hrefOf(e, "/book?x=1")).toBe("/_haip/preview/tok/book?x=1");
    expect(hrefOf(e, "/")).toBe("/_haip/preview/tok");
    expect(hrefOf({ ...e, base: "" }, "/")).toBe("/");
    expect(imageOf(e, "asset:a")?.src).toBe("/x");
    expect(imageOf(e, "https://evil.example/x.jpg")).toBeNull();
  });
});

describe("document operations", () => {
  it("adds, moves and removes sections but never removes a HAIP section", () => {
    const l = live();
    const d = structuredClone(l.doc);
    const id = addBlock(d, "home", "Offer", "h1");
    expect(d.pages[0].content[1].props.id).toBe(id);
    moveBlock(d, "home", id, -1);
    expect(d.pages[0].content[0].props.id).toBe(id);
    removeBlock(d, "stay", "d1");
    expect(d.pages[1].content).toHaveLength(1);
    const pid = addPage(d, "Long stays");
    expect(d.pages.find(p => p.id === pid)?.path).toBe("/long-stays");
    expect(addPage(d, "Long stays")).toBe("long-stays-2");
  });

  it("new sections carry every field from the spec", () => {
    for (const type of Object.keys(SPEC.blocks)) {
      const b = newBlock(type);
      for (const f of SPEC.blocks[type].fields) expect(b.props).toHaveProperty(f.key);
    }
  });
});
