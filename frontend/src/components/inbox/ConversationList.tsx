"use client";
import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { ChannelIcon } from "./ChannelIcon";
import { Sparkles, ArrowUpDown, CheckSquare, Square, CheckCheck, Archive, Trash2, X } from "lucide-react";
import type { ConversationSummary } from "@/store/inbox";

type SortMode = "smart" | "recent" | "unread";

const SORT_LABELS: Record<SortMode, string> = {
  smart:  "Smart",
  recent: "Recent",
  unread: "Unread first",
};

interface ConversationListProps {
  conversations: ConversationSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onSortChange?: (mode: SortMode) => void;
  channelFilter?: string;
  className?: string;
  // W13: bulk actions
  onBulkResolve?: (ids: string[]) => void;
  onBulkMarkRead?: (ids: string[]) => void;
  onBulkAssign?: (ids: string[]) => void;
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
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
}: ConversationListProps) {
  const [sort, setSort] = useState<SortMode>(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem("inbox_sort") as SortMode) ?? "smart";
    }
    return "smart";
  });
  const [showSortMenu, setShowSortMenu] = useState(false);
  // W13: multi-select state
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

  const filtered = channelFilter
    ? conversations.filter(c => c.channel === channelFilter)
    : conversations;

  // Client-side sort (mirrors backend smart/recent/unread)
  const sorted = [...filtered].sort((a, b) => {
    if (sort === "unread") {
      const diff = (b.unread_count ?? 0) - (a.unread_count ?? 0);
      if (diff !== 0) return diff;
    } else if (sort === "smart") {
      const aUnread = (a.unread_count ?? 0) > 0 ? 0 : 1;
      const bUnread = (b.unread_count ?? 0) > 0 ? 0 : 1;
      if (aUnread !== bUnread) return aUnread - bUnread;
    }
    return new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime();
  });

  return (
    <div className={cn("flex flex-col overflow-y-auto", className)}>
      {/* W13: bulk action toolbar */}
      {isSelecting && (
        <div className="px-3 py-2 border-b border-indigo-100 bg-indigo-50 flex items-center gap-2 flex-shrink-0">
          <span className="text-xs font-semibold text-indigo-700">{selected.size} selected</span>
          <button onClick={selectAll} className="text-[11px] text-indigo-600 hover:underline">All</button>
          <div className="flex-1" />
          {onBulkMarkRead && (
            <button
              onClick={() => { onBulkMarkRead(Array.from(selected)); clearSelection(); }}
              title="Mark as read"
              className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg bg-white border border-indigo-200 text-indigo-600 hover:bg-indigo-100"
            >
              <CheckCheck size={11} /> Read
            </button>
          )}
          {onBulkResolve && (
            <button
              onClick={() => { onBulkResolve(Array.from(selected)); clearSelection(); }}
              title="Resolve conversations"
              className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg bg-white border border-indigo-200 text-indigo-600 hover:bg-indigo-100"
            >
              <Archive size={11} /> Resolve
            </button>
          )}
          <button onClick={clearSelection} className="text-gray-400 hover:text-gray-600 ml-1">
            <X size={13} />
          </button>
        </div>
      )}
      {/* W11: sort indicator */}
      <div className="px-4 py-1.5 border-b border-gray-50 flex items-center justify-between relative">
        <span className="text-[10px] text-gray-400">Sort: <span className="font-medium text-gray-600">{SORT_LABELS[sort]}</span></span>
        <button
          onClick={() => setShowSortMenu(v => !v)}
          className="text-gray-400 hover:text-gray-600 transition-colors"
          title="Change sort order"
        >
          <ArrowUpDown size={12} />
        </button>
        {showSortMenu && (
          <div className="absolute top-full right-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-lg z-10 overflow-hidden">
            {(Object.keys(SORT_LABELS) as SortMode[]).map(m => (
              <button
                key={m}
                onClick={() => { setSort(m); setShowSortMenu(false); }}
                className={cn(
                  "w-full text-left px-4 py-2 text-xs transition-colors",
                  sort === m ? "bg-indigo-50 text-indigo-700 font-medium" : "text-gray-700 hover:bg-gray-50"
                )}
              >
                {SORT_LABELS[m]}
              </button>
            ))}
          </div>
        )}
      </div>
      {sorted.length === 0 && (
        <div className="py-16 text-center text-sm text-gray-400">
          No conversations yet
        </div>
      )}
      {sorted.map(conv => {
        const isActive = conv.id === activeId;
        const isChecked = selected.has(conv.id);
        return (
          <button
            key={conv.id}
            onClick={() => isSelecting ? toggleSelect(conv.id, { stopPropagation: () => {} } as any) : onSelect(conv.id)}
            className={cn(
              "w-full text-left px-4 py-3.5 border-b border-gray-50 transition-colors group",
              isActive ? "bg-indigo-50/70" : "hover:bg-gray-50",
              isChecked && "bg-indigo-50"
            )}
          >
            <div className="flex items-start gap-3">
              {/* W13: checkbox (shows on hover or when selecting) */}
              <div
                className={cn("flex-shrink-0 mt-0.5", isSelecting || isChecked ? "block" : "hidden group-hover:block")}
                onClick={e => toggleSelect(conv.id, e)}
              >
                {isChecked
                  ? <CheckSquare size={16} className="text-indigo-500" />
                  : <Square size={16} className="text-gray-300" />
                }
              </div>
              {/* Avatar — hide when checkbox visible */}
              <div className={cn(
                "w-9 h-9 rounded-full bg-gradient-to-br from-indigo-400 to-blue-500 flex items-center justify-center text-white text-sm font-bold flex-shrink-0",
                (isSelecting || isChecked) ? "hidden" : "group-hover:hidden block"
              )}>
                {conv.guest_name?.[0]?.toUpperCase() ?? "?"}
              </div>

              <div className="flex-1 min-w-0">
                {/* Name + time */}
                <div className="flex items-center justify-between gap-1 mb-0.5">
                  <span className={cn(
                    "text-sm font-semibold truncate",
                    isActive ? "text-indigo-700" : "text-gray-900"
                  )}>
                    {conv.guest_name || conv.guest_phone}
                  </span>
                  <span className="text-[10px] text-gray-400 flex-shrink-0">
                    {timeAgo(conv.last_message_at)}
                  </span>
                </div>

                {/* Last message */}
                <div className="flex items-center gap-1.5 mb-1">
                  <ChannelIcon channel={conv.channel} className="w-4 h-4 rounded" />
                  <p className={cn(
                    "text-xs truncate",
                    conv.unread_count > 0 ? "text-gray-800 font-medium" : "text-gray-500"
                  )}>
                    {conv.last_message}
                  </p>
                </div>

                {/* Badges */}
                <div className="flex items-center gap-1.5">
                  {conv.status !== "open" && (
                    <span className={cn(
                      "text-[10px] font-medium px-1.5 py-0.5 rounded capitalize",
                      conv.status === "resolved" ? "bg-gray-100 text-gray-500" : "bg-amber-100 text-amber-600"
                    )}>
                      {conv.status}
                    </span>
                  )}
                  {conv.has_ai_draft && (
                    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-600 flex items-center gap-1">
                      <Sparkles size={9} /> AI draft
                    </span>
                  )}
                  {conv.unread_count > 0 && (
                    <span className="ml-auto bg-indigo-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center flex-shrink-0">
                      {conv.unread_count > 9 ? "9+" : conv.unread_count}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
