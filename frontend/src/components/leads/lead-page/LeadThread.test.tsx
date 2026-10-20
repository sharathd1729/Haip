import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { LeadThread } from "./LeadThread";
import type { FeedItem } from "./types";

const NOW = new Date("2026-10-19T07:40:00Z");
const items: FeedItem[] = [
  { id: "booking-1", kind: "booking", at: "2026-02-14T06:30:00Z", booking_id: "b1", label: "Ratha 2", status: "checked_out", check_in: "2026-02-14", check_out: "2026-02-15", guests: 4, amount: 42000 },
  { id: "call-1", kind: "call", at: "2026-10-17T13:12:00Z", call_id: "c1", direction: "inbound", answered: true, duration_seconds: 252, summary: "Wants Ratha for 8 friends.", has_recording: true, has_transcript: true },
  { id: "stage-1", kind: "stage", at: "2026-10-17T13:17:00Z", from_label: "General Enquiry", to_label: "Active", by_name: "Jishanth" },
  { id: "msg-1", kind: "message", at: "2026-10-17T13:19:00Z", channel: "whatsapp", direction: "outbound", text: "Namaskara Sharath", sender_name: "Jishanth", delivery: "read" },
  { id: "msg-2", kind: "message", at: "2026-10-17T13:35:00Z", channel: "whatsapp", direction: "inbound", text: "Send the price for 8" },
  { id: "quote-1", kind: "quote", at: "2026-10-17T13:50:00Z", amount: 65000, shared_via: "sent", status: "issued", label: "Kabini overnight", valid_until_text: "Tue, 20 Oct" },
  { id: "call-2", kind: "call", at: "2026-10-18T12:40:00Z", call_id: "c2", direction: "outbound", answered: false, duration_seconds: 38 },
  { id: "task-1", kind: "task", at: "2026-10-18T13:00:00Z", text: "Call about the counter-offer", status: "open", by_name: "Autopilot" },
  { id: "merge-1", kind: "merge", at: "2026-10-19T04:10:00Z", text: "Another record of this person was joined to this lead", by_name: "Jishanth" },
];

function renderThread(list = items) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>
    <LeadThread items={list} inquiryId="i1" canSend canOpenBookings capped={false} messagesRestricted={false} now={NOW} />
  </QueryClientProvider>);
}

afterEach(cleanup);

describe("LeadThread", () => {
  it("renders messages, calls, quotes, bookings, stage changes, tasks and merges in the order they happened", () => {
    renderThread();
    const conversation = screen.getByRole("list", { name: "Conversation" });
    const order = Array.from(conversation.querySelectorAll("[data-testid^='thread-']")).map(el => el.getAttribute("data-testid"));
    expect(order).toEqual(["thread-booking", "thread-call", "thread-stage", "thread-message", "thread-message", "thread-quote", "thread-call", "thread-task", "thread-merge"]);
    // day separators between days
    expect(within(conversation).getByText("Today · Mon 19 Oct")).toBeTruthy();
    expect(within(conversation).getByText("Yesterday · Sun 18 Oct")).toBeTruthy();
    // the call card carries duration, summary, recording and transcript; the missed one says so
    expect(screen.getByText("Incoming call · 4 min 12 s")).toBeTruthy();
    expect(screen.getByText("Wants Ratha for 8 friends.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Play recording/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Transcript" }).getAttribute("href")).toBe("/dashboard/calls/c1");
    expect(screen.getByText("Outgoing call · not answered")).toBeTruthy();
    expect(screen.getByText("₹65,000")).toBeTruthy();
    expect(screen.getByText(/Stage: General Enquiry → Active/)).toBeTruthy();
  });

  it("filters to one kind", async () => {
    renderThread();
    await userEvent.click(screen.getByRole("button", { name: /^Calls/ }));
    expect(screen.getAllByTestId("thread-call")).toHaveLength(2);
    expect(screen.queryByTestId("thread-message")).toBeNull();
  });

  it("says so when there is nothing yet", () => {
    renderThread([]);
    expect(screen.getByText("Nothing here yet")).toBeTruthy();
  });
});
