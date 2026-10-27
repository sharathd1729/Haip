import { describe, it, expect } from "vitest";
import { reasonNeeded, stageErrorText } from "./stageMove";

const st = (order: number, won = false, lost = false) => ({ order, is_closed_won: won, is_closed_lost: lost });

describe("stage moves", () => {
  it("asks for a reason to reopen a lost lead or move back; never for Sold or forward", () => {
    expect(reasonNeeded(st(6, false, true), st(2))).toBe("reopen");
    expect(reasonNeeded(st(3), st(2))).toBe("back");
    expect(reasonNeeded(st(2), st(3))).toBeNull();
    expect(reasonNeeded(st(5, true), st(2))).toBeNull();              // Sold: the backend refuses, no reason form
    expect(reasonNeeded(st(6, false, true), st(5, true))).toBeNull();
  });

  it("shows the backend's own words", () => {
    expect(stageErrorText({ response: { data: { detail: "Only an owner or manager can reopen a lost lead." } } }, "x"))
      .toBe("Only an owner or manager can reopen a lost lead.");
    expect(stageErrorText({ response: { data: { detail: { code: "outcome_reason_required", message: "Say why" } } } }, "x")).toBe("Say why");
    expect(stageErrorText(new Error("A reason is required to reopen a lost lead."), "x")).toBe("A reason is required to reopen a lost lead.");
    expect(stageErrorText({}, "fallback")).toBe("fallback");
  });
});
