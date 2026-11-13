import { describe, expect, it } from "vitest";
import { dayLabel, dueLabel, durationLabel, groupByDay, istDay, ownerLabel } from "./personal";

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
