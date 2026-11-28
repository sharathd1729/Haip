"use client";
// The Inbox list on a phone (mobile-first plan, approved mockup 24 Oct 2026): chats like WhatsApp. Each row: who, the last
// message, whose turn it is ("our turn" / "replied"), when, and how many unread. A chat with an AI draft waiting is marked and
// its "Review" button opens the thread, where the existing approve / edit / reject flow lives: nothing is ever approved or sent
// from this list. Chips: Our turn (the server's needs_reply view, counted server-side), AI drafts (loaded chats with a draft
// held for a person) and All; the channel lives in Filters. Tapping a row opens the thread, as before.
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, SlidersHorizontal, Sparkles } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { ChannelIcon } from "@/components/inbox/ChannelIcon";
import { Skeleton } from "@/components/ui/skeleton";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { AvatarChannelBadges, toGuestChannel } from "@/components/inbox/ChannelBadges";
import type { InboxView } from "@/components/inbox/ConversationList";
import type { ConversationSummary, GuestChannel } from "@/store/inbox";
import { BottomSheet, CompactRow, EmptyState, FilterSearch, RowAction, RowList, RowTag } from "@/components/ui/kit";
import { shortAgo } from "@/lib/waitText";

type Chip = "our_turn" | "drafts" | "all";

const pickCls = (on: boolean) => cn(
  "flex min-h-11 w-full cursor-pointer items-center justify-between gap-2 rounded-xl border px-3 text-left text-[14.5px] font-semibold text-[var(--haip-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
  on ? "border-primary bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)] bg-[var(--haip-card)]");

/** Whose turn, said the way the mockup does: an AI draft waits for approval, the guest waits on us, or we replied last. */
export function turnOf(c: ConversationSummary): { label: string; tone: "danger" | "warning" | "success" | "info" | "neutral" } {
  if (c.has_ai_draft) return { label: "approve", tone: "info" };
  if (c.is_waiting_reply) {
    const mins = c.waiting_since ? (Date.now() - new Date(c.waiting_since).getTime()) / 60000 : 0;
    return { label: "our turn", tone: mins >= 60 ? "danger" : "warning" };
  }
  if (c.status === "snoozed") return { label: "snoozed", tone: "neutral" };
  if (c.status === "resolved") return { label: "done", tone: "neutral" };
  return { label: "replied", tone: "success" };
}

