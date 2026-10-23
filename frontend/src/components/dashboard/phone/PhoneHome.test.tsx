import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { name: "Sharath D", role: "owner", tenantId: "t1" } }, status: "authenticated" }) }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));

import { PhoneHome, dueThisWeek } from "./PhoneHome";
import { waitingBreakdown } from "./WaitingBanner";

const R = { restricted: true } as const;

// Fixtures for the component, not product data.
function overview({ bookings = true, revenue = true } = {}) {
  return {
    generated_at: new Date().toISOString(),
    period: { date_from: "2026-10-24", date_to: "2026-10-24", timezone: "Asia/Kolkata", previous_from: "", previous_to: "" },
    access: { tenant_wide: true, bookings, revenue },
    insights: [{ id: "x", severity: "critical", title: "2169 leads not followed up in 24h", body: "" }],
    owner: {
      kpis: {
        new_leads: { count: 6, previous: 0, change: null, basis: "" },
        qualified: { count: 4, previous: 0, change: null, basis: "" },
        bookings: bookings ? { count: 2, previous: 0, change: null, basis: "" } : R,
        booked_value: revenue ? { total: 132000, rental: 120000, add_ons: 12000, previous: 0, change: null, basis: "" } : R,
        payment_received: revenue ? { amount: 45000, previous: 0, change: null, refunds: 0, basis: "" } : R,
      },
    },
  };
}

function trip(id: string, patch: Record<string, unknown> = {}) {
  return { id, external_id: id, checkin: "2026-10-30", checkout: "2026-10-31", adults: 4, children: 0, status: "confirmed", raw_status: "confirmed",
    payment_status: "partial", total: 76700, total_paid: 71700, total_outstanding: 5000, payment_overdue: false, trip: "Coorg",
    property: { id: "p1", name: "Ratha 1", type: "caravan" }, main_guest: { id: "g", first_name: "Anita", last_name: "", phone: null, email: null },
    next_payment_due_date: null, next_payment_amount: 0, channel: null, created_at: null, inquiry_id: null, deposit: null, check_in_time: null, check_out_time: null, ...patch };
}

const queue = { people_waiting: 3, total: 4, unowned: 1, severity: { stale: 1 },
  items: [{ kind: "callback", severity: "urgent", guest_id: "a" }, { kind: "callback", severity: "late", guest_id: "b" },
    { kind: "new_lead", severity: "fresh", guest_id: "c", owner_id: null }, { kind: "new_lead", severity: "stale", guest_id: "e", owner_id: null }, { kind: "reply", severity: "stale", guest_id: "d" }] };

function route(ov: ReturnType<typeof overview>, trips = [trip("b1"), trip("b2", { main_guest: { id: "g2", first_name: "Shruthi", last_name: "", phone: null, email: null }, trip: "Wild Karnataka", total_outstanding: 0, payment_status: "paid" })]) {
  get.mockImplementation((url: string) => {
    if (url === "/work-queue") return Promise.resolve({ data: queue });
    if (url === "/dashboard/business-overview") return Promise.resolve({ data: ov });
    if (url === "/leads") return Promise.resolve({ data: { total: 4, leads: [], stages: {} } });
    if (url === "/reports/checkin-months") return Promise.resolve({ data: { rows: [
      { month: "2026-10-01", label: "Oct 2026", enquiries: 12, valid: 7, won: 2, lost: 3, open: 7 },
      { month: "2026-11-01", label: "Nov 2026", enquiries: 5, valid: 4, won: 0, lost: 0, open: 5 }],
      no_date: { month: null, label: "Date not given yet", enquiries: 9, valid: 3, won: 0, lost: 1, open: 8 } } });
    if (url === "/bookings") return Promise.resolve({ data: { data: trips, meta: { current_page: 1, last_page: 1, per_page: 100, total: trips.length, from: 1, to: trips.length } } });
    return Promise.reject(new Error(url));
  });
}

