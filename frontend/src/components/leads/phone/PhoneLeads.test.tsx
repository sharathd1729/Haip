import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), patch: (...a: unknown[]) => patch(...a) } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { id: "u1", name: "Asha", role: "concierge" } }, status: "authenticated" }) }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { PhoneLeads } from "./PhoneLeads";
import { matches, tripText, waitedText } from "./leadRow";

if (typeof window.PointerEvent === "undefined") {
  (window as unknown as { PointerEvent: typeof MouseEvent }).PointerEvent = class extends MouseEvent {} as typeof MouseEvent;
}

const STAGES = [
  { id: "s1", key: "general_enquiry", label: "General Enquiry", color: "#888", order: 1, is_default_entry: true, is_closed_won: false, is_closed_lost: false, category: "invalid", is_valid_lead_entry: false, is_collab_entry: false, lead_count: 0 },
  { id: "s2", key: "active", label: "Active", color: "#888", order: 2, is_default_entry: false, is_closed_won: false, is_closed_lost: false, category: "valid", is_valid_lead_entry: true, is_collab_entry: false, lead_count: 0 },
  { id: "s3", key: "lost", label: "Lost", color: "#888", order: 3, is_default_entry: false, is_closed_won: false, is_closed_lost: true, category: "valid", is_valid_lead_entry: false, is_collab_entry: false, lead_count: 0 },
];
function lead(id: string, patch: Record<string, unknown> = {}) {
  return { inquiry_id: id, guest_id: `g${id}`, display_name: "Monika", profile_completeness_pct: 50, identity_signals: ["phone"], inquiry_stage: "new",
    stage_key: "active", property_interest: ["Goa"], check_in: "2026-11-26", ai_summary: "Wants a Goa trip for 4; Goa is not offered, suggest Western Ghats to the Sea instead",
    assigned_agent_id: "u2", assigned_agent_name: "Jishank", ...patch };
}

function route() {
  get.mockImplementation((url: string, cfg?: { params?: Record<string, unknown> }) => {
    if (url === "/pipeline-stages") return Promise.resolve({ data: STAGES });
    if (url === "/leads/needs-action") return Promise.resolve({ data: { buckets: [{ key: "call", total: 2, leads: [lead("1"), lead("2", { display_name: "Suleman", identity_signals: [], assigned_agent_id: null, assigned_agent_name: null, stage_key: "general_enquiry", property_interest: [], check_in: null, ai_summary: "Wants a weekend near Bengaluru" })] }] } });
    if (url === "/leads" && cfg?.params?.page_size === 1) return Promise.resolve({ data: { total: 0, page: 1, page_size: 1, leads: [], stages: { general_enquiry: { count: 19 }, active: { count: 8 }, lost: { count: 3 } } } });
    if (url === "/leads") return Promise.resolve({ data: { total: 1, page: 1, page_size: 30, stages: {}, leads: [lead("9", { display_name: "Vishal", property_interest: ["Mysuru"] })] } });
    if (url === "/users/lite") return Promise.resolve({ data: [{ id: "u1", name: "Asha" }] });
    return Promise.resolve({ data: [] });
  });
}

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><PhoneLeads /></QueryClientProvider>);
}

beforeEach(() => { cleanup(); get.mockReset(); post.mockReset(); patch.mockReset(); route(); });

describe("Phone Leads", () => {
  it("opens on Needs action with stage chips and their counts, and compact rows with the one-line AI note", async () => {
    renderIt();
    expect(await screen.findByText("Monika · Goa, 26 Nov")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Needs action/ }).getAttribute("aria-pressed")).toBe("true");
    expect(await screen.findByRole("button", { name: /Active\s*8/ })).toBeTruthy();
    expect(screen.getByText(/Wants a weekend near Bengaluru/)).toBeTruthy();
    expect(screen.getByText("unassigned")).toBeTruthy();
    expect(screen.getByRole("button", { name: "New lead" })).toBeTruthy();
  });

  it("calls a lead with a phone and offers Assign for one without", async () => {
    post.mockResolvedValue({ data: {} });
    renderIt();
    await userEvent.click(await screen.findByRole("button", { name: "Call Monika" }));
    expect(post).toHaveBeenCalledWith("/calls/click-to-call", { inquiry_id: "1" });
    expect(screen.getByRole("button", { name: "Assign Suleman" })).toBeTruthy();
  });

  it("switches to a stage and searches what is loaded", async () => {
    renderIt();
    await userEvent.click(await screen.findByRole("button", { name: /Active\s*8/ }));
    expect(await screen.findByText("Vishal · Mysuru, 26 Nov")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/leads", { params: { page: 1, page_size: 30, stage: "active" } });
    await userEvent.type(screen.getByRole("textbox", { name: "Search leads" }), "goa");
    expect(await screen.findByText("No leads match")).toBeTruthy();
  });

  it("opens a row's sheet with the AI note, and Move stage uses the audited lead sheet", async () => {
    patch.mockResolvedValue({ data: {} });
    renderIt();
    await userEvent.click(await screen.findByRole("button", { name: "Monika, open details" }));
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(screen.getByText("AI note")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Move stage/ }));
    await userEvent.click(await screen.findByRole("radio", { name: /Lost/ }));
    expect(await screen.findByText("Mark as lost")).toBeTruthy();
    expect(patch).not.toHaveBeenCalled();
  });

  it("says when the list could not load", async () => {
    get.mockImplementation((url: string) => url === "/leads/needs-action" ? Promise.reject(new Error("down")) : Promise.resolve({ data: url === "/pipeline-stages" ? STAGES : { stages: {}, leads: [] } }));
    renderIt();
    expect(await screen.findByText("Couldn't load the leads")).toBeTruthy();
  });
});

describe("lead row helpers", () => {
  it("formats trip, wait and search", () => {
    const l = lead("1") as never;
    expect(tripText(l)).toBe("Goa, 26 Nov");
    expect(matches(l, "goa")).toBe(true);
    expect(matches(l, "kerala")).toBe(false);
    expect(waitedText(2 * 86400)).toBe(" 2d");
    expect(waitedText(null)).toBe("");
  });
});