export function PhoneInboxList({
  conversations, isLoading, view, onViewChange, counts, onSelect, onLoadMore, isLoadingMore, channelFilter, channelOptions, onChannelChange,
}: {
  conversations: ConversationSummary[];
  isLoading: boolean;
  view: InboxView;
  onViewChange: (v: InboxView) => void;
  counts?: { needs_reply: number; unassigned: number; mine: number };
  onSelect: (id: string) => void;
  onLoadMore?: () => void;
  isLoadingMore?: boolean;
  channelFilter: string;
  channelOptions: { value: string; label: string }[];
  onChannelChange: (v: string) => void;
}) {
  const [drafts, setDrafts] = useState(false);
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState(false);
  // Phones open on "Our turn" (the approved mockup); once, so picking All afterwards sticks.
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current) return;
    opened.current = true;
    if (view === "") onViewChange("needs_reply");
  }, [view, onViewChange]);

  const chip: Chip = drafts ? "drafts" : view === "needs_reply" ? "our_turn" : "all";
  const pick = (v: string) => {
    setDrafts(v === "drafts");
    onViewChange(v === "our_turn" ? "needs_reply" : "");
  };
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    return conversations.filter(c => (!drafts || c.has_ai_draft)
      && (!t || [c.guest_name, c.guest_phone, c.last_message].some(v => (v ?? "").toLowerCase().includes(t))));
  }, [conversations, drafts, q]);
  const draftCount = drafts || view === "" ? conversations.filter(c => c.has_ai_draft).length : undefined;
  const views = [
    { value: "our_turn", label: "Our turn", count: counts?.needs_reply },
    { value: "drafts", label: "AI drafts", count: onLoadMore ? undefined : draftCount },
    { value: "all", label: "All chats", count: undefined as number | undefined },
  ];
  const nOn = (chip !== "our_turn" ? 1 : 0) + (channelFilter ? 1 : 0);       // "Our turn" is how the phone opens: not a filter
  // What the thin line can honestly count: the server's number for Our turn, else nothing while more chats can still load.
  const shownCount = q ? rows.length : chip === "our_turn" ? counts?.needs_reply : onLoadMore ? undefined : rows.length;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* ONE row on top (owner, 28 Nov 2026): the search bar is the header, with one filter button whose badge counts what is
          on. Which chats and which channel are picked in the sheet; no chip row. One thin line says what is shown. */}
      <div className="grid gap-1 border-b border-[var(--haip-border)] px-4 pb-1.5 pt-3">
        <div className="flex items-center gap-2">
          <FilterSearch value={q} onChange={setQ} placeholder="Name, phone or message" label="Search chats" className="min-w-0 max-w-none" />
          <button type="button" onClick={() => setFilters(true)} aria-label={nOn ? `Filters, ${nOn} on` : "Filters"}
            className="relative flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-2)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50">
            <SlidersHorizontal size={18} aria-hidden />
            {nOn > 0 && <span aria-hidden className="absolute -right-1 -top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-[11px] font-bold tabular-nums text-primary-foreground">{nOn}</span>}
          </button>
        </div>
        <button type="button" onClick={() => setFilters(true)}
          className="flex min-h-8 cursor-pointer items-center gap-1 self-start rounded-lg text-left text-[13px] font-semibold text-[var(--haip-fg-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50">
          <span>{views.find(v => v.value === chip)?.label}</span>
          {shownCount != null && <span className="tabular-nums text-[var(--haip-fg-subtle)]">· {shownCount}</span>}
          {channelFilter && <ChannelIcon channel={channelFilter} showBg={false} />}
          <ChevronDown size={14} aria-hidden className="text-[var(--haip-fg-subtle)]" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-6 pt-3">
        {isLoading ? (
          <div className="grid gap-1.5" aria-busy="true">{[0, 1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-[64px] rounded-xl" />)}</div>
        ) : rows.length === 0 ? (
          <div className="haip-card"><EmptyState
            title={q ? "No chats match" : chip === "our_turn" ? "Nobody is waiting on a reply" : chip === "drafts" ? "No AI drafts waiting" : "No conversations here"}
            hint={chip === "drafts" && onLoadMore ? "Only the chats loaded so far are checked. Load more below." : undefined} /></div>
        ) : (
          <RowList label="Chats">
            {rows.map(c => {
              const turn = turnOf(c);
              const channels = (c.guest_channels?.length ? c.guest_channels : [toGuestChannel(c.channel)].filter(Boolean)) as GuestChannel[];
              const name = c.guest_name || c.guest_phone || "Guest";
              return (
                <CompactRow key={c.id} onClick={() => onSelect(c.id)} label={`${name}, open chat`}
                  avatar={<span className="relative inline-flex"><GuestAvatar name={c.guest_name} phone={c.guest_phone} /><AvatarChannelBadges channels={channels} size={14} /></span>}
                  title={name}
                  subtitle={c.has_ai_draft ? "AI draft ready to review" : c.last_message || "No messages yet"}
                  meta={c.has_ai_draft ? undefined : turn.label} metaTone={turn.tone}
                  metaSub={c.has_ai_draft ? undefined : shortAgo(c.last_message_at)}
                  extra={c.unread_count > 0 || c.stage_label ? <>
                    {c.unread_count > 0 && <RowTag tone="highlight">{c.unread_count > 99 ? "99+" : c.unread_count} new</RowTag>}
                    {c.stage_label && <RowTag>{c.stage_label}</RowTag>}
                  </> : undefined}
                  actions={c.has_ai_draft ? <RowAction icon={Sparkles} label={`Review the AI draft for ${name}`} onClick={() => onSelect(c.id)} /> : undefined} />
              );
            })}
          </RowList>
        )}
        {onLoadMore && !isLoading && (
          <button type="button" onClick={onLoadMore} disabled={isLoadingMore} className="haip-btn-secondary mt-3 min-h-11 w-full">
            {isLoadingMore ? "Loading…" : "Load older chats"}
          </button>
        )}
      </div>

      <BottomSheet open={filters} onOpenChange={setFilters} title="Show and filter" description="Which chats, and from which channel."
        footer={<button type="button" onClick={() => setFilters(false)} className="haip-btn-primary min-h-11 w-full cursor-pointer">
          {shownCount == null ? "Show chats" : `Show ${shownCount} ${shownCount === 1 ? "chat" : "chats"}`}</button>}>
        <div role="radiogroup" aria-label="Which chats" className="grid gap-1.5">
          {views.map(v => (
            <button key={v.value} type="button" role="radio" aria-checked={chip === v.value} onClick={() => pick(v.value)} className={pickCls(chip === v.value)}>
              <span className="min-w-0 truncate">{v.label}</span>
              <span className="flex shrink-0 items-center gap-2 tabular-nums text-[13px] text-[var(--haip-fg-subtle)]">
                {v.count ?? ""}{chip === v.value && <Check size={16} className="text-primary" aria-hidden />}
              </span>
            </button>
          ))}
        </div>
        <p className="mb-1.5 mt-4 text-[12.5px] font-bold text-[var(--haip-fg-2)]">Channel</p>
        <div role="radiogroup" aria-label="Channel" className="grid gap-1.5">
          {channelOptions.map(o => (
            <button key={o.value} type="button" role="radio" aria-checked={channelFilter === o.value} onClick={() => onChannelChange(o.value)} className={pickCls(channelFilter === o.value)}>
              <span className="flex min-w-0 items-center gap-2">{o.value && <ChannelIcon channel={o.value} />}<span className="truncate">{o.label}</span></span>
              {channelFilter === o.value && <Check size={16} className="shrink-0 text-primary" aria-hidden />}
            </button>
          ))}
        </div>
      </BottomSheet>
    </div>
  );
}
