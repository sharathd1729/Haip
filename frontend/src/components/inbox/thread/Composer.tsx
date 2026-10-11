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

export function Composer({
  isVoiceOnly, windowBlocked, isInternalNote, exitInternalNote, replyToMsg, setReplyToMsg, scheduledFor, setScheduledFor,
  replyText, setReplyText, isEmpty, emptyPulse, isComposerRewriting, showComposerTonePicker, setShowComposerTonePicker,
  showComposerLangPicker, setShowComposerLangPicker, composerRewrite, showSavedReplies, setShowSavedReplies,
  savedReplyQuery, detail, textareaRef, mentionQuery, mentionMatches, insertMention, onlineUsers, showSchedule,
  setShowSchedule, handleTextChange, handleKeyDown, handleSend, sendMutation,
}: {
  isVoiceOnly: boolean; windowBlocked: boolean; isInternalNote: boolean; exitInternalNote: () => void;
  replyToMsg: Message | null; setReplyToMsg: (m: Message | null) => void;
  scheduledFor: string | null; setScheduledFor: (v: string | null) => void;
  replyText: string; setReplyText: (v: string | ((prev: string) => string)) => void;
  isEmpty: boolean; emptyPulse: boolean;
  isComposerRewriting: boolean;
  showComposerTonePicker: boolean; setShowComposerTonePicker: (fn: boolean | ((v: boolean) => boolean)) => void;
  showComposerLangPicker: boolean; setShowComposerLangPicker: (fn: boolean | ((v: boolean) => boolean)) => void;
  composerRewrite: Mut;
  showSavedReplies: boolean; setShowSavedReplies: (v: boolean) => void; savedReplyQuery: string;
  detail?: ConversationDetail;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  mentionQuery: string | null; mentionMatches: any[]; insertMention: (u: any) => void;
  onlineUsers: { id: string }[];
  showSchedule: boolean; setShowSchedule: (fn: boolean | ((v: boolean) => boolean)) => void;
  handleTextChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  handleSend: (overrideScheduled?: string | null) => void;
  sendMutation: Mut;
}) {
  return (
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
                  className="flex items-center gap-2 mb-2 px-1 py-1 rounded-lg border bg-[var(--haip-status-info-bg)] border-[var(--haip-status-info-border)] text-[var(--haip-status-info-fg)]"
                >
                  <CalendarClock size={12} className="flex-shrink-0" />
                  <span className="text-xs flex-1">
                    Scheduled for {new Date(scheduledFor).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                  </span>
                  <button onClick={() => setScheduledFor(null)} aria-label="Cancel scheduled send" className="opacity-60 hover:opacity-100">
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
                      className="flex items-center gap-1 text-[11px] text-[var(--haip-fg-subtle)] bg-[var(--haip-card)] hover:bg-[var(--haip-surface)] border border-[var(--haip-border)] px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                    >
                      {isComposerRewriting ? <Loader2 size={11} className="animate-spin" /> : <Wand2 size={11} />} Tone Fix
                    </button>
                    {showComposerTonePicker && (
                      <div className="absolute z-10 mt-1 bg-[var(--haip-card)] border border-[var(--haip-border)] rounded-lg shadow-lg py-1 min-w-[110px]">
                        {COMPOSER_REWRITE_TONES.map(t => (
                          <button
                            key={t}
                            onClick={() => { composerRewrite.mutate({ tone: t }); setShowComposerTonePicker(false); }}
                            className="w-full text-left px-3 py-1.5 text-xs text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] capitalize"
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
                      className="flex items-center gap-1 text-[11px] text-[var(--haip-fg-subtle)] bg-[var(--haip-card)] hover:bg-[var(--haip-surface)] border border-[var(--haip-border)] px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                    >
                      <Languages size={11} /> Translate
                    </button>
                    {showComposerLangPicker && (
                      <div className="absolute z-10 mt-1 bg-[var(--haip-card)] border border-[var(--haip-border)] rounded-lg shadow-lg py-1 min-w-[110px]">
                        {COMPOSER_REWRITE_LANGUAGES.map(lang => (
                          <button
                            key={lang}
                            onClick={() => { composerRewrite.mutate({ targetLanguage: lang }); setShowComposerLangPicker(false); }}
                            className="w-full text-left px-3 py-1.5 text-xs text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]"
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
                  className={cn("flex-1 text-sm rounded-full px-4 py-2.5 focus:outline-none resize-none transition-all", emptyPulse && "animate-pulse")}
                  style={{
                    minHeight: "42px",
                    background: isInternalNote ? "color-mix(in srgb, var(--haip-amber) 6%, transparent)" : "var(--input-bg)",
                    border: `1.5px solid ${emptyPulse ? "var(--haip-red)" : isInternalNote ? "color-mix(in srgb, var(--haip-amber) 40%, transparent)" : "var(--haip-border)"}`,
                    color: "var(--haip-fg)",
                  }}
                />
                {/* Send button + Schedule dropdown trigger */}
                <div className="flex flex-shrink-0 items-center gap-1">
                  <button
                    onClick={() => handleSend()}
                    disabled={sendMutation.isPending}
                    className={cn(
                      "h-10 w-10 rounded-full flex items-center justify-center transition-colors duration-150",
                      !isEmpty && !isInternalNote && !scheduledFor && "ibx-send-btn",
                    )}
                    style={{
                      background: isEmpty ? "var(--muted)" : isInternalNote ? "var(--haip-amber)" : scheduledFor ? "var(--primary)" : undefined,
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
                      className="h-10 w-6 rounded-full flex items-center justify-center transition-colors duration-150"
                    style={{
                      background: isEmpty ? "var(--muted)" : "var(--primary)",
                      color: isEmpty ? "var(--haip-fg-subtle)" : "var(--primary-foreground)",
                    }}
                    >
                      <ChevronDown size={11} />
                    </button>
                  )}
                </div>
              </div>
              {/* W2: helper text */}
              <p className="text-[10px] mt-1 px-1 flex items-center gap-1.5" style={{ color: "var(--haip-fg-subtle)" }}>
                {/* Which channel a reply goes out on -- matters once a guest
                    has talked to us on more than one. */}
                {!isInternalNote && detail && toGuestChannel(detail.channel) && (
                  <span className="inline-flex items-center gap-1 font-semibold" style={{ color: "var(--haip-fg-muted)" }}>
                    <ChannelBadge channel={toGuestChannel(detail.channel)!} size={12} />
                    Replying on {channelLabel(detail.channel)} ·
                  </span>
                )}
                {isInternalNote
                  ? "Esc to cancel · Enter to save note"
                  : scheduledFor
                  ? "Click send to schedule · click ✕ above to cancel"
                  : "Enter to send · Shift+Enter newline · /note for internal notes · / for saved replies"}
              </p>
            </div>
  );
}
