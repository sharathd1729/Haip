import { describe, expect, it } from "vitest";
import type { SpecV2 } from "@/site-blocks/v2/types";
import { addPage, addSection, duplicateSection, moveSection, pruneMenus, removePage, removeSection, sectionsOf } from "./targets";
import { startTemplate } from "./templates";

const doc = (): SpecV2 => ({
  spec_version: 2,
  site: { name: "Neelgiri", tagline: "", ref_prefix: null, contact: { phone: "", whatsapp: "", email: "", address: "" }, social: {},
    menus: { main: [{ label: "Story", to: "/story", children: [{ label: "Photos", to: "/#gallery" }] }], footer: [{ label: "Web", to: "https://x.example" }] } },
  tokens: { palette: { name: "forest-amber", ink: "#1B2420", surface: "#F5F1E8", primary: "#2F5D46", accent: "#A8641C" }, display: "fraunces", body: "figtree", radius: "soft", motion: "calm" },
  pages: [{ slug: "/", title: "Home", nav: false, seo: { title: "", description: "" }, sections: [
    { id: "hero", type: "hero", variant: "split", source: "media:approved", slots: { headline: "Hi" } },
    { id: "gallery", type: "gallery", variant: "masonry", source: "media:approved", slots: {} }] },
  { slug: "/story", title: "Story", nav: true, seo: { title: "", description: "" }, sections: [{ id: "text", type: "text", variant: "plain", source: "site:text", slots: {} }] }],
});
const home = { kind: "page", slug: "/" } as const;

describe("on-page editor operations (website W2/W4)", () => {
  it("adds, copies and moves parts with site-unique ids", () => {
    const d = doc();
    expect(addSection(d, home, "gallery", 1)).toBe("gallery-2");
    expect(duplicateSection(d, home, 0)).toBe("hero-2");
    moveSection(d, home, 0, 1);
    expect(sectionsOf(d, home)!.map(s => s.id)).toEqual(["hero-2", "hero", "gallery-2", "gallery"]);
  });

  it("removing a part or page also drops menu links that would point nowhere", () => {
    const d = doc();
    removeSection(d, home, 1);
    expect(d.site.menus!.main[0].children).toEqual([]);
    removePage(d, "/story");
    expect(d.site.menus!.main).toEqual([]);
    expect(d.site.menus!.footer).toHaveLength(1);
    pruneMenus(d);
    removePage(d, "/");
    expect(d.pages).toHaveLength(1);                    // the home page never goes
  });

  it("a new page gets a free address; a design copies the standard parts with fresh ids", () => {
    const d = doc();
    expect(addPage(d, "Story")).toBe("/story-2");
    startTemplate(d, "stay");
    expect(d.templates!.stay!.sections.map(s => s.type)).toEqual(["stay-gallery", "stay-details", "stay-booking", "stay-rules", "stay-map"]);
    expect(sectionsOf(d, { kind: "template", key: "stay" })).toHaveLength(5);
    expect(addSection(d, { kind: "template", key: "stay" }, "stay-booking")).toBe("stay-booking-2");
  });
});