function renderHome() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><PhoneHome /></QueryClientProvider>);
}

beforeEach(() => { cleanup(); get.mockReset(); });

describe("Phone Home", () => {
  it("shows who is waiting from the work queue, the four numbers and the next 7 days of trips", async () => {
    route(overview());
    renderHome();
    expect(await screen.findByText("3 people waiting for you")).toBeTruthy();
    expect(screen.getByText("2 call-backs · 1 new lead")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Assign 1" }).getAttribute("href")).toBe("/dashboard/my-day?kind=new_lead");
    expect(await screen.findByText("New leads")).toBeTruthy();
    expect(await screen.findByText(/4 valid enquiries · today/)).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/leads", { params: { validity: "valid", lead_type: "guest", enquiry_date_preset: "today", page: 1, page_size: 1 } });
    expect(screen.getByText("Booked")).toBeTruthy();
    expect(screen.getByText("₹45,000")).toBeTruthy();
    expect(await screen.findByText("Due this week")).toBeTruthy();
    expect(await screen.findByText("Anita · Coorg")).toBeTruthy();
    expect(screen.getByText("₹5,000 due")).toBeTruthy();
    expect(screen.getByText("Paid")).toBeTruthy();
  });

  it("leaves 'What the AI noticed' and the definitions off the phone", async () => {
    route(overview());
    renderHome();
    await screen.findByText("New leads");
    expect(screen.queryByText(/What the AI noticed/)).toBeNull();
    expect(screen.queryByText(/2169 leads/)).toBeNull();
    expect(screen.queryByText(/How these numbers are defined/)).toBeNull();
  });

  it("hides money and bookings a role may not see instead of showing 0", async () => {
    route(overview({ bookings: false, revenue: false }));
    renderHome();
    await screen.findByText("New leads");
    expect(screen.queryByText("Booked")).toBeNull();
    expect(screen.queryByText("Collected")).toBeNull();
    expect(screen.queryByText("Due this week")).toBeNull();
    expect(screen.queryByText("Trips next 7 days")).toBeNull();
    expect(get.mock.calls.some(c => c[0] === "/bookings")).toBe(false);
  });
});

describe("Leads by check-in", () => {
  it("lists the months from the check-in report with the 'Date not given yet' row", async () => {
    route(overview());
    renderHome();
    expect(await screen.findByText("Oct 2026")).toBeTruthy();
    expect(screen.getByText("7 valid · 2 won · 7 open")).toBeTruthy();
    expect(screen.getByText("Date not given yet")).toBeTruthy();
    expect(screen.getByText("9 enquiries")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/reports/checkin-months", expect.objectContaining({ params: expect.objectContaining({ months: 3 }) }));
  });

  it("leaves the section out for a role the report refuses", async () => {
    route(overview());
    const base = get.getMockImplementation()!;
    get.mockImplementation((url: string, cfg?: unknown) => url === "/reports/checkin-months"
      ? Promise.reject({ response: { status: 403 } }) : base(url, cfg));
    renderHome();
    await screen.findByText("New leads");
    await new Promise(r => setTimeout(r, 30));
    expect(screen.queryByText("Leads by check-in")).toBeNull();
  });
});

describe("helpers", () => {
  it("adds up money still due on live bookings only", () => {
    const rows = [trip("a"), trip("b", { total_outstanding: 12000 }), trip("c", { raw_status: "cancelled", total_outstanding: 9000 }), trip("d", { total_outstanding: 0 })];
    expect(dueThisWeek(rows as never)).toEqual({ amount: 17000, count: 2 });
  });
  it("names the three biggest reasons and skips the cold tail and calendar clashes", () => {
    expect(waitingBreakdown([{ kind: "reply", severity: "fresh", guest_id: "1" }, { kind: "clash", severity: "fresh", guest_id: null },
      { kind: "new_lead", severity: "stale", guest_id: "2" }])).toBe("1 reply");
  });
});
