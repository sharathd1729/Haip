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
      <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--haip-icon-neutral)]" />
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="h-10 w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] pl-10 pr-10 text-[16px] text-[var(--haip-fg)] placeholder:text-[var(--haip-fg-subtle)] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 max-md:h-11 sm:text-[14px]" />
      {value && (
        <button type="button" aria-label="Clear search" onClick={() => onChange("")}
          className="absolute right-1 top-1/2 flex size-9 -translate-y-1/2 items-center justify-center rounded-lg text-[var(--haip-icon-neutral)] hover:text-[var(--haip-fg)]">
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
        "relative flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3.5 text-[13.5px] font-semibold transition-colors active:scale-[0.97] max-md:before:absolute max-md:before:-inset-y-1 max-md:before:inset-x-0 max-md:before:content-['']",
        active ? "border-[color-mix(in_srgb,var(--primary)_35%,transparent)] bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-muted)] hover:border-[var(--haip-border-strong)] hover:text-[var(--haip-fg)]",
      )}>
      {children}
      {count != null && <span className="num text-[12px] font-bold opacity-80">{count}</span>}
    </button>
  );
}
