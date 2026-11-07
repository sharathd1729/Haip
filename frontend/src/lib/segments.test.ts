import { describe, it, expect } from "vitest";
import { SEGMENTS, placeholderLabel, segmentFor } from "./segments";

describe("segment profile", () => {
  it("maps every business type to its own experience, and anything unknown or loading to a plain property", () => {
    expect(segmentFor("caravan").key).toBe("caravan");
    expect(segmentFor("villa_resort").key).toBe("villa");
    expect(segmentFor("homestay").key).toBe("homestay");
    expect(segmentFor("hotel").key).toBe("hotel");
    expect(segmentFor(null).key).toBe("property");
    expect(segmentFor("farmhouse" as never).key).toBe("property");
  });

  it("keeps the caravan words and sections exactly as they are today", () => {
    const c = segmentFor("caravan");
    expect([c.unit.one, c.booking.one, c.timing, c.notChosen, c.nobodyIn]).toEqual(
      ["vehicle", "trip", "noon to noon", "Unassigned (vehicle not chosen yet)", "Nobody is on a trip right now"]);
    expect(c.sections.bookingDetail).toMatchObject({ route: true, kmAndDriver: true });
    expect(c.sections.calendar).toEqual({ channelFilter: false, rentalwiseSync: false });
    expect(placeholderLabel(c)).toBe("Unassigned");
  });

  it("gives a villa business villa and stay words and a stay card, never caravan ones", () => {
    const v = segmentFor("villa_resort");
    expect([v.unit.one, v.unit.Many, v.booking.one, v.start, v.end, v.whichUnit, v.notChosen, v.nobodyIn, v.allUnits]).toEqual(
      ["villa", "Villas", "stay", "check-in", "check-out", "Which villa?", "Unassigned (villa not chosen yet)", "Nobody is staying right now", "All villas"]);
    expect(v.card).toEqual(["dates", "nights", "guests", "unit", "caretaker", "deposit", "balance"]);
    expect(v.sections.bookingDetail).toMatchObject({ route: false, kmAndDriver: false });
    expect(placeholderLabel(v)).toBe("Which villa?");
  });

  it("no stay segment carries a caravan-only card field or word", () => {
    for (const s of Object.values(SEGMENTS).filter(s => s.key !== "caravan")) {
      expect(s.card.some(f => f === "route" || f === "km" || f === "driver")).toBe(false);
      expect(JSON.stringify(s)).not.toMatch(/\b(vehicles?|trips?)\b|noon to noon/);
    }
  });
});
