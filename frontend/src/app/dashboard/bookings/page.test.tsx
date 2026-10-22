import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor, cleanup, within } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { name: "Jishanth", role: "reservations" } }, status: "authenticated" }) }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(), useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/dashboard/bookings" }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import BookingsPage from "./page";
import { todayIST, addDays } from "@/lib/bookingAgenda";

const T = todayIST();
const VEH = [{ id: "r1", name: "Ratha 1" }, { id: "r2", name: "Ratha 2" }];

function row(id: string, name: string, veh: "r1" | "r2", inOff: number, outOff: number, extra: Record<string, unknown> = {}) {
  const [first, ...rest] = name.split(" ");
  return {
    id, external_id: id, checkin: addDays(T, inOff), checkout: addDays(T, outOff), adults: 3, children: 0, status: "confirmed", raw_status: "confirmed",
    payment_status: "partial", total: 70000, total_paid: 35000, total_outstanding: 35000, next_payment_due_date: null, next_payment_amount: 0,
    payment_overdue: false, property: { id: veh, name: veh === "r1" ? "Ratha 1" : "Ratha 2", type: "caravan" },
    main_guest: { id: `g-${id}`, first_name: first, last_name: rest.join(" "), phone: "+919800000001", email: null },
    channel: "direct", created_at: null, inquiry_id: null, trip: "Coorg 48-hour Retreat", deposit: null, check_in_time: "12:00", check_out_time: "12:00",
    ...extra,
  };
}
const UPCOMING = [row("b1", "Neha Kulkarni", "r1", 1, 3),
  row("b2", "Manisha Rao", "r2", 2, 3, { payment_overdue: true, total_outstanding: 9590, total_paid: 60410 })];   // an instalment is past due
const CANCELLED = [row("b4", "Sharat Kumar", "r2", 5, 7, { raw_status: "cancelled", total_paid: 0, total_outstanding: 0, payment_status: "unpaid" })];
const STAYING = [row("b3", "Arjun Menon", "r2", -1, 1, { raw_status: "checked_in", deposit: { amount: 10000, status: "held" }, total_paid: 70000, total_outstanding: 0, payment_status: "paid" })];

function detail(id: string) {
  return {
    id, status: "confirmed", channel: "direct", pms_managed: false, check_in: addDays(T, 1), check_out: addDays(T, 3), nights: 2,
    check_in_time: "12:00", check_out_time: "12:00", adults: 3, children: 0, occasion: null, special_requests: "", internal_notes: "",
    concierge_notes: "", schedule: [], next_due: null, deposit: null, service_requests: [], assignees: [], inquiry_id: null, calendar_sync: null,
    created_at: null, property: { id: "r1", name: "Ratha 1", type: "caravan" }, guest: { id: "g", name: "Neha Kulkarni", phone: "+919800000001", email: null },
    financials: { stay_charge: 70000, addons_total: 0, total: 70000, paid: 35000, outstanding: 35000, payment_status: "partial" },
    addons: [], payments: [], payment_links: [], available_addons: [], activity: [], trip: "Coorg 48-hour Retreat",
    whatsapp: { conversation_id: null, last_inbound_at: null, window_open: false },
  };
}

function api(url: string, cfg?: { params?: Record<string, unknown> }) {
  const p = cfg?.params ?? {};
  if (url === "/bookings/properties") return { data: VEH };
  if (url === "/bookings/summary") return { data: { month: T.slice(0, 7), today: T, bookings: 3, by_vehicle: [], booked_value: 210000, collected: 140000, still_due: 70000, overdue: 0 } };
  if (url === "/bookings/occupancy") return { data: { today: T, from: T, to: addDays(T, 14), days: 14, vehicles: [] } };
  if (url === "/bookings") {
    let rows = p.segment === "staying" ? STAYING : p.segment === "upcoming" ? UPCOMING : p.segment === "cancelled" ? CANCELLED : [];
    if (p.property_id) rows = rows.filter(r => String(p.property_id).split(",").includes(r.property.id));
    const counts = { upcoming: UPCOMING.length, staying: STAYING.length, past: 0, cancelled: CANCELLED.length };
    return { data: { data: rows, meta: { current_page: 1, last_page: 1, per_page: 50, total: rows.length, from: 1, to: rows.length, today: T, segment_counts: counts } } };
  }
  if (url.startsWith("/bookings/")) {
    const id = url.split("/")[2];
    if (url.endsWith("/booking-messages")) return { data: { messages: [], templates: {} } };
    if (url.endsWith("/invoices")) return { data: { invoices: [], can_reissue: false } };
    return { data: detail(id) };
  }
  if (url === "/payments/razorpay") return { data: { connected: true } };
  return { data: {} };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><BookingsPage /></QueryClientProvider>);
}

beforeEach(() => {
  cleanup(); get.mockReset(); post.mockReset();
  get.mockImplementation((url: string, cfg?: { params?: Record<string, unknown> }) => Promise.resolve(api(url, cfg)));
  window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }) as never;
});

const card = (name: string) => screen.getByRole("button", { name: new RegExp(`^Open ${name}`) }).closest("article") as HTMLElement;

