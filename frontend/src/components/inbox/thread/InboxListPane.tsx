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

export function InboxListPane({
  mobileView, setMobileView, onlineUsers, savedViews, setActiveView, activeView, displayConversations, scopedFeed,
  conversations, listLoading, activeConversationId, setActiveConversation, inboxView, setInboxView, viewCounts,
  channelFilter, setChannelFilter, hasMoreConversations, fetchNextConversationPage, isLoadingMoreConversations,
  clickToCallMutation,
}: {
  mobileView: "list" | "thread"; setMobileView: (v: "list" | "thread") => void;
  onlineUsers: { id: string; name: string; role: string }[];
  savedViews: any[]; setActiveView: (fn: (av: string | null) => string | null) => void; activeView: string | null;
  displayConversations: any[] | undefined; scopedFeed: boolean; conversations: any[];
  listLoading: boolean; activeConversationId: string | null; setActiveConversation: (id: string) => void;
  inboxView: InboxView; setInboxView: (v: InboxView) => void;
  viewCounts: { needs_reply: number; unassigned: number; mine: number } | undefined;
  channelFilter: string; setChannelFilter: (v: string) => void;
  hasMoreConversations: boolean | undefined; fetchNextConversationPage: () => void; isLoadingMoreConversations: boolean;
  clickToCallMutation: Mut;
}) {
  const queryClient = useQueryClient();
  return (
      <div className={cn(
        "flex-col bg-card",
        "border-r",
        mobileView === "list" ? "flex w-full" : "hidden",
        "md:flex md:w-[340px] md:flex-shrink-0",
      )}
        style={{ borderColor: "var(--haip-border)" }}
      >
        {/* W18: online agents indicator */}
        {onlineUsers.length > 0 && (
          <div className="hidden md:flex px-3 py-1.5 items-center gap-1.5" style={{ borderBottom: "1px solid var(--haip-border)" }}>
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--haip-status-success-fg)] flex-shrink-0" />
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
        {savedViews.length > 0 && (
          <div className="px-3 py-2" style={{ borderBottom: "1px solid var(--haip-border)" }}>
            <p className="text-[10px] font-medium uppercase tracking-widest mb-1.5" style={{ color: "var(--haip-fg-subtle)" }}>Saved views</p>
            <div className="space-y-0.5">
              {savedViews.map((v: any) => (
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

        <ConversationList
            conversations={displayConversations ?? (scopedFeed ? [] : conversations)}
            isLoading={listLoading}
            activeId={activeConversationId}
            onSelect={id => { setActiveConversation(id); setMobileView("thread"); }}
            view={inboxView}
            onViewChange={setInboxView}
            counts={viewCounts}
            channelFilter={channelFilter}
            channelOptions={CHANNEL_FILTERS}
            onChannelChange={setChannelFilter}
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
            onCall={guestNumber => clickToCallMutation.mutate(guestNumber)}
            callingNumber={clickToCallMutation.isPending ? (clickToCallMutation.variables ?? null) : null}
          />
      </div>
  );
}
