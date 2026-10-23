import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), patch: (...a: unknown[]) => patch(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { OutcomeSheet, type OutcomeView } from "./OutcomeSheet";

const catalogue = {
  lost: [{ key: "price", label: "Price" }, { key: "dates_unavailable", label: "Dates not available" }],
  won: [{ key: "package_fit", label: "The package fit" }],
};
const ready: OutcomeView = { reason: null, note: null, source: null, catalogue,
  proposal: { kind: "lost", status: "ready", reason: "price", label: "Price", confidence: 0.8,
    quotes: [{ source: "message", id: "m1", text: "the price is too high for us" }] } };
const lost = { id: "s-lost", key: "lost", label: "Lost", order: 9, category: "valid", is_closed_lost: true, is_closed_won: false };

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => { get.mockReset(); post.mockReset(); patch.mockReset(); patch.mockResolvedValue({ data: {} }); });
afterEach(cleanup);

describe("OutcomeSheet", () => {
  it("asks the AI, preselects its reason with the quote, and confirms with one tap", async () => {
    post.mockResolvedValue({ data: ready });
    get.mockResolvedValue({ data: ready });
    wrap(<OutcomeSheet open onClose={vi.fn()} inquiryId="i1" name="Ravi" kind="lost" stage={lost as never} />);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads/i1/outcome/propose", { kind: "lost" }));
    expect(await screen.findByText(/the price is too high for us/)).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("radio", { name: /Price/ }).getAttribute("aria-checked")).toBe("true"));
    await userEvent.click(screen.getByRole("button", { name: /Confirm lost/ }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/inquiries/i1", { stage_id: "s-lost", outcome_reason: "price" }));
  });

  it("lets a person pick another reason when there is no suggestion", async () => {
    const none = { ...ready, proposal: { kind: "lost" as const, status: "no_evidence" as const } };
    post.mockResolvedValue({ data: none });
    get.mockResolvedValue({ data: none });
    wrap(<OutcomeSheet open onClose={vi.fn()} inquiryId="i1" name="Ravi" kind="lost" stage={lost as never} />);
    expect(await screen.findByText(/No calls or chats to read yet/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /Confirm lost/ }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole("radio", { name: /Dates not available/ }));
    await userEvent.type(screen.getByPlaceholderText("Note (optional)"), "Wanted Diwali");
    await userEvent.click(screen.getByRole("button", { name: /Confirm lost/ }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/inquiries/i1",
      { stage_id: "s-lost", outcome_reason: "dates_unavailable", outcome_reason_note: "Wanted Diwali" }));
  });
});
