"use client";
import { useState, useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";
import { ChannelIcon } from "./ChannelIcon";
import { Sparkles, ArrowUpDown, CheckSquare, Square, CheckCheck, Archive, X, Star, Phone, Loader2, Clock, Bot, PhoneMissed, AlertTriangle, Flame, Search, Reply } from "@/lib/icons";
import { Bed, UserCheck } from "lucide-react";
import type { ConversationSummary } from "@/store/inbox";

type SortMode = "smart" | "recent" | "unread";

const SORT_LABELS: Record<SortMode, string> = {
  smart:  "Smart",
  recent: "Recent",
  unread: "Unread first",
};

// HAIP Inbox UI-fidelity pass, ticket 4: prototype's quick-filter chip row
// (Assigned to Me / Waiting Reply / AI Needs Review / Missed Calls).
type QuickFilter = "all" | "assigned_to_me" | "waiting_reply" | "ai_needs_review" | "missed_calls";
type CompletenessTab = "all" | "complete" | "needs_info";

// Below this, a lead has at most an Instagram handle -- no real channel
// identity yet. Matches _COMPLETENESS_MAP's whatsapp_number tier (60) on
// the backend (leads_service.py).
const COMPLETE_THRESHOLD = 60;

// Extended summary with optional enrichment fields
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
  channelFilter?: string;
  className?: string;
  onBulkResolve?: (ids: string[]) => void;
  onBulkMarkRead?: (ids: string[]) => void;
  onBulkAssign?: (ids: string[]) => void;
  /** Present (non-undefined) whenever another page of older conversations
   * exists to fetch -- absent once the list has reached the end. */
  onLoadMore?: () => void;
  isLoadingMore?: boolean;
  /** Signed-in user's id, for the "Assigned to Me" quick filter. */
  currentUserId?: string | null;
  /** HAIP Inbox full-parity pass, ticket 2: archive a single conversation
   * from the hover quick-actions row (PATCH /conversations/{id}). */
  onArchive?: (id: string) => void;
  /** Mcube-disconnect + outbound-calling pass: trigger a real IVR-mediated
   * outbound call (POST /calls/click-to-call) instead of opening the
   * device's own dialer. */
  onCall?: (guestNumber: string) => void;
  /** guest_number currently mid-flight, to show a spinner on that row's
   * call button and prevent double-firing. */
  callingNumber?: string | null;
}

