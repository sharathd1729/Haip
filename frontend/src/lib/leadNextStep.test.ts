import { describe, it, expect } from "vitest";
import { dateRange, deriveNextStep, leadTemperature, pickLiveBooking, type BookingRow, type NextStepFacts } from "./leadNextStep";

const NOW = new Date("2026-10-19T07:40:00Z");          // Mon 19 Oct, 1:10 pm IST
const ago = (h: number) => new Date(NOW.getTime() - h * 3_600_000).toISOString();
const ahead = (h: number) => new Date(NOW.getTime() + h * 3_600_000).toISOString();
const ACTIVE = { key: "active", label: "Active", category: "valid" };

function facts(patch: Partial<NextStepFacts> = {}): NextStepFacts {
  return { name: "Sharath", stage: ACTIVE, hasPhone: true, now: NOW, lastInboundAt: ago(30), lastOutboundAt: ago(29), ...patch };
}

describe("deriveNextStep", () => {
  it("a lost lead has nothing to do, whatever the thread says", () => {
    const s = deriveNextStep(facts({ stage: { key: "lost", is_closed_lost: true }, lastOutboundAt: ago(40), lostReason: "budget_mismatch" }));
    expect(s.key).toBe("closed_lost");
    expect(s.actions).toEqual([]);
    expect(s.why).toContain("Price too high");
  });

  it("a new enquiry is never told it was marked lost: the stage drives the step", () => {
    const s = deriveNextStep(facts({ stage: { key: "general_enquiry", category: "invalid", is_default_entry: true } as never }));
    expect(s.key).toBe("qualify");
    expect(s.title).toBe("Call Sharath to qualify");
    expect(s.actions[0]).toBe("call");
  });

  it("an unanswered guest message comes before the quote follow-up", () => {
    const s = deriveNextStep(facts({ lastInboundAt: ago(2), lastOutboundAt: ago(20),
      openQuote: { amount: 65000, sharedVia: "sent", validUntil: ahead(30), status: "issued" } }));
    expect(s.key).toBe("reply");
    expect(s.actions).toEqual(["message", "call"]);
  });

  it("a missed call they made is the first thing to fix", () => {
    const s = deriveNextStep(facts({ missedInboundUnreturned: true, lastInboundAt: ago(2), lastOutboundAt: ago(20) }));
    expect(s.key).toBe("call_back");
    expect(s.tone).toBe("urgent");
  });

  it("a quote about to expire asks for a follow-up with its expiry", () => {
    const s = deriveNextStep(facts({ openQuote: { amount: 65000, sharedVia: "sent", validUntil: ahead(6), status: "issued" } }));
    expect(s.key).toBe("quote_expiring");
    expect(s.why).toContain("₹65,000");
    expect(s.actions[0]).toBe("call");
  });

  it("an expired quote asks for a fresh quote", () => {
    const s = deriveNextStep(facts({ openQuote: { amount: 65000, sharedVia: "sent", validUntil: ago(1), status: "issued" } }));
    expect(s.key).toBe("quote_expired");
    expect(s.actions[0]).toBe("quote");
  });

  it("a saved but unsent quote asks to send it", () => {
    expect(deriveNextStep(facts({ openQuote: { amount: 60000, sharedVia: null, status: "issued" } })).key).toBe("send_quote");
  });

  const SOLD = { key: "sold", label: "Sold", category: "valid", is_closed_won: true };
  const ANJALI = { id: "b1", outstanding: 45500, checkIn: "2026-10-24", checkOut: "2026-10-26", propertyName: "Ratha 1" };

  it("a live booking on a lead that is not Sold asks to mark it Sold, even with a quote open", () => {
    const s = deriveNextStep(facts({ name: "Anjali", stage: { key: "responding", label: "Responding", category: "valid" }, booking: ANJALI,
      openQuote: { amount: 35000, sharedVia: "sent", validUntil: ahead(40), status: "issued" } }));
    expect(s.key).toBe("mark_sold");
    expect(s.title).toBe("Anjali is booked on Ratha 1, 24–26 Oct · mark this lead Sold");
    expect(s.actions).toEqual(["mark_sold", "open_booking"]);
    expect(s.title).not.toContain("35,000");
  });

  it("a live booking beats an unanswered message too", () => {
    expect(deriveNextStep(facts({ booking: ANJALI, lastInboundAt: ago(1), lastOutboundAt: ago(5) })).key).toBe("mark_sold");
  });

  it("Sold with money due asks to collect it before pickup; paid is done", () => {
    const due = deriveNextStep(facts({ stage: SOLD, booking: ANJALI }));
    expect(due.title).toBe("Collect ₹45,500 before pickup");
    expect(due.actions[0]).toBe("open_booking");
    const paid = deriveNextStep(facts({ stage: SOLD, booking: { ...ANJALI, outstanding: 0 } }));
    expect(paid.key).toBe("booked");
    expect(paid.tone).toBe("done");
  });

  it("a lost lead whose person is booked points at the booking, not at nothing", () => {
    const s = deriveNextStep(facts({ stage: { key: "lost", label: "Lost", is_closed_lost: true }, booking: ANJALI }));
    expect(s.key).toBe("booked_lead_closed");
    expect(s.actions).toEqual(["open_booking"]);
  });

  it("Sold with only a finished trip is done, not missing a booking", () => {
    expect(deriveNextStep(facts({ stage: SOLD, pastBooking: true })).key).toBe("trip_done");
  });

  it("sold with no booking linked asks for the booking", () => {
    expect(deriveNextStep(facts({ stage: { key: "sold", label: "Sold", is_closed_won: true } })).key).toBe("add_booking");
  });

  it("two unanswered calls switch to WhatsApp", () => {
    const s = deriveNextStep(facts({ unansweredOutboundCalls: 2 }));
    expect(s.key).toBe("no_answer");
    expect(s.actions[0]).toBe("message");
  });

  it("never offers Call without a phone number", () => {
    const s = deriveNextStep(facts({ hasPhone: false, lastInboundAt: ago(40), lastOutboundAt: ago(30) }));
    expect(s.key).toBe("ask_number");
    expect(s.actions).not.toContain("call");
  });

  it("a pending AI draft is reviewed before anything else open", () => {
    expect(deriveNextStep(facts({ pendingDrafts: 1, lastInboundAt: ago(1), lastOutboundAt: ago(5) })).key).toBe("review_draft");
  });
});

