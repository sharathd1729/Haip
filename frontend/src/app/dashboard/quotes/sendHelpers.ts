// Pure helpers for "Send quote + payment link": whether the button may be pressed (and the exact reason when not), and the
// journey after sending (link created -> sent on WhatsApp -> paid -> booking -> invoice -> confirmation). The server makes
// the same checks again (POST /quotes/{id}/send); these only explain them before the click.
import { deliveryPill } from "@/lib/invoices";
import { dayLabel, money } from "./quoteHelpers";
import type { Catalog, Journey, LeadHit, MessageState, Preview } from "./types";

export const TEMPLATE_NOTE =
  "The WhatsApp template ratha_quote_payment_v1 is not approved yet: the payment links are made for you to copy, nothing is sent to the guest.";

export interface SendGate { canSend: boolean; reason: string | null; note: string | null }

export function sendGate({ canQuote, preview, lead, nextAt, saved, setup }: {
  canQuote: boolean; preview: Preview | undefined; lead: LeadHit | null; nextAt: string; saved: boolean; setup: Catalog["send_setup"];
}): SendGate {
  const no = (reason: string): SendGate => ({ canSend: false, reason, note: null });
  if (!canQuote) return no("Your role cannot send quotes.");
  if (!preview || preview.primary.status !== "ok") return no("Price the trip first.");
  if (preview.send_blockers.length) return no(preview.send_blockers[0]);
  if (!preview.primary.advance || Number(preview.primary.advance) <= 0) return no("No payment terms are published, so there is no advance to collect.");
  if (!lead) return no("Pick the lead to send this quote to.");
  if (!saved && !nextAt) return no("Set a dated next step: the quote is saved to the lead before it is sent.");
  if (!setup.razorpay_connected) return no("Razorpay is not connected. Add your keys in Settings > Payments.");
  const note = setup.template_status !== "approved" ? TEMPLATE_NOTE : !saved ? "Saves the quote to the lead first." : null;
  return { canSend: true, reason: null, note };
}

export type StepState = "done" | "waiting" | "problem";
export interface JourneyStep { key: string; title: string; detail: string; state: StepState }

const optionName = (rank: number, many: boolean) => (many ? (rank === 2 ? "Option 2" : "Option 1") : "The trip");

function messageStep(m: MessageState | null): Pick<JourneyStep, "detail" | "state"> {
  if (!m) return { detail: "Not sent yet.", state: "waiting" };
  if (m.status === "not_sent") {
    return { detail: m.error === "template not approved" ? "Not sent: the WhatsApp template is not approved yet. Copy the links below."
      : `Not sent${m.error ? `: ${m.error}` : ""}. Copy the links below.`, state: "problem" };
  }
  if (m.status === "sending") return { detail: "Preparing the quote PDF and the message.", state: "waiting" };
  const pill = deliveryPill(m.status);
  if (m.status === "failed") return { detail: `Not delivered${m.error ? `: ${m.error}` : ""}.`, state: "problem" };
  return { detail: `${pill.label}. The quote PDF is attached; the button opens option 1's link.`, state: m.status === "queued" ? "waiting" : "done" };
}

export function journeySteps(j: Journey): JourneyStep[] {
  const many = j.options.length > 1;
  const withLinks = j.options.filter(o => o.link);
  const expired = !j.paid && withLinks.length > 0 && withLinks.every(o => o.link!.status === "expired" || o.link!.status === "cancelled");
  const linkDetail = withLinks.map(o => `${optionName(o.option_rank, many)}: ${money(o.link!.amount)} advance`
    + (o.link!.expires_at ? `, expires ${dayLabel(o.link!.expires_at)}` : "")).join(" · ");
  const msg = messageStep(j.message);
  const paidOption = j.paid ? optionName(j.paid.option_rank, many).toLowerCase() : "";
  return [
    { key: "links", title: "Payment links created", detail: linkDetail || "No links yet.", state: withLinks.length ? "done" : "waiting" },
    { key: "sent", title: "Quote sent on WhatsApp", ...msg },
    {
      key: "paid", title: "Guest paid",
      detail: j.paid ? `${money(j.paid.amount)} for ${paidOption}.`
        : expired ? "The links expired unpaid. Save the quote again to send new ones."
        : many ? "Waiting. Each option has its own link; the guest pays for the one they choose." : "Waiting for the guest.",
      state: j.paid ? "done" : expired ? "problem" : "waiting",
    },
    {
      key: "booking", title: "Booking created",
      detail: j.booking_id ? "Made from the quote. Payment in the ledger, lead moved to Sold." : j.needs_staff ?? "Made automatically when the advance lands.",
      state: j.booking_id ? "done" : j.needs_staff ? "problem" : "waiting",
    },
    { key: "invoice", title: "Invoice", detail: j.invoice ? j.invoice.number : "Issued after the payment.", state: j.invoice ? "done" : "waiting" },
    {
      key: "confirmation", title: "Confirmation sent",
      detail: j.confirmation ? `${deliveryPill(j.confirmation.status).label}, with the invoice attached.` : "Goes out with the invoice.",
      state: !j.confirmation ? "waiting" : j.confirmation.status === "failed" ? "problem" : "done",
    },
  ];
}
