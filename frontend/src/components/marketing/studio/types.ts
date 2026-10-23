// Marketing Studio API shapes (backend/app/api/v1/endpoints/marketing_studio.py) and small shared helpers.
import type { Tone } from "@/components/ui/kit";
import { getToken } from "@/lib/api";

export const STUDIO = "/marketing/studio";

/** A Studio section by its tab value; the page reads ?tab= (deep links from the setup checklist and banners). */
export const studioHref = (tab: string) => `/dashboard/marketing/studio?tab=${encodeURIComponent(tab)}`;

/** Open a backend OAuth start page (Facebook, Google, Canva, Instagram). Those pages take the HAIP token as ?token=
 *  because they are plain browser links; fetch a FRESH one first (the session refreshes it), so an old tab never lands
 *  on a raw 401 page. */
export async function openOAuth(path: string, newTab = false): Promise<void> {
  const tab = newTab ? window.open("", "_blank") : null;      // opened inside the click, or the browser blocks it
  const token = await getToken(true);
  const raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
  const base = raw.endsWith("/api/v1") ? raw : `${raw}/api/v1`;
  const url = token ? `${base}${path}?token=${encodeURIComponent(token)}` : "/login";
  if (tab) tab.location.href = url;
  else window.location.assign(url);
}

export type Kind = "post" | "carousel" | "story" | "promo" | "reel";
export type ItemStatus = "draft" | "in_review" | "approved" | "rejected" | "archived" | "scheduled" | "published";

export interface Version {
  id: string; version: number; payload: Record<string, unknown>; sha256: string; origin: "ai" | "human";
  note: string | null; prompt_version: string | null; model: string | null; created_by: string | null; created_at: string;
}

export interface Decision {
  id: string; version_id: string; decision: "submitted" | "approved" | "rejected" | "withdrawn";
  note: string | null; actor_user_id: string; created_at: string;
}

export interface ContentItem {
  id: string; kind: Kind; channel: string; title: string; status: ItemStatus; property_id: string | null;
  plan_id: string | null; planned_for: string | null; current_version_id: string | null; approved_version_id: string | null;
  generation_status: "idle" | "pending" | "failed"; generation_error: string | null; created_by: string | null;
  created_at: string; updated_at: string;
  current?: Version | null; versions?: Version[]; decisions?: Decision[];
  /** Drafts only: 1-based slots without a library photo. Non-empty = "Needs photos" (the server refuses to submit). */
  needs_photos?: number[];
  /** Approved items only: why autopilot could not schedule it (latest try). */
  auto_schedule_error?: string | null;
}

export interface Finding {
  area: string; observation: string; metric_keys: string[]; recommendation: string; priority: "high" | "medium" | "low";
}

export interface Baseline {
  posts_counted: number; enough_signal: boolean; min_posts: number; medians: Record<string, number | null>;
  by_post: { media_id: string; media_type: string | null; multiples: Record<string, number> }[];
  by_media_type: Record<string, { posts: number; median_reach: number | null; median_interactions: number | null }>;
}

export interface Measured {
  source: string; available: boolean; captured_at: string | null;
  account: Record<string, number | null>; posts: Record<string, unknown>[]; baseline?: Baseline;
}

export interface Audit {
  id: string; status: "pending" | "ready" | "failed"; error: string | null; measured: Measured;
  assessment: {
    summary: string; strengths: string[]; findings: Finding[];
    stop?: string[]; keep?: string[]; test?: string[]; not_enough_signal?: string[];
  } | null;
  prompt_version: string | null; model: string | null; created_at: string;
}

export interface CalendarEntry {
  date: string; kind: Kind; pillar: string; idea: string;
  targets?: string | null; campaign?: string | null; bucket?: "proven" | "new" | "experimental" | null;
  indicator?: string | null; stop_if?: string | null;
}

export interface DemandGap { property: string; properties?: string[]; start: string; end: string; nights: number; why: string[]; days_away: number }
export interface Demand {
  from: string; to: string; state: string | null; gaps: DemandGap[];
  occasions: { date: string; day: string; name: string; kind: "public" | "festival" }[];
  long_weekends: { start: string; end: string; days: number; leave_days: number; reason: string }[];
}

export interface Plan {
  id: string; status: "pending" | "ready" | "failed" | "archived"; error: string | null; period_start: string; period_end: string;
  brief: string | null; audit_id: string | null; created_at: string;
  body: {
    goals: string[]; audience: string; pillars: string[]; cadence: string; calendar: CalendarEntry[];
    position?: string | null; rotation?: string | null; out_of_scope?: string[];
    campaigns?: { name: string; goal: string; targets?: string | null; channels?: string[] }[];
    reactive_days?: string[]; demand?: Demand | null;
  } | null;
}

export interface Asset {
  id: string; url: string | null; mime_type: string; width: number | null; height: number | null; bytes: number;
  alt_text: string | null; source: "upload" | "template" | "ai" | "instagram" | "canva"; created_at: string;
  status?: "active" | "pending_review" | "archived"; created_by?: string | null; provenance?: Record<string, unknown> | null;
  tags?: PhotoTags | null; people_ok?: boolean; duration_ms?: number | null;
}

/** What the vision model saw in a library photo (agency M2). */
export interface PhotoTags {
  subjects: string[]; light: string; season: string; people: boolean; text_or_logo: boolean; quality: number;
  mood: string[]; description: string;
}

export const KIND_LABEL: Record<Kind, string> = { post: "Post", carousel: "Carousel", story: "Story", promo: "Promo", reel: "Reel" };

export const STATUS: Record<ItemStatus, { label: string; tone: Tone }> = {
  draft: { label: "Draft", tone: "neutral" },
  in_review: { label: "Waiting for approval", tone: "warning" },
  approved: { label: "Approved", tone: "success" },
  rejected: { label: "Changes asked", tone: "danger" },
  archived: { label: "Archived", tone: "neutral" },
  scheduled: { label: "Scheduled", tone: "info" },
  published: { label: "Posted", tone: "success" },
};

/** The backend sends {detail: {code, message, problems[]}} for its own errors and {detail: string} for auth/permission ones. */
export function studioError(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string") return d === "Insufficient permissions" ? "Your role can't do that." : d;
  if (d && typeof d === "object") {
    const o = d as { message?: string; problems?: string[] };
    return [o.message, ...(o.problems ?? [])].filter(Boolean).join(" ") || fallback;
  }
  return fallback;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

export function day(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  return new Date(`${isoDate}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "numeric", month: "short" });
}

export const inputCls =
  "w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2 text-base text-[var(--haip-fg)] " +
  "placeholder:text-[var(--haip-fg-subtle)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)] sm:text-sm";

export const btn =
  "inline-flex min-h-11 items-center justify-center rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3.5 " +
  "text-[13px] font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-50 sm:min-h-9";

export const btnPrimary =
  "inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-3.5 text-[13px] font-semibold " +
  "text-primary-foreground hover:opacity-90 disabled:opacity-50 sm:min-h-9";
