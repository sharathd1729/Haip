/**
 * Inbox store — tracks unread counts, active conversation, and realtime events.
 */
import { create } from "zustand";

export interface ConversationSummary {
  id: string;
  guest_name: string;
  guest_phone: string;
  channel: "whatsapp" | "instagram" | "web" | "sms";
  last_message: string;
  last_message_at: string;
  unread_count: number;
  has_ai_draft: boolean;
  status: "open" | "resolved" | "snoozed";
}

interface InboxState {
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  totalUnread: number;

  // Actions
  setConversations: (list: ConversationSummary[]) => void;
  upsertConversation: (c: ConversationSummary) => void;
  setActiveConversation: (id: string | null) => void;
  markRead: (id: string) => void;
  setAiDraft: (conversationId: string, hasDraft: boolean) => void;
}

export const useInboxStore = create<InboxState>((set, get) => ({
  conversations: [],
  activeConversationId: null,
  totalUnread: 0,

  setConversations: (list) =>
    set({
      conversations: list,
      totalUnread: list.reduce((acc, c) => acc + (c.unread_count ?? 0), 0),
    }),

  upsertConversation: (c) => {
    const existing = get().conversations;
    const idx = existing.findIndex(e => e.id === c.id);
    const updated =
      idx >= 0
        ? existing.map((e, i) => (i === idx ? c : e))
        : [c, ...existing];
    set({
      conversations: updated,
      totalUnread: updated.reduce((acc, x) => acc + (x.unread_count ?? 0), 0),
    });
  },

  setActiveConversation: (id) => set({ activeConversationId: id }),

  markRead: (id) => {
    const updated = get().conversations.map(c =>
      c.id === id ? { ...c, unread_count: 0 } : c
    );
    set({
      conversations: updated,
      totalUnread: updated.reduce((acc, c) => acc + (c.unread_count ?? 0), 0),
    });
  },

  setAiDraft: (conversationId, hasDraft) => {
    const updated = get().conversations.map(c =>
      c.id === conversationId ? { ...c, has_ai_draft: hasDraft } : c
    );
    set({ conversations: updated });
  },
}));
