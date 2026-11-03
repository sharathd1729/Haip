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
export type FollowupFailure = "timeout" | "provider_error" | "bad_output";
export interface Followup { id: string; question: string; status: "queued" | "answered" | "failed"; answer: string | null; reason?: FollowupFailure | null }
/** Why a follow-up failed, in words (older rows have no reason). */
export const FOLLOWUP_FAILURE: Record<FollowupFailure, string> = {
  timeout: "The AI service timed out. Try again.",
  provider_error: "The AI service is unavailable right now. Try again in a minute.",
  bad_output: "The AI gave an unusable answer. Try again or rephrase.",
};
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

// ── AI Executive (backend: app/services/chief, GET /chief/home) ─────────────────────────────────────────────────
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export const SEVERITY_TONE: Record<Severity, Tone> = { critical: "danger", high: "danger", medium: "warning", low: "info", info: "neutral" };
export const SEVERITY_LABEL: Record<Severity, string> = { critical: "Critical", high: "Act today", medium: "Watch", low: "Low", info: "Note" };
export type DismissReason = "not_now" | "already_handled" | "wrong" | "not_worth_it" | "too_risky";
export const DISMISS_LABEL: Record<DismissReason, string> = {
  not_now: "Not now", already_handled: "Already handled", wrong: "This is wrong", not_worth_it: "Not worth it", too_risky: "Too risky",
};

export interface ChiefFinding {
  id: string; code: string; role: string; role_label: string; severity: Severity; title: string; body: string | null;
  why: string | null; next_step: string | null; explained_by: "ai" | "rule"; numbers: Record<string, number>;
  evidence: { type: string; id: string; href?: string | null }[]; cta_label: string | null; cta_href: string | null;
  status: "open" | "resolved" | "dismissed"; first_seen_at: string | null; last_seen_at: string | null;
}
export interface ChiefSettings {
  enabled: boolean; paused: boolean; roles_off: string[]; detectors_off: string[]; whatsapp_approvals: boolean; daily_action_cap: number;
}
export type ProposalStatus = "awaiting_approval" | "approved" | "executing" | "waiting" | "done" | "failed" | "rejected" | "expired";
export interface ChiefProposal {
  id: string; finding_id: string; code: string; title: string; why: string; risk_tier: "R1" | "R2" | "R3"; app_only: boolean;
  preview: string[]; plan_sha: string; status: ProposalStatus; step_index: number;
  steps: { type: string; label: string; tier: string; status: "pending" | "done" | "waiting" | "failed" | null; reason: string | null; at: string | null }[];
  created_at: string | null; decided_at: string | null; decided_via: "app" | "whatsapp" | null; finished_at: string | null;
  failure: string | null; next_check_at: string | null;
}
export interface ApprovalItem {
  source: "executive" | "marketing" | "learning"; id: string; title: string; detail: string; risk_tier: string;
  waiting_since: string | null; href: string | null;
}
export const TIER_LABEL: Record<ChiefProposal["risk_tier"], string> = {
  R1: "Internal only", R2: "Changes team tools or AI settings", R3: "Reaches guests or money",
};
export const PROPOSAL_STATUS_LABEL: Record<ProposalStatus, string> = {
  awaiting_approval: "Needs your OK", approved: "Approved, starting", executing: "Working on it", waiting: "Waiting",
  done: "Done", failed: "Stopped", rejected: "You said no", expired: "No longer needed",
};
export const PROPOSAL_STATUS_TONE: Record<ProposalStatus, Tone> = {
  awaiting_approval: "highlight", approved: "info", executing: "info", waiting: "warning", done: "success", failed: "danger",
  rejected: "neutral", expired: "neutral",
};
export interface ChiefHome {
  settings: ChiefSettings;
  counts: Record<Severity, number> & { open: number; resolved_7d: number };
  roles: { key: string; label: string; findings: ChiefFinding[] }[];
  top: ChiefFinding[];
  brief: ReportSummary | null;
  last_checked_at: string | null;
  proposals: ChiefProposal[];
  activity: ChiefProposal[];
  approvals: ApprovalItem[];
}

export function sinceText(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
}
