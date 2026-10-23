import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PhoneInboxList, turnOf } from "./PhoneInboxList";
import type { ConversationSummary } from "@/store/inbox";

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
function conv(id: string, patch: Partial<ConversationSummary> = {}): ConversationSummary {
  return { id, guest_name: "Chandu", guest_phone: "+919800000001", channel: "whatsapp", last_message: "Talk to us", last_message_at: ago(30),
    unread_count: 0, has_ai_draft: false, status: "open", is_waiting_reply: false, ...patch };
}
const CONVS = [
  conv("c1", { is_waiting_reply: true, waiting_since: ago(90), unread_count: 2 }),
  conv("c2", { guest_name: "Shubham", has_ai_draft: true, last_message: "A multi-day trip to Mysore?" }),
  conv("c3", { guest_name: "Anita", last_message: "You: Sending the Coorg plan now" }),
];

function renderIt(over: Partial<Parameters<typeof PhoneInboxList>[0]> = {}) {
  const props = {
    conversations: CONVS, isLoading: false, view: "needs_reply" as const, onViewChange: vi.fn(), counts: { needs_reply: 6, unassigned: 1, mine: 2 },
    onSelect: vi.fn(), channelFilter: "", channelOptions: [{ value: "", label: "All" }, { value: "whatsapp", label: "WhatsApp" }], onChannelChange: vi.fn(), ...over,
  };
  render(<PhoneInboxList {...props} />);
  return props;
}

beforeEach(() => cleanup());

describe("Phone Inbox list", () => {
  it("shows whose turn it is, unread counts and marks AI drafts with a Review button that opens the thread (never approves)", async () => {
    const p = renderIt();
    expect(screen.getByText("our turn").className).toContain("danger");
    expect(screen.getByText("2 new")).toBeTruthy();
    expect(screen.getByText("replied")).toBeTruthy();
    expect(screen.getByText("AI draft ready to review")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Review the AI draft for Shubham" }));
    expect(p.onSelect).toHaveBeenCalledWith("c2");
    await userEvent.click(screen.getByRole("button", { name: "Anita, open chat" }));
    expect(p.onSelect).toHaveBeenLastCalledWith("c3");
  });

  it("Our turn uses the server's needs_reply view and count; AI drafts filters the loaded chats", async () => {
    const p = renderIt();
    expect(screen.getByRole("button", { name: /Our turn\s*6/ }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.click(screen.getByRole("button", { name: /AI drafts/ }));
    expect(p.onViewChange).toHaveBeenLastCalledWith("");
    expect(screen.queryByText("Anita")).toBeNull();
    expect(screen.getByText("Shubham")).toBeTruthy();
  });

  it("opens on Our turn when the inbox was showing everything", () => {
    const p = renderIt({ view: "" });
    expect(p.onViewChange).toHaveBeenCalledWith("needs_reply");
  });

  it("searches loaded chats and has loading and empty states", async () => {
    renderIt();
    await userEvent.type(screen.getByRole("textbox", { name: "Search chats" }), "zzz");
    expect(screen.getByText("No chats match")).toBeTruthy();
    cleanup();
    renderIt({ isLoading: true });
    expect(document.querySelector("[aria-busy=true]")).toBeTruthy();
  });

  it("turnOf reads the conversation's own flags", () => {
    expect(turnOf(conv("x", { has_ai_draft: true })).label).toBe("approve");
    expect(turnOf(conv("x", { is_waiting_reply: true, waiting_since: ago(5) }))).toEqual({ label: "our turn", tone: "warning" });
    expect(turnOf(conv("x", { status: "resolved" })).label).toBe("done");
  });
});
