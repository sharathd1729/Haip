import { describe, expect, it } from "vitest";
import {
  buildEvents, clock, filterParams, freeColumns, groupByDay, isOverdue, lakh, moneyChip, newBookingHref, stripBlocks,
  NO_FILTERS, type AgendaRow, type Occupancy,
} from "./bookingAgenda";

const TODAY = "2026-10-19";

function row(p: Partial<AgendaRow> & { id: string }): AgendaRow {
  return {
    external_id: "1", checkin: TODAY, checkout: "2026-10-21", adults: 2, children: 0, status: "confirmed", raw_status: "confirmed",
    payment_status: "partial", total: 70000, total_paid: 35000, total_outstanding: 35000,
    property: { id: "r1", name: "Ratha 1", type: "caravan" }, next_payment_due_date: null, next_payment_amount: 0, payment_overdue: false,
    main_guest: { id: "g", first_name: p.id, last_name: "", phone: "+919800000001", email: null }, channel: "direct", created_at: null,
    inquiry_id: null, trip: null, deposit: null, check_in_time: "12:00", check_out_time: "12:00",
    ...p,
  };
}

describe("agenda day rows", () => {
  it("lists check-ins and check-outs by day in time order, with the check-outs of guests staying now", () => {
    const neha = row({ id: "Neha", checkin: "2026-10-20", checkout: "2026-10-22" });
    const rohan = row({ id: "Rohan", checkin: TODAY, checkout: TODAY, check_in_time: "16:00", check_out_time: "22:00" });
    const manisha = row({ id: "Manisha", checkin: "2026-10-21", checkout: "2026-10-22", check_in_time: null });
    const arjun = row({ id: "Arjun", checkin: "2026-10-18", checkout: "2026-10-20", raw_status: "checked_in" });
    const ev = buildEvents([neha, rohan, manisha], "upcoming", [arjun]);
    const days = groupByDay(ev).map(d => [d.day, d.events.map(e => `${e.kind}:${e.row.id}${e.stayingNow ? "*" : ""}`)]);
    expect(days).toEqual([
      [TODAY, ["in:Rohan"]],                                   // a same-day trip has no separate check-out row
      ["2026-10-20", ["out:Arjun*", "in:Neha"]],                // the caravan comes back before it goes out again
      ["2026-10-21", ["in:Manisha"]],                            // no time set sorts as noon
      ["2026-10-22", ["out:Manisha", "out:Neha"]],
    ]);
  });

  it("staying now shows check-outs, past reads newest first, cancelled shows the lost check-in", () => {
    const a = row({ id: "A", checkin: "2026-10-01", checkout: "2026-10-03", raw_status: "checked_out" });
    const b = row({ id: "B", checkin: "2026-10-10", checkout: "2026-10-12", raw_status: "checked_out" });
    expect(buildEvents([a, b], "past").map(e => e.day)).toEqual(["2026-10-12", "2026-10-03"]);
    expect(buildEvents([a], "staying")[0]).toMatchObject({ kind: "out", stayingNow: true });
    expect(buildEvents([row({ id: "C", raw_status: "cancelled" })], "cancelled")[0]).toMatchObject({ kind: "cancelled", day: TODAY });
  });
});

