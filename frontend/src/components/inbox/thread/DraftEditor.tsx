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

export function DraftEditor({
  editingDraftId, editText, setEditText, setEditingDraftId, activeConversationId,
}: {
  editingDraftId: string | null; editText: string; setEditText: (t: string) => void;
  setEditingDraftId: (id: string | null) => void; activeConversationId: string | null;
}) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return (
    <>
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
    </>
  );
}
