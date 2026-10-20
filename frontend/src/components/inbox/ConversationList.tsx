"use client";
// Inbox conversation list (redesign). One search box, one row of filter
// chips (Needs reply / Unassigned / Mine / All, counted server-side), a
// channel + sort row, then rows with:
//   avatar with every channel the guest has used pinned to its bottom edge,
//   name, time, last message, ONE status tag, owner initial or unread count.
// Bulk select, load more and the hover Call / Archive actions are unchanged.
import { useState, useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";
import { avatarInitials, avatarTintClass } from "@/lib/avatarTint";
import { ArrowUpDown, CheckSquare, Square, CheckCheck, Archive, X, Star, Phone, Loader2, Search, Reply, ChevronDown } from "@/lib/icons";
import type { ConversationSummary } from "@/store/inbox";
import { AvatarChannelBadges, toGuestChannel } from "./ChannelBadges";

type SortMode = "smart" | "recent" | "unread";
export type InboxView = "" | "needs_reply" | "unassigned" | "mine";

const SORT_LABELS: Record<SortMode, string> = {
  smart:  "Smart",
  recent: "Newest first",
  unread: "Unread first",
};

export interface ConversationSummaryExt extends ConversationSummary {
  is_vip?: boolean;
  has_active_booking?: boolean;
  needs_attention?: boolean;
  property_name?: string;
}

interface ConversationListProps {
  conversations: ConversationSummaryExt[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onSortChange?: (mode: SortMode) => void;
  className?: string;
  onBulkResolve?: (ids: string[]) => void;
  onBulkMarkRead?: (ids: string[]) => void;
  /** Present whenever another page of older conversations exists. */
  onLoadMore?: () => void;
  isLoadingMore?: boolean;
  /** Archive one conversation from the hover actions (PATCH is_open=false). */
  onArchive?: (id: string) => void;
  /** Real IVR-mediated outbound call (POST /calls/click-to-call). */
  onCall?: (guestNumber: string) => void;
  callingNumber?: string | null;
  /** Server-side filter chip + its counts (GET /conversations/counts). */
  view: InboxView;
  onViewChange: (v: InboxView) => void;
  counts?: { needs_reply: number; unassigned: number; mine: number };
  /** Channel dropdown. */
  channelFilter: string;
  channelOptions: { value: string; label: string }[];
  onChannelChange: (v: string) => void;
  isLoading?: boolean;
}



function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

type Tone = "amber" | "red" | "green" | "violet" | "gray";
const TONE: Record<Tone, string> = {
  amber: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]",
  red: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]",
  green: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]",
  violet: "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]",
  gray: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)]",
};

/** The single most important status for a row -- never a pile of badges. */
function statusFor(c: ConversationSummaryExt): { label: string; tone: Tone } | null {
  // A reply the AI deliberately held back (price / fact / escalation guard)
  // still needs a human -- otherwise that guest is never answered.
  if (c.has_ai_draft) return { label: "AI reply held", tone: "violet" };
  if (c.is_waiting_reply) {
    // Colour escalates with the wait so only the guests who have waited longest stand out:
    // under an hour is plain, an hour or more is amber, four hours or more is red.
    const mins = c.waiting_since ? (Date.now() - new Date(c.waiting_since).getTime()) / 60000 : 0;
    const tone: Tone = mins >= 240 ? "red" : mins >= 60 ? "amber" : "gray";
    return { label: c.waiting_since ? `Waiting ${timeAgo(c.waiting_since)}` : "Waiting", tone };
  }
  if (c.has_phone_decline_alert) return { label: "No phone shared", tone: "red" };
  if (c.sla_status === "breached") return { label: "SLA breached", tone: "red" };
  if (c.has_active_booking) return { label: "Booked", tone: "violet" };
  if (c.status === "snoozed") return { label: "Snoozed", tone: "gray" };
  if (c.status === "resolved") return { label: "Resolved", tone: "gray" };
  return null;
}

const VIEWS: { key: InboxView; label: string; countKey?: "needs_reply" | "unassigned" | "mine" }[] = [
  { key: "needs_reply", label: "Needs reply", countKey: "needs_reply" },
  { key: "unassigned", label: "Unassigned", countKey: "unassigned" },
  { key: "mine", label: "Mine", countKey: "mine" },
  { key: "", label: "All" },
];

