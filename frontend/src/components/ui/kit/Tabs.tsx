"use client";
import type { KeyboardEvent, ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface TabItem { value: string; label: ReactNode; count?: number }

/** Controlled tab strip. Arrow keys move between tabs, Home/End jump, and it scrolls sideways on a phone
 *  instead of wrapping onto several lines. */
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
      className={cn("flex gap-1 overflow-x-auto rounded-xl bg-[var(--haip-surface)] p-1 haip-scrollbar-x", className)}>
      {items.map(t => {
        const on = t.value === value;
        return (
          <button key={t.value} role="tab" aria-selected={on} tabIndex={on ? 0 : -1} onClick={() => onChange(t.value)}
            className={cn(
              "flex min-h-9 shrink-0 items-center gap-1.5 rounded-lg px-3.5 text-[12.5px] font-semibold transition-colors",
              on ? "bg-[var(--haip-card)] text-[var(--haip-fg)] shadow-sm" : "text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)]",
            )}>
            {t.label}
            {t.count != null && <span className="text-[11px] font-medium tabular-nums opacity-70">{t.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
