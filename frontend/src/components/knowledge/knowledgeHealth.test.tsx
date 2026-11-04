import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { KnowledgeHealthCard, type HealthReport } from "./KnowledgeHealthCard";

const report: HealthReport = {
  period_days: 30, usable: 4, blocked: 1, counts: { gave_up: 1, never_used: 1 },
  words: {
    waiting_approval: "Waiting for your approval", indexing: "Being prepared for search", failed: "Preparing for search failed; it will retry",
    gave_up: "Preparing for search failed too often; press Re-index", out_of_date: "No longer on the page or post it came from",
    never_used: "Usable, but no reply used it in this period", off: "Switched off", rejected: "Rejected",
  },
  replies: { recorded: 12, by_search_status: { ok: 9, embedding_unavailable: 3 } },
  entries: [{ id: "e1", question: "Do you allow pets?", preview: "Pets are welcome", category: "faq", source: "manual", property_id: null,
              updated_at: null, reasons: [{ code: "gave_up", words: "Preparing for search failed too often; press Re-index" }],
              error: "NIM 504", times_used: 0 }],
  entries_capped: false,
};

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => { get.mockReset(); post.mockReset(); });
afterEach(() => cleanup());

describe("Knowledge health", () => {
  it("lists each unusable entry with its reason and the reply search outcomes; Re-index calls the refresh endpoint", async () => {
    get.mockResolvedValue({ data: report });
    post.mockResolvedValue({ data: { queued_for_indexing: 1 } });
    wrap(<KnowledgeHealthCard />);
    expect(await screen.findByText("Do you allow pets?")).toBeTruthy();
    expect(screen.getByText("Preparing for search failed too often; press Re-index")).toBeTruthy();
    expect(screen.getByText("NIM 504")).toBeTruthy();
    expect(screen.getByText("12 AI replies: 9 found passages, 3 search could not run.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Re-index/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/knowledge/refresh"));
  });

  it("is hidden from roles that may not see it", async () => {
    get.mockRejectedValue({ response: { status: 403 } });
    wrap(<KnowledgeHealthCard />);
    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("Knowledge health")).toBeNull());
  });
});
