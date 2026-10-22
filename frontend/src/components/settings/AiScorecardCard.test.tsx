import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a) } }));

import { AiScorecardCard, pct, type Scorecard } from "./AiScorecardCard";

afterEach(cleanup);

const empty: Scorecard = {
  period: "7d",
  ai_replies: { sent_alone: 0, approved_as_written: 0, edited: 0, rejected: 0, decided: 0, no_edit_share: null },
  consults: { opened: 0, expired: 0, by_reason: [] },
  answer_minutes: { answered: 0, median: null, p90: null, sla_minutes: 15, inside_sla_share: null },
  held_back: { total: 0, reasons: [] },
  conversion: { with_consult: { leads: 0, won: 0, rate: null }, without_consult: { leads: 0, won: 0, rate: null } },
};

describe("AiScorecardCard", () => {
  it("says No data on an empty period instead of a fake percentage, and names the period", async () => {
    get.mockResolvedValue({ data: empty });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><AiScorecardCard /></QueryClientProvider>);
    expect((await screen.findAllByText("No data")).length).toBeGreaterThan(2);
    expect(screen.queryByText("0%")).toBeNull();
    expect(screen.getAllByText(/last 7 days/).length).toBeGreaterThan(0);
  });

  it("formats shares", () => {
    expect(pct(null)).toBe("No data");
    expect(pct(0.6)).toBe("60%");
  });
});
