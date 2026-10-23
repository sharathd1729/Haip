// Hand-written types for the AI business analyst + learning loop (backend: app/services/analyst, app/services/learning).
import type { Tone } from "@/components/ui/kit";

export type Kind = "daily_pulse" | "weekly_brief" | "monthly_review";
export type HealthStatus = "green" | "amber" | "red" | "no_data";

export const KIND_LABEL: Record<Kind, string> = {
  daily_pulse: "Daily pulse", weekly_brief: "Weekly brief", monthly_review: "Monthly review",
};

export const STATUS_TONE: Record<HealthStatus, Tone> = { green: "success", amber: "warning", red: "danger", no_data: "neutral" };
export const STATUS_LABEL: Record<HealthStatus, string> = { green: "Healthy", amber: "Watch", red: "Act now", no_data: "No data" };

export interface HealthMetric {
  metric: string; value: number | null; base: number; status: HealthStatus;
  amber_at: number; red_at: number; worse_when: "above" | "below"; min_base: number; explain: string;
}
export interface HealthCheck {
  key: string; label: string; status: HealthStatus; metrics?: HealthMetric[];
  evidence?: { ids: Record<string, string[]>; quotes: { who: string; text: string; conversation_id: string }[] };
}
export interface Recommendation {
  action: string; owner_role: string; due: string; expected_effect: string; change_proposal?: string | null;
}
export interface Brief {
  headline: string; working: string[]; not_working: string[]; why_lost: string; why_dms_not_leads: string;
  team: string; demand: string; money: string; recommendations: Recommendation[]; last_week_followup: string;
}
export interface TeamRow {
  user_id: string | null; name: string; calls_received: number; calls_answered: number; missed_not_returned: number;
  outbound_made: number; outbound_connected: number; followups_due: number; followups_on_time: number;
  first_contact_minutes: number | null; leads: number; booked: number;
}
export interface Facts {
  kind_label: string; period: { from: string; to: string; days: number };
  journey: {
    revenue: { restricted?: boolean; bookings?: number; booked_value?: number; collected?: number };
    contacts: { to_lead: { n: number; x: number; rate: number | null } };
    leads: { new: number };
    ads: { spend: number; chats_started: number; cost_per_chat: number | null; connected: boolean };
  };
  team: TeamRow[];
  demand: { routes_asked: { label: string; count: number }[]; unavailable_asks: { label: string; count: number }[] };
  health: HealthCheck[];
}
export interface Followup { id: string; question: string; status: "queued" | "answered" | "failed"; answer: string | null }
export interface ReportSummary {
  id: string; kind: Kind; period: { from: string; to: string }; headline: string | null; source: "llm" | "deterministic";
  created_at: string | null; health: { key: string; label: string; status: HealthStatus }[];
}
export interface Report extends ReportSummary {
  brief: Brief; facts: Facts; followups: Followup[];
  delivery?: { actions?: Record<string, { assigned_to: string; name: string }> };
}

export interface Arm { assigned: number; n: number; x: number; rate: number | null }
export interface Experiment {
  id: string; change_type: string; area: string; title: string; status: string; target_metric: string;
  control_arm: Arm; treatment_arm: Arm; days_left: number | null; decided_by: string | null;
  decision: { result?: string; reason?: string }; undo_available: boolean; test?: { p_two_sided?: number; diff?: number } | null;
}
export interface Board { made: Experiment[]; suggested: Experiment[]; running: Experiment[]; paused: boolean; experiments_allowed: boolean }

export const METRIC_LABEL: Record<string, string> = {
  dm_to_lead: "Gave a phone number", lead_to_quote: "Got a quote", quote_to_won: "Quote became a booking", guest_reply: "Kept talking",
};

export function pct(r: number | null | undefined): string {
  return r === null || r === undefined ? "No data" : `${Math.round(r * 100)}%`;
}

export function periodText(p: { from: string; to: string }): string {
  const f = (s: string) => new Date(`${s}T00:00:00+05:30`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  return p.from === p.to ? f(p.from) : `${f(p.from)} – ${f(p.to)}`;
}
