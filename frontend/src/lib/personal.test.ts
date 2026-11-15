import { describe, expect, it } from "vitest";
import { calendarLink, chatGroup, citeOrder, dayLabel, dueLabel, durationLabel, groupByDay, istDay, momentHref, momentLabel, monthGrid, ownerLabel, refKey, shiftMonth, splitCites, withoutCites } from "./personal";

// 14 Nov 2026, 01:30 IST = 13 Nov 20:00 UTC: the IST day differs from the UTC day, which is the case that breaks.
const NOW = new Date("2026-11-13T20:00:00Z");

describe("personal call helpers", () => {
  it("reads days in IST", () => {
    expect(istDay(NOW)).toBe("2026-11-14");
    expect(dayLabel("2026-11-14", NOW)).toBe("Today");
    expect(dayLabel("2026-11-13", NOW)).toBe("Yesterday");
    expect(dayLabel("2026-11-15", NOW)).toBe("Tomorrow");
    expect(dayLabel("2026-11-10", NOW)).toMatch(/10 Nov/);
    expect(dayLabel("2025-11-10", NOW)).toMatch(/2025/);
  });

  it("says when a reminder is due or late", () => {
    expect(dueLabel("", NOW)).toEqual({ text: "", overdue: false });
    expect(dueLabel("2026-11-14", NOW)).toEqual({ text: "Due today", overdue: false });
    expect(dueLabel("2026-11-15", NOW)).toEqual({ text: "Due tomorrow", overdue: false });
    expect(dueLabel("2026-11-12", NOW).overdue).toBe(true);
  });

  it("formats durations and owners", () => {
    expect(durationLabel(45)).toBe("45 s");
    expect(durationLabel(741)).toBe("12 min");
    expect(durationLabel(3900)).toBe("1 h 5 min");
    expect(ownerLabel("me")).toBe("You");
    expect(ownerLabel("Prashant")).toBe("Prashant");
  });

  it("builds Google Calendar links", () => {
    const timed = new URL(calendarLink({ title: "Catering tasting", date: "2026-11-16", time: "16:00", place: "Indiranagar" }));
    expect(timed.searchParams.get("dates")).toBe("20261116T160000/20261116T170000");
    expect(timed.searchParams.get("ctz")).toBe("Asia/Kolkata");
    expect(timed.searchParams.get("location")).toBe("Indiranagar");
    const allDay = new URL(calendarLink({ title: "Send the guest count", date: "2026-11-30" }));
    expect(allDay.searchParams.get("dates")).toBe("20261130/20261201");
  });

  it("groups calls by IST day, newest first", () => {
    const rows = [
      { id: "a", at: "2026-11-13T19:00:00Z" }, // 14 Nov 00:30 IST
      { id: "b", at: "2026-11-13T17:00:00Z" }, // 13 Nov 22:30 IST
      { id: "c", at: "2026-11-13T05:00:00Z" }, // 13 Nov 10:30 IST
    ];
    expect(groupByDay(rows).map(g => [g.day, g.rows.map(r => r.id)])).toEqual([
      ["2026-11-14", ["a"]],
      ["2026-11-13", ["b", "c"]],
    ]);
  });
});

describe("calendar grid", () => {
  it("starts on the Monday on or before the 1st and covers 6 weeks", () => {
    const days = monthGrid("2026-11"); // 1 Nov 2026 is a Sunday
    expect(days[0]).toBe("2026-10-26");
    expect(days[6]).toBe("2026-11-01");
    expect(days).toHaveLength(42);
    expect(days[41]).toBe("2026-12-06");
  });
  it("moves across years", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  });
});

describe("references", () => {
  it("matches the backend key and labels moments", () => {
    expect(refKey("  Book the   Venue ")).toBe("book the venue");
    expect(momentLabel(42.7)).toBe("0:42");
    expect(momentLabel(3729)).toBe("1:02:09");
    expect(momentHref("c1", 41.5)).toBe("/dashboard/me/calls/c1?t=41");
    expect(momentHref("c1")).toBe("/dashboard/me/calls/c1");
  });
  it("numbers sourced points in reading order", () => {
    const order = citeOrder({
      decision: "Host them", sections: [{ heading: "A", bullets: ["no source", "Arrives 21st"] }],
      action_items: [{ id: "1", text: "Book venue", owner: "me", due: "", context: "", done: false, done_at: null }],
      open_points: [], upcoming: [],
      refs: { "arrives 21st": { at: 41, quote: "x" }, "book venue": { at: 60, quote: "y" } },
    });
    expect([...order.entries()]).toEqual([["arrives 21st", 1], ["book venue", 2]]);
  });
  it("splits and strips [n] markers", () => {
    expect(splitCites("Ravi agreed [1]. Price [2][1].")).toEqual(["Ravi agreed ", 1, ". Price ", 2, 1, "."]);
    expect(withoutCites("Ravi agreed [1]. Price [2][1].")).toBe("Ravi agreed. Price.");
  });
  it("groups chats by day", () => {
    const now = new Date("2026-11-15T06:00:00Z");
    expect(chatGroup("2026-11-15T03:00:00Z", now)).toBe("Today");
    expect(chatGroup("2026-11-14T03:00:00Z", now)).toBe("Yesterday");
    expect(chatGroup("2026-11-10T03:00:00Z", now)).toBe("Previous 7 days");
    expect(chatGroup("2026-09-10T03:00:00Z", now)).toBe("September 2026");
  });
});
