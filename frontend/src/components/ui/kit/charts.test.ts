import { describe, expect, it } from "vitest";
import { niceMax } from "./MiniBars";
import { sparkPath } from "./Sparkline";

describe("sparkPath", () => {
  it("needs two points", () => {
    expect(sparkPath([])).toBeNull();
    expect(sparkPath([5])).toBeNull();
  });

  it("starts at the left pad, ends on the last value, and never leaves its box", () => {
    const w = 48, h = 18, pad = 2.5;
    const path = sparkPath([0, 11, 5, 0, 0, 0, 3], w, h, pad)!;
    expect(path.d.startsWith("M2.5,15.5")).toBe(true);      // first value is the minimum: bottom-left
    expect(path.last[0]).toBeCloseTo(w - pad);
    const ys = [...path.d.matchAll(/,(-?[\d.]+)/g)].map(m => Number(m[1]));
    // monotone curve: control points stay between the lowest and highest real value
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(pad - 0.05);
    expect(Math.max(...ys)).toBeLessThanOrEqual(h - pad + 0.05);
  });

  it("draws a flat line for equal values", () => {
    const ys = [...sparkPath([4, 4, 4])!.d.matchAll(/,(-?[\d.]+)/g)].map(m => Number(m[1]));
    expect(new Set(ys).size).toBe(1);
  });
});

describe("niceMax", () => {
  it("rounds an axis up to a round number at or above the value", () => {
    expect([0, 2, 4, 5, 11, 40, 41, 99, 100, 101].map(niceMax)).toEqual([4, 4, 4, 5, 20, 40, 50, 100, 100, 200]);
  });
});