export function ConversationList({
  conversations, activeId, onSelect, onSortChange, className,
  onBulkResolve, onBulkMarkRead, onLoadMore, isLoadingMore, onArchive, onCall, callingNumber,
  view, onViewChange, counts, channelFilter, channelOptions, onChannelChange, isLoading,
}: ConversationListProps) {
  const [sort, setSort] = useState<SortMode>(() => {
    if (typeof window !== "undefined") {
      try { return (localStorage.getItem("inbox_sort") as SortMode) ?? "recent"; } catch { return "recent"; }
    }
    return "recent";
  });
  const [showSortMenu, setShowSortMenu] = useState(false);
  // Compact rows fit more conversations on screen. Remembered on this device.
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    try { setCompact(localStorage.getItem("inbox_density") === "compact"); } catch { /* storage unavailable */ }
  }, []);
  const toggleCompact = () => setCompact(c => {
    const next = !c;
    try { localStorage.setItem("inbox_density", next ? "compact" : "comfortable"); } catch { /* ignore */ }
    return next;
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const isSelecting = selected.size > 0;
  const [searchQuery, setSearchQuery] = useState("");

  const toggleSelect = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  useEffect(() => {
    try { localStorage.setItem("inbox_sort", sort); } catch { /* private mode */ }
    onSortChange?.(sort);
  }, [sort, onSortChange]);

  // Search runs over the conversations already loaded (name/phone, last
  // message, property). The filter chips themselves are server-side.
  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter(c =>
      (c.guest_name ?? "").toLowerCase().includes(q) ||
      (c.guest_phone ?? "").toLowerCase().includes(q) ||
      (c.last_message ?? "").toLowerCase().includes(q) ||
      (c.property_name ?? "").toLowerCase().includes(q)
    );
  }, [conversations, searchQuery]);

  const sorted = useMemo(() => [...filtered].sort((a, b) => {
    if (sort === "unread") {
      const diff = (b.unread_count ?? 0) - (a.unread_count ?? 0);
      if (diff !== 0) return diff;
    } else if (sort === "smart") {
      if (!!a.is_vip !== !!b.is_vip) return a.is_vip ? -1 : 1;
      if (!!a.is_waiting_reply !== !!b.is_waiting_reply) return a.is_waiting_reply ? -1 : 1;
      const aUnread = (a.unread_count ?? 0) > 0 ? 0 : 1;
      const bUnread = (b.unread_count ?? 0) > 0 ? 0 : 1;
      if (aUnread !== bUnread) return aUnread - bUnread;
    }
    return new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime();
  }), [filtered, sort]);

  const selectAll = () => setSelected(new Set(sorted.map(c => c.id)));
  const clearSelection = () => setSelected(new Set());

  return (
    <div className={cn("flex flex-col min-h-0", className)}>
      {/* Search + filter chips + channel/sort -- the only controls above the list */}
      <div className="px-3 pt-3 pb-2 space-y-2.5 flex-shrink-0" style={{ borderBottom: "1px solid var(--haip-border)" }}>
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--haip-fg-subtle)" }} />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search guests and messages"
            aria-label="Search conversations"
            className="w-full pl-9 pr-3 py-2 rounded-xl text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
            style={{ background: "var(--muted)", color: "var(--haip-fg)" }}
          />
        </div>

        <div role="tablist" aria-label="Inbox filter" className="flex gap-1.5 overflow-x-auto scrollbar-hide">
          {VIEWS.map(v => {
            const on = view === v.key;
            const n = v.countKey ? counts?.[v.countKey] : undefined;
            return (
              <button
                key={v.key || "all"}
                role="tab"
                aria-selected={on}
                onClick={() => onViewChange(v.key)}
                className={cn(
                  "flex-shrink-0 inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full transition-colors border",
                  "border-[color:var(--haip-border)]",
                )}
                style={on ? { background: "color-mix(in srgb, var(--primary) 12%, var(--haip-card))", color: "var(--primary)", borderColor: "color-mix(in srgb, var(--primary) 50%, transparent)" } : { color: "var(--haip-fg-2, var(--haip-fg))", background: "var(--haip-card)" }}
              >
                {v.label}
                {n != null && n > 0 && (
                  <span className={"tabular-nums text-primary"}>{n}</span>
                )}
              </button>
            );
          })}
        </div>

        <div className="flex items-center justify-between relative">
          <label className="relative inline-flex items-center gap-1 text-xs font-semibold" style={{ color: "var(--haip-fg-subtle)" }}>
            <select
              value={channelFilter}
              onChange={e => onChannelChange(e.target.value)}
              aria-label="Channel"
              className="appearance-none bg-transparent pr-4 outline-none cursor-pointer"
            >
              {channelOptions.map(o => (
                <option key={o.value || "all"} value={o.value}>{o.value ? o.label : "All channels"}</option>
              ))}
            </select>
            <ChevronDown size={12} className="absolute right-0 pointer-events-none" />
          </label>
          <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={toggleCompact}
            aria-pressed={compact}
            className="inline-flex items-center text-xs font-semibold hover:text-[var(--haip-fg)]"
            style={{ color: "var(--haip-fg-subtle)" }}
            title={compact ? "Show comfortable rows" : "Show more conversations (compact rows)"}
          >
            {compact ? "Comfortable" : "Compact"}
          </button>
          <button
            onClick={() => setShowSortMenu(v => !v)}
            className="inline-flex items-center gap-1 text-xs font-semibold"
            style={{ color: "var(--haip-fg-subtle)" }}
            aria-haspopup="menu"
            aria-expanded={showSortMenu}
          >
            {SORT_LABELS[sort]} <ArrowUpDown size={11} />
          </button>
          </div>
          {showSortMenu && (
            <div role="menu" className="absolute top-full right-0 mt-1 border rounded-xl shadow-lg z-20 overflow-hidden"
              style={{ background: "var(--haip-card)", borderColor: "var(--haip-border)" }}>
              {(Object.keys(SORT_LABELS) as SortMode[]).map(m => (
                <button
                  key={m}
                  role="menuitem"
                  onClick={() => { setSort(m); setShowSortMenu(false); }}
                  className={cn("w-full text-left px-4 py-2 text-xs", sort === m ? "bg-primary/10 text-primary font-semibold" : "hover:bg-[color:var(--muted)]")}
                  style={sort === m ? undefined : { color: "var(--haip-fg)" }}
                >
                  {SORT_LABELS[m]}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {isSelecting && (
        <div className="px-3 py-2 border-b border-primary/20 bg-primary/10 flex items-center gap-2 flex-shrink-0">
          <span className="text-xs font-semibold text-primary">{selected.size} selected</span>
          <button onClick={selectAll} className="text-[11px] text-primary hover:underline">All</button>
          <div className="flex-1" />
          {onBulkMarkRead && (
            <button onClick={() => { onBulkMarkRead(Array.from(selected)); clearSelection(); }}
              className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg bg-[var(--haip-card)] border border-primary/30 text-primary hover:bg-primary/10">
              <CheckCheck size={11} /> Read
            </button>
          )}
          {onBulkResolve && (
            <button onClick={() => { onBulkResolve(Array.from(selected)); clearSelection(); }}
              className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg bg-[var(--haip-card)] border border-primary/30 text-primary hover:bg-primary/10">
              <Archive size={11} /> Resolve
            </button>
          )}
          <button onClick={clearSelection} className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)] ml-1" aria-label="Clear selection">
            <X size={13} />
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto haip-scrollbar">
        {isLoading ? (
          <div className="py-10 flex justify-center"><Loader2 size={18} className="animate-spin" style={{ color: "var(--haip-fg-subtle)" }} /></div>
        ) : sorted.length === 0 ? (
          <div className="py-16 px-6 text-center">
            <p className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>
              {view === "needs_reply" ? "Nobody is waiting on a reply" : searchQuery ? "No matches" : "No conversations here"}
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--haip-fg-subtle)" }}>
              {view ? "Try the All filter to see every conversation." : "New messages will appear here."}
            </p>
          </div>
        ) : sorted.map(conv => {
          const isActive = conv.id === activeId;
          const isChecked = selected.has(conv.id);
          const displayName = conv.guest_name || conv.guest_phone || "Guest";
          const status = statusFor(conv);
          const unread = conv.unread_count ?? 0;
          // Fall back to this conversation's own channel if the server
          // didn't send the guest's full channel list.
          const own = toGuestChannel(conv.channel);
          const channels = conv.guest_channels?.length ? conv.guest_channels : own ? [own] : [];

          return (
            <div
              key={conv.id}
              role="button"
              tabIndex={0}
              onClick={() => isSelecting ? toggleSelect(conv.id, { stopPropagation: () => {} } as React.MouseEvent) : onSelect(conv.id)}
              onKeyDown={e => { if (e.key === "Enter") onSelect(conv.id); }}
              className={cn(
                compact ? "py-1.5" : "py-2.5",
                "w-full text-left px-3 transition-colors group relative cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary",
                isActive ? "bg-primary/10" : "hover:bg-[color:var(--muted)]",
              )}
              style={{ borderBottom: "1px solid var(--haip-border)" }}
            >
              {!isSelecting && (
                <div className="absolute right-2 top-2 hidden group-hover:flex items-center gap-1 rounded-lg border shadow-sm px-1 py-1 z-10"
                  style={{ background: "var(--haip-card)", borderColor: "var(--haip-border)" }}>
                  {conv.guest_phone && onCall && (
                    <button type="button" onClick={e => { e.stopPropagation(); onCall(conv.guest_phone); }}
                      disabled={callingNumber === conv.guest_phone} title="Call"
                      className="p-1 rounded hover:bg-[var(--haip-surface)] text-[var(--haip-status-success-fg)] disabled:opacity-50">
                      {callingNumber === conv.guest_phone ? <Loader2 size={12} className="animate-spin" /> : <Phone size={12} />}
                    </button>
                  )}
                  <button type="button" onClick={e => { e.stopPropagation(); onSelect(conv.id); }} title="Reply"
                    className="p-1 rounded hover:bg-[var(--haip-surface)] text-primary">
                    <Reply size={12} />
                  </button>
                  {onArchive && (
                    <button type="button" onClick={e => { e.stopPropagation(); onArchive(conv.id); }} title="Resolve"
                      className="p-1 rounded hover:bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)]">
                      <Archive size={12} />
                    </button>
                  )}
                </div>
              )}

              <div className="flex items-start gap-3">
                {/* Avatar with every channel this guest has used pinned to its bottom edge */}
                <div className="flex-shrink-0 w-10 relative mb-1.5">
                  {(isSelecting || isChecked) ? (
                    <span onClick={e => toggleSelect(conv.id, e)}>
                      {isChecked ? <CheckSquare size={32} className="text-primary" /> : <Square size={32} className="text-[var(--haip-border-strong)]" />}
                    </span>
                  ) : (
                    <span
                      onClick={e => { if (e.shiftKey) toggleSelect(conv.id, e); }}
                      className={cn("w-10 h-10 rounded-full flex items-center justify-center text-[13px] font-bold", avatarTintClass(displayName || "?"))}
                    >
                      {avatarInitials(displayName || "?")}
                    </span>
                  )}
                  {!(isSelecting || isChecked) && <AvatarChannelBadges channels={channels} size={16} />}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1 min-w-0">
                      {conv.is_vip && <Star size={10} className="flex-shrink-0 text-amber-400 fill-amber-400" />}
                      <span className={cn("text-sm truncate", unread > 0 ? "font-extrabold" : "font-semibold")} style={{ color: "var(--haip-fg)" }}>
                        {displayName}
                      </span>
                      {conv.ad_title && (
                        <span title={`From ad: ${conv.ad_title}`} className="flex-shrink-0 text-[9px] font-bold text-pink-600 bg-pink-50 rounded px-1 uppercase">Ad</span>
                      )}
                    </span>
                    <span className={cn("text-[11px] flex-shrink-0 tabular-nums", unread > 0 ? "font-bold text-primary" : "")}
                      style={unread > 0 ? undefined : { color: "var(--haip-fg-subtle)" }}>
                      {conv.last_message_at ? timeAgo(conv.last_message_at) : ""}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2 mt-0.5">
                    <p className={cn("text-[13px] truncate", unread > 0 ? "font-semibold" : "")}
                      style={{ color: unread > 0 ? "var(--haip-fg)" : "var(--haip-fg-subtle)" }}>
                      {conv.last_message || "No messages yet"}
                    </p>
                    {unread > 0 ? (
                      <span className="flex-shrink-0 min-w-[18px] h-[18px] px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center tabular-nums">
                        {unread > 99 ? "99+" : unread}
                      </span>
                    ) : conv.assigned_owner_name ? (
                      <span title={`Owner: ${conv.assigned_owner_name}`}
                        className="flex-shrink-0 w-5 h-5 rounded-full bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)] text-[9px] font-bold flex items-center justify-center">
                        {conv.assigned_owner_name[0]?.toUpperCase()}
                      </span>
                    ) : null}
                  </div>
                  {status && (
                    <span className={cn(compact ? "mt-0.5" : "mt-1.5", "inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full", TONE[status.tone])}>
                      <span className="w-1.5 h-1.5 rounded-full bg-current" />
                      {status.label}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {onLoadMore && !isLoading && (
          <div className="flex justify-center py-3">
            <button onClick={onLoadMore} disabled={isLoadingMore}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-50"
              style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}>
              {isLoadingMore ? <><Loader2 size={12} className="animate-spin" /> Loading…</> : "Load more"}
            </button>
          </div>
        )}
        <div className="h-4" />
      </div>
    </div>
  );
}
