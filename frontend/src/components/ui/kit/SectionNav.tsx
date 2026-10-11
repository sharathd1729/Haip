"use client";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface SectionNavItem { value: string; label: ReactNode; hint?: ReactNode }

/** Left-hand section list for long pages (Settings). Stacks into a horizontal scroller on phones, so a
 *  long page never becomes one endless column of every section. */
export function SectionNav({ items, value, onChange, label, className }: {
  items: SectionNavItem[]; value: string; onChange: (value: string) => void; label: string; className?: string;
}) {
  return (
    <nav aria-label={label}
      className={cn("flex gap-1 overflow-x-auto haip-scrollbar-x lg:flex-col lg:overflow-visible", className)}>
      {items.map(it => {
        const on = it.value === value;
        return (
          <button key={it.value} type="button" aria-current={on ? "page" : undefined} onClick={() => onChange(it.value)}
            className={cn(
              "flex min-h-9 shrink-0 flex-col items-start justify-center rounded-lg px-3 py-1.5 text-left transition-colors",
              on ? "bg-primary/10 text-primary" : "text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]",
            )}>
            <span className="text-[13px] font-semibold">{it.label}</span>
            {it.hint && <span className="hidden text-[11px] font-normal text-[var(--haip-fg-subtle)] lg:block">{it.hint}</span>}
          </button>
        );
      })}
    </nav>
  );
}
