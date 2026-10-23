"use client";
// The Inbox list on a phone (mobile-first plan, approved mockup 24 Oct 2026): chats like WhatsApp. Each row: who, the last
// message, whose turn it is ("our turn" / "replied"), when, and how many unread. A chat with an AI draft waiting is marked and
// its "Review" button opens the thread, where the existing approve / edit / reject flow lives: nothing is ever approved or sent
// from this list. Chips: Our turn (the server's needs_reply view, counted server-side), AI drafts (loaded chats with a draft
// held for a person) and All; the channel lives in Filters. Tapping a row opens the thread, as before.
import { useEffect, useMemo, useRef, useState } from "react";
import { Sparkles } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { AvatarChannelBadges, toGuestChannel } from "@/components/inbox/ChannelBadges";
import type { InboxView } from "@/components/inbox/ConversationList";
import type { ConversationSummary, GuestChannel } from "@/store/inbox";
import { BottomSheet, ChipRow, CompactRow, EmptyState, FilterSearch, RowAction, RowList, RowTag } from "@/components/ui/kit";
import { shortAgo } from "@/lib/waitText";

type Chip = "our_turn" | "drafts" | "all";

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

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="grid gap-2 border-b border-[var(--haip-border)] px-4 pb-2 pt-3">
        <FilterSearch value={q} onChange={setQ} placeholder="Name, phone or message" label="Search chats" className="min-w-0 max-w-none" />
        <ChipRow label="Which chats" value={chip} onChange={pick} onFilters={() => setFilters(true)} filterCount={channelFilter ? 1 : 0}
          items={[
            { value: "our_turn", label: "Our turn", count: counts?.needs_reply },
            { value: "drafts", label: "AI drafts", count: onLoadMore ? undefined : draftCount },
            { value: "all", label: "All" },
          ]} />
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

      <BottomSheet open={filters} onOpenChange={setFilters} title="Channel" description="Show chats from one channel.">
        <ul className="grid">
          {channelOptions.map(o => (
            <li key={o.value}>
              <button type="button" aria-pressed={channelFilter === o.value} onClick={() => { onChannelChange(o.value); setFilters(false); }}
                className="flex min-h-12 w-full items-center border-t border-[var(--haip-border)] text-left text-[15px] text-[var(--haip-fg)] first:border-t-0 aria-pressed:font-bold aria-pressed:text-primary">
                {o.label}
              </button>
            </li>
          ))}
        </ul>
      </BottomSheet>
    </div>
  );
}
