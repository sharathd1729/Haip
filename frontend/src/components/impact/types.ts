// Hand-written types for GET /dashboard/impact (backend/app/services/impact_service.py). Change both together.
import { duration, inr, num, pct } from "@/components/dashboard/command/types";

export type Unit = "minutes" | "%" | "count" | "inr";
export interface Period { from: string; to: string; days: number }
export interface Change { kind: "points" | "pct"; value: number; better: boolean | null }
export interface OwnerBaseline { metric: string; value: number; period_label: string; source_note: string | null; updated_at: string | null; source: "owner_entered" }

interface TileBase { key: string; label: string; unit: Unit; definition: string; lower_is_better: boolean }
export type Tile = (TileBase & { restricted: true }) | (TileBase & {
  restricted: false;
  before: { owner: OwnerBaseline | null; measured: { value: number | null; n: number | null; period: Period } };
  with: { value: number | null; n: number | null; period: Period };
  change: Change | null;
  change_against: "owner_entered" | "measured" | null;
});

export interface ReplySummary {
  turns: number; answered: number; unanswered: number; answered_pct: number | null;
  median_seconds: number | null; p90_seconds: number | null; within_pct: Record<"5" | "15" | "60", number | null>;
}
export interface ResponderSummary { answered: number; median_seconds: number | null; p90_seconds: number | null; within_15_pct: number | null }
export type ChannelKey = "whatsapp_cloud" | "personal_whatsapp" | "instagram";
export type ResponderKey = "ai" | "staff_ai_draft" | "staff";

export interface WindowMeasure {
  period: Period;
  replies: {
    all: ReplySummary; by_channel: Record<ChannelKey, ReplySummary>; by_responder: Record<ResponderKey, ResponderSummary>;
    after_hours: { turns: number; answered: number; within_15_pct: number | null; answered_by_ai: number; ai_share_pct: number | null; median_seconds: number | null };
    excluded_too_recent: number; truncated: boolean;
  };
  funnel: { enquiries: number; leads: number; quoted: number; booked: number; lead_to_quote_pct: number | null; lead_to_booking_pct: number | null };
  new_leads: number;
  missed_calls: { missed: number; returned: number; returned_pct: number | null; median_callback_seconds: number | null; within_60_pct: number | null };
  lost: { total: number; by_reason: { reason: string; label: string; count: number }[] };
}

export interface RevenueMonth { month: string; from: string; to: string; bookings: number; booked_value: number; collected: number; refunded: number }

export type ImpactView = {
  saved: { go_live: string | null; days: number }; can_edit: boolean; can_revenue: boolean; days: number; tenant_name: string;
} & ({ needs_go_live: true; go_live: null } | {
  needs_go_live: false; go_live: string; windows: { before: Period; with: Period }; generated_at: string;
  tiles: Tile[]; before: WindowMeasure; with: WindowMeasure; notes: string[];
  revenue: { restricted: true } | { restricted: false; months: RevenueMonth[]; go_live_month: string };
});

export interface BaselineRow { metric: string; label: string; unit: Unit; definition: string; restricted: boolean; baseline?: OwnerBaseline | null }

export interface CaseStudyStatus {
  status: "draft" | "published" | "withdrawn"; slug: string | null; published_at: string | null; can_edit: boolean;
  snapshot: PublicSnapshot | null;
}

export interface PublicTile {
  key: string; label: string; unit: Unit; definition: string;
  before: { value: number; source: "owner_entered" | "measured"; period: string } | null;
  with: { value: number; period: string }; change: Change | null;
}
export interface PublicSnapshot {
  version: number; brand_name: string; headline: string | null; summary: string | null; go_live: string;
  windows: { before: Period; with: Period }; tiles: PublicTile[];
  channels: { channel: ChannelKey; label: string; turns: number; answered_pct: number | null; median_minutes: number | null; within_15_pct: number | null }[];
  after_hours: { turns: number; within_15_pct: number | null; ai_share_pct: number | null };
  includes_revenue: boolean; measured_through: string;
}

export const CHANNEL_LABELS: Record<ChannelKey, string> = {
  whatsapp_cloud: "WhatsApp (business number)", personal_whatsapp: "WhatsApp (team phones)", instagram: "Instagram",
};
export const RESPONDER_LABELS: Record<ResponderKey, string> = {
  ai: "AI on its own", staff_ai_draft: "Staff sending an AI draft", staff: "Staff",
};

/** A tile value in its unit; null stays "—" (nothing to measure), never 0. */
export function formatValue(value: number | null | undefined, unit: Unit): string {
  if (value == null) return "—";
  if (unit === "minutes") return duration(value * 60);
  if (unit === "%") return pct(value);
  if (unit === "inr") return inr(value);
  return num(value);
}

/** "-96%" / "+30 pts" with whether it is an improvement. Null when there is no real baseline: never "-100%" against nothing. */
export function formatChange(change: Change | null | undefined): { text: string; tone: "success" | "danger" | "neutral" } | null {
  if (!change) return null;
  const sign = change.value > 0 ? "+" : change.value < 0 ? "−" : "";
  const abs = Math.abs(change.value);
  const text = change.kind === "points" ? `${sign}${abs.toFixed(abs % 1 ? 1 : 0)} pts` : `${sign}${abs.toFixed(abs % 1 ? 1 : 0)}%`;
  return { text, tone: change.better == null ? "neutral" : change.better ? "success" : "danger" };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-01" -> "1 Sep 2026". Dates here are IST calendar days, so no timezone conversion. */
export function formatDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function formatPeriod(p: { from: string; to: string }): string {
  return `${formatDay(p.from)} – ${formatDay(p.to)}`;
}

/** "2026-09" -> "Sep 2026" */
export function formatMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}
