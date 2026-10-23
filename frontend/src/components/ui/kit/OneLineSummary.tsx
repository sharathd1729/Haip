"use client";
// One line of AI summary with "more" for the rest ("Wants Coorg 3 days, asked price  more"). The full text is always in the
// DOM for screen readers; "more" only lifts the clamp. Short text gets no button.
import { useState } from "react";
import { cn } from "@/lib/utils";

/** Past this many characters a summary no longer fits one phone line (375px, 13px Figtree), so "more" is offered. */
export const ONE_LINE_CHARS = 56;

export function OneLineSummary({ text, label = "AI note", className }: { text?: string | null; label?: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const t = (text ?? "").trim();
  if (!t) return null;
  const long = t.length > ONE_LINE_CHARS;
  return (
    <p className={cn("flex min-w-0 items-baseline gap-1.5 text-[13px] leading-snug text-[var(--haip-fg-2)]", className)}>
      <span className="sr-only">{label}: </span>
      <span className={cn("min-w-0 flex-1", open ? "[overflow-wrap:anywhere]" : "truncate")}>{t}</span>
      {long && (
        <button type="button" aria-expanded={open} onClick={e => { e.stopPropagation(); setOpen(v => !v); }}
          className="relative shrink-0 text-[12.5px] font-bold text-primary before:absolute before:-inset-x-2 before:-inset-y-3 before:content-['']">
          {open ? "less" : "more"}
        </button>
      )}
    </p>
  );
}
