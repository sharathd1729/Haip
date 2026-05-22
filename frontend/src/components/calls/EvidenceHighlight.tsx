"use client";
import { cn } from "@/lib/utils";

interface EvidenceSpan {
  start: number; // char index in transcript text
  end: number;
  label?: string;
  sentiment?: "positive" | "negative" | "neutral";
}

interface EvidenceHighlightProps {
  text: string;
  spans: EvidenceSpan[];
  onSpanClick?: (span: EvidenceSpan) => void;
  className?: string;
}

const SENTIMENT_STYLES: Record<string, string> = {
  positive: "bg-indigo-100 text-indigo-800 border-indigo-200",
  negative: "bg-red-100 text-red-800 border-red-200",
  neutral:  "bg-blue-50 text-blue-800 border-blue-200",
};

export function EvidenceHighlight({
  text,
  spans,
  onSpanClick,
  className,
}: EvidenceHighlightProps) {
  if (!spans || spans.length === 0) {
    return <span className={className}>{text}</span>;
  }

  // Sort spans by start, then render segments
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const parts: React.ReactNode[] = [];
  let cursor = 0;

  for (const span of sorted) {
    if (span.start > cursor) {
      parts.push(
        <span key={`plain-${cursor}`}>{text.slice(cursor, span.start)}</span>
      );
    }
    const style = SENTIMENT_STYLES[span.sentiment ?? "neutral"];
    parts.push(
      <mark
        key={`span-${span.start}`}
        title={span.label}
        onClick={() => onSpanClick?.(span)}
        className={cn(
          "rounded px-0.5 border cursor-pointer hover:opacity-80 transition-opacity",
          style,
          onSpanClick && "cursor-pointer"
        )}
      >
        {text.slice(span.start, span.end)}
      </mark>
    );
    cursor = span.end;
  }

  if (cursor < text.length) {
    parts.push(<span key={`plain-end`}>{text.slice(cursor)}</span>);
  }

  return <span className={className}>{parts}</span>;
}
