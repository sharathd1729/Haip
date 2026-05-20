"use client";
import { Sparkles, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

export type AiTone = "warm" | "formal" | "brief" | "persuasive";

const TONES: { value: AiTone; label: string; emoji: string }[] = [
  { value: "warm",       label: "Warm",       emoji: "🤗" },
  { value: "formal",     label: "Formal",     emoji: "📋" },
  { value: "brief",      label: "Brief",      emoji: "⚡" },
  { value: "persuasive", label: "Persuasive", emoji: "💬" },
];

interface AIDraftPanelProps {
  tone: AiTone;
  onToneChange: (t: AiTone) => void;
  onRegenerate: () => void;
  isPending: boolean;
  hasDraft: boolean;
  rejectedCount: number;
  onRecallRejected: () => void;
}

export function AIDraftPanel({
  tone,
  onToneChange,
  onRegenerate,
  isPending,
  hasDraft,
  rejectedCount,
  onRecallRejected,
}: AIDraftPanelProps) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Tone chips */}
      <div className="flex items-center gap-1">
        {TONES.map(t => (
          <button
            key={t.value}
            onClick={() => onToneChange(t.value)}
            className={cn(
              "flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg transition-colors border",
              tone === t.value
                ? "bg-teal-100 border-teal-300 text-teal-700"
                : "bg-white border-gray-200 text-gray-500 hover:bg-gray-50"
            )}
          >
            <span>{t.emoji}</span>
            {t.label}
          </button>
        ))}
      </div>

      {/* Regenerate button */}
      <button
        onClick={onRegenerate}
        disabled={isPending}
        title="Regenerate draft with current tone"
        className={cn(
          "flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-lg border transition-colors",
          "text-teal-600 bg-teal-50 hover:bg-teal-100 border-teal-200 disabled:opacity-50"
        )}
      >
        <RefreshCw size={11} className={isPending ? "animate-spin" : ""} />
        {isPending ? "Generating…" : "Regenerate"}
      </button>

      {/* Recall rejected drafts */}
      {rejectedCount > 0 && (
        <button
          onClick={onRecallRejected}
          title="Recall a previously rejected draft"
          className="text-[11px] text-gray-400 hover:text-gray-600 transition-colors"
        >
          ↶ {rejectedCount} rejected
        </button>
      )}
    </div>
  );
}
