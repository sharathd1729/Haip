import { Phone, MessageSquare, Home, Star } from "lucide-react";
import { cn } from "@/lib/utils";

export type TimelineEventType = "call" | "message" | "stay" | "inquiry" | "score";

export interface TimelineEventProps {
  type: TimelineEventType;
  title: string;
  subtitle?: string;
  timestamp: string;
  score?: number;
  isLast?: boolean;
}

const TYPE_CONFIG: Record<TimelineEventType, {
  icon: React.ReactNode;
  color: string;
  bg: string;
}> = {
  call:    { icon: <Phone size={13} />,         color: "text-blue-600",   bg: "bg-blue-100" },
  message: { icon: <MessageSquare size={13} />, color: "text-green-600",  bg: "bg-green-100" },
  stay:    { icon: <Home size={13} />,          color: "text-purple-600", bg: "bg-purple-100" },
  inquiry: { icon: <Star size={13} />,          color: "text-amber-600",  bg: "bg-amber-100" },
  score:   { icon: <Star size={13} />,          color: "text-teal-600",   bg: "bg-teal-100" },
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit",
  });
}

export function TimelineEvent({ type, title, subtitle, timestamp, score, isLast }: TimelineEventProps) {
  const cfg = TYPE_CONFIG[type];
  return (
    <div className="flex gap-3">
      {/* Icon + line */}
      <div className="flex flex-col items-center">
        <div className={cn("w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0", cfg.bg, cfg.color)}>
          {cfg.icon}
        </div>
        {!isLast && <div className="w-px flex-1 bg-gray-100 mt-1" />}
      </div>

      {/* Content */}
      <div className={cn("pb-4 min-w-0 flex-1", isLast && "pb-0")}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-sm font-medium text-gray-800 truncate">{title}</p>
            {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
          </div>
          <div className="flex flex-col items-end gap-1 flex-shrink-0">
            <span className="text-[11px] text-gray-400">{formatDate(timestamp)}</span>
            {score != null && (
              <span className={cn(
                "text-[10px] font-bold px-1.5 py-0.5 rounded",
                score >= 80 ? "bg-teal-100 text-teal-700" :
                score >= 60 ? "bg-amber-100 text-amber-700" :
                "bg-red-100 text-red-600"
              )}>
                {Math.round(score)}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
