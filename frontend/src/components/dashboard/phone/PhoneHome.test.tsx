import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { name: "Sharath D", role: "owner", tenantId: "t1" } }, status: "authenticated" }) }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
vi.mock("@/components/providers/WorkspaceProvider", async (orig) => ({ ...(await orig<object>()), useBusinessType: () => "caravan" }));   // the caravan words ("Trips next 7 days")

import { PhoneHome, dueThisWeek } from "./PhoneHome";
import { callBars, leadBars, waitingKinds } from "@/components/dashboard/overview/OverviewParts";

const R = { restricted: true } as const;
const DAYS = ["2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24"];

// Fixtures for the component, not product data.
function overview({ bookings = true, revenue = true } = {}) {
  return {
    generated_at: new Date().toISOString(),
    period: { date_from: "2026-10-24", date_to: "2026-10-24", timezone: "Asia/Kolkata", previous_from: "", previous_to: "" },
    access: { tenant_wide: true, bookings, revenue },
    insights: [{ id: "x", severity: "critical", title: "2169 leads not followed up in 24h", body: "" }],
    sources: [{ key: "whatsapp", label: "WhatsApp", leads: 4, bookings: null, booking_value: null }, { key: "call", label: "Calls", leads: 2, bookings: null, booking_value: null },
      { key: "website", label: "Website", leads: 0, bookings: null, booking_value: null }],
    series: { granularity: "day", days: DAYS, period_start_index: 6, leads: [1, 0, 2, 1, 0, 1, 6], conversations: [0, 0, 0, 0, 0, 0, 0],
      bookings: bookings ? [0, 1, 0, 0, 0, 0, 2] : null, booking_value: revenue ? [0, 50000, 0, 0, 0, 0, 132000] : null, net_collected: revenue ? [0, 0, 0, 0, 0, 0, 45000] : null,
      calls: [3, 5, 2, 4, 6, 1, 9], calls_missed: [0, 1, 0, 0, 2, 0, 2] },
    funnel: { basis: "People who became leads in the period", note: "", stages: [
      { key: "identified", label: "New leads", count: 6, previous: 0, rate_from_previous: null, change: null },
      { key: "qualified", label: "With dates", count: 4, previous: 0, rate_from_previous: 66.7, change: null },
      { key: "booked", label: "Booked", count: 2, previous: 0, rate_from_previous: 50, change: null },
      { key: "paid", label: "Paid", count: 1, previous: 0, rate_from_previous: 50, change: null }] },
    owner: {
      ai_calls: { sales_actions: { count: 0, href: "/dashboard/inbox", items: [] }, autopilot: { count: 0, href: "/x", by_stage: [], items: [] },
        calls: { total: 9, missed: 2, returned: 1, not_returned: 1, href: "/dashboard/calls" } },
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

const person = (kind: string, severity: string, guest_id: string, title: string) =>
  ({ kind, severity, guest_id, title, detail: "", action: "", href: `/dashboard/leads/${guest_id}`, channels: [], since: null });
const queue = { people_waiting: 3, total: 4, unowned: 1, severity: { stale: 1 },
  items: [person("callback", "urgent", "a", "Meera"), person("callback", "late", "b", "Vikram"), person("new_lead", "fresh", "c", "Kavya"),
    person("new_lead", "stale", "e", "Old lead"), person("reply", "stale", "d", "Older lead")] };

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
  it("shows who is waiting from the work queue, the four numbers with their trend, and the next 7 days", async () => {
    route(overview());
    renderHome();
    // the people still waiting (not the cold tail), and the way into My day
    expect((await screen.findByRole("link", { name: "3 people waiting. Open My day" })).getAttribute("href")).toBe("/dashboard/my-day");
    // four tiles, each a link to the list behind its number
    const tiles = within(await screen.findByRole("region", { name: "Numbers, Today" }));
    const leads = tiles.getByRole("link", { name: /New leads/ });
    expect(leads.getAttribute("href")).toBe("/dashboard/leads");
    expect(leads.textContent).toContain("6");
    expect(tiles.getByRole("img", { name: "4 from WhatsApp" })).toBeTruthy();           // channel counts are icons with a spoken label
    expect(tiles.queryByRole("img", { name: /from Website/ })).toBeNull();              // a channel with no leads is left out
    expect(tiles.getByRole("img", { name: "New leads, last 7 days: 1, 0, 2, 1, 0, 1, 6" })).toBeTruthy();
    expect(tiles.getByRole("link", { name: /Calls/ }).textContent).toContain("9");
    expect(tiles.getByRole("img", { name: "2 missed" })).toBeTruthy();
    expect(tiles.getByRole("link", { name: /Bookings/ }).textContent).toContain("2");
    expect(tiles.getByRole("link", { name: /Booked value/ }).textContent).toContain("₹1.32 L");
    // the chart says what it answers; the funnel is the server's
    expect(screen.getByText("New leads per day")).toBeTruthy();
    expect(screen.getByText("From lead to booking")).toBeTruthy();
    // next 7 days: money still owed on the trips, then who arrives
    expect((await screen.findByText("To collect · 7 days")).closest("a")?.textContent).toContain("₹5,000");
    const arriving = within(screen.getByRole("region", { name: "Arriving next" }));
    expect(await arriving.findByText("Anita")).toBeTruthy();
    expect(arriving.getByText("₹5,000 due")).toBeTruthy();
    expect(arriving.getByText("Paid")).toBeTruthy();
  });

  it("leaves 'What the AI noticed' and the definitions off the phone", async () => {
    route(overview());
    renderHome();
    await screen.findByText("New leads per day");
    expect(screen.queryByText(/What the AI noticed/)).toBeNull();
    expect(screen.queryByText(/2169 leads/)).toBeNull();
    expect(screen.queryByText(/How these numbers are defined/)).toBeNull();
  });

  it("hides money and bookings a role may not see instead of showing 0", async () => {
    route(overview({ bookings: false, revenue: false }));
    renderHome();
    await screen.findByText("New leads per day");
    expect(screen.getByRole("link", { name: "Bookings: hidden for your role" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Booked value: hidden for your role" })).toBeTruthy();
    expect(screen.queryByText("To collect · 7 days")).toBeNull();
    expect(screen.queryByText("Arriving next")).toBeNull();
    expect(document.body.textContent).not.toMatch(/₹0\b/);
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
    await screen.findByText("New leads per day");
    await new Promise(r => setTimeout(r, 30));
    expect(screen.queryByText("Leads by check-in")).toBeNull();
  });
});

describe("helpers", () => {
  it("adds up money still due on live bookings only", () => {
    const rows = [trip("a"), trip("b", { total_outstanding: 12000 }), trip("c", { raw_status: "cancelled", total_outstanding: 9000 }), trip("d", { total_outstanding: 0 })];
    expect(dueThisWeek(rows as never)).toEqual({ amount: 17000, count: 2 });
  });
  it("sorts the people waiting into calls to return, people to answer and follow-ups", () => {
    expect(waitingKinds([person("callback", "urgent", "1", "A"), person("reply", "fresh", "2", "B"), person("new_lead", "fresh", "3", "C"),
      person("followup", "late", "4", "D")] as never)).toEqual({ calls: 1, replies: 2, followups: 1 });
  });
  it("draws one bar per day, marks today, and splits calls into answered and missed", () => {
    const s = overview().series as never;
    const leads = leadBars(s, "2026-10-24");
    expect(leads).toHaveLength(7);
    expect(leads[6]).toMatchObject({ value: 6, now: true });
    expect(leads[6].tip).toMatch(/24 Oct.*: 6 new leads$/);
    expect(leads[0].now).toBe(false);
    const calls = callBars(s, "2026-10-24")!;
    expect(calls[6]).toMatchObject({ value: 7, top: 2 });                    // 9 calls, 2 of them missed
    expect(calls[6].tip).toMatch(/7 answered, 2 missed$/);
    expect(callBars({ ...(s as object), calls: null, calls_missed: null } as never)).toBeNull();   // an agent's view has no call series
  });
});
