// Phone leads list, Hospitality Hybrid: inside a stage, leads are grouped by what the agent should do with them, so the
// ones that need a person now are never below the fold. Order inside a group is the server's order (newest activity first).
import type { LeadCard } from "./LeadCard";

export type LeadGroupKey = "now" | "today" | "later";
export const LEAD_GROUP_LABEL: Record<LeadGroupKey, string> = { now: "Act now", today: "Today", later: "Later" };

const istDay = (d: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(d);

/** Act now: past its target time, the guest is waiting on a reply, an AI draft is waiting for review, or the AI asked for a
 *  person. Today: created or touched today (India time). Later: everything else. */
export function leadGroup(lead: LeadCard, now: Date = new Date()): LeadGroupKey {
  if (lead.sla_breached || lead.response_time_status === "waiting" || lead.pending_draft || lead.needs_agent_followup) return "now";
  const today = istDay(now);
  const touched = [lead.last_touch_at, lead.created_at].some(t => !!t && istDay(new Date(t)) === today);
  return touched ? "today" : "later";
}

export function groupLeads(leads: LeadCard[], now: Date = new Date()): { key: LeadGroupKey; leads: LeadCard[] }[] {
  const out: Record<LeadGroupKey, LeadCard[]> = { now: [], today: [], later: [] };
  for (const l of leads) out[leadGroup(l, now)].push(l);
  return (["now", "today", "later"] as const).filter(k => out[k].length > 0).map(k => ({ key: k, leads: out[k] }));
}
