import { describe, expect, it } from "vitest";
import { canManageOps, expiryLevel, nextAction, showUnitCards, stayNextAction, whenLabel, type OpsUnit } from "./ops";

const unit = (n: number): OpsUnit[] => Array.from({ length: n }, (_, i) => ({
  property_id: String(i), name: `Ratha ${i + 1}`, tone: "ok", status: "Free", line: "", problem: null, file_id: null, ready_pct: null,
}));

describe("ops screen rules", () => {
  it("shows unit cards only for 1 to 6 units", () => {
    expect(showUnitCards(unit(0))).toBe(false);
    expect(showUnitCards(unit(2))).toBe(true);
    expect(showUnitCards(unit(6))).toBe(true);
    expect(showUnitCards(unit(7))).toBe(false);
  });

  it("says when in plain words", () => {
    expect(whenLabel({ date: "2026-10-25", time: null, now: true }, "2026-10-25")).toBe("Now");
    expect(whenLabel({ date: "2026-10-25", time: "07:00", now: false }, "2026-10-25")).toBe("Today 7 am");
    expect(whenLabel({ date: "2026-10-26", time: "18:30", now: false }, "2026-10-25")).toBe("Tomorrow 6:30 pm");
    expect(whenLabel({ date: "2026-10-28", time: null, now: false }, "2026-10-25")).toMatch(/Wed.*28.*Oct/);
  });

  it("keeps dispatch, settle and close for managers", () => {
    expect(nextAction("start", false)).toBeNull();
    expect(nextAction("start", true)).toEqual({ kind: "dispatch", label: "Dispatch" });
    expect(nextAction("close", false)).toBeNull();
    expect(nextAction("rep", true)).toMatchObject({ kind: "settle", step: "report_approved" });
    expect(nextAction("route", false)?.kind).toBe("accept");
    expect(nextAction("bal", false)?.kind).toBe("booking");
    expect(nextAction("wait", true)).toBeNull();
    expect(canManageOps("foh")).toBe(false);
  });
});

describe("expiryLevel", () => {
  it("follows the server's paper rule: 30 days amber, 7 days or past red", () => {
    expect(expiryLevel(null, "2026-10-28")).toBeNull();
    expect(expiryLevel("2026-12-28", "2026-10-28")).toBeNull();
    expect(expiryLevel("2026-11-27", "2026-10-28")).toBe("amber");
    expect(expiryLevel("2026-11-04", "2026-10-28")).toBe("red");
    expect(expiryLevel("2026-10-01", "2026-10-28")).toBe("red");
  });
});

describe("stayNextAction (villa pack)", () => {
  it("keeps check-in, the deposit, settling and closing for managers", () => {
    expect(stayNextAction("checkin", false)).toBeNull();
    expect(stayNextAction("checkin", true)?.kind).toBe("checkin");
    expect(stayNextAction("deposit", false)).toBeNull();
    expect(stayNextAction("ret", true)).toMatchObject({ kind: "settle", step: "return_checked" });
    expect(stayNextAction("close", true)?.kind).toBe("close");
  });

  it("lets the team do the rest", () => {
    expect(stayNextAction("people", false)?.kind).toBe("people");
    expect(stayNextAction("meals", false)?.kind).toBe("meals");
    expect(stayNextAction("checkout", false)?.kind).toBe("checkout");
    expect(stayNextAction("bal", false)?.kind).toBe("booking");
    expect(stayNextAction("wait", true)).toBeNull();
  });
});