// Deterministic color from a string (for guest avatar backgrounds)
function nameColor(name: string | null | undefined): string {
  const colors = [
    "from-teal-400 to-emerald-500",
    "from-blue-400 to-indigo-500",
    "from-violet-400 to-purple-500",
    "from-rose-400 to-pink-500",
    "from-amber-400 to-orange-500",
    "from-cyan-400 to-sky-500",
  ];
  if (!name) return colors[0];   // ← guard: undefined/null/empty → teal default
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) & 0xffff;
  return colors[hash % colors.length];
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

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onSortChange,
  channelFilter,
  className,
  onBulkResolve,
  onBulkMarkRead,
  onBulkAssign,
  onLoadMore,
  isLoadingMore,
  currentUserId,
  onArchive,
  onCall,
  callingNumber,
}: ConversationListProps) {
  const [sort, setSort] = useState<SortMode>(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem("inbox_sort") as SortMode) ?? "smart";
    }
    return "smart";
  });
  const [showSortMenu, setShowSortMenu] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const isSelecting = selected.size > 0;
  const [quickFilter, setQuickFilter] = useState<QuickFilter>("all");
  const [completenessTab, setCompletenessTab] = useState<CompletenessTab>("all");
  const [searchQuery, setSearchQuery] = useState("");

  const toggleSelect = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(sorted.map(c => c.id)));
  const clearSelection = () => setSelected(new Set());

  useEffect(() => {
    localStorage.setItem("inbox_sort", sort);
    onSortChange?.(sort);
  }, [sort, onSortChange]);

  const channelFiltered = useMemo(
    () => channelFilter
      ? conversations.filter(c => c.channel === channelFilter)
      : conversations,
    [conversations, channelFilter]
  );

  // HAIP Inbox full-parity pass, ticket 2: search filters over the
  // already-loaded page client-side (guest name/phone, last message
  // preview, property name) -- same idiom as channelFiltered. Sits right
  // after the channel select so every downstream count (tabs, quick
  // filters) reflects the search term too.
  const searchFiltered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return channelFiltered;
    return channelFiltered.filter(c =>
      (c.guest_name ?? "").toLowerCase().includes(q) ||
      (c.guest_phone ?? "").toLowerCase().includes(q) ||
      (c.last_message ?? "").toLowerCase().includes(q) ||
      (c.property_name ?? "").toLowerCase().includes(q)
    );
  }, [channelFiltered, searchQuery]);

  // HAIP Inbox UI-fidelity pass, ticket 4: quick-filter chip counts are
  // computed off searchFiltered (after channel-select + search, before the
  // tab/quick-filter itself) -- so a count reflects "how many if I picked
  // this filter right now", same scope the prototype's counts use.
  const quickFilterCounts = useMemo(() => ({
    assigned_to_me:  searchFiltered.filter(c => !!currentUserId && c.assigned_to === currentUserId).length,
    waiting_reply:   searchFiltered.filter(c => c.is_waiting_reply).length,
    ai_needs_review: searchFiltered.filter(c => c.has_ai_draft).length,
    missed_calls:    searchFiltered.filter(c => c.channel === "voice").length,
  }), [searchFiltered, currentUserId]);

  const completenessCounts = useMemo(() => ({
    complete:   searchFiltered.filter(c => (c.profile_completeness_pct ?? 0) >= COMPLETE_THRESHOLD).length,
    needs_info: searchFiltered.filter(c => (c.profile_completeness_pct ?? 0) < COMPLETE_THRESHOLD).length,
  }), [searchFiltered]);

  const tabFiltered = useMemo(() => {
    if (completenessTab === "complete") return searchFiltered.filter(c => (c.profile_completeness_pct ?? 0) >= COMPLETE_THRESHOLD);
    if (completenessTab === "needs_info") return searchFiltered.filter(c => (c.profile_completeness_pct ?? 0) < COMPLETE_THRESHOLD);
    return searchFiltered;
  }, [searchFiltered, completenessTab]);

  const filtered = useMemo(() => {
    switch (quickFilter) {
      case "assigned_to_me":  return tabFiltered.filter(c => !!currentUserId && c.assigned_to === currentUserId);
      case "waiting_reply":   return tabFiltered.filter(c => c.is_waiting_reply);
      case "ai_needs_review": return tabFiltered.filter(c => c.has_ai_draft);
      case "missed_calls":    return tabFiltered.filter(c => c.channel === "voice");
      default:                return tabFiltered;
    }
  }, [tabFiltered, quickFilter, currentUserId]);

  const sorted = useMemo(() => [...filtered].sort((a, b) => {
    if (sort === "unread") {
      const diff = (b.unread_count ?? 0) - (a.unread_count ?? 0);
      if (diff !== 0) return diff;
    } else if (sort === "smart") {
      // VIP first, then unread, then attention-needed, then recent
      if (a.is_vip !== b.is_vip) return a.is_vip ? -1 : 1;
      if (a.needs_attention !== b.needs_attention) return a.needs_attention ? -1 : 1;
      const aUnread = (a.unread_count ?? 0) > 0 ? 0 : 1;
      const bUnread = (b.unread_count ?? 0) > 0 ? 0 : 1;
      if (aUnread !== bUnread) return aUnread - bUnread;
    }
    return new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime();
  }), [filtered, sort]);

  return (
    <div className={cn("flex flex-col overflow-y-auto haip-scrollbar", className)}>
      {/* HAIP Inbox full-parity pass, ticket 2: search over the already-loaded
          page -- guest name/phone, last message preview, property name. */}
      <div className="px-3 py-2 border-b flex-shrink-0" style={{ borderColor: "var(--haip-border)" }}>
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: "var(--haip-fg-subtle)" }} />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search guest, message or property…"
            className="w-full pl-8 pr-3 py-1.5 rounded-lg text-xs outline-none border"
            style={{ borderColor: "var(--haip-border)", background: "var(--card)", color: "var(--haip-fg)" }}
          />
        </div>
      </div>

      {/* HAIP Inbox UI-fidelity pass, ticket 4: completeness tabs (prototype's
          CRM Leads/Unqualified, reframed around live profile-completeness
          rather than a fabricated "CRM lead" conversion event). */}
      <div className="px-3 py-2 border-b flex gap-1 overflow-x-auto scrollbar-hide flex-shrink-0" style={{ borderColor: "var(--haip-border)" }}>
        {([
          { key: "all" as const,        label: `All (${searchFiltered.length})` },
          { key: "complete" as const,   label: `Complete (${completenessCounts.complete})` },
          { key: "needs_info" as const, label: `Needs Info (${completenessCounts.needs_info})` },
        ]).map(t => (
          <button
            key={t.key}
            onClick={() => setCompletenessTab(t.key)}
            className="flex-shrink-0 px-2.5 py-1 rounded-md text-[11px] font-medium whitespace-nowrap transition-colors"
            style={completenessTab === t.key
              ? { background: "var(--primary)", color: "var(--primary-foreground)" }
              : { color: "var(--haip-fg-muted)" }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Quick-filter chips: Assigned to Me / Waiting Reply / AI Needs Review / Missed Calls */}
      <div className="p-2 border-b grid grid-cols-2 gap-1 flex-shrink-0" style={{ borderColor: "var(--haip-border)" }}>
        {([
          { key: "assigned_to_me" as const,  label: "Assigned to Me",  icon: UserCheck,    count: quickFilterCounts.assigned_to_me },
          { key: "waiting_reply" as const,   label: "Waiting Reply",   icon: Clock,        count: quickFilterCounts.waiting_reply },
          { key: "ai_needs_review" as const, label: "AI Needs Review", icon: Bot,          count: quickFilterCounts.ai_needs_review },
          { key: "missed_calls" as const,    label: "Missed Calls",    icon: PhoneMissed,  count: quickFilterCounts.missed_calls },
        ]).map(f => {
          const Icon = f.icon;
          const isActive = quickFilter === f.key;
          return (
            <button
              key={f.key}
              onClick={() => setQuickFilter(isActive ? "all" : f.key)}
              className="ibx-pill px-2.5 py-1.5 text-left flex items-center justify-between gap-1 text-[11px] transition-colors"
              style={isActive
                ? f.key === "ai_needs_review"
                  ? { background: "var(--ibx-iris)", color: "#fff", boxShadow: "0 6px 18px rgba(91,91,206,0.25)" }
                  : { background: "var(--ibx-grad)", color: "#fff", boxShadow: "var(--ibx-shadow-glow)" }
                : { color: "var(--haip-fg-muted)", background: "var(--haip-card)" }}
            >
              <span className="flex items-center gap-1.5 truncate">
                <Icon size={13} className="flex-shrink-0" />
                {f.label}
              </span>
              <span
                className="font-mono text-[10px] font-bold px-1.5 rounded-full flex-shrink-0"
                style={{ background: isActive ? "rgba(255,255,255,0.25)" : "var(--muted)", color: "inherit" }}
              >
                {f.count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Bulk action toolbar */}
      {isSelecting && (
        <div className="px-3 py-2 border-b border-teal-100 bg-teal-50 flex items-center gap-2 flex-shrink-0">
          <span className="text-xs font-semibold text-teal-700">{selected.size} selected</span>
          <button onClick={selectAll} className="text-[11px] text-teal-600 hover:underline">All</button>
          <div className="flex-1" />
          {onBulkMarkRead && (
            <button
              onClick={() => { onBulkMarkRead(Array.from(selected)); clearSelection(); }}
              className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg bg-white border border-teal-200 text-teal-600 hover:bg-teal-100"
            >
              <CheckCheck size={11} /> Read
            </button>
          )}
          {onBulkResolve && (
            <button
              onClick={() => { onBulkResolve(Array.from(selected)); clearSelection(); }}
              className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg bg-white border border-teal-200 text-teal-600 hover:bg-teal-100"
            >
              <Archive size={11} /> Resolve
            </button>
          )}
          <button onClick={clearSelection} className="text-gray-400 hover:text-gray-600 ml-1">
            <X size={13} />
          </button>
        </div>
      )}

      {/* Sort bar */}
      <div className="px-4 py-1.5 border-b border-gray-50 flex items-center justify-between relative flex-shrink-0">
        <span className="text-[10px] text-gray-400">
          Sort: <span className="font-medium text-gray-600">{SORT_LABELS[sort]}</span>
          {filtered.length > 0 && (
            <span className="ml-1.5 text-gray-300">· {filtered.length}</span>
          )}
        </span>
        <button
          onClick={() => setShowSortMenu(v => !v)}
          className="text-gray-400 hover:text-gray-600 transition-colors"
          title="Change sort order"
        >
          <ArrowUpDown size={12} />
        </button>
        {showSortMenu && (
          <div className="absolute top-full right-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-lg z-20 overflow-hidden">
            {(Object.keys(SORT_LABELS) as SortMode[]).map(m => (
              <button
                key={m}
                onClick={() => { setSort(m); setShowSortMenu(false); }}
                className={cn(
                  "w-full text-left px-4 py-2 text-xs transition-colors",
                  sort === m ? "bg-teal-50 text-teal-700 font-medium" : "text-gray-700 hover:bg-gray-50"
                )}
              >
                {SORT_LABELS[m]}
              </button>
            ))}
          </div>
        )}
      </div>

      {sorted.length === 0 && (
        <div className="py-16 text-center">
          <div className="text-3xl mb-2">💬</div>
          <p className="text-sm text-gray-400">No conversations yet</p>
          <p className="text-xs text-gray-300 mt-1">Messages will appear here</p>
        </div>
      )}

      {sorted.map(conv => {
        const isActive = conv.id === activeId;
        const isChecked = selected.has(conv.id);
        const displayName = conv.guest_name || conv.guest_phone || "";
        const initial = displayName?.[0]?.toUpperCase() ?? "?";
        const gradient = nameColor(displayName);

        return (
          <button
            key={conv.id}
            onClick={() => isSelecting
              ? toggleSelect(conv.id, { stopPropagation: () => {} } as React.MouseEvent)
              : onSelect(conv.id)
            }
            className={cn(
              "w-full text-left ibx-conv-card transition-all group relative",
              isActive && "active",
              isChecked && "bg-[var(--ibx-green-soft)]",
              conv.needs_attention && !isActive && "bg-amber-50/40"
            )}
          >
            {/* Mcube-disconnect + outbound-calling pass: Quick Call now
                triggers a real IVR-mediated outbound call (agent's phone
                rings first, then bridges to the guest) instead of opening
                the device's own dialer -- still no audio in the browser,
                still compliant with CLAUDE.md's "not a softphone" rule. */}
            {!isSelecting && (
              <div
                className="absolute right-2 top-2 hidden group-hover:flex items-center gap-1 rounded-lg border shadow-sm px-1 py-1 z-10"
                style={{ background: "var(--card)", borderColor: "var(--haip-border)" }}
              >
                {conv.guest_phone && onCall && (
                  <button
                    type="button"
                    onClick={e => { e.stopPropagation(); onCall(conv.guest_phone); }}
                    disabled={callingNumber === conv.guest_phone}
                    title="Call via IVR"
                    className="p-1 rounded hover:bg-gray-100 text-emerald-600 disabled:opacity-50"
                  >
                    {callingNumber === conv.guest_phone
                      ? <Loader2 size={12} className="animate-spin" />
                      : <Phone size={12} />}
                  </button>
                )}
                <button
                  type="button"
                  onClick={e => { e.stopPropagation(); onSelect(conv.id); }}
                  title="Quick reply"
                  className="p-1 rounded hover:bg-gray-100 text-teal-600"
                >
                  <Reply size={12} />
                </button>
                {onArchive && (
                  <button
                    type="button"
                    onClick={e => { e.stopPropagation(); onArchive(conv.id); }}
                    title="Archive"
                    className="p-1 rounded hover:bg-gray-100 text-gray-400"
                  >
                    <Archive size={12} />
                  </button>
                )}
              </div>
            )}

            <div className="flex items-start gap-2.5">
              {/* Checkbox / Avatar */}
              <div className="flex-shrink-0 relative mt-0.5">
                {(isSelecting || isChecked) ? (
                  <div onClick={e => toggleSelect(conv.id, e)}>
                    {isChecked
                      ? <CheckSquare size={32} className="text-teal-500" />
                      : <Square size={32} className="text-gray-300" />
                    }
                  </div>
                ) : (
                  <div
                    className={cn(
                      "w-9 h-9 rounded-full bg-gradient-to-br flex items-center justify-center text-white text-sm font-bold transition-all",
                      gradient,
                      !isActive && "group-hover:ring-2 group-hover:ring-[color:var(--ibx-green-soft)]"
                    )}
                    style={isActive ? { boxShadow: "0 0 0 2.5px var(--haip-card), 0 0 0 4.5px var(--ibx-green-bright)" } : undefined}
                  >
                    {initial}
                  </div>
                )}

                {/* Channel badge — bottom-right of avatar */}
                {!isSelecting && !isChecked && (
                  <div className="absolute -bottom-0.5 -right-0.5 w-4 h-4 rounded-full bg-white flex items-center justify-center">
                    <ChannelIcon channel={conv.channel} className="w-3 h-3" />
                  </div>
                )}
              </div>

              <div className="flex-1 min-w-0">
                {/* Row 1: Name + time */}
                <div className="flex items-center justify-between gap-1 mb-0.5">
                  <div className="flex items-center gap-1 min-w-0">
                    {conv.is_vip && (
                      <Star size={10} className="flex-shrink-0 text-amber-400 fill-amber-400" />
                    )}
                    <span
                      className="text-sm font-semibold truncate"
                      style={{ color: isActive ? "var(--ibx-green)" : "var(--haip-fg)" }}
                    >
                      {conv.guest_name || conv.guest_phone}
                    </span>
                    {conv.ad_title && (
                      <span
                        title={`via Ad: ${conv.ad_title}`}
                        className="flex-shrink-0 text-[9px] font-semibold text-pink-600 bg-pink-50 border border-pink-200 rounded px-1 py-0.5 uppercase tracking-wide"
                      >
                        Ad
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] text-gray-400 flex-shrink-0 tabular-nums">
                    {timeAgo(conv.last_message_at)}
                  </span>
                </div>

                {/* Row 2: Property name (if available) */}
                {conv.property_name && (
                  <div className="flex items-center gap-1 mb-0.5">
                    <Bed size={9} className="text-gray-300 flex-shrink-0" />
                    <span className="text-[10px] text-gray-400 truncate">{conv.property_name}</span>
                  </div>
                )}

                {/* Row 3: Last message preview */}
                <p className={cn(
                  "text-xs truncate mb-1",
                  conv.unread_count > 0 ? "text-gray-800 font-medium" : "text-gray-500"
                )}>
                  {conv.last_message || "No messages yet"}
                </p>

                {/* Row 4: Status badges + unread pill */}
                <div className="flex items-center gap-1 flex-wrap">
                  {conv.sla_status === "breached" && (
                    <span className="ibx-badge sla">
                      <AlertTriangle size={7} />SLA breached
                    </span>
                  )}
                  {conv.sla_status === "warning" && (
                    <span className="ibx-badge vip">
                      SLA due soon
                    </span>
                  )}
                  {conv.profile_completeness_pct != null && conv.profile_completeness_pct > 0 && (
                    <span
                      title="Lead profile completeness"
                      className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full bg-teal-50 text-teal-700 flex items-center gap-0.5 flex-shrink-0"
                    >
                      <Flame size={7} />{conv.profile_completeness_pct}%
                    </span>
                  )}
                  {conv.has_active_booking && (
                    <span className="text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-green-100 text-green-700 flex items-center gap-0.5 flex-shrink-0">
                      <Bed size={7} />Booked
                    </span>
                  )}
                  {conv.needs_attention && (
                    <span className="text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-600 flex-shrink-0">
                      ⚠ Needs reply
                    </span>
                  )}
                  {conv.status === "snoozed" && (
                    <span className="text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-500 flex-shrink-0">
                      Snoozed
                    </span>
                  )}
                  {conv.status === "resolved" && (
                    <span className="text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-400 flex-shrink-0">
                      Resolved
                    </span>
                  )}
                  {conv.has_ai_draft && (
                    <span className="ibx-badge ai">
                      <Sparkles size={8} />Draft
                    </span>
                  )}
                  {conv.unread_count > 0 && (
                    <span className="ibx-unread-pill ml-auto">
                      {conv.unread_count > 99 ? "99+" : conv.unread_count}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </button>
        );
      })}

      {/* Load more — the caller now fetches a channel-scoped page from the
          server whenever channelFilter is set (see inbox/page.tsx), so
          onLoadMore/isLoadingMore already reflect the right underlying
          query either way; no need to hide this while filtered anymore. */}
      {onLoadMore && (
        <div className="flex justify-center py-3 flex-shrink-0">
          <button
            onClick={onLoadMore}
            disabled={isLoadingMore}
            className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 transition-colors duration-150 disabled:opacity-50"
          >
            {isLoadingMore ? <><Loader2 size={12} className="animate-spin" /> Loading…</> : "Load more"}
          </button>
        </div>
      )}

      {/* Bottom padding for mobile nav */}
      <div className="h-4 flex-shrink-0" />
    </div>
  );
}