describe("Bookings cards by date", () => {
  it("shows one card per booking under its check-in day, never separate check-in and check-out rows", async () => {
    renderPage();
    expect(await screen.findByRole("button", { name: /^Open Neha Kulkarni/ })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /^Open Neha Kulkarni/ })).toHaveLength(1);    // a 2-night booking appears once
    expect(screen.queryByText(/Check-out/)).toBeNull();
    expect(screen.queryByText(/Arjun Menon/)).toBeNull();                                     // staying now is its own tab
    const day1 = screen.getByRole("region", { name: new RegExp(`^Tomorrow`) });
    expect(within(day1).getByText(/Neha Kulkarni/)).toBeTruthy();
    expect(within(day1).queryByText(/Manisha Rao/)).toBeNull();                               // she checks in the day after
    expect(within(card("Neha Kulkarni")).getByText(/· 2 nights/)).toBeTruthy();
    expect(within(card("Neha Kulkarni")).getByText(/₹35,000 due/)).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Upcoming/ }).textContent).toContain("2");
    expect(document.querySelector('a[href^="tel:"], a[href*="wa.me"]')).toBeNull();
  });

  it("day groups flow across columns, each group its heading with its cards stacked, in date order", async () => {
    renderPage();
    await screen.findByRole("button", { name: /^Open Neha Kulkarni/ });
    const grid = screen.getByTestId("card-groups");
    expect(grid.className).toContain("grid-cols-[repeat(auto-fill,minmax(min(100%,330px),1fr))]");
    const groups = Array.from(grid.children) as HTMLElement[];
    expect(groups.map(g => g.getAttribute("aria-label"))).toEqual([expect.stringMatching(/^Tomorrow/), expect.stringMatching(/^[A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}$/)]);
    expect(within(groups[0]).getAllByRole("article")).toHaveLength(1);           // Neha, under her own day
    expect(within(groups[1]).getByText("Manisha Rao")).toBeTruthy();
  });

  it("an overdue booking says overdue on its card, not just due", async () => {
    renderPage();
    await screen.findByRole("button", { name: /^Open Manisha Rao/ });
    const m = card("Manisha Rao");
    expect(within(m).getByText("₹9,590 overdue")).toBeTruthy();
    expect(within(m).getByText("Overdue")).toBeTruthy();
    expect((within(m).getByRole("button", { name: "Collect from Manisha Rao" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("staying now shows one card per stay; cancelled shows the amount struck through", async () => {
    renderPage();
    await screen.findByRole("button", { name: /^Open Neha Kulkarni/ });
    await userEvent.click(screen.getByRole("tab", { name: /Staying/ }));
    const trip = await screen.findByRole("region", { name: "On a trip now" });
    expect(within(trip).getAllByRole("button", { name: /^Open / })).toHaveLength(1);
    expect(within(card("Arjun Menon")).getByText("Paid in full")).toBeTruthy();
    expect((within(card("Arjun Menon")).getByRole("button", { name: /nothing to collect/ }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole("tab", { name: /Cancelled/ }));
    await screen.findByRole("button", { name: /^Open Sharat Kumar/ });
    const struck = within(card("Sharat Kumar")).getByTestId("cancelled-total");
    expect(struck.tagName).toBe("S");
    expect(struck.textContent).toBe("₹70,000");
  });

  it("the Filters sheet narrows the list", async () => {
    renderPage();
    await screen.findByRole("button", { name: /^Open Neha Kulkarni/ });
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    await userEvent.click(await screen.findByRole("button", { name: "Ratha 2" }));
    await userEvent.click(screen.getByRole("button", { name: "Show bookings" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /^Open Neha Kulkarni/ })).toBeNull());
    expect(screen.getByRole("button", { name: /^Open Manisha Rao/ })).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/bookings", expect.objectContaining({ params: expect.objectContaining({ property_id: "r2", segment: "upcoming" }) }));
    expect(screen.getByRole("button", { name: "Filters, 1 on" })).toBeTruthy();
  });

  it("opens a booking with Call through HAIP, never a tel: link", async () => {
    post.mockResolvedValue({ data: { status: "initiated" } });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /^Open Neha Kulkarni/ }));
    const sheet = await screen.findByRole("dialog");
    expect(await within(sheet).findByRole("heading", { name: "Stay" })).toBeTruthy();
    expect(within(sheet).getByText(/Coorg 48-hour Retreat · 2 nights/)).toBeTruthy();
    expect(within(sheet).getByRole("button", { name: "Check in" })).toBeTruthy();   // due tomorrow
    expect(document.querySelector('a[href^="tel:"], a[href*="wa.me"]')).toBeNull();
    await userEvent.click(within(sheet).getByRole("button", { name: /^Call$/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/calls/click-to-call", { guest_number: "+919800000001" }));
  });

  it("hydrates without a mismatch even when the cache already holds the month and the list", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    // As restored from the persisted cache before hydration: the server never has this, so the first client render must ignore it.
    client.setQueryData(["bookings-summary"], api("/bookings/summary").data);
    client.setQueryData(["bookings", "cards", "upcoming", {}], { pages: [api("/bookings", { params: { segment: "upcoming" } }).data], pageParams: [1] });
    const ui = <QueryClientProvider client={client}><BookingsPage /></QueryClientProvider>;
    const html = renderToString(ui);
    expect(html).not.toContain('role="alert"');
    expect(html).not.toContain("Neha Kulkarni");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>.*?Export/);
    const host = document.createElement("div");
    host.innerHTML = html;
    document.body.appendChild(host);
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    await act(async () => { hydrateRoot(host, ui); });
    const mismatch = errors.mock.calls.filter(c => /hydrat|did not match/i.test(String(c[0])));
    errors.mockRestore();
    expect(mismatch).toEqual([]);
    expect(await within(host).findByRole("button", { name: /^Open Neha Kulkarni/ })).toBeTruthy();
    host.remove();
  });

  it("New booking goes to the New booking page", async () => {
    renderPage();
    expect((await screen.findByRole("link", { name: /New booking/ })).getAttribute("href")).toBe("/dashboard/bookings/new");
  });
});
