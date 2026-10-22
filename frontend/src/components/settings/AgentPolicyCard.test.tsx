import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const put = vi.fn(() => Promise.resolve({ data: {} }));
let role = "owner";
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), put: (...a: unknown[]) => put(...(a as [])) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { role } } }) }));

import { AgentPolicyCard, type AgentPolicy } from "./AgentPolicyCard";

afterEach(cleanup);
beforeEach(() => { get.mockReset(); put.mockClear(); role = "owner"; });

const policy: AgentPolicy = {
  modes: { discount: "consult", answer_faq: "autonomous" },
  defaults: { discount: "consult", answer_faq: "autonomous" },
  classes: [{ key: "answer_faq", label: "Answer questions" }, { key: "discount", label: "Discuss a discount" }],
};

function show() {
  get.mockResolvedValue({ data: policy });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><AgentPolicyCard /></QueryClientProvider>);
}

describe("AgentPolicyCard", () => {
  it("saves only the changed classes", async () => {
    show();
    const select = await screen.findByLabelText("Discuss a discount");
    await userEvent.selectOptions(select, "draft_for_approval");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/ai/agent-policy", { modes: { discount: "draft_for_approval" } }));
  });

  it("is read-only for a manager", async () => {
    role = "manager";
    show();
    const select = await screen.findByLabelText("Discuss a discount");
    expect((select as HTMLSelectElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });
});
