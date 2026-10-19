// Pure helpers for the rate calculator: the starting form, the request body, the prefill from a lead/chat/call, what the
// buttons may do, the "Opened from ..." line and the receipt. No prices are computed here: POST /quote-calculator/price does it.
import { formatINR } from "@/lib/utils";
import type { AddonRow, CalcContext, CalcForm, CalcSetup, LeadRow, PriceResult, QuoteFrom, Receipt, Trip, Unit } from "./types";

export const UNIT_LABEL: Record<Unit, string> = {
  one_time: "one-time", per_day: "per day", per_guest: "per guest", per_guest_day: "per guest per day",
};
export const SOURCE_LABEL: Record<string, string> = {
  whatsapp: "WhatsApp", phone_call: "Phone call", instagram: "Instagram", referral: "Referral", walk_in: "Walk-in",
  website: "Website", other: "Other",
};
export const GST_LABEL: Record<string, string> = { "0": "0% · no GST", "5": "5%", "18": "18%", "40": "40%", other: "Other rate" };

/** "70000.00" -> "₹70,000" (lakh grouping). */
export function money(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? formatINR(n) : "—";
}

/** "2026-10-30" -> "Fri, 30 Oct" (a calendar date: no time-zone shift). */
export function dayLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Digits and one dot, as typed into a money field. */
export function cleanNumber(v: string): string {
  const s = v.replace(/[^\d.]/g, "");
  const i = s.indexOf(".");
  return i < 0 ? s : s.slice(0, i + 1) + s.slice(i + 1).replace(/\./g, "");
}

let seq = 0;
export const rowId = () => `a${++seq}`;

export function defaultForm(setup: CalcSetup): CalcForm {
  const slab = setup.gst_slabs.includes(String(Number(setup.settings.gst_percent))) ? String(Number(setup.settings.gst_percent)) : "other";
  return {
    mode: setup.packages.length ? "fixed" : "custom",
    packageKey: setup.packages[0]?.key ?? "",
    customTitle: "Custom trip",
    ratePerDay: setup.custom.rate_per_day ? String(Number(setup.custom.rate_per_day)) : "",
    plannedKm: "",
    kmRate: setup.custom.km_rates[0] ? String(Number(setup.custom.km_rates[0])) : "",
    start: addDays(setup.today, 1),
    days: 1,
    guests: setup.custom.free_guests || 2,
    addons: setup.addons.map(a => ({ id: rowId(), name: a.name, price: String(Number(a.price)), unit: a.unit, on: false, custom: false })),
    discount: "0",
    slab,
    customRate: slab === "other" ? String(Number(setup.settings.gst_percent)) : "12",
    inclusive: setup.settings.prices_include_gst,
    overrideOn: false,
    overridePrice: "",
    overrideReason: "",
    showUsual: true,
    paymentLink: setup.send_setup.razorpay_connected,
  };
}

/** The trip fields a lead / chat / call already gave us. */
export function applyTrip(form: CalcForm, trip: Trip | undefined, setup: CalcSetup): CalcForm {
  if (!trip) return form;
  const next = { ...form };
  if (trip.start_date && trip.start_date >= setup.today) next.start = trip.start_date;
  if (trip.days) next.days = Math.max(1, Math.min(30, trip.days));
  if (trip.guests) next.guests = Math.max(1, Math.min(50, trip.guests));
  if (trip.package_key && setup.packages.some(p => p.key === trip.package_key)) {
    next.mode = "fixed";
    next.packageKey = trip.package_key;
  } else if (trip.route && !trip.package_key) {
    next.customTitle = trip.route;
  }
  return next;
}

export function gstRate(form: CalcForm): string {
  return form.slab === "other" ? (cleanNumber(form.customRate) || "0") : form.slab;
}

