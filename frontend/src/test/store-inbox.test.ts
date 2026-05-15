import { describe, it, expect, beforeEach } from "vitest";
import { useInboxStore } from "@/store/inbox";
import type { ConversationSummary } from "@/store/inbox";

const makeConv = (id: string, unread = 1): ConversationSummary => ({
  id,
  guest_name: `Guest ${id}`,
  guest_phone: "+918000000000",
  channel: "whatsapp",
  last_message: "Hello",
  last_message_at: new Date().toISOString(),
  unread_count: unread,
  has_ai_draft: false,
  status: "open",
});

describe("useInboxStore", () => {
  beforeEach(() => {
    useInboxStore.setState({ conversations: [], activeConversationId: null, totalUnread: 0 });
  });

  it("setConversations computes totalUnread", () => {
    const convs = [makeConv("a", 3), makeConv("b", 2)];
    useInboxStore.getState().setConversations(convs);
    expect(useInboxStore.getState().totalUnread).toBe(5);
  });

  it("upsertConversation inserts new conv at top", () => {
    useInboxStore.getState().setConversations([makeConv("existing")]);
    useInboxStore.getState().upsertConversation(makeConv("new", 2));
    const { conversations, totalUnread } = useInboxStore.getState();
    expect(conversations[0].id).toBe("new");
    expect(totalUnread).toBe(3);
  });

  it("upsertConversation updates existing conv in place", () => {
    useInboxStore.getState().setConversations([makeConv("c", 1)]);
    useInboxStore.getState().upsertConversation({ ...makeConv("c", 5), last_message: "Updated" });
    const { conversations, totalUnread } = useInboxStore.getState();
    expect(conversations.length).toBe(1);
    expect(conversations[0].unread_count).toBe(5);
    expect(conversations[0].last_message).toBe("Updated");
    expect(totalUnread).toBe(5);
  });

  it("markRead zeros unread for conversation", () => {
    useInboxStore.getState().setConversations([makeConv("d", 4), makeConv("e", 2)]);
    useInboxStore.getState().markRead("d");
    const { totalUnread } = useInboxStore.getState();
    expect(totalUnread).toBe(2);
  });

  it("setAiDraft toggles has_ai_draft", () => {
    useInboxStore.getState().setConversations([makeConv("f")]);
    useInboxStore.getState().setAiDraft("f", true);
    expect(useInboxStore.getState().conversations[0].has_ai_draft).toBe(true);
    useInboxStore.getState().setAiDraft("f", false);
    expect(useInboxStore.getState().conversations[0].has_ai_draft).toBe(false);
  });
});
