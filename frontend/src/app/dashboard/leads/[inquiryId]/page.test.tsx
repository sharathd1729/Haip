import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), patch: vi.fn() } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { id: "u1", name: "Jishanth", role: "reservations" } }, status: "authenticated" }) }));
const push = vi.fn();
vi.mock("next/navigation", () => ({ useParams: () => ({ inquiryId: "i1" }), useRouter: () => ({ push, back: vi.fn() }), usePathname: () => "/dashboard/leads/i1" }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
const openQuote = vi.fn();
vi.mock("@/components/quotes/QuoteSheetProvider", () => ({ useQuoteSheet: () => ({ open: openQuote, close: vi.fn() }) }));
vi.mock("@/components/providers/WorkspaceProvider", () => ({ useBusinessType: () => "caravan" }));

import LeadDetailPage from "./page";

const lead = {
  inquiry_id: "i1", guest_id: "g1", display_name: "Sharath N", source: "organic_call", stage_key: "general_enquiry", inquiry_stage: "new",
  check_in: "2026-11-01", check_out: "2026-11-02", adults: 8, children: 0, assigned_agent_name: "Jishanth", assigned_agent_id: "u1",
  // The old contradiction: a summary written when the lead was lost, while the stage is now a fresh enquiry.
  ai_summary: "Sharath was marked lost after asking for a discount.", ai_analysis: { written_stage_key: "lost" },
  quote_history: [], identity_signals: ["phone"], recommended_actions: [], autopilot: null,
};
const feed = {
  inquiry_id: "i1", guest_id: "g1", capped: false, total_available: 1, messages_restricted: false, bookings: [], tasks: [], merges: [], availability: [],
  items: [{ id: "call-1", kind: "call", at: "2026-10-17T13:12:00Z", call_id: "c1", direction: "inbound", answered: true, duration_seconds: 120, summary: "Asked about Kabini." }],
  channels: [{ conversation_id: "cwa", channel: "whatsapp", last_inbound_at: null, can_send: true, ai_enabled: true }],
  contact: { phone_masked: "+91 ••••• ••321", has_phone: true, has_whatsapp: true, has_instagram: false },
  trip: { route: "Kabini, via Mysuru", pickup: null, special_requests: null, lost_reason: null },
  facts: { unanswered_outbound_calls: 0, missed_inbound_unreturned: false, pending_drafts: 0, last_inbound_at: null, last_outbound_at: null },
};
const stages = [
  { id: "s1", key: "general_enquiry", label: "General Enquiry", order: 1, category: "invalid", is_closed_won: false, is_closed_lost: false, is_default_entry: true },
  { id: "s2", key: "active", label: "Active", order: 3, category: "valid", is_closed_won: false, is_closed_lost: false, is_default_entry: false },
  { id: "s3", key: "lost", label: "Lost", order: 5, category: "valid", is_closed_won: false, is_closed_lost: true, is_default_entry: false },
];

function routes(url: string) {
  if (url === "/leads/i1") return Promise.resolve({ data: lead });
  if (url === "/leads/i1/feed") return Promise.resolve({ data: feed });
  if (url === "/pipeline-stages") return Promise.resolve({ data: stages });
  if (url === "/users/me") return Promise.resolve({ data: { id: "u1" } });
  return Promise.resolve({ data: [] });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><LeadDetailPage /></QueryClientProvider>);
}

beforeEach(() => {
  get.mockReset(); post.mockReset(); push.mockReset();
  get.mockImplementation(routes);
  window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }) as never;
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(cleanup);

describe("Lead page (C · Chat)", () => {
  it("Call posts click-to-call for this lead and nothing on the page is a tel: or wa.me link", async () => {
    post.mockResolvedValue({ data: { status: "initiated", provider_call_id: "req-1" } });
    renderPage();
    expect(await screen.findByText("Asked about Kabini.")).toBeTruthy();

    await userEvent.click(screen.getAllByRole("button", { name: /^Call$/ })[0]);

    await waitFor(() => expect(post).toHaveBeenCalledWith("/calls/click-to-call", { inquiry_id: "i1" }));
    const panel = await screen.findByTestId("call-panel");
    expect(within(panel).getByText("Ringing your phone…")).toBeTruthy();
    expect(within(panel).queryByRole("button", { name: /hang up/i })).toBeNull();
    expect(document.querySelector("a[href^='tel:'], a[href*='wa.me']")).toBeNull();
  });

  it("derives one next step from the stage and flags a summary written at another stage", async () => {
    renderPage();
    const bar = await screen.findByTestId("next-step-bar");
    expect(within(bar).getByText("Call Sharath to qualify")).toBeTruthy();
    // the details panel says the same thing, and does not let the old "marked lost" summary contradict it
    expect(screen.getAllByText("Call Sharath to qualify").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId("summary-stale").textContent).toContain("Written when the lead was Lost");
  });

  it("Add booking goes to the new booking flow for this lead", async () => {
    renderPage();
    await screen.findByTestId("next-step-bar");
    await userEvent.click(screen.getByRole("button", { name: "Book" }));
    expect(push).toHaveBeenCalledWith("/dashboard/bookings/new?inquiry=i1");
  });
});
