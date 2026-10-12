import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { name: "Sharath D", role: "owner" } }, status: "authenticated" }) }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { AttentionStrip } from "./AttentionStrip";
import { CommandCenter } from "./CommandCenter";
import { JourneyBand } from "./JourneyBand";
import { KpiGrid } from "./KpiGrid";
import { Ledger } from "./Ledger";
import { Team } from "./Team";
import { Trends } from "./Trends";
import { inr, inrShort, pct, periodLabel, type BusinessOverview } from "./types";

// A small workspace with every block present. Values are fixtures for the component, not product data.
function overview(patch: Partial<BusinessOverview> = {}): BusinessOverview {
  return {
    generated_at: "2026-09-20T09:00:00+00:00",
    period: { date_from: "2026-09-10", date_to: "2026-09-20", timezone: "Asia/Kolkata", previous_from: "2026-08-30", previous_to: "2026-09-09" },
    filters: { property_id: null, channel: null, agent_id: null },
    access: { tenant_wide: true, bookings: true, revenue: true },
    leads: { received: 124, received_change: { pct: 12.5, direction: "up" }, valid: 90, invalid: 30, marked_spam_excluded: 4,
      converted_to_booking: 18, conversion_rate: 14.5, conversion_basis: "cohort", unassigned_now: 3,
      lost: 11, by_expected_check_in: [{ month: "2026-11", count: 6 }, { month: "2026-12", count: 3 }], expected_check_in_unknown: 40,
      high_intent_at_risk: { count: 2, items: [{ inquiry_id: "i1", name: "Priya S", reason: "waiting for a reply", href: "/dashboard/leads/i1" }] } },
    bookings: { restricted: false, confirmed_created: 21, confirmed_change: { pct: 5, direction: "up" }, cancelled_of_created: 2,
      pending: { available: false, reason: "no pending status" }, upcoming_checkins: 6, upcoming_window_days: 7,
      needs_payment: 9, payment_overdue: 2, needs_payment_truncated: false, not_linked_to_a_lead: 3, upcoming_checkouts: 4,
      by_property: [{ property_id: "p1", name: "Caravan 1", bookings: 12, value: 800000 }], by_channel: [{ channel: "airbnb", bookings: 5, value: 300000 }], basis: "bookings made in the period" },
    revenue: { restricted: false, gross_booking_value: 1250000, gross_change: { pct: -8, direction: "down" }, add_ons_value: 40000,
      arriving_value: 900000, collected: 640000, collected_change: null, refunds: 25000, net_collected: 615000,
      outstanding_on_live_bookings: 410000, overdue_amount: 90000,
      net_revenue: { available: false, reason: "no tax or commission data" },
      target: { available: false, reason: "No target is set for this month." }, basis: "stay charge booked" },
    funnel: { basis: "cohort", note: "Counts the leads received in this period and what became of them so far.",
      stages: [
        { key: "received", label: "Lead received", count: 124, previous: 100, rate_from_previous: null, change: { pct: 24, direction: "up" } },
        { key: "valid", label: "Valid lead", count: 90, previous: 80, rate_from_previous: 72.6, change: null },
        { key: "booked", label: "Booking confirmed", count: 18, previous: 20, rate_from_previous: 20, change: { pct: -10, direction: "down" } },
        { key: "paid", label: "Payment collected", count: 11, previous: 12, rate_from_previous: 61.1, change: null },
      ] },
    series: { granularity: "day", days: ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"], period_start_index: 2, leads: [3, 4, 5, 6], bookings: [0, 1, 1, 2],
      booking_value: [0, 1000, 2000, 3000], net_collected: [0, 0, 500, 0] },
    pipeline: [{ stage: "Active", category: "valid", won: false, lost: false, count: 60 }, { stage: "Sold", category: "valid", won: true, lost: false, count: 18 }],
    sources: [{ key: "whatsapp", label: "WhatsApp", leads: 70, bookings: 12, booking_value: 800000 }],
    meta_ads: { configured: true, spend: 45000, reported_chats: 80, verified_conversations: 30, verified_leads: 28, verified_bookings: 4,
      verified_booking_value: 300000, not_traced: 50, cost_per_verified_lead: 1607, return_on_spend: 6.67 },
    agents: [{ agent_id: "u1", name: "Asha", leads: 40, valid: 30, invalid: 10, bookings: 8, booking_value: 500000, calls_answered: 20, calls_missed: 5, callbacks_waiting: 3,
      avg_response_seconds: 540, messages_sent: 120, followups_total: 20, followups_completed: 15, followups_overdue: 2, ai_drafts_approved: 9, ai_drafts_total: 12, avg_call_score: 82.5 }],
    attention: [
      { key: "unassigned", label: "Leads nobody owns", count: 3, oldest_at: null, href: "/dashboard/my-day" },
      { key: "waiting_reply", label: "Guests waiting for a reply", count: 0, oldest_at: null, href: "/dashboard/my-day" },
      { key: "payment_overdue", label: "Bookings with an overdue payment", count: 2, oldest_at: null, href: "/dashboard/bookings" },
    ],
    stale_integrations: [], insights: [],
    ...patch,
  };
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => { get.mockReset(); cleanup(); });

