import { describe, expect, it } from "vitest";
import { autopilotHeadline, channelLabel, formatInr, groundedMissedTotal, hasActionable, ruleLabel, temperatureTone, type AutopilotEvent } from "./actionable";

const ev = (over: Partial<AutopilotEvent>): AutopilotEvent => ({
  id: "e1", status: "applied", rule: "explicit_decline", source: "rule", to_stage_label: "Lost", reason: "x", evidence: [], ...over,
});

describe("actionable helpers", () => {
  it("formats rupees in lakh grouping and skips missing values", () => {
    expect(formatInr(125000)).toBe("₹1,25,000");
    expect(formatInr(null)).toBeNull();
    expect(formatInr(Number.NaN)).toBeNull();
  });
  it("sums only grounded missed revenue", () => {
    expect(groundedMissedTotal([
      { kind: "extra_night", what: "a", est_inr: 21000, grounded: true },
      { kind: "add_on", what: "b", est_inr: 5000, grounded: false },
      { kind: "x", what: "c" },
    ])).toBe(21000);
    expect(groundedMissedTotal(undefined)).toBe(0);
  });
  it("labels channels, temperatures and rules in plain words", () => {
    expect(channelLabel("whatsapp")).toBe("WhatsApp");
    expect(channelLabel(null)).toBeNull();
    expect(temperatureTone("hot")).toBe("danger");
    expect(temperatureTone("cold")).toBe("info");
    expect(temperatureTone(undefined)).toBe("neutral");
    expect(ruleLabel("dates_passed")).toBe("Dates passed");
    expect(ruleLabel("something_new")).toBe("something new");
  });
  it("knows when there is nothing actionable to show", () => {
    expect(hasActionable(null)).toBe(false);
    expect(hasActionable({ missed_revenue: [], haip_updates: [] })).toBe(false);
    expect(hasActionable({ next_best_action: { action: "Call Kiran today" } })).toBe(true);
  });
  it("writes the autopilot headline per status", () => {
    expect(autopilotHeadline(ev({}))).toBe("Moved to Lost by autopilot");
    expect(autopilotHeadline(ev({ status: "suggested" }))).toBe("Autopilot suggests: Lost");
    expect(autopilotHeadline(ev({ status: "undone" }))).toBe("Autopilot move to Lost was undone");
    expect(autopilotHeadline(ev({ status: "blocked", to_stage_label: null }))).toBe("Autopilot held back a move to a new stage");
  });
});
