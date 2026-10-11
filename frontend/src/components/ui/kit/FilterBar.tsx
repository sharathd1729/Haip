"use client";
import type { ReactNode } from "react";
import { Search, X } from "@/lib/icons";
import { cn } from "@/lib/utils";

/** One row for search + filters. Wraps cleanly; put the search first so it keeps the widest slot. */
export function FilterBar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("flex flex-wrap items-center gap-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden", className)}>{children}</div>;
}

export function FilterSearch({ value, onChange, placeholder, label = "Search", className }: {
  value: string; onChange: (v: string) => void; placeholder?: string; label?: string; className?: string;
}) {
  return (
    <label className={cn("relative block min-w-[200px] flex-1 sm:max-w-sm", className)}>
      <span className="sr-only">{label}</span>
      <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-icon-neutral)]" />
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="h-9 w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] pl-9 pr-8 text-[13px] text-[var(--haip-fg)] placeholder:text-[var(--haip-fg-subtle)] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20" />
      {value && (
        <button type="button" aria-label="Clear search" onClick={() => onChange("")}
          className="absolute right-2 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded text-[var(--haip-icon-neutral)] hover:text-[var(--haip-fg)]">
          <X size={13} />
        </button>
      )}
    </label>
  );
}

/** A quick filter ("Upcoming", "Needs payment"). `aria-pressed` so screen readers announce the state. */
export function FilterChip({ active, onClick, count, children }: {
  active?: boolean; onClick: () => void; count?: number; children: ReactNode;
}) {
  return (
    <button type="button" aria-pressed={!!active} onClick={onClick}
      className={cn(
        "flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-[12.5px] font-medium transition-colors active:scale-[0.97]",
        active ? "border-primary bg-primary/10 text-primary" : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-2)] hover:border-[var(--haip-border-strong)]",
      )}>
      {children}
      {count != null && <span className="text-[11px] tabular-nums opacity-70">{count}</span>}
    </button>
  );
}
