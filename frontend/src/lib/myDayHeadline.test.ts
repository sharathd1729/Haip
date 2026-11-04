import { describe, expect, it } from "vitest";
import { myDayHeadline } from "./myDayHeadline";

describe("myDayHeadline", () => {
  it("shows the badge's number (people_waiting) as 'need action now'", () => {
    expect(myDayHeadline({ total: 60, people: 46, people_waiting: 22, unowned: 3 }))
      .toBe("46 waiting · 22 need action now · 24 older · 3 with no owner");
  });
  it("leaves out 'older' when nobody has gone cold", () => {
    expect(myDayHeadline({ total: 2, people: 2, people_waiting: 2 })).toBe("2 waiting · 2 need action now");
  });
  it("has loading and empty lines", () => {
    expect(myDayHeadline(undefined)).toBe("Loading…");
    expect(myDayHeadline({ total: 0, people: 0, people_waiting: 0 })).toBe("Nobody is waiting. Nice.");
  });
});
