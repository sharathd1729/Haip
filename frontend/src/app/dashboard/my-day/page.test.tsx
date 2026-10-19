import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { name: "Asha Rao", role: "concierge" } }, status: "authenticated" }) }));
const nav = vi.hoisted(() => ({ search: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => nav.search }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import MyDayPage from "./page";

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

function item(patch: Record<string, unknown>) {
  return {
    kind: "new_lead", title: "Lead", detail: "Shared their number", action: "Call", href: "/dashboard/leads/i1",
    inquiry_id: "i1", guest_id: "g1", guest_phone: "+919800000001", owner_id: null, owner_name: null,
    channels: ["whatsapp"], since: ago(5), overdue: false, severity: "fresh", attempts: 0, facts: [], has_draft: false,
    ...patch,
  };
}

function queue(items: ReturnType<typeof item>[]) {
  const sev = { fresh: 0, late: 0, urgent: 0, critical: 0, stale: 0 } as Record<string, number>;
  items.forEach(i => { sev[i.severity as string] += 1; });
  const counts = { new_lead: 0, callback: 0, reply: 0, no_reply: 0, followup: 0, clash: 0 } as Record<string, number>;
  items.forEach(i => { counts[i.kind as string] += 1; });
  return { counts, oldest: { new_lead: null, callback: null, reply: null, followup: null }, severity: sev, total: items.length, people: items.length, unowned: items.filter(i => !i.owner_id).length, items, scope: "team" };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MyDayPage /></QueryClientProvider>);
}

beforeEach(() => { cleanup(); get.mockReset(); post.mockReset(); nav.search = new URLSearchParams(); });

describe("My day", () => {
  it("puts people past their target time first, new arrivals next, and hides the cold ones until asked", async () => {
    get.mockResolvedValue({ data: queue([
      item({ title: "Priya Nair", severity: "critical", since: ago(600), detail: "“Is the caravan free this weekend?”", facts: ["12–14 Dec", "2 adults"] }),
      item({ title: "Karan", severity: "fresh", since: ago(3), guest_id: "g2", inquiry_id: "i2" }),
      item({ title: "Old Lead", severity: "stale", since: ago(60 * 24 * 5), guest_id: "g3", inquiry_id: "i3" }),
    ]) });
    renderPage();

    expect(await screen.findByText("Priya Nair")).toBeTruthy();
    expect(screen.getByText(/3 people are waiting/)).toBeTruthy();
    expect(screen.getByText(/1 past their target time/)).toBeTruthy();
    expect(screen.getByText("Past their target time")).toBeTruthy();
    expect(screen.getByText("Just arrived")).toBeTruthy();
    expect(screen.getByText("Very overdue")).toBeTruthy();
    expect(screen.getByText("12–14 Dec")).toBeTruthy();
    expect(screen.getAllByText(/Nobody owns this yet/).length).toBeGreaterThan(0);
    // The cold lead is behind a toggle, not in the way.
    expect(screen.queryByText("Old Lead")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Gone cold \(1\)/ }));
    expect(screen.getByText("Old Lead")).toBeTruthy();
  });

  it("places the call from the row instead of opening a page", async () => {
    post.mockResolvedValue({ data: { status: "initiated" } });
    get.mockResolvedValue({ data: queue([item({ title: "Priya Nair", severity: "urgent", since: ago(150) })]) });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Call" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/calls/click-to-call", { inquiry_id: "i1" }));
  });

  it("calls a missed caller by their own number", async () => {
    post.mockResolvedValue({ data: {} });
    get.mockResolvedValue({ data: queue([item({ kind: "callback", title: "Unknown caller", action: "Call back", inquiry_id: null, severity: "late", since: ago(45), channels: ["call"] })]) });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Call back" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/calls/click-to-call", { guest_number: "+919800000001" }));
  });

  it("says so when nobody is waiting", async () => {
    get.mockResolvedValue({ data: queue([]) });
    renderPage();
    expect(await screen.findByText("All caught up")).toBeTruthy();
    expect(screen.getByText("Nobody is waiting. Nice.")).toBeTruthy();
  });

  it("offers a retry when the list cannot load", async () => {
    get.mockRejectedValue(new Error("offline"));
    renderPage();
    expect(await screen.findByText("Couldn't load your list")).toBeTruthy();
  });

  it("opens on exactly the people a dashboard card counted (?flag=) and lists the not-replying kind", async () => {
    nav.search = new URLSearchParams("flag=not_called");
    get.mockResolvedValue({ data: queue([
      item({ title: "Kavya", flags: ["not_called"] }),
      item({ title: "Rohan", guest_id: "g2", inquiry_id: "i2", flags: [] }),
      item({ title: "Pooja", kind: "no_reply", guest_id: "g3", inquiry_id: "i3", detail: "Our last message: “Shall I hold the dates?”", flags: ["not_called"] }),
    ]) });
    renderPage();
    expect(await screen.findByText("Kavya")).toBeTruthy();
    expect(screen.getByText("Pooja")).toBeTruthy();
    expect(screen.queryByText("Rohan")).toBeNull();
    expect(screen.getByText("Not called yet")).toBeTruthy();
    expect(screen.getByText("Not replying to us")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Show everyone" }));
    expect(await screen.findByText("Rohan")).toBeTruthy();
  });

  it("lists calendar clashes in their own section, with dates, vehicle and a link to that calendar day", async () => {
    get.mockResolvedValue({ data: queue([
      item({ title: "Karan", severity: "urgent", since: ago(150) }),
      item({ kind: "clash", title: "Double booking on Ratha 1: Google 2026-10-21 to 2026-10-22", action: "Open",
             detail: "Two bookings hold the same dates on this vehicle", inquiry_id: null, guest_id: null, guest_phone: null,
             channels: [], severity: "critical", facts: ["21 Oct – 22 Oct", "Ratha 1"],
             href: "/dashboard/portfolio/calendar?date=2026-10-21&property=p1" }),
    ]) });
    renderPage();
    const link = (await screen.findByText("Double booking on Ratha 1: Google 2026-10-21 to 2026-10-22")).closest("a");
    expect(screen.getByRole("heading", { name: /Calendar clashes/ })).toBeTruthy();
    expect(link?.getAttribute("href")).toBe("/dashboard/portfolio/calendar?date=2026-10-21&property=p1");
    expect(screen.getByText("21 Oct – 22 Oct")).toBeTruthy();
    expect(screen.getByText("Ratha 1")).toBeTruthy();
    // The clash is not one of the people past their target time.
    expect(screen.getByText("Past their target time").parentElement?.textContent).toContain("1");
    expect(screen.getByRole("button", { name: /Calendar clashes/ })).toBeTruthy();
  });
});
