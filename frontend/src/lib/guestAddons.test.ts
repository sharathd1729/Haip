import { describe, expect, it } from "vitest";
import { daysToGo, greeting, inr, payLabel, receipt, type AddonOffer } from "./guestAddons";

const offer = (o: Partial<AddonOffer>): AddonOffer => ({
  id: "x", name: "X", description: null, category: null, price: 1000, price_type: "per_stay", unit: "once",
  default_quantity: 1, max_quantity: 1, needs_approval: false, stay_change: null, available: true, unavailable_reason: null, ...o,
});

describe("guest add-ons receipt", () => {
  const offers = [
    offer({ id: "bbq", name: "Barbecue", price: 1200, price_type: "per_person", max_quantity: 20 }),
    offer({ id: "cook", name: "Cook", price: 3000, price_type: "per_night", needs_approval: true, max_quantity: 2 }),
    offer({ id: "night", name: "Extra night", price: 14500, available: false }),
  ];

  it("splits pay-now from items the team confirms first and skips unavailable ones", () => {
    const r = receipt(offers, { bbq: 4, cook: 2, night: 1 });
    expect(r.payNow).toBe(4800);
    expect(r.later).toBe(6000);
    expect(r.lines.map(l => l.detail)).toEqual(["4 people", "2 nights · we confirm first"]);
  });

  it("labels the button by what happens", () => {
    expect(payLabel(4800, 6000)).toBe("Pay ₹4,800");
    expect(payLabel(0, 6000)).toBe("Send request");
    expect(payLabel(0, 0)).toBe("Pick an add-on");
    expect(inr(125000)).toBe("₹1,25,000");
  });

  it("counts days to check-in and greets accordingly", () => {
    expect(daysToGo("2026-11-14", "2026-11-08")).toBe(6);
    expect(greeting("Meera", 6)).toBe("Hi Meera, 6 days to go");
    expect(greeting("Meera", 0)).toBe("Hi Meera, welcome today");
    expect(greeting("Meera", -1)).toBe("Hi Meera, enjoy your stay");
  });
});