/** The request body of /price and /quotes. null while something required is missing. */
export function toPayload(form: CalcForm, inquiryId: string | null): Record<string, unknown> | null {
  if (!form.start || form.days < 1 || form.guests < 1) return null;
  if (form.mode === "fixed" && !form.packageKey) return null;
  const rate = Number(cleanNumber(form.ratePerDay));
  if (form.mode === "custom" && !(rate > 0)) return null;
  const override = form.overrideOn && Number(cleanNumber(form.overridePrice)) > 0
    ? { price: cleanNumber(form.overridePrice), reason: form.overrideReason.trim() || null, show_usual: form.showUsual } : null;
  return {
    mode: form.mode,
    package_key: form.mode === "fixed" ? form.packageKey : null,
    custom: form.mode === "custom" ? {
      title: form.customTitle.trim() || "Custom trip", rate_per_day: String(rate),
      planned_km: cleanNumber(form.plannedKm) || null, km_rate: cleanNumber(form.kmRate) || null,
    } : null,
    start_date: form.start, days: form.days, guests: form.guests,
    addons: form.addons.filter(a => a.on && a.name.trim()).map(a => ({ name: a.name.trim(), price: cleanNumber(a.price) || "0", unit: a.unit })),
    discount_percent: form.discount || "0",
    gst_percent: gstRate(form),
    prices_include_gst: form.inclusive,
    override,
    payment_link: form.paymentLink,
    inquiry_id: inquiryId,
  };
}

/** The add-on amount shown in its row (a hint; the quote's lines come from the server). */
export function addonAmount(a: AddonRow, days: number, guests: number): number {
  const q = a.unit === "per_day" ? days : a.unit === "per_guest" ? guests : a.unit === "per_guest_day" ? days * guests : 1;
  return (Number(cleanNumber(a.price)) || 0) * q;
}

export interface ActionGate {
  canPrice: boolean;
  needsOk: boolean;
  sendLabel: string;
  canSend: boolean;
  canCopy: boolean;
  canSave: boolean;
  hint: string | null;
}

/** What the three buttons may do now. */
export function actionGate({ result, lead, busy }: { result: PriceResult | undefined; lead: LeadRow | null; busy: boolean }): ActionGate {
  const ok = !!result?.ok && !busy;
  const needsOk = !!result?.approval?.required_for_you;
  let hint: string | null = null;
  if (result && !result.ok) hint = result.message;
  else if (needsOk) hint = "More than the allowed discount: the owner or a manager approves it before it goes to the guest.";
  else if (!lead) hint = "Pick a lead to save this quote. Copy still works without one.";
  return {
    canPrice: ok, needsOk,
    sendLabel: needsOk ? "Send for owner OK" : "Send on WhatsApp",
    canSend: ok && !!lead,
    canCopy: ok && !needsOk,
    canSave: ok && !!lead,
    hint,
  };
}

/** The preview text without the payment-link line (a copy with no lead saved has no real link). */
export function withoutPayLine(text: string): string {
  return text.split("\n").filter(l => !l.startsWith("Pay the advance here:")).join("\n");
}

const FROM_TEXT: Record<QuoteFrom, (name: string) => string> = {
  inbox: n => `Opened from ${n}'s WhatsApp chat.`,
  call: n => `Opened from the call with ${n}.`,
  calls: n => `Opened from the call with ${n}.`,
  lead: n => `Opened from ${n}'s lead.`,
  leads: n => `Opened from ${n}'s lead card.`,
  my_day: n => `Opened from My day (${n}).`,
  home: n => `Opened from Home (${n}).`,
  operations: n => `Opened from the agent dashboard (${n}).`,
  quotes: n => `Quote for ${n}.`,
};
const FILLED_SOURCE: Partial<Record<QuoteFrom, string>> = { inbox: "the chat", call: "the call summary", calls: "the call summary" };

/** "Opened from Kiran Reddy's WhatsApp chat. Route, dates and guests filled in from the chat." */
export function fromLine(from: QuoteFrom | undefined, ctx: CalcContext | undefined, fallbackName?: string | null): string {
  if (!from || from === "quotes") return "";
  const name = ctx?.lead?.guest_name || ctx?.guest_name || fallbackName || ctx?.add?.phone || "this guest";
  let out = FROM_TEXT[from](name);
  const filled = ctx?.filled ?? [];
  if (filled.length) {
    const words: string[] = filled.map(f => (f === "route" ? "Route" : f === "dates" ? "dates" : "guests"));
    words[0] = words[0].charAt(0).toUpperCase() + words[0].slice(1);
    const list = words.length > 1 ? `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}` : words[0];
    out += ` ${list} filled in from ${FILLED_SOURCE[from] ?? "the lead"}.`;
  }
  if (ctx?.lead?.kind === "new_trip") out += ` Their last trip was ${ctx.lead.stage_label}, so this quote starts a new lead.`;
  if (!ctx?.lead && ctx?.add) out += " This number has no lead yet: add it below.";
  return out;
}

