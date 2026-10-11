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

export function ThreadHeader({
  detail, setMobileView, isOfficialWhatsApp, windowOpen, aiToggleMutation, assignMutation, teamMembers,
  currentUserId, clickToCallMutation, resolveMutation, setShowGuestSheet, setShowSearch, showSnooze,
  setShowSnooze, snoozeMutation,
}: {
  detail?: ConversationDetail;
  setMobileView: (v: "list" | "thread") => void;
  isOfficialWhatsApp: boolean;
  windowOpen: boolean;
  aiToggleMutation: Mut; assignMutation: Mut; clickToCallMutation: Mut; resolveMutation: Mut; snoozeMutation: Mut;
  teamMembers: any[];
  currentUserId: string | null;
  setShowGuestSheet: (v: boolean) => void;
  setShowSearch: (fn: (s: boolean) => boolean) => void;
  showSnooze: boolean;
  setShowSnooze: (fn: (s: boolean) => boolean) => void;
}) {
  return (
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
                  <div className="ibx-avatar flex-shrink-0" style={{ width: 36, height: 36, fontSize: 14 }}>
                    {detail.guest_name?.[0]?.toUpperCase() ?? "?"}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-[15px] font-bold truncate" style={{ color: "var(--haip-fg)" }}>{detail.guest_name || detail.guest_phone}</span>
                      {/* Messaging-window countdown (official WhatsApp only -- the one channel that enforces it here) */}
                      {isOfficialWhatsApp && detail.last_inbound_at && (
                        windowOpen ? (
                          <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)] flex-shrink-0">
                            <Timer size={10} />
                            {formatWindowCountdown(getWindowSecondsLeft(detail.last_inbound_at))} to reply
                          </span>
                        ) : (
                          <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)] flex-shrink-0">
                            <AlertTriangle size={10} /> Template required
                          </span>
                        )
                      )}
                    </div>
                    <div className="mt-0.5">
                      {/* Every channel this guest has talked to us on */}
                      <TalkedOn
                        size={14}
                        channels={detail.guest_channels?.length
                          ? detail.guest_channels
                          : (toGuestChannel(detail.channel) ? [toGuestChannel(detail.channel)!] : [])}
                      />
                    </div>
                  </div>

                  {/* Pause / resume the AI for this one guest */}
                  <button
                    type="button"
                    onClick={() => aiToggleMutation.mutate(!(detail.ai_enabled ?? true))}
                    disabled={aiToggleMutation.isPending}
                    role="switch"
                    aria-checked={detail.ai_enabled ?? true}
                    title={(detail.ai_enabled ?? true) ? "AI is replying to this guest -- click to pause" : "AI is paused for this guest -- click to resume"}
                    className={cn(
                      "hidden sm:inline-flex items-center gap-2 text-xs font-bold px-2.5 py-1.5 rounded-lg transition-colors disabled:opacity-60",
                      (detail.ai_enabled ?? true) ? "bg-primary/10 text-primary" : "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)]",
                    )}
                  >
                    <span className={cn("relative w-7 h-4 rounded-full transition-colors", (detail.ai_enabled ?? true) ? "bg-primary" : "bg-[var(--haip-border-strong)]")}>
                      <span className={cn("absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all", (detail.ai_enabled ?? true) ? "left-3.5" : "left-0.5")} />
                    </span>
                    AI replies
                  </button>

                  {/* Owner */}
                  <select
                    value={detail.assigned_to ?? ""}
                    onChange={e => assignMutation.mutate(e.target.value || null)}
                    aria-label="Owner"
                    className="hidden md:block text-xs font-semibold px-2 py-1.5 rounded-lg border outline-none max-w-[140px]"
                    style={{ borderColor: "var(--haip-border)", background: "var(--haip-card)", color: "var(--haip-fg)" }}
                  >
                    <option value="">Unassigned</option>
                    {(teamMembers as any[]).map((u: any) => (
                      <option key={u.id} value={u.id}>{u.id === currentUserId ? `${u.name} (me)` : u.name}</option>
                    ))}
                  </select>

                  {/* Call -- IVR click-to-call: the agent's phone rings, then bridges to the guest */}
                  {detail.guest_phone && (
                    <button
                      type="button"
                      onClick={() => clickToCallMutation.mutate(detail.guest_phone)}
                      disabled={clickToCallMutation.isPending}
                      className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-60 flex-shrink-0"
                    >
                      {clickToCallMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Phone size={13} />}
                      Call
                    </button>
                  )}

                  {/* Resolve */}
                  <button
                    type="button"
                    onClick={() => resolveMutation.mutate()}
                    disabled={resolveMutation.isPending || detail.status === "resolved"}
                    title={detail.status === "resolved" ? "Resolved" : "Mark resolved"}
                    aria-label="Mark resolved"
                    className="hidden sm:flex w-8 h-8 rounded-lg border items-center justify-center text-[var(--haip-status-success-fg)] hover:bg-[var(--haip-status-success-bg)] disabled:opacity-40"
                    style={{ borderColor: "var(--haip-border)" }}
                  >
                    <Check size={15} />
                  </button>

                  {/* Guest 360 -- mobile opens it as a sheet */}
                  <button
                    onClick={() => setShowGuestSheet(true)}
                    className="md:hidden w-8 h-8 rounded-lg flex items-center justify-center transition-colors duration-150 hover:bg-muted"
                    style={{ color: "var(--haip-fg-subtle)" }}
                    title="Guest details"
                    aria-label="Guest details"
                  >
                    <User size={14} />
                  </button>
                  {/* Search messages -- desktop */}
                  <button
                    onClick={() => setShowSearch(s => !s)}
                    className="hidden md:flex w-8 h-8 rounded-lg items-center justify-center transition-colors duration-150 hover:bg-muted"
                    style={{ color: "var(--haip-fg-subtle)" }}
                    title="Search messages"
                    aria-label="Search messages"
                  >
                    <Search size={14} />
                  </button>
                  {/* Snooze -- desktop */}
                  <div className="relative hidden md:block">
                    <button
                      onClick={() => setShowSnooze(s => !s)}
                      className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors duration-150 hover:bg-muted"
                      style={{ color: "var(--haip-fg-subtle)" }}
                      title="Snooze conversation"
                      aria-label="Snooze conversation"
                    >
                      <BellOff size={14} />
                    </button>
                    {showSnooze && (
                      <div className="absolute top-full right-0 mt-1 z-20 rounded-xl shadow-md overflow-hidden w-44" style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)" }}>
                        {[
                          { label: "3 hours", hours: 3 },
                          { label: "Until tomorrow", hours: 18 },
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
                </>
              ) : <Skeleton className="h-6 w-48" />}
            </div>
  );
}
