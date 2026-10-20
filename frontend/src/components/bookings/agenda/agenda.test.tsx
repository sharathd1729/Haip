import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
const toast = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast }) }));

import { OccupancyStrip } from "./OccupancyStrip";
import { MonthSummary } from "./MonthSummary";
import { CollectSheet } from "@/components/bookings/CollectSheet";

const T = "2026-10-19";

function wrap(ui: React.ReactNode, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}

beforeEach(() => { cleanup(); get.mockReset(); post.mockReset(); toast.mockReset(); });

describe("Occupancy strip", () => {
  it("draws each vehicle's bookings, marks money still due, opens a block and books an empty day", async () => {
    get.mockResolvedValue({ data: { today: T, from: T, to: "2026-11-02", days: 14, vehicles: [
      { property_id: "r1", name: "Ratha 1", slot: 1, placeholder: false, holds: [], bookings: [
        { booking_id: "b1", guest_name: "Rohan Shetty", check_in: T, check_out: T, status: "confirmed", due: true },
        { booking_id: "b2", guest_name: "Neha Kulkarni", check_in: "2026-10-20", check_out: "2026-10-22", status: "confirmed", due: false },
      ] },
      { property_id: "r2", name: "Ratha 2", slot: 2, placeholder: false, bookings: [], holds: [{ from: "2026-10-25", to: "2026-10-27", reason: "maintenance" }] },
    ] } });
    const onOpen = vi.fn();
    wrap(<OccupancyStrip onOpen={onOpen} />);
    const rohan = await screen.findByRole("button", { name: /Rohan Shetty, Ratha 1/ });
    expect(rohan.getAttribute("data-due")).toBe("true");
    expect(rohan.textContent).toBe("Rohan");
    const neha = screen.getByRole("button", { name: /Neha Kulkarni, Ratha 1/ });
    expect(neha.getAttribute("data-due")).toBeNull();
    expect(neha.className).toContain("col-span-2");
    expect(screen.getByText("Maint.")).toBeTruthy();
    await userEvent.click(neha);
    expect(onOpen).toHaveBeenCalledWith("b2");
    const free = screen.getByRole("link", { name: "New booking on Ratha 1, Thu 22 Oct" });
    expect(free.getAttribute("href")).toBe("/dashboard/bookings/new?property=r1&from=2026-10-22&to=2026-10-23");
    expect(screen.queryByRole("link", { name: "New booking on Ratha 2, Sun 25 Oct" })).toBeNull();   // blocked for maintenance
  });
});

describe("Month summary", () => {
  it("says money is hidden without revenue access, never ₹0", async () => {
    const r = { restricted: true };
    get.mockResolvedValue({ data: { month: "2026-10", today: T, bookings: 6, by_vehicle: [{ property_id: "r1", name: "Ratha 1", count: 4 }],
      booked_value: r, collected: r, still_due: r, overdue: r } });
    wrap(<MonthSummary />);
    expect(await screen.findByText("October 2026")).toBeTruthy();
    expect(screen.getByText("6")).toBeTruthy();
    expect(screen.getAllByText("Hidden").length).toBe(3);
    expect(screen.queryByText(/₹0/)).toBeNull();
  });
});

function booking(outstanding: number, paid: number) {
  return {
    id: "bk", status: "confirmed", channel: "direct", pms_managed: false, check_in: "2026-10-20", check_out: "2026-10-22", nights: 2,
    check_in_time: null, check_out_time: null, adults: 3, children: 0, occasion: null, special_requests: "", internal_notes: "", concierge_notes: "",
    schedule: [], next_due: null, deposit: null, service_requests: [], assignees: [], inquiry_id: null, calendar_sync: null, created_at: null,
    property: { id: "r1", name: "Ratha 1", type: "caravan" }, guest: { id: "g", name: "Neha Kulkarni", phone: "+919800000001", email: null },
    financials: { stay_charge: 70000, addons_total: 0, total: 70000, paid, outstanding, payment_status: "partial" },
    addons: [], payments: [], payment_links: [], available_addons: [], activity: [],
    whatsapp: { conversation_id: "c1", last_inbound_at: new Date(Date.now() - 40 * 60_000).toISOString(), window_open: true },
  };
}

describe("Collect sheet", () => {
  it("records a payment received and the booking's due drops", async () => {
    get.mockImplementation((url: string) => Promise.resolve(
      url === "/bookings/bk" ? { data: booking(35000, 35000) }
        : url === "/payments/razorpay" ? { data: { connected: true } }
          : { data: { messages: [], templates: {} } }));
    post.mockResolvedValue({ data: booking(25000, 45000) });
    const onClose = vi.fn();
    const { client } = wrap(<CollectSheet bookingId="bk" open onClose={onClose} />);
    expect(await screen.findByText(/Goes as a normal message/)).toBeTruthy();       // the guest wrote 40 minutes ago
    await userEvent.click(screen.getByRole("button", { name: /Record a payment already received/ }));
    const amount = screen.getByLabelText("Amount (₹)") as HTMLInputElement;
    expect(amount.value).toBe("35000");
    await userEvent.clear(amount);
    await userEvent.type(amount, "50000");
    expect(screen.getByText("Enter an amount up to ₹35,000.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Record payment" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.clear(amount);
    await userEvent.type(amount, "10000");
    await userEvent.selectOptions(screen.getByLabelText("How was it paid?"), "cash");
    await userEvent.click(screen.getByRole("button", { name: "Record payment" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/bookings/bk/payments", expect.objectContaining({ kind: "payment", amount: 10000, method: "cash" })));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "₹10,000 recorded · ₹25,000 still due" }));
    expect((client.getQueryData(["booking", "bk"]) as ReturnType<typeof booking>).financials.outstanding).toBe(25000);
  });

  it("sends the Razorpay link on WhatsApp", async () => {
    get.mockImplementation((url: string) => Promise.resolve(
      url === "/bookings/bk" ? { data: booking(35000, 35000) }
        : url === "/payments/razorpay" ? { data: { connected: true } } : { data: { messages: [], templates: {} } }));
    post.mockResolvedValue({ data: { id: "l", short_url: "https://rzp.io/i/x", amount: 35000, status: "created", expires_at: null, created_at: null,
      whatsapp: { status: "queued", reason: null, via: "text" } } });
    wrap(<CollectSheet bookingId="bk" open onClose={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Send link" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/bookings/bk/payment-links", { amount: 35000, send_whatsapp: true }));
  });
});
