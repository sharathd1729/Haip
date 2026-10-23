"use client";
// One row of quick filters on a phone: the 3-4 chips people actually use, each with its count, then a Filters button for the
// rest (which opens a BottomSheet). Scrolls sideways inside itself, so the page never does. A single choice: aria-pressed.
import type { ReactNode } from "react";
import { SlidersHorizontal } from "@/lib/icons";
import { cn } from "@/lib/utils";

export interface ChipItem { value: string; label: ReactNode; count?: number | null }

export function ChipRow({ items, value, onChange, onFilters, filterCount = 0, label, className }: {
  items: ChipItem[];
  value: string;
  onChange: (value: string) => void;
  /** Shows the Filters button when given. */
  onFilters?: () => void;
  /** How many secondary filters are on (shown on the Filters button). */
  filterCount?: number;
  label: string;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label}
      className={cn("-mx-4 flex gap-1.5 overflow-x-auto px-4 py-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden", className)}>
      {items.map(it => {
        const on = it.value === value;
        return (
          <button key={it.value} type="button" aria-pressed={on} onClick={() => onChange(it.value)}
            className={cn(
              "inline-flex min-h-11 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3.5 text-[13.5px] font-semibold transition-colors active:scale-[0.97]",
              on ? "border-transparent bg-[var(--haip-tab-active-bg)] text-[var(--haip-tab-active-fg)]"
                : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-2)]",
            )}>
            {it.label}
            {it.count != null && <span className={cn("num text-[12px] font-bold", on ? "opacity-90" : "text-[var(--haip-fg-subtle)]")}>{it.count}</span>}
          </button>
        );
      })}
      {onFilters && (
        <button type="button" onClick={onFilters} aria-label={filterCount ? `Filters, ${filterCount} on` : "Filters"}
          className="inline-flex min-h-11 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-[var(--haip-border)] bg-[var(--haip-card)] px-3.5 text-[13.5px] font-semibold text-[var(--haip-fg-2)]">
          <SlidersHorizontal size={15} />Filters
          {filterCount > 0 && <span className="num rounded-full bg-primary px-1.5 text-[11.5px] font-bold leading-[18px] text-primary-foreground">{filterCount}</span>}
        </button>
      )}
    </div>
  );
}
