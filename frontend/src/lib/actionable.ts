// Actionable AI output (backend services/ai_actionable.py) + lead autopilot shapes. Hand-written types: there is no
// OpenAPI generator. Shared by the lead page, the call detail page and the Leads list.
import type { Tone } from "@/components/ui/page";

export interface NextBestAction {
  action: string;
  owner?: string | null;
  channel?: "call" | "whatsapp" | "instagram" | "email" | "in_person" | "internal" | null;
  deadline?: string | null;
  why?: string | null;
}
export interface MissedRevenue { kind: string; what: string; est_inr?: number | null; grounded?: boolean; evidence?: string | null }
export interface Actionable {
  next_best_action?: NextBestAction | null;
  blocking_objection?: { objection: string; counter?: string | null } | null;
  missed_revenue?: MissedRevenue[];
  temperature?: { value: "hot" | "warm" | "cold"; reason?: string | null } | null;
  haip_updates?: { field: string; value: string; why?: string | null }[];
  outcome?: string | null;
  decline_reason?: string | null;
  decline_quote?: string | null;
}

export interface AutopilotEvidence { kind: "message" | "call" | "booking" | "quote" | "inquiry" | string; id: string; quote?: string }
export interface AutopilotEvent {
  id: string;
  status: "suggested" | "applied" | "undone" | "superseded" | "blocked" | "accepted" | "dismissed";
  rule: string;
  source: "rule" | "ai";
  from_stage_label?: string | null;
  to_stage_label?: string | null;
  reason: string;
  lost_reason_label?: string | null;
  confidence?: number | null;
  evidence: AutopilotEvidence[];
  blocked_reason?: string | null;
  created_at?: string | null;
  can_undo?: boolean;
}
export interface AutopilotBlock {
  mode: "off" | "suggest" | "autopilot";
  pinned: boolean;
  pinned_at?: string | null;
  last_move?: AutopilotEvent | null;
  suggestion?: AutopilotEvent | null;
  history?: AutopilotEvent[];
}
export interface AutopilotMoveBadge { event_id: string; to_stage_label?: string | null; reason: string; source: string; at?: string | null }

const CHANNEL_LABEL: Record<string, string> = {
  call: "Call", whatsapp: "WhatsApp", instagram: "Instagram", email: "Email", in_person: "In person", internal: "Internal",
};
export function channelLabel(channel?: string | null): string | null {
  return channel ? CHANNEL_LABEL[channel] ?? channel : null;
}

export function temperatureTone(value?: string | null): Tone {
  return value === "hot" ? "danger" : value === "warm" ? "warning" : value === "cold" ? "info" : "neutral";
}

/** ₹ in Indian grouping (₹1,25,000), no decimals. */
export function formatInr(amount?: number | null): string | null {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) return null;
  return `₹${Math.round(amount).toLocaleString("en-IN")}`;
}

/** Only grounded figures are summed: an estimate nobody stated is not money we missed. */
export function groundedMissedTotal(items?: MissedRevenue[]): number {
  return (items ?? []).reduce((sum, m) => sum + (m.grounded && m.est_inr ? m.est_inr : 0), 0);
}

export function hasActionable(a?: Actionable | null): boolean {
  return !!a && !!(a.next_best_action?.action || a.blocking_objection?.objection || a.temperature?.value
    || (a.missed_revenue ?? []).length || (a.haip_updates ?? []).length);
}

const RULE_LABEL: Record<string, string> = {
  booking_exists: "Booking found", dates_passed: "Dates passed", explicit_decline: "Guest declined",
  unanswered_calls: "Calls unanswered", quote_no_reply: "No reply to quote", no_reply: "No reply",
  qualified: "Qualified", ai_classifier: "AI read",
};
export function ruleLabel(rule: string): string {
  return RULE_LABEL[rule] ?? rule.replace(/_/g, " ");
}

/** "Moved to Lost by autopilot" / "Autopilot suggests: Lost" / "Undone" -- one line for the lead page. */
export function autopilotHeadline(e: AutopilotEvent): string {
  const to = e.to_stage_label ?? "a new stage";
  if (e.status === "applied") return `Moved to ${to} by autopilot`;
  if (e.status === "undone") return `Autopilot move to ${to} was undone`;
  if (e.status === "blocked") return `Autopilot held back a move to ${to}`;
  return `Autopilot suggests: ${to}`;
}

export function evidenceLabel(e: AutopilotEvidence): string {
  return ({ message: "Message", call: "Call", booking: "Booking", quote: "Quote", inquiry: "Lead details" } as Record<string, string>)[e.kind] ?? e.kind;
}
