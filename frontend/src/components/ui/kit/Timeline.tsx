import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface TimelineEntry {
  id: string;
  /** Short heading: what happened. */
  title: ReactNode;
  /** Who/where/detail line. */
  detail?: ReactNode;
  /** Already formatted in the workspace timezone (see lib/format). */
  time: ReactNode;
  /** Optional right-hand badge, e.g. a StatusPill. */
  badge?: ReactNode;
}

/** Vertical history of a record (calls, messages, stage changes), newest first. A line joins the dots;
 *  the entries carry the information, the line only orders them. */
export function Timeline({ entries, empty, className }: {
  entries: TimelineEntry[]; empty?: ReactNode; className?: string;
}) {
  if (entries.length === 0) {
    return <p className={cn("py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]", className)}>{empty ?? "Nothing yet."}</p>;
  }
  return (
    <ol className={cn("relative flex flex-col", className)}>
      {entries.map((e, i) => (
        <li key={e.id} className="relative flex gap-3 pb-4 last:pb-0">
          <div className="relative flex w-3 shrink-0 justify-center">
            <span className={cn("z-10 mt-1.5 size-2.5 rounded-full ring-[3px] ring-[var(--haip-card)]", i === 0 ? "bg-primary" : "bg-[var(--haip-border-strong)]")} />
            {i < entries.length - 1 && <span className="absolute inset-y-3 w-px bg-[var(--haip-border)]" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <p className="text-[14px] font-semibold text-[var(--haip-fg)]">{e.title}</p>
              {e.badge}
              <time className="ml-auto text-[12px] tabular-nums text-[var(--haip-fg-subtle)]">{e.time}</time>
            </div>
            {e.detail && <p className="mt-0.5 text-[13px] leading-relaxed text-[var(--haip-fg-2)] [overflow-wrap:anywhere]">{e.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}
