"use client";
import type { KeyboardEvent, ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface TabItem { value: string; label: ReactNode; count?: number }

/** Controlled tab strip on a green track: the active tab is a sea-green pill with white text and its count turns into a
 *  lime pill. Arrow keys move between tabs, Home/End jump, and it scrolls sideways on a phone instead of wrapping. */
export function Tabs({ items, value, onChange, label, className }: {
  items: TabItem[]; value: string; onChange: (value: string) => void; label: string; className?: string;
}) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = items.findIndex(t => t.value === value);
    const go = (n: number) => { onChange(items[(n + items.length) % items.length].value); e.preventDefault(); };
    if (e.key === "ArrowRight") go(i + 1);
    else if (e.key === "ArrowLeft") go(i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(items.length - 1);
  };
  return (
    <div role="tablist" aria-label={label} onKeyDown={onKey}
      className={cn("flex w-fit max-w-full gap-1 overflow-x-auto rounded-full bg-[var(--haip-tabs-track)] p-1 haip-scrollbar-x", className)}>
      {items.map(t => {
        const on = t.value === value;
        return (
          <button key={t.value} role="tab" aria-selected={on} tabIndex={on ? 0 : -1} onClick={() => onChange(t.value)}
            className={cn(
              "flex min-h-9 shrink-0 items-center gap-1.5 rounded-full px-4 text-[13.5px] font-semibold transition-colors max-md:min-h-11",
              on ? "bg-[var(--haip-tab-active-bg)] text-[var(--haip-tab-active-fg)] shadow-[var(--haip-shadow-sm)]" : "text-[var(--haip-tab-fg)] hover:bg-[var(--hover-bg)]",
            )}>
            {t.label}
            {t.count != null && (
              <span className={cn("num rounded-full px-1.5 text-[11px] font-bold leading-[18px]",
                on ? "bg-[var(--haip-tab-count-active-bg)] text-[var(--haip-tab-count-active-fg)]" : "bg-[var(--haip-tab-count-bg)] text-[var(--haip-tab-fg)]")}>
                {t.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
