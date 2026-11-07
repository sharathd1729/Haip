import { describe, it, expect } from "vitest";
import { cleanName, holdLabel, mergeHolds, nightsWord, splitWaiting, type HoldBlock } from "./calendarHolds";

const ev = (title: string, waiting = false, key?: string, guest?: string) =>
  ({ title, needs_vehicle: waiting, event_key: key, feed_name: "Demo bookings", details: guest ? { guest_name: guest } : {} });
const hold = (id: string, from: string, to: string, extra: Partial<HoldBlock> = {}): HoldBlock =>
  ({ id, blocked_from: from, blocked_to: to, reason: "offline_booking", ...extra });

describe("calendar holds", () => {
  it("cleans Google's bold and italic markers like the backend", () => {
    expect(cleanName("*Mr.Saksham*")).toBe("Mr.Saksham");
    expect(cleanName("*Ms. Ritika* / _Mr. Rahul_")).toBe("Ms. Ritika / Mr. Rahul");
    expect(cleanName("Mag/Sharma")).toBe("Mag/Sharma");
    expect(cleanName(null)).toBe("");
  });

  it("labels a calendar hold by guest, then title, and other holds by kind", () => {
    expect(holdLabel(hold("a", "2026-11-01", "2026-11-02", { event: ev("*Mag/Kapoor*") }))).toBe("Mag/Kapoor");
    expect(holdLabel(hold("a", "2026-11-01", "2026-11-02", { event: ev("Booking", false, undefined, "*Asha*") }))).toBe("Asha");
    expect(holdLabel(hold("a", "2026-11-01", "2026-11-02", { reason: "maintenance" }))).toBe("Maintenance");
    expect(holdLabel(hold("a", "2026-11-01", "2026-11-02"))).toBe("Blocked");
    expect(nightsWord("2026-11-05", "2026-11-08")).toBe("3 nights");
  });

  it("draws an event entered one night at a time as one bar, and keeps different events apart", () => {
    const merged = mergeHolds([
      hold("d2", "2026-11-06", "2026-11-07", { event: ev("Mag/Kapoor") }),
      hold("d1", "2026-11-05", "2026-11-06", { event: ev("Mag/Kapoor") }),
      hold("d3", "2026-11-07", "2026-11-08", { event: ev("*Mag/Kapoor*") }),
      hold("x", "2026-11-08", "2026-11-09", { event: ev("Other guest") }),
      hold("m", "2026-11-12", "2026-11-14", { reason: "maintenance" }),
    ]);
    expect(merged.map(m => [m.id, m.blocked_from, m.blocked_to, m.ids.length])).toEqual([
      ["d1", "2026-11-05", "2026-11-08", 3], ["x", "2026-11-08", "2026-11-09", 1], ["m", "2026-11-12", "2026-11-14", 1]]);
  });

  it("shows a 'Which villa?' event once, not on every unit, and leaves each unit its own holds", () => {
    const waitingOn = (id: string, unit: string) => hold(id, "2026-11-10", "2026-11-12", { vehicle: unit, event: ev("Mag/Sharma", true, "f:sharma") });
    const rows = [
      { name: "Villa Aster", blocks: [waitingOn("w1", "Villa Aster"), hold("a", "2026-11-05", "2026-11-08", { event: ev("Mag/Kapoor") })] },
      { name: "Neem House", blocks: [waitingOn("w2", "Neem House")] },
      { name: "Lotus Pool", blocks: [waitingOn("w3", "Lotus Pool"), hold("n1", "2026-11-17", "2026-11-18", { event: ev("Mr. Saksham", true, "f:s1") }),
        hold("n2", "2026-11-18", "2026-11-19", { event: ev("Mr. Saksham", true, "f:s2") })] },
    ];
    const out = splitWaiting(rows);
    expect(out.waiting.map(w => [holdLabel(w), w.blocked_from, w.blocked_to])).toEqual([
      ["Mag/Sharma", "2026-11-10", "2026-11-12"], ["Mr. Saksham", "2026-11-17", "2026-11-19"]]);
    expect(out.rows.map(r => r.blocks.map(b => b.id))).toEqual([["a"], [], []]);
  });
});
