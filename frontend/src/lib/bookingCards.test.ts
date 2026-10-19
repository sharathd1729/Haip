import { describe, expect, it } from "vitest";
import { dayHeading, groupCards, paidPct, payState, stayLine } from "./bookingCards";
import type { AgendaRow } from "./bookingAgenda";

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

describe("cards by date", () => {
  it("puts each booking once, under its check-in day, soonest first", () => {
    const neha = row({ id: "Neha", checkin: "2026-10-20", checkout: "2026-10-22" });
    const rohan = row({ id: "Rohan", checkin: TODAY, checkout: TODAY });
    const manisha = row({ id: "Manisha", checkin: "2026-10-20", checkout: "2026-10-21", property: { id: "r2", name: "Ratha 2", type: "caravan" } });
    const groups = groupCards([neha, rohan, manisha, neha], "upcoming", TODAY);
    expect(groups.map(g => [g.title, g.hint, g.rows.map(r => r.id)])).toEqual([
      ["Today · Mon 19 Oct", "1 check-in", ["Rohan"]],
      ["Tomorrow · Tue 20 Oct", "2 check-ins", ["Neha", "Manisha"]],      // a 2-night booking is one card, not a check-in and a check-out
    ]);
    expect(groups.flatMap(g => g.rows).filter(r => r.id === "Neha")).toHaveLength(1);
  });

  it("staying now is one group by soonest check-out; past and cancelled read newest first", () => {
    const a = row({ id: "A", checkin: "2026-10-17", checkout: "2026-10-21", raw_status: "checked_in" });
    const b = row({ id: "B", checkin: "2026-10-18", checkout: "2026-10-20", raw_status: "checked_in" });
    expect(groupCards([a, b], "staying", TODAY).map(g => [g.title, g.rows.map(r => r.id)])).toEqual([["On a trip now", ["B", "A"]]]);
    const old = row({ id: "Old", checkin: "2026-10-01", raw_status: "checked_out" });
    const recent = row({ id: "Recent", checkin: "2026-10-11", raw_status: "checked_out" });
    expect(groupCards([old, recent], "past", TODAY).map(g => g.title)).toEqual(["Sun 11 Oct", "Thu 1 Oct"]);
    expect(dayHeading("2026-10-18", TODAY)).toBe("Yesterday · Sun 18 Oct");
  });

  it("writes the stay in one line", () => {
    expect(stayLine({ checkin: "2026-10-24", checkout: "2026-10-26", check_in_time: "12:00", check_out_time: "12:00" })).toBe("24 → 26 Oct · 2 nights");
    expect(stayLine({ checkin: "2026-10-30", checkout: "2026-11-01", check_in_time: null, check_out_time: null })).toBe("30 Oct → 1 Nov · 2 nights");
    expect(stayLine({ checkin: "2026-10-15", checkout: "2026-10-15", check_in_time: "09:00", check_out_time: "21:00" })).toBe("15 Oct · 9 am–9 pm · day trip");
    expect(stayLine({ checkin: "2026-10-15", checkout: "2026-10-15", check_in_time: null, check_out_time: null })).toBe("15 Oct · day trip");
  });

  it("money line: due with its date, overdue by the single rule, paid, nothing for cancelled", () => {
    expect(payState(row({ id: "x", checkin: "2026-10-24", next_payment_due_date: "2026-10-21", total_outstanding: 31850 }), TODAY))
      .toEqual({ pill: "Part paid", tone: "warning", text: "₹31,850 due 21 Oct", due: 31850 });
    // Fathima: check-in Fri 30 Oct, an instalment past due -> overdue, the same as the month summary says.
    expect(payState(row({ id: "f", checkin: "2026-10-30", payment_overdue: true, total_outstanding: 9590 }), TODAY))
      .toMatchObject({ pill: "Overdue", tone: "danger", text: "₹9,590 overdue" });
    expect(payState(row({ id: "p", total_paid: 70000, total_outstanding: 0, payment_status: "paid" }), TODAY)).toMatchObject({ pill: "Paid", due: 0 });
    expect(payState(row({ id: "c", raw_status: "cancelled" }), TODAY)).toBeNull();
    expect(paidPct(row({ id: "h" }))).toBe(50);
  });
});
