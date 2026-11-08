import { describe, expect, it } from "vitest";
import { num, pctChange, positionChange } from "./websiteGoogle";

describe("websiteGoogle helpers", () => {
  it("shows No data for null, never 0", () => {
    expect(num(null)).toBe("No data");
    expect(num(undefined)).toBe("No data");
    expect(num(0)).toBe("0");
    expect(num(125000)).toBe("1,25,000");
  });
  it("lower position is better", () => {
    expect(positionChange(3, 5.5)).toEqual({ text: "up 2.5", tone: "success" });
    expect(positionChange(8, 6)).toEqual({ text: "down 2", tone: "danger" });
    expect(positionChange(4, 4)).toEqual({ text: "no change", tone: "neutral" });
    expect(positionChange(null, 4)).toBeNull();
    expect(positionChange(4, null)).toBeNull();
  });
  it("no change shown without a baseline", () => {
    expect(pctChange(null)).toBeNull();
    expect(pctChange(12.5)?.text).toBe("+12.5% vs previous");
    expect(pctChange(-50)?.tone).toBe("danger");
  });
});
