"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { BellOff, Calculator, Check, ChevronLeft, Loader2, MessageSquare, MoreHorizontal, Phone, Search, Timer, User } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/page";
import { ChannelBadges, TalkedOn, toGuestChannel } from "@/components/inbox/ChannelBadges";
import { SendQuoteButton, useCanQuote } from "@/components/quotes/SendQuoteButton";
import { useQuoteSheet } from "@/components/quotes/QuoteSheetProvider";
import { useContactChoice } from "@/components/contact/ContactChoice";
import {
  type ConversationDetail, type Mut, getWindowSecondsLeft, formatWindowCountdown,
} from "./types";

/** How long the guest has been waiting, when their last real message is unanswered. Internal notes and
 *  AI drafts that were never sent (pending, rejected, expired) are not replies, so they don't count. */
function waitingSince(detail: ConversationDetail): string | null {
  const real = detail.messages.filter(m => !m.is_internal && !(m.ai_drafted && m.direction === "outbound" && m.was_approved !== true));   // pending, rejected or expired: never sent
  const last = real[real.length - 1];
  return last && last.direction === "inbound" ? last.timestamp : null;
}

function waitLabel(iso: string): { text: string; mins: number } {
  const mins = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return { text: `${mins}m`, mins };
  const h = Math.floor(mins / 60);
  return { text: h < 24 ? `${h}h ${mins % 60}m` : `${Math.floor(h / 24)}d`, mins };
}

const ITEM = "flex min-h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] text-[var(--haip-fg)] hover:bg-[var(--haip-surface)] disabled:opacity-50";
const ICON_BTN = "relative after:absolute after:-inset-1 after:content-[''] md:after:hidden flex size-9 flex-shrink-0 items-center justify-center rounded-lg text-[var(--haip-icon-neutral)] transition-colors hover:bg-[var(--haip-surface)] hover:text-[var(--haip-fg)] active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";

/** "More" menu: the things an agent does occasionally (find in thread, snooze, hand over). It closes on
 *  Escape or an outside click, and each action closes it. Opens from the button's corner, not the centre. */
