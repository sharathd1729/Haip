// The Bookings agenda (layout B): pure rules for the segments, day rows, money chips, the vehicle strip and the filters.
// Shapes mirror backend/app/services/booking_agenda_service.py and GET /bookings (bookings.py).
import { useSyncExternalStore } from "react";
import type { Tone } from "@/components/ui/page";
import { formatINR } from "@/lib/utils";
import type { BookingRow, BookingStatus, Deposit } from "@/lib/bookings";

export type Segment = "upcoming" | "staying" | "past" | "cancelled";
export const SEGMENTS: { value: Segment; label: string }[] = [
  { value: "upcoming", label: "Upcoming" },
  { value: "staying", label: "Staying now" },
  { value: "past", label: "Past" },
  { value: "cancelled", label: "Cancelled" },
];

/** A row of GET /bookings with the fields the agenda reads. `status` there is the old RentalWise-style label; `raw_status` is the real one. */
export interface AgendaRow extends BookingRow {
  inquiry_id: string | null;
  trip: string | null;
  deposit: { amount: number; status: Deposit["status"] } | null;
  raw_status: BookingStatus;
  check_in_time: string | null;
  check_out_time: string | null;
}

export interface AgendaList {
  data: AgendaRow[];
  meta: { current_page: number; last_page: number; per_page: number; total: number; from: number; to: number;
    today?: string; segment_counts?: Record<Segment, number> };
}

export type Money = number | { restricted: true };
export interface MonthSummary {
  month: string; today: string; bookings: number;
  by_vehicle: { property_id: string; name: string; count: number }[];
  booked_value: Money; collected: Money; still_due: Money; overdue: Money;
}

export interface Occupancy {
  today: string; from: string; to: string; days: number;
  vehicles: {
    property_id: string; name: string; slot: number; placeholder: boolean;
    bookings: { booking_id: string; guest_name: string; check_in: string; check_out: string; status: string; due: boolean }[];
    holds: { from: string; to: string; reason: string }[];
  }[];
}

export const isRestricted = (m: Money | undefined): m is { restricted: true } => typeof m === "object" && m !== null && m.restricted === true;

// ── Dates and times (the workspace runs on IST) ─────────────────────────────

