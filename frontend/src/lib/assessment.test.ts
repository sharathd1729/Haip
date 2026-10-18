import { describe, expect, it } from "vitest";
import { DEFAULT_ANSWERS, answersProblem, months, plotSqft, reportPdfUrl, segmentFor, toggle } from "./assessment";

describe("segmentFor (same rule as the backend)", () => {
  it.each([[4999, "small"], [5000, "medium"], [43559, "medium"], [43560, "large"]] as const)("%i sq ft -> %s", (sqft, seg) => {
    expect(segmentFor(sqft)).toBe(seg);
  });
  it("converts acres", () => {
    expect(plotSqft({ plot_size: 2, plot_unit: "acres" })).toBe(87120);
  });
});

describe("answersProblem", () => {
  const ok = { ...DEFAULT_ANSWERS, city: "Madikeri" };
  it("accepts sensible answers", () => expect(answersProblem(ok)).toBeNull());
  it("explains what to fix", () => {
    expect(answersProblem({ ...ok, plot_size: 100, plot_unit: "sqft" })).toMatch(/500 sq ft/);
    expect(answersProblem({ ...ok, rooms: 0 })).toMatch(/at least one room/);
    expect(answersProblem({ ...ok, rooms: 0, property_type: "event_space" })).toBeNull();
    expect(answersProblem({ ...ok, rooms: 2.5 })).toMatch(/whole number/);
    expect(answersProblem({ ...ok, city: " " })).toMatch(/town or city/);
    expect(answersProblem({ ...ok, landmark_km: Number.NaN })).toMatch(/Distance/);
  });
});

describe("helpers", () => {
  it("toggles chips", () => {
    expect(toggle(["pool"], "spa")).toEqual(["pool", "spa"]);
    expect(toggle(["pool", "spa"], "pool")).toEqual(["spa"]);
  });
  it("labels payback", () => {
    expect(months(30)).toBe("30 months");
    expect(months(null)).toBe("No payback");
  });
  it("builds the PDF link with the token encoded", () => {
    expect(reportPdfUrl("a b", "t/k")).toBe("/api/v1/public/assessment/a%20b/report.pdf?token=t%2Fk");
  });
});