describe("leadTemperature", () => {
  it("follows the stage first, then how recently they wrote", () => {
    expect(leadTemperature({ stage: { key: "lost", is_closed_lost: true }, now: NOW }).label).toBe("Closed");
    expect(leadTemperature({ stage: ACTIVE, booking: { id: "b" }, now: NOW }).label).toBe("Won");
    expect(leadTemperature({ stage: ACTIVE, lastInboundAt: ago(5), now: NOW }).label).toBe("Hot");
    expect(leadTemperature({ stage: ACTIVE, lastInboundAt: ago(72), now: NOW }).label).toBe("Warm");
    expect(leadTemperature({ stage: ACTIVE, lastInboundAt: ago(400), now: NOW }).label).toBe("Cold");
    expect(leadTemperature({ stage: ACTIVE, now: NOW }).label).toBe("Cold");
  });
});

describe("pickLiveBooking", () => {
  const row = (p: Partial<BookingRow>): BookingRow => ({ booking_id: "b", status: "confirmed", check_in: "2026-10-24", check_out: "2026-10-26", ...p });

  it("takes the person's live booking made on this lead, on no lead, or for this lead's dates", () => {
    expect(pickLiveBooking([row({ inquiry_id: null })], "i1", null, NOW)?.booking_id).toBe("b");
    expect(pickLiveBooking([row({ inquiry_id: "i2" })], "i1", "2026-10-24", NOW)?.booking_id).toBe("b");
    expect(pickLiveBooking([row({ booking_id: "x", inquiry_id: null }), row({ booking_id: "mine", inquiry_id: "i1", check_in: "2026-11-01", check_out: "2026-11-02" })], "i1", null, NOW)?.booking_id).toBe("mine");
  });

  it("ignores cancelled and finished stays, and another trip on another lead", () => {
    expect(pickLiveBooking([row({ status: "cancelled" })], "i1", null, NOW)).toBeNull();
    expect(pickLiveBooking([row({ status: "checked_out", check_in: "2026-02-14", check_out: "2026-02-15" })], "i1", null, NOW)).toBeNull();
    expect(pickLiveBooking([row({ check_out: "2026-10-18" })], "i1", null, NOW)).toBeNull();
    expect(pickLiveBooking([row({ inquiry_id: "i2", check_in: "2026-12-20", check_out: "2026-12-22" })], "i1", "2026-11-01", NOW)).toBeNull();
  });
});

describe("dateRange", () => {
  it("writes the month once inside a month and twice across months", () => {
    expect(dateRange("2026-10-24", "2026-10-26")).toBe("24–26 Oct");
    expect(dateRange("2026-10-30", "2026-11-02")).toBe("30 Oct – 2 Nov");
    expect(dateRange("2026-10-24", null)).toBe("24 Oct");
  });
});
