import { describe, it, expect } from "vitest";
import { journeySteps, sendGate, TEMPLATE_NOTE } from "./sendHelpers";
import type { Journey, LeadHit, Preview, PricedOption } from "./types";

const primary = { status: "ok", advance: "44940", total: "89880.00" } as unknown as PricedOption;
const pv = (over: Partial<Preview> = {}): Preview =>
  ({ primary, fallback: null, stay_check: "confirmed", can_save: true, save_blockers: [], send_blockers: [], ...over });
const lead = { inquiry_id: "i1", guest_name: "Kiran" } as LeadHit;
const ok = { razorpay_connected: true, template_status: "approved" };

describe("sendGate", () => {
  it("explains the first thing that stops sending", () => {
    expect(sendGate({ canQuote: false, preview: pv(), lead, nextAt: "x", saved: true, setup: ok }).reason).toBe("Your role cannot send quotes.");
    const stay = pv({ send_blockers: ["Confirm the overnight stay before sending the price."] });
    expect(sendGate({ canQuote: true, preview: stay, lead, nextAt: "x", saved: true, setup: ok }).reason).toBe("Confirm the overnight stay before sending the price.");
    expect(sendGate({ canQuote: true, preview: pv(), lead: null, nextAt: "x", saved: false, setup: ok }).reason).toBe("Pick the lead to send this quote to.");
    expect(sendGate({ canQuote: true, preview: pv(), lead, nextAt: "", saved: false, setup: ok }).reason).toMatch(/dated next step/);
    expect(sendGate({ canQuote: true, preview: pv(), lead, nextAt: "x", saved: true, setup: { ...ok, razorpay_connected: false } }).reason)
      .toMatch(/Razorpay is not connected/);
    expect(sendGate({ canQuote: true, preview: pv({ primary: { ...primary, advance: null } }), lead, nextAt: "x", saved: true, setup: ok }).reason)
      .toMatch(/no advance/);
  });

  it("allows sending, saving first, and warns when the template is not approved", () => {
    expect(sendGate({ canQuote: true, preview: pv(), lead, nextAt: "x", saved: false, setup: ok }))
      .toEqual({ canSend: true, reason: null, note: "Saves the quote to the lead first." });
    expect(sendGate({ canQuote: true, preview: pv(), lead, nextAt: "", saved: true, setup: ok }).note).toBeNull();
    expect(sendGate({ canQuote: true, preview: pv(), lead, nextAt: "x", saved: true, setup: { ...ok, template_status: "draft" } }).note).toBe(TEMPLATE_NOTE);
  });
});

const link = (id: string, amount: number, expires: string | null) =>
  ({ id, external_id: `p-${id}`, short_url: `u-${id}`, amount, status: "created" as const, expires_at: expires, booking_id: null, created_at: null, paid_at: null });
const base: Journey = {
  quote_number: "Q-1", group_id: "g",
  options: [
    { quote_id: "a", option_rank: 1, status: "issued", amount: "89880", advance: "44940", link: link("l1", 44940, "2026-10-21T18:29:59Z") },
    { quote_id: "b", option_rank: 2, status: "issued", amount: "41440", advance: "20720", link: link("l2", 20720, null) },
  ],
  message: { status: "sending", error: null, at: null, message_id: null, conversation_id: null }, fallback_message: null, paid: null,
  booking_id: null, invoice: null, confirmation: null, needs_staff: null, polling: true,
};
const state = (j: Journey) => Object.fromEntries(journeySteps(j).map(s => [s.key, s.state]));

describe("journeySteps", () => {
  it("waits for the guest after sending", () => {
    const steps = journeySteps(base);
    expect(steps.map(s => s.key)).toEqual(["links", "sent", "paid", "booking", "invoice", "confirmation"]);
    expect(steps[0].detail).toBe("Option 1: ₹44,940 advance, expires Wed, 21 Oct · Option 2: ₹20,720 advance");
    expect(state(base)).toEqual({ links: "done", sent: "waiting", paid: "waiting", booking: "waiting", invoice: "waiting", confirmation: "waiting" });
  });

  it("shows a message that was not sent and expired links as problems", () => {
    const j: Journey = { ...base, message: { ...base.message!, status: "not_sent", error: "template not approved" },
      options: base.options.map(o => ({ ...o, link: { ...o.link!, status: "expired" as const } })) };
    expect(state(j)).toMatchObject({ sent: "problem", paid: "problem" });
    expect(journeySteps(j)[1].detail).toMatch(/template is not approved/);
  });

  it("is done through the confirmation once booked, and flags a payment staff must handle", () => {
    const booked: Journey = { ...base, message: { ...base.message!, status: "read" }, paid: { quote_id: "a", option_rank: 1, amount: 44940, at: null },
      booking_id: "s1", invoice: { number: "INV/1", id: "i" }, confirmation: { status: "delivered", error: null }, polling: false };
    expect(new Set(Object.values(state(booked)))).toEqual(new Set(["done"]));
    const stuck: Journey = { ...base, paid: booked.paid, needs_staff: "Paid, but no booking was made automatically." };
    expect(state(stuck).booking).toBe("problem");
  });
});
