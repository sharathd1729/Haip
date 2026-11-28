import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, cleanup, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { name: "Sharath D", role: "owner", tenantId: "t1" } }, status: "authenticated" }) }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/components/providers/WorkspaceProvider", () => ({ useBusinessType: () => "caravan" }));
const nav = vi.hoisted(() => ({ search: "" }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/dashboard", useSearchParams: () => new URLSearchParams(nav.search) }));

import { CommandCenter } from "./CommandCenter";
import { ageText, deltaText, lakh, targetBars, weekLabel, whenText, type OwnerBlock } from "./owner";
import { inr, periodLabel } from "./types";

// Fixtures for the components, not product data.
function owner(patch: Partial<OwnerBlock> = {}): OwnerBlock {
  const since = new Date(Date.now() - 26 * 3600_000).toISOString();
  return {
    today: "2026-10-19",
    attention: [
      { key: "not_replying", title: "Not replying", reason: "We wrote last and they have been silent for 24 h or more", count: 2, severity: "fresh",
        href: "/dashboard/my-day?kind=no_reply", restricted: false, people: [{ name: "Pooja Nair", since, facts: ["25–27 Oct"] }, { name: "Arjun", since }] },
      { key: "not_called", title: "Not called yet", reason: "Shared a phone number; nobody has called them", count: 1, severity: "urgent",
        href: "/dashboard/my-day?flag=not_called", restricted: false, people: [{ name: "Kavya Iyer", since }] },
      { key: "missed_calls", title: "Missed calls not returned", reason: "They called", count: 0, severity: "fresh", href: "/dashboard/my-day?kind=callback", restricted: false, people: [] },
      { key: "followups", title: "Follow-ups overdue", reason: "active leads only", count: 0, severity: "fresh", href: "/x", restricted: false, people: [] },
      { key: "at_risk", title: "Promising leads at risk", reason: "Warm", count: 0, severity: "fresh", href: "/x", restricted: false, people: [] },
      { key: "owing", title: "Bookings still owing money", reason: "Check-in in the next 30 days", count: 2, amount: 127750, severity: "urgent",
        href: "/dashboard/bookings?quick=due", restricted: false, people: [{ name: "Anjali Menon", amount: 31850, due_date: "2026-10-21", overdue: false }] },
    ],
    kpis: {
      new_leads: { count: 14, previous: 11, change: { pct: 27.3, direction: "up" }, basis: "" },
      qualified: { count: 9, previous: 0, change: null, rate_of_new: 64.3, basis: "" },
      bookings: { count: 3, previous: 0, change: null, basis: "" },
      booked_value: { total: 133000, rental: 118000, add_ons: 15000, previous: 0, change: null, basis: "" },
      payment_received: { amount: 86000, previous: 52000, change: { pct: 65.4, direction: "up" }, refunds: 0, basis: "" },
    },
    target: { restricted: false, month: "2026-10-01", from: "2026-10-01", to: "2026-10-31", days_in_month: 31, days_elapsed: 19, days_left: 12,
      basis: "", available: true, booked: { total: 232800, rental: 208000, add_ons: 24800, count: 7 }, payment_received: 161500, pace_pct: 61.3,
      target: 600000, achieved_pct: 38.8, expected_by_today: 367742, ahead_by: -134942, to_go: 367200, href: "/dashboard/targets" },
    movements: { restricted: false, window_days: 7, from: "2026-10-19", to: "2026-10-25", check_ins: 1, check_outs: 1, truncated: false,
      items: [{ kind: "check_in", date: "2026-10-19", days_from_today: 0, guest: "Fathima Rizwan", property: "Ratha 1", trip: "day trip", href: "/dashboard/bookings/s1", status: "confirmed" },
        { kind: "check_out", date: "2026-10-20", days_from_today: 1, guest: "Rohit V", property: "Ratha 2", trip: "2 nights", href: "/dashboard/bookings/s2", status: "checked_in" }] },
    travel: { weeks: [{ start: "2026-10-19", active: 4, booked: 2 }, { start: "2026-10-26", active: 6, booked: 1 }, { start: null, active: 4, booked: 0 }],
      booked_restricted: false, active_basis: "open leads with a phone number and a check-in date", booked_basis: "confirmed bookings by check-in week" },
    stages: { stages: [{ key: "active", label: "Active", category: "valid", won: false, lost: false, count: 12 }, { key: "lost", label: "Lost", category: "valid", won: false, lost: true, count: 9 }],
      lost_by_reason: [{ reason: "wrong_dates", label: "Dates did not work", count: 4 }], unqualified: 2, basis: "" },
    caravans: { restricted: false, month: "2026-10-01", days_in_month: 31, basis: "",
      items: [{ property_id: "p1", name: "Ratha 1", booked_value: 132400, nights: 11, occupancy_pct: 35 }, { property_id: "p2", name: "Ratha 2", booked_value: 100400, nights: 8, occupancy_pct: 26 }] },
    ai_calls: { sales_actions: { count: 2, href: "/dashboard/inbox", items: [{ name: "Meera", href: "/dashboard/leads/i1" }, { name: "Vikram", href: "/dashboard/leads/i2" }] },
      autopilot: { count: 5, href: "/dashboard/settings/lead-autopilot", by_stage: [{ label: "Lost", count: 3 }, { label: "RNR", count: 2 }], items: [] },
      calls: { total: 61, missed: 6, returned: 5, not_returned: 1, href: "/dashboard/calls" } },
    team: { month: "2026-10-01", from: "2026-10-01", to: "2026-10-19", unattributed: null, basis: "",
      rows: [{ agent_id: "u1", name: "Jishanth", target: 300000, achieved: 142000, achieved_pct: 47.3, calls: 58, leads_owned: 14, median_first_reply_seconds: 540 }] },
    ...patch,
  };
}

function overview(o: OwnerBlock = owner()) {
  return {
    generated_at: "2026-10-19T09:00:00+00:00",
    period: { date_from: "2026-10-19", date_to: "2026-10-19", timezone: "Asia/Kolkata", previous_from: "2026-10-18", previous_to: "2026-10-18" },
    filters: { property_id: null, channel: null, agent_id: null },
    access: { tenant_wide: true, bookings: true, revenue: true },
    leads: { definition: "A lead is a person we hold a usable phone number for." },
    sources: [{ key: "instagram", label: "Instagram", leads: 15, bookings: null, booking_value: null }, { key: "organic_call", label: "Organic calls", leads: 3, bookings: null, booking_value: null }],
    insights: [],
    bookings: { restricted: false, upcoming_checkouts: 4 },
    series: { granularity: "day", days: ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19"], period_start_index: 6,
      leads: [2, 1, 3, 0, 2, 4, 14], conversations: [0, 0, 0, 0, 0, 0, 0], bookings: [0, 1, 0, 0, 1, 0, 3], booking_value: [0, 40000, 0, 0, 52000, 0, 133000],
      net_collected: [0, 0, 0, 0, 0, 0, 86000], calls: [40, 52, 38, 61, 47, 30, 61], calls_missed: [3, 5, 2, 8, 4, 1, 6] },
    funnel: { basis: "People who became leads in the period", note: "", stages: [
      { key: "identified", label: "New leads", count: 14, previous: 11, rate_from_previous: null, change: null },
      { key: "qualified", label: "With dates", count: 9, previous: 0, rate_from_previous: 64.3, change: null },
      { key: "booked", label: "Booked", count: 3, previous: 0, rate_from_previous: 33.3, change: null },
      { key: "paid", label: "Paid", count: 2, previous: 0, rate_from_previous: 66.7, change: null }] },
    owner: o,
  };
}

const waiting = (kind: string, severity: string, id: string, title: string) =>
  ({ kind, severity, guest_id: id, title, detail: "", action: "", href: `/dashboard/leads/${id}`, channels: ["whatsapp"], since: null });
const QUEUE = { people_waiting: 3, total: 3, severity: {}, items: [waiting("callback", "urgent", "a", "Meera Iyer"), waiting("reply", "late", "b", "Ananya Rao"), waiting("followup", "fresh", "c", "Rohan Mehta")] };
const TRIP = { id: "s1", external_id: "s1", checkin: "2026-10-21", checkout: "2026-10-23", adults: 2, children: 0, status: "confirmed", raw_status: "confirmed",
  payment_status: "partial", total: 60000, total_paid: 30000, total_outstanding: 30000, payment_overdue: false, trip: "Coorg",
  property: { id: "p1", name: "Ratha 1", type: "caravan" }, main_guest: { id: "g", first_name: "Fathima", last_name: "Rizwan", phone: null, email: null },
  next_payment_due_date: null, next_payment_amount: 0, channel: null, created_at: null, inquiry_id: null, deposit: null, check_in_time: null, check_out_time: null };

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function serve(payload: unknown | Error) {
  get.mockImplementation((url: string) => {
    if (url === "/dashboard/business-overview") return payload instanceof Error ? Promise.reject(payload) : Promise.resolve({ data: payload });
    if (url === "/work-queue") return Promise.resolve({ data: QUEUE });
    if (url === "/bookings") return Promise.resolve({ data: { data: [TRIP], meta: { current_page: 1, last_page: 1, per_page: 100, total: 1, from: 1, to: 1 } } });
    return Promise.resolve({ data: [] });
  });
}

beforeEach(() => { get.mockReset(); cleanup(); window.sessionStorage.clear(); window.localStorage.clear(); });

describe("owner dashboard helpers", () => {
  it("writes money in Indian units and never invents a figure", () => {
    expect(lakh(25000)).toBe("₹25,000");
    expect(lakh(125000)).toBe("₹1.25 L");
    expect(lakh(600000)).toBe("₹6 L");
    expect(lakh(32000000)).toBe("₹3.2 Cr");
    expect(lakh(null)).toBe("—");
    expect(inr(125000)).toBe("₹1,25,000");
  });
  it("shows a change only against a real baseline", () => {
    expect(deltaText(null, 0).tone).toBe("none");
    expect(deltaText({ pct: -100, direction: "down" }, 0).text).toBe("nothing to compare with before");   // never -100% against nothing
    expect(deltaText({ pct: 27.3, direction: "up" }, 11).text).toBe("▲ 27.3% vs 11 before");
    expect(deltaText({ pct: -10, direction: "down" }, 200000, true).text).toBe("▼ 10% vs ₹2 L before");
  });
  it("stacks rental and add-ons against the target and places the pace line", () => {
    expect(targetBars({ target: 600000, booked: { total: 232800, rental: 208000, add_ons: 24800, count: 7 }, pace_pct: 61.3 }))
      .toEqual({ rental: (208000 / 600000) * 100, addOns: (24800 / 600000) * 100, pace: 61.3, over: false });
    const over = targetBars({ target: 100, booked: { total: 150, rental: 120, add_ons: 30, count: 1 }, pace_pct: 50 });
    expect(over.rental + over.addOns).toBe(100);
    expect(over.over).toBe(true);
  });
  it("labels ages, days and weeks", () => {
    const now = Date.parse("2026-10-19T12:00:00Z");
    expect(ageText("2026-10-19T09:00:00Z", now)).toBe("3h");
    expect(ageText("2026-10-17T12:00:00Z", now)).toBe("2d");
    expect(ageText(null, now)).toBe("");
    expect([whenText(0), whenText(1), whenText(6)]).toEqual(["Today", "Tomorrow", "In 6 days"]);
    expect(weekLabel("2026-10-19", 0)).toBe("This week");
    expect(weekLabel("2026-10-26", 1)).toBe("Next week");
    expect(weekLabel(null, 5)).toBe("Later");
    expect(periodLabel("2026-10-19", "2026-10-19")).toMatch(/^19 Oct\w* 2026$/);
  });
});

describe("CommandCenter (layout A)", () => {
  it("opens on Today with the one-glance Overview in its order: who is waiting, the numbers, the trend, the next 7 days", async () => {
    serve(overview());
    const { container } = wrap(<CommandCenter />);
    expect((await screen.findByRole("link", { name: "3 people waiting. Open My day" })).getAttribute("href")).toBe("/dashboard/my-day");
    const call = get.mock.calls.find(c => c[0] === "/dashboard/business-overview")!;
    expect(call[1].params).toEqual({ date_preset: "today" });

    const tiles = within(await screen.findByRole("region", { name: "Numbers, Today" }));
    expect(tiles.getByRole("link", { name: /New leads/ }).textContent).toContain("14");
    expect(tiles.getByRole("img", { name: "15 from Instagram" })).toBeTruthy();
    expect(tiles.getByRole("link", { name: /Calls/ }).textContent).toContain("61");
    expect(tiles.getByRole("img", { name: "6 missed" })).toBeTruthy();
    expect(tiles.getByRole("link", { name: /Bookings/ }).textContent).toContain("3");
    expect(tiles.getByRole("link", { name: /Booked value/ }).textContent).toContain("₹1.33 L");
    expect(tiles.getByRole("img", { name: "Calls, last 7 days: 40, 52, 38, 61, 47, 30, 61" })).toBeTruthy();

    const text = container.textContent ?? "";
    let pos = 0;
    for (const title of ["waiting for your team", "New leads per day", "Calls per day", "From lead to booking", "Check-ins · 7 days", "Waiting for you", "Arriving next"]) {
      const next = text.indexOf(title, pos);          // each block is found after the one before it
      expect(next, title).toBeGreaterThanOrEqual(pos);
      pos = next;
    }
    expect(within(screen.getByRole("region", { name: "Waiting for you" })).getByText("Meera Iyer")).toBeTruthy();
    expect(within(await screen.findByRole("region", { name: "Arriving next" })).getByText("₹30,000 due")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Next 7 days" })).getByText("Check-outs · 7 days").closest("a")?.textContent).toContain("4");
    // the pickers stay behind Filters until someone needs them; attention cards, target and payment received live on their tabs
    expect(screen.queryByLabelText("Channel")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    expect(screen.getByLabelText("Channel")).toBeTruthy();
    expect(text).not.toMatch(/Needs attention|October target|Cash collected|Net cash/);
    expect(text).not.toMatch(/conversation|without a phone number\b(?! are handled)/i);
  });

  it("puts each block on its dashboard tab", async () => {
    serve(overview());
    for (const [tab, titles] of [["leads", ["Needs attention", "Payment received", "When leads want to travel", "Where leads came from", "Leads by stage", "AI and calls"]],
      ["revenue", ["October target", "Caravans"]], ["team", ["Team"]]] as const) {
      nav.search = `tab=${tab}`;
      const { container, unmount } = wrap(<CommandCenter />);
      await screen.findByRole("button", { name: "Overview" });
      await waitFor(() => { for (const t of titles) expect(container.textContent, `${tab}: ${t}`).toContain(t); });
      if (tab !== "leads") expect(container.textContent).not.toContain("Needs attention");
      expect(container.textContent).not.toContain("New leads per day");       // the one-glance blocks are the Overview's
      unmount();
    }
    nav.search = "";
  });

  it("shows each attention card's count, reason, first names and link on the Leads tab", async () => {
    nav.search = "tab=leads";
    serve(overview());
    wrap(<CommandCenter />);
    const card = (await screen.findByRole("heading", { name: "Not replying" })).closest("div.haip-card") as HTMLElement;
    nav.search = "";
    expect(within(card).getByText("Pooja Nair")).toBeTruthy();
    expect(within(card).getByText(/24 h or more/)).toBeTruthy();
    expect(within(card).getByRole("link").getAttribute("href")).toBe("/dashboard/my-day?kind=no_reply");
    const owing = screen.getByRole("heading", { name: "Bookings still owing money" }).closest("div.haip-card") as HTMLElement;
    expect(owing.textContent).toMatch(/₹1.28 L/);
    expect(owing.textContent).toMatch(/2 bookings/);
    const clear = screen.getByRole("heading", { name: "Missed calls not returned" }).closest("div.haip-card") as HTMLElement;
    expect(clear.textContent).toMatch(/All clear/);
  });

  it("asks the server again for another period and another check-in window", async () => {
    serve(overview());
    wrap(<CommandCenter />);
    await screen.findByText("New leads per day");
    await userEvent.click(screen.getByRole("tab", { name: "This month" }));
    await waitFor(() => expect(get.mock.calls.some(c => c[1]?.params?.date_preset === "this_month")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Next 30 days" }));
    await waitFor(() => expect(get.mock.calls.some(c => c[1]?.params?.window_days === 30)).toBe(true));
    expect(window.sessionStorage.getItem("haip_dashboard_period_session")).toBe("this_month");
    expect(window.localStorage.getItem("haip_dashboard_period")).toBeNull();
  });

  it("shows the empty target state with a link when no target is set", async () => {
    nav.search = "tab=revenue";
    serve(overview(owner({ target: { restricted: false, month: "2026-10-01", from: "2026-10-01", to: "2026-10-31", days_in_month: 31, days_elapsed: 19,
      days_left: 12, basis: "", available: false, reason: "No target is set for this month.", href: "/dashboard/targets",
      booked: { total: 1000, rental: 1000, add_ons: 0, count: 1 }, payment_received: 0, pace_pct: 61.3 } })));
    wrap(<CommandCenter />);
    expect(await screen.findByText("No target is set for this month.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Set this month’s target" }).getAttribute("href")).toBe("/dashboard/targets");
    nav.search = "";
  });

  it("explains hidden numbers instead of showing zeros", async () => {
    const hidden = overview(owner({ target: { restricted: true }, movements: { restricted: true }, caravans: { restricted: true }, team: null, ai_calls: null,
      kpis: { ...owner().kpis, booked_value: { restricted: true }, payment_received: { restricted: true } } }));
    serve(hidden);
    const first = wrap(<CommandCenter />);
    // Overview: the tile says the number is hidden; with no call figures for this viewer there is no Calls tile at all
    expect(await screen.findByRole("link", { name: "Booked value: hidden for your role" })).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Numbers, Today" })).queryByRole("link", { name: /Calls/ })).toBeNull();
    expect(first.container.textContent).not.toMatch(/₹0\b/);
    first.unmount();

    nav.search = "tab=revenue";
    const { container } = wrap(<CommandCenter />);
    expect(await screen.findByText(/Targets and amounts are hidden for your role/)).toBeTruthy();
    expect(screen.getAllByText(/Bookings are hidden for your role/).length).toBeGreaterThanOrEqual(1);
    expect(container.textContent).not.toMatch(/₹0\b/);
    nav.search = "";
  });

  it("shows an error state with a retry when the first load fails", async () => {
    serve(new Error("boom"));
    wrap(<CommandCenter />);
    expect(await screen.findByText("The business overview didn’t load.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});

describe("why the overview did not load", () => {
  it("tells a missing module, a missing role, a signed-out session and a network failure apart", async () => {
    const { overviewProblem } = await import("./CommandCenter");
    const http = (status: number, detail: unknown) => ({ response: { status, data: { detail } } });
    expect(overviewProblem(http(403, { error: "module_not_enabled", missing_modules: ["analytics"] })).title).toMatch(/switched on for this workspace/);
    expect(overviewProblem(http(403, "Insufficient permissions")).title).toMatch(/role doesn.t include/);
    expect(overviewProblem(http(401, "x")).title).toMatch(/signed out/);
    expect(overviewProblem(new Error("Network Error")).canRetry).toBe(true);
    expect(overviewProblem(http(403, "no")).canRetry).toBe(false);
  });
});
