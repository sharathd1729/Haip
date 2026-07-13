"use client";
import { useState, useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";
import { ChannelIcon } from "./ChannelIcon";
import {
  Sparkles, ArrowUpDown, CheckSquare, Square, CheckCheck,
  Archive, X, Star, Bed, Phone,
} from "lucide-react";
import type { ConversationSummary } from "@/store/inbox";

type SortMode = "smart" | "recent" | "unread";

const SORT_LABELS: Record<SortMode, string> = {
  smart:  "Smart",
  recent: "Recent",
  unread: "Unread first",
};

// Extended summary with optional enrichment fields
export interface ConversationSummaryExt extends ConversationSummary {
  is_vip?: boolean;
  has_active_booking?: boolean;
  needs_attention?: boolean;
  assigned_to?: string;
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

// Channel accent color for left border
const CHANNEL_BORDER: Record<string, string> = {
  whatsapp:  "border-l-2 border-l-green-400",
  instagram: "border-l-2 border-l-pink-400",
  web:       "border-l-2 border-l-blue-400",
  sms:       "border-l-2 border-l-amber-400",
};

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

  const filtered = useMemo(
    () => channelFilter
      ? conversations.filter(c => c.channel === channelFilter)
      : conversations,
    [conversations, channelFilter]
  );

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
        const channelBorder = CHANNEL_BORDER[conv.channel] ?? "";

        return (
          <button
            key={conv.id}
            onClick={() => isSelecting
              ? toggleSelect(conv.id, { stopPropagation: () => {} } as React.MouseEvent)
              : onSelect(conv.id)
            }
            className={cn(
              "w-full text-left px-3 py-3 border-b border-gray-50 transition-all group",
              channelBorder,
              isActive
                ? "bg-teal-50/80"
                : "hover:bg-gray-50/80",
              isChecked && "bg-teal-50",
              conv.needs_attention && !isActive && "bg-amber-50/40"
            )}
          >
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
                  <div className={cn(
                    "w-9 h-9 rounded-full bg-gradient-to-br flex items-center justify-center text-white text-sm font-bold",
                    gradient,
                    "group-hover:ring-2 group-hover:ring-teal-200 transition-all"
                  )}>
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
                    <span className={cn(
                      "text-sm font-semibold truncate",
                      isActive ? "text-teal-700" : "text-gray-900"
                    )}>
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
                <div className="flex items-center gap-1">
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
                    <span className="text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-teal-100 text-teal-600 flex items-center gap-0.5 flex-shrink-0">
                      <Sparkles size={8} />Draft
                    </span>
                  )}
                  {conv.unread_count > 0 && (
                    <span className="ml-auto bg-teal-500 text-white text-[9px] font-bold rounded-full min-w-[16px] h-4 flex items-center justify-center px-1 flex-shrink-0">
                      {conv.unread_count > 99 ? "99+" : conv.unread_count}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </button>
        );
      })}

      {/* Bottom padding for mobile nav */}
      <div className="h-4 flex-shrink-0" />
    </div>
  );
}
