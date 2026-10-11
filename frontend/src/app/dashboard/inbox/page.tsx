"use client";
import { useState, useRef, useEffect, useCallback, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { useQuery, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Send, Sparkles } from "@/lib/icons";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { type InboxView } from "@/components/inbox/ConversationList";

import { PhoneDeclineCallout } from "@/components/inbox/PhoneDeclineCallout";

import { GuestPanel } from "@/components/inbox/GuestPanel";
import { PinnedInquiryBanner } from "@/components/inbox/PinnedInquiryBanner";

import type { RecommendedAction } from "@/components/ai/AIRecommendationCard";

import { useInboxStore } from "@/store/inbox";
import { useAutoGrow } from "@/hooks/useAutoGrow";
import { ThreadHeader } from "@/components/inbox/thread/ThreadHeader";
import { ThreadSearch } from "@/components/inbox/thread/ThreadSearch";
import { ThreadBody } from "@/components/inbox/thread/ThreadBody";
import { DraftEditor } from "@/components/inbox/thread/DraftEditor";
import { ComposerNotices } from "@/components/inbox/thread/ComposerNotices";
import { Composer } from "@/components/inbox/thread/Composer";
import { InboxListPane } from "@/components/inbox/thread/InboxListPane";
import { type Message, type ConversationDetail, type TimelineItem, type TimelineCallItem, getWindowSecondsLeft } from "@/components/inbox/thread/types";
import { useToast } from "@/components/ui/toast";
import { usePresence } from "@/hooks/usePresence";
// B5: only needed once the user opens the template picker (WhatsApp window
// re-open flow) -- keep it out of this route's initial chunk.
const TemplatePickerModal = dynamic(
  () => import("@/components/inbox/TemplatePickerModal").then(m => m.TemplatePickerModal),
  { ssr: false }
);



// ─── Page ─────────────────────────────────────────────────────────────────────

function InboxPageInner() {
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

  // Deep link from outside the inbox (Worklist's "Open" button, a lead
  // card, a search result) -- e.g. /dashboard/inbox?conversation=<id>.
  // Confirmed live: this page never read the param at all, so "Open"
  // always landed on the inbox's default view instead of the actual
  // thread. Applied once per id (not on every render) so a manual
  // selection afterward isn't clobbered back to the link target if the
  // param is still sitting in the URL.
  const searchParams = useSearchParams();
  const deepLinkConversationId = searchParams.get("conversation");
  const appliedDeepLinkRef = useRef<string | null>(null);
  useEffect(() => {
    if (deepLinkConversationId && appliedDeepLinkRef.current !== deepLinkConversationId) {
      appliedDeepLinkRef.current = deepLinkConversationId;
      setActiveConversation(deepLinkConversationId);
      setMobileView("thread");
    }
  }, [deepLinkConversationId, setActiveConversation]);

  // Mobile: single-panel navigation ("list" | "thread")
  const [mobileView, setMobileView] = useState<"list" | "thread">("list");
  // Guest 360 panel is desktop-only (hidden md:flex on GuestPanel) -- on
  // mobile it opens as a sheet from the thread header instead.
  const [showGuestSheet, setShowGuestSheet] = useState(false);

  const [channelFilter, setChannelFilter] = useState("");
  // Filter chip (Needs reply / Unassigned / Mine / All) -- applied
  // server-side, so it covers the whole inbox, not just the loaded page.
  const [inboxView, setInboxView] = useState<InboxView>("");
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

  // "personal_whatsapp" isn't a real ChannelType -- it's this UI's tab for
  // Conversation.source="personal_bridge" rows, which all carry
  // channel="whatsapp". Translate the tab selection into the real params
  // the backend understands (see conversations.py's list_conversations).
  function channelQueryParams(filterValue: string): { channel?: string; source?: string } {
    if (filterValue === "personal_whatsapp") {
      return { channel: "whatsapp", source: "personal_bridge" };
    }
    return { channel: filterValue };
  }

  // Always-unfiltered feed: source of truth for useInboxStore (Sidebar's
  // unread badge etc. read the global store, not whatever's currently
  // rendered here) and what's shown when channelFilter === "" ("All").
  const {
    data: allConversationPages,
    isLoading: allListLoading,
    fetchNextPage: fetchNextAllPage,
    hasNextPage: hasMoreAllConversations,
    isFetchingNextPage: isLoadingMoreAllConversations,
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

  // Channel-scoped feed, only fetched while a channel tab is selected.
  //
  // Previously channelFilter was applied purely client-side (filtering
  // whatever the unfiltered fetch above happened to have loaded), while
  // that fetch always pulled the 50 most recent conversations across EVERY
  // channel with no channel param at all. As newer Instagram/call/other
  // traffic filled those 50 slots, older WhatsApp (or any other channel's)
  // conversations fell out of the loaded window entirely -- and with
  // "Load more" hidden whenever a channel filter was active (see
  // ConversationList.tsx), there was no way to ever bring them back. A
  // WhatsApp tab showing "2 chats" while more genuinely existed was this,
  // not a data problem. This queries the backend's own channel filter
  // (conversations.py already supported `channel=`) instead.
  const {
    data: filteredConversationPages,
    isLoading: filteredListLoading,
    fetchNextPage: fetchNextFilteredPage,
    hasNextPage: hasMoreFilteredConversations,
    isFetchingNextPage: isLoadingMoreFilteredConversations,
  } = useInfiniteQuery({
    queryKey: ["conversations", channelFilter, inboxView],
    queryFn: ({ pageParam }: { pageParam?: string }) =>
      api.get("/conversations", {
        params: {
          limit: CONVERSATION_PAGE_SIZE,
          ...(channelFilter ? channelQueryParams(channelFilter) : {}),
          ...(inboxView ? { view: inboxView } : {}),
          ...(pageParam ? { before: pageParam } : {}),
        },
      }).then(r => r.data as any[]),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.length === CONVERSATION_PAGE_SIZE
        ? lastPage[lastPage.length - 1]?.last_message_at
        : undefined,
    enabled: !!channelFilter || !!inboxView,
    staleTime: 30_000,
  });

  const scopedFeed = !!channelFilter || !!inboxView;
  const { data: viewCounts } = useQuery<{ needs_reply: number; unassigned: number; mine: number }>({
    queryKey: ["conversations", "counts"],
    queryFn: () => api.get("/conversations/counts").then(r => r.data),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const listLoading = scopedFeed ? filteredListLoading : allListLoading;
  const fetchNextConversationPage = scopedFeed ? fetchNextFilteredPage : fetchNextAllPage;
  const hasMoreConversations = scopedFeed ? hasMoreFilteredConversations : hasMoreAllConversations;
  const isLoadingMoreConversations = scopedFeed ? isLoadingMoreFilteredConversations : isLoadingMoreAllConversations;

  // HOTFIX (production incident): .flat() on every render produced a new
  // array reference each time even when the underlying pages hadn't
  // changed, so the effect below never saw a stable dependency -- it fired
  // every render, called setConversations, which re-rendered this
  // component, which called .flat() again... "Maximum update depth
  // exceeded" (React error #185), infinite loop, whole Inbox page down in
  // prod. useMemo keyed on the pages (react-query's own stable reference,
  // unchanged unless the query result actually changed) fixes it.
  const allConversationData = useMemo(
    () => allConversationPages?.pages.flat(),
    [allConversationPages]
  );
  const filteredConversationData = useMemo(
    () => filteredConversationPages?.pages.flat(),
    [filteredConversationPages]
  );
  const displayConversations = scopedFeed ? filteredConversationData : allConversationData;

  // onSuccess was removed in TanStack Query v5 — use useEffect to sync store.
  // Always synced from the unfiltered feed, never the channel-scoped one, so
  // switching to a channel tab doesn't clobber the global store other UI
  // (Sidebar's unread badge) reads from.
  useEffect(() => {
    if (allConversationData) setConversations(allConversationData);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allConversationData]);

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
  // The 24h service window is a WhatsApp Cloud API concept -- the personal
  // bridge (whatsmeow) has no such window and doesn't send through HAIP at
  // all yet (Phase 1 read-only), so showing a countdown here is meaningless.
  const isOfficialWhatsApp = isWhatsApp && detail?.source !== "personal_bridge";
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

  // Header actions (Inbox redesign): pause/resume AI for this guest, change
  // owner, resolve. All go through PATCH /conversations/{id}.
  const patchConversation = (body: Record<string, unknown>) =>
    api.patch(`/conversations/${activeConversationId}`, body).then(r => r.data);
  const refreshConversation = () => {
    queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] });
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
  };
  const patchError = (title: string) => (e: unknown) => {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    toast({ variant: "error", title, description: typeof msg === "string" ? msg : "Please try again." });
  };
  const aiToggleMutation = useMutation({
    mutationFn: (ai_enabled: boolean) => patchConversation({ ai_enabled }),
    onSuccess: (_, on) => {
      refreshConversation();
      toast({ variant: "success", title: on ? "AI replies resumed" : "AI paused for this guest" });
    },
    onError: patchError("Couldn't change AI replies"),
  });
  const assignMutation = useMutation({
    mutationFn: (assigned_to: string | null) => patchConversation({ assigned_to }),
    onSuccess: () => { refreshConversation(); toast({ variant: "success", title: "Owner updated" }); },
    onError: patchError("Couldn't change owner"),
  });
  const resolveMutation = useMutation({
    mutationFn: () => patchConversation({ is_open: false }),
    onSuccess: () => { refreshConversation(); toast({ variant: "success", title: "Marked resolved" }); },
    onError: patchError("Couldn't resolve"),
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

  // W25: @mention — fetch team members. /users is owner/manager-only and
  // 403s for every other role, which silently emptied @mention for anyone
  // else -- /users/lite is name-only but open to any authenticated role.
  const { data: teamMembers = [] } = useQuery({
    queryKey: ["users-lite"],
    queryFn: () => api.get("/users/lite").then(r => r.data),
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
    <div className="haip-inbox-v2 h-full flex overflow-hidden">
      {/* Left: conversation list — full-width on mobile when mobileView==="list", sidebar on md+ */}
      <InboxListPane
        mobileView={mobileView} setMobileView={setMobileView} onlineUsers={onlineUsers}
        savedViews={savedViews as any[]} setActiveView={setActiveView} activeView={activeView}
        displayConversations={displayConversations} scopedFeed={scopedFeed} conversations={conversations}
        listLoading={listLoading} activeConversationId={activeConversationId} setActiveConversation={setActiveConversation}
        inboxView={inboxView} setInboxView={setInboxView} viewCounts={viewCounts}
        channelFilter={channelFilter} setChannelFilter={setChannelFilter}
        hasMoreConversations={hasMoreConversations} fetchNextConversationPage={() => fetchNextConversationPage()}
        isLoadingMoreConversations={isLoadingMoreConversations} clickToCallMutation={clickToCallMutation}
      />

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
            <ThreadHeader
              detail={detail} setMobileView={setMobileView} isOfficialWhatsApp={isOfficialWhatsApp} windowOpen={windowOpen}
              aiToggleMutation={aiToggleMutation} assignMutation={assignMutation} teamMembers={teamMembers as any[]}
              currentUserId={currentUserId} clickToCallMutation={clickToCallMutation} resolveMutation={resolveMutation}
              setShowGuestSheet={setShowGuestSheet} setShowSearch={setShowSearch} showSnooze={showSnooze}
              setShowSnooze={setShowSnooze} snoozeMutation={snoozeMutation}
            />


            {/* Phone-decline alert plan: sits above the AI draft strip, same
                position as the approved mockup. */}
            {detail?.phone_decline_task && (
              <PhoneDeclineCallout conversationId={detail.id} task={detail.phone_decline_task} />
            )}

            {/* HAIP Inbox UI-fidelity pass, ticket 5: pinned-inquiry banner
                (dates/guests/budget + lead score) above the thread. */}
            <PinnedInquiryBanner inquiryId={detail?.inquiry_id ?? null} />

            <ThreadSearch
              showSearch={showSearch} searchQ={searchQ} setSearchQ={setSearchQ} setShowSearch={setShowSearch}
              searchLoading={searchLoading} searchResults={searchResults as any[]} setActiveConversation={setActiveConversation}
            />

            <ThreadBody
              detail={detail} detailLoading={detailLoading} olderMessages={olderMessages}
              hasMoreOlderMessages={hasMoreOlderMessages} loadOlderMessages={loadOlderMessages}
              loadingOlderMessages={loadingOlderMessages} callItems={callItems}
              handleApprove={handleApprove} handleReject={handleReject} handleRetry={handleRetry}
              setEditingDraftId={setEditingDraftId} setEditText={setEditText} setReplyToMsg={setReplyToMsg}
              textareaRef={textareaRef} rewriteDraft={rewriteDraft} rewritingMessageId={rewritingMessageId}
              aiTyping={aiTyping} bottomRef={bottomRef}
            />

            <DraftEditor
              editingDraftId={editingDraftId} editText={editText} setEditText={setEditText}
              setEditingDraftId={setEditingDraftId} activeConversationId={activeConversationId}
            />

            <ComposerNotices
              isVoiceOnly={isVoiceOnly} windowBlocked={windowBlocked}
              setShowTemplatePicker={setShowTemplatePicker} setIsInternalNote={setIsInternalNote}
            />

            <Composer
              isVoiceOnly={isVoiceOnly} windowBlocked={windowBlocked} isInternalNote={isInternalNote}
              exitInternalNote={exitInternalNote} replyToMsg={replyToMsg} setReplyToMsg={setReplyToMsg}
              scheduledFor={scheduledFor} setScheduledFor={setScheduledFor} replyText={replyText} setReplyText={setReplyText}
              isEmpty={isEmpty} emptyPulse={emptyPulse} isComposerRewriting={isComposerRewriting}
              showComposerTonePicker={showComposerTonePicker} setShowComposerTonePicker={setShowComposerTonePicker}
              showComposerLangPicker={showComposerLangPicker} setShowComposerLangPicker={setShowComposerLangPicker}
              composerRewrite={composerRewrite} showSavedReplies={showSavedReplies} setShowSavedReplies={setShowSavedReplies}
              savedReplyQuery={savedReplyQuery} detail={detail} textareaRef={textareaRef} mentionQuery={mentionQuery}
              mentionMatches={mentionMatches} insertMention={insertMention} onlineUsers={onlineUsers}
              showSchedule={showSchedule} setShowSchedule={setShowSchedule} handleTextChange={handleTextChange}
              handleKeyDown={handleKeyDown} handleSend={handleSend} sendMutation={sendMutation}
            />
          </>
        )}
      </div>

      {/* Right: Guest 360 panel — hidden on mobile (see mobile sheet below) */}
      {detail && <GuestPanel detail={detail} />}

      {/* Mobile: Guest 360 as a sheet instead of a permanent panel */}
      <Sheet open={showGuestSheet} onOpenChange={setShowGuestSheet}>
        <SheetContent side="right" className="haip-inbox-v2 p-0 w-[85vw] sm:max-w-sm">
          {detail && <GuestPanel detail={detail} mobileVariant />}
        </SheetContent>
      </Sheet>

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

// useSearchParams (for the ?conversation= deep link, see InboxPageInner)
// requires a Suspense boundary around any Client Component that calls it,
// or a static production build fails with "Missing Suspense boundary with
// useSearchParams".
export default function InboxPage() {
  return (
    <Suspense fallback={<div className="h-full" style={{ background: "var(--haip-bg, transparent)" }} />}>
      <InboxPageInner />
    </Suspense>
  );
}
