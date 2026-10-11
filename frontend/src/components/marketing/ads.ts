// Shapes and small helpers for the Marketing (Meta ads) page. Mirrors backend/app/services/meta_ads_service.py.
import { formatINR } from "@/lib/utils";
import type { Tone } from "@/components/ui/kit";

export interface Backfill {
  state: "queued" | "running" | "done" | "stopped";
  started_at?: string; finished_at?: string; months?: number; total?: number; done?: number; rows?: number;
  failed?: { from: string; to: string; error: string }[]; stopped_because?: string | null;
}
export interface AdsStatus {
  configured: boolean; has_token: boolean; token_source: string | null;
  ad_account: { id: string; name: string | null; currency: string | null } | null;
  last_synced_at: string | null; last_error: string | null; backfill: Backfill | null; earliest_data: string | null;
}
export interface Audience { ages: string | null; genders: string[]; places: string[]; interests: string[]; platforms: string[] }
export interface Creative { title?: string; body?: string; thumbnail_url?: string; image_url?: string; call_to_action_type?: string; object_type?: string }
export interface Measures {
  spend: number; impressions: number; clicks: number; link_clicks: number; post_engagement: number; video_views: number;
  first_replies: number; meta_conversations: number;
  ctr: number | null; cpm: number | null; cpc: number | null; cost_per_conversation: number | null;
}
export interface Status {
  status?: string | null; effective_status?: string | null; objective?: string | null; optimization_goal?: string | null;
  daily_budget?: number | null; lifetime_budget?: number | null; starts_at?: string | null; ends_at?: string | null;
}
export interface Results { haip_leads: number; bookings: number; revenue: number; cost_per_lead: number | null; roas: number | null }
export interface AdDetail extends Measures, Status, Results {
  ad_id: string; name: string; adset_id?: string; adset_name?: string; creative?: Creative | null; audience?: Audience | null;
}
export interface Campaign extends Measures, Status, Results {
  campaign_id: string; campaign_name: string; ads: number; ad_details: AdDetail[]; haip_conversations: number;
}
export interface Summary {
  since: string; until: string; days: number; currency: string;
  totals: Measures & Results & { haip_conversations: number; attribution_gap: number };
  campaigns: Campaign[];
  daily: { date: string; spend: number; conversations: number; impressions: number; clicks: number }[];
}
export interface AdAccount { id: string; name: string; currency: string; status: number | null }

export const num = (n: number | null | undefined) => (n == null ? "—" : new Intl.NumberFormat("en-IN").format(n));
export const money = (n: number | null | undefined) => (n == null ? "—" : formatINR(n));
export const money2 = (n: number | null | undefined) =>
  n == null ? "—" : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(n);
export const pct = (n: number | null | undefined) => (n == null ? "—" : `${n.toFixed(2)}%`);
export const times = (n: number | null | undefined) => (n == null ? "—" : `${n.toFixed(1)}×`);
export const shortDate = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
export const longDate = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

/** Meta's status words, in words an owner uses. Colour only reinforces the label. */
export function statusLabel(s?: string | null): { label: string; tone: Tone } | null {
  if (!s) return null;
  if (s === "ACTIVE") return { label: "Running", tone: "success" };
  if (s.includes("PAUSED")) return { label: "Paused", tone: "neutral" };
  if (s === "ARCHIVED" || s === "DELETED") return { label: s === "DELETED" ? "Deleted" : "Archived", tone: "neutral" };
  if (s === "DISAPPROVED" || s === "WITH_ISSUES") return { label: "Needs attention", tone: "danger" };
  if (s === "IN_PROCESS" || s === "PENDING_REVIEW" || s === "PENDING_BILLING_INFO") return { label: s === "PENDING_BILLING_INFO" ? "Billing needed" : "In review", tone: "warning" };
  return { label: s.replace(/_/g, " ").toLowerCase().replace(/^\w/, c => c.toUpperCase()), tone: "info" };
}

export const OBJECTIVES: Record<string, string> = {
  OUTCOME_ENGAGEMENT: "Engagement", OUTCOME_TRAFFIC: "Traffic", OUTCOME_LEADS: "Leads", OUTCOME_SALES: "Sales",
  OUTCOME_AWARENESS: "Awareness", OUTCOME_APP_PROMOTION: "App installs", MESSAGES: "Messages",
};
export const objectiveLabel = (o?: string | null) => (o ? OBJECTIVES[o] ?? o.replace(/^OUTCOME_/, "").replace(/_/g, " ").toLowerCase().replace(/^\w/, c => c.toUpperCase()) : null);

export function budgetLabel(s: Status): string | null {
  if (s.daily_budget) return `${formatINR(s.daily_budget)} a day`;
  if (s.lifetime_budget) return `${formatINR(s.lifetime_budget)} in total`;
  return null;
}

export function errorText(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 2) return "just now";
  if (m < 60) return `${m} minutes ago`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h} hours ago` : `${Math.floor(h / 24)} days ago`;
}
