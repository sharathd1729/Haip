// SiteSpec v2 types: a hand mirror of backend/app/schemas/site_spec.py (change both together). spec.json is a copy of
// backend/app/services/website_spec_v2.json (backend tests compare them). The server validates the spec and binds every
// section's data (website_bindings.py); this folder only renders what it is given.
import catalogue from "./spec.json";
import type { LiveData } from "../types";

export type SectionType = "hero" | "packages" | "itinerary" | "gallery" | "reviews" | "faq" | "contact" | "booking-cta";

export const CATALOGUE = catalogue as unknown as {
  spec_version: 2;
  sections: Record<SectionType, { label: string; variants: string[]; source: string }>;
  palettes: Record<string, { label: string; ink: string; surface: string; primary: string; accent: string }>;
  fonts: { display: Record<string, { family: string; stack: string }>; body: Record<string, { family: string; stack: string }> };
};

export interface WaLink { code: string; href: string }
export interface Contact { phone: string; whatsapp: string; email: string; address: string }

export interface SectionV2 { id: string; type: SectionType; variant: string; slots: Record<string, unknown>; source: string }
export interface PageV2 { slug: string; title: string; nav: boolean; seo: { title: string; description: string }; sections: SectionV2[] }
export interface SpecV2 {
  spec_version: 2;
  site: { name: string; tagline: string; ref_prefix: string | null; contact: Contact; social: Record<string, string> };
  tokens: { palette: { name: string; ink: string; surface: string; primary: string; accent: string }; display: string; body: string;
    radius: "soft" | "sharp" | "pill"; motion: "calm" };
  pages: PageV2[];
}

export interface PackageItem {
  key: string; name: string; summary: string; length: string; inclusions: string[]; days: string[]; destinations: string[];
  max_guests: number; price: { amount: string; label: string } | null; price_label: string | null; wa: WaLink | null;
}
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
  assets: LiveData["assets"];
  legal: LiveData["legal"];
}

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