describe("formatting", () => {
  it("uses Indian grouping and never renders a missing number as zero", () => {
    expect(inr(125000)).toBe("₹1,25,000");
    expect(inr(null)).toBe("—");
    expect(pct(null)).toBe("—");
    expect(pct(14.5)).toBe("14.5%");
    expect(inrShort(12_50_000)).toBe("₹12.5L");
    expect(inrShort(3.4e7)).toBe("₹3.4Cr");
  });
  it("spells out the period", () => {
    // the month abbreviation is locale data ("Sep" or "Sept" depending on the ICU build), so match either
    expect(periodLabel("2026-09-10", "2026-09-20")).toMatch(/^10 Sep\w* – 20 Sep\w* 2026$/);
    expect(periodLabel("2026-09-12", "2026-09-12")).toMatch(/^12 Sep\w* 2026$/);
  });
});

describe("Ledger", () => {
  it("shows the three business columns with server-supplied figures", () => {
    render(<Ledger data={overview()} />);
    expect(screen.getByRole("heading", { name: "Leads" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Bookings" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Revenue" })).toBeTruthy();
    expect(screen.getByText("₹12,50,000")).toBeTruthy();            // gross booking value, Indian grouping
    expect(screen.getByText("124")).toBeTruthy();
    expect(screen.getByText("Not tracked")).toBeTruthy();           // pending bookings are not a HAIP concept
    expect(screen.getByText(/Net revenue: not available/)).toBeTruthy();
    expect(screen.getByText(/No target is set for this month/)).toBeTruthy();
  });

  it("explains a restricted block instead of showing a number", () => {
    const { container } = render(<Ledger data={overview({ revenue: { restricted: true }, bookings: { restricted: true } })} />);
    expect(screen.getByText(/Revenue figures are hidden for your role/)).toBeTruthy();
    expect(screen.getByText(/Booking figures are hidden for your role/)).toBeTruthy();
    expect(container.textContent).not.toMatch(/₹/);                  // no amount, and in particular no ₹0
  });

  it("links figures to the records behind them", () => {
    render(<Ledger data={overview()} />);
    const hrefs = screen.getAllByRole("link").map(a => a.getAttribute("href"));
    expect(hrefs).toContain("/dashboard/bookings?quick=due");
    expect(hrefs).toContain("/dashboard/bookings?quick=upcoming");
    expect(hrefs).toContain("/dashboard/my-day?kind=unassigned");
  });
});

