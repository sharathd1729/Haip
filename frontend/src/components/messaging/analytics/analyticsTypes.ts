// Shape of GET /messaging/analytics and small formatting helpers.

export interface Totals {
  sent: number; delivered: number; read: number; failed: number;
  delivery_rate: number | null; read_rate: number | null; failure_rate: number | null;
}
export interface DayRow { date: string; sent: number; delivered: number; read: number; failed: number; delivery_rate: number | null; read_rate: number | null }
export interface FailureRow { group: string; label: string; count: number; reason: string; hint: string | null }
export interface CampaignRow extends Totals {
  id: string; name: string; status: string; template_name: string | null; created_at: string | null; total: number;
}
export interface TemplateRow extends Totals { template_name: string; campaigns: number }
export interface HourRow { hour: number; sent: number; read: number; read_rate: number | null }

export interface Analytics {
  range: { days: number; from: string; to: string };
  totals: Totals & { campaigns: number; contacts: number; opt_outs: number };
  previous: Totals;
  daily: DayRow[];
  failures: FailureRow[];
  campaigns: CampaignRow[];
  templates: TemplateRow[];
  hours: HourRow[];
  best_hour: number | null;
  upcoming: { id: string; name: string; scheduled_at: string | null }[];
  running: number;
  health: { connected: boolean; templates: Record<string, number> };
  truncated: boolean;
}

export const fmt = (n: number) => n.toLocaleString("en-IN");
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v}%`);

export function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], { day: "numeric", month: "short" });
}

export function hourLabel(h: number): string {
  const suffix = h < 12 ? "am" : "pm";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}${suffix}`;
}

/** Change vs the previous period: relative for counts, points for rates. */
export function change(current: number | null, previous: number | null, kind: "count" | "points"): { text: string; dir: "up" | "down" | "flat" } | null {
  if (current === null || previous === null) return null;
  if (kind === "count") {
    if (previous === 0) return current === 0 ? { text: "no change", dir: "flat" } : null;
    const d = Math.round(((current - previous) / previous) * 100);
    return { text: `${Math.abs(d)}%`, dir: d > 0 ? "up" : d < 0 ? "down" : "flat" };
  }
  const d = Math.round((current - previous) * 10) / 10;
  return { text: `${Math.abs(d)} pts`, dir: d > 0 ? "up" : d < 0 ? "down" : "flat" };
}
