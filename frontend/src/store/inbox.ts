/**
 * Inbox store — tracks unread counts, active conversation, and realtime events.
 */
import { create } from "zustand";

export interface ConversationSummary {
  id: string;
  guest_name: string;
  guest_phone: string;
  channel: "whatsapp" | "instagram" | "web" | "voice" | "sms";
  last_message: string;
  last_message_at: string;
  unread_count: number;
  has_ai_draft: boolean;
  status: "open" | "resolved" | "snoozed";
  ad_title?: string | null;  // T0.5: set when this conversation originated from a Click-to-Instagram ad

  // HAIP Inbox UI-fidelity pass, ticket 2: lead owner/stage/score/SLA,
  // batch-fetched by list_conversations from data that was already joined
  // in memory but never serialized before.
  assigned_to?: string | null;
  assigned_owner_name?: string | null;
  stage_key?: string | null;
  stage_label?: string | null;
  profile_completeness_pct?: number | null;
  is_waiting_reply?: boolean;
  sla_status?: "on_time" | "warning" | "breached" | null;
  // Phone-decline alert plan: an open "Guest declined phone number" Task
  // exists for this conversation.
  has_phone_decline_alert?: boolean;
  // Inbox redesign: every channel this guest has talked to us on, drawn as
  // icons under the avatar (e.g. ["instagram", "call"]).
  guest_channels?: GuestChannel[];
  // When the guest's unanswered message arrived ("Waiting 12m").
  waiting_since?: string | null;
  // False when an agent paused the AI for this conversation.
  ai_enabled?: boolean;
}

export type GuestChannel = "instagram" | "whatsapp" | "call";

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
  setPhoneDeclineAlert: (conversationId: string, hasAlert: boolean) => void;
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

  setPhoneDeclineAlert: (conversationId, hasAlert) => {
    const updated = get().conversations.map(c =>
      c.id === conversationId ? { ...c, has_phone_decline_alert: hasAlert } : c
    );
    set({ conversations: updated });
  },
}));
