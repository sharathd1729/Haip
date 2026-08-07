"use client";
import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import { useQuery, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Send, Sparkles, Loader2, BellOff, Search, X, StickyNote, Reply, ChevronDown, ChevronLeft, CalendarClock, Timer, AlertTriangle, LayoutTemplate, Phone, Languages, Wand2 } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { ConversationList } from "@/components/inbox/ConversationList";
import { MessageBubble } from "@/components/inbox/MessageBubble";
import { SavedReplyMenu } from "@/components/inbox/SavedReplyMenu";
import { AIDraftPanel } from "@/components/inbox/AIDraftPanel";
import { TypingDots } from "@/components/inbox/TypingDots";
import { ChannelIcon, channelLabel } from "@/components/inbox/ChannelIcon";
import { GuestPanel } from "@/components/inbox/GuestPanel";
import { PinnedInquiryBanner } from "@/components/inbox/PinnedInquiryBanner";
import { CallLogCard, type CallTimelineItem } from "@/components/inbox/CallLogCard";
import type { RecommendedAction } from "@/components/ai/AIRecommendationCard";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useInboxStore } from "@/store/inbox";
import { useAutoGrow } from "@/hooks/useAutoGrow";
import { useToast } from "@/components/ui/toast";
import { usePresence } from "@/hooks/usePresence";
// B5: only needed once the user opens the template picker (WhatsApp window
// re-open flow) -- keep it out of this route's initial chunk.
const TemplatePickerModal = dynamic(
  () => import("@/components/inbox/TemplatePickerModal").then(m => m.TemplatePickerModal),
  { ssr: false }
);

// ─── Types ────────────────────────────────────────────────────────────────────

interface Message {
  id: string;
  text: string;
  direction: "inbound" | "outbound";
  status?: "pending" | "queued" | "sent" | "delivered" | "read" | "failed";
  delivery_state?: string;
  delivery_error?: string;
  timestamp: string;
  sender_name?: string;
  ai_drafted?: boolean;
  ai_confidence?: number;
  is_internal?: boolean;
  replied_to_message_id?: string;
  media_url?: string | null;   // T0.5
  media_type?: string | null;
  shared_post_url?: string | null;
  suggested_actions?: RecommendedAction[];  // ticket 4
}

interface ConversationDetail {
  id: string;
  guest_id?: string;
  inquiry_id?: string | null;
  guest_name?: string;
  guest_phone: string;
  channel: string;
  status: "open" | "resolved" | "snoozed";
  messages: Message[];
  last_inbound_at?: string | null;  // D9: WhatsApp 24h service window
  total_messages?: number;
  messages_capped?: boolean;  // true when older history exists beyond `messages`
}

// HAIP Inbox prototype-wiring plan, ticket 2/5: the call side of the merged
// timeline. Messages keep coming from ConversationDetail/olderMessages
// (already paginated, tested) -- only calls are pulled in from the new
// timeline endpoint and interleaved by timestamp, to avoid disturbing that
// working pagination state machine.
interface TimelineCallItem {
  type: "call";
  occurred_at: string;
  call: CallTimelineItem;
}
interface TimelineMessageItem {
  type: "message";
  occurred_at: string;
}
type TimelineItem = TimelineCallItem | TimelineMessageItem;

// D9: compute seconds remaining in 24h WhatsApp service window
function getWindowSecondsLeft(last_inbound_at?: string | null): number {
  if (!last_inbound_at) return 0;
  const since = (Date.now() - new Date(last_inbound_at).getTime()) / 1000;
  return Math.max(0, 86400 - since);
}

function formatWindowCountdown(secs: number): string {
  if (secs <= 0) return "Expired";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (h > 0) return `${h}h ${m}m left`;
  return `${m}m left`;
}

// HAIP Inbox full-parity pass, ticket 5: same option sets MessageBubble.tsx
// uses for the stored-draft rewrite pickers -- duplicated here (not
// exported there) since this is the composer's own free-text version.
const COMPOSER_REWRITE_LANGUAGES = ["Hindi", "Kannada", "Tamil", "Telugu", "Malayalam"];
const COMPOSER_REWRITE_TONES = ["warm", "formal", "brief", "persuasive"] as const;

const CHANNEL_FILTERS = [
  { value: "",          label: "All" },
  { value: "whatsapp",  label: "WhatsApp" },
  { value: "instagram", label: "Instagram" },
  { value: "voice",     label: "Call" },
  { value: "web",       label: "Web" },
];

// ─── M1: Channel filter row with scroll-fade ──────────────────────────────────

