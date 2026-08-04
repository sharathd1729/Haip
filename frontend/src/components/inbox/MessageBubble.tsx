"use client";
import { CheckCheck, Check, Clock, RotateCw, Sparkles, ThumbsUp, ThumbsDown, Edit2, Reply, StickyNote, Languages, Wand2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { memo, useState } from "react";
import { AIRecommendationCard, type RecommendedAction } from "@/components/ai/AIRecommendationCard";

// HAIP Inbox prototype-wiring plan, ticket 3: real translate/tone-fix,
// scoped to the pending draft's own message id -- not the composer-level
// AIDraftPanel (that's for regenerating a whole new draft, a different
// concept). A small fixed list rather than free text input: keeps this
// action row compact and matches the guest languages HAIP's hospitality
// tenants actually see.
const REWRITE_LANGUAGES = ["Hindi", "Kannada", "Tamil", "Telugu", "Malayalam"];
const REWRITE_TONES = ["warm", "formal", "brief", "persuasive"] as const;

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
  isInternal?: boolean;                  // W24
  aiConfidence?: number;
  senderName?: string;
  mediaUrl?: string | null;              // T0.5
  mediaType?: string | null;             // image/video/audio/document
  sharedPostUrl?: string | null;         // Instagram post/ad share — permalink, not fetchable media
  suggestedActions?: RecommendedAction[]; // ticket 4: inline one-click action card
  entityRefs?: { guest_id?: string; inquiry_id?: string };
  onApprove?: (id: string) => void;
  onEdit?: (id: string, text: string) => void;
  onReject?: (id: string) => void;
  onRetry?: (id: string) => void;
  onReply?: (id: string) => void;        // W5
  onRewrite?: (id: string, opts: { tone?: string; target_language?: string }) => void;
  isRewriting?: boolean;
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

function StatusIcon({ status, error }: { status?: MessageStatus; error?: string }) {
  if (!status) return null;
  const meta = STATUS_META[status];
  if (!meta) return null;
  const tip = error ? `Failed: ${error}` : meta.label;
  return (
    <span title={tip} className={cn("flex-shrink-0 transition-colors", meta.color)} aria-label={tip}>
      {meta.icon}
    </span>
  );
}

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

// T0.5: inline media rendering. mediaUrl is only ever set server-side after
// passing an SSRF domain allowlist check (see meta_graph.validate_media_url),
// so it's safe to render directly here.
function MediaContent({ url, type }: { url: string; type?: string | null }) {
  const kind = (type || "").toLowerCase();
  if (kind.startsWith("image") || kind === "image") {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={url} alt="Attachment" className="rounded-xl max-w-full max-h-72 object-contain" />
    );
  }
  if (kind.startsWith("video") || kind === "video" || kind === "ig_reel" || kind === "reel" || kind === "share") {
    return <video src={url} controls className="rounded-xl max-w-full max-h-72" />;
  }
  if (kind.startsWith("audio") || kind === "audio") {
    return <audio src={url} controls className="max-w-full" />;
  }
  // Unknown/document type — link out rather than guessing a renderer
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="text-teal-600 underline text-sm">
      View attachment
    </a>
  );
}

