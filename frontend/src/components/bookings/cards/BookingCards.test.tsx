import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { BookingCards } from "./BookingCards";
import type { AgendaRow } from "@/lib/bookingAgenda";

const row = (id: string, checkin: string): AgendaRow => ({
  id, external_id: id, checkin, checkout: checkin, adults: 2, children: 0, status: "confirmed", raw_status: "confirmed",
  payment_status: "paid", total: 25000, total_paid: 25000, total_outstanding: 0, property: { id: "r1", name: "Ratha 1", type: "caravan" },
  next_payment_due_date: null, next_payment_amount: 0, payment_overdue: false,
  main_guest: { id: "g", first_name: id, last_name: "", phone: null, email: null }, channel: "direct", created_at: null,
  inquiry_id: null, trip: null, deposit: null, check_in_time: null, check_out_time: null,
});

function show(paneOpen: boolean) {
  const noop = vi.fn();
  render(<BookingCards rows={[row("Asha", "2026-10-21"), row("Ravi", "2026-10-22"), row("Lina", "2026-10-23")]} segment="upcoming" today="2026-10-20"
    paneOpen={paneOpen} canCollect slotOf={() => 1} onOpen={noop} onCall={noop} onWhatsApp={noop} onCollect={noop} />);
  return screen.getAllByTestId("card-groups").at(-1)!;
}

describe("BookingCards layout", () => {
  it("day groups are the grid items, in date order; at most two columns while the pane is open", () => {
    const grid = show(false);
    expect(Array.from(grid.children).map(g => g.getAttribute("aria-label"))).toEqual(["Tomorrow · Wed 21 Oct", "Thu 22 Oct", "Fri 23 Oct"]);
    expect(grid.className).toContain("minmax(min(100%,330px),1fr)");
    expect(show(true).className).toContain("minmax(min(100%,max(330px,34%)),1fr)");
  });
});
