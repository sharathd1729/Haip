// Website art director API (backend/app/api/v1/endpoints/website_builder.py). Shapes mirror
// backend/app/schemas/site_builder.py and website_builder_service.state(); hand-written, change both together.
import api from "@/lib/api";

const B = "/websites/builder";
export type StepKey = "sitemap" | "wireframe" | "style";
export type JobStatus = "pending" | "running" | "ready" | "failed" | "approved";

export interface BriefOwner { goals: string[]; audience: string; tone: string; must_haves: string[]; avoid: string[] }
export interface BriefFacts {
  business: { name: string; type: string | null; tagline: string; description: string; usps: string[]; languages: string[] };
  location: { city: string; region: string; address: string };
  contact: { phone: string; whatsapp: string; email: string; address: string };
  brand_kit: { primary: string | null; accent: string | null; font: string | null; has_logo: boolean };
  price_policy: "handoff" | "grounded";
  packages: { key: string; name: string; length: string; summary: string; destinations: string[] }[];
  destinations: { key: string; name: string }[];
  itineraries: { key: string; name: string; nights: number; days: number }[];
  stays: { name: string; type: string | null; city: string | null; sleeps: number }[];
  content: { faq_questions: string[]; faq_count: number; approved_photos: number; reviews_usable: number; reviews_rated: number; average_rating: number | null };
  guests_last_year: { enquiries: number; occasions?: Record<string, number>; top_cities?: string[]; average_adults?: number | null; share_with_children?: number };
}

export interface SitemapArt { note: string; pages: { slug: string; title: string; nav: boolean; reason: string; sections: { type: string; reason: string }[] }[] }
export interface WireSection { id: string; type: string; variant: string; eyebrow?: string | null; heading?: string | null; headline?: string | null;
  subhead?: string | null; intro?: string | null; text?: string | null; cta_label?: string | null }
export interface WireframeArt { note: string; pages: { slug: string; title: string; nav: boolean; seo_title: string; seo_description: string; sections: WireSection[] }[] }
export interface Direction { name: string; mood: string; sample_headline: string;
  tokens: { palette: { name: string; ink: string; surface: string; primary: string; accent: string }; display: string; body: string; radius: "soft" | "sharp" | "pill"; motion: "calm" } }
export interface StyleArt { note: string; directions: Direction[] }

export interface Job { id: string; kind: StepKey | "copy"; status: JobStatus; feedback: string | null; error: string | null;
  artifact: unknown; picked: number | null; attempts: number | null; version_id: string | null; model: string | null; created_at: string | null }
export interface BuilderState {
  brief: { facts: BriefFacts; owner: BriefOwner } | null; brief_id: string | null;
  steps: Record<StepKey, { latest: Job | null; approved_id: string | null; can_run: boolean }>;
  next: "brief" | StepKey | "done"; draft_version_id: string | null; busy: boolean;
}

export const builderApi = {
  state: () => api.get<BuilderState>(B).then(r => r.data),
  facts: () => api.get<BriefFacts>(`${B}/brief/facts`).then(r => r.data),
  saveBrief: (owner: BriefOwner) => api.post<BuilderState>(`${B}/brief`, { owner }).then(r => r.data),
  run: (step: StepKey, feedback?: string) => api.post<BuilderState>(`${B}/steps/${step}/run`, { feedback: feedback || null }).then(r => r.data),
  approve: (step: StepKey, job_id: string) => api.post<BuilderState>(`${B}/steps/${step}/approve`, { job_id }).then(r => r.data),
  pick: (job_id: string, index: number) =>
    api.post<BuilderState & { version: { id: string; number: number } }>(`${B}/style/pick`, { job_id, index }).then(r => r.data),
};

export const SECTION_LABEL: Record<string, string> = {
  hero: "Hero", packages: "Packages", itinerary: "Itinerary", gallery: "Gallery", reviews: "Reviews", faq: "FAQ",
  contact: "Contact and map", "booking-cta": "Booking call to action",
};

/** "one, two" <-> ["one", "two"] for the brief's list fields (one item per line). */
export const toLines = (v: string): string[] => v.split("\n").map(x => x.trim()).filter(Boolean);
