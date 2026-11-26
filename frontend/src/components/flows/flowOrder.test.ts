import { describe, expect, it } from "vitest";
import { describeDelay, splitDelay } from "./flowOrder";

describe("flow waits", () => {
  it("describes and splits waits", () => {
    expect(describeDelay(1440)).toBe("Wait 1 day");
    expect(describeDelay(4320)).toBe("Wait 3 days");
    expect(describeDelay(90)).toBe("Wait 90 min");
    expect(splitDelay(120)).toEqual({ amount: 2, unit: "hours" });
  });
});
