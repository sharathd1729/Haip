import { describe, expect, it } from "vitest";
import { change } from "./AutomationsOverview";

describe("change vs the period before", () => {
  it("never shows a percentage against an empty earlier period", () => {
    expect(change(5, 0)).toEqual({ text: "new", tone: "info" });
    expect(change(0, 0)).toBeNull();
  });
  it("shows a signed percentage otherwise", () => {
    expect(change(118, 100)).toEqual({ text: "+18%", tone: "success" });
    expect(change(50, 100)).toEqual({ text: "-50%", tone: "danger" });
    expect(change(100, 100)).toEqual({ text: "same", tone: "neutral" });
  });
});
