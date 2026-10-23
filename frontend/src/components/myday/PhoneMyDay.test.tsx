import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
const sess = vi.hoisted(() => ({ role: "owner" }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { name: "Asha Rao", role: sess.role } }, status: "authenticated" }) }));
const nav = vi.hoisted(() => ({ search: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => nav.search, usePathname: () => "/dashboard/my-day" }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/components/consults/ConsultsPanel", () => ({ ConsultsPanel: () => null }));

import { PhoneMyDay } from "./PhoneMyDay";

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
function item(patch: Record<string, unknown>) {
  return { kind: "new_lead", title: "Lead", detail: "Shared their number", action: "Call", href: "/dashboard/leads/i1", inquiry_id: "i1",
    guest_id: "g1", guest_phone: "+919800000001", owner_id: null, owner_name: null, channels: ["whatsapp"], since: ago(5), overdue: false,
    severity: "fresh", attempts: 0, facts: [], has_draft: false, lane: "now", ...patch };
}
const ITEMS = [
  item({ title: "Ravi", kind: "callback", action: "Call back", inquiry_id: null, guest_id: "g2", detail: "Missed call, not returned", severity: "urgent", since: ago(2 * 1440), facts: ["3-9 Jan"] }),
  item({ title: "Neha", guest_id: "g3", severity: "fresh", since: ago(20) }),
  item({ title: "Priya", kind: "reply", guest_id: "g4", lane: "today", href: "/dashboard/inbox?c=c1", detail: "“Dates for Hampi?”", has_draft: true, owner_id: "u1" }),
];
const queue = (items = ITEMS) => ({ counts: { consult: 0, callback: 1, new_lead: 1, reply: 1, no_reply: 0, followup: 0, clash: 0 }, people: items.length,
  people_waiting: items.length, items, scope: "team" });

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><PhoneMyDay /></QueryClientProvider>);
}

beforeEach(() => {
  cleanup(); get.mockReset(); post.mockReset(); nav.search = new URLSearchParams(); sess.role = "owner";
  get.mockImplementation((url: string) => url === "/work-queue/counts" ? Promise.resolve({ data: { people: 2, people_waiting: 2 } }) : Promise.resolve({ data: queue() }));
});

describe("Phone My day", () => {
  it("shows Mine / Team with counts, the kind chips and the lanes with who, why and how late", async () => {
    renderIt();
    expect(await screen.findByText("Ravi · 3-9 Jan")).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Team/ }).getAttribute("aria-selected")).toBe("true");
    expect(within(screen.getByRole("tab", { name: /Mine/ })).getByText("2")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Call backs/ })).toBeTruthy();
    expect(screen.getByText("Call now")).toBeTruthy();
    expect(screen.getByText("Reply or follow up today")).toBeTruthy();
    expect(screen.getByText("2d late").className).toContain("danger");
    expect(screen.getByText("AI reply ready")).toBeTruthy();
    expect(screen.getByText("unassigned")).toBeTruthy();
  });

  it("calls a missed caller back through click-to-call and a reply row links to the chat", async () => {
    post.mockResolvedValue({ data: {} });
    renderIt();
    await userEvent.click(await screen.findByRole("button", { name: "Call back Ravi" }));
    expect(post).toHaveBeenCalledWith("/calls/click-to-call", { guest_number: "+919800000001" });
    await userEvent.click(screen.getByRole("button", { name: "Call Neha" }));
    expect(post).toHaveBeenLastCalledWith("/calls/click-to-call", { inquiry_id: "i1" });
    expect(screen.getByRole("link", { name: "Reply to Priya" }).getAttribute("href")).toBe("/dashboard/inbox?c=c1");
  });

  it("filters by chip and opens the rest of the kinds from Filters", async () => {
    renderIt();
    await screen.findByText("Neha");
    await userEvent.click(screen.getByRole("button", { name: /Replies/ }));
    expect(screen.queryByText("Neha")).toBeNull();
    expect(screen.getByText("Priya")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    expect(await screen.findByText("Not replying to us")).toBeTruthy();
  });

  it("agents get no Mine/Team switch, and an empty queue says so", async () => {
    sess.role = "concierge";
    get.mockResolvedValue({ data: queue([]) });
    renderIt();
    expect(await screen.findByText("All caught up")).toBeTruthy();
    expect(screen.queryByRole("tab", { name: /Team/ })).toBeNull();
  });

  it("says when the list could not load", async () => {
    get.mockRejectedValue(new Error("down"));
    renderIt();
    expect(await screen.findByText("Couldn't load your list")).toBeTruthy();
  });
});
