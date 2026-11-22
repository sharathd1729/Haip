import { describe, expect, it } from "vitest";
import { costLine, MODE_LABELS, ROW_TEXT, rupees } from "./aiSwitches";

describe("Settings > AI cost text", () => {
  it("shows rupees in the Indian style and keeps paise on small amounts", () => {
    expect(rupees(0.005, 88)).toBe("₹0.44");
    expect(rupees(1420.5, 88)).toBe("₹1,25,004");
  });

  it("says why a row has no cost of its own, and says Not used for zero uses", () => {
    expect(costLine({ cost_usd: null, uses: null, cost_unknown_uses: null, cost_note: "not_metered" }, 88)).toMatch(/not tracked/);
    expect(costLine({ cost_usd: null, uses: null, cost_unknown_uses: null, cost_note: "in_lead_summaries" }, 88)).toMatch(/Lead summaries/);
    expect(costLine({ cost_usd: 0, uses: 0, cost_unknown_uses: 0 }, 88)).toBe("Not used");
  });

  it("counts uses and flags unknown costs instead of guessing them", () => {
    expect(costLine({ cost_usd: 1, uses: 1, cost_unknown_uses: 0 }, 88)).toBe("₹88.00 · 1 use");
    expect(costLine({ cost_usd: 2, uses: 12, cost_unknown_uses: 3 }, 88)).toBe("₹176 · 12 uses (3 with unknown cost)");
  });

  it("has a plain-language line for every switch the backend sends", () => {
    const keys = [
      "whatsapp_replies", "instagram_dm_replies", "instagram_comment_replies", "call_analysis", "call_transcription",
      "lead_summaries", "personal_whatsapp_summaries", "lead_autopilot", "briefings",
      "ask_haip", "marketing", "website", "operations", "personal_assistant", "core",
    ];
    for (const k of keys) expect(ROW_TEXT[k]?.does.length).toBeGreaterThan(10);
    expect(MODE_LABELS.shadow).toBe("Draft for staff");
  });
});
