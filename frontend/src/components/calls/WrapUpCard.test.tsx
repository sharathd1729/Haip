import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const push = vi.fn();
const role = vi.hoisted(() => ({ value: "reservations" }));
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), patch: (...a: unknown[]) => patch(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { role: role.value } } }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));

import { WrapUpCard, clock, factText, type WrapUpCall } from "./WrapUpCard";

// The workspace's own stages (never fixed names): this one calls its open stage "Follow up".
const STAGES = [
  { id: "s1", key: "follow_up", label: "Follow up", order: 1, color: "#888", is_default_entry: true, is_closed_won: false, is_closed_lost: false },
  { id: "s2", key: "sold", label: "Sold", order: 2, color: "#888", is_default_entry: false, is_closed_won: true, is_closed_lost: false },
];
const lead = { inquiry_id: "i1", guest_id: "g1", display_name: "Unknown caller", inquiry_stage: "new", stage_key: "follow_up",
  check_in: null, adults: 4, budget_estimate: null, trip: { route: null, special_requests: null } };
const call: WrapUpCall = {
  id: "c1", inquiry_id: "i1", guest_name: "Unknown caller", needs_wrap_up: true, wrap_up_notes: null, transcription_status: "done", ai_score_status: "done",
  ai_insights: { heard_name: "Priya", temperature: { value: "hot", reason: "Asked how to pay" }, from_call: [
    { field: "check_in", value: "2026-12-14", said_at: 12.4, quote: "Four of us, 14th to 16th December" },
    { field: "adults", value: 4, said_at: 12.4, quote: "Four of us, 14th to 16th December" },
    { field: "budget", value: 70000, said_at: 71, quote: "Budget around 70 thousand" },
  ] },
};

function wrap(c: WrapUpCall = call, onPlay = vi.fn()) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><WrapUpCard call={c} onPlay={onPlay} /></QueryClientProvider>);
  return onPlay;
}

beforeEach(() => {
  role.value = "reservations";
  get.mockReset(); post.mockReset(); patch.mockReset(); push.mockReset();
  get.mockImplementation((url: string) => Promise.resolve({ data: url === "/pipeline-stages" ? STAGES : lead }));
  post.mockResolvedValue({ data: {} }); patch.mockResolvedValue({ data: {} });
});
afterEach(cleanup);

describe("helpers", () => {
  it("formats what was said and when", () => {
    expect(factText("check_in", "2026-12-14")).toContain("14 Dec");
    expect(factText("budget", 70000)).toContain("70,000");
    expect(clock(71)).toBe("1:11");
  });
});

describe("After-call wrap-up", () => {
  it("leads with who, the workspace's own stage and the heat, and offers the name heard on the call", async () => {
    wrap();
    expect(await screen.findByRole("button", { name: "Stage: Follow up. Change" })).toBeTruthy();      // the client's stage name
    expect(screen.getByText("Hot")).toBeTruthy();
    expect(screen.getByText("To do")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Use this name" }));
    expect(patch).toHaveBeenCalledWith("/inquiries/i1", { guest_name: "Priya" });
  });

  it("lists what was heard with the moment it was said; a fact the lead already holds is not ticked", async () => {
    const onPlay = wrap();
    const checkIn = await screen.findByRole("checkbox", { name: "Save Check-in on the lead" }) as HTMLInputElement;
    await waitFor(() => expect(checkIn.checked).toBe(true));
    const adults = screen.getByRole("checkbox", { name: "Save Adults on the lead" }) as HTMLInputElement;
    expect(adults.checked).toBe(false);
    expect(adults.disabled).toBe(true);                                     // the lead already has 4 adults
    expect(screen.getByText("on the lead")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Play where this was said, at 1:11" }));
    expect(onPlay).toHaveBeenCalledWith(71);
  });

  it("saves only the ticked facts on the lead, then the note on the call", async () => {
    wrap();
    const budget = await screen.findByRole("checkbox", { name: "Save Budget on the lead" }) as HTMLInputElement;
    await waitFor(() => expect(budget.checked).toBe(true));
    await userEvent.click(budget);                                          // the agent does not trust this one
    await userEvent.type(screen.getByRole("textbox", { name: /Your note/ }), "Send quote today");
    await userEvent.click(screen.getByRole("button", { name: "Save 1 to lead" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/calls/c1/wrap-up", { notes: "Send quote today" }));
    expect(patch).toHaveBeenCalledWith("/inquiries/i1", { check_in: "2026-12-14" });
  });

  it("Save and book saves first, then opens the booking form for this lead", async () => {
    wrap();
    await userEvent.click(await screen.findByRole("button", { name: /Save and book/ }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard/bookings/new?inquiry=i1"));
    expect(post).toHaveBeenCalledWith("/calls/c1/wrap-up", { notes: "" });
  });

  it("says HAIP is still reading the call, and says so when nothing was heard", async () => {
    wrap({ ...call, ai_score_status: "processing", ai_insights: null });
    expect(await screen.findByText(/HAIP is reading the call/)).toBeTruthy();
    cleanup();
    wrap({ ...call, ai_insights: { from_call: [] } });
    expect(await screen.findByText(/No dates, guests or budget were heard/)).toBeTruthy();
  });

  it("a call with no lead keeps the note only; a role that cannot edit leads cannot tick or book", async () => {
    wrap({ ...call, inquiry_id: null });
    expect(await screen.findByText(/not linked to a lead/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Save and book/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save wrap-up" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/calls/c1/wrap-up", { notes: "" }));
    expect(patch).not.toHaveBeenCalled();
    cleanup();
    role.value = "foh";
    wrap();
    const checkIn = await screen.findByRole("checkbox", { name: "Save Check-in on the lead" }) as HTMLInputElement;
    expect(checkIn.disabled).toBe(true);
    expect(screen.queryByRole("button", { name: /Save and book/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Use this name" })).toBeNull();
  });
});