/** "Last trip: Sold. A new lead is made for this trip." etc. -- the line under the chosen lead. */
export function stageNote(lead: LeadRow): string {
  if (lead.created) return (lead.matched_existing ? "Already in HAIP: same person, new lead. " : "New person, new lead. ")
    + "Moves to Active when the quote is sent or copied.";
  if (lead.kind === "new_trip") return `Last trip: ${lead.stage_label}. A new lead is made for this trip when you save.`;
  const notEngaged = lead.stage_category === "invalid" || ["General Enquiry", "Unqualified", "RNR"].includes(lead.stage_label);
  return notEngaged ? `${lead.stage_label} now. Moves to Active when the quote is sent or copied.` : `${lead.stage_label}. Stage stays as it is.`;
}

const HOW: Record<Receipt["how"], string> = { sent: "sent on WhatsApp", copied: "copied", saved: "saved, not sent", pending_approval: "not sent yet" };

/** The "what got recorded" list after Send / Copy / Save. done = it happened; the last line is what happens on payment. */
export function receiptSteps(r: Receipt, lead: LeadRow | null): { title: string; done: string[]; next: string[]; warning: string | null } {
  const first = (r.lead.guest_name || "the guest").split(" ")[0];
  const valid = dayLabel(r.valid_until);
  if (r.how === "pending_approval") {
    return {
      title: "Waiting for the owner's OK",
      done: [`Saved to ${first}'s lead as ${r.quote_number}, not sent yet`,
        `The owner gets a task to approve the price (${(r.approval?.reasons ?? []).join("; ") || "lowered price"})`],
      next: ["Once approved, you can send or copy it"], warning: null,
    };
  }
  const how = HOW[r.how];
  const done: string[] = [];
  if (lead?.created) done.push(`New lead added: ${lead.guest_name}${lead.phone_last4 ? `, ••${lead.phone_last4}` : ""}, from ${lead.source_label}${lead.matched_existing ? " (joined to the person already in HAIP)" : ""}`);
  else if (r.lead_created) done.push("New lead made for this trip; the earlier lead stays as it is");
  done.push(`Quote ${r.quote_number} saved to ${first}'s lead · ${how}`);
  done.push(r.stage.moved ? `Stage: ${r.stage.from} → ${r.stage.to}` : r.how === "saved" ? "Stage unchanged until the quote is sent or copied" : `Stage stays ${r.stage.from}`);
  if (r.follow_up_at) done.push(`Follow-up in My day on ${dayLabel(r.follow_up_at.slice(0, 10))}, the day the quote expires`);
  done.push(`Lead timeline and Leads360 card: latest quote ${money(r.total)} · ${how} · valid till ${valid}`);
  const next = Number(r.advance) > 0 ? [`When the ${money(r.advance)} advance is paid: booking on the vacant caravan, lead becomes Sold`] : [];
  // A send that could not happen, or a copy made without its payment link, says why.
  const warning = r.message?.status === "not_sent" || (r.how === "copied" && r.message?.message) ? r.message!.message : null;
  return { title: r.how === "sent" ? "Sent and saved to the lead" : r.how === "copied" ? "Copied and saved to the lead" : "Saved to the lead", done, next, warning };
}

/** Copy text that may still be on its way (Safari keeps the user gesture only for a ClipboardItem promise). */
export async function copyText(text: string | Promise<string>): Promise<boolean> {
  const p = Promise.resolve(text);
  try {
    if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
      await navigator.clipboard.write([new ClipboardItem({ "text/plain": p.then(t => new Blob([t], { type: "text/plain" })) })]);
      return true;
    }
  } catch { /* fall back to writeText */ }
  try {
    await navigator.clipboard.writeText(await p);
    return true;
  } catch {
    return false;
  }
}
