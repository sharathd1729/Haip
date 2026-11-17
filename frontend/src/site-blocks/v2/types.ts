// SiteSpec v2 types: a hand mirror of backend/app/schemas/site_spec.py (change both together). spec.json is a copy of
// backend/app/services/website_spec_v2.json (backend tests compare them). The server validates the spec and binds every
// section's data (website_bindings.py); this folder only renders what it is given.
import catalogue from "./spec.json";
import type { LiveData } from "../types";

export type SectionType = "hero" | "stays" | "booking" | "packages" | "itinerary" | "gallery" | "reviews" | "faq" | "contact" | "booking-cta" | "text" | "offer"
  | "stay-gallery" | "stay-details" | "stay-rules" | "stay-map" | "stay-booking" | "package-details";
/** Parts only a stay / package page design uses (website W4; backend site_spec.template_of). */
export const templateOf = (t: string): "stay" | "package" | null => (t.startsWith("stay-") ? "stay" : t.startsWith("package-") ? "package" : null);
/** Site sections a page design may also use (backend TEMPLATE_SHARED). */
export const TEMPLATE_SHARED: SectionType[] = ["text", "reviews", "faq", "gallery", "booking-cta", "contact", "offer"];
/** A design used until the owner makes their own (W4). Ids are fixed: the sites app and the editor both draw it. */
export function defaultTemplate(key: "stay" | "package"): SectionV2[] {
  const part = (type: SectionType, variant: string): SectionV2 => ({ id: type, type, variant, source: CATALOGUE.sections[type].source, slots: {} });
  return key === "stay" ? [part("stay-gallery", "mosaic"), part("stay-details", "two-column"), part("stay-booking", "card"), part("stay-rules", "chips"),
    part("stay-map", "card")]
    : [part("package-details", "two-column")];
}

export const CATALOGUE = catalogue as unknown as {
  spec_version: 2;
  sections: Record<SectionType, { label: string; variants: string[]; source: string }>;
  palettes: Record<string, { label: string; ink: string; surface: string; primary: string; accent: string }>;
  fonts: { display: Record<string, { family: string; stack: string }>; body: Record<string, { family: string; stack: string }> };
};

export interface WaLink { code: string; href: string }
export interface Contact { phone: string; whatsapp: string; email: string; address: string }

/** Header logo; `logo` = "asset:<id>" from the approved library. show_name false = the logo already spells the name. */
export interface Brand { logo: string | null; show_name: boolean }
/** A menu link: "/page", "/page#section-id", "/stays/<slug>", "/policies" or an https:// link. */
export interface MenuItem { label: string; to: string }
export interface Menus { main: (MenuItem & { children: MenuItem[] })[]; footer: MenuItem[] }

export interface SectionV2 { id: string; type: SectionType; variant: string; slots: Record<string, unknown>; source: string }
export interface PageV2 { slug: string; title: string; nav: boolean; seo: { title: string; description: string }; sections: SectionV2[] }
export interface SpecV2 {
  spec_version: 2;
  site: { name: string; tagline: string; ref_prefix: string | null; contact: Contact; social: Record<string, string>;
    /** Website W1 (backend site_spec.py SiteInfo): absent until the owner sets them. */
    brand?: Brand; whatsapp_button?: { on: boolean; text: string }; menus?: Menus };
  tokens: { palette: { name: string; ink: string; surface: string; primary: string; accent: string }; display: string; body: string;
    radius: "soft" | "sharp" | "pill"; motion: "calm" };
  pages: PageV2[];
  /** Website W4: one design that makes a page per stay (/stays/<slug>) or per package (/packages/<key>). */
  templates?: Partial<Record<"stay" | "package", { sections: SectionV2[] }>>;
  /** Other languages' words (website phase 6, i18n.ts): tagline, page titles/search texts by slug, section text by id. */
  i18n?: Record<string, { tagline?: string; pages?: Record<string, { title?: string; seo_title?: string; seo_description?: string }>;
    sections?: Record<string, Record<string, string>> }>;
}

