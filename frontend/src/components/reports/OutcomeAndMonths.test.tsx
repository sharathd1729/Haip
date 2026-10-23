import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a) } }));

import { CheckinMonths } from "./CheckinMonths";
import { OutcomeReasons } from "./OutcomeReasons";

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
const row = (label: string, extra = {}) => ({ month: "2026-11-01", label, enquiries: 3, valid: 2, won: 1, lost: 1, open: 1,
  top_lost_reasons: [{ reason: "price", label: "Price", count: 1 }], booked_revenue: 125000, ...extra });

beforeEach(() => get.mockReset());
afterEach(cleanup);

describe("CheckinMonths", () => {
  it("shows each month, the undated row and restricted money", async () => {
    get.mockResolvedValue({ data: { start: "2026-11", months: 1, skipped: 1, money: false, basis: "Basis.",
      rows: [row("Nov 2026", { booked_revenue: { restricted: true } })], no_date: { ...row("Date not given yet"), month: null, booked_revenue: undefined } } });
    wrap(<CheckinMonths />);
    expect(await screen.findByText("Nov 2026")).toBeTruthy();
    expect(screen.getByText("Date not given yet")).toBeTruthy();
    expect(screen.getByText("Revenue restricted")).toBeTruthy();
    expect(screen.getAllByText("Lost: Price 1").length).toBe(2);
    expect(screen.getByText(/1 with a check-in we could not read/)).toBeTruthy();
  });
});

describe("OutcomeReasons", () => {
  it("keeps confirmed apart from proposed", async () => {
    const side = (n: number) => ({ total: n + 1, confirmed: n, proposed: 1, not_recorded: 0,
      reasons: [{ reason: "price", label: "Price", confirmed: n, proposed: 1 }] });
    get.mockResolvedValue({ data: { from: "2026-10-01", to: "2026-10-30", basis: "closed", skipped: 0, won: side(0), lost: side(2),
      definitions: { confirmed: "Confirmed.", proposed: "Proposed." } } });
    wrap(<OutcomeReasons />);
    expect(await screen.findByText("Why we lost · 3")).toBeTruthy();
    expect(screen.getByText("2 confirmed · 1 proposed by AI · 0 not recorded yet")).toBeTruthy();
  });
});
