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

export function ThreadSearch({
  showSearch, searchQ, setSearchQ, setShowSearch, searchLoading, searchResults, setActiveConversation,
}: {
  showSearch: boolean; searchQ: string; setSearchQ: (v: string) => void; setShowSearch: (v: boolean) => void;
  searchLoading: boolean; searchResults: any[]; setActiveConversation: (id: string) => void;
}) {
  return (
    <>
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
    </>
  );
}
