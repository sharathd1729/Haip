"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { BellOff, Check, ChevronLeft, Loader2, MoreHorizontal, Phone, Search, Timer, User } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/page";
import { TalkedOn, toGuestChannel } from "@/components/inbox/ChannelBadges";
import {
  type ConversationDetail, type Mut, getWindowSecondsLeft, formatWindowCountdown,
} from "./types";

/** How long the guest has been waiting, when their last real message is unanswered. Internal notes and
 *  AI drafts nobody has approved are not replies, so they don't count. */
function waitingSince(detail: ConversationDetail): string | null {
  const real = detail.messages.filter(m => !m.is_internal && !(m.ai_drafted && m.direction === "outbound" && m.was_approved == null));
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
const ICON_BTN = "flex size-9 flex-shrink-0 items-center justify-center rounded-lg text-[var(--haip-icon-neutral)] transition-colors hover:bg-[var(--haip-surface)] hover:text-[var(--haip-fg)] active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";

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
  currentUserId, clickToCallMutation, resolveMutation, setShowGuestSheet, setShowSearch, snoozeMutation,
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
}) {
  if (!detail) {
    return <div className="flex-shrink-0 border-b border-[var(--haip-border)] px-3 py-3 md:px-5"><Skeleton className="h-10 w-56" /></div>;
  }

  const aiOn = detail.ai_enabled ?? true;
  const waiting = waitingSince(detail);
  const wait = waiting ? waitLabel(waiting) : null;
  const owner = teamMembers.find((u: any) => u.id === detail.assigned_to);
  const name = detail.guest_name || detail.guest_phone;
  const showWindow = isOfficialWhatsApp && !!detail.last_inbound_at;
  const channels = detail.guest_channels?.length ? detail.guest_channels : (toGuestChannel(detail.channel) ? [toGuestChannel(detail.channel)!] : []);

  return (
    <div className="flex-shrink-0 border-b border-[var(--haip-border)]">
      <div className="flex items-center gap-2 px-3 py-2.5 md:gap-3 md:px-5">
        <button type="button" onClick={() => setMobileView("list")} aria-label="Back to conversations"
          className={cn(ICON_BTN, "-ml-1 md:hidden")}>
          <ChevronLeft size={18} />
        </button>

        <div className="ibx-avatar flex-shrink-0 !size-10 !text-[15px]" aria-hidden>
          {detail.guest_name?.[0]?.toUpperCase() ?? "?"}
        </div>

        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[15px] font-bold leading-tight text-[var(--haip-fg)]" title={name}>{name}</h2>
          <div className="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-[var(--haip-fg-subtle)]">
            <TalkedOn size={14} channels={channels} />
            <span className="truncate">{owner ? (owner.id === currentUserId ? "Assigned to you" : `Owner: ${owner.name}`) : "No owner yet"}</span>
          </div>
        </div>

        {detail.guest_phone && (
          <button type="button" onClick={() => clickToCallMutation.mutate(detail.guest_phone)} disabled={clickToCallMutation.isPending}
            className="inline-flex h-9 flex-shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3.5 text-[13px] font-semibold text-primary-foreground transition-[opacity,transform] hover:opacity-90 active:scale-[0.97] disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2">
            {clickToCallMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Phone size={14} />}
            <span className="hidden sm:inline">Call</span>
          </button>
        )}

        <button type="button" onClick={() => resolveMutation.mutate()} disabled={resolveMutation.isPending || detail.status === "resolved"}
          aria-label={detail.status === "resolved" ? "Resolved" : "Mark resolved"}
          className="inline-flex h-9 flex-shrink-0 items-center gap-1.5 rounded-lg border border-[var(--haip-border)] px-2.5 text-[13px] font-semibold text-[var(--haip-fg-2)] transition-[background-color,transform] hover:bg-[var(--haip-status-success-bg)] hover:text-[var(--haip-status-success-fg)] active:scale-[0.97] disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          <Check size={15} />
          <span className="hidden lg:inline">{detail.status === "resolved" ? "Resolved" : "Resolve"}</span>
        </button>

        <button type="button" onClick={() => setShowGuestSheet(true)} aria-label="Guest details" className={cn(ICON_BTN, "md:hidden")}>
          <User size={16} />
        </button>

        <MoreMenu label="More actions">
          {close => (
            <>
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
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 pb-2.5 md:px-5">
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

        <button type="button" role="switch" aria-checked={aiOn} onClick={() => aiToggleMutation.mutate(!aiOn)} disabled={aiToggleMutation.isPending}
          title={aiOn ? "AI is replying to this guest. Click to pause." : "AI is paused for this guest. Click to resume."}
          className="ml-auto inline-flex min-h-7 items-center gap-2 rounded-lg px-1.5 text-xs font-semibold text-[var(--haip-fg-2)] disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          <span className={cn("relative h-4 w-7 rounded-full transition-colors", aiOn ? "bg-primary" : "bg-[var(--haip-border-strong)]")}>
            <span className={cn("absolute top-0.5 size-3 rounded-full bg-white transition-[left]", aiOn ? "left-3.5" : "left-0.5")} />
          </span>
          {aiOn ? "AI on" : "AI paused"}
        </button>
      </div>
    </div>
  );
}
