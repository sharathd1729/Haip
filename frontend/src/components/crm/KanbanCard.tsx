"use client";
import { Phone, MessageSquare, Calendar, MoreHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { GuestAvatar } from "./GuestAvatar";

export interface KanbanCardData {
  id: string;
  guest_name?: string;
  guest_phone: string;
  property_name?: string;
  check_in?: string;
  check_out?: string;
  channel?: string;
  budget?: number;
  last_activity?: string;
  tags?: string[];
}

interface KanbanCardProps {
  card: KanbanCardData;
  onClick?: (id: string) => void;
  draggable?: boolean;
  className?: string;
}

function formatDate(iso?: string) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function KanbanCard({ card, onClick, draggable, className }: KanbanCardProps) {
  return (
    <div
      draggable={draggable}
      onClick={() => onClick?.(card.id)}
      className={cn(
        "bg-white border border-gray-100 rounded-xl p-3 shadow-sm cursor-pointer",
        "hover:shadow-md hover:border-gray-200 transition-all",
        "active:scale-[0.98]",
        draggable && "cursor-grab active:cursor-grabbing",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <GuestAvatar name={card.guest_name} phone={card.guest_phone} size="sm" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-900 truncate">
              {card.guest_name || card.guest_phone}
            </p>
            {card.property_name && (
              <p className="text-xs text-gray-400 truncate">{card.property_name}</p>
            )}
          </div>
        </div>
        <button
          onClick={e => e.stopPropagation()}
          className="text-gray-300 hover:text-gray-500 transition-colors flex-shrink-0"
        >
          <MoreHorizontal size={14} />
        </button>
      </div>

      {/* Date range */}
      {(card.check_in || card.check_out) && (
        <div className="flex items-center gap-1 text-[11px] text-gray-500 mb-2">
          <Calendar size={11} className="text-gray-400" />
          {formatDate(card.check_in)} {card.check_out && `– ${formatDate(card.check_out)}`}
        </div>
      )}

      {/* Budget */}
      {card.budget && (
        <p className="text-sm font-semibold text-gray-800 mb-2">
          ₹{card.budget.toLocaleString("en-IN")}
        </p>
      )}

      {/* Tags */}
      {card.tags && card.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {card.tags.slice(0, 3).map(tag => (
            <span key={tag} className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded-md">
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* Channel icons */}
      <div className="flex items-center gap-1.5 justify-end">
        {card.channel === "whatsapp" && <MessageSquare size={12} className="text-green-500" />}
        {card.channel === "call" && <Phone size={12} className="text-blue-500" />}
      </div>
    </div>
  );
}
