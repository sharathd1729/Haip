"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Send, Sparkles, User, Loader2, BellOff, Search, X, StickyNote, Reply, Clock, ChevronDown, ChevronLeft, CalendarClock, Timer, AlertTriangle, LayoutTemplate } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { ConversationList } from "@/components/inbox/ConversationList";
import { MessageBubble } from "@/components/inbox/MessageBubble";
import { SavedReplyMenu } from "@/components/inbox/SavedReplyMenu";
import { AIDraftPanel } from "@/components/inbox/AIDraftPanel";
import { TypingDots } from "@/components/inbox/TypingDots";
import { ChannelIcon } from "@/components/inbox/ChannelIcon";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useInboxStore } from "@/store/inbox";
import { useInboxStream } from "@/hooks/useInboxStream";
import { useAutoGrow } from "@/hooks/useAutoGrow";
import { useToast } from "@/components/ui/toast";
import { usePresence } from "@/hooks/usePresence";

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
}

interface ConversationDetail {
  id: string;
  guest_name?: string;
  guest_phone: string;
  channel: string;
  status: "open" | "resolved" | "snoozed";
  messages: Message[];
  last_inbound_at?: string | null;  // D9: WhatsApp 24h service window
}

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

const CHANNEL_FILTERS = [
  { value: "",          label: "All" },
  { value: "whatsapp",  label: "WhatsApp" },
  { value: "instagram", label: "Instagram" },
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
          style={{ background: "linear-gradient(to right, white, transparent)" }} />
      )}
      {/* Right fade */}
      {canScrollRight && (
        <div className="pointer-events-none absolute right-0 top-0 bottom-0 w-8 z-10"
          style={{ background: "linear-gradient(to left, white, transparent)" }} />
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
            className={cn(
              "flex-shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors min-h-[36px] min-w-[40px]",
              value === f.value ? "bg-teal-500 text-white" : "text-gray-500 hover:bg-gray-100"
            )}
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
  const { data: session } = useSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();
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

  // Queries must be declared before derived state that references their data
  const { data: conversationData, isLoading: listLoading } = useQuery<any[]>({
    queryKey: ["conversations"],
    queryFn: () => api.get("/conversations").then(r => r.data),
    staleTime: 30_000,
  });

  // onSuccess was removed in TanStack Query v5 — use useEffect to sync store
  useEffect(() => {
    if (conversationData) setConversations(conversationData);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationData]);

  const { data: detail, isLoading: detailLoading } = useQuery<ConversationDetail>({
    queryKey: ["conversation", activeConversationId],
    queryFn: () => api.get(`/conversations/${activeConversationId}`).then(r => r.data),
    enabled: !!activeConversationId,
    staleTime: 0,
  });

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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [detail?.messages]);

  const accessToken = (session as any)?.accessToken as string | undefined;

  useInboxStream(accessToken, useCallback((event) => {
    if (event.event === "message_received" && event.conversation_id) {
      queryClient.invalidateQueries({ queryKey: ["conversation", event.conversation_id] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    }
    if (event.event === "ai_draft_ready" && event.conversation_id) {
      setAiDraft(event.conversation_id as string, true);
      queryClient.invalidateQueries({ queryKey: ["conversation", event.conversation_id] });
      toast({ variant: "info", title: "AI draft ready", description: "Review and approve in inbox." });
    }
  }, [queryClient, setAiDraft, toast]));

  const sendMutation = useMutation({
    mutationFn: ({ text, is_internal, replied_to_message_id, scheduled_for }: { text: string; is_internal?: boolean; replied_to_message_id?: string; scheduled_for?: string | null }) =>
      api.post(`/conversations/${activeConversationId}/messages`, {
        body: text,
        direction: "outbound",
        is_internal: is_internal ?? false,
        replied_to_message_id: replied_to_message_id ?? null,
        scheduled_for: scheduled_for ?? null,
      }),
    onSuccess: () => {
      setReplyText("");
      setIsInternalNote(false);
      setReplyToMsg(null);
      setScheduledFor(null);
      setShowSchedule(false);
      queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] });
    },
    onError: () => toast({ variant: "error", title: "Send failed" }),
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
      api.post(`/conversations/${activeConversationId}/messages/ai-draft`, {}),
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
  const triggerEmptyPulse = () => {
    setEmptyPulse(true);
    setTimeout(() => setEmptyPulse(false), 800);
  };

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

  return (
    <div className="h-full flex overflow-hidden bg-white">
      {/* Left: conversation list — full-width on mobile when mobileView==="list", sidebar on md+ */}
      <div className={cn(
        "flex-col border-r border-gray-100",
        // mobile: full width on list view, hidden on thread view
        mobileView === "list" ? "flex w-full" : "hidden",
        // desktop: always visible, fixed width
        "md:flex md:w-72 md:flex-shrink-0",
      )}>
        {/* W18: online agents indicator */}
        {onlineUsers.length > 0 && (
          <div className="px-3 py-1.5 border-b border-gray-50 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 flex-shrink-0" />
            <span className="text-[10px] text-gray-500">
              {onlineUsers.length === 1
                ? `${onlineUsers[0].name.split(" ")[0]} is online`
                : `${onlineUsers.length} agents online`}
            </span>
            <div className="ml-auto flex -space-x-1">
              {onlineUsers.slice(0, 4).map(u => (
                <div
                  key={u.id}
                  title={`${u.name} (${u.role})`}
                  className="w-5 h-5 rounded-full bg-teal-500 border border-white flex items-center justify-center text-white text-[8px] font-bold"
                >
                  {u.name[0]?.toUpperCase()}
                </div>
              ))}
            </div>
          </div>
        )}
        {/* W15: saved views section */}
        {(savedViews as any[]).length > 0 && (
          <div className="px-3 py-2 border-b border-gray-50">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Saved views</p>
            <div className="space-y-0.5">
              {(savedViews as any[]).map((v: any) => (
                <button
                  key={v.id}
                  onClick={() => setActiveView(av => av === v.id ? null : v.id)}
                  className={cn(
                    "w-full text-left px-2.5 py-1.5 rounded-lg text-xs transition-colors",
                    activeView === v.id ? "bg-teal-100 text-teal-700 font-medium" : "text-gray-600 hover:bg-gray-50"
                  )}
                >
                  {v.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* M1: channel filter with scroll-fade on overflow */}
        <div className="px-3 py-2.5 border-b border-gray-100">
          <ChannelFilterRow
            filters={CHANNEL_FILTERS}
            value={channelFilter}
            onChange={setChannelFilter}
          />
        </div>

        {listLoading ? (
          <div className="flex-1 divide-y divide-gray-50">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="px-4 py-3.5 flex gap-3">
                <Skeleton className="w-9 h-9 rounded-full" />
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
            onBulkMarkRead={ids => {
              // W13: mark multiple conversations as read
              Promise.all(ids.map(id => api.post(`/conversations/${id}/read`)))
                .then(() => queryClient.invalidateQueries({ queryKey: ["conversations"] }));
            }}
          />
        )}
      </div>

      {/* Center: message thread — full-width on mobile when mobileView==="thread" */}
      <div className={cn(
        "flex-col overflow-hidden",
        mobileView === "thread" ? "flex flex-1" : "hidden",
        "md:flex md:flex-1",
      )}>
        {!activeConversationId ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
            <div className="w-14 h-14 rounded-2xl bg-gray-100 flex items-center justify-center mx-auto mb-4">
              <Sparkles size={24} className="text-gray-400" />
            </div>
            <p className="text-gray-500 text-sm font-medium">Select a conversation</p>
            <p className="text-gray-400 text-xs mt-1">Choose from the left panel</p>
          </div>
        ) : (
          <>
            <div className="px-3 md:px-5 py-3 border-b border-gray-100 flex items-center gap-2 md:gap-3 flex-shrink-0">
              {/* Mobile back button */}
              <button
                onClick={() => setMobileView("list")}
                className="md:hidden flex items-center justify-center w-8 h-8 rounded-lg text-gray-500 hover:bg-gray-100 flex-shrink-0 -ml-1"
                aria-label="Back to conversations"
              >
                <ChevronLeft size={18} />
              </button>
              {detail ? (
                <>
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-teal-400 to-blue-500 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
                    {detail.guest_name?.[0]?.toUpperCase() ?? "?"}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-gray-900">{detail.guest_name || detail.guest_phone}</div>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <ChannelIcon channel={detail.channel} className="w-4 h-4" />
                      <span className="text-xs text-gray-400 capitalize">{detail.channel}</span>
                      <Badge variant={detail.status === "open" ? "success" : "ghost"} className="text-[10px] py-0 h-4">{detail.status}</Badge>
                      {/* D9: WhatsApp 24h service window indicator */}
                      {isWhatsApp && detail.last_inbound_at && (
                        windowOpen ? (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-green-50 border border-green-200 text-[10px] text-green-700 font-medium">
                            <Timer size={9} />
                            {/* suppress lint: windowTick used to trigger re-render on tick */}
                            Service window: {formatWindowCountdown(getWindowSecondsLeft(detail.last_inbound_at))}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-amber-50 border border-amber-300 text-[10px] text-amber-700 font-medium">
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
                    className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center transition-colors"
                    title="Search messages (W17)"
                  >
                    <Search size={14} />
                  </button>
                  {/* W14: snooze */}
                  <div className="relative">
                    <button
                      onClick={() => setShowSnooze(s => !s)}
                      className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center transition-colors"
                      title="Snooze conversation (W14)"
                    >
                      <BellOff size={14} />
                    </button>
                    {showSnooze && (
                      <div className="absolute top-full right-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-lg z-20 overflow-hidden w-44">
                        {[
                          { label: "3 hours", hours: 3 },
                          { label: "Tomorrow 9am", hours: 18 },
                          { label: "Next week", hours: 168 },
                        ].map(opt => (
                          <button
                            key={opt.label}
                            onClick={() => {
                              const d = new Date(Date.now() + opt.hours * 3600_000);
                              snoozeMutation.mutate(d.toISOString());
                            }}
                            className="w-full text-left px-4 py-2 text-xs text-gray-700 hover:bg-gray-50 transition-colors"
                          >
                            {opt.label}
                          </button>
                        ))}
                        <button
                          onClick={() => snoozeMutation.mutate(null)}
                          className="w-full text-left px-4 py-2 text-xs text-red-500 hover:bg-red-50 border-t border-gray-100 transition-colors"
                        >
                          Clear snooze
                        </button>
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => draftMutation.mutate()}
                    disabled={draftMutation.isPending || aiTyping}
                    className="flex items-center gap-1.5 text-xs font-medium text-teal-600 bg-teal-50 hover:bg-teal-100 border border-teal-200 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
                  >
                    {draftMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                    AI draft
                  </button>
                </>
              ) : <Skeleton className="h-6 w-48" />}
            </div>

            {/* W7: AI tone strip — show when AI draft exists or AI is active */}
            {(conversations.find(c => c.id === activeConversationId)?.has_ai_draft || aiTyping) && (
              <div className="px-4 py-2 border-b border-teal-100 bg-teal-50/50 flex-shrink-0">
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

            {/* W17: search overlay */}
            {showSearch && (
              <div className="border-b border-gray-100 px-4 py-3 bg-gray-50 space-y-2 flex-shrink-0">
                <div className="flex items-center gap-2">
                  <Search size={13} className="text-gray-400 flex-shrink-0" />
                  <input
                    autoFocus
                    value={searchQ}
                    onChange={e => setSearchQ(e.target.value)}
                    placeholder="Search messages…"
                    className="flex-1 text-sm bg-transparent outline-none text-gray-800 placeholder:text-gray-400"
                  />
                  <button onClick={() => { setShowSearch(false); setSearchQ(""); }}><X size={13} className="text-gray-400" /></button>
                </div>
                {searchQ.length >= 2 && (
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {searchLoading ? <p className="text-xs text-gray-400 py-2 text-center">Searching…</p>
                    : (searchResults as any[]).length === 0 ? <p className="text-xs text-gray-400 py-2 text-center">No results</p>
                    : (searchResults as any[]).map((r: any) => (
                      <button
                        key={r.message_id}
                        onClick={() => {
                          setActiveConversation(r.conversation_id);
                          setShowSearch(false);
                          setSearchQ("");
                        }}
                        className="w-full text-left px-3 py-2 rounded-lg hover:bg-white text-xs transition-colors"
                      >
                        <p className="font-medium text-gray-800 truncate">{r.guest_name || r.guest_phone}</p>
                        <p className="text-gray-500 truncate">{r.snippet}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="flex-1 overflow-y-auto px-3 md:px-5 py-4 space-y-3">
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
                  {detail?.messages.map(msg => (
                    <MessageBubble
                      key={msg.id}
                      id={msg.id}
                      text={msg.text}
                      direction={msg.direction}
                      status={(msg.delivery_state ?? msg.status) as any}
                      deliveryError={msg.delivery_error}
                      timestamp={msg.timestamp}
                      isAiDraft={!!(msg.ai_drafted && msg.direction === "outbound")}
                      isInternal={msg.is_internal}
                      aiConfidence={msg.ai_confidence}
                      senderName={msg.direction === "outbound" ? msg.sender_name : (detail.guest_name || detail.guest_phone)}
                      onApprove={(id) => approveMutation.mutate(id)}
                      onEdit={(id, text) => { setEditingDraftId(id); setEditText(text); }}
                      onReject={(id) => {
                        // W7: stash up to last 3 rejected drafts for recall
                        const draftMsg = detail?.messages.find(m => m.id === id);
                        if (draftMsg) setRejectedDrafts(p => [...p.slice(-2), draftMsg.text]);
                        api.post(`/conversations/${activeConversationId}/messages/${id}/reject`, {}).catch(() => {});
                        queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] });
                      }}
                      onRetry={(id) => retryMutation.mutate({ conversationId: activeConversationId!, messageId: id })}
                      onReply={(id) => {
                        setReplyToMsg(msg);
                        textareaRef.current?.focus();
                      }}
                    />
                  ))}
                  {aiTyping && <div className="flex justify-start"><TypingDots /></div>}
                  <div ref={bottomRef} />
                </>
              )}
            </div>

            {editingDraftId && (
              <div className="px-5 py-3 bg-teal-50 border-t border-teal-100 flex gap-2">
                <textarea
                  value={editText}
                  onChange={e => setEditText(e.target.value)}
                  rows={2}
                  className="flex-1 text-sm border border-teal-200 rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal-500 resize-none bg-white"
                />
                <div className="flex flex-col gap-1">
                  <button
                    onClick={() => {
                      api.post(`/conversations/${activeConversationId}/messages/${editingDraftId}/approve`, { text: editText })
                        .then(() => {
                          setEditingDraftId(null);
                          queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] });
                          toast({ variant: "success", title: "Edited draft sent" });
                        });
                    }}
                    className="text-xs font-semibold text-white bg-teal-500 hover:bg-teal-600 px-3 py-1.5 rounded-lg transition-colors"
                  >Send</button>
                  <button onClick={() => setEditingDraftId(null)} className="text-xs text-gray-500 hover:text-gray-700 px-3 py-1.5">Cancel</button>
                </div>
              </div>
            )}

            {/* D9: Window-closed blocker — shown instead of composer when 24h window expired */}
            {windowBlocked && (
              <div className="px-4 py-4 border-t border-amber-200 bg-amber-50/60 flex-shrink-0">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <AlertTriangle size={14} className="text-amber-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-amber-800">24-hour service window closed</p>
                    <p className="text-xs text-amber-600 mt-0.5">
                      Free-form messages are not allowed. Send a pre-approved WhatsApp template to re-open the window.
                    </p>
                    <div className="flex gap-2 mt-3">
                      <button
                        onClick={() => {
                          toast({ variant: "info", title: "Template picker", description: "Select a WhatsApp template to send." });
                        }}
                        className="inline-flex items-center gap-1.5 text-xs font-semibold bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 rounded-lg transition-colors"
                      >
                        <LayoutTemplate size={12} />
                        Send template
                      </button>
                      <button
                        onClick={() => { setIsInternalNote(true); }}
                        className="inline-flex items-center gap-1.5 text-xs font-medium text-amber-700 bg-amber-100 hover:bg-amber-200 px-3 py-1.5 rounded-lg transition-colors"
                      >
                        <StickyNote size={12} />
                        Internal note
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Composer — W1, W2, W3, W24, W5 */}
            <div className={cn(
              "px-3 md:px-4 pt-2 pb-2 md:pb-1 border-t flex-shrink-0",
              windowBlocked && !isInternalNote && "hidden",
              isInternalNote ? "border-amber-200 bg-amber-50/40" : "border-gray-100"
            )}>
              {/* W24: internal note banner */}
              {isInternalNote && (
                <div className="flex items-center gap-2 mb-2 px-1">
                  <StickyNote size={12} className="text-amber-500" />
                  <span className="text-xs font-semibold text-amber-700">Internal note — not sent to guest</span>
                  <button onClick={exitInternalNote} className="ml-auto text-amber-400 hover:text-amber-600">
                    <X size={12} />
                  </button>
                </div>
              )}
              {/* W5: reply-to preview */}
              {replyToMsg && (
                <div className="flex items-start gap-2 mb-2 px-1 py-1 bg-gray-100 rounded-lg border-l-2 border-teal-400">
                  <Reply size={11} className="text-teal-500 mt-0.5 flex-shrink-0" />
                  <p className="text-xs text-gray-600 truncate flex-1">{replyToMsg.text}</p>
                  <button onClick={() => setReplyToMsg(null)} className="text-gray-400 hover:text-gray-600 flex-shrink-0">
                    <X size={11} />
                  </button>
                </div>
              )}
              {/* W4: scheduled send banner */}
              {scheduledFor && (
                <div className="flex items-center gap-2 mb-2 px-1 py-1 bg-blue-50 border border-blue-100 rounded-lg">
                  <CalendarClock size={12} className="text-blue-500 flex-shrink-0" />
                  <span className="text-xs text-blue-700 flex-1">
                    Scheduled for {new Date(scheduledFor).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                  </span>
                  <button onClick={() => setScheduledFor(null)} className="text-blue-300 hover:text-blue-600">
                    <X size={11} />
                  </button>
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
                  <div className="absolute bottom-full left-0 mb-1.5 z-30 bg-white border border-gray-200 rounded-xl shadow-lg p-1 min-w-[200px]">
                    <p className="text-[10px] font-semibold text-gray-400 uppercase px-2 py-1">Mention teammate</p>
                    {mentionMatches.map((u: any) => (
                      <button
                        key={u.id}
                        onClick={() => insertMention(u)}
                        className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-gray-50"
                      >
                        <div className="w-6 h-6 rounded-full bg-teal-500 flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0">
                          {u.name?.[0]?.toUpperCase() ?? "?"}
                        </div>
                        <div className="text-left">
                          <p className="text-xs font-medium text-gray-800">{u.name}</p>
                          <p className="text-[10px] text-gray-400 capitalize">{u.role}</p>
                        </div>
                        {onlineUsers.some(o => o.id === u.id) && (
                          <span className="ml-auto w-1.5 h-1.5 rounded-full bg-green-400 flex-shrink-0" />
                        )}
                      </button>
                    ))}
                  </div>
                )}

                {/* W4: schedule dropdown */}
                {showSchedule && (
                  <div className="absolute bottom-full right-0 mb-1.5 z-30 bg-white border border-gray-200 rounded-xl shadow-lg p-1 min-w-[170px]">
                    <p className="text-[10px] font-semibold text-gray-400 uppercase px-2 py-1">Send later</p>
                    {SCHEDULE_OPTIONS.map(opt => (
                      <button
                        key={opt.label}
                        onClick={() => {
                          const iso = opt.getValue();
                          setScheduledFor(iso);
                          setShowSchedule(false);
                        }}
                        className="w-full text-left text-xs px-3 py-1.5 rounded-lg hover:bg-gray-50 text-gray-700"
                      >
                        {opt.label}
                      </button>
                    ))}
                    <div className="border-t border-gray-100 my-1 pt-1 px-2 pb-1">
                      <input
                        type="datetime-local"
                        className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-teal-400"
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
                  className={cn(
                    "flex-1 text-sm border rounded-xl px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:border-transparent resize-none placeholder:text-gray-400 transition-all",
                    isInternalNote
                      ? "bg-amber-50 border-amber-300 focus:ring-amber-300"
                      : "bg-gray-50 border-gray-200 focus:ring-teal-500",
                    emptyPulse && "border-red-300 ring-2 ring-red-200 animate-pulse"
                  )}
                  style={{ minHeight: "42px" }}
                />
                {/* Send button + Schedule dropdown trigger */}
                <div className="flex flex-shrink-0">
                  <button
                    onClick={() => handleSend()}
                    disabled={sendMutation.isPending}
                    className={cn(
                      "h-10 px-3 rounded-l-xl text-white flex items-center justify-center transition-colors",
                      isEmpty
                        ? "bg-gray-300 cursor-not-allowed"
                        : isInternalNote
                        ? "bg-amber-500 hover:bg-amber-600"
                        : scheduledFor
                        ? "bg-blue-600 hover:bg-blue-700"
                        : "bg-[#0B1F3A] hover:bg-[#163458]"
                    )}
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
                      className={cn(
                        "h-10 w-6 rounded-r-xl text-white flex items-center justify-center transition-colors border-l border-white/20",
                        isEmpty ? "bg-gray-300 cursor-not-allowed"
                        : scheduledFor ? "bg-blue-600 hover:bg-blue-700"
                        : "bg-[#0B1F3A] hover:bg-[#163458]"
                      )}
                    >
                      <ChevronDown size={11} />
                    </button>
                  )}
                </div>
              </div>
              {/* W2: helper text */}
              <p className="text-[10px] text-gray-400 mt-1 px-1">
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

      {/* Right: guest mini-card — hidden on mobile */}
      {detail && (
        <div className="hidden md:flex md:flex-col w-64 flex-shrink-0 border-l border-gray-100 overflow-y-auto p-4 space-y-4">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">Guest</p>
            <div className="flex items-center gap-2.5">
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-teal-400 to-blue-500 flex items-center justify-center text-white font-bold flex-shrink-0">
                {detail.guest_name?.[0]?.toUpperCase() ?? "?"}
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900">{detail.guest_name || "Unknown"}</p>
                <p className="text-xs text-gray-500">{detail.guest_phone}</p>
              </div>
            </div>
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">Channel</p>
            <div className="flex items-center gap-2">
              <ChannelIcon channel={detail.channel} />
              <span className="text-sm text-gray-700 capitalize">{detail.channel}</span>
            </div>
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">Status</p>
            <Badge variant={detail.status === "open" ? "success" : "ghost"} className="capitalize">{detail.status}</Badge>
          </div>
          <div className="pt-2 border-t border-gray-100">
            <a
              href={`/dashboard/guests?phone=${encodeURIComponent(detail.guest_phone)}`}
              className="text-xs text-teal-600 hover:text-teal-700 font-medium flex items-center gap-1"
            >
              <User size={12} /> View guest profile →
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