export function todayIST(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const parts = (iso: string) => { const d = new Date(`${iso}T00:00:00Z`); return { wd: WEEKDAY[d.getUTCDay()], day: d.getUTCDate(), mon: MONTH[d.getUTCMonth()] }; };

/** "Mon 19 Oct" */
export function shortDay(iso: string): string { const p = parts(iso); return `${p.wd} ${p.day} ${p.mon}`; }

/** The three lines of a day label: "Today" / "Tmrw" / "Wed", the day number, the month. */
export function dayLabel(iso: string, today: string): { top: string; day: number; month: string } {
  const p = parts(iso);
  const top = iso === today ? "Today" : iso === addDays(today, 1) ? "Tmrw" : iso === addDays(today, -1) ? "Yday" : p.wd;
  return { top, day: p.day, month: p.mon };
}

/** "16:00" -> "4:00 pm". Null stays null: no time was set on the booking. */
export function clock(t: string | null | undefined): string | null {
  if (!t || !/^\d{1,2}:\d{2}$/.test(t)) return null;
  const [h, m] = t.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}

export function nights(r: { checkin: string; checkout: string }): number { return Math.max(0, daysBetween(r.checkin, r.checkout)); }

/** "₹3.95 L" for a headline (₹1,25,000 style below a lakh, crores past 1 Cr). The full figure goes next to it. */
export function lakh(n: number): string {
  const trim = (x: number) => x.toFixed(2).replace(/\.?0+$/, "");
  if (Math.abs(n) >= 1e7) return `₹${trim(n / 1e7)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${trim(n / 1e5)} L`;
  return formatINR(n);
}

export function guestName(r: BookingRow): string {
  const g = r.main_guest;
  if (!g) return "Unknown guest";
  return `${g.first_name} ${g.last_name}`.trim() || g.phone || "Unknown guest";
}

// ── Money ────────────────────────────────────────────────────────────────────

/** Same rule as booking_agenda_service.is_overdue: money still owed, not cancelled, and an instalment is past due or the trip has started. */
export function isOverdue(r: AgendaRow, today: string): boolean {
  if (r.raw_status === "cancelled" || r.total_outstanding <= 0) return false;
  return r.payment_overdue || r.checkin < today;
}

export interface MoneyChip { label: string; tone: Tone }

/** The one money fact a day row shows. Overdue money (the single isOverdue rule, the same one the month summary uses) always wins,
 *  on any row. Otherwise a check-in shows what to collect and a check-out the deposit to hand back. */
export function moneyChip(kind: EventKind, r: AgendaRow, today: string): MoneyChip | null {
  if (kind === "cancelled" || r.raw_status === "cancelled") return null;
  if (isOverdue(r, today)) return { label: `${formatINR(r.total_outstanding)} overdue`, tone: "danger" };
  if (kind === "in" && r.total_outstanding > 0) {
    return { label: `Collect ${formatINR(r.total_outstanding)}`, tone: r.payment_status === "unpaid" ? "danger" : "warning" };
  }
  if (kind === "out" && r.deposit && r.deposit.status === "held" && r.deposit.amount > 0 && r.raw_status !== "checked_out") {
    return { label: `Return ${formatINR(r.deposit.amount)} deposit`, tone: "neutral" };
  }
  return null;
}

// ── Agenda: check-ins and check-outs by day ─────────────────────────────────

export type EventKind = "in" | "out" | "cancelled";
export interface AgendaEvent { key: string; day: string; time: string | null; kind: EventKind; row: AgendaRow; stayingNow: boolean }

const sortTime = (t: string | null) => (t && /^\d{1,2}:\d{2}$/.test(t) ? t.padStart(5, "0") : "12:00");   // no time = Ratha's noon start

/** Events for a segment. Upcoming: each check-in, each check-out of a trip that spans nights, and the check-outs of guests staying
 *  now. Staying now and Past: check-outs. Cancelled: the check-in that will not happen. Past and Cancelled read newest first. */
export function buildEvents(rows: AgendaRow[], segment: Segment, stayingNow: AgendaRow[] = []): AgendaEvent[] {
  const ev: AgendaEvent[] = [];
  const add = (row: AgendaRow, kind: EventKind, staying = false) => ev.push({
    key: `${row.id}:${kind}`, kind, row, stayingNow: staying,
    day: kind === "out" ? row.checkout : row.checkin,
    time: kind === "out" ? row.check_out_time : row.check_in_time,
  });
  for (const r of rows) {
    if (segment === "cancelled") add(r, "cancelled");
    else if (segment === "staying" || segment === "past") add(r, "out", segment === "staying");
    else { add(r, "in"); if (nights(r) > 0) add(r, "out"); }
  }
  if (segment === "upcoming") {
    const seen = new Set(rows.map(r => r.id));
    stayingNow.filter(r => !seen.has(r.id)).forEach(r => add(r, "out", true));
  }
  const newestFirst = segment === "past" || segment === "cancelled";
  return ev.sort((a, b) =>
    (newestFirst ? b.day.localeCompare(a.day) : a.day.localeCompare(b.day))
    || sortTime(a.time).localeCompare(sortTime(b.time))
    || (a.kind === b.kind ? 0 : a.kind === "out" ? -1 : 1)        // the caravan comes back before it goes out again
    || guestName(a.row).localeCompare(guestName(b.row)));
}

export function groupByDay(events: AgendaEvent[]): { day: string; events: AgendaEvent[] }[] {
  const out: { day: string; events: AgendaEvent[] }[] = [];
  for (const e of events) {
    const last = out[out.length - 1];
    if (last && last.day === e.day) last.events.push(e); else out.push({ day: e.day, events: [e] });
  }
  return out;
}

// ── Vehicle strip ────────────────────────────────────────────────────────────

export interface StripBlock { key: string; bookingId: string | null; label: string; title: string; start: number; span: number; due: boolean; hold: boolean }

/** Blocks for one vehicle across the strip's columns (0 = the first day). A trip fills its days from pickup up to the drop day
 *  (noon to noon); a same-day trip fills its one day. Holds (blocked dates) are drawn too, without a booking to open. */
export function stripBlocks(v: Occupancy["vehicles"][number], from: string, days: number): StripBlock[] {
  const out: StripBlock[] = [];
  for (const b of v.bookings) {
    const sameDay = b.check_in === b.check_out;
    const start = Math.max(0, daysBetween(from, b.check_in));
    const end = Math.min(days, daysBetween(from, b.check_out) + (sameDay ? 1 : 0));
    if (end <= start) continue;
    const first = (b.guest_name || "Guest").trim().split(/\s+/)[0];
    out.push({ key: b.booking_id, bookingId: b.booking_id, label: first, start, span: end - start, due: b.due, hold: false,
      title: `${b.guest_name}, ${v.name}, ${shortDay(b.check_in)} to ${shortDay(b.check_out)}${b.due ? ", money still due" : ""}` });
  }
  for (const h of v.holds) {
    const start = Math.max(0, daysBetween(from, h.from));
    const end = Math.min(days, daysBetween(from, h.to));
    if (end <= start) continue;
    out.push({ key: `hold:${h.from}:${h.to}`, bookingId: null, label: h.reason === "maintenance" ? "Maint." : "Blocked", start, span: end - start,
      due: false, hold: true, title: `${v.name} blocked ${shortDay(h.from)} to ${shortDay(addDays(h.to, -1))}` });
  }
  return out.sort((a, b) => a.start - b.start);
}

// ── Filters sheet ────────────────────────────────────────────────────────────

export interface Filters { status: string[]; pay: string[]; vehicle: string[]; channel: string[]; from: string; to: string }
export const NO_FILTERS: Filters = { status: [], pay: [], vehicle: [], channel: [], from: "", to: "" };

export const PAY_OPTIONS = [
  { value: "paid", label: "Paid" }, { value: "partial", label: "Part paid" }, { value: "unpaid", label: "Unpaid" },
  { value: "due", label: "Still due" }, { value: "overdue", label: "Overdue" },
];

export function filterCount(f: Filters): number {
  return f.status.length + f.pay.length + f.vehicle.length + f.channel.length + (f.from || f.to ? 1 : 0);
}

/** GET /bookings params for the filters (several values of one filter are comma separated). */
export function filterParams(f: Filters): Record<string, string | undefined> {
  const many = (v: string[]) => (v.length ? v.join(",") : undefined);
  return {
    status: many(f.status), payment_status: many(f.pay), property_id: many(f.vehicle), channel: many(f.channel),
    check_in_from: f.from || undefined, check_in_to: f.to || undefined,
  };
}

export function toggle(list: string[], v: string): string[] {
  return list.includes(v) ? list.filter(x => x !== v) : [...list, v];
}

/** False on the server and during hydration, true after (and at once on client-side navigation). Gate query-driven UI on it so
 *  the first client render matches the server HTML even when the persisted query cache already holds data. */
export function useHydrated(): boolean {
  return useSyncExternalStore(noopSubscribe, () => true, () => false);
}
const noopSubscribe = () => () => {};

/** Vehicle colour slot for the strip and the vehicle tag: Ratha 1 -> 1, Ratha 2 -> 2 (in name order), anything else -> 0. */
export function vehicleSlot(name: string | null | undefined, order: string[]): number {
  const i = name ? order.indexOf(name) : -1;
  return i < 0 ? 0 : (i % 2) + 1;
}

/** Roles that may change a booking, record money and send pay links (the backend's _EDIT roles on bookings). */
export const canEditBookings = (role: string | null | undefined) => role === "owner" || role === "manager" || role === "reservations";

/** Columns of the strip with no booking or hold: a tap there starts a new booking for that vehicle and day. */
export function freeColumns(blocks: StripBlock[], days: number): number[] {
  const taken = new Set<number>();
  blocks.forEach(b => { for (let i = b.start; i < b.start + b.span; i++) taken.add(i); });
  return Array.from({ length: days }, (_, i) => i).filter(i => !taken.has(i));
}

/** The New booking page, prefilled with a vehicle and a one-night stay from `from`. */
export const newBookingHref = (propertyId: string, from: string) =>
  `/dashboard/bookings/new?${new URLSearchParams({ property: propertyId, from, to: addDays(from, 1) }).toString()}`;
