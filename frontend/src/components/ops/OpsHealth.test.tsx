import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OpsHealth, fmtMinutes, fmtPct, type OpsMetrics } from "./OpsHealth";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a) } }));

const times = (median: number | null, count = 0) => ({ count, median_min: median, p90_min: median });
const metrics = (patch: Partial<OpsMetrics> = {}): OpsMetrics => ({
  period: { from: "2026-10-10", to: "2026-11-08", days: 30, label: "Last 30 days" },
  time_to_acknowledge: { all: times(12, 5), not_acknowledged: 0 },
  time_to_resolve: { all: times(null), closed_without_guest_answer: 0 },
  issues: { issues: 5, stays: 20, per_10_stays: 2.5, repeats: [] },
  ready_on_time: { judged: 0, on_time: 0, pct: null },
  paperwork_before_arrival: { judged: 4, complete: 3, pct: 75 },
  addon_revenue: { live: false, per_stay: null },
  reviews: { available: false, note: "not built yet" },
  in_stay_replies: { turns: 0, on_time: 0, pct: null },
  by_property: [],
  ...patch,
});

function show(m: OpsMetrics) {
  get.mockResolvedValueOnce({ data: m });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><OpsHealth /></QueryClientProvider>);
}

describe("ops metric formatting", () => {
  it("says No data for an empty figure, never 0", () => {
    expect(fmtMinutes(null)).toBe("No data");
    expect(fmtPct(null)).toBe("No data");
    expect(fmtMinutes(0)).toBe("0 min");
    expect(fmtMinutes(135)).toBe("2 h 15 min");
    expect(fmtMinutes(4 * 1440)).toBe("4 days");
  });
});

describe("OpsHealth", () => {
  it("shows each figure with its period, and No data where nothing was judged", async () => {
    show(metrics());
    expect(await screen.findByText("12 min")).toBeTruthy();
    expect(screen.getByText("2.5")).toBeTruthy();
    expect(screen.getByText("75%")).toBeTruthy();
    expect(screen.getAllByText("No data").length).toBe(4);   // fix time, ready, add-ons, replies
    expect(screen.getByText("no add-ons sold yet")).toBeTruthy();
    expect(screen.getByText(/last 30 days, IST/)).toBeTruthy();
  });

  it("shows one empty state when the period has nothing at all", async () => {
    show(metrics({ issues: { issues: 0, stays: 0, per_10_stays: null, repeats: [] }, time_to_acknowledge: { all: times(null), not_acknowledged: 0 } }));
    expect(await screen.findByText("No stays or issues in the last 30 days yet")).toBeTruthy();
  });
});