export interface PackageItem {
  key: string; name: string; summary: string; length: string; inclusions: string[]; days: string[]; destinations: string[];
  max_guests: number; price: { amount: string; label: string } | null; price_label: string | null; wa: WaLink | null;
}
/** grounded price mode only: the lowest nightly tariff from HAIP's website price engine (website_pricing.from_price). */
export interface FromPrice { amount: string; label: string }
/** One bookable property (caravan, villa, room). `photo` is "asset:<id>" (approved library photo) or an https URL. */
export interface StayItem { id: string; slug?: string; bathrooms?: number | null; city?: string; name: string; summary: string; sleeps: number; bedrooms: number | null; amenities: string[]; photo: string | null; from: FromPrice | null }
export interface ItineraryDay { day: number; title: string; stops: string[]; overnight: string; notes: string }
export interface Itinerary { name: string; nights: number; destination: string; about: string; packages: string[]; days: ItineraryDay[] }
export interface Review { quote: string; name: string; rating: number | null; source: string; date: string }

/** Server-bound data per section id. Each section reads only its own keys. */
export interface Bound {
  wa: WaLink | null;
  media?: string | string[] | null;
  items?: unknown[];
  itinerary?: Itinerary | null;
  count?: number;
  average?: number | null;
  /** offer band: its promo code while usable; `label` ("15% off") only when the business shows prices. */
  promo?: { code: string; until: string | null; min_nights: number; label: string | null } | null;
}

export interface LiveDataV2 {
  spec_version: 2;
  site: LiveData["site"];
  version: LiveData["version"];
  doc: SpecV2;
  theme: { vars: Record<string, string>; motion: "calm"; scheme: "light" | "dark"; fonts_href: string };
  price_mode: "handoff" | "grounded";
  bound: Record<string, Bound>;
  page_wa: Record<string, WaLink | null>;
  /** The floating WhatsApp button per page slug (only while site.whatsapp_button.on). */
  float_wa?: Record<string, WaLink | null>;
  assets: LiveData["assets"];
  policies: LiveData["policies"];
  legal: LiveData["legal"];
  tracking?: LiveData["tracking"];
  /** JSON-LD per page slug (backend website_seo; live pages only). */
  jsonld?: Record<string, object[]>;
  business_kind?: string | null;
  /** Approved guides on this site (website_blog); the footer links /blog when > 0. */
  blog_count?: number;
  /** Every stay the site offers (phase 6): /stays/<slug> pages and /compare. */
  stays_index?: StayItem[];
  /** Every published retail package (W4): /packages/<key> pages. */
  packages_index?: PackageItem[];
}

/** Pages every v2 site has without a spec page: Razorpay returns guests to /book/done, confirmations link /my-booking, and
 * /policies holds the cancellation, payment and house rules (sites app, drawn with the v1 parts). */
export const SYSTEM_PAGES: Record<string, string> = { "/policies": "Policies", "/book/done": "Your booking", "/my-booking": "My booking" };

export function isV2(live: LiveData | LiveDataV2): live is LiveDataV2 {
  return (live as LiveDataV2).spec_version === 2;
}

export function findPageV2(live: LiveDataV2, path: string): PageV2 | null {
  const clean = ("/" + path.replace(/^\/+|\/+$/g, "")).toLowerCase();
  return live.doc.pages.find(p => p.slug === clean) || null;
}

/** v1 pack variables from a v2 theme, for pages still drawn with v1 styles (the /links page, the enquiry form). */
export function kVars(live: LiveDataV2): Record<string, string> {
  const v = live.theme.vars;
  return { "--k-bg": v["--v-surface"], "--k-ink": v["--v-ink"], "--k-muted": v["--v-muted"], "--k-card": v["--v-surface"],
    "--k-line": v["--v-line"], "--k-a": v["--v-primary"], "--k-b": v["--v-primary"], "--k-b-ink": v["--v-on-primary"],
    "--k-soft": v["--v-surface-alt"], "--k-display": v["--v-display"], "--k-body": v["--v-body"], "--k-band": "none" };
}

export const txt = (v: unknown): string => (typeof v === "string" ? v : "");
