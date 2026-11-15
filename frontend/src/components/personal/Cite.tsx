"use client";
// References, the way Perplexity / ChatGPT show them: a small numbered chip after a fact. Tapping it opens the words on
// the call it came from, inline under the line (never a popover that falls off a phone screen), with "Play from 0:42".
// On a memory page the chip plays the recording right there (MomentProvider); elsewhere it opens the memory at that
// moment (/dashboard/me/calls/{id}?t=42).
import { createContext, useContext, useState } from "react";
import Link from "next/link";
import { Play } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { citeOrder, momentHref, momentLabel, refKey, type Memory, type Ref } from "@/lib/personal";

interface Moments { refs: Record<string, Ref>; order: Map<string, number>; play?: (at: number) => void }
const MomentContext = createContext<Moments | null>(null);

/** Gives every <Cite text> inside a memory its number and lets it play the recording. */
export function MomentProvider({ memory, play, children }: { memory: Memory; play?: (at: number) => void; children: React.ReactNode }) {
  return <MomentContext.Provider value={{ refs: memory.refs ?? {}, order: citeOrder(memory), play }}>{children}</MomentContext.Provider>;
}

/** The chip for one point of the current memory; nothing when the point has no source. */
export function Cite({ text }: { text: string }) {
  const ctx = useContext(MomentContext);
  const k = refKey(text);
  const ref = ctx?.refs[k];
  if (!ctx || !ref) return null;
  return <SourceChip n={ctx.order.get(k) ?? 1} quote={ref.quote} at={ref.at} onPlay={ctx.play} />;
}

/** A numbered chip that opens its source card. `callId` makes "Open the call" a link (Reminders, Calendar, Ask). */
export function SourceChip({ n, quote, at, onPlay, callId, label }: {
  n: number | string;
  quote: string | null;
  at: number | null;
  onPlay?: (at: number) => void;
  callId?: string;
  /** Who / when, shown above the quote (Ask answers). */
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={e => { e.stopPropagation(); setOpen(o => !o); }}
        aria-expanded={open}
        aria-label={`Source ${n}${at != null ? `, at ${momentLabel(at)} in the call` : ""}`}
        className={cn(
          "mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-full px-1 align-middle text-[11px] font-bold leading-none tabular-nums transition-colors duration-150",
          // small to read, 44px to tap (the pseudo element); "y-cite-size-" opts out of globals.css's touch min-height,
          // which matches [class*="size-"], so the chip does not stretch the line on phones
          "y-cite-size-chip relative before:absolute before:-inset-[13px] before:content-['']",
          open ? "bg-[var(--y-brand)] text-[var(--y-on-brand)]" : "bg-[var(--y-soft)] text-[var(--y-soft-ink)] hover:bg-[var(--y-brand)] hover:text-[var(--y-on-brand)]",
        )}
      >
        {n}
      </button>
      {open && (
        <span className="y-enter my-1.5 block rounded-[12px] border border-[var(--y-line)] bg-[var(--y-canvas)] px-3 py-2.5 text-[13.5px] font-normal not-italic leading-snug text-[var(--y-ink)]">
          {label && <span className="mb-1 block text-[12px] font-semibold text-[var(--y-ink-2)]">{label}</span>}
          {quote ? <span className="block italic text-[var(--y-ink-2)]">&ldquo;{quote}&rdquo;</span> : <span className="block text-[var(--y-ink-2)]">From this call</span>}
          <span className="mt-2 flex flex-wrap items-center gap-2">
            {at != null && onPlay && (
              <button type="button" onClick={() => onPlay(at)}
                className="y-press inline-flex min-h-9 items-center gap-1.5 rounded-full bg-[var(--y-brand)] px-3 text-[13px] font-semibold text-[var(--y-on-brand)]">
                <Play size={13} aria-hidden /> Play from {momentLabel(at)}
              </button>
            )}
            {callId && (
              <Link href={momentHref(callId, at)}
                className="y-press inline-flex min-h-9 items-center gap-1.5 rounded-full border border-[var(--y-line-strong)] px-3 text-[13px] font-semibold text-[var(--y-ink)]">
                {at != null ? <><Play size={13} aria-hidden /> Hear it at {momentLabel(at)}</> : "Open the call"}
              </Link>
            )}
          </span>
        </span>
      )}
    </>
  );
}
