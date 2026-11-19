import { describe, expect, it } from "vitest";
import { repeatLine } from "./PublishPanel";

describe("repeat posts line", () => {
  it("says which run it is and how many are left", () => {
    expect(repeatLine({ run: 0, repeat_every_days: null, repeat_left: null })).toBe("");
    expect(repeatLine({ run: 0, repeat_every_days: 28, repeat_left: 3 })).toBe("first post · 3 more, every 4 weeks");
    expect(repeatLine({ run: 2, repeat_every_days: 14, repeat_left: 1 })).toBe("repeat 2 · 1 more, every 2 weeks");
    expect(repeatLine({ run: 3, repeat_every_days: 14, repeat_left: 0 })).toBe("repeat 3 · last one");
  });
});
