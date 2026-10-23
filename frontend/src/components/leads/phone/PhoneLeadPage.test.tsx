import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), patch: vi.fn(), put: vi.fn() } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { id: "u1", name: "Jishanth", role: "reservations" } }, status: "authenticated" }) }));
vi.mock("next/navigation", () => ({ useParams: () => ({ inquiryId: "i1" }), useRouter: () => ({ push: vi.fn(), back: vi.fn() }), usePathname: () => "/dashboard/leads/i1" }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/components/quotes/QuoteSheetProvider", () => ({ useQuoteSheet: () => ({ open: vi.fn(), close: vi.fn() }) }));
vi.mock("@/components/providers/WorkspaceProvider", () => ({ useBusinessType: () => "caravan" }));

import LeadDetailPage from "@/app/dashboard/leads/[inquiryId]/page";
import { tripChips } from "./LeadHero";

// Fixtures for the component, not product data.
const lead = {
  inquiry_id: "i1", guest_id: "g1", display_name: "Monika Rao", source: "wa_direct", stage_key: "active", inquiry_stage: "new",
  check_in: "2026-11-26", check_out: null, adults: 4, children: 0, assigned_agent_name: "Jishank", assigned_agent_id: "u2",
  ai_summary: "Wants a Goa trip for 4; Goa isn't offered, so suggest Western Ghats to the Sea instead of a custom route.",
  quote_history: [], identity_signals: ["phone"], recommended_actions: [], autopilot: null, property_interest: ["Goa"],
};
const feed = {
  inquiry_id: "i1", guest_id: "g1", capped: false, total_available: 1, messages_restricted: false, bookings: [], tasks: [], merges: [], availability: [],
  items: [{ id: "m1", kind: "message", at: "2026-10-22T10:00:00Z", direction: "inbound", channel: "whatsapp", text: "Can you share details of renting a caravan?" }],
  channels: [{ conversation_id: "cwa", channel: "whatsapp", last_inbound_at: "2026-10-22T10:00:00Z", can_send: true, ai_enabled: true }],
  contact: { phone_masked: "+91 ••••• ••321", has_phone: true, has_whatsapp: true, has_instagram: false, first_touch_channel: "whatsapp" },
  trip: { route: null, pickup: null, special_requests: null, lost_reason: null },
  facts: { unanswered_outbound_calls: 0, missed_inbound_unreturned: false, pending_drafts: 0, last_inbound_at: "2026-10-22T10:00:00Z", last_outbound_at: null },
};
const stages = [
  { id: "s2", key: "active", label: "Active", order: 3, category: "valid", is_closed_won: false, is_closed_lost: false, is_default_entry: false },
  { id: "s3", key: "lost", label: "Lost", order: 5, category: "valid", is_closed_won: false, is_closed_lost: true, is_default_entry: false },
];

function routes(url: string) {
  if (url === "/leads/i1") return Promise.resolve({ data: lead });
  if (url === "/leads/i1/feed") return Promise.resolve({ data: feed });
  if (url === "/pipeline-stages") return Promise.resolve({ data: stages });
  if (url === "/users/me") return Promise.resolve({ data: { id: "u1" } });
  if (url === "/leads/i1/evidence") return Promise.resolve({ data: { items: [] } });
  return Promise.resolve({ data: [] });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><LeadDetailPage /></QueryClientProvider>);
}

beforeEach(() => {
  get.mockReset(); post.mockReset();
  get.mockImplementation(routes);
  post.mockResolvedValue({ data: {} });
  // A phone: below 768px every query matches (the desktop page's own "wide" query is never asked on this path).
  window.matchMedia = vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }) as never;
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(cleanup);

describe("Phone lead page", () => {
  it("shows who, stage · owner · channel, the trip chips with what is missing, the three actions and a one-line AI note", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Monika Rao" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Stage: Active" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Owner: Jishank" })).toBeTruthy();
    expect(screen.getByText("Goa")).toBeTruthy();
    expect(screen.getByText("4 adults")).toBeTruthy();
    expect(screen.getByText("no return date")).toBeTruthy();
    expect(screen.getByText("no budget")).toBeTruthy();
    expect((await screen.findAllByRole("button", { name: /^Call$/ })).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: /^WhatsApp$/ }).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Send package/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "more" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Activity" }).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByText("Can you share details of renting a caravan?")).toBeTruthy();
  });

  it("Call uses click-to-call for this lead, and the stage chip opens the audited stage sheet", async () => {
    renderPage();
    await userEvent.click((await screen.findAllByRole("button", { name: /^Call$/ }))[0]);
    expect(post).toHaveBeenCalledWith("/calls/click-to-call", { inquiry_id: "i1" });
    await userEvent.click(screen.getByRole("button", { name: "Stage: Active" }));
    expect(await screen.findByText("Move stage")).toBeTruthy();
  });

  it("moves between the Trip, Quotes and Evidence tabs", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Monika Rao" });
    await userEvent.click(screen.getByRole("tab", { name: "Trip" }));
    expect(screen.getByRole("tab", { name: "Trip" }).getAttribute("aria-selected")).toBe("true");
    await userEvent.click(screen.getByRole("tab", { name: "Evidence" }));
    expect(screen.getByRole("tab", { name: "Evidence" }).getAttribute("aria-selected")).toBe("true");
  });

  it("says when the lead is not found", async () => {
    get.mockImplementation((url: string) => url === "/leads/i1" ? Promise.reject({ response: { status: 404 } }) : routes(url));
    renderPage();
    expect(await screen.findByText("Lead not found")).toBeTruthy();
  });
});

describe("tripChips", () => {
  it("lists where, when, who and what is missing", () => {
    expect(tripChips({ ...lead, check_in: null } as never).map(c => c.text)).toEqual(["Goa", "4 adults", "no dates", "no budget"]);
    expect(tripChips({ ...lead, check_out: "2026-11-28", adults: 0, budget_estimate: 50000 } as never).filter(c => c.missing).map(c => c.text)).toEqual(["no guest count"]);
  });
});
