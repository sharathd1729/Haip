import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a) } }));

import { DailyLeadReport } from "./DailyLeadReport";
import { CheckinCoverage } from "./CheckinCoverage";

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const block = (a: number[], h: number[]) => ({
  automatic: { received: a[0], handled: a[1], in_valid_stage: a[2], conversions: a[3] },
  human: { reviewed: h[0], valid: h[1], not_valid: h[2], not_yet_reviewed: h[3] },
});

beforeEach(() => get.mockReset());
afterEach(cleanup);

describe("DailyLeadReport", () => {
  it("shows the automatic numbers apart from the human review, per agent", async () => {
    get.mockResolvedValue({ data: { date: "2026-10-21", definitions: {}, total: block([7, 5, 4, 1], [3, 2, 1, 4]),
      agents: [{ agent_id: "u1", name: "Asha", ...block([4, 3, 2, 1], [2, 2, 0, 2]) }] } });
    wrap(<DailyLeadReport />);
    expect(await screen.findByText("From the records (automatic)")).toBeTruthy();
    expect(screen.getByText("Reviewed by a person (Valid enquiry?)")).toBeTruthy();
    expect(screen.getAllByText("Asha").length).toBeGreaterThan(0);
    expect(get).toHaveBeenCalledWith("/reports/daily-validation", { params: { date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) } });
  });

  it("says so when it cannot load, with a retry", async () => {
    get.mockRejectedValue(new Error("down"));
    wrap(<DailyLeadReport />);
    expect(await screen.findByText("Couldn't load the report")).toBeTruthy();
    get.mockResolvedValue({ data: { date: "2026-10-21", definitions: {}, total: block([0, 0, 0, 0], [0, 0, 0, 0]), agents: [] } });
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Nothing on this day")).toBeTruthy();
  });
});

describe("CheckinCoverage", () => {
  it("flags a weekend below target and lists booked vehicles; each date on demand", async () => {
    const cover = (valid: number, below: boolean, booked: string[] = []) => ({ valid, reviewed_valid: 1, stage_valid: valid - 1, below_target: below, booked_vehicles: booked });
    get.mockResolvedValue({ data: { from: "2026-10-22", to: "2026-11-01", target: 5, vehicles: ["Ratha 1", "Ratha 2"], unparsed: 1, basis: "Open guest enquiries.",
      weekends: [{ friday: "2026-10-23", sunday: "2026-10-25", partial: false, ...cover(2, true, ["Ratha 1"]) },
                 { friday: "2026-10-30", sunday: "2026-11-01", partial: false, ...cover(6, false) }],
      days: [{ date: "2026-10-23", weekday: "Fri", is_weekend: true, ...cover(2, true, ["Ratha 1"]) }] } });
    wrap(<CheckinCoverage />);
    expect(await screen.findByText("Below target")).toBeTruthy();
    expect(screen.getByText("On target")).toBeTruthy();
    expect(screen.getByText(/Booked: Ratha 1 \(1 of 2\)/)).toBeTruthy();
    expect(screen.getByText(/could not read/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Show each date" }));
    expect(screen.getByText("Fri 23 Oct")).toBeTruthy();
  });
});