function ChannelFilterRow({
  filters,
  value,
  onChange,
}: {
  filters: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [canScrollLeft, setCanScrollLeft] = useState(false);

  function updateFades() {
    const el = scrollRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 4);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  }

  useEffect(() => {
    updateFades();
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", updateFades, { passive: true });
    return () => el.removeEventListener("scroll", updateFades);
  }, []);

  return (
    <div className="relative">
      {/* Left fade */}
      {canScrollLeft && (
        <div className="pointer-events-none absolute left-0 top-0 bottom-0 w-6 z-10"
          style={{ background: "linear-gradient(to right, var(--haip-card), transparent)" }} />
      )}
      {canScrollRight && (
        <div className="pointer-events-none absolute right-0 top-0 bottom-0 w-8 z-10"
          style={{ background: "linear-gradient(to left, var(--haip-card), transparent)" }} />
      )}
      <div
        ref={scrollRef}
        className="flex gap-1 overflow-x-auto scrollbar-hide"
        style={{ WebkitOverflowScrolling: "touch" }}
      >
        {filters.map(f => (
          <button
            key={f.value}
            onClick={() => onChange(f.value)}
            className="flex-shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors duration-150 min-h-[36px] min-w-[40px]"
            style={value === f.value
              ? { background: "var(--primary)", color: "var(--primary-foreground)" }
              : { color: "var(--haip-fg-muted)" }}
          >
            {f.value && <ChannelIcon channel={f.value} className="w-3.5 h-3.5" />}
            {f.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function InboxPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { data: session } = useSession();
  const currentUserId = (session?.user as { id?: string } | undefined)?.id ?? null;
  const {
    conversations,
    activeConversationId,
    setConversations,
    setActiveConversation,
    markRead,
    setAiDraft,
  } = useInboxStore();

  // Mobile: single-panel navigation ("list" | "thread")
  const [mobileView, setMobileView] = useState<"list" | "thread">("list");

  const [channelFilter, setChannelFilter] = useState("");
  const [replyText, setReplyText] = useState("");
  const [aiTyping, setAiTyping] = useState(false);
  const [editingDraftId, setEditingDraftId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [emptyPulse, setEmptyPulse] = useState(false);
  const [showSavedReplies, setShowSavedReplies] = useState(false);
  const [savedReplyQuery, setSavedReplyQuery] = useState("");
  // W24: internal note mode
  const [isInternalNote, setIsInternalNote] = useState(false);
  // W5: reply-to
  const [replyToMsg, setReplyToMsg] = useState<Message | null>(null);
  // W14: snooze picker
  const [showSnooze, setShowSnooze] = useState(false);
  // W7: AI tone
  const [aiTone, setAiTone] = useState<"warm" | "formal" | "brief" | "persuasive">("warm");
  const [rejectedDrafts, setRejectedDrafts] = useState<string[]>([]);
  // W17: search
  const [showSearch, setShowSearch] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  // W4: scheduled send
  const [showSchedule, setShowSchedule] = useState(false);
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [scheduledFor, setScheduledFor] = useState<string | null>(null);
  // W25: @mention
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  // D9: 24h service window countdown tick
  const [windowTick, setWindowTick] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useAutoGrow(textareaRef, replyText, 6);

  const isEmpty = replyText.trim().length === 0;

  // D9: tick every 60s to refresh the countdown display
  useEffect(() => {
    const id = setInterval(() => setWindowTick(t => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  // CONVERSATION_PAGE_SIZE keeps each request bounded -- the list used to
  // fetch with no limit at all (server default 50, uncapped growth as the
  // conversation table grows), with no way to reach anything past the first
  // page. Cursor is `last_message_at` of the oldest conversation loaded so
  // far, matching how the list is already sorted server-side.
  const CONVERSATION_PAGE_SIZE = 50;
  const {
    data: conversationPages,
    isLoading: listLoading,
    fetchNextPage: fetchNextConversationPage,
    hasNextPage: hasMoreConversations,
    isFetchingNextPage: isLoadingMoreConversations,
  } = useInfiniteQuery({
    queryKey: ["conversations"],
    queryFn: ({ pageParam }: { pageParam?: string }) =>
      api.get("/conversations", { params: { limit: CONVERSATION_PAGE_SIZE, ...(pageParam ? { before: pageParam } : {}) } })
        .then(r => r.data as any[]),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.length === CONVERSATION_PAGE_SIZE
        ? lastPage[lastPage.length - 1]?.last_message_at
        : undefined,
    staleTime: 30_000,
  });

  // HOTFIX (production incident): .flat() on every render produced a new
  // array reference each time even when the underlying pages hadn't
  // changed, so the effect below never saw a stable dependency -- it fired
  // every render, called setConversations, which re-rendered this
  // component, which called .flat() again... "Maximum update depth
  // exceeded" (React error #185), infinite loop, whole Inbox page down in
  // prod. useMemo keyed on conversationPages (react-query's own stable
  // reference, unchanged unless the query result actually changed) fixes it.
  const conversationData = useMemo(
    () => conversationPages?.pages.flat(),
    [conversationPages]
  );

  // onSuccess was removed in TanStack Query v5 — use useEffect to sync store
  useEffect(() => {
    if (conversationData) setConversations(conversationData);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationData]);

  const { data: detail, isLoading: detailLoading } = useQuery<ConversationDetail>({
    queryKey: ["conversation", activeConversationId],
    queryFn: () => api.get(`/conversations/${activeConversationId}`).then(r => r.data),
    enabled: !!activeConversationId,
    staleTime: 30_000,
  });

  // HAIP Inbox full-parity pass, ticket 5: same lead-detail query
  // GuestPanel/ProfileCompletenessWidget/PinnedInquiryBanner already fetch
  // (identical queryKey, dedupes) -- just need profile_completeness_pct
  // here for the thread-header pill.
  const { data: threadLeadDetail } = useQuery<{ profile_completeness_pct?: number }>({
    queryKey: ["lead-detail", detail?.inquiry_id],
    queryFn: () => api.get(`/leads/${detail?.inquiry_id}`).then(r => r.data),
    enabled: !!detail?.inquiry_id,
    staleTime: 30_000,
  });

  // HAIP Inbox prototype-wiring plan, ticket 2: call side of the merged
  // timeline -- messages keep coming from `detail`/`olderMessages` above
  // (already paginated), only the call items are pulled from here and
  // interleaved by timestamp below.
  const { data: timeline } = useQuery<{ items: TimelineItem[] }>({
    queryKey: ["conversation-timeline", activeConversationId],
    queryFn: () => api.get(`/conversations/${activeConversationId}/timeline`).then(r => r.data),
    enabled: !!activeConversationId,
    staleTime: 30_000,
  });
  const callItems = (timeline?.items ?? []).filter(
    (i): i is TimelineCallItem => i.type === "call"
  );

  // HAIP Inbox prototype-wiring plan, ticket 3: real translate/tone-fix of
  // a pending draft, scoped to its own message id.
  const [rewritingMessageId, setRewritingMessageId] = useState<string | null>(null);
  const rewriteDraft = useMutation({
    mutationFn: ({ messageId, tone, targetLanguage }: { messageId: string; tone?: string; targetLanguage?: string }) =>
      api.post(`/conversations/${activeConversationId}/messages/${messageId}/rewrite`, {
        tone, target_language: targetLanguage,
      }),
    onMutate: ({ messageId }) => setRewritingMessageId(messageId),
    onSettled: () => setRewritingMessageId(null),
    onSuccess: () => {
      // Draft rewrite is async (Celery) -- refetch after a short delay
      // rather than immediately, same pattern as AI draft generation.
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] }), 1500);
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? "Rewrite failed";
      toast({ variant: "error", title: "Could not rewrite draft", description: msg });
    },
  });

  // HAIP Inbox full-parity pass, ticket 5: Translate/Tone-Fix on the
  // composer's free-typed text (not an existing stored draft the way
  // rewriteDraft above handles) -- kicks off composer_rewrite.delay, then
  // polls the short-lived job-result endpoint since there's no Message row
  // to refetch a conversation for.
  const [isComposerRewriting, setIsComposerRewriting] = useState(false);
  const [showComposerTonePicker, setShowComposerTonePicker] = useState(false);
  const [showComposerLangPicker, setShowComposerLangPicker] = useState(false);
  const composerRewrite = useMutation({
    mutationFn: async ({ tone, targetLanguage }: { tone?: string; targetLanguage?: string }) => {
      const { data } = await api.post(`/conversations/${activeConversationId}/composer/rewrite`, {
        text: replyText, tone, target_language: targetLanguage,
      });
      const jobId = data.job_id as string;
      for (let attempt = 0; attempt < 15; attempt++) {
        await new Promise(r => setTimeout(r, 700));
        const status = await api.get(`/conversations/${activeConversationId}/composer/rewrite/${jobId}`).then(r => r.data);
        if (status.status === "done") return status.rewritten_text as string;
        if (status.status === "failed") throw new Error("Rewrite failed");
      }
      throw new Error("Rewrite timed out");
    },
    onMutate: () => setIsComposerRewriting(true),
    onSettled: () => setIsComposerRewriting(false),
    onSuccess: (rewrittenText) => setReplyText(rewrittenText),
    onError: () => {
      toast({ variant: "error", title: "Could not rewrite message", description: "Please try again." });
    },
  });

  // "Load older messages" — get_conversation_detail's initial payload only
  // carries the most recent 50 (see backend B3 fix); older history is
  // reached via a separate cursor endpoint, not by widening that payload.
  // Kept as plain state rather than useInfiniteQuery since the first page
  // (conversation detail) and subsequent pages (GET /messages) come from
  // two different endpoints with different response shapes.
  const [olderMessages, setOlderMessages] = useState<Message[]>([]);
  const [hasMoreOlderMessages, setHasMoreOlderMessages] = useState(false);
  const [loadingOlderMessages, setLoadingOlderMessages] = useState(false);

  // Reset older-message state whenever the active conversation changes.
  useEffect(() => {
    setOlderMessages([]);
    setHasMoreOlderMessages(!!detail?.messages_capped);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConversationId, detail?.messages_capped]);

  const loadOlderMessages = useCallback(async () => {
    if (!activeConversationId || loadingOlderMessages) return;
    const oldest = (olderMessages[0] ?? detail?.messages[0])?.timestamp;
    if (!oldest) return;
    setLoadingOlderMessages(true);
    try {
      const res = await api.get(`/conversations/${activeConversationId}/messages`, {
        params: { before: oldest, limit: 50 },
      });
      setOlderMessages(prev => [...res.data.messages, ...prev]);
      setHasMoreOlderMessages(res.data.has_more);
    } finally {
      setLoadingOlderMessages(false);
    }
  }, [activeConversationId, loadingOlderMessages, olderMessages, detail?.messages]);

  // Mark as read when conversation detail loads
  useEffect(() => {
    if (detail && activeConversationId) markRead(activeConversationId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.id, activeConversationId]);

  // D9: derived service window state — only meaningful for WhatsApp
  // windowTick dependency ensures re-render every 60s to refresh countdown
  const isWhatsApp = detail?.channel === "whatsapp";
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const windowSecsLeft = isWhatsApp ? getWindowSecondsLeft(detail?.last_inbound_at) : Infinity;
  const windowOpen = windowSecsLeft > 0 || !isWhatsApp;
  // Block free-form send when window is closed and this is a WhatsApp thread (not internal note)
  const windowBlocked = isWhatsApp && !windowOpen && !isInternalNote;
  void windowTick; // consumed by re-render cycle to refresh countdown

  // HAIP Inbox UI-fidelity pass, ticket 1/5: a channel="voice" conversation
  // (call_ingest.py's fallback for a guest whose only touchpoint is a
  // phone call) has no chat send path -- no WhatsApp/Instagram dispatcher
  // exists for it. Show a clear disabled state instead of a composer that
  // would silently fail to send.
  const isVoiceOnly = detail?.channel === "voice";

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [detail?.messages]);

  // SSE is owned exclusively by DashboardSSEBridge (mounted once in the dashboard
  // layout) -- it already invalidates ["conversations"]/["conversation", id] and
  // calls setAiDraft for message_received/ai_draft_ready. A second useInboxStream
  // connection here opened a duplicate EventSource per inbox page mount, which
  // under reconnect churn exhausted the browser's connection pool
  // (net::ERR_INSUFFICIENT_RESOURCES) and starved every other request, including
  // the send-message call itself.

  const sendMutation = useMutation({
    mutationFn: ({ text, is_internal, replied_to_message_id, scheduled_for }: { text: string; is_internal?: boolean; replied_to_message_id?: string; scheduled_for?: string | null }) =>
      api.post(`/conversations/${activeConversationId}/messages`, {
        body: text,
        direction: "outbound",
        is_internal: is_internal ?? false,
        replied_to_message_id: replied_to_message_id ?? null,
        scheduled_for: scheduled_for ?? null,
      }),
    // Optimistic insert — show the message immediately instead of waiting on
    // the full send round trip (Meta API call + DB write can take several
    // seconds). Reconciled with the real row once the query is invalidated.
    onMutate: async ({ text, is_internal, replied_to_message_id }) => {
      const key = ["conversation", activeConversationId];
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<ConversationDetail>(key);
      const optimisticMessage: Message = {
        id: `optimistic-${Date.now()}`,
        text,
        direction: "outbound",
        status: "queued",
        timestamp: new Date().toISOString(),
        is_internal: is_internal ?? false,
        replied_to_message_id: replied_to_message_id ?? undefined,
      };
      queryClient.setQueryData<ConversationDetail>(key, (old) =>
        old ? { ...old, messages: [...old.messages, optimisticMessage] } : old
      );
      setReplyText("");
      setIsInternalNote(false);
      setReplyToMsg(null);
      setScheduledFor(null);
      setShowSchedule(false);
      return { previous, key };
    },
    onSuccess: (_data, _vars, context) => {
      queryClient.invalidateQueries({ queryKey: context?.key ?? ["conversation", activeConversationId] });
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(context.key, context.previous);
      toast({ variant: "error", title: "Send failed" });
    },
  });

  const retryMutation = useMutation({
    mutationFn: ({ conversationId, messageId }: { conversationId: string; messageId: string }) =>
      api.post(`/conversations/${conversationId}/messages/${messageId}/retry`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] });
      toast({ variant: "success", title: "Message re-queued" });
    },
    onError: () => toast({ variant: "error", title: "Retry failed" }),
  });

  // Mcube-disconnect + outbound-calling pass: agent clicks a guest's number,
  // Vobiz (or whichever IVR is active) rings the agent's registered mobile
  // first, then bridges to the guest -- no audio in the browser.
  const clickToCallMutation = useMutation({
    mutationFn: (guest_number: string) => api.post("/calls/click-to-call", { guest_number }),
    onSuccess: () => toast({ variant: "success", title: "Calling…", description: "Your phone will ring shortly." }),
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Could not start call", description: typeof msg === "string" ? msg : "Please try again." });
    },
  });

  // W14: snooze
  const snoozeMutation = useMutation({
    mutationFn: (snooze_until: string | null) =>
      api.post(`/conversations/${activeConversationId}/snooze`, { snooze_until }),
    onSuccess: (_, snooze_until) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setShowSnooze(false);
      toast({ variant: "success", title: snooze_until ? "Conversation snoozed" : "Snooze cleared" });
    },
  });

  // W17: search
  const { data: searchResults = [], isLoading: searchLoading } = useQuery({
    queryKey: ["search", searchQ],
    queryFn: () => api.get(`/conversations/search?q=${encodeURIComponent(searchQ)}`).then(r => r.data),
    enabled: showSearch && searchQ.trim().length >= 2,
    staleTime: 10_000,
  });

  const draftMutation = useMutation({
    mutationFn: () =>
      api.post(`/conversations/${activeConversationId}/messages/ai-draft`, { tone: aiTone }),
    onMutate: () => setAiTyping(true),
    onSettled: () => setAiTyping(false),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] }),
    onError: () => toast({ variant: "error", title: "AI draft failed" }),
  });

  const approveMutation = useMutation({
    mutationFn: (msgId: string) =>
      api.post(`/conversations/${activeConversationId}/messages/${msgId}/approve`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] });
      if (activeConversationId) setAiDraft(activeConversationId, false);
      toast({ variant: "success", title: "Draft approved & sent" });
    },
    onError: () => toast({ variant: "error", title: "Approval failed" }),
  });

  // W1: pulse animation on empty send attempt
  const triggerEmptyPulse = useCallback(() => {
    setEmptyPulse(true);
    setTimeout(() => setEmptyPulse(false), 800);
  }, []);

  // Stable message action handlers — useCallback prevents MessageBubble React.memo invalidation
  const handleApprove = useCallback((id: string) => approveMutation.mutate(id), [approveMutation]);
  const handleRetry = useCallback((id: string) => {
    if (!activeConversationId) return;
    retryMutation.mutate({ conversationId: activeConversationId, messageId: id });
  }, [retryMutation, activeConversationId]);
  const handleReject = useCallback((id: string) => {
    if (!activeConversationId || !detail) return;
    const draftMsg = detail.messages.find(m => m.id === id);
    if (draftMsg) setRejectedDrafts(p => [...p.slice(-2), draftMsg.text]);
    api.post(`/conversations/${activeConversationId}/messages/${id}/reject`, {}).catch(() => {});
    queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] });
  }, [activeConversationId, detail, queryClient]);

  const handleSend = (overrideScheduled?: string | null) => {
    if (isEmpty) { triggerEmptyPulse(); return; }
    if (!activeConversationId) return;
    // D9: block free-form send when service window is closed (except internal notes)
    if (windowBlocked) return;
    sendMutation.mutate({
      text: replyText.trim(),
      is_internal: isInternalNote,
      replied_to_message_id: replyToMsg?.id,
      scheduled_for: overrideScheduled !== undefined ? overrideScheduled : scheduledFor,
    });
  };

  // W4: quick schedule options
  const SCHEDULE_OPTIONS = [
    { label: "In 1 hour",     getValue: () => new Date(Date.now() + 60 * 60 * 1000).toISOString() },
    { label: "Tomorrow 9am",  getValue: () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); return d.toISOString(); } },
    { label: "Tomorrow 6pm",  getValue: () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(18, 0, 0, 0); return d.toISOString(); } },
    { label: "Monday 9am",    getValue: () => { const d = new Date(); const day = d.getDay(); const diff = (8 - day) % 7 || 7; d.setDate(d.getDate() + diff); d.setHours(9, 0, 0, 0); return d.toISOString(); } },
  ];

  // W3: "/" in composer opens saved-reply menu; /note triggers internal mode (W24)
  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setReplyText(val);

    // W24: /note command
    if (val === "/note" || val === "/note ") {
      setIsInternalNote(true);
      setReplyText("");
      setShowSavedReplies(false);
      return;
    }

    if (val === "/" || (val.startsWith("/") && !isInternalNote)) {
      setShowSavedReplies(true);
      setSavedReplyQuery(val.slice(1));
    } else {
      setShowSavedReplies(false);
    }

    // W25: @mention detection — find last "@word" in the text
    const atMatch = val.match(/@(\w*)$/);
    if (atMatch) {
      setMentionQuery(atMatch[1]);
    } else {
      setMentionQuery(null);
    }
  };

  const exitInternalNote = () => {
    setIsInternalNote(false);
    setReplyText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Esc: exit internal note mode (W24) or clear reply-to (W5)
    if (e.key === "Escape") {
      if (mentionQuery !== null) { setMentionQuery(null); return; }
      if (isInternalNote) { exitInternalNote(); return; }
      if (replyToMsg) { setReplyToMsg(null); return; }
    }
    // Cmd+Enter / Ctrl+Enter also sends (X2)
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleSend(); return; }
    // Plain Enter sends; Shift+Enter inserts newline (W2)
    if (e.key === "Enter" && !e.shiftKey) {
      if (showSavedReplies) return; // let SavedReplyMenu handle Enter
      if (mentionQuery !== null) return; // let mention menu handle Enter
      e.preventDefault();
      handleSend();
    }
  };

  // W25: insert mention
  const insertMention = (user: any) => {
    // Replace trailing @... with @name
    setReplyText(prev => prev.replace(/@\w*$/, `@${user.name.split(" ")[0]} `));
    setMentionQuery(null);
    textareaRef.current?.focus();
  };

  // W15: saved views
  const { data: savedViews = [] } = useQuery({
    queryKey: ["saved-views", "inbox"],
    queryFn: () => api.get("/saved-views?scope=inbox").then(r => r.data),
  });
  const [activeView, setActiveView] = useState<string | null>(null);

  // W18: presence — heartbeat + poll
  const { onlineUsers } = usePresence(true);

  // W25: @mention — fetch team members
  const { data: teamMembers = [] } = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get("/users").then(r => r.data),
    staleTime: 60_000,
  } as any);

  const mentionMatches = mentionQuery !== null
    ? (teamMembers as any[]).filter((u: any) =>
        u.name?.toLowerCase().includes(mentionQuery.toLowerCase()) ||
        u.email?.toLowerCase().includes(mentionQuery.toLowerCase())
      ).slice(0, 5)
    : [];

  // Three-pane inbox: white panes over the shell's grey canvas, per the
  // prototype's .inbox (grey) / .inbox-pane (white) split.
  return (
    <div className="h-full flex overflow-hidden">
      {/* Left: conversation list — full-width on mobile when mobileView==="list", sidebar on md+ */}
      <div className={cn(
        "flex-col bg-card",
        "border-r",
        mobileView === "list" ? "flex w-full" : "hidden",
        "md:flex md:w-[280px] md:flex-shrink-0",
      )}
        style={{ borderColor: "var(--haip-border)" }}
      >
        {/* W18: online agents indicator */}
        {onlineUsers.length > 0 && (
          <div className="px-3 py-1.5 flex items-center gap-1.5" style={{ borderBottom: "1px solid var(--haip-border)" }}>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
            <span className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>
              {onlineUsers.length === 1
                ? `${onlineUsers[0].name.split(" ")[0]} is online`
                : `${onlineUsers.length} agents online`}
            </span>
            <div className="ml-auto flex -space-x-1">
              {onlineUsers.slice(0, 4).map(u => (
                <div
                  key={u.id}
                  title={`${u.name} (${u.role})`}
                  className="w-5 h-5 rounded-full flex items-center justify-center text-[8px] font-bold"
                  style={{ background: "var(--primary)", color: "var(--primary-foreground)", border: "1px solid var(--haip-card)" }}
                >
                  {u.name[0]?.toUpperCase()}
                </div>
              ))}
            </div>
          </div>
        )}
        {/* W15: saved views section */}
        {(savedViews as any[]).length > 0 && (
          <div className="px-3 py-2" style={{ borderBottom: "1px solid var(--haip-border)" }}>
            <p className="text-[10px] font-medium uppercase tracking-widest mb-1.5" style={{ color: "var(--haip-fg-subtle)" }}>Saved views</p>
            <div className="space-y-0.5">
              {(savedViews as any[]).map((v: any) => (
                <button
                  key={v.id}
                  onClick={() => setActiveView(av => av === v.id ? null : v.id)}
                  className="w-full text-left px-2.5 py-1.5 rounded-lg text-xs transition-colors duration-150"
                  style={activeView === v.id
                    ? { background: "color-mix(in srgb, var(--primary) 10%, transparent)", color: "var(--primary)", fontWeight: 500 }
                    : { color: "var(--haip-fg-muted)" }}
                >
                  {v.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* M1: channel filter with scroll-fade on overflow */}
        <div className="px-3 py-2.5" style={{ borderBottom: "1px solid var(--haip-border)" }}>
          <ChannelFilterRow
            filters={CHANNEL_FILTERS}
            value={channelFilter}
            onChange={setChannelFilter}
          />
        </div>

        {listLoading ? (
          <div className="flex-1 divide-y" style={{ borderColor: "var(--haip-border)" }}>
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="px-4 py-3.5 flex gap-3">
                <Skeleton className="w-9 h-9 rounded-full flex-shrink-0" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3 w-28" /><Skeleton className="h-2.5 w-40" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <ConversationList
            conversations={conversations}
            activeId={activeConversationId}
            onSelect={id => { setActiveConversation(id); setMobileView("thread"); }}
            channelFilter={channelFilter || undefined}
            className="flex-1"
            onBulkResolve={ids => {
              // W13: resolve multiple conversations
              Promise.all(ids.map(id => api.patch(`/conversations/${id}`, { is_open: false })))
                .then(() => queryClient.invalidateQueries({ queryKey: ["conversations"] }));
            }}
            onArchive={id => {
              // HAIP Inbox full-parity pass, ticket 2: hover-row Archive action
              api.patch(`/conversations/${id}`, { is_open: false })
                .then(() => queryClient.invalidateQueries({ queryKey: ["conversations"] }));
            }}
            onBulkMarkRead={ids => {
              // W13: mark multiple conversations as read
              Promise.all(ids.map(id => api.post(`/conversations/${id}/read`)))
                .then(() => queryClient.invalidateQueries({ queryKey: ["conversations"] }));
            }}
            onLoadMore={hasMoreConversations ? () => fetchNextConversationPage() : undefined}
            isLoadingMore={isLoadingMoreConversations}
            currentUserId={currentUserId}
            onCall={guestNumber => clickToCallMutation.mutate(guestNumber)}
            callingNumber={clickToCallMutation.isPending ? (clickToCallMutation.variables ?? null) : null}
          />
        )}
      </div>

      {/* Center: message thread — full-width on mobile when mobileView==="thread" */}
      <div className={cn(
        "flex-col overflow-hidden bg-card",
        mobileView === "thread" ? "flex flex-1" : "hidden",
        "md:flex md:flex-1",
      )}>
        {!activeConversationId ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center mx-auto mb-4" style={{ background: "var(--muted)" }}>
              <Sparkles size={18} style={{ color: "var(--haip-fg-subtle)" }} />
            </div>
            <p className="text-sm font-medium" style={{ color: "var(--haip-fg)" }}>Select a conversation</p>
            <p className="text-xs mt-1" style={{ color: "var(--haip-fg-subtle)" }}>Choose from the left panel</p>
          </div>
        ) : (
          <>
            <div className="px-3 md:px-5 py-3 flex items-center gap-2 md:gap-3 flex-shrink-0" style={{ borderBottom: "1px solid var(--haip-border)" }}>
              {/* Mobile back button */}
              <button
                onClick={() => setMobileView("list")}
                className="md:hidden flex items-center justify-center w-8 h-8 rounded-lg hover:bg-muted flex-shrink-0 -ml-1"
                style={{ color: "var(--haip-fg-subtle)" }}
                aria-label="Back to conversations"
              >
                <ChevronLeft size={18} />
              </button>
              {detail ? (
                <>
                  <div
                    className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
                    style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
                  >
                    {detail.guest_name?.[0]?.toUpperCase() ?? "?"}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>{detail.guest_name || detail.guest_phone}</div>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <ChannelIcon channel={detail.channel} className="w-4 h-4" />
                      <span className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>{channelLabel(detail.channel)}</span>
                      <Badge variant={detail.status === "open" ? "success" : "ghost"} className="text-[10px] py-0 h-4">{detail.status}</Badge>
                      {/* HAIP Inbox full-parity pass, ticket 5: completeness
                          pill -- real data (not a fake "convert to lead"
                          action like the prototype's pill), scrolls to the
                          existing ProfileCompletenessWidget on click. */}
                      {threadLeadDetail?.profile_completeness_pct != null && (
                        <button
                          type="button"
                          onClick={() => document.getElementById("profile-completeness-widget")?.scrollIntoView({ behavior: "smooth", block: "center" })}
                          title="Jump to profile completeness"
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold transition-colors hover:opacity-80"
                          style={{ background: "color-mix(in srgb, var(--primary) 10%, transparent)", color: "var(--primary)" }}
                        >
                          {threadLeadDetail.profile_completeness_pct}% complete
                        </button>
                      )}
                      {/* D9: WhatsApp 24h service window indicator */}
                      {isWhatsApp && detail.last_inbound_at && (
                        windowOpen ? (
                          <span
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium"
                            style={{
                              background: "color-mix(in srgb, var(--haip-green) 10%, transparent)",
                              border: "1px solid color-mix(in srgb, var(--haip-green) 30%, transparent)",
                              color: "var(--haip-green)",
                            }}
                          >
                            <Timer size={9} />
                            {/* suppress lint: windowTick used to trigger re-render on tick */}
                            Service window: {formatWindowCountdown(getWindowSecondsLeft(detail.last_inbound_at))}
                          </span>
                        ) : (
                          <span
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium"
                            style={{
                              background: "color-mix(in srgb, var(--haip-amber) 10%, transparent)",
                              border: "1px solid color-mix(in srgb, var(--haip-amber) 35%, transparent)",
                              color: "var(--haip-amber)",
                            }}
                          >
                            <AlertTriangle size={9} />
                            Template required
                          </span>
                        )
                      )}
                    </div>
                  </div>
                  {/* W17: search */}
                  <button
                    onClick={() => setShowSearch(s => !s)}
                    className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors duration-150 hover:bg-muted"
                    style={{ color: "var(--haip-fg-subtle)" }}
                    title="Search messages"
                  >
                    <Search size={14} />
                  </button>
                  {/* W14: snooze */}
                  <div className="relative">
                    <button
                      onClick={() => setShowSnooze(s => !s)}
                      className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors duration-150 hover:bg-muted"
                      style={{ color: "var(--haip-fg-subtle)" }}
                      title="Snooze conversation"
                    >
                      <BellOff size={14} />
                    </button>
                    {showSnooze && (
                      <div className="absolute top-full right-0 mt-1 z-20 rounded-xl shadow-md overflow-hidden w-44" style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)" }}>
                        {[
                          { label: "3 hours", hours: 3 },
                          { label: "Tomorrow 9am", hours: 18 },
                          { label: "Next week", hours: 168 },
                        ].map(opt => (
                          <button
                            key={opt.label}
                            onClick={() => { snoozeMutation.mutate(new Date(Date.now() + opt.hours * 3600_000).toISOString()); }}
                            className="w-full text-left px-4 py-2 text-xs transition-colors duration-150 hover:bg-muted"
                            style={{ color: "var(--haip-fg-muted)" }}
                          >
                            {opt.label}
                          </button>
                        ))}
                        <button
                          onClick={() => snoozeMutation.mutate(null)}
                          className="w-full text-left px-4 py-2 text-xs transition-colors duration-150 hover:bg-muted"
                          style={{ color: "var(--haip-red)", borderTop: "1px solid var(--haip-border)" }}
                        >
                          Clear snooze
                        </button>
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => draftMutation.mutate()}
                    disabled={draftMutation.isPending || aiTyping}
                    className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors duration-150 disabled:opacity-50"
                    style={{
                      background: "color-mix(in srgb, var(--primary) 8%, transparent)",
                      border: "1px solid color-mix(in srgb, var(--primary) 20%, transparent)",
                      color: "var(--primary)",
                    }}
                  >
                    {draftMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                    AI draft
                  </button>
                </>
              ) : <Skeleton className="h-6 w-48" />}
            </div>

            {/* W7: AI tone strip */}
            {(conversations.find(c => c.id === activeConversationId)?.has_ai_draft || aiTyping) && (
              <div className="px-4 py-2 flex-shrink-0" style={{ borderBottom: "1px solid var(--haip-border)", background: "color-mix(in srgb, var(--primary) 4%, transparent)" }}>
                <AIDraftPanel
                  tone={aiTone}
                  onToneChange={setAiTone}
                  onRegenerate={() => draftMutation.mutate()}
                  isPending={draftMutation.isPending || aiTyping}
                  hasDraft={true}
                  rejectedCount={rejectedDrafts.length}
                  onRecallRejected={() => {
                    const last = rejectedDrafts[rejectedDrafts.length - 1];
                    if (last) { setReplyText(last); setRejectedDrafts(p => p.slice(0, -1)); }
                  }}
                />
              </div>
            )}

            {/* HAIP Inbox UI-fidelity pass, ticket 5: pinned-inquiry banner
                (dates/guests/budget + lead score) above the thread. */}
            <PinnedInquiryBanner inquiryId={detail?.inquiry_id ?? null} />

            {/* W17: search overlay */}
            {showSearch && (
              <div className="px-4 py-3 space-y-2 flex-shrink-0" style={{ borderBottom: "1px solid var(--haip-border)", background: "var(--muted)" }}>
                <div className="flex items-center gap-2">
                  <Search size={13} className="flex-shrink-0" style={{ color: "var(--haip-fg-subtle)" }} />
                  <input
                    autoFocus
                    value={searchQ}
                    onChange={e => setSearchQ(e.target.value)}
                    placeholder="Search messages…"
                    className="flex-1 text-sm bg-transparent outline-none"
                    style={{ color: "var(--haip-fg)" }}
                  />
                  <button onClick={() => { setShowSearch(false); setSearchQ(""); }} style={{ color: "var(--haip-fg-subtle)" }}><X size={13} /></button>
                </div>
                {searchQ.length >= 2 && (
                  <div className="space-y-1 max-h-48 overflow-y-auto haip-scrollbar">
                    {searchLoading ? <p className="text-xs py-2 text-center" style={{ color: "var(--haip-fg-subtle)" }}>Searching…</p>
                    : (searchResults as any[]).length === 0 ? <p className="text-xs py-2 text-center" style={{ color: "var(--haip-fg-subtle)" }}>No results</p>
                    : (searchResults as any[]).map((r: any) => (
                      <button
                        key={r.message_id}
                        onClick={() => { setActiveConversation(r.conversation_id); setShowSearch(false); setSearchQ(""); }}
                        className="w-full text-left px-3 py-2 rounded-lg text-xs transition-colors duration-150 hover:bg-card"
                      >
                        <p className="font-medium truncate" style={{ color: "var(--haip-fg)" }}>{r.guest_name || r.guest_phone}</p>
                        <p className="truncate" style={{ color: "var(--haip-fg-subtle)" }}>{r.snippet}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Thread body sits a shade below the white pane so the message
                column reads as its own surface (prototype .thread-body).
                --haip-surface, not a literal gradient: it resolves to #F8FAFC
                in light and the page bg in dark, so this doesn't invert. */}
            <div
              className="flex-1 overflow-y-auto px-3 md:px-5 py-4 space-y-3"
              style={{ background: "var(--haip-surface)" }}
            >
              {detailLoading ? (
                <div className="space-y-4">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className={cn("flex", i % 2 === 0 ? "justify-start" : "justify-end")}>
                      <Skeleton className="h-10 w-48 rounded-2xl" />
                    </div>
                  ))}
                </div>
              ) : (
                <>
                  {hasMoreOlderMessages && (
                    <div className="flex justify-center pb-1">
                      <button
                        onClick={loadOlderMessages}
                        disabled={loadingOlderMessages}
                        className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors duration-150 disabled:opacity-50"
                        style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)", background: "var(--haip-card)" }}
                      >
                        {loadingOlderMessages
                          ? <><Loader2 size={12} className="animate-spin" /> Loading…</>
                          : "Load older messages"}
                      </button>
                    </div>
                  )}
                  {(() => {
                    const msgs = [...olderMessages, ...(detail?.messages ?? [])];
                    // Interleave calls (ticket 2) by timestamp -- messages
                    // keep their own tested render path, calls are spliced
                    // in purely for chronological display.
                    type Row = { key: string; at: number } & (
                      | { kind: "message"; msg: Message }
                      | { kind: "call"; call: CallTimelineItem }
                    );
                    const rows: Row[] = [
                      ...msgs.map(m => ({ key: `m-${m.id}`, at: new Date(m.timestamp).getTime(), kind: "message" as const, msg: m })),
                      ...callItems.map(c => ({ key: `c-${c.call.id}`, at: new Date(c.occurred_at).getTime(), kind: "call" as const, call: c.call })),
                    ].sort((a, b) => a.at - b.at);

                    return rows.map(row => row.kind === "call" ? (
                      <CallLogCard key={row.key} call={row.call} />
                    ) : (
                      <MessageBubble
                        key={row.key}
                        id={row.msg.id}
                        text={row.msg.text}
                        direction={row.msg.direction}
                        status={(row.msg.delivery_state ?? row.msg.status) as any}
                        deliveryError={row.msg.delivery_error}
                        timestamp={row.msg.timestamp}
                        isAiDraft={!!(row.msg.ai_drafted && row.msg.direction === "outbound")}
                        isInternal={row.msg.is_internal}
                        aiConfidence={row.msg.ai_confidence}
                        senderName={row.msg.direction === "outbound" ? row.msg.sender_name : (detail?.guest_name || detail?.guest_phone)}
                        mediaUrl={row.msg.media_url}
                        mediaType={row.msg.media_type}
                        sharedPostUrl={row.msg.shared_post_url}
                        suggestedActions={row.msg.suggested_actions}
                        entityRefs={{ guest_id: detail?.guest_id, inquiry_id: detail?.inquiry_id ?? undefined }}
                        onApprove={handleApprove}
                        onEdit={(id, text) => { setEditingDraftId(id); setEditText(text); }}
                        onReject={handleReject}
                        onRetry={handleRetry}
                        onReply={(id) => {
                          setReplyToMsg(row.msg);
                          textareaRef.current?.focus();
                        }}
                        onRewrite={(id, opts) => rewriteDraft.mutate({ messageId: id, tone: opts.tone, targetLanguage: opts.target_language })}
                        isRewriting={rewritingMessageId === row.msg.id}
                      />
                    ));
                  })()}
                  {aiTyping && <div className="flex justify-start"><TypingDots /></div>}
                  <div ref={bottomRef} />
                </>
              )}
            </div>

            {editingDraftId && (
              <div className="px-5 py-3 flex gap-2" style={{ borderTop: "1px solid var(--haip-border)", background: "color-mix(in srgb, var(--primary) 4%, transparent)" }}>
                <textarea
                  value={editText}
                  onChange={e => setEditText(e.target.value)}
                  rows={2}
                  className="flex-1 text-sm rounded-lg px-3 py-2 focus:outline-none resize-none"
                  style={{ border: "1px solid var(--haip-border)", background: "var(--haip-card)", color: "var(--haip-fg)" }}
                />
                <div className="flex flex-col gap-1">
                  <button
                    onClick={() => {
                      api.post(`/conversations/${activeConversationId}/messages/${editingDraftId}/approve`, { text: editText })
                        .then(() => { setEditingDraftId(null); queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] }); toast({ variant: "success", title: "Edited draft sent" }); });
                    }}
                    className="text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors duration-150"
                    style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
                  >Send</button>
                  <button onClick={() => setEditingDraftId(null)} className="text-xs px-3 py-1.5" style={{ color: "var(--haip-fg-subtle)" }}>Cancel</button>
                </div>
              </div>
            )}

            {/* HAIP Inbox UI-fidelity pass, ticket 5: no chat composer for a
                voice-only conversation -- there's no WhatsApp/Instagram
                thread to send into, only the call log above. */}
            {isVoiceOnly && (
              <div
                className="px-4 py-4 flex items-center gap-3 flex-shrink-0"
                style={{ borderTop: "1px solid var(--haip-border)", background: "var(--muted)" }}
              >
                <Phone size={16} style={{ color: "var(--haip-fg-subtle)" }} />
                <p className="text-xs font-medium" style={{ color: "var(--haip-fg-subtle)" }}>
                  No chat channel yet — call log only
                </p>
              </div>
            )}

            {/* D9: Window-closed blocker — shown instead of composer when 24h window expired */}
            {!isVoiceOnly && windowBlocked && (
              <div
                className="px-4 py-4 flex-shrink-0"
                style={{
                  borderTop: "1px solid color-mix(in srgb, var(--haip-amber) 30%, transparent)",
                  background: "color-mix(in srgb, var(--haip-amber) 6%, transparent)",
                }}
              >
                <div className="flex items-start gap-3">
                  <div
                    className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
                    style={{ background: "color-mix(in srgb, var(--haip-amber) 15%, transparent)" }}
                  >
                    <AlertTriangle size={14} style={{ color: "var(--haip-amber)" }} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold" style={{ color: "var(--haip-amber)" }}>24-hour service window closed</p>
                    <p className="text-xs mt-0.5" style={{ color: "var(--haip-amber)" }}>
                      Free-form messages are not allowed. Send a pre-approved WhatsApp template to re-open the window.
                    </p>
                    <div className="flex gap-2 mt-3">
                      <button
                        onClick={() => setShowTemplatePicker(true)}
                        className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
                        style={{ background: "var(--haip-amber)", color: "#fff" }}
                      >
                        <LayoutTemplate size={12} />
                        Send template
                      </button>
                      <button
                        onClick={() => { setIsInternalNote(true); }}
                        className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
                        style={{
                          background: "color-mix(in srgb, var(--haip-amber) 15%, transparent)",
                          color: "var(--haip-amber)",
                        }}
                      >
                        <StickyNote size={12} />
                        Internal note
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Composer */}
            <div
              className={cn("px-3 md:px-4 pt-2 pb-2 md:pb-1 flex-shrink-0", (isVoiceOnly || (windowBlocked && !isInternalNote)) && "hidden")}
              style={{
                borderTop: isInternalNote
                  ? "1px solid color-mix(in srgb, var(--haip-amber) 30%, transparent)"
                  : "1px solid var(--haip-border)",
                background: isInternalNote ? "color-mix(in srgb, var(--haip-amber) 4%, transparent)" : "transparent",
              }}
            >
              {/* W24: internal note banner */}
              {isInternalNote && (
                <div className="flex items-center gap-2 mb-2 px-1">
                  <StickyNote size={12} style={{ color: "var(--haip-amber)" }} />
                  <span className="text-xs font-semibold" style={{ color: "var(--haip-amber)" }}>Internal note — not sent to guest</span>
                  <button onClick={exitInternalNote} className="ml-auto transition-colors" style={{ color: "var(--haip-fg-subtle)" }}>
                    <X size={12} />
                  </button>
                </div>
              )}
              {/* W5: reply-to preview */}
              {replyToMsg && (
                <div className="flex items-start gap-2 mb-2 px-1 py-1 rounded-lg" style={{ background: "var(--muted)", borderLeft: "2px solid var(--primary)" }}>
                  <Reply size={11} className="mt-0.5 flex-shrink-0" style={{ color: "var(--primary)" }} />
                  <p className="text-xs truncate flex-1" style={{ color: "var(--haip-fg-muted)" }}>{replyToMsg.text}</p>
                  <button onClick={() => setReplyToMsg(null)} className="flex-shrink-0" style={{ color: "var(--haip-fg-subtle)" }}>
                    <X size={11} />
                  </button>
                </div>
              )}
              {/* W4: scheduled send banner */}
              {scheduledFor && (
                <div
                  className="flex items-center gap-2 mb-2 px-1 py-1 rounded-lg"
                  style={{
                    background: "color-mix(in srgb, #3B82F6 8%, transparent)",
                    border: "1px solid color-mix(in srgb, #3B82F6 20%, transparent)",
                  }}
                >
                  <CalendarClock size={12} className="flex-shrink-0" style={{ color: "#3B82F6" }} />
                  <span className="text-xs flex-1" style={{ color: "#3B82F6" }}>
                    Scheduled for {new Date(scheduledFor).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                  </span>
                  <button onClick={() => setScheduledFor(null)} style={{ color: "#3B82F6", opacity: 0.6 }}>
                    <X size={11} />
                  </button>
                </div>
              )}
              {/* HAIP Inbox full-parity pass, ticket 5: Translate/Tone-Fix on
                  whatever the agent is currently typing -- distinct from
                  MessageBubble's pickers, which only operate on an
                  already-stored AI draft. */}
              {!isInternalNote && replyText.trim().length > 0 && (
                <div className="flex items-center gap-1.5 mb-1.5 px-1">
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => { setShowComposerTonePicker(v => !v); setShowComposerLangPicker(false); }}
                      disabled={isComposerRewriting}
                      className="flex items-center gap-1 text-[11px] text-gray-500 bg-white hover:bg-gray-50 border border-gray-200 px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                    >
                      {isComposerRewriting ? <Loader2 size={11} className="animate-spin" /> : <Wand2 size={11} />} Tone Fix
                    </button>
                    {showComposerTonePicker && (
                      <div className="absolute z-10 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[110px]">
                        {COMPOSER_REWRITE_TONES.map(t => (
                          <button
                            key={t}
                            onClick={() => { composerRewrite.mutate({ tone: t }); setShowComposerTonePicker(false); }}
                            className="w-full text-left px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 capitalize"
                          >
                            {t}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => { setShowComposerLangPicker(v => !v); setShowComposerTonePicker(false); }}
                      disabled={isComposerRewriting}
                      className="flex items-center gap-1 text-[11px] text-gray-500 bg-white hover:bg-gray-50 border border-gray-200 px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                    >
                      <Languages size={11} /> Translate
                    </button>
                    {showComposerLangPicker && (
                      <div className="absolute z-10 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[110px]">
                        {COMPOSER_REWRITE_LANGUAGES.map(lang => (
                          <button
                            key={lang}
                            onClick={() => { composerRewrite.mutate({ targetLanguage: lang }); setShowComposerLangPicker(false); }}
                            className="w-full text-left px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
                          >
                            {lang}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="relative flex gap-2 items-end">
                {/* W3: SavedReplyMenu */}
                {showSavedReplies && (
                  <SavedReplyMenu
                    query={savedReplyQuery}
                    context={{ guest_name: detail?.guest_name }}
                    onSelect={(resolved) => {
                      setReplyText(resolved);
                      setShowSavedReplies(false);
                      textareaRef.current?.focus();
                    }}
                    onClose={() => setShowSavedReplies(false)}
                    anchorRef={textareaRef}
                  />
                )}

                {/* W25: @mention dropdown */}
                {mentionQuery !== null && mentionMatches.length > 0 && (
                  <div
                    className="absolute bottom-full left-0 mb-1.5 z-30 rounded-xl p-1 min-w-[200px]"
                    style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", boxShadow: "var(--haip-shadow-lg)" }}
                  >
                    <p className="text-[10px] font-semibold uppercase px-2 py-1" style={{ color: "var(--haip-fg-subtle)" }}>Mention teammate</p>
                    {mentionMatches.map((u: any) => (
                      <button
                        key={u.id}
                        onClick={() => insertMention(u)}
                        className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-muted"
                      >
                        <div
                          className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0"
                          style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
                        >
                          {u.name?.[0]?.toUpperCase() ?? "?"}
                        </div>
                        <div className="text-left">
                          <p className="text-xs font-medium" style={{ color: "var(--haip-fg)" }}>{u.name}</p>
                          <p className="text-[10px] capitalize" style={{ color: "var(--haip-fg-subtle)" }}>{u.role}</p>
                        </div>
                        {onlineUsers.some(o => o.id === u.id) && (
                          <span className="ml-auto w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: "var(--haip-green)" }} />
                        )}
                      </button>
                    ))}
                  </div>
                )}

                {/* W4: schedule dropdown */}
                {showSchedule && (
                  <div
                    className="absolute bottom-full right-0 mb-1.5 z-30 rounded-xl p-1 min-w-[170px]"
                    style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", boxShadow: "var(--haip-shadow-lg)" }}
                  >
                    <p className="text-[10px] font-semibold uppercase px-2 py-1" style={{ color: "var(--haip-fg-subtle)" }}>Send later</p>
                    {SCHEDULE_OPTIONS.map(opt => (
                      <button
                        key={opt.label}
                        onClick={() => {
                          const iso = opt.getValue();
                          setScheduledFor(iso);
                          setShowSchedule(false);
                        }}
                        className="w-full text-left text-xs px-3 py-1.5 rounded-lg hover:bg-muted"
                        style={{ color: "var(--haip-fg-muted)" }}
                      >
                        {opt.label}
                      </button>
                    ))}
                    <div className="pt-1 px-2 pb-1 mt-1" style={{ borderTop: "1px solid var(--haip-border)" }}>
                      <input
                        type="datetime-local"
                        className="w-full text-xs rounded-lg px-2 py-1 focus:outline-none"
                        style={{ border: "1px solid var(--haip-border)", background: "var(--input-bg)", color: "var(--haip-fg)" }}
                        onChange={e => {
                          if (e.target.value) {
                            setScheduledFor(new Date(e.target.value).toISOString());
                            setShowSchedule(false);
                          }
                        }}
                      />
                    </div>
                  </div>
                )}

                <textarea
                  ref={textareaRef}
                  value={replyText}
                  onChange={handleTextChange}
                  onKeyDown={handleKeyDown}
                  rows={1}
                  placeholder={isInternalNote ? "Write an internal note…" : "Type a message or / for saved replies…"}
                  className={cn("flex-1 text-sm rounded-xl px-3.5 py-2.5 focus:outline-none resize-none transition-all", emptyPulse && "animate-pulse")}
                  style={{
                    minHeight: "42px",
                    background: isInternalNote ? "rgba(245,158,11,0.06)" : "var(--input-bg)",
                    border: `1px solid ${emptyPulse ? "var(--haip-red)" : isInternalNote ? "rgba(245,158,11,0.4)" : "var(--haip-border)"}`,
                    color: "var(--haip-fg)",
                  }}
                />
                {/* Send button + Schedule dropdown trigger */}
                <div className="flex flex-shrink-0">
                  <button
                    onClick={() => handleSend()}
                    disabled={sendMutation.isPending}
                    className="h-10 px-3 rounded-l-xl flex items-center justify-center transition-colors duration-150"
                    style={{
                      background: isEmpty ? "var(--muted)" : isInternalNote ? "#F59E0B" : scheduledFor ? "#2563EB" : "var(--primary)",
                      color: isEmpty ? "var(--haip-fg-subtle)" : "var(--primary-foreground)",
                      cursor: isEmpty ? "not-allowed" : "pointer",
                    }}
                    aria-label="Send message"
                  >
                    {sendMutation.isPending ? <Loader2 size={14} className="animate-spin" />
                     : isInternalNote ? <StickyNote size={14} />
                     : scheduledFor ? <CalendarClock size={14} />
                     : <Send size={14} />}
                  </button>
                  {!isInternalNote && (
                    <button
                      onClick={() => setShowSchedule(v => !v)}
                      title="Schedule send"
                      className="h-10 w-6 rounded-r-xl flex items-center justify-center transition-colors duration-150"
                    style={{
                      background: isEmpty ? "var(--muted)" : scheduledFor ? "#2563EB" : "var(--primary)",
                      color: isEmpty ? "var(--haip-fg-subtle)" : "var(--primary-foreground)",
                      borderLeft: "1px solid rgba(255,255,255,0.15)",
                    }}
                    >
                      <ChevronDown size={11} />
                    </button>
                  )}
                </div>
              </div>
              {/* W2: helper text */}
              <p className="text-[10px] mt-1 px-1" style={{ color: "var(--haip-fg-subtle)" }}>
                {isInternalNote
                  ? "Esc to cancel · Enter to save note"
                  : scheduledFor
                  ? "Click send to schedule · click ✕ above to cancel"
                  : "Enter to send · Shift+Enter newline · /note for internal notes · / for saved replies"}
              </p>
            </div>
          </>
        )}
      </div>

      {/* Right: Guest 360 panel — hidden on mobile */}
      {detail && <GuestPanel detail={detail} />}

      {showTemplatePicker && activeConversationId && (
        <TemplatePickerModal
          conversationId={activeConversationId}
          onClose={() => setShowTemplatePicker(false)}
          onSent={() => toast({ variant: "success", title: "Template sent", description: "The template message is on its way." })}
        />
      )}
    </div>
  );
}
