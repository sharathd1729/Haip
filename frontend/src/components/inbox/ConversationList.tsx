"use client";
import { cn } from "@/lib/utils";
import { ChannelIcon } from "./ChannelIcon";
import { Sparkles } from "lucide-react";
import type { ConversationSummary } from "@/store/inbox";

interface ConversationListProps {
  conversations: ConversationSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  channelFilter?: string;
  className?: string;
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
  channelFilter,
  className,
}: ConversationListProps) {
  const filtered = channelFilter
    ? conversations.filter(c => c.channel === channelFilter)
    : conversations;

  return (
    <div className={cn("flex flex-col overflow-y-auto", className)}>
      {filtered.length === 0 && (
        <div className="py-16 text-center text-sm text-gray-400">
          No conversations yet
        </div>
      )}
      {filtered.map(conv => {
        const isActive = conv.id === activeId;
        return (
          <button
            key={conv.id}
            onClick={() => onSelect(conv.id)}
            className={cn(
              "w-full text-left px-4 py-3.5 border-b border-gray-50 transition-colors group",
              isActive ? "bg-teal-50/70" : "hover:bg-gray-50"
            )}
          >
            <div className="flex items-start gap-3">
              {/* Avatar */}
              <div className="w-9 h-9 rounded-full bg-gradient-to-br from-teal-400 to-blue-500 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
                {conv.guest_name?.[0]?.toUpperCase() ?? "?"}
              </div>

              <div className="flex-1 min-w-0">
                {/* Name + time */}
                <div className="flex items-center justify-between gap-1 mb-0.5">
                  <span className={cn(
                    "text-sm font-semibold truncate",
                    isActive ? "text-teal-700" : "text-gray-900"
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
                    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-teal-100 text-teal-600 flex items-center gap-1">
                      <Sparkles size={9} /> AI draft
                    </span>
                  )}
                  {conv.unread_count > 0 && (
                    <span className="ml-auto bg-teal-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center flex-shrink-0">
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
