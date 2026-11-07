import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("@/components/providers/WorkspaceProvider", async (orig) => ({ ...(await orig<object>()), useBusinessType: () => "villa_resort" }));

import { BookingCards } from "./BookingCards";
import type { AgendaRow } from "@/lib/bookingAgenda";

afterEach(cleanup);

const T = "2026-11-07";
const row = (extra: Record<string, unknown>) => ({
  id: "b1", external_id: "1", checkin: "2026-11-09", checkout: "2026-11-13", adults: 4, children: 0, status: "confirmed", raw_status: "confirmed",
  payment_status: "partial", total: 96000, total_paid: 48000, total_outstanding: 48000, next_payment_due_date: null, next_payment_amount: 0,
  payment_overdue: false, property: { id: "v1", name: "Banyan Court", type: "villa" },
  main_guest: { id: "g1", first_name: "*Priya", last_name: "Raman*", phone: "+919800000001", email: null },
  channel: "direct", created_at: null, inquiry_id: null, trip: "Coorg route", deposit: { amount: 10000, status: "pending" }, caretaker: "Lata",
  check_in_time: null, check_out_time: null, ...extra,
}) as unknown as AgendaRow;

const show = (rows: AgendaRow[], segment: "upcoming" | "staying" = "upcoming") => render(
  <BookingCards rows={rows} segment={segment} today={T} paneOpen={false} canCollect slotOf={() => 1}
    onOpen={vi.fn()} onCall={vi.fn()} onWhatsApp={vi.fn()} onCollect={vi.fn()} />);

describe("Booking cards for a villa business", () => {
  it("carries the villa, nights, guests, caretaker and deposit, never a caravan route", () => {
    show([row({})]);
    expect(screen.getByText("Priya Raman")).toBeTruthy();                       // Google's bold markers gone
    expect(screen.getByText("Banyan Court")).toBeTruthy();
    expect(screen.getByText("9 → 13 Nov · 4 nights")).toBeTruthy();
    expect(screen.getByText("4 guests · Caretaker Lata")).toBeTruthy();
    expect(screen.getByText(/Deposit ₹10,000 not collected yet/)).toBeTruthy();
    expect(screen.queryByText("Coorg route")).toBeNull();
  });

  it("calls the staying group 'Staying now' and a booking with no villa 'Which villa?'", () => {
    show([row({ property: null, raw_status: "checked_in", checkin: "2026-11-06" })], "staying");
    expect(screen.getByRole("region", { name: "Staying now" })).toBeTruthy();
    expect(screen.getByText("1 staying", { exact: false })).toBeTruthy();
    expect(screen.getByText("Which villa?")).toBeTruthy();
  });
});
