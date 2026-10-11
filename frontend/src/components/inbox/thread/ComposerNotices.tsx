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

export function ComposerNotices({
  isVoiceOnly, windowBlocked, setShowTemplatePicker, setIsInternalNote,
}: {
  isVoiceOnly: boolean; windowBlocked: boolean;
  setShowTemplatePicker: (v: boolean) => void; setIsInternalNote: (v: boolean) => void;
}) {
  return (
    <>
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
    </>
  );
}
