import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { FactsList } from "./BriefStep";
import { FONTS_HREF, SitemapView, StyleView, WireframeView } from "./Artifacts";
import { toLines, type BriefFacts, type StyleArt } from "@/lib/websiteBuilder";

const style: StyleArt = { note: "Three looks.", directions: [
  { name: "Estate Morning", mood: "Warm paper.", sample_headline: "Three *mornings*", tokens: { palette: { name: "estate-olive", ink: "#23241C", surface: "#F4EFE3", primary: "#4B5A2A", accent: "#A4432C" }, display: "fraunces", body: "figtree", radius: "soft", motion: "calm" } },
  { name: "Lamp", mood: "Night.", sample_headline: "Your room", tokens: { palette: { name: "lamp-night", ink: "#F2EBDD", surface: "#121A2E", primary: "#E3B14E", accent: "#E58A6B" }, display: "bricolage", body: "inter", radius: "pill", motion: "calm" } },
  { name: "Coast", mood: "Sea.", sample_headline: "Sunset", tokens: { palette: { name: "coast-sand", ink: "#1A2531", surface: "#F7F2EA", primary: "#1D5C75", accent: "#B9552F" }, display: "playfair", body: "manrope", radius: "sharp", motion: "calm" } },
] };

describe("art director artifacts", () => {
  it("shows the sitemap with a reason for every page and section", () => {
    const html = renderToString(<SitemapView a={{ note: "Lead with the road.", pages: [{ slug: "/", title: "Home", nav: false, reason: "Where enquiries start",
      sections: [{ type: "hero", reason: "Show the caravan" }, { type: "booking-cta", reason: "A clear ask" }] }] }} />);
    expect(html).toContain("Where enquiries start");
    expect(html).toContain("Booking call to action");
    expect(html).toContain("Show the caravan");
  });

  it("draws the wireframe as section blocks with their variant names", () => {
    const html = renderToString(<WireframeView a={{ note: "", pages: [{ slug: "/", title: "Home", nav: false, seo_title: "", seo_description: "",
      sections: [{ id: "hero", type: "hero", variant: "fullbleed-image", headline: "Wake up where the *road* ends" }] }] }} />);
    expect(html).toContain("fullbleed-image");
    expect(html).toContain("Wake up where the road ends");
  });

  it("shows three style cards with swatches, faces and a pick button, and readable button text", () => {
    const picks: number[] = [];
    const html = renderToString(<StyleView a={style} pickedIndex={null} onPick={i => picks.push(i)} />);
    expect(html.match(/Use this look/g)?.length).toBe(3);
    expect(html).toContain("Fraunces + Figtree");
    expect(html).toContain("background:#121A2E");
    expect(html).toContain("color:#121A2E");                  // dark surface reads on gold primary
    expect(FONTS_HREF).toContain("family=Fraunces");
  });

  it("lists HAIP's facts and says plainly when something is missing", () => {
    const f = { business: { name: "Wanderwheel", type: "caravan", tagline: "", description: "", usps: [], languages: [] },
      location: { city: "Bengaluru", region: "", address: "" }, contact: { phone: "", whatsapp: "", email: "", address: "" },
      brand_kit: { primary: null, accent: null, font: null, has_logo: false }, price_policy: "handoff", packages: [], destinations: [],
      itineraries: [], stays: [], content: { faq_questions: [], faq_count: 0, approved_photos: 3, reviews_usable: 0, reviews_rated: 0, average_rating: null },
      guests_last_year: { enquiries: 0 } } satisfies BriefFacts;
    const html = renderToString(<FactsList f={f} />);
    expect(html).toContain("Nothing in HAIP yet");
    expect(html).toContain("Never: guests ask on WhatsApp");
    expect(toLines(" a \n\n b ")).toEqual(["a", "b"]);
  });
});
