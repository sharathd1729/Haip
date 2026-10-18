import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn(() => Promise.resolve({ data: {} }));
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...(a as [])) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { SalesActionCard, type SalesAction } from "./SalesActionCard";

afterEach(cleanup);
beforeEach(() => { get.mockReset(); post.mockClear(); });

const option = {
  quote_id: "q1", package_name: "Coorg 48-hour Retreat", destination: "Coorg", check_in: "2026-10-30", check_out: "2026-11-01", guests: 5,
  total: "78792.00", advance: "39396", valid_until: "2026-10-21", at_actuals: ["Tolls and parking"],
};
const action = (over: Partial<SalesAction> = {}): SalesAction => ({
  id: "a1", inquiry_id: "i1", conversation_id: "c1", quote_id: "q1", mode: "suggest", status: "pending",
  summary: { ...option, quote_number: "Q-ABC12345", fallback: null }, hold_reasons: [], last_error: null, can_decide: true,
  readiness: { can_send: true, blockers: [], warnings: [] }, ...over,
});

function show(rows: SalesAction[]) {
  get.mockResolvedValue({ data: rows });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><SalesActionCard conversationId="c1" /></QueryClientProvider>);
}

describe("SalesActionCard", () => {
  it("shows nothing when no quote waits for a person", async () => {
    const { container } = show([]);
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });

  it("shows the quote in lakh-style rupees and sends it on approve", async () => {
    show([action()]);
    expect(await screen.findByText(/Quote ready to send · Q-ABC12345/)).toBeTruthy();
    expect(screen.getByText("₹78,792")).toBeTruthy();
    expect(screen.getByText(/Tolls and parking/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /send quote \+ payment link/i }));
    expect(post).toHaveBeenCalledWith("/sales-actions/a1/approve");
  });

  it("blocks sending while something must be fixed and says what", async () => {
    show([action({ readiness: { can_send: false, blockers: [{ code: "stay_not_confirmed", message: "Confirm the overnight stay before sending the price." }], warnings: [] } })]);
    expect(await screen.findByText("Confirm the overnight stay before sending the price.")).toBeTruthy();
    expect((screen.getByRole("button", { name: /send quote/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("hides the decision buttons from someone who cannot send quotes", async () => {
    show([action({ can_decide: false })]);
    expect(await screen.findByText(/A teammate who can send quotes/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /send quote/i })).toBeNull();
  });
});
