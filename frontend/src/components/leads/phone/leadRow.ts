// Pure helpers for the phone Leads rows (kept apart so the list and its sheet can share them without a cycle).
import type { LeadCard } from "@/components/leads/LeadCard";
import { leadTemperature, type NextStepStage } from "@/lib/leadNextStep";

/** "Goa, 26 Nov": where (the first route or property they asked about, else the occasion) and when. */
export function tripText(l: LeadCard): string {
  const where = l.property_interest?.[0] || l.occasion || "";
  const when = l.check_in ? new Date(l.check_in.length <= 10 ? `${l.check_in}T12:00:00+05:30` : l.check_in)
    .toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }) : "";
  return [where, when].filter(Boolean).join(", ");
}

export type Heat = "hot" | "warm" | "cold";

/** How recently the guest reached us (their last message, else when the lead arrived): the lead page's own rule
 *  (leadTemperature: 48 hours Hot, a week Warm, older Cold). A closed lead (won, lost) has no heat. */
export function leadHeat(l: LeadCard, stage: NextStepStage | null | undefined, now?: Date): Heat | null {
  if (!stage) return null;
  const label = leadTemperature({ stage, lastInboundAt: l.last_inbound_at ?? l.created_at, booking: null, now }).label;
  return label === "Hot" ? "hot" : label === "Warm" ? "warm" : label === "Cold" ? "cold" : null;
}

export const HEAT_LABEL: Record<Heat, string> = { hot: "Hot", warm: "Warm", cold: "Cold" };
/** Soft background + matching border for a card. */
export const HEAT_CARD: Record<Heat, string> = {
  hot: "!border-[var(--haip-heat-hot-bd)] !bg-[var(--haip-heat-hot-bg)]",
  warm: "!border-[var(--haip-heat-warm-bd)] !bg-[var(--haip-heat-warm-bg)]",
  cold: "!border-[var(--haip-heat-cold-bd)] !bg-[var(--haip-heat-cold-bg)]",
};
/** The same tint for a row inside a list card: soft background and a bar on the leading edge. */
export const HEAT_ROW: Record<Heat, string> = {
  hot: "bg-[var(--haip-heat-hot-bg)] shadow-[inset_3px_0_0_var(--haip-heat-hot-bd)]",
  warm: "bg-[var(--haip-heat-warm-bg)] shadow-[inset_3px_0_0_var(--haip-heat-warm-bd)]",
  cold: "bg-[var(--haip-heat-cold-bg)] shadow-[inset_3px_0_0_var(--haip-heat-cold-bd)]",
};

/** Client-side match over what is loaded: name, trip, occasion, source. (GET /leads has no search parameter.) */
export function matches(l: LeadCard, q: string): boolean {
  const t = q.trim().toLowerCase();
  if (!t) return true;
  return [l.display_name, tripText(l), l.occasion, l.source, l.primary_channel, ...(l.property_interest ?? [])]
    .some(v => (v ?? "").toLowerCase().includes(t));
}

/** " 2d" for how long the guest has waited on us (LeadCard.response_time_seconds); empty when unknown. */
export function waitedText(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "";
  const m = Math.floor(seconds / 60);
  return ` ${m < 60 ? `${Math.max(1, m)}m` : m < 1440 ? `${Math.floor(m / 60)}h` : `${Math.floor(m / 1440)}d`}`;
}
