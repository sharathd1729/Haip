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

describe("Occupancy strip placeholder row", () => {
  it("says the full words for bookings no unit was chosen for, never a 4-letter cut", async () => {
    get.mockResolvedValue({ data: { today: T, from: T, to: "2026-11-02", days: 14, vehicles: [
      { property_id: "v1", name: "Villa Aster", slot: 1, placeholder: false, holds: [], bookings: [] },
      { property_id: "u", name: "Unassigned", slot: 0, placeholder: true, holds: [], bookings: [
        { booking_id: "b9", guest_name: "Saksham", check_in: "2026-10-21", check_out: "2026-10-23", status: "confirmed", due: false },
      ] },
    ] } });
    wrap(<OccupancyStrip onOpen={vi.fn()} />);
    expect(await screen.findByText("Which property?")).toBeTruthy();     // no workspace loaded = a plain property business
    expect(screen.queryByText("Unas")).toBeNull();
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

describe("Occupancy strip for a stay business (11 villas)", () => {
  const villas = Array.from({ length: 11 }, (_, i) => `Villa ${String.fromCharCode(65 + i)}`);
  const waitingEvent = (key: string) => ({ title: "*Mag/Sharma*", needs_vehicle: true, event_key: key, feed_name: "Demo bookings", details: {} });
  function data() {
    return { today: T, from: T, to: "2026-11-02", days: 14, vehicles: villas.map((name, i) => ({
      property_id: `p${i}`, name, slot: 1, placeholder: false, bookings: [],
      holds: [
        // one event held on every villa (named no villa), entered as two one-night events
        { id: `w1-${i}`, from: "2026-10-21", to: "2026-10-22", reason: "offline_booking", event: waitingEvent("f:w1") },
        { id: `w2-${i}`, from: "2026-10-22", to: "2026-10-23", reason: "offline_booking", event: waitingEvent("f:w2") },
        ...(i === 0 ? [{ id: "k1", from: "2026-10-24", to: "2026-10-25", reason: "offline_booking", event: { title: "Kapoor", needs_vehicle: false, details: {} } },
          { id: "k2", from: "2026-10-25", to: "2026-10-26", reason: "offline_booking", event: { title: "Kapoor", needs_vehicle: false, details: {} } }] : []),
      ],
    })) };
  }
  beforeEach(() => { try { window.localStorage.removeItem("haip.bookings.strip"); } catch { /* none */ } });

  it("starts folded with one line, opens on request and remembers it", async () => {
    get.mockResolvedValue({ data: data() });
    wrap(<OccupancyStrip onOpen={vi.fn()} />);
    expect(await screen.findByText(/11 of 11 properties free tonight · 0 check-ins · 1 calendar event needs a property/)).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Villa A" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Show properties" }));
    expect(screen.getByRole("group", { name: "Villa A" })).toBeTruthy();
    expect(window.localStorage.getItem("haip.bookings.strip")).toBe("open");
  });

  it("shows a 'Which villa?' event once, merges back-to-back nights, and a tap on a hold opens its sheet", async () => {
    window.localStorage.setItem("haip.bookings.strip", "open");
    get.mockResolvedValue({ data: data() });
    const onOpenHold = vi.fn();
    wrap(<OccupancyStrip onOpen={vi.fn()} onOpenHold={onOpenHold} />);
    const which = await screen.findByRole("group", { name: "Which property?" });
    const waitingBars = which.querySelectorAll("button");
    expect(waitingBars).toHaveLength(1);                                     // two one-night events, one bar, shown once
    expect(waitingBars[0].textContent).toContain("Mag/Sharma");
    expect(screen.getByRole("group", { name: "Villa B" }).querySelectorAll("button")).toHaveLength(0);   // not repeated on each villa
    const kapoor = screen.getByRole("button", { name: /Kapoor \(Google Calendar\)/ });
    expect(kapoor.className).toContain("col-span-2");
    await userEvent.click(kapoor);
    expect(onOpenHold).toHaveBeenCalledWith(expect.objectContaining({ id: "k1", blocked_to: "2026-10-26" }), "Villa A");
    expect(screen.queryByRole("link", { name: "New booking on Villa B, Wed 21 Oct" })).toBeNull();   // a "Which villa?" day is not offered
  });
});
