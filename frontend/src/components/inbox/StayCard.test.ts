import { describe, it, expect } from "vitest";
import { pickStay, type BookingRow } from "./StayCard";

const T = "2026-10-17";
const b = (id: string, checkin: string, checkout: string, status = "confirmed"): BookingRow => ({ id, checkin, checkout, status });

describe("pickStay", () => {
  it("prefers a stay in progress over an upcoming one", () => {
    expect(pickStay([b("next", "2026-10-25", "2026-10-27"), b("now", "2026-10-16", "2026-10-19")], T)).toEqual({ row: b("now", "2026-10-16", "2026-10-19"), when: "now" });
  });
  it("marks a stay that starts today as arriving today", () => {
    const r = pickStay([b("later", "2026-11-02", "2026-11-04"), b("today", T, "2026-10-19")], T);
    expect(r?.row.id).toBe("today");
    expect(r?.when).toBe("today");
  });
  it("otherwise picks the soonest upcoming stay", () => {
    expect(pickStay([b("later", "2026-11-02", "2026-11-04"), b("soon", "2026-10-20", "2026-10-22")], T)).toEqual({ row: b("soon", "2026-10-20", "2026-10-22"), when: "next" });
  });
  it("treats the check-out day as over and ignores cancelled and past stays", () => {
    expect(pickStay([b("left", "2026-10-14", T), b("x", "2026-10-20", "2026-10-22", "cancelled"), b("old", "2026-09-01", "2026-09-03")], T)).toBeNull();
  });
  it("accepts full timestamps as well as plain dates", () => {
    expect(pickStay([b("ts", "2026-10-16T00:00:00", "2026-10-18T00:00:00")], T)?.when).toBe("now");
  });
});
