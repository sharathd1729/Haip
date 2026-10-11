"use client";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/page";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Right-align numbers/money so digits line up. */
  align?: "left" | "right";
  /** Hide below this breakpoint. The row detail (onRowClick) is where hidden columns go. */
  hideBelow?: "sm" | "md" | "lg";
  className?: string;
}

const HIDE = { sm: "hidden sm:table-cell", md: "hidden md:table-cell", lg: "hidden lg:table-cell" } as const;
const ROW_PAD = { comfortable: "py-3", compact: "py-1.5" } as const;
export type Density = keyof typeof ROW_PAD;

/** The one table: sticky header, density toggle, optional selection, and honest loading / empty / error
 *  states. It scrolls inside its own box so the page itself never scrolls sideways. */
export function DataTable<T>({
  columns, rows, rowKey, loading, error, onRetry, empty, onRowClick,
  selectedKeys, onSelectionChange, density: densityProp, onDensityChange, maxHeightClass = "max-h-[70vh]", className,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  empty?: { title: ReactNode; hint?: ReactNode; action?: ReactNode };
  onRowClick?: (row: T) => void;
  /** Pass both to turn on checkboxes. */
  selectedKeys?: Set<string>;
  onSelectionChange?: (keys: Set<string>) => void;
  density?: Density;
  onDensityChange?: (d: Density) => void;
  /** Tailwind max-height class for the scroll box. */
  maxHeightClass?: string;
  className?: string;
}) {
  const [localDensity, setLocalDensity] = useState<Density>("comfortable");
  const density = densityProp ?? localDensity;
  const setDensity = onDensityChange ?? setLocalDensity;
  const selectable = !!selectedKeys && !!onSelectionChange;
  const allOn = selectable && rows.length > 0 && rows.every(r => selectedKeys!.has(rowKey(r)));

  const toggleAll = () => onSelectionChange!(allOn ? new Set() : new Set(rows.map(rowKey)));
  const toggleOne = (k: string) => {
    const next = new Set(selectedKeys);
    if (next.has(k)) next.delete(k); else next.add(k);
    onSelectionChange!(next);
  };

  const colSpan = columns.length + (selectable ? 1 : 0);

  return (
    <div className={cn("haip-card overflow-hidden", className)}>
      <div className="flex items-center justify-between gap-2 border-b border-[var(--haip-border)] px-3 py-1.5">
        <p className="text-xs text-[var(--haip-fg-subtle)]" aria-live="polite">
          {loading ? "Loading…" : `${rows.length} ${rows.length === 1 ? "row" : "rows"}`}
          {selectable && selectedKeys!.size > 0 && ` · ${selectedKeys!.size} selected`}
        </p>
        <div role="group" aria-label="Row density" className="flex rounded-md bg-[var(--haip-surface)] p-0.5">
          {(["comfortable", "compact"] as const).map(d => (
            <button key={d} type="button" aria-pressed={density === d} onClick={() => setDensity(d)}
              className={cn("h-7 rounded px-2.5 text-[11px] font-semibold capitalize transition-colors",
                density === d ? "bg-[var(--haip-card)] text-[var(--haip-fg)] shadow-sm" : "text-[var(--haip-fg-subtle)]")}>
              {d}
            </button>
          ))}
        </div>
      </div>

      <div className={cn("overflow-auto", maxHeightClass)}>
        <table className="w-full border-collapse text-[13px]">
          <thead className="sticky top-0 z-10 bg-[var(--haip-surface)]">
            <tr>
              {selectable && (
                <th className="w-10 px-3 py-2">
                  <input type="checkbox" aria-label="Select all rows" checked={allOn} onChange={toggleAll} className="size-4 accent-primary" />
                </th>
              )}
              {columns.map(c => (
                <th key={c.key} scope="col"
                  className={cn("whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]",
                    c.align === "right" ? "text-right" : "text-left", c.hideBelow && HIDE[c.hideBelow])}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && Array.from({ length: 6 }, (_, i) => (
              <tr key={`sk${i}`} className="border-t border-[var(--haip-border)]">
                <td colSpan={colSpan} className={cn("px-3", ROW_PAD[density])}><Skeleton className="h-4 w-full" /></td>
              </tr>
            ))}

            {!loading && error && (
              <tr><td colSpan={colSpan}>
                <EmptyState title="Could not load this list" hint={error}
                  action={onRetry && <button type="button" onClick={onRetry} className="h-9 rounded-lg border border-[var(--haip-border)] px-4 text-[13px] font-semibold hover:bg-[var(--haip-surface)]">Try again</button>} />
              </td></tr>
            )}

            {!loading && !error && rows.length === 0 && (
              <tr><td colSpan={colSpan}><EmptyState title={empty?.title ?? "Nothing here yet"} hint={empty?.hint} action={empty?.action} /></td></tr>
            )}

            {!loading && !error && rows.map(r => {
              const k = rowKey(r);
              const on = selectable && selectedKeys!.has(k);
              return (
                <tr key={k} onClick={onRowClick ? () => onRowClick(r) : undefined}
                  className={cn("border-t border-[var(--haip-border)] transition-colors",
                    onRowClick && "cursor-pointer hover:bg-[var(--haip-surface)]", on && "bg-primary/5")}>
                  {selectable && (
                    <td className="w-10 px-3" onClick={e => e.stopPropagation()}>
                      <input type="checkbox" aria-label="Select row" checked={!!on} onChange={() => toggleOne(k)} className="size-4 accent-primary" />
                    </td>
                  )}
                  {columns.map(c => (
                    <td key={c.key}
                      className={cn("px-3 text-[var(--haip-fg)]", ROW_PAD[density], c.align === "right" ? "text-right tabular-nums" : "text-left",
                        c.hideBelow && HIDE[c.hideBelow], c.className)}>
                      {c.cell(r)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