export const MessageBubble = memo(function MessageBubble({
  id,
  text,
  direction,
  status,
  deliveryError,
  timestamp,
  isAiDraft,
  isInternal,
  aiConfidence,
  senderName,
  mediaUrl,
  mediaType,
  sharedPostUrl,
  suggestedActions,
  entityRefs,
  onApprove,
  onEdit,
  onReject,
  onRetry,
  onReply,
  onRewrite,
  isRewriting,
  className,
}: MessageBubbleProps) {
  const isOut    = direction === "outbound";
  const isFailed = status === "failed";
  const [hovered, setHovered] = useState(false);
  const [showLangPicker, setShowLangPicker] = useState(false);
  const [showTonePicker, setShowTonePicker] = useState(false);
  // Note: this component is wrapped in React.memo — it only re-renders when props change.

  // W24: Internal notes always centered with amber styling
  if (isInternal) {
    return (
      <div className={cn("flex justify-center", className)}>
        <div className="max-w-[85%] bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5 text-sm text-amber-800">
          <div className="flex items-center gap-1.5 mb-1 text-[10px] font-bold text-amber-600 uppercase tracking-wide">
            <StickyNote size={10} />
            Internal note
            {senderName && <span className="font-normal normal-case ml-1 text-amber-500">· {senderName}</span>}
          </div>
          <p className="whitespace-pre-wrap">{text}</p>
          <p className="text-[10px] text-amber-400 mt-1">{formatTime(timestamp)}</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn("flex flex-col group", isOut ? "items-end" : "items-start", className)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Sender name */}
      {senderName && !isOut && (
        <span className="text-[10px] text-gray-400 font-medium mb-1 ml-1">{senderName}</span>
      )}

      <div className={cn("max-w-[80%] flex flex-col gap-1", isOut && "items-end")}>
        {/* Bubble */}
        <div className="relative">
          <div className={cn(
            "px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed",
            isOut
              ? isAiDraft
                ? "bg-teal-50 border border-teal-200 text-gray-800 rounded-br-sm"
                : isFailed
                ? "bg-red-50 border border-red-200 text-gray-800 rounded-br-sm"
                : "bg-[#0F766E] text-white rounded-br-sm"
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
            {mediaUrl && (
              <div className={cn(text && !/^\[[a-z_]+\]$/i.test(text) ? "mb-1.5" : "")}>
                <MediaContent url={mediaUrl} type={mediaType} />
              </div>
            )}
            {!mediaUrl && sharedPostUrl && (
              <div className={cn(text && !/^\[[a-z_]+\]$/i.test(text) ? "mb-1.5" : "")}>
                <a
                  href={sharedPostUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-sm text-teal-600 underline"
                >
                  View shared post on Instagram
                </a>
              </div>
            )}
            {/* Bracketed placeholder ("[image]") is a fallback caption only --
                don't show it redundantly once the real media/post link is rendered. */}
            {text && !((mediaUrl || sharedPostUrl) && /^\[[a-z_]+\]$/i.test(text)) && (
              <p className="whitespace-pre-wrap">{text}</p>
            )}
          </div>

          {/* W5: hover reply action */}
          {onReply && hovered && (
            <button
              onClick={() => onReply(id)}
              title="Reply to this message"
              className={cn(
                "absolute top-1/2 -translate-y-1/2 w-6 h-6 rounded-full bg-white border border-gray-200 shadow-sm flex items-center justify-center text-gray-400 hover:text-teal-600 transition-colors",
                isOut ? "-left-8" : "-right-8"
              )}
            >
              <Reply size={11} />
            </button>
          )}
        </div>

        {/* Meta row — W20: status always visible */}
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

            {/* Ticket 3: real translate/tone-fix, scoped to this draft */}
            {onRewrite && (
              <>
                <div className="relative">
                  <button
                    onClick={() => setShowTonePicker(v => !v)}
                    disabled={isRewriting}
                    title="Rewrite tone"
                    className="flex items-center gap-1 text-xs text-gray-500 bg-white hover:bg-gray-50 border border-gray-200 px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                  >
                    <Wand2 size={11} /> Tone
                  </button>
                  {showTonePicker && (
                    <div className="absolute z-10 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[110px]">
                      {REWRITE_TONES.map(t => (
                        <button
                          key={t}
                          onClick={() => { onRewrite(id, { tone: t }); setShowTonePicker(false); }}
                          className="w-full text-left px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 capitalize"
                        >
                          {t}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="relative">
                  <button
                    onClick={() => setShowLangPicker(v => !v)}
                    disabled={isRewriting}
                    title="Translate"
                    className="flex items-center gap-1 text-xs text-gray-500 bg-white hover:bg-gray-50 border border-gray-200 px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                  >
                    <Languages size={11} /> Translate
                  </button>
                  {showLangPicker && (
                    <div className="absolute z-10 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[110px]">
                      {REWRITE_LANGUAGES.map(lang => (
                        <button
                          key={lang}
                          onClick={() => { onRewrite(id, { target_language: lang }); setShowLangPicker(false); }}
                          className="w-full text-left px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
                        >
                          {lang}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        )}

        {/* Ticket 4/HAIP Inbox UI-fidelity pass ticket 5: inline one-click
            action card alongside a grounded draft -- restyled here (wrapper
            only, not the shared AIRecommendationCard used by Calls/Leads360/
            GuestJourney/Ask HAIP) to the prototype's denser, more prominent
            treatment, still in HAIP teal rather than the prototype's indigo. */}
        {isAiDraft && suggestedActions && suggestedActions.length > 0 && (
          <div
            className="mt-1.5 w-full rounded-xl p-0.5"
            style={{ background: "linear-gradient(135deg, var(--primary), color-mix(in srgb, var(--primary) 40%, transparent))" }}
          >
            <div className="rounded-[10px]" style={{ background: "var(--card)" }}>
              <AIRecommendationCard
                title="AI recommendation"
                summary={
                  suggestedActions.some(a => a.action_type === "send_quote")
                    ? "A live quote is ready to send."
                    : suggestedActions.some(a => a.action_type === "send_whatsapp_draft")
                      ? "This draft asks the guest for their phone number."
                      : "The AI has a suggested next step."
                }
                entityRefs={entityRefs ?? {}}
                actions={suggestedActions}
                source="inbox_thread"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
});
