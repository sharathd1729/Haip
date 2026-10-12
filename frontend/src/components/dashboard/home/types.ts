// Shape of GET /dashboard/overview as the Home dashboard uses it.

export interface KPIDelta { pct: number; direction: "up" | "down" | "neutral"; }

export interface OverviewResponse {
  date_from: string;
  date_to: string;
  role_scope: string;
  kpi: {
    total_leads: number; qualified_leads: number; avg_response_seconds: number;
    followups_total: number; followups_completed: number; calls: number;
    bookings: number; conversion_rate: number;
    /** null when the viewer lacks revenue.read (see `revenue_restricted`); never 0 in its place. */
    revenue: number | null;
  };
  revenue_restricted?: boolean;
  kpi_deltas: Record<string, KPIDelta>;
  funnel: { stage: string; count: number; pct: number }[];
  calls: { total: number; answered: number; missed: number; missed_recovered: number; callback_rate_pct: number };
  needs_you_now: NeedsYouNow;
  series: Series;
  sources: { key: string; label: string; count: number; pct: number }[];
  top_insights: Insight[];
  agents?: AgentRow[];
}

export interface NeedsYouNow {
  waiting_reply: number; waiting_oldest_at: string | null;
  missed_not_called_back: number; missed_oldest_at: string | null;
  phone_not_called: number;
  followups_overdue: number; followups_oldest_due: string | null;
}

export interface Series {
  days: string[];
  leads: number[];
  /** null = workspace-wide figures the viewer may not see. */
  bookings: number[] | null;
  revenue: number[] | null;
  prev_revenue: number[] | null;
  calls_answered_pct: (number | null)[];
}

export interface Insight {
  id: string; severity: string; title: string; body: string;
  cta_label?: string | null; cta_href?: string | null;
}

export interface AgentRow {
  agent_id: string; agent_name: string; leads_handled: number;
  avg_response_seconds: number; response_count: number;
  calls_answered: number; calls_missed: number; calls_missed_recovered: number;
  conversions: number;
}

export function formatSeconds(s: number): string {
  if (!s) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s >= 3600) {
    const h = Math.floor(s / 3600);
    const m = Math.round((s % 3600) / 60);
    return m ? `${h}h ${m}m` : `${h}h`;
  }
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return rem ? `${m}m ${String(rem).padStart(2, "0")}s` : `${m}m`;
}

export function formatRupees(n: number): string {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(1)}Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(1)}L`;
  if (n >= 1e3) return `₹${(n / 1e3).toFixed(0)}k`;
  return `₹${Math.round(n)}`;
}

export function ago(iso: string | null): string {
  if (!iso) return "";
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return `${Math.max(1, m)}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}
