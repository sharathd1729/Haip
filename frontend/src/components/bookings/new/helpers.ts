// Pure helpers for the new-booking flow: the starting form, the request body, the prefill from a lead / quote / calendar,
// which numbers tick, what is still needed, and the small formatters. No money is computed here: the preview does it.
import { formatINR } from "@/lib/utils";
import type { BookingForm, ComposeContext, ComposeSetup, GuestCard, Preview, Problem, QuotePrefill, Section } from "./types";

export const SECTIONS: { key: Section; n: number; title: string }[] = [
  { key: "guest", n: 1, title: "Guest" },
  { key: "trip", n: 2, title: "Trip" },
  { key: "veh", n: 3, title: "Caravan and interior" },
  { key: "addons", n: 4, title: "Add-ons" },
  { key: "price", n: 5, title: "Price" },
  { key: "pay", n: 6, title: "Payment" },
  { key: "confirm", n: 7, title: "Confirmation" },
];

let seq = 0;
export const rowId = () => `n${++seq}`;

export function money(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "₹0";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? formatINR(n) : "₹0";
}

/** "2026-11-01" -> "Sun 1 Nov" (a calendar date: no time-zone shift). */
export function day(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return "–";
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).replace(",", "");
}

/** "07:00" -> "7:00 am". */
export function clock(t: string | null | undefined): string {
  if (!t) return "";
  const [h, m] = t.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h >= 12 ? "pm" : "am"}`;
}

/** "21–22 Oct", "30 Oct–1 Nov". */
export function span(a: string, b: string): string {
  if (!a) return "";
  const mon = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { month: "short", timeZone: "UTC" });
  const dn = (iso: string) => Number(iso.slice(8, 10));
  if (!b || a === b) return `${dn(a)} ${mon(a)}`;
  return mon(a) === mon(b) ? `${dn(a)}–${dn(b)} ${mon(b)}` : `${dn(a)} ${mon(a)}–${dn(b)} ${mon(b)}`;
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function nightsBetween(a: string, b: string): number {
  if (!a || !b || b < a) return 0;
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 864e5);
}

export function cleanNumber(v: string): string {
  const s = v.replace(/[^\d.]/g, "");
  const i = s.indexOf(".");
  return i < 0 ? s : s.slice(0, i + 1) + s.slice(i + 1).replace(/\./g, "");
}

export const digits = (v: string) => v.replace(/\D/g, "");
export const masked = (last4: string | null | undefined) => (last4 ? `•••• ${last4}` : "no number");
export const firstName = (name: string | null | undefined) => (name || "").trim().split(" ")[0] || "the guest";

export function defaultForm(setup: ComposeSetup): BookingForm {
  const gst = String(Number(setup.settings.gst_percent));
  return {
    guest: null, newGuest: null, adding: false, ng: { phone: "", name: "", source: "" }, guestQ: "", inquiryId: null, fromLead: false,
    start: null, mode: setup.packages.length ? "fixed" : "custom", packageKey: "", customTitle: "Custom trip",
    ratePerDay: setup.custom.rate_per_day ? String(Number(setup.custom.rate_per_day)) : "",
    checkIn: "", checkInTime: "12:00", checkOut: "", checkOutTime: "12:00", guests: 2, pickup: "",
    vehicle: "auto", interior: "", notes: "",
    addons: setup.addons.map(a => ({ id: rowId(), name: a.name, price: String(Number(a.price)), unit: a.unit, on: false, custom: false })),
    discount: "0", slab: setup.gst_slabs.includes(gst) ? gst : "18", inclusive: setup.settings.prices_include_gst,
    overrideOn: false, overridePrice: "", overrideReason: "",
    advance: "50", advanceAmount: "", advanceDue: "", balanceRule: "pickup", deposit: "10000", depositCollect: "pickup",
    payNow: "none", payMethod: "upi", payAmount: "", payRef: "", confirm: "now", invoice: true,
  };
}

/** The request body for POST /bookings/compose (and /preview). Empty fields go as null; the server says what is missing. */
export function toPayload(f: BookingForm): Record<string, unknown> {
  const quoteId = f.start && f.start !== "scratch" ? f.start : null;
  return {
    guest_id: f.guest?.guest_id ?? null,
    new_guest: !f.guest && f.newGuest ? { phone: f.newGuest.phone, name: f.newGuest.name || null, source: f.newGuest.source } : null,
    inquiry_id: f.inquiryId, quote_id: quoteId, start_scratch: f.start === "scratch",
    mode: f.mode, package_key: f.mode === "fixed" ? f.packageKey || null : null,
    custom: f.mode === "custom" ? { title: f.customTitle || "Custom trip", rate_per_day: f.ratePerDay || "0" } : null,
    check_in: f.checkIn || null, check_in_time: f.checkInTime || "12:00", check_out: f.checkOut || null, check_out_time: f.checkOutTime || "12:00",
    guests: f.guests, pickup: f.pickup.trim() || null,
    property_id: f.vehicle === "auto" ? null : f.vehicle, interior: f.interior || null, notes: f.notes.trim() || null,
    addons: f.addons.filter(a => a.on && a.name.trim() && Number(a.price) > 0).map(a => ({ name: a.name.trim(), price: a.price, unit: a.unit })),
    discount_percent: f.discount || "0", gst_percent: f.slab, prices_include_gst: f.inclusive,
    override: f.overrideOn ? { price: f.overridePrice || null, reason: f.overrideReason.trim() || null } : null,
    advance: f.advance === "other" ? { amount: f.advanceAmount || "0" } : { percent: f.advance },
    advance_due: f.advanceDue || null, balance_rule: f.balanceRule,
    deposit_amount: f.deposit || "0", deposit_collect: f.depositCollect,
    payment: { kind: f.payNow, method: f.payMethod, amount: f.payNow === "paid" && f.payAmount ? f.payAmount : null,
               reference: f.payNow === "paid" ? f.payRef.trim() || null : null },
    confirmation: f.confirm, attach_invoice: f.invoice,
  };
}

/** Picking a guest: a saved quote must be chosen (or Start from scratch) when they have one; else start from scratch with
 *  the lead's dates. */
export function pickGuest(f: BookingForm, g: GuestCard, ctx?: ComposeContext): BookingForm {
  const usable = (ctx?.quotes ?? []).some(q => q.usable);
  let next: BookingForm = { ...f, guest: g, newGuest: null, adding: false, guestQ: "", start: usable ? null : "scratch",
                            inquiryId: ctx?.lead?.inquiry_id ?? g.open_lead?.inquiry_id ?? null };
  if (!usable && ctx) next = applyTrip(next, ctx.trip);
  return next;
}

/** The dates a package sets from a check-in (as the mock-up): its nights from the package record (`nights`, from the rate
 *  calculator's rules: 48 hours = 2 nights); a same-day trip returns the same day, 10 am to 8 pm; a package that does not say
 *  keeps a later check-out, else one night. */
export function packageLength(p: ComposeSetup["packages"][number], checkIn: string, f: BookingForm): Partial<BookingForm> {
  if (p.nights === 0 || p.product === "same_day") {
    return { checkOut: checkIn, ...(f.checkOutTime <= f.checkInTime || f.checkInTime === "12:00" ? { checkInTime: "10:00", checkOutTime: "20:00" } : {}) };
  }
  if (p.nights != null) {
    return { checkOut: addDays(checkIn, p.nights), ...(f.checkOut && f.checkOut === f.checkIn ? { checkInTime: "12:00", checkOutTime: "12:00" } : {}) };
  }
  return !f.checkOut || f.checkOut <= checkIn ? { checkOut: addDays(checkIn, 1) } : {};
}

export function applyTrip(f: BookingForm, trip: ComposeContext["trip"] | undefined): BookingForm {
  if (!trip || f.checkIn) return f;
  return { ...f, checkIn: trip.check_in ?? f.checkIn, checkOut: trip.check_out ?? f.checkOut, guests: trip.guests ?? f.guests,
           packageKey: trip.package_key ?? f.packageKey, mode: trip.package_key ? "fixed" : f.mode };
}

export function applyQuote(f: BookingForm, id: string, p: QuotePrefill, setup: ComposeSetup): BookingForm {
  const next: BookingForm = {
    ...f, start: id, checkIn: p.check_in ?? f.checkIn, checkOut: p.check_out ?? f.checkOut, checkInTime: p.check_in_time,
    checkOutTime: p.check_out_time, guests: p.guests ?? f.guests, vehicle: "auto", overrideOn: false, overridePrice: "", overrideReason: "",
  };
  if (p.mode === "custom" && p.custom) {
    next.mode = "custom";
    next.customTitle = p.custom.title || "Custom trip";
    next.ratePerDay = String(Number(p.custom.rate_per_day ?? 0));
  } else if (p.package_key && setup.packages.some(k => k.key === p.package_key)) {
    next.mode = "fixed";
    next.packageKey = p.package_key;
  }
  if (p.calculator) {
    const names = new Set((p.addons ?? []).map(a => a.name));
    const known = f.addons.filter(a => !a.custom).map(a => {
      const q = (p.addons ?? []).find(x => x.name === a.name);
      return q ? { ...a, on: true, price: String(Number(q.price)), unit: q.unit } : { ...a, on: false };
    });
    const extra = (p.addons ?? []).filter(a => !f.addons.some(x => x.name === a.name && !x.custom))
      .map(a => ({ id: rowId(), name: a.name, price: String(Number(a.price)), unit: a.unit, on: true, custom: true }));
    next.addons = names.size ? [...known, ...extra] : known;
    next.discount = p.discount_percent ? String(Number(p.discount_percent)) : "0";
    if (p.gst_percent != null) next.slab = String(Number(p.gst_percent));
    if (p.prices_include_gst != null) next.inclusive = p.prices_include_gst;
  }
  return next;
}

/** The problems the page shows now: live ones always, the rest once Create was pressed. While a new guest is being typed,
 *  the guest line says to finish it. */
export function shownProblems(f: BookingForm, preview: Preview | undefined, showErr: boolean): Problem[] {
  const all = allProblems(f, preview);
  return all.filter(p => p.live || showErr);
}

export function allProblems(f: BookingForm, preview: Preview | undefined): Problem[] {
  const list = preview?.problems ?? [{ section: "guest" as const, message: "Pick the guest, or add a new one with their phone number.", live: false }];
  if (f.adding && !f.guest && !f.newGuest) {
    return list.map(p => p.section === "guest" && p.message.startsWith("Pick the guest")
      ? { ...p, message: "Finish adding the new guest: a 10-digit mobile number is needed." } : p);
  }
  return list;
}

export type SectionMark = "ok" | "bad" | "todo";

/** A section's number becomes a tick when nothing in it is missing (and a guest is picked), "!" when Create found a problem
 *  in it, else stays its number. */
export function sectionMark(section: Section, problems: Problem[], showErr: boolean, hasGuest: boolean): SectionMark {
  const mine = problems.some(p => p.section === section);
  if (mine && showErr) return "bad";
  return !mine && hasGuest ? "ok" : "todo";
}

export function firstProblemSection(problems: Problem[]): Section | null {
  const order = SECTIONS.map(s => s.key);
  const sorted = [...problems].sort((a, b) => order.indexOf(a.section) - order.indexOf(b.section));
  return sorted[0]?.section ?? null;
}
