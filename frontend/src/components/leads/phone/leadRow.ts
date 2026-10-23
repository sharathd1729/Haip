// Pure helpers for the phone Leads rows (kept apart so the list and its sheet can share them without a cycle).
import type { LeadCard } from "@/components/leads/LeadCard";

/** "Goa, 26 Nov": where (the first route or property they asked about, else the occasion) and when. */
export function tripText(l: LeadCard): string {
  const where = l.property_interest?.[0] || l.occasion || "";
  const when = l.check_in ? new Date(l.check_in.length <= 10 ? `${l.check_in}T12:00:00+05:30` : l.check_in)
    .toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }) : "";
  return [where, when].filter(Boolean).join(", ");
}

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
