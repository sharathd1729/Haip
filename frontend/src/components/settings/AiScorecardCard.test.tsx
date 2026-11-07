import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a) } }));

import { AiScorecardCard, pct, secs, type IntentRow, type Scorecard } from "./AiScorecardCard";

afterEach(cleanup);

const empty: Scorecard = {
  period: "7d",
  ai_replies: { sent_alone: 0, approved_as_written: 0, edited: 0, rejected: 0, decided: 0, no_edit_share: null },
  consults: { opened: 0, expired: 0, by_reason: [] },
  answer_minutes: { answered: 0, median: null, p90: null, sla_minutes: 15, inside_sla_share: null },
  held_back: { total: 0, reasons: [] },
  conversion: { with_consult: { leads: 0, won: 0, rate: null }, without_consult: { leads: 0, won: 0, rate: null } },
  by_intent: { days: 30, min_decided: 30, intents: [] },
};

const row = (o: Partial<IntentRow>): IntentRow => ({
  intent: "faq_answer", drafts: 32, decided: 30, sent_autonomous: 20, reviewed: 10, too_few: false, verbatim_share: 0.4,
  edited_share: 0.4, median_edit_pct: 80, rejected_share: 0.2, expired_share: 0.063, median_action_sec: 300, ...o,
});

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><AiScorecardCard /></QueryClientProvider>);
}

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
    expect(secs(45)).toBe("45 s");
    expect(secs(300)).toBe("5 min");
    expect(secs(5400)).toBe("1.5 h");
  });

  it("shows drafts by intent for the last 30 days, with too few to judge under 30 decided", async () => {
    get.mockResolvedValue({ data: { ...empty, by_intent: { days: 30, min_decided: 30, intents: [
      row({}), row({ intent: "price_quote", decided: 3, too_few: true, verbatim_share: null, edited_share: null, rejected_share: null,
        expired_share: null, median_edit_pct: null, median_action_sec: null }),
    ] } } });
    renderCard();
    expect(await screen.findByText("Questions (FAQ)")).toBeTruthy();
    expect(screen.getByText("Drafts by intent (last 30 days)")).toBeTruthy();
    expect(screen.getByText("Price")).toBeTruthy();
    expect(screen.getByText("Too few to judge")).toBeTruthy();
    expect(screen.getAllByText("40%").length).toBeGreaterThan(0);
  });

  it("says when there are no drafts in the 30 days", async () => {
    get.mockResolvedValue({ data: empty });
    renderCard();
    expect(await screen.findByText("No AI drafts in the last 30 days")).toBeTruthy();
  });
});
