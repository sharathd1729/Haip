import { create } from "zustand";

export interface NotificationItem {
  id: string;
  event: string;        // "message_received" | "ai_draft_ready" | "call_processed" | ...
  title: string;
  body: string;
  url: string;
  ts: number;           // Date.now()
  read: boolean;
}

interface NotificationsState {
  items: NotificationItem[];
  addEvent: (payload: Record<string, unknown>) => void;
  markAllRead: () => void;
  unreadCount: () => number;
}

function eventToNotification(payload: Record<string, unknown>): NotificationItem | null {
  const event = payload.event as string;
  const id = `${event}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

  switch (event) {
    case "message_received":
      return {
        id,
        event,
        title: "New message",
        body: payload.channel === "instagram" ? "New Instagram DM received" : "New WhatsApp message received",
        url: payload.conversation_id
          ? `/dashboard/inbox?id=${payload.conversation_id}`
          : "/dashboard/inbox",
        ts: Date.now(),
        read: false,
      };
    case "ai_draft_ready":
      return {
        id,
        event,
        title: "AI draft ready",
        body: "A reply has been drafted and is waiting for your approval.",
        url: payload.conversation_id
          ? `/dashboard/inbox?id=${payload.conversation_id}`
          : "/dashboard/inbox",
        ts: Date.now(),
        read: false,
      };
    case "call_processed":
    case "wrap_up_ready":
      return {
        id,
        event,
        title: "Call summary ready",
        body: "AI wrap-up and scoring is complete.",
        url: payload.call_id ? `/dashboard/calls/${payload.call_id}` : "/dashboard/calls",
        ts: Date.now(),
        read: false,
      };
    case "call_scored":
      return {
        id,
        event,
        title: "QA score updated",
        body: `Call scored${payload.score ? `: ${payload.score}/100` : ""}.`,
        url: payload.call_id ? `/dashboard/calls/${payload.call_id}` : "/dashboard/calls",
        ts: Date.now(),
        read: false,
      };
    default:
      return null;
  }
}

export const useNotificationsStore = create<NotificationsState>((set, get) => ({
  items: [],

  addEvent: (payload) => {
    const item = eventToNotification(payload);
    if (!item) return;
    set((state) => ({
      // Keep last 20 only
      items: [item, ...state.items].slice(0, 20),
    }));
  },

  markAllRead: () => {
    set((state) => ({
      items: state.items.map((n) => ({ ...n, read: true })),
    }));
  },

  unreadCount: () => get().items.filter((n) => !n.read).length,
}));
