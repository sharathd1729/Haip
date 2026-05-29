"use client";
import { memo } from "react";
import { cn } from "@/lib/utils";
import { EvidenceHighlight } from "./EvidenceHighlight";

interface EvidenceSpan {
  start: number;
  end: number;
  label?: string;
  sentiment?: "positive" | "negative" | "neutral";
}

export interface TranscriptTurnProps {
  speaker: "agent" | "guest" | string;
  text: string;
  t0: number;  // seconds from call start
  t1: number;
  evidenceSpans?: EvidenceSpan[];
  isActive?: boolean; // highlighted when playhead is within this turn
  onClick?: (t0: number) => void; // seek audio
}

function formatTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

const SPEAKER_STYLES = {
  agent: {
    avatar: "bg-[#0F766E] text-white",
    label: "Agent",
    bubble: "bg-white border border-gray-100",
  },
  guest: {
    avatar: "bg-teal-500 text-white",
    label: "Guest",
    bubble: "bg-teal-50 border border-teal-100",
  },
} as const;

export const TranscriptTurn = memo(function TranscriptTurn({
  speaker,
  text,
  t0,
  t1,
  evidenceSpans = [],
  isActive = false,
  onClick,
}: TranscriptTurnProps) {
  const key = (speaker === "agent" || speaker === "0") ? "agent" : "guest";
  const styles = SPEAKER_STYLES[key];
  const initial = key === "agent" ? "A" : "G";

  return (
    <div
      className={cn(
        "flex gap-3 px-1 py-1 rounded-xl transition-colors",
        isActive && "bg-teal-50/60",
        onClick && "cursor-pointer"
      )}
      onClick={() => onClick?.(t0)}
    >
      {/* Avatar */}
      <div className={cn(
        "w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5",
        styles.avatar
      )}>
        {initial}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1">
          <span className="text-xs font-semibold text-gray-600">{styles.label}</span>
          <button
            className="text-[10px] text-gray-300 hover:text-teal-500 transition-colors tabular-nums"
            onClick={(e) => { e.stopPropagation(); onClick?.(t0); }}
            title="Seek to this turn"
          >
            {formatTime(t0)}–{formatTime(t1)}
          </button>
        </div>
        <div className={cn(
          "text-sm text-gray-700 leading-relaxed rounded-xl px-3.5 py-2.5 border",
          styles.bubble
        )}>
          <EvidenceHighlight text={text} spans={evidenceSpans} />
        </div>
      </div>
    </div>
  );
});
