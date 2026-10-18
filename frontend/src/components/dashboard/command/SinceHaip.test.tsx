import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a) } }));

import { SinceHaip, changeText, formatValue, type SinceHaipView } from "./SinceHaip";

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

// Fixtures for the component, not product data.
const VIEW: SinceHaipView = {
  needs_go_live: false, go_live: "2026-09-29", days: 30, can_edit: true,
  windows: { before: { from: "2026-09-08", to: "2026-09-28", days: 21 }, with: { from: "2026-09-29", to: "2026-10-19", days: 21 } },
  tiles: [
    { key: "leads", label: "New leads", unit: "count", lower_is_better: false, definition: "d", restricted: false,
      before: { value: 0, n: 0, has_data: false, source: "Leads were not captured before HAIP." }, with: { value: 42 }, change: null },
    { key: "bookings", label: "Bookings made", unit: "count", lower_is_better: false, definition: "d", restricted: false,
      before: { value: 8, n: 8, has_data: true, source: "HAIP's booking records: 8 from the shared calendar." }, with: { value: 10 },
      change: { kind: "pct", value: 25, better: true } },
    { key: "booked_value", label: "Bookings value", restricted: true },
    { key: "first_reply_minutes", label: "Average first reply by the team", unit: "minutes", lower_is_better: true, definition: "d",
      restricted: false, before: { value: 95, n: 40, has_data: true, source: "Replies HAIP holds from personal WhatsApp (40 replies)." },
      with: { value: 12.5 }, change: { kind: "pct", value: -86.8, better: true } },
  ],
};

beforeEach(() => { cleanup(); get.mockReset(); });

describe("SinceHaip", () => {
  it("shows both windows, labels each before figure with its source and never a change against no data", async () => {
    get.mockResolvedValue({ data: VIEW });
    wrap(<SinceHaip />);
    expect(await screen.findByText("42")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/dashboard/impact/since-haip");
    expect(screen.getByText("No data")).toBeTruthy();
    expect(screen.getByText("Leads were not captured before HAIP.")).toBeTruthy();
    expect(screen.getByText("+25%")).toBeTruthy();
    expect(screen.getByText("-86.8%")).toBeTruthy();
    expect(screen.getByText("Hidden for your role")).toBeTruthy();
    expect(screen.queryByText(/-100%/)).toBeNull();
    expect(screen.getByText(/vs the 21 days before go-live/)).toBeTruthy();
  });

  it("asks the owner for a go-live date and tells a manager who sets it", async () => {
    get.mockResolvedValue({ data: { needs_go_live: true, go_live: null, days: 30, can_edit: true } });
    wrap(<SinceHaip />);
    expect(await screen.findByText("Set the go-live date")).toBeTruthy();
    cleanup();
    get.mockResolvedValue({ data: { needs_go_live: true, go_live: null, days: 30, can_edit: false } });
    wrap(<SinceHaip />);
    expect(await screen.findByText(/owner hasn’t set the date/)).toBeTruthy();
  });

  it("says when it did not load and offers a retry", async () => {
    get.mockRejectedValue(new Error("network"));
    wrap(<SinceHaip />);
    expect(await screen.findByText(/didn’t load/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});

describe("formatting", () => {
  it("formats by unit and colours the change by whether it is better", () => {
    expect(formatValue("minutes", 95)).toBe("1h 35m");
    expect(formatValue("count", null)).toBe("—");
    expect(changeText({ kind: "points", value: 3.5, better: false })).toEqual({ text: "+3.5 pts", tone: "danger" });
    expect(changeText({ kind: "pct", value: 0, better: null })).toEqual({ text: "0%", tone: "neutral" });
  });
});
