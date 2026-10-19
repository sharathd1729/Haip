import { describe, it, expect } from "vitest";
import { deriveNextStep, leadTemperature, type NextStepFacts } from "./leadNextStep";

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

  it("a booking with money due asks to collect it; a paid one is done", () => {
    expect(deriveNextStep(facts({ booking: { id: "b1", outstanding: 32500 } })).title).toBe("Collect ₹32,500 still due");
    const paid = deriveNextStep(facts({ booking: { id: "b1", outstanding: 0 } }));
    expect(paid.key).toBe("booked");
    expect(paid.tone).toBe("done");
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
