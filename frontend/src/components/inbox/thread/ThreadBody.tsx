"use client";
import type { RefObject } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Send, Sparkles, Loader2, BellOff, Search, X, StickyNote, Reply, ChevronDown, ChevronLeft, ChevronRight, CalendarClock, Timer, AlertTriangle, LayoutTemplate, Phone, Languages, Wand2, User, Check } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { TalkedOn, ChannelBadge, toGuestChannel } from "@/components/inbox/ChannelBadges";
import { ChannelIcon, channelLabel } from "@/components/inbox/ChannelIcon";
import { MessageBubble } from "@/components/inbox/MessageBubble";
import { SavedReplyMenu } from "@/components/inbox/SavedReplyMenu";
import { TypingDots } from "@/components/inbox/TypingDots";
import { CallLogCard, type CallTimelineItem } from "@/components/inbox/CallLogCard";
import { ConversationList, type InboxView } from "@/components/inbox/ConversationList";
import {
  type Message, type ConversationDetail, type TimelineCallItem, type Mut,
  getWindowSecondsLeft, formatWindowCountdown, COMPOSER_REWRITE_LANGUAGES, COMPOSER_REWRITE_TONES,
  CHANNEL_FILTERS, SCHEDULE_OPTIONS,
} from "./types";

export function ThreadBody({
  detail, detailLoading, olderMessages, hasMoreOlderMessages, loadOlderMessages, loadingOlderMessages, callItems,
  handleApprove, handleReject, handleRetry, setEditingDraftId, setEditText, setReplyToMsg, textareaRef,
  rewriteDraft, rewritingMessageId, aiTyping, bottomRef,
}: {
  detail?: ConversationDetail; detailLoading: boolean;
  olderMessages: Message[]; hasMoreOlderMessages: boolean; loadOlderMessages: () => void; loadingOlderMessages: boolean;
  callItems: TimelineCallItem[];
  handleApprove: (id: string) => void; handleReject: (id: string) => void; handleRetry: (id: string) => void;
  setEditingDraftId: (id: string | null) => void; setEditText: (t: string) => void;
  setReplyToMsg: (m: Message | null) => void;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  rewriteDraft: Mut; rewritingMessageId: string | null;
  aiTyping: boolean; bottomRef: RefObject<HTMLDivElement | null>;
}) {
  // Thread body sits a shade below the white pane so the message column reads as its own surface
  // (prototype .thread-body). --haip-surface, not a literal gradient: it resolves to #F8FAFC in light
  // and the page bg in dark, so this doesn't invert.
  return (
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
                    // Real bug, reported live: a rejected AI draft
                    // (was_approved=false) fell out of isAiDraft's gate
                    // (which only checks was_approved == null) and rendered
                    // as an ordinary outbound bubble -- same green styling,
                    // same checkmark treatment -- with nothing distinguishing
                    // it from a message that was actually delivered. It was
                    // never sent to the guest at all, so showing it in the
                    // thread as if it were is actively misleading to
                    // whoever's reading the conversation. Excluded entirely
                    // rather than given a "rejected" visual treatment --
                    // there's nothing useful about seeing a reply that never
                    // reached the guest sitting in their conversation history.
                    const msgs = [...olderMessages, ...(detail?.messages ?? [])]
                      .filter(m => !(m.ai_drafted && m.direction === "outbound" && m.was_approved === false));
                    // Interleave calls (ticket 2) by timestamp -- messages
                    // keep their own tested render path, calls are spliced
                    // in purely for chronological display.
                    type Row = { key: string; at: number } & (
                      | { kind: "message"; msg: Message }
                      | { kind: "call"; call: CallTimelineItem }
                      | { kind: "date"; label: string }
                    );
                    const rows: Row[] = [
                      ...msgs.map(m => ({ key: `m-${m.id}`, at: new Date(m.timestamp).getTime(), kind: "message" as const, msg: m })),
                      ...callItems.map(c => ({ key: `c-${c.call.id}`, at: new Date(c.occurred_at).getTime(), kind: "call" as const, call: c.call })),
                    ].sort((a, b) => a.at - b.at);

                    // Insert a date separator before the first row of each
                    // calendar day -- without this, a message from a week
                    // ago and one from just now show identical bare times
                    // ("10:23 am") with nothing marking the gap between
                    // them, which is exactly what read like "this whole
                    // thread happened today" for an old conversation with
                    // one recent reply spliced in.
                    const withDates: Row[] = [];
                    let lastDateKey = "";
                    for (const row of rows) {
                      const d = new Date(row.at);
                      const dateKey = d.toDateString();
                      if (dateKey !== lastDateKey) {
                        lastDateKey = dateKey;
                        const today = new Date();
                        const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
                        const label =
                          dateKey === today.toDateString() ? "Today" :
                          dateKey === yesterday.toDateString() ? "Yesterday" :
                          d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: d.getFullYear() !== today.getFullYear() ? "numeric" : undefined });
                        withDates.push({ key: `date-${dateKey}`, at: row.at, kind: "date", label });
                      }
                      withDates.push(row);
                    }

                    return withDates.map(row => row.kind === "date" ? (
                      <div key={row.key} className="flex justify-center my-2">
                        <span
                          className="text-[11px] font-medium px-2.5 py-1 rounded-full"
                          style={{ background: "var(--haip-card)", color: "var(--haip-fg-subtle)", border: "1px solid var(--haip-border)" }}
                        >
                          {row.label}
                        </span>
                      </div>
                    ) : row.kind === "call" ? (
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
                        isAiDraft={!!(row.msg.ai_drafted && row.msg.direction === "outbound" && row.msg.was_approved == null)}
                        isInternal={row.msg.is_internal}
                        aiConfidence={row.msg.ai_confidence}
                        senderName={row.msg.direction === "outbound" ? row.msg.sender_name : (detail?.guest_name || detail?.guest_phone)}
                        channel={row.msg.channel}
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
  );
}
