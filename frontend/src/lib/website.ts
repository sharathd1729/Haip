// Website builder API (backend/app/api/v1/endpoints/website.py). Shapes are hand-written next to their use.
import api from "@/lib/api";
import type { LiveData, SiteDoc } from "@/site-blocks/types";

export const WEB = "/websites";

export interface SiteSettings {
  booking_mode: "instant" | "deposit" | "request" | "enquiry"; deposit_percent: number; hold_minutes: number; balance_due_days: number;
  show_prices: boolean; prices_include_gst: boolean; property_ids: string[]; min_nights: number; max_advance_days: number;
}
export interface Domain { id: string; hostname: string; kind: "subdomain" | "custom"; status: string; error: string | null; verify_token: string | null; cname_target: string }
export interface SiteOut {
  id: string; name: string; slug: string; status: "draft" | "live" | "paused"; settings: SiteSettings; url: string;
  draft: { id: string; number: number; status: string; sha256: string; updated_at: string | null } | null;
  live: { id: string; number: number; published_at: string | null } | null;
  domains: Domain[];
}
export interface Check { key: string; ok: boolean; level: "ok" | "warn" | "block"; title: string; detail: string; fix: string | null }
export interface DraftOut {
  version: { id: string; number: number; status: string; sha256: string; origin: string; note: string | null; updated_at: string | null };
  doc: SiteDoc; problems: string[]; checks: Check[];
}
export interface VersionRow { id: string; number: number; status: string; origin: string; note: string | null; sha256: string;
  created_by: string | null; submitted_by: string | null; approved_by: string | null; published_at: string | null; updated_at: string | null }
export interface AiJob { id: string; kind: "edit" | "generate"; request: string | null; status: "pending" | "running" | "ready" | "failed";
  result: { reply: string; changes: string[]; refused: string[]; touched: string[] } | null; error: string | null; result_version_id: string | null; created_at: string | null }
export interface MediaItem { id: string; ref: string; url: string | null; alt_text: string | null; width: number | null; height: number | null; source: string }
export interface Analytics { days: number; views: { total: number; by_day: [string, number][]; top_pages: [string, number][]; sources: [string, number][] };
  website_leads: number; bookings: Record<string, { count: number; value?: string }>; money_restricted: boolean }

export const webApi = {
  site: () => api.get<SiteOut>(`${WEB}/site`).then(r => r.data),
  create: () => api.post<SiteOut>(`${WEB}/site`, {}).then(r => r.data),
  /** "Make my website": builds a full draft from HAIP data (creates the site if there is none). */
  make: () => api.post<{ site: SiteOut }>(`${WEB}/make`, {}).then(r => r.data.site),
  /** Sections left out because HAIP has no data for them yet, with what to add and where. */
  missing: () => api.get<{ items: { section: string; title: string; how: string; href: string }[] }>(`${WEB}/missing`).then(r => r.data.items),
  settings: (s: SiteSettings) => api.put<SiteOut>(`${WEB}/site/settings`, s).then(r => r.data),
  pause: (on: boolean) => api.post<SiteOut>(`${WEB}/site/${on ? "pause" : "resume"}`).then(r => r.data),
  draft: () => api.get<DraftOut>(`${WEB}/draft`).then(r => r.data),
  save: (doc: SiteDoc, base: string) => api.put<DraftOut>(`${WEB}/draft`, { doc, base_sha256: base }).then(r => r.data),
  live: () => api.get<LiveData>(`${WEB}/live-data`).then(r => r.data),
  versions: () => api.get<VersionRow[]>(`${WEB}/versions`).then(r => r.data),
  submit: (id: string, note?: string) => api.post<SiteOut>(`${WEB}/versions/${id}/submit`, { version_id: id, note }).then(r => r.data),
  publish: (id: string) => api.post<SiteOut>(`${WEB}/versions/${id}/publish`, { version_id: id }).then(r => r.data),
  reject: (id: string, note?: string) => api.post<SiteOut>(`${WEB}/versions/${id}/reject`, { version_id: id, note }).then(r => r.data),
  restore: (id: string) => api.post<DraftOut>(`${WEB}/versions/${id}/restore`).then(r => r.data),
  preview: () => api.get<{ url: string }>(`${WEB}/preview-link`).then(r => r.data),
  addDomain: (hostname: string) => api.post<SiteOut>(`${WEB}/domains`, { hostname }).then(r => r.data),
  verifyDomain: (id: string) => api.post<SiteOut>(`${WEB}/domains/${id}/verify`).then(r => r.data),
  removeDomain: (id: string) => api.delete<SiteOut>(`${WEB}/domains/${id}`).then(r => r.data),
  aiEdit: (message: string) => api.post<AiJob>(`${WEB}/ai/edit`, { message }).then(r => r.data),
  aiGenerate: (brief?: string) => api.post<AiJob>(`${WEB}/ai/generate`, { brief: brief || null }).then(r => r.data),
  aiJob: (id: string) => api.get<AiJob>(`${WEB}/ai/jobs/${id}`).then(r => r.data),
  aiJobs: () => api.get<AiJob[]>(`${WEB}/ai/jobs`).then(r => r.data),
  media: () => api.get<MediaItem[]>(`${WEB}/media`).then(r => r.data),
  upload: (file: File, alt?: string) => {
    const f = new FormData();
    f.append("file", file);
    if (alt) f.append("alt_text", alt);
    return api.post<MediaItem>(`${WEB}/media`, f).then(r => r.data);
  },
  analytics: (days = 30) => api.get<Analytics>(`${WEB}/analytics`, { params: { days } }).then(r => r.data),
};

export function webError(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string") return d === "Insufficient permissions" ? "Your role can't do that." : d;
  if (d && typeof d === "object") {
    const o = d as { message?: string; problems?: string[] };
    return [o.message, ...(o.problems || [])].filter(Boolean).join(" ") || fallback;
  }
  return fallback;
}

export function errorCode(e: unknown): string | undefined {
  const d = (e as { response?: { data?: { detail?: { code?: string; error?: string } } } })?.response?.data?.detail;
  return d?.code || d?.error;
}

export function statusOf(e: unknown): number | undefined {
  return (e as { response?: { status?: number } })?.response?.status;
}
