// Google surfaces (backend endpoints/website_google.py, numbers from services/google_metrics.py; KPI catalogue section 18).
// Every number may be null = "No data" (never shown as 0); change_pct is null when there is nothing to compare with.
import api from "@/lib/api";

const G = "/websites/google";

export type Pull = { last_ok_at?: string | null; last_error?: string | null; failures?: number; backoff_until?: string | null };
export type SpeedSide = { verdict: string | null; whole_site: boolean; lcp_ms: number | null; inp_ms: number | null;
  cls: number | null; lab_score: number | null } | null;
export type Speed = { configured: boolean; week_of: string | null;
  pages: { label: string | null; url: string; mobile?: SpeedSide; desktop?: SpeedSide; mobile_error?: string }[] };
export type GoogleSummary = {
  period: { days: number; from: string; to: string; previous_from: string; previous_to: string };
  data_through: { business_profile: string | null; search_console: string | null };
  visibility: { business_profile: number | null; search_results: number | null; total: number | null;
    previous_total: number | null; change_pct: number | null;
    by_surface: Record<"search_mobile" | "search_desktop" | "maps_mobile" | "maps_desktop", number> | null };
  actions: { website_clicks: number | null; calls: number | null; directions: number | null; messages: number | null;
    search_clicks: number | null; total: number | null; previous_total: number | null; change_pct: number | null };
  money_queries: { query: string; position: number | null; previous: number | null; clicks: number | null;
    impressions: number | null; weeks: { week_from: string; position: number | null }[] }[];
  speed: Speed;
  labels: Record<string, string>;
};
export type SearchConsoleStatus = { available: boolean; connected: boolean; property: string | null;
  properties: { site_url: string; permission: string | null }[]; sitemap_submitted: string | null;
  sitemap_problem: string | null; money_queries: string[]; pull: Pull };
export type GoogleOverview = {
  search_console: SearchConsoleStatus;
  business_profile: { available: boolean; connected: boolean; locations: number; pull: Pull };
  pagespeed: { configured: boolean };
  summary: GoogleSummary;
};

export const googleApi = {
  overview: (days = 28) => api.get<GoogleOverview>(G, { params: { days } }).then(r => r.data),
  property: (property: string) => api.put<SearchConsoleStatus>(`${G}/search-console/property`, { property }).then(r => r.data),
  moneyQueries: (queries: string[]) => api.put<SearchConsoleStatus>(`${G}/money-queries`, { queries }).then(r => r.data),
  disconnect: () => api.delete(`${G}/search-console`).then(r => r.data),
  refresh: () => api.post(`${G}/refresh`).then(r => r.data),
};

/** "1,240" or "No data". */
export const num = (n: number | null | undefined) => (n == null ? "No data" : n.toLocaleString("en-IN"));

/** Position change in words: lower position = better. null when either side is unknown. */
export function positionChange(cur: number | null, prev: number | null): { text: string; tone: "success" | "danger" | "neutral" } | null {
  if (cur == null || prev == null) return null;
  const d = Math.round((prev - cur) * 10) / 10;
  if (d === 0) return { text: "no change", tone: "neutral" };
  return d > 0 ? { text: `up ${d}`, tone: "success" } : { text: `down ${-d}`, tone: "danger" };
}

export function pctChange(p: number | null): { text: string; tone: "success" | "danger" | "neutral" } | null {
  if (p == null) return null;
  return { text: `${p > 0 ? "+" : ""}${p}% vs previous`, tone: p > 0 ? "success" : p < 0 ? "danger" : "neutral" };
}

export const VERDICT: Record<string, string> = { FAST: "Fast", AVERAGE: "Needs work", SLOW: "Slow" };
