"use client";
import { Phone, MessageSquare, Calendar, MoreHorizontal, AlertTriangle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { GuestAvatar } from "./GuestAvatar";

// K4: color palette for assignee avatars — consistent hash → color
const AVATAR_PALETTE = [
  "bg-purple-500", "bg-blue-500", "bg-teal-500", "bg-green-500",
  "bg-amber-500", "bg-orange-500", "bg-rose-500", "bg-pink-500",
  "bg-indigo-500", "bg-cyan-500", "bg-lime-500", "bg-emerald-500",
];

function hashColor(userId: string): string {
  let h = 0;
  for (let i = 0; i < userId.length; i++) h = (h * 31 + userId.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length];
}

// K5: age-bucket → left-edge stripe color
function ageStripeColor(enteredAt?: string | null): string {
  if (!enteredAt) return "bg-gray-200";
  const days = (Date.now() - new Date(enteredAt).getTime()) / 86_400_000;
  if (days < 1)  return "bg-teal-400";
  if (days < 3)  return "bg-yellow-400";
  if (days < 7)  return "bg-orange-400";
  return "bg-red-500";
}

function ageLabel(enteredAt?: string | null): string {
  if (!enteredAt) return "Age unknown";
  const diff = Date.now() - new Date(enteredAt).getTime();
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 24) return `In this stage for ${hours}h`;
  const days = Math.floor(diff / 86_400_000);
  return `In this stage for ${days}d`;
}

// K6: SLA chip
function SlaChip({ slaState, elapsedSeconds }: { slaState?: string; elapsedSeconds?: number }) {
  if (!slaState || slaState === "safe") return null;
  const mins = elapsedSeconds != null ? Math.floor(elapsedSeconds / 60) : null;
  const label = mins != null
    ? slaState === "breach" ? `⏱ -${mins}m` : `⏱ ${mins}m`
    : "⏱ SLA";
  return (
    <span className={cn(
      "inline-flex items-center text-[9px] font-bold px-1.5 py-0.5 rounded-full",
      slaState === "breach"  ? "bg-red-100 text-red-600"
      : slaState === "warning" ? "bg-amber-100 text-amber-600"
      : "bg-teal-100 text-teal-600"
    )}>
      {label}
    </span>
  );
}

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
  // K4
  assigned_to?: string;
  assignee_name?: string;
  // K5
  current_stage_entered_at?: string;
  // K6
  sla_state?: string;
  sla_elapsed_seconds?: number;
}

interface KanbanCardProps {
  card: KanbanCardData;
  onClick?: (id: string) => void;
  onAssign?: (id: string, userId: string | null) => void;
  draggable?: boolean;
  className?: string;
}

function formatDate(iso?: string) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function KanbanCard({ card, onClick, onAssign, draggable, className }: KanbanCardProps) {
  const stripe = ageStripeColor(card.current_stage_entered_at);
  const ageTip  = ageLabel(card.current_stage_entered_at);

  return (
    <div
      draggable={draggable}
      onClick={() => onClick?.(card.id)}
      className={cn(
        "bg-white border border-gray-100 rounded-xl shadow-sm cursor-pointer overflow-hidden",
        "hover:shadow-md hover:border-gray-200 transition-all",
        "active:scale-[0.98] flex",
        draggable && "cursor-grab active:cursor-grabbing",
        className
      )}
    >
      {/* K5: left-edge age stripe */}
      <div title={ageTip} className={cn("w-1 flex-shrink-0", stripe)} />

      <div className="flex-1 p-3">
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

          {/* K4: assignee chip */}
          {card.assigned_to ? (
            <button
              onClick={e => { e.stopPropagation(); onAssign?.(card.id, null); }}
              title={card.assignee_name ?? "Assigned — click to unassign"}
              className={cn(
                "w-6 h-6 rounded-full flex items-center justify-center text-white text-[9px] font-bold flex-shrink-0",
                hashColor(card.assigned_to)
              )}
            >
              {(card.assignee_name ?? "?")[0].toUpperCase()}
            </button>
          ) : (
            <span
              title="Unassigned"
              className="flex items-center gap-0.5 text-[9px] font-bold text-red-500 bg-red-50 border border-red-200 px-1.5 py-0.5 rounded-full flex-shrink-0"
            >
              <AlertTriangle size={8} /> Unassigned
            </span>
          )}
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

        {/* Footer: channel + K6 SLA badge */}
        <div className="flex items-center gap-1.5 justify-between">
          <div className="flex items-center gap-1">
            {card.channel === "whatsapp" && <MessageSquare size={12} className="text-green-500" />}
            {card.channel === "call" && <Phone size={12} className="text-blue-500" />}
          </div>
          <SlaChip slaState={card.sla_state} elapsedSeconds={card.sla_elapsed_seconds} />
        </div>
      </div>
    </div>
  );
}
