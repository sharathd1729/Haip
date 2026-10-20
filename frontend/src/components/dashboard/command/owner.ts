// The owner dashboard (layout A) part of GET /dashboard/business-overview (`owner`, backend services
// owner_dashboard_attention.py / owner_dashboard_blocks.py) and the pure helpers its cards share. Every number is computed on the
// server; these helpers only format it. A block the viewer may not read arrives as { restricted: true }; never shown as 0.
import type { Change, Restricted } from "./types";

export type Severity = "fresh" | "late" | "urgent" | "critical" | "stale";

export interface AttentionPerson { name: string; detail?: string; since?: string | null; facts?: string[]; href?: string | null;
  amount?: number | null; due_date?: string | null; overdue?: boolean; check_in?: string }
export interface AttentionCard {
  key: "not_replying" | "not_called" | "missed_calls" | "followups" | "at_risk" | "owing";
  title: string; reason?: string; count?: number; amount?: number | null; people?: AttentionPerson[]; href?: string;
  severity?: Severity; restricted: boolean;
}

export interface Kpi { count: number; previous: number; change: Change | null; basis: string; rate_of_new?: number | null }
export interface BookedValue { total: number; rental: number; add_ons: number; previous: number; change: Change | null; basis: string }
export interface Received { amount: number; previous: number; change: Change | null; refunds: number; basis: string }
export interface OwnerKpis {
  new_leads: Kpi; qualified: Kpi;
  bookings: Kpi | Restricted; booked_value: BookedValue | Restricted; payment_received: Received | Restricted;
}

export interface TargetBlock {
  restricted: false; month: string; from: string; to: string; days_in_month: number; days_elapsed: number; days_left: number;
  basis: string; available: boolean; reason?: string; href?: string;
  booked?: { total: number; rental: number; add_ons: number; count: number }; payment_received?: number; pace_pct?: number;
  target?: number; achieved_pct?: number; expected_by_today?: number; ahead_by?: number; to_go?: number;
}

export interface Movement { kind: "check_in" | "check_out"; date: string; days_from_today: number; guest: string; property: string;
  trip: string; href: string; status: string }
export interface Movements { restricted: false; window_days: number; from: string; to: string; check_ins: number; check_outs: number;
  items: Movement[]; truncated: boolean }

export interface TravelWeek { start: string | null; active: number; booked: number | null }
export interface Travel { weeks: TravelWeek[]; booked_restricted: boolean; active_basis: string; booked_basis: string }

export interface StageRow { key: string; label: string; category: string | null; won: boolean; lost: boolean; count: number }
export interface Stages { stages: StageRow[]; lost_by_reason: { reason: string; label: string; count: number }[]; unqualified: number; basis: string }

export interface Caravan { property_id: string; name: string; booked_value: number | null; nights: number; occupancy_pct: number | null }
export interface Caravans { restricted: false; month: string; days_in_month: number; items: Caravan[]; basis: string }

export interface AiCalls {
  sales_actions: { count: number; href: string; items: { name: string; package?: string | null; href: string }[] };
  autopilot: { count: number; href: string; by_stage: { label: string; count: number }[]; items: { name: string; to: string; reason: string; href: string }[] };
  calls: { total: number; missed: number; returned: number; not_returned: number; href: string };
}

export interface TeamRow { agent_id: string; name: string; target: number | null; achieved: number | null; achieved_pct: number | null;
  calls: number; leads_owned: number; median_first_reply_seconds: number | null }
export interface Team { month: string; from: string; to: string; rows: TeamRow[]; unattributed: number | null; basis: string }

export interface OwnerBlock {
  attention: AttentionCard[];
  kpis: OwnerKpis;
  target: TargetBlock | Restricted;
  movements: Movements | Restricted;
  travel: Travel;
  stages: Stages;
  caravans: Caravans | Restricted;
  ai_calls: AiCalls | null;
  team: Team | null;
  today: string;
}

export const restricted = (b: object | null | undefined): b is Restricted => !!b && (b as Restricted).restricted === true;

// ── helpers ───────────────────────────────────────────────────────────────────────────────────────────────────

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** ₹1,25,000 below a lakh is written in full; from a lakh up, "₹1.25 L" / "₹2 Cr" (Indian units, at most two decimals). */
export function lakh(n: number | null | undefined): string {
  if (n == null) return "—";
  const v = Math.abs(n), sign = n < 0 ? "-" : "";
  const short = (x: number) => x.toFixed(2).replace(/\.?0+$/, "");
  if (v >= 1e7) return `${sign}₹${short(v / 1e7)} Cr`;
  if (v >= 1e5) return `${sign}₹${short(v / 1e5)} L`;
  return `${sign}₹${INR.format(Math.round(v))}`;
}

/** "▲ 12% vs 10 before" — only with a real baseline. No baseline (0 or none) says so instead of a made-up percentage. */
export function deltaText(change: Change | null | undefined, previous: number | null | undefined, money = false): { text: string; tone: "up" | "down" | "flat" | "none" } {
  if (!change || !previous) return { text: "nothing to compare with before", tone: "none" };
  const prev = money ? lakh(previous) : INR.format(previous);
  if (change.direction === "neutral") return { text: `same as before (${prev})`, tone: "flat" };
  const arrow = change.direction === "up" ? "▲" : "▼";
  return { text: `${arrow} ${Math.abs(change.pct)}% vs ${prev} before`, tone: change.direction };
}

/** Bar geometry for the target card: rental and add-ons stacked, both as % of the target (capped at 100), and the pace marker. */
export function targetBars(t: Pick<TargetBlock, "target" | "booked" | "pace_pct">): { rental: number; addOns: number; pace: number; over: boolean } {
  const goal = t.target ?? 0, b = t.booked;
  if (!goal || !b) return { rental: 0, addOns: 0, pace: Math.min(100, t.pace_pct ?? 0), over: false };
  const rental = Math.min(100, (b.rental / goal) * 100);
  const addOns = Math.min(100 - rental, (b.add_ons / goal) * 100);
  return { rental, addOns, pace: Math.min(100, t.pace_pct ?? 0), over: b.total > goal };
}

/** "3h", "2d" since an ISO time; "" when unknown. */
export function ageText(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const m = Math.floor((now - new Date(iso).getTime()) / 60000);
  if (!Number.isFinite(m) || m < 0) return "";
  if (m < 60) return `${Math.max(1, m)}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

/** "Today" / "Tomorrow" / "In 6 days". */
export function whenText(days: number): string {
  return days <= 0 ? "Today" : days === 1 ? "Tomorrow" : `In ${days} days`;
}

/** Week bucket label: "This week", "Next week", "26 Oct", ..., "Later" (start null). */
export function weekLabel(start: string | null, index: number): string {
  if (!start) return "Later";
  if (index === 0) return "This week";
  if (index === 1) return "Next week";
  return new Date(`${start}T12:00:00+05:30`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
}

/** "October" for "2026-10-01". */
export function monthName(iso: string): string {
  return new Date(`${iso}T12:00:00+05:30`).toLocaleDateString("en-IN", { month: "long", timeZone: "Asia/Kolkata" });
}

/** "1–31 Oct" for a month or part of one. */
export function dayRange(from: string, to: string): string {
  const f = new Date(`${from}T12:00:00+05:30`), t = new Date(`${to}T12:00:00+05:30`);
  const mon = t.toLocaleDateString("en-IN", { month: "short", timeZone: "Asia/Kolkata" });
  return from === to ? `${t.getDate()} ${mon}` : `${f.getDate()}–${t.getDate()} ${mon}`;
}
