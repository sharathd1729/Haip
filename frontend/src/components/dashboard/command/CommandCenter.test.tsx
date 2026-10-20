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
    owner: o,
  };
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function serve(payload: unknown | Error) {
  get.mockImplementation((url: string) => {
    if (url === "/dashboard/business-overview") return payload instanceof Error ? Promise.reject(payload) : Promise.resolve({ data: payload });
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
  it("opens on Today and renders every block in the approved order", async () => {
    serve(overview());
    const { container } = wrap(<CommandCenter />);
    expect(await screen.findByRole("heading", { name: "Needs attention" })).toBeTruthy();
    const call = get.mock.calls.find(c => c[0] === "/dashboard/business-overview")!;
    expect(call[1].params).toEqual({ date_preset: "today" });
    const order = ["Needs attention", "October target", "Check-ins and check-outs", "When leads want to travel", "Where leads came from",
      "Leads by stage", "Caravans", "AI and calls", "Team"];
    const text = container.textContent ?? "";
    let pos = text.indexOf("Needs attention");
    for (const title of order) {                      // each block is found after the one before it
      const next = text.indexOf(title, pos);
      expect(next, title).toBeGreaterThanOrEqual(pos);
      pos = next;
    }
    expect(screen.getByText("Payment received", { selector: "span" })).toBeTruthy();
    expect(text).not.toMatch(/Cash collected|Net cash/);
    expect(text).not.toMatch(/conversation|without a phone number\b(?! are handled)/i);
  });

  it("shows each attention card's count, reason, first names and link", async () => {
    serve(overview());
    wrap(<CommandCenter />);
    const card = (await screen.findByRole("heading", { name: "Not replying" })).closest("div.haip-card") as HTMLElement;
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
    await screen.findByRole("heading", { name: "Needs attention" });
    await userEvent.click(screen.getByRole("tab", { name: "This month" }));
    await waitFor(() => expect(get.mock.calls.some(c => c[1]?.params?.date_preset === "this_month")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Next 30 days" }));
    await waitFor(() => expect(get.mock.calls.some(c => c[1]?.params?.window_days === 30)).toBe(true));
    expect(window.sessionStorage.getItem("haip_dashboard_period_session")).toBe("this_month");
    expect(window.localStorage.getItem("haip_dashboard_period")).toBeNull();
  });

  it("shows the empty target state with a link when no target is set", async () => {
    serve(overview(owner({ target: { restricted: false, month: "2026-10-01", from: "2026-10-01", to: "2026-10-31", days_in_month: 31, days_elapsed: 19,
      days_left: 12, basis: "", available: false, reason: "No target is set for this month.", href: "/dashboard/targets",
      booked: { total: 1000, rental: 1000, add_ons: 0, count: 1 }, payment_received: 0, pace_pct: 61.3 } })));
    wrap(<CommandCenter />);
    expect(await screen.findByText("No target is set for this month.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Set this month’s target" }).getAttribute("href")).toBe("/dashboard/targets");
  });

  it("explains hidden blocks instead of showing zeros", async () => {
    serve(overview(owner({ target: { restricted: true }, movements: { restricted: true }, caravans: { restricted: true }, team: null, ai_calls: null,
      kpis: { ...owner().kpis, booked_value: { restricted: true }, payment_received: { restricted: true } } })));
    const { container } = wrap(<CommandCenter />);
    expect(await screen.findByText(/Targets and amounts are hidden for your role/)).toBeTruthy();
    expect(screen.getAllByText(/Bookings are hidden for your role/).length).toBe(2);
    expect(container.textContent).not.toMatch(/₹0\b/);
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
