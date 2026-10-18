// Marketing Studio API shapes (backend/app/api/v1/endpoints/marketing_studio.py) and small shared helpers.
import type { Tone } from "@/components/ui/kit";

export const STUDIO = "/marketing/studio";

export type Kind = "post" | "carousel" | "story" | "promo";
export type ItemStatus = "draft" | "in_review" | "approved" | "rejected" | "archived";

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

export interface CalendarEntry { date: string; kind: Kind; pillar: string; idea: string }

export interface Plan {
  id: string; status: "pending" | "ready" | "failed" | "archived"; error: string | null; period_start: string; period_end: string;
  brief: string | null; audit_id: string | null; created_at: string;
  body: {
    goals: string[]; audience: string; pillars: string[]; cadence: string; calendar: CalendarEntry[];
    position?: string | null; rotation?: string | null; out_of_scope?: string[];
  } | null;
}

export interface Asset {
  id: string; url: string | null; mime_type: string; width: number | null; height: number | null; bytes: number;
  alt_text: string | null; source: "upload" | "template" | "ai" | "instagram"; created_at: string;
}

export const KIND_LABEL: Record<Kind, string> = { post: "Post", carousel: "Carousel", story: "Story", promo: "Promo" };

export const STATUS: Record<ItemStatus, { label: string; tone: Tone }> = {
  draft: { label: "Draft", tone: "neutral" },
  in_review: { label: "Waiting for approval", tone: "warning" },
  approved: { label: "Approved", tone: "success" },
  rejected: { label: "Changes asked", tone: "danger" },
  archived: { label: "Archived", tone: "neutral" },
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
