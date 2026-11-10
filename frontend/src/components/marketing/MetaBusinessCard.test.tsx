import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const put = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: {
  get: (...a: unknown[]) => get(...a), put: (...a: unknown[]) => put(...a), post: (...a: unknown[]) => post(...a), delete: vi.fn(),
} }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { MetaBusinessCard, type MetaBusiness } from "./MetaBusinessCard";

const OFF: MetaBusiness = {
  connected: false, token_name: null, capabilities: null, pages: [], page: null, checked_at: null, token_expires_at: null,
  lead_forms: { enabled: false, forms: [], last_run_at: null, last_error: null, imported: 0, last_lead_at: null },
};
const ok = { ok: true, missing: [] };
const ON: MetaBusiness = {
  ...OFF, connected: true, token_name: "lead crm", pages: [{ id: "147", name: "Demo Villas" }], page: { id: "147", name: "Demo Villas" },
  capabilities: { ads: ok, lead_forms: ok, instagram_dm: { ok: false, missing: ["permission pages_messaging"] } },
};

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MetaBusinessCard /></QueryClientProvider>);
}

beforeEach(() => { cleanup(); get.mockReset(); put.mockReset(); post.mockReset(); });

describe("MetaBusinessCard", () => {
  it("asks for the token and sends it once", async () => {
    get.mockResolvedValue({ data: OFF });
    put.mockResolvedValue({ data: ON });
    renderIt();
    const input = await screen.findByLabelText("Meta Business token");
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.type(input, "  EAAWdemo-token-0123456789  ");
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/meta-business/token", { access_token: "EAAWdemo-token-0123456789" }));
    await screen.findByText("lead crm");
    expect(screen.queryByLabelText("Meta Business token")).toBeNull();      // the token is never shown again
  });

  it("says what is ready, what is missing, and switches lead forms on", async () => {
    get.mockResolvedValue({ data: ON });
    put.mockResolvedValue({ data: { ...ON, lead_forms: { ...ON.lead_forms, enabled: true, imported: 3, forms: [{ id: "f1", name: "Villa enquiry", status: "ACTIVE" }] } } });
    renderIt();
    await screen.findByText("Missing: permission pages_messaging");
    expect(screen.getAllByText("Ready").length).toBe(2);
    await userEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/meta-business/lead-forms", { enabled: true }));
    await screen.findByText("Villa enquiry");
    expect(screen.getByText(/3 leads brought in so far/)).toBeTruthy();
    post.mockResolvedValue({ data: {} });
    await userEvent.click(screen.getByRole("button", { name: "Import the last 90 days" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/meta-business/lead-forms/import", { days: 90 }));
  });

  it("hides the lead-form switch when the token cannot read lead forms", async () => {
    get.mockResolvedValue({ data: { ...ON, capabilities: { ...ON.capabilities!, lead_forms: { ok: false, missing: ["permission leads_retrieval"] } } } });
    renderIt();
    await screen.findByText("Missing: permission leads_retrieval");
    expect(screen.queryByRole("switch")).toBeNull();
  });
});
