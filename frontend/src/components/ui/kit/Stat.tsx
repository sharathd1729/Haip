import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type Tone } from "@/components/ui/page";

/** One headline number. It says what period it covers (`hint`), never clips the value (it wraps its
 *  container and exposes the full text on hover), and shows a change only when there is a real baseline. */
export function Stat({
  label, value, hint, change, loading, className,
}: {
  label: ReactNode;
  value: ReactNode;
  /** What the number covers, e.g. "last 7 days" or "all time". */
  hint?: ReactNode;
  /** Pass null when there is nothing to compare against: no "-100%" against an empty period. */
  change?: { text: string; tone: Tone } | null;
  loading?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("haip-card min-w-0 px-4 py-3.5", className)}>
      <p className="truncate text-[11px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{label}</p>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-24" />
      ) : (
        <p className="mt-1 text-[26px] font-semibold leading-none tabular-nums text-[var(--haip-fg)] [overflow-wrap:anywhere]" title={typeof value === "string" ? value : undefined}>
          {value}
        </p>
      )}
      <div className="mt-2 flex min-h-5 flex-wrap items-center gap-x-2 gap-y-1">
        {change && !loading && <StatusPill tone={change.tone}>{change.text}</StatusPill>}
        {hint && <span className="text-xs text-[var(--haip-fg-subtle)]">{hint}</span>}
      </div>
    </div>
  );
}