function MoreMenu({ children, label }: { children: (close: () => void) => ReactNode; label: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button type="button" className={ICON_BTN} aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <MoreHorizontal size={16} />
      </button>
      {open && (
        <div role="menu"
          className="absolute right-0 top-full z-30 mt-1.5 w-60 origin-top-right rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-1.5 shadow-lg transition-[opacity,transform] duration-150 starting:scale-95 starting:opacity-0">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

function MenuLabel({ children }: { children: ReactNode }) {
  return <p className="px-2.5 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{children}</p>;
}

export function ThreadHeader({
  detail, setMobileView, isOfficialWhatsApp, windowOpen, aiToggleMutation, assignMutation, teamMembers,
  currentUserId, clickToCallMutation, resolveMutation, setShowGuestSheet, setShowSearch, snoozeMutation, onStartWhatsApp,
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
  /** Kept for the page's call site; the menu now owns its own open state. */
  showSnooze?: boolean;
  setShowSnooze?: (fn: (s: boolean) => boolean) => void;
  /** An Instagram chat with a guest who gave their number: message that number on the official WhatsApp. */
  onStartWhatsApp?: () => void;
}) {
  // Call = My phone | Office line; WhatsApp = My WhatsApp | HAIP WhatsApp (components/contact/ContactChoice). The Inbox already
  // shows this person the number, so it is used as is.
  const guestName = detail?.guest_name || "the guest";
  const callChoice = useContactChoice({ kind: "call", inquiryId: detail?.inquiry_id ?? "", name: guestName, canReveal: false,
    phone: detail?.guest_phone, onOffice: () => { if (detail?.guest_phone) clickToCallMutation.mutate(detail.guest_phone); } });
  const waChoice = useContactChoice({ kind: "whatsapp", inquiryId: detail?.inquiry_id ?? "", name: guestName, canReveal: false,
    phone: detail?.guest_phone, onOffice: () => { if (detail?.channel === "instagram") onStartWhatsApp?.(); } });
  const canQuote = useCanQuote();
  const quoteSheet = useQuoteSheet();
  if (!detail) {
    return <div className="flex-shrink-0 border-b border-[var(--haip-border)] px-3 py-3 pt-[calc(0.75rem+env(safe-area-inset-top))] md:px-5 md:pt-3"><Skeleton className="h-10 w-56" /></div>;
  }

  const aiOn = detail.ai_enabled ?? true;
  const waiting = waitingSince(detail);
  const wait = waiting ? waitLabel(waiting) : null;
  const owner = teamMembers.find((u: any) => u.id === detail.assigned_to);
  const name = detail.guest_name || detail.guest_phone;
  const showWindow = isOfficialWhatsApp && !!detail.last_inbound_at;
  const channels = detail.guest_channels?.length ? detail.guest_channels : (toGuestChannel(detail.channel) ? [toGuestChannel(detail.channel)!] : []);

  return (
    // @container: the buttons show their words by the thread column's width, not the window's (the column is ~384px
    // between the list and the guest panel at 1024px, where the words did not fit).
    <div className="@container flex-shrink-0 border-b border-[var(--haip-border)] pt-[env(safe-area-inset-top)] md:pt-0">
      <div className="flex items-center gap-1.5 px-3 py-2 md:gap-3 md:px-5 md:py-2.5">
        <button type="button" onClick={() => setMobileView("list")} aria-label="Back to conversations"
          className={cn(ICON_BTN, "-ml-1 md:hidden")}>
          <ChevronLeft size={18} />
        </button>

        <div className="ibx-avatar flex-shrink-0 !size-9 !text-[14px] md:!size-10 md:!text-[15px]" aria-hidden>
          {detail.guest_name?.[0]?.toUpperCase() ?? "?"}
        </div>

        {/* Phone: ONE header row (owner, 28 Nov 2026). The name opens the guest's details; the line under it says who is
            waiting and how long to reply. Quote, Resolve and the rest live in More. Desktop keeps its buttons and the strip. */}
        <button type="button" onClick={() => setShowGuestSheet(true)} aria-label={`${name}, guest details`}
          className="min-w-0 flex-1 cursor-pointer rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 md:hidden">
          <span className="block truncate text-[15px] font-bold leading-tight text-[var(--haip-fg)]">{name}</span>
          <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-[var(--haip-fg-subtle)]">
            <ChannelBadges size={14} channels={channels} className="shrink-0" />{/* a channel is its icon */}
            {wait ? <span className={cn("truncate font-semibold", wait.mins >= 120 ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-status-warning-fg)]")}>Waiting {wait.text}</span>
              : showWindow && windowOpen ? <span className="truncate tabular-nums">{formatWindowCountdown(getWindowSecondsLeft(detail.last_inbound_at))} to reply</span>
                : <span className="truncate">{owner ? (owner.id === currentUserId ? "Yours" : owner.name) : "No owner yet"}</span>}
          </span>
        </button>
        <div className="hidden min-w-0 flex-1 md:block">
          <h2 className="truncate text-[15px] font-bold leading-tight text-[var(--haip-fg)]" title={name}>{name}</h2>
          <div className="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-[var(--haip-fg-subtle)]">
            <TalkedOn size={14} channels={channels} />
            <span className="truncate">{owner ? (owner.id === currentUserId ? "Assigned to you" : `Owner: ${owner.name}`) : "No owner yet"}</span>
          </div>
        </div>

        {/* Phone: the AI switch sits in the header row (the strip below is desktop only). */}
        {detail.can_send !== false && (
          <button type="button" role="switch" aria-checked={aiOn} onClick={() => aiToggleMutation.mutate(!aiOn)} disabled={aiToggleMutation.isPending}
            aria-label={aiOn ? "AI is replying to this guest. Tap to pause." : `AI is paused for this guest${detail.ai_off_reason ? ` (${detail.ai_off_reason})` : ""}. Tap to resume.`}
            className="inline-flex min-h-11 flex-shrink-0 cursor-pointer items-center gap-1.5 rounded-lg px-1 text-[11.5px] font-bold text-[var(--haip-fg-2)] disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 md:hidden">
            <span aria-hidden className={cn("relative h-4 w-7 rounded-full transition-colors", aiOn ? "bg-primary" : "bg-[var(--haip-border-strong)]")}>
              <span className={cn("absolute top-0.5 size-3 rounded-full bg-white transition-[left]", aiOn ? "left-3.5" : "left-0.5")} />
            </span>
            AI
          </button>
        )}

        {detail.guest_phone && (
          <button type="button" onClick={callChoice.start} disabled={clickToCallMutation.isPending} aria-label="Call"
            className="relative inline-flex h-9 flex-shrink-0 cursor-pointer items-center gap-1.5 rounded-lg bg-primary px-3.5 after:absolute after:inset-x-0 after:-inset-y-1 after:content-[''] md:after:hidden text-[13px] font-semibold text-primary-foreground transition-[opacity,transform] hover:opacity-90 active:scale-[0.97] disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2">
            {clickToCallMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Phone size={14} />}
            <span className="hidden @md:inline">Call</span>
          </button>
        )}

        {onStartWhatsApp && detail.channel === "instagram" && detail.guest_phone && (
          <button type="button" onClick={waChoice.start} aria-label="Start on WhatsApp"
            className="hidden h-9 flex-shrink-0 items-center md:inline-flex gap-1.5 rounded-lg border border-[var(--haip-border)] px-2.5 text-[13px] font-semibold text-[var(--haip-status-success-fg)] transition-[background-color,transform] hover:bg-[var(--haip-status-success-bg)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
            <MessageSquare size={15} />
            <span className="hidden @md:inline">WhatsApp</span>
          </button>
        )}

        {/* The rate calculator on top of the chat, prefilled with this lead and the trip the chat mentioned. */}
        <SendQuoteButton iconOnlyBelowSm labelClassName="hidden @md:inline" className="hidden h-9 min-h-0 sm:min-h-0 md:inline-flex"
          args={{ conversationId: detail.id, inquiryId: detail.inquiry_id ?? null, from: "inbox", name: detail.guest_name || null }} />

        <button type="button" onClick={() => resolveMutation.mutate()} disabled={resolveMutation.isPending || detail.status === "resolved"}
          aria-label={detail.status === "resolved" ? "Resolved" : "Mark resolved"}
          className="hidden h-9 flex-shrink-0 items-center md:inline-flex gap-1.5 rounded-lg border border-[var(--haip-border)] px-2.5 text-[13px] font-semibold text-[var(--haip-fg-2)] transition-[background-color,transform] hover:bg-[var(--haip-status-success-bg)] hover:text-[var(--haip-status-success-fg)] active:scale-[0.97] disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          <Check size={15} />
          <span className="hidden @2xl:inline">{detail.status === "resolved" ? "Resolved" : "Resolve"}</span>
        </button>

        <MoreMenu label="More actions">
          {close => (
            <>
              {/* Phone only: what the desktop header shows as buttons */}
              <div className="md:hidden">
                <button type="button" role="menuitem" className={ITEM} onClick={() => { setShowGuestSheet(true); close(); }}>
                  <User size={15} className="text-[var(--haip-icon-neutral)]" /> Guest details
                </button>
                {canQuote && (
                  <button type="button" role="menuitem" className={ITEM}
                    onClick={() => { quoteSheet.open({ conversationId: detail.id, inquiryId: detail.inquiry_id ?? null, from: "inbox", name: detail.guest_name || null }); close(); }}>
                    <Calculator size={15} className="text-[var(--haip-icon-neutral)]" /> Send quote
                  </button>
                )}
                <button type="button" role="menuitem" className={ITEM} disabled={resolveMutation.isPending || detail.status === "resolved"}
                  onClick={() => { resolveMutation.mutate(); close(); }}>
                  <Check size={15} className="text-[var(--haip-icon-neutral)]" /> {detail.status === "resolved" ? "Resolved" : "Mark resolved"}
                </button>
                {detail.guest_phone && (
                  <button type="button" role="menuitem" className={ITEM} onClick={() => { waChoice.start(); close(); }}>
                    <MessageSquare size={15} className="text-[var(--haip-icon-neutral)]" /> {detail.channel === "instagram" ? "Start on WhatsApp" : "Open in my WhatsApp"}
                  </button>
                )}
              </div>

              <button type="button" role="menuitem" className={ITEM} onClick={() => { setShowSearch(s => !s); close(); }}>
                <Search size={15} className="text-[var(--haip-icon-neutral)]" /> Search in this conversation
              </button>

              <MenuLabel>Snooze</MenuLabel>
              {[{ label: "For 3 hours", hours: 3 }, { label: "Until tomorrow", hours: 18 }, { label: "For a week", hours: 168 }].map(opt => (
                <button key={opt.label} type="button" role="menuitem" className={ITEM}
                  onClick={() => { snoozeMutation.mutate(new Date(Date.now() + opt.hours * 3600_000).toISOString()); close(); }}>
                  <BellOff size={15} className="text-[var(--haip-icon-neutral)]" /> {opt.label}
                </button>
              ))}
              <button type="button" role="menuitem" className={cn(ITEM, "text-[var(--haip-status-danger-fg)]")}
                onClick={() => { snoozeMutation.mutate(null); close(); }}>
                <span className="w-[15px]" /> Clear snooze
              </button>

              <MenuLabel>Owner</MenuLabel>
              <button type="button" role="menuitem" className={ITEM} onClick={() => { assignMutation.mutate(null); close(); }}>
                <span className="flex w-[15px] justify-center">{!detail.assigned_to && <Check size={13} />}</span> Unassigned
              </button>
              {teamMembers.map((u: any) => (
                <button key={u.id} type="button" role="menuitem" className={ITEM} onClick={() => { assignMutation.mutate(u.id); close(); }}>
                  <span className="flex w-[15px] justify-center">{detail.assigned_to === u.id && <Check size={13} />}</span>
                  <span className="truncate">{u.id === currentUserId ? `${u.name} (me)` : u.name}</span>
                </button>
              ))}
            </>
          )}
        </MoreMenu>
      </div>

      {/* State strip: only what needs attention. Who is waiting, whether a template is needed, and whether the
          AI is replying. Empty strips are not rendered. */}
      {!aiOn && detail.ai_off_reason && (
        <p className="px-3 pb-2 text-[12px] font-semibold text-[var(--haip-status-warning-fg)] md:hidden">AI turned off: {detail.ai_off_reason}</p>
      )}
      {callChoice.sheet}
      {waChoice.sheet}
      <div className="hidden flex-wrap items-center gap-x-3 gap-y-1.5 px-3 pb-2.5 md:flex md:px-5">
        {wait && (
          <StatusPill tone={wait.mins >= 120 ? "danger" : "warning"}>
            Waiting {wait.text}<span className="hidden sm:inline">&nbsp;for a reply</span>
          </StatusPill>
        )}
        {showWindow && (windowOpen ? (
          <StatusPill tone="neutral" className="gap-1"><Timer size={10} />{formatWindowCountdown(getWindowSecondsLeft(detail.last_inbound_at))}<span className="hidden sm:inline">&nbsp;to reply</span></StatusPill>
        ) : (
          <StatusPill tone="warning">Template required</StatusPill>
        ))}

        {!aiOn && detail.ai_off_reason && (
          <StatusPill tone="warning">AI turned off: {detail.ai_off_reason}</StatusPill>
        )}

        {/* A read-only thread never gets AI replies (can_send), so there is nothing to switch. */}
        {detail.can_send !== false && (
        <button type="button" role="switch" aria-checked={aiOn} onClick={() => aiToggleMutation.mutate(!aiOn)} disabled={aiToggleMutation.isPending}
          title={aiOn ? "AI is replying to this guest. Click to pause." : "AI is paused for this guest. Click to resume."}
          className="ml-auto inline-flex min-h-7 items-center gap-2 rounded-lg px-1.5 text-xs font-semibold text-[var(--haip-fg-2)] disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          <span className={cn("relative h-4 w-7 rounded-full transition-colors", aiOn ? "bg-primary" : "bg-[var(--haip-border-strong)]")}>
            <span className={cn("absolute top-0.5 size-3 rounded-full bg-white transition-[left]", aiOn ? "left-3.5" : "left-0.5")} />
          </span>
          {aiOn ? "AI on" : detail.ai_off_reason ? "AI off" : "AI paused"}
        </button>
        )}
      </div>
    </div>
  );
}
