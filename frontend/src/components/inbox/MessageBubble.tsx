"use client";
import { CheckCheck, Check, Clock, RotateCw, Sparkles, ThumbsUp, ThumbsDown, Edit2 } from "lucide-react";
import { cn } from "@/lib/utils";

export type MessageDirection = "inbound" | "outbound";
export type MessageStatus = "pending" | "queued" | "sent" | "delivered" | "read" | "failed";

export interface MessageBubbleProps {
  id: string;
  text: string;
  direction: MessageDirection;
  status?: MessageStatus;
  deliveryError?: string;
  timestamp: string;
  isAiDraft?: boolean;
  aiConfidence?: number;
  senderName?: string;
  onApprove?: (id: string) => void;
  onEdit?: (id: string, text: string) => void;
  onReject?: (id: string) => void;
  onRetry?: (id: string) => void;
  className?: string;
}

const STATUS_META: Record<
  MessageStatus,
  { icon: React.ReactNode; label: string; color: string }
> = {
  pending:   { icon: <Clock size={12} />,       label: "Pending",   color: "text-gray-300" },
  queued:    { icon: <Clock size={12} />,        label: "Queued",    color: "text-gray-300" },
  sent:      { icon: <Check size={12} />,        label: "Sent",      color: "text-gray-400" },
  delivered: { icon: <CheckCheck size={12} />,   label: "Delivered", color: "text-gray-400" },
  read:      { icon: <CheckCheck size={12} />,   label: "Read",      color: "text-teal-400" },
  failed:    { icon: <RotateCw size={12} />,     label: "Failed",    color: "text-red-400" },
};

// W20: always-visible status icon with tooltip
function StatusIcon({ status, error }: { status?: MessageStatus; error?: string }) {
  if (!status) return null;
  const meta = STATUS_META[status];
  if (!meta) return null;
  const tip = error ? `Failed: ${error}` : meta.label;
  return (
    <span
      title={tip}
      className={cn("flex-shrink-0 transition-colors", meta.color)}
      aria-label={tip}
    >
      {meta.icon}
    </span>
  );
}

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

export function MessageBubble({
  id,
  text,
  direction,
  status,
  deliveryError,
  timestamp,
  isAiDraft,
  aiConfidence,
  senderName,
  onApprove,
  onEdit,
  onReject,
  onRetry,
  className,
}: MessageBubbleProps) {
  const isOut = direction === "outbound";
  const isFailed = status === "failed";

  return (
    <div className={cn("flex flex-col", isOut ? "items-end" : "items-start", className)}>
      {/* Sender name */}
      {senderName && !isOut && (
        <span className="text-[10px] text-gray-400 font-medium mb-1 ml-1">{senderName}</span>
      )}

      <div className={cn("max-w-[80%] flex flex-col gap-1", isOut && "items-end")}>
        {/* Bubble */}
        <div className={cn(
          "px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed",
          isOut
            ? isAiDraft
              ? "bg-teal-50 border border-teal-200 text-gray-800 rounded-br-sm"
              : isFailed
              ? "bg-red-50 border border-red-200 text-gray-800 rounded-br-sm"
              : "bg-[#0B1F3A] text-white rounded-br-sm"
            : "bg-white border border-gray-100 shadow-sm text-gray-800 rounded-bl-sm"
        )}>
          {isAiDraft && (
            <div className="flex items-center gap-1.5 mb-1.5 pb-1.5 border-b border-teal-100">
              <Sparkles size={12} className="text-teal-500" />
              <span className="text-[10px] font-bold text-teal-600 uppercase tracking-wide">AI Draft</span>
              {aiConfidence != null && (
                <span className="ml-auto text-[10px] text-teal-500 font-mono">
                  {Math.round(aiConfidence * 100)}%
                </span>
              )}
            </div>
          )}
          <p className="whitespace-pre-wrap">{text}</p>
        </div>

        {/* Meta row — W20: status always visible, not hover-gated */}
        <div className={cn("flex items-center gap-1.5 px-1", isOut ? "flex-row-reverse" : "flex-row")}>
          <span className="text-[10px] text-gray-400">{formatTime(timestamp)}</span>
          {isOut && <StatusIcon status={status} error={deliveryError} />}
          {/* W23: inline retry for failed messages */}
          {isOut && isFailed && onRetry && (
            <button
              onClick={() => onRetry(id)}
              title={deliveryError ? `Retry — last error: ${deliveryError}` : "Retry sending"}
              className="flex items-center gap-0.5 text-[10px] font-medium text-red-500 hover:text-red-700 transition-colors ml-1"
            >
              <RotateCw size={10} /> Retry
            </button>
          )}
        </div>

        {/* AI draft action buttons */}
        {isAiDraft && (
          <div className="flex items-center gap-1.5 mt-0.5">
            <button
              onClick={() => onApprove?.(id)}
              className="flex items-center gap-1 text-xs font-semibold text-teal-600 bg-teal-50 hover:bg-teal-100 border border-teal-200 px-2.5 py-1 rounded-lg transition-colors"
            >
              <ThumbsUp size={11} /> Approve
            </button>
            <button
              onClick={() => onEdit?.(id, text)}
              className="flex items-center gap-1 text-xs text-gray-600 bg-white hover:bg-gray-50 border border-gray-200 px-2.5 py-1 rounded-lg transition-colors"
            >
              <Edit2 size={11} /> Edit
            </button>
            <button
              onClick={() => onReject?.(id)}
              className="flex items-center gap-1 text-xs text-red-500 bg-red-50 hover:bg-red-100 border border-red-200 px-2.5 py-1 rounded-lg transition-colors"
            >
              <ThumbsDown size={11} /> Reject
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
