import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn(() => Promise.resolve({ data: { delivery: "queued" } }));
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...(a as [])) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { ConsultCard, type Consult } from "./ConsultCard";
import { ConsultBanner } from "./ConsultsPanel";

afterEach(cleanup);
beforeEach(() => { get.mockReset(); post.mockClear(); });

const consult = (over: Partial<Consult> = {}): Consult => ({
  id: "k1", conversation_id: "c1", guest_id: "g1", guest_name: "Priya", inquiry_id: null, channel: "whatsapp", status: "open",
  level: "manager", reasons: [{ code: "discount_request", label: "The guest asked for a discount or a better price" }],
  question: "Any discount for 2 days?", proposed_answer: "We can add the Culinary kit.", options: [], evidence: {},
  sla_due_at: "2026-10-22T09:15:00Z", overdue: false, created_at: "2026-10-22T09:00:00Z", holding_sent: true, window_open: true,
  assigned_name: null, answered_name: null, answer_mode: null, delivery: null, ...over,
});

function show(c: Consult) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ConsultCard consult={c} /></QueryClientProvider>);
}

describe("ConsultCard", () => {
  it("shows the question, why the AI asked and the held answer; Approve sends it", async () => {
    show(consult());
    expect(screen.getByText("“Any discount for 2 days?”")).toBeTruthy();
    expect(screen.getByText("The guest asked for a discount or a better price")).toBeTruthy();
    expect(screen.getByText("We can add the Culinary kit.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Approve & send" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/consults/k1/answer", { mode: "approve_proposed", save_to_kb: false }));
  });

  it("Edit & send posts the edited text", async () => {
    show(consult());
    await userEvent.click(screen.getByRole("button", { name: "Edit & send" }));
    const box = screen.getByLabelText("Your answer to the guest");
    await userEvent.clear(box);
    await userEvent.type(box, "No discount, but a free kit");
    await userEvent.click(screen.getByRole("button", { name: "Send my answer" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/consults/k1/answer", { mode: "edited", text: "No discount, but a free kit", save_to_kb: false }));
  });

  it("warns when the 24-hour window is closed and offers no approve without a proposed answer", () => {
    show(consult({ window_open: false, proposed_answer: null }));
    expect(screen.getByText(/24-hour window is closed/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve & send" })).toBeNull();
  });
});

describe("ConsultBanner", () => {
  it("renders nothing when the thread has no open consult", async () => {
    get.mockResolvedValue({ data: [] });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(<QueryClientProvider client={qc}><ConsultBanner conversationId="c1" /></QueryClientProvider>);
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});
