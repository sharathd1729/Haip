import { describe, expect, it } from "vitest";
import { TEMPLATES } from "./templates";

describe("Instagram automation templates", () => {
  it("never mention a price, so a workspace's price rule decides", () => {
    for (const t of TEMPLATES) {
      const text = [t.message, ...(t.sequence ?? []).map(s => s.text)].join(" ");
      expect(text).not.toMatch(/₹|\bRs\.?\s?\d|\bINR\b|\d{3,}/);
    }
  });
  it("leave link buttons for the owner to fill in, and ask for the number when they collect details", () => {
    for (const t of TEMPLATES) {
      if (t.button) expect(t.button.url).toBe("");
      if (t.form?.enabled) expect(t.form.questions.filter(q => q.key === "phone")).toHaveLength(1);
    }
  });
});
