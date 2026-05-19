"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Send, Sparkles, User, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { ConversationList } from "@/components/inbox/ConversationList";
import { MessageBubble } from "@/components/inbox/MessageBubble";
import { SavedReplyMenu } from "@/components/inbox/SavedReplyMenu";
import { TypingDots } from "@/components/inbox/TypingDots";
import { ChannelIcon } from "@/components/inbox/ChannelIcon";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useInboxStore } from "@/store/inbox";
import { useInboxStream } from "@/hooks/useInboxStream";
import { useAutoGrow } from "@/hooks/useAutoGrow";
import { useToast } from "@/components/ui/toast";

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
}

interface ConversationDetail {
  id: string;
  guest_name?: string;
  guest_phone: string;
  channel: string;
  status: "open" | "resolved" | "snoozed";
  messages: Message[];
}

const CHANNEL_FILTERS = [
  { value: "",          label: "All" },
  { value: "whatsapp",  label: "WhatsApp" },
  { value: "instagram", label: "Instagram" },
  { value: "web",       label: "Web" },
];

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

  const [channelFilter, setChannelFilter] = useState("");
  const [replyText, setReplyText] = useState("");
  const [aiTyping, setAiTyping] = useState(false);
  const [editingDraftId, setEditingDraftId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [emptyPulse, setEmptyPulse] = useState(false);
  const [showSavedReplies, setShowSavedReplies] = useState(false);
  const [savedReplyQuery, setSavedReplyQuery] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useAutoGrow(textareaRef, replyText, 6);

  const isEmpty = replyText.trim().length === 0;

  const { isLoading: listLoading } = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api.get("/conversations").then(r => r.data),
    onSuccess: (data: any[]) => setConversations(data),
  } as any);

  const { data: detail, isLoading: detailLoading } = useQuery<ConversationDetail>({
    queryKey: ["conversation", activeConversationId],
    queryFn: () => api.get(`/conversations/${activeConversationId}`).then(r => r.data),
    enabled: !!activeConversationId,
    onSuccess: () => { if (activeConversationId) markRead(activeConversationId); },
  } as any);

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
    mutationFn: (text: string) =>
      api.post(`/conversations/${activeConversationId}/messages`, { text, direction: "outbound" }),
    onSuccess: () => {
      setReplyText("");
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

  const handleSend = () => {
    if (isEmpty) { triggerEmptyPulse(); return; }
    if (!activeConversationId) return;
    sendMutation.mutate(replyText.trim());
  };

  // W3: "/" in composer opens saved-reply menu
  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setReplyText(val);
    if (val === "/" || val.startsWith("/")) {
      setShowSavedReplies(true);
      setSavedReplyQuery(val.slice(1));
    } else {
      setShowSavedReplies(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Cmd+Enter / Ctrl+Enter also sends (X2)
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleSend(); return; }
    // Plain Enter sends; Shift+Enter inserts newline (W2)
    if (e.key === "Enter" && !e.shiftKey) {
      if (showSavedReplies) return; // let SavedReplyMenu handle Enter
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="h-full flex overflow-hidden bg-white">
      {/* Left: conversation list */}
      <div className="w-72 flex-shrink-0 border-r border-gray-100 flex flex-col">
        <div className="px-3 py-2.5 border-b border-gray-100">
          <div className="flex gap-1 overflow-x-auto">
            {CHANNEL_FILTERS.map(f => (
              <button
                key={f.value}
                onClick={() => setChannelFilter(f.value)}
                className={cn(
                  "flex-shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors",
                  channelFilter === f.value ? "bg-teal-500 text-white" : "text-gray-500 hover:bg-gray-100"
                )}
              >
                {f.value && <ChannelIcon channel={f.value} className="w-3.5 h-3.5" />}
                {f.label}
              </button>
            ))}
          </div>
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
            onSelect={id => setActiveConversation(id)}
            channelFilter={channelFilter || undefined}
            className="flex-1"
          />
        )}
      </div>

      {/* Center: message thread */}
      <div className="flex-1 flex flex-col overflow-hidden">
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
            <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-3 flex-shrink-0">
              {detail ? (
                <>
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-teal-400 to-blue-500 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
                    {detail.guest_name?.[0]?.toUpperCase() ?? "?"}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-gray-900">{detail.guest_name || detail.guest_phone}</div>
                    <div className="flex items-center gap-1.5">
                      <ChannelIcon channel={detail.channel} className="w-4 h-4" />
                      <span className="text-xs text-gray-400 capitalize">{detail.channel}</span>
                      <Badge variant={detail.status === "open" ? "success" : "ghost"} className="text-[10px] py-0 h-4">{detail.status}</Badge>
                    </div>
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

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
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
                      aiConfidence={msg.ai_confidence}
                      senderName={msg.direction === "outbound" ? msg.sender_name : (detail.guest_name || detail.guest_phone)}
                      onApprove={(id) => approveMutation.mutate(id)}
                      onEdit={(id, text) => { setEditingDraftId(id); setEditText(text); }}
                      onReject={(id) => {
                        api.post(`/conversations/${activeConversationId}/messages/${id}/reject`, {}).catch(() => {});
                        queryClient.invalidateQueries({ queryKey: ["conversation", activeConversationId] });
                      }}
                      onRetry={(id) => retryMutation.mutate({ conversationId: activeConversationId!, messageId: id })}
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

            {/* Composer — W1, W2, W3 */}
            <div className="px-4 pt-2 pb-1 border-t border-gray-100 flex-shrink-0">
              <div className="relative flex gap-2 items-end">
                {/* W3: SavedReplyMenu */}
                {showSavedReplies && (
                  <SavedReplyMenu
                    query={savedReplyQuery}
                    context={{
                      guest_name: detail?.guest_name,
                    }}
                    onSelect={(resolved) => {
                      setReplyText(resolved);
                      setShowSavedReplies(false);
                      textareaRef.current?.focus();
                    }}
                    onClose={() => setShowSavedReplies(false)}
                    anchorRef={textareaRef}
                  />
                )}
                <textarea
                  ref={textareaRef}
                  value={replyText}
                  onChange={handleTextChange}
                  onKeyDown={handleKeyDown}
                  rows={1}
                  placeholder="Type a message or / for saved replies…"
                  className={cn(
                    "flex-1 text-sm border rounded-xl px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent resize-none bg-gray-50 placeholder:text-gray-400 transition-all",
                    // W1: pulse on empty send attempt
                    emptyPulse ? "border-red-300 ring-2 ring-red-200 animate-pulse" : "border-gray-200"
                  )}
                  style={{ minHeight: "42px" }}
                />
                <button
                  onClick={handleSend}
                  disabled={sendMutation.isPending}
                  className={cn(
                    "w-10 h-10 rounded-xl text-white flex items-center justify-center flex-shrink-0 transition-colors",
                    // W1: visually distinct when empty (no opacity trick — just color shift)
                    isEmpty
                      ? "bg-gray-300 cursor-not-allowed"
                      : "bg-[#0B1F3A] hover:bg-[#163458]"
                  )}
                  aria-label="Send message"
                >
                  {sendMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                </button>
              </div>
              {/* W2: helper text */}
              <p className="text-[10px] text-gray-400 mt-1 px-1">
                Enter to send · Shift+Enter for newline · / for saved replies
              </p>
            </div>
          </>
        )}
      </div>

      {/* Right: guest mini-card */}
      {detail && (
        <div className="w-64 flex-shrink-0 border-l border-gray-100 overflow-y-auto p-4 space-y-4">
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
