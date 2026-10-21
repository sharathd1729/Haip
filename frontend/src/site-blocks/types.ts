// Shared by the HAIP editor (frontend/) and the sites renderer (sites/, which copies this folder at build time).
// Keep this folder free of app imports: only React, lucide-react and files in this folder.
import spec from "./blocks.json";

export type Spec = typeof spec;
export type BlockType = keyof Spec["blocks"];
export const SPEC = spec as unknown as {
  version: number; packs: string[]; personalities: string[]; backgrounds: string[]; icons: string[]; review_sources: string[];
  system_pages: Record<string, { path: string; title: string; required?: boolean; system?: boolean; template?: boolean; block?: string }>;
  blocks: Record<string, BlockSpec>;
};

export interface FieldSpec {
  key: string; label: string; kind: "text" | "textarea" | "lines" | "toggle" | "select" | "tags" | "link" | "date" | "image" | "images" | "list";
  max?: number; max_items?: number; required?: boolean; options?: string[]; options_from?: string; item?: FieldSpec[];
}
export interface BlockSpec { label: string; desc: string; layouts?: string[]; live?: string; system?: boolean; fields: FieldSpec[] }

export type Props = Record<string, unknown> & { id: string; layout?: string; background?: string };
export interface Block { type: string; props: Props }
export interface Page { id: string; key: string; title: string; path: string; nav: boolean; seo: { title: string; description: string }; content: Block[] }
export interface SiteDoc {
  schema: number;
  theme: { pack: string; personality: string };
  site: { name: string; tagline: string; logo: string; contact: { phone: string; whatsapp: string; email: string; address: string }; social: Record<string, string> };
  pages: Page[];
}

export interface Stay {
  id: string; slug: string; name: string; type: string; sleeps: number; max_adults: number; bedrooms?: number | null; bathrooms?: number | null;
  city: string; photos: string[]; amenities: string[]; summary: string; from_price?: string | null;
  description?: string; faqs?: { q: string; a: string }[]; extras?: { id: string; name: string; description: string; category: string; price: string | null; price_type: string }[];
  lat?: number | null; lng?: number | null; address?: string;
}

export interface LiveData {
  site: { id: string; name: string; status: string; preview: boolean; booking_mode: "instant" | "deposit" | "request" | "enquiry";
    deposit_percent: number; show_prices: boolean; hold_minutes: number; min_nights: number; prices_include_gst: boolean; today: string };
  version: { id: string; number: number; sha256: string };
  doc: SiteDoc;
  stays: Stay[];
  assets: Record<string, { src: string; alt: string; w?: number | null; h?: number | null }>;
  policies: { cancellation_policy?: { tiers: { days_before: number; refund_percent: number }[]; non_refundable_items?: string[] };
    payment_policy?: { advance_percent: number; balance_due_days_before_checkin: number; accepted_methods?: string[] };
    stay_rules?: { check_in_time: string; check_out_time: string; house_rules?: string[]; id_required?: boolean; min_age?: number | null } };
  legal: { legal_name: string; gstin: string | null; address: string | null };
}

/** Plain data (it crosses the server -> client boundary in the sites app). Use hrefOf / imageOf / callApi. */
export interface SiteEnv {
  mode: "live" | "preview" | "editor";
  base: string;                       // prefix for internal links: "" on the live site, "/_haip/preview/<token>" in a preview
  apiBase: string | null;             // guest API base ("/_haip/api"); null in the editor and previews: nothing is sent
  assets: Record<string, { src: string; alt: string }>;
  stay?: Stay | null;                 // the stay a StayDetail page is about
  query?: Record<string, string>;
}

export function hrefOf(env: SiteEnv, path: string): string {
  if (!path.startsWith("/")) return path;
  const [p, q] = path.split("?");
  return `${env.base}${p === "/" && env.base ? "" : p}${q ? `?${q}` : ""}` || "/";
}

export function imageOf(env: SiteEnv, ref: unknown): { src: string; alt: string } | null {
  if (typeof ref !== "string" || !ref.startsWith("asset:")) return null;
  return env.assets[ref.slice(6)] || null;
}

export function callApi(env: SiteEnv, path: string, init?: { method?: string; body?: unknown }): Promise<Response> {
  if (!env.apiBase) return Promise.reject(new Error("offline"));
  return fetch(env.apiBase + path, {
    method: init?.method || "GET",
    headers: init?.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
}

export const str = (v: unknown): string => (typeof v === "string" ? v : "");
export const arr = <T = string>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
export const bool = (v: unknown): boolean => v === true;

export function inr(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "";
  return "₹" + Math.round(n).toLocaleString("en-IN");
}
