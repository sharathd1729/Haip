import type { RecommendedAction } from "@/components/ai/AIRecommendationCard";
import type { CallTimelineItem } from "@/components/inbox/CallLogCard";
import type { GuestChannel } from "@/store/inbox";

export interface Message {
  channel?: string;  // whatsapp | instagram | ... -- shown as an icon on guest messages
  id: string;
  text: string;
  direction: "inbound" | "outbound";
  status?: "pending" | "queued" | "sent" | "delivered" | "read" | "failed";
  delivery_state?: string;
  delivery_error?: string;
  timestamp: string;
  sender_name?: string;
  ai_drafted?: boolean;
  // null/undefined = still pending a decision, true = approved & sent,
  // false = rejected -- backend now serializes this (previously omitted
  // entirely), which is what isAiDraft below gates on.
  was_approved?: boolean | null;
  ai_confidence?: number;
  is_internal?: boolean;
  replied_to_message_id?: string;
  media_url?: string | null;   // T0.5
  media_type?: string | null;
  shared_post_url?: string | null;
  suggested_actions?: RecommendedAction[];  // ticket 4
}

export interface ConversationDetail {
  id: string;
  guest_id?: string;
  inquiry_id?: string | null;
  guest_name?: string;
  guest_phone: string;
  channel: string;
  source?: string | null;
  status: "open" | "resolved" | "snoozed";
  messages: Message[];
  last_inbound_at?: string | null;  // D9: WhatsApp 24h service window
  total_messages?: number;
  messages_capped?: boolean;  // true when older history exists beyond `messages`
  // Phone-decline alert plan: the open "Guest declined phone number" Task
  // for this conversation, if any (see backend concierge_draft.py's
  // _maybe_alert_phone_decline).
  phone_decline_task?: { id: string; title: string } | null;
  // Inbox redesign: every channel the guest has used, the per-conversation
  // AI switch, and the owner.
  guest_channels?: GuestChannel[];
  ai_enabled?: boolean;
  assigned_to?: string | null;
}

// HAIP Inbox prototype-wiring plan, ticket 2/5: the call side of the merged
// timeline. Messages keep coming from ConversationDetail/olderMessages
// (already paginated, tested) -- only calls are pulled in from the new
// timeline endpoint and interleaved by timestamp, to avoid disturbing that
// working pagination state machine.
export interface TimelineCallItem {
  type: "call";
  occurred_at: string;
  call: CallTimelineItem;
}
export interface TimelineMessageItem {
  type: "message";
  occurred_at: string;
}
export type TimelineItem = TimelineCallItem | TimelineMessageItem;

/** The slice of a TanStack mutation the thread components use. */
export interface Mut {
  mutate: (...args: any[]) => void;
  isPending: boolean;
  variables?: any;
}

// D9: compute seconds remaining in 24h WhatsApp service window
export function getWindowSecondsLeft(last_inbound_at?: string | null): number {
  if (!last_inbound_at) return 0;
  const since = (Date.now() - new Date(last_inbound_at).getTime()) / 1000;
  return Math.max(0, 86400 - since);
}

export function formatWindowCountdown(secs: number): string {
  if (secs <= 0) return "Expired";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (h > 0) return `${h}h ${m}m left`;
  return `${m}m left`;
}

// HAIP Inbox full-parity pass, ticket 5: same option sets MessageBubble.tsx
// uses for the stored-draft rewrite pickers -- duplicated here (not
// exported there) since this is the composer's own free-text version.
export const COMPOSER_REWRITE_LANGUAGES = ["Hindi", "Kannada", "Tamil", "Telugu", "Malayalam"];
export const COMPOSER_REWRITE_TONES = ["warm", "formal", "brief", "persuasive"] as const;

export const CHANNEL_FILTERS = [
  { value: "",          label: "All" },
  { value: "whatsapp",  label: "WhatsApp" },
  { value: "instagram", label: "Instagram" },
  { value: "voice",     label: "Call" },
  { value: "webchat",   label: "Web" },
  // Personal/Business-app WhatsApp bridge (whatsmeow, unofficial) -- kept
  // out of "WhatsApp"/"All" for now (product decision) since it shares
  // channel="whatsapp" with the official Cloud API but isn't the same
  // pipe; this tab is the only way to reach conversations tagged
  // source="personal_bridge" (backend excludes them from every other filter).
  { value: "personal_whatsapp", label: "Personal WhatsApp" },
];

// W4: quick schedule options
export const SCHEDULE_OPTIONS = [
    { label: "In 1 hour",     getValue: () => new Date(Date.now() + 60 * 60 * 1000).toISOString() },
    { label: "Tomorrow 9am",  getValue: () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); return d.toISOString(); } },
    { label: "Tomorrow 6pm",  getValue: () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(18, 0, 0, 0); return d.toISOString(); } },
    { label: "Monday 9am",    getValue: () => { const d = new Date(); const day = d.getDay(); const diff = (8 - day) % 7 || 7; d.setDate(d.getDate() + diff); d.setHours(9, 0, 0, 0); return d.toISOString(); } },
  ];