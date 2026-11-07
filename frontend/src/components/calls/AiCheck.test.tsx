import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { AiCheck } from "./AiCheck";

function renderIt(props: { ai?: string | null; human?: string | null }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><AiCheck callId="c1" {...props} /></QueryClientProvider>);
}

beforeEach(() => { cleanup(); post.mockReset(); post.mockResolvedValue({ data: {} }); });

describe("AiCheck", () => {
  it("Yes confirms the AI's outcome in one tap", async () => {
    renderIt({ ai: "hot" });
    expect(screen.getByText(/Was the AI right\?/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Yes/ }));
    expect(post).toHaveBeenCalledWith("/calls/c1/disposition/confirm", { ai_correct: true });
  });

  it("No asks for the right outcome, without offering the AI's own", async () => {
    renderIt({ ai: "hot" });
    await userEvent.click(screen.getByRole("button", { name: /No/ }));
    expect(screen.queryByRole("button", { name: "Hot lead" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Callback" }));
    expect(post).toHaveBeenCalledWith("/calls/c1/disposition/confirm", { ai_correct: false, disposition: "callback" });
  });

  it("shows the answer once confirmed and nothing before the AI has read the call", () => {
    renderIt({ ai: "booked", human: "lost" });
    expect(screen.getByText(/AI said Booked/)).toBeTruthy();
    cleanup();
    const { container } = renderIt({ ai: null });
    expect(container.textContent).toBe("");
  });
});
