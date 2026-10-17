import { describe, it, expect } from "vitest";
import { unitState } from "./TodayStrip";

const T = "2026-10-17";
const row = (stays: object[] = [], blocks: object[] = []) =>
  ({ property_id: "p1", property_name: "Ratha 1", stays, blocks }) as Parameters<typeof unitState>[0];
const stay = (check_in: string, check_out: string, status = "confirmed", guest_name = "Vikram Pillai") =>
  ({ id: check_in, check_in, check_out, status, guest_name, adults: 2 });

describe("unitState", () => {
  it("is free with nothing on it", () => {
    expect(unitState(row(), T)).toEqual({ kind: "free" });
  });
  it("is out while a stay spans today (check-out day exclusive)", () => {
    expect(unitState(row([stay("2026-10-15", "2026-10-19")]), T)).toEqual({ kind: "out", guest: "Vikram Pillai", until: "2026-10-19" });
  });
  it("prefers the stay that starts today over the one that ends today", () => {
    const s = unitState(row([stay("2026-10-14", T, "confirmed", "Asha"), stay(T, "2026-10-20", "confirmed", "Meera")]), T);
    expect(s).toEqual({ kind: "starts", guest: "Meera", until: "2026-10-20" });
  });
  it("reports a return when the only stay ends today", () => {
    expect(unitState(row([stay("2026-10-14", T)]), T)).toEqual({ kind: "back", guest: "Vikram Pillai" });
  });
  it("ignores cancelled stays", () => {
    expect(unitState(row([stay("2026-10-15", "2026-10-19", "cancelled")]), T)).toEqual({ kind: "free" });
  });
  it("shows a block's calendar title, else maintenance or blocked", () => {
    const b = { id: "b", blocked_from: "2026-10-16", blocked_to: "2026-10-18", reason: "maintenance", event: null };
    expect(unitState(row([], [b]), T)).toEqual({ kind: "blocked", why: "Maintenance" });
    expect(unitState(row([], [{ ...b, reason: "other", event: { title: "Goa trip" } }]), T)).toEqual({ kind: "blocked", why: "Goa trip" });
  });
});
