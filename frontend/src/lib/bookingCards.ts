// The CRM Bookings list (layout A · Cards by date): ONE card per booking, grouped under its check-in day.
// Check-in and check-out are never separate rows here; that agenda view (lib/bookingAgenda buildEvents) is kept for the Ops module.
import type { Tone } from "@/components/ui/page";
import { formatINR } from "@/lib/utils";
import { addDays, clock, isOverdue, nights, shortDay, type AgendaRow, type Segment } from "@/lib/bookingAgenda";

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dm = (iso: string) => { const d = new Date(`${iso}T00:00:00Z`); return { day: d.getUTCDate(), mon: MON[d.getUTCMonth()] }; };
const dayMonth = (iso: string) => { const p = dm(iso); return `${p.day} ${p.mon}`; };

/** "Today · Mon 19 Oct", "Tomorrow · Tue 20 Oct", "Yesterday · Sun 18 Oct", else "Sat 24 Oct". */
export function dayHeading(iso: string, today: string): string {
  if (iso === today) return `Today · ${shortDay(iso)}`;
  if (iso === addDays(today, 1)) return `Tomorrow · ${shortDay(iso)}`;
  if (iso === addDays(today, -1)) return `Yesterday · ${shortDay(iso)}`;
  return shortDay(iso);
}

/** The stay in one line: "24 → 26 Oct · 2 nights", "30 Oct → 1 Nov · 2 nights", a day trip "15 Oct · 9 am–9 pm · day trip". */
export function stayLine(r: Pick<AgendaRow, "checkin" | "checkout" | "check_in_time" | "check_out_time">): string {
  const n = nights(r);
  if (n === 0) {
    const a = clock(r.check_in_time)?.replace(":00", ""), b = clock(r.check_out_time)?.replace(":00", "");
    const times = a && b ? `${a}–${b}` : a ?? b;
    return [dayMonth(r.checkin), times, "day trip"].filter(Boolean).join(" · ");
  }
  const s = dm(r.checkin), e = dm(r.checkout);
  const left = s.mon === e.mon ? `${s.day}` : `${s.day} ${s.mon}`;
  return `${left} → ${e.day} ${e.mon} · ${n} night${n === 1 ? "" : "s"}`;
}

export interface PayState { pill: string; tone: Tone; text: string | null; due: number }

/** The money line of a card. The single overdue rule (isOverdue, as in the month summary) wins: "₹9,590 overdue". */
export function payState(r: AgendaRow, today: string): PayState | null {
  if (r.raw_status === "cancelled") return null;
  if (r.total_outstanding <= 0) return { pill: "Paid", tone: "success", text: r.total > 0 ? "Paid in full" : null, due: 0 };
  if (isOverdue(r, today)) return { pill: "Overdue", tone: "danger", text: `${formatINR(r.total_outstanding)} overdue`, due: r.total_outstanding };
  const when = r.next_payment_due_date ?? r.checkin;   // no schedule: due before pickup
  return {
    pill: r.payment_status === "unpaid" ? "Unpaid" : "Part paid", tone: r.payment_status === "unpaid" ? "danger" : "warning",
    text: `${formatINR(r.total_outstanding)} due ${dayMonth(when)}`, due: r.total_outstanding,
  };
}

export interface CardGroup { key: string; title: string; hint: string; rows: AgendaRow[] }

/** Groups for a tab. Upcoming / Past / Cancelled: by check-in day (Past and Cancelled newest first). Staying now: one group,
 *  "On a trip now", soonest check-out first. Each booking appears exactly once. */
export function groupCards(rows: AgendaRow[], segment: Segment, today: string): CardGroup[] {
  const seen = new Set<string>();
  const unique = rows.filter(r => (seen.has(r.id) ? false : (seen.add(r.id), true)));
  if (segment === "staying") {
    const sorted = [...unique].sort((a, b) => a.checkout.localeCompare(b.checkout));
    return sorted.length ? [{ key: "staying", title: "On a trip now", hint: `${sorted.length} on a trip`, rows: sorted }] : [];
  }
  const newestFirst = segment === "past" || segment === "cancelled";
  const sorted = [...unique].sort((a, b) =>
    (newestFirst ? b.checkin.localeCompare(a.checkin) : a.checkin.localeCompare(b.checkin))
    || (a.property?.name ?? "").localeCompare(b.property?.name ?? ""));
  const out: CardGroup[] = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last && last.key === r.checkin) last.rows.push(r);
    else out.push({ key: r.checkin, title: dayHeading(r.checkin, today), hint: "", rows: [r] });
  }
  const noun = segment === "upcoming" ? "check-in" : "booking";
  out.forEach(g => { g.hint = `${g.rows.length} ${noun}${g.rows.length === 1 ? "" : "s"}`; });
  return out;
}

/** Share of the total received, 0-100, for the card's progress bar. */
export const paidPct = (r: AgendaRow) => (r.total > 0 ? Math.max(0, Math.min(100, Math.round((r.total_paid / r.total) * 100))) : 0);
