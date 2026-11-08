import { describe, expect, it } from "vitest";
import type { OpsStaff } from "@/lib/ops";
import {
  buildWeek, chainTimes, countGaps, mondayOf, moveStep, stepWords, weekDates, withOwnerLast,
  type ShiftOverride, type ShiftPattern,
} from "./opsRoster";

const person = (id: string, name: string, duty: string): OpsStaff => ({
  id, name, phone_e164: "+910000000000", active: true, whatsapp_opt_in_at: null, notes: null,
  duties: [{ duty, property_id: null }], licence_number: null, licence_expires_on: null,
});
const pat = (id: string, staff_id: string, duty: string, weekday: number, start: number, end: number): ShiftPattern => ({
  id, staff_id, duty, property_id: null, weekday, start_minute: start * 60, end_minute: end * 60, active: true,
});
const MON = "2026-11-09";
const staff = [person("ak", "Anil", "caretaker"), person("sn", "Suresh", "caretaker"), person("mn", "Meera", "fnb")];

describe("week dates", () => {
  it("finds the Monday and the seven days", () => {
    expect(mondayOf("2026-11-11")).toBe(MON);
    expect(mondayOf(MON)).toBe(MON);
    expect(mondayOf("2026-11-15")).toBe(MON);
    expect(weekDates(MON)).toEqual(["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"]);
  });
});

describe("buildWeek", () => {
  const patterns = [
    ...[0, 1, 2, 3, 4, 5].map(wd => pat(`mn${wd}`, "mn", "fnb", wd, 6, 14)),
    pat("ak0", "ak", "caretaker", 0, 7, 15),
    pat("sn4", "sn", "caretaker", 4, 23, 7),
  ];

  it("puts shifts in their day, marks night shifts and flags a day with nobody", () => {
    const rows = buildWeek(MON, patterns, [], staff);
    expect(rows.map(r => r.duty)).toEqual(["caretaker", "fnb"]);
    const care = rows[0];
    expect(care.cells[0]).toMatchObject([{ kind: "shift", name: "Anil", time: "07:00-15:00" }]);
    expect(care.cells[4]).toMatchObject([{ kind: "night", name: "Suresh", time: "23:00-07:00" }]);
    expect(care.cells[1]).toMatchObject([{ kind: "gap" }]);
    expect(rows[1].cells[6]).toMatchObject([{ kind: "gap" }]); // kitchen works six days, not Sunday
    expect(countGaps(rows, 6)).toBe(2);
  });

  it("shows leave instead of the shift, and that day becomes a gap", () => {
    const leave: ShiftOverride = { id: "o1", staff_id: "mn", kind: "leave", starts_at: "2026-11-10T18:30:00Z", ends_at: "2026-11-11T18:30:00Z", duty: null, replacement_staff_id: null };
    const kitchen = buildWeek(MON, patterns, [leave], staff)[1];
    expect(kitchen.cells[2].map(i => i.kind)).toEqual(["leave", "gap"]); // Wed 11 Nov, IST
    expect(kitchen.cells[1][0].kind).toBe("shift");
    expect(kitchen.cells[3][0].kind).toBe("shift");
  });

  it("shows the cover on a swap and adds an extra shift", () => {
    const swap: ShiftOverride = { id: "o2", staff_id: "ak", kind: "swap", starts_at: "2026-11-08T18:30:00Z", ends_at: "2026-11-09T18:30:00Z", duty: null, replacement_staff_id: "sn" };
    const extra: ShiftOverride = { id: "o3", staff_id: "ak", kind: "extra", starts_at: "2026-11-10T04:30:00Z", ends_at: "2026-11-10T12:30:00Z", duty: "caretaker", replacement_staff_id: null };
    const care = buildWeek(MON, patterns, [swap, extra], staff)[0];
    expect(care.cells[0]).toMatchObject([{ kind: "leave", name: "Anil" }, { kind: "shift", name: "Suresh", note: "covering Anil" }]);
    expect(care.cells[1]).toMatchObject([{ kind: "shift", name: "Anil", time: "10:00-18:00", note: "extra shift" }]);
  });

  it("lists a duty someone holds even before any shift is set, without inventing gaps", () => {
    const rows = buildWeek(MON, [], [], [person("rs", "Ravi", "driver")]);
    expect(rows).toHaveLength(1);
    expect(rows[0].cells.every(c => c.length === 0)).toBe(true);
  });
});

describe("chain", () => {
  it("times each step: first one at once, empty steps skipped, the rest after each wait", () => {
    expect(chainTimes([{ recipients: ["Suresh"] }, { recipients: [] }, { recipients: ["Deepa"] }, { recipients: ["You"] }], 15)).toEqual([0, null, 15, 30]);
    expect(chainTimes([{ recipients: [] }, { recipients: ["Deepa"] }, { recipients: ["You"] }], 60)).toEqual([null, 0, 60]);
  });

  it("always saves the owner last, once", () => {
    const steps = withOwnerLast([{ type: "role", role: "owner" }, { type: "on_shift" }, { type: "role", role: "manager" }]);
    expect(steps).toEqual([{ type: "on_shift" }, { type: "role", role: "manager" }, { type: "role", role: "owner" }]);
  });

  it("moves a step and stays put at the ends", () => {
    expect(moveStep(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
    expect(moveStep(["a", "b"], 0, -1)).toEqual(["a", "b"]);
  });

  it("names each step in plain words", () => {
    const name = (id: string) => (id === "ak" ? "Anil" : undefined);
    expect(stepWords({ type: "on_shift" }, "caretaker", name)).toBe("Whoever is on shift (helper / caretaker)");
    expect(stepWords({ type: "on_shift", duty: "ops_manager" }, "caretaker", name)).toBe("Ops manager on shift");
    expect(stepWords({ type: "staff", staff_id: "ak" }, "caretaker", name)).toBe("Anil");
    expect(stepWords({ type: "role", role: "manager" }, "caretaker", name)).toBe("Managers");
  });
});
