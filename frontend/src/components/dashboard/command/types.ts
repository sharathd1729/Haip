// Shape of GET /dashboard/business-overview (backend/app/services/business_overview_service.py) and the few
// formatting helpers the Owner Command Center shares. Business numbers are computed on the server; nothing here
// derives a KPI. A figure the viewer may not see arrives as `null` inside a block marked `restricted`; a figure HAIP
// cannot compute arrives as `{ available: false, reason }`. Neither is ever shown as 0.

export interface Change { pct: number; direction: "up" | "down" | "neutral" }
export interface Unavailable { available: false; reason: string }
export interface Restricted { restricted: true }

export interface FunnelStage {
  key: "received" | "valid" | "booked" | "paid";
  label: string;
  count: number;
  previous: number;
  rate_from_previous: number | null;
  change: Change | null;
}

export interface LeadsBlock {
  received: number; received_change: Change | null;
  valid: number; invalid: number; marked_spam_excluded: number;
  converted_to_booking: number; conversion_rate: number | null; conversion_basis: string;
  unassigned_now: number;
}

export interface BookingsBlock {
  restricted: false;
  confirmed_created: number; confirmed_change: Change | null;
  cancelled_of_created: number;
  pending: Unavailable;
  upcoming_checkins: number; upcoming_window_days: number;
  needs_payment: number; payment_overdue: number; needs_payment_truncated: boolean;
  not_linked_to_a_lead: number | null;
  basis: string;
}

export interface Target {
  available: true; month: string; monthly_target: number; picked_up: number; achieved_pct: number | null; basis: string;
}

export interface RevenueBlock {
  restricted: false;
  gross_booking_value: number | null; gross_change: Change | null;
  add_ons_value: number | null; arriving_value: number | null;
  collected: number | null; collected_change: Change | null;
  refunds: number | null; net_collected: number | null;
  outstanding_on_live_bookings: number | null; overdue_amount: number | null;
  net_revenue: Unavailable;
  target: Target | Unavailable | null;
  basis: string;
}

export interface SeriesBlock {
  days: string[];
  period_start_index: number;
  leads: number[];
  bookings: number[] | null;
  booking_value: number[] | null;
  net_collected: number[] | null;
}

export interface PipelineRow { stage: string; category: string | null; won: boolean; lost: boolean; count: number }
export interface SourceRow { key: string; label: string; leads: number; bookings: number | null; booking_value: number | null }
export interface AgentRow { agent_id: string | null; name: string; leads: number; bookings: number | null; booking_value: number | null }

export interface MetaAds {
  configured: boolean;
  last_synced_at?: string | null; last_error?: string | null;
  spend?: number | null; reported_chats?: number; verified_conversations?: number; verified_leads?: number;
  verified_bookings?: number | null; verified_booking_value?: number | null; not_traced?: number; basis?: string;
  cost_per_verified_lead?: number | null; return_on_spend?: number | null;
}

export interface AttentionItem { key: string; label: string; count: number; oldest_at: string | null; href: string }
export interface StaleIntegration { kind: string; label: string; status: "yellow" | "red"; last_sync: string | null; message: string | null; href: string }
export interface Insight { id: string; severity: string; title: string; body: string; cta_label?: string | null; cta_href?: string | null }

export interface BusinessOverview {
  generated_at: string;
  period: { date_from: string; date_to: string; timezone: string; previous_from: string; previous_to: string };
  filters: { property_id: string | null; channel: string | null; agent_id: string | null };
  access: { tenant_wide: boolean; bookings: boolean; revenue: boolean };
  leads: LeadsBlock;
  bookings: BookingsBlock | Restricted;
  revenue: RevenueBlock | Restricted;
  funnel: { basis: string; note: string; stages: FunnelStage[] };
  series: SeriesBlock;
  pipeline: PipelineRow[];
  sources: SourceRow[];
  meta_ads: MetaAds | null;
  agents: AgentRow[] | null;
  attention: AttentionItem[];
  stale_integrations: StaleIntegration[];
  insights: Insight[];
}

export const isRestricted = <T extends object>(block: T | Restricted): block is Restricted => "restricted" in block && (block as Restricted).restricted === true;
export const isUnavailable = (v: unknown): v is Unavailable => typeof v === "object" && v !== null && (v as Unavailable).available === false;

// ── formatting ────────────────────────────────────────────────────────────────────────────────────────────────

const INR = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const NUM = new Intl.NumberFormat("en-IN");

/** ₹1,25,000 — full Indian grouping, never clipped. */
export const inr = (n: number | null | undefined): string => (n == null ? "—" : INR.format(n));
export const num = (n: number | null | undefined): string => (n == null ? "—" : NUM.format(n));
export const pct = (n: number | null | undefined): string => (n == null ? "—" : `${n.toFixed(n % 1 ? 1 : 0)}%`);

/** ₹1.2L / ₹3.4Cr — for chart axes and tight spaces only. */
export function inrShort(n: number): string {
  const v = Math.abs(n), sign = n < 0 ? "-" : "";
  if (v >= 1e7) return `${sign}₹${(v / 1e7).toFixed(1)}Cr`;
  if (v >= 1e5) return `${sign}₹${(v / 1e5).toFixed(1)}L`;
  if (v >= 1e3) return `${sign}₹${(v / 1e3).toFixed(0)}k`;
  return `${sign}₹${Math.round(v)}`;
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const m = Math.floor((now - new Date(iso).getTime()) / 60000);
  if (!Number.isFinite(m)) return "";
  if (m < 60) return `${Math.max(1, m)}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

/** "10 Sep – 20 Sep 2026" for a period; a single day collapses to "12 Sep 2026". */
export function periodLabel(from: string, to: string): string {
  const f = new Date(`${from}T00:00:00`), t = new Date(`${to}T00:00:00`);
  const d = (x: Date, year: boolean) => x.toLocaleDateString("en-IN", { day: "numeric", month: "short", ...(year ? { year: "numeric" } : {}) });
  return from === to ? d(t, true) : `${d(f, f.getFullYear() !== t.getFullYear())} – ${d(t, true)}`;
}