describe("money chip", () => {
  it("check-in: collect what is due; unpaid or overdue reads as danger", () => {
    expect(moneyChip("in", row({ id: "x" }), TODAY)).toEqual({ label: "Collect ₹35,000", tone: "warning" });
    expect(moneyChip("in", row({ id: "x", payment_status: "unpaid", total_paid: 0, total_outstanding: 70000 }), TODAY)?.tone).toBe("danger");
    expect(moneyChip("in", row({ id: "x", payment_status: "paid", total_paid: 70000, total_outstanding: 0 }), TODAY)).toBeNull();
  });

  it("an overdue booking says overdue on its check-in row, not Collect (same rule as the month summary)", () => {
    // Future check-in, but an instalment of the schedule is past due: the month summary counts it as overdue.
    const fathima = row({ id: "Fathima", checkin: "2026-10-30", checkout: "2026-11-01", payment_overdue: true, total_outstanding: 9590 });
    expect(isOverdue(fathima, TODAY)).toBe(true);
    expect(moneyChip("in", fathima, TODAY)).toEqual({ label: "₹9,590 overdue", tone: "danger" });
    expect(moneyChip("out", { ...fathima, deposit: { amount: 10000, status: "held" } }, TODAY)).toEqual({ label: "₹9,590 overdue", tone: "danger" });
  });

  it("check-out: hand back a held deposit; otherwise money owed after the trip started is overdue", () => {
    const held = row({ id: "x", payment_status: "paid", total_outstanding: 0, deposit: { amount: 10000, status: "held" }, checkin: "2026-10-18" });
    expect(moneyChip("out", held, TODAY)).toEqual({ label: "Return ₹10,000 deposit", tone: "neutral" });
    expect(moneyChip("out", { ...held, raw_status: "checked_out" }, TODAY)).toBeNull();
    const owing = row({ id: "y", checkin: "2026-10-15", checkout: "2026-10-16" });
    expect(isOverdue(owing, TODAY)).toBe(true);
    expect(moneyChip("out", owing, TODAY)).toEqual({ label: "₹35,000 overdue", tone: "danger" });
    expect(moneyChip("cancelled", row({ id: "z", raw_status: "cancelled" }), TODAY)).toBeNull();
    expect(isOverdue(row({ id: "w", checkin: "2026-10-25", payment_overdue: true }), TODAY)).toBe(true);   // a past-due instalment
  });
});

describe("vehicle strip", () => {
  const v: Occupancy["vehicles"][number] = {
    property_id: "r1", name: "Ratha 1", slot: 1, placeholder: false,
    bookings: [
      { booking_id: "b1", guest_name: "Rohan Shetty", check_in: TODAY, check_out: TODAY, status: "confirmed", due: true },
      { booking_id: "b2", guest_name: "Neha Kulkarni", check_in: "2026-10-20", check_out: "2026-10-22", status: "confirmed", due: false },
      { booking_id: "b3", guest_name: "Arjun", check_in: "2026-10-15", check_out: "2026-10-20", status: "checked_in", due: false },
      { booking_id: "b4", guest_name: "Meera", check_in: "2026-11-01", check_out: "2026-11-05", status: "confirmed", due: false },
    ],
    holds: [{ from: "2026-10-25", to: "2026-10-27", reason: "maintenance" }],
  };

  it("places each booking pickup day to drop day, marks money due, and clips to the 14 days", () => {
    const blocks = stripBlocks(v, TODAY, 14);
    expect(blocks.map(b => [b.bookingId, b.label, b.start, b.span, b.due])).toEqual([
      ["b1", "Rohan", 0, 1, true],              // same-day trip fills its one day; coral marker
      ["b3", "Arjun", 0, 1, false],             // started before the strip: clipped to its first column
      ["b2", "Neha", 1, 2, false],              // 20 -> 22 Oct, noon to noon: two columns
      [null, "Maint.", 6, 2, false],            // a hold has nothing to open
      ["b4", "Meera", 13, 1, false],
    ]);
    expect(freeColumns(blocks, 14)).toEqual([3, 4, 5, 8, 9, 10, 11, 12]);
    expect(newBookingHref("r1", "2026-10-22")).toBe("/dashboard/bookings/new?property=r1&from=2026-10-22&to=2026-10-23");
  });
});

describe("helpers", () => {
  it("formats times, lakh figures and filter params", () => {
    expect(clock("16:00")).toBe("4:00 pm");
    expect(clock("00:30")).toBe("12:30 am");
    expect(clock(null)).toBeNull();
    expect(lakh(395000)).toBe("₹3.95 L");
    expect(lakh(35000)).toBe("₹35,000");
    expect(lakh(12500000)).toBe("₹1.25 Cr");
    expect(filterParams({ ...NO_FILTERS, vehicle: ["r1", "r2"], pay: ["overdue"], from: "2026-10-01" })).toEqual({
      status: undefined, payment_status: "overdue", property_id: "r1,r2", channel: undefined, check_in_from: "2026-10-01", check_in_to: undefined,
    });
  });
});
