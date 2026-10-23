import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
const sess = vi.hoisted(() => ({ role: "owner" }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { name: "Asha", role: sess.role } }, status: "authenticated" }) }));
const push = vi.fn();
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(), useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
vi.mock("@/components/bookings/CollectSheet", () => ({ CollectSheet: ({ bookingId }: { bookingId: string }) => <div>collect-sheet {bookingId}</div> }));
vi.mock("@/components/bookings/WhatsAppSheet", () => ({ WhatsAppSheet: ({ bookingId }: { bookingId: string }) => <div>wa-sheet {bookingId}</div> }));
vi.mock("@/components/bookings/agenda/FiltersSheet", () => ({ FiltersSheet: () => null }));

import { PhoneBookings, moneyTag } from "./PhoneBookings";
import { dateSpan } from "./BookingRowSheet";

function row(id: string, patch: Record<string, unknown> = {}) {
  return { id, external_id: `HB-${id}`, checkin: "2026-10-30", checkout: "2026-10-31", adults: 4, children: 0, status: "confirmed", raw_status: "confirmed",
    payment_status: "partial", total: 76700, total_paid: 71700, total_outstanding: 5000, payment_overdue: false, trip: "Coorg",
    property: { id: "p1", name: "Ratha 1", type: "caravan" }, main_guest: { id: "g", first_name: "Anita", last_name: "", phone: "+919800000001", email: null },
    next_payment_due_date: null, next_payment_amount: 0, channel: null, created_at: null, inquiry_id: null, deposit: null, check_in_time: null, check_out_time: null, ...patch };
}
const ROWS = [row("b1"), row("b2", { main_guest: { id: "g2", first_name: "Shruthi", last_name: "", phone: null, email: null }, trip: "Wild Karnataka",
  checkin: "2026-10-31", checkout: "2026-11-01", total: 132000, total_paid: 132000, total_outstanding: 0, payment_status: "paid", property: { id: "p2", name: "Ratha 2", type: "caravan" } })];
const OCC = { today: "2026-10-29", from: "2026-10-29", to: "2026-11-04", days: 7, vehicles: [
  { property_id: "p1", name: "Ratha 1", slot: 1, placeholder: false, holds: [], bookings: [{ booking_id: "b1", guest_name: "Anita", check_in: "2026-10-30", check_out: "2026-10-31", status: "confirmed", due: true }] },
  { property_id: "p2", name: "Ratha 2", slot: 2, placeholder: false, holds: [], bookings: [{ booking_id: "zz", guest_name: "Other", check_in: "2026-11-02", check_out: "2026-11-03", status: "confirmed", due: false }] },
] };

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><PhoneBookings /></QueryClientProvider>);
}

beforeEach(() => {
  cleanup(); get.mockReset(); push.mockReset(); sess.role = "owner";
  get.mockImplementation((url: string) => {
    if (url === "/bookings/occupancy") return Promise.resolve({ data: OCC });
    if (url === "/bookings/properties") return Promise.resolve({ data: [] });
    return Promise.resolve({ data: { data: ROWS, meta: { current_page: 1, last_page: 1, per_page: 50, total: 2, from: 1, to: 2, today: "2026-10-29",
      segment_counts: { upcoming: 2, staying: 1, past: 40, cancelled: 3 } } } });
  });
});

describe("Phone Bookings", () => {
  it("shows the status chips with counts, the 7-day strip and rows with amount and a due / paid pill", async () => {
    renderIt();
    expect(await screen.findByText("Anita · Coorg")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Upcoming\s*2/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /Staying\s*1/ })).toBeTruthy();
    expect(screen.getByText("₹5,000 due")).toBeTruthy();
    expect(screen.getByText("paid")).toBeTruthy();
    expect(screen.getByText("₹1.32 L")).toBeTruthy();
    expect(await screen.findByRole("group", { name: "Ratha 1" })).toBeTruthy();
  });

  it("opens a booking's sheet with Total / Paid / Still due and hands Collect and WhatsApp to the existing sheets", async () => {
    renderIt();
    await userEvent.click(await screen.findByRole("button", { name: "Anita, open booking details" }));
    expect(await screen.findByText("Still due before trip")).toBeTruthy();
    expect(screen.getAllByText("₹76,700").length).toBe(2);
    expect(screen.getByRole("link", { name: /Full page/ }).getAttribute("href")).toBe("/dashboard/bookings/b1");
    await userEvent.click(screen.getByRole("button", { name: /Collect/ }));
    expect(screen.getByText("collect-sheet b1")).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });

  it("hides Collect for roles that may not record money", async () => {
    sess.role = "concierge";
    renderIt();
    await userEvent.click(await screen.findByRole("button", { name: "Anita, open booking details" }));
    expect(await screen.findByText("Still due before trip")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Collect/ })).toBeNull();
    expect(screen.getByRole("button", { name: /WhatsApp/ })).toBeTruthy();
  });

  it("a strip bar outside the loaded list opens that booking's full page", async () => {
    renderIt();
    await userEvent.click(await screen.findByRole("button", { name: /Other, Ratha 2/ }));
    expect(push).toHaveBeenCalledWith("/dashboard/bookings/zz");
  });

  it("says when the list could not load", async () => {
    get.mockImplementation((url: string) => url === "/bookings" ? Promise.reject(new Error("down")) : Promise.resolve({ data: url === "/bookings/occupancy" ? OCC : [] }));
    renderIt();
    expect(await screen.findByText("Could not load bookings")).toBeTruthy();
  });
});

describe("helpers", () => {
  it("money pill and date span", () => {
    expect(moneyTag(row("x", { checkin: "2026-10-20", payment_overdue: true }) as never, "2026-10-29")?.tone).toBe("danger");
    expect(moneyTag(row("x", { total_outstanding: 0 }) as never, "2026-10-29")?.label).toBe("paid");
    expect(moneyTag(row("x", { total: 0, total_outstanding: 0 }) as never, "2026-10-29")).toBeNull();
    expect(dateSpan("2026-10-30", "2026-10-31")).toBe("30–31 Oct");
    expect(dateSpan("2026-10-31", "2026-11-02")).toBe("31 Oct – 2 Nov");
  });
});
