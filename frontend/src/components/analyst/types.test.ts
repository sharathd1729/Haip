import { describe, expect, it } from "vitest";
import { STATUS_LABEL, STATUS_TONE, pct, periodText } from "./types";

describe("analyst helpers", () => {
  it("never shows a fake percentage for missing data", () => {
    expect(pct(null)).toBe("No data");
    expect(pct(undefined)).toBe("No data");
    expect(pct(0)).toBe("0%");
    expect(pct(0.4235)).toBe("42%");
  });
  it("names the period in IST", () => {
    expect(periodText({ from: "2026-10-19", to: "2026-10-19" })).toBe("19 Oct");
    expect(periodText({ from: "2026-10-12", to: "2026-10-18" })).toBe("12 Oct – 18 Oct");
  });
  it("every health status has words, not only a colour", () => {
    for (const s of ["green", "amber", "red", "no_data"] as const) {
      expect(STATUS_LABEL[s]).toBeTruthy();
      expect(STATUS_TONE[s]).toBeTruthy();
    }
  });
});