describe("JourneyBand", () => {
  it("shows each stage's count and its rate from the previous stage, and says it is a cohort", () => {
    render(<JourneyBand data={overview()} />);
    const stages = screen.getAllByRole("listitem");
    expect(stages).toHaveLength(4);
    expect(within(stages[1]).getByText(/72.6% of lead received/)).toBeTruthy();
    expect(within(stages[2]).getByText(/20% of valid lead/)).toBeTruthy();
    expect(screen.getAllByText(/what became of them so far/).length).toBeGreaterThan(0);
    expect(screen.getByText(/3 bookings made in this period have no lead attached/)).toBeTruthy();
  });

  it("says there is nothing to show for an empty period rather than drawing zeros", () => {
    const empty = overview();
    empty.funnel.stages = empty.funnel.stages.map(s => ({ ...s, count: 0, previous: 0, rate_from_previous: null, change: null }));
    render(<JourneyBand data={empty} />);
    expect(screen.getByText(/no journey to show/)).toBeTruthy();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("hides the booking and payment stages from a viewer without booking access", () => {
    render(<JourneyBand data={overview({ bookings: { restricted: true } })} />);
    const stages = screen.getAllByRole("listitem");
    expect(within(stages[2]).getByText("—")).toBeTruthy();
    expect(within(stages[3]).getByText("—")).toBeTruthy();
  });
});

describe("AttentionStrip", () => {
  it("lists only what needs attention", () => {
    render(<AttentionStrip data={overview()} />);
    expect(screen.getByText("Leads nobody owns")).toBeTruthy();
    expect(screen.getByText("Bookings with an overdue payment")).toBeTruthy();
    expect(screen.queryByText("Guests waiting for a reply")).toBeNull();     // count 0: not listed
  });
  it("is quiet and says so when nothing is waiting", () => {
    render(<AttentionStrip data={overview({ attention: [], stale_integrations: [] })} />);
    expect(screen.getByText(/Nothing is waiting on your team/)).toBeTruthy();
  });
  it("surfaces a failing integration with words, not colour alone", () => {
    render(<AttentionStrip data={overview({ stale_integrations: [{ kind: "hostaway", label: "Hostaway", status: "red", last_sync: null, message: null, href: "/dashboard/settings/integrations" }] })} />);
    expect(screen.getByText(/has stopped syncing/)).toBeTruthy();
  });
});

describe("CommandCenter", () => {
  function serve(payload: unknown | Error) {
    get.mockImplementation((url: string) => {
      if (url === "/dashboard/business-overview") return payload instanceof Error ? Promise.reject(payload) : Promise.resolve({ data: payload });
      return Promise.resolve({ data: [] });
    });
  }

  it("renders the overview and asks the server for the selected period", async () => {
    serve(overview());
    wrap(<CommandCenter />);
    expect(await screen.findByText("From lead to payment")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/Sharath/);
    const call = get.mock.calls.find(c => c[0] === "/dashboard/business-overview")!;
    expect(call[1].params).toEqual({ date_preset: "this_month" });
    expect(screen.getByText(/India time \(IST\)/)).toBeTruthy();
  });

  it("sends the filters the user picks and keeps the page on screen while it reloads", async () => {
    serve(overview());
    wrap(<CommandCenter />);
    await screen.findByText("From lead to payment");
    await userEvent.click(screen.getByRole("tab", { name: "Last 7 days" }));
    await waitFor(() => expect(get.mock.calls.some(c => c[1]?.params?.date_preset === "last_7d")).toBe(true));
    expect(screen.getByText("From lead to payment")).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText("Channel"), "instagram");
    await waitFor(() => expect(get.mock.calls.some(c => c[1]?.params?.channel === "instagram")).toBe(true));
  });

  it("does not fetch a custom range until both dates are valid", async () => {
    serve(overview());
    wrap(<CommandCenter />);
    await screen.findByText("From lead to payment");
    get.mockClear();
    await userEvent.click(screen.getByRole("tab", { name: "Custom" }));
    expect(screen.getByText("Pick both dates to apply.")).toBeTruthy();
    expect(get.mock.calls.some(c => c[1]?.params?.date_preset === "custom")).toBe(false);
  });

  it("shows an error state with a retry when the first load fails", async () => {
    serve(new Error("boom"));
    wrap(<CommandCenter />);
    expect(await screen.findByText("The business overview didn’t load.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("renders a restricted viewer's page without any money", async () => {
    serve(overview({ access: { tenant_wide: false, bookings: true, revenue: false }, revenue: { restricted: true }, meta_ads: null, agents: null,
      sources: [{ key: "whatsapp", label: "WhatsApp", leads: 5, bookings: 1, booking_value: null }] }));
    const { container } = wrap(<CommandCenter />);
    expect(await screen.findByText(/Revenue figures are hidden for your role/)).toBeTruthy();
    expect(container.textContent).not.toMatch(/₹/);
    expect(screen.queryByLabelText("Agent")).toBeNull();            // agent filter is for owners and managers
  });
});


describe("KpiGrid", () => {
  it("shows six headline tiles that each open the records behind them", () => {
    render(<KpiGrid data={overview()} />);
    const tiles = screen.getAllByRole("link");
    expect(tiles).toHaveLength(6);
    expect(tiles.map(t => t.getAttribute("href"))).toEqual(["/dashboard/leads", "/dashboard/bookings", "/dashboard/targets", "/dashboard/bookings", "/dashboard/leads", "#needs-attention"]);
    expect(screen.getByText("₹12,50,000")).toBeTruthy();
    expect(screen.getByText("14.5%")).toBeTruthy();
  });
  it("counts the attention list in the sixth tile and never shows a restricted figure as zero", () => {
    const { container } = render(<KpiGrid data={overview({ revenue: { restricted: true }, bookings: { restricted: true } })} />);
    expect(screen.getAllByText("Restricted")).toHaveLength(3);
    expect(container.textContent).not.toMatch(/₹/);
    expect(screen.getByText("5")).toBeTruthy();         // 3 unassigned + 2 overdue payments, from the fixture's attention list
  });
});

describe("Ledger on a phone", () => {
  it("switches between Leads, Bookings and Revenue with a tab strip", async () => {
    render(<Ledger data={overview()} />);
    expect(screen.getByRole("tab", { name: "Leads" }).getAttribute("aria-selected")).toBe("true");
    await userEvent.click(screen.getByRole("tab", { name: "Revenue" }));
    expect(screen.getByRole("tab", { name: "Revenue" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Leads" }).getAttribute("aria-selected")).toBe("false");
  });
});

describe("Trends", () => {
  it("offers day, week and month and reports the choice", async () => {
    const onTrend = vi.fn();
    render(<Trends data={overview()} trend="day" onTrend={onTrend} />);
    await userEvent.click(screen.getByRole("tab", { name: "Weekly" }));
    expect(onTrend).toHaveBeenCalledWith("week");
    expect(screen.getByText(/Expected check-in of these leads/)).toBeTruthy();
    expect(screen.getByText(/11 lost/)).toBeTruthy();
  });
});

describe("Team", () => {
  it("shows the agent's leads, calls, replies, follow-ups and call quality, with unknowns as a dash", () => {
    const rows = overview().agents!;
    render(<Team rows={[...rows, { ...rows[0], agent_id: "u2", name: "Bala", avg_response_seconds: null, avg_call_score: null, calls_answered: 0, calls_missed: 0, callbacks_waiting: 0 }]} />);
    expect(screen.getAllByText("9m").length).toBeGreaterThan(0);          // 540 s
    expect(screen.getByText("82.5%")).toBeTruthy();
    expect(screen.getAllByText("20 / 5").length).toBeGreaterThan(0);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);   // Bala: no reply time or score yet
  });
  it("says so when there is no activity", () => {
    render(<Team rows={[]} />);
    expect(screen.getByText("No agent activity in this period.")).toBeTruthy();
  });
});
