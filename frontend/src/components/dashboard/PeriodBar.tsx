"use client";
// One date filter for every Home view. It stays pinned under the top bar while the page scrolls, and the choice is
// remembered on this device (same key for the owner Command Center and the operations view, so Home never shows
// two different periods depending on which one you landed on).
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export const PERIOD_PRESETS = [
  { value: "today", label: "Today" },
  { value: "last_7d", label: "Last 7 days" },
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
] as const;

export type PeriodValue = (typeof PERIOD_PRESETS)[number]["value"];
const KEY = "haip_dashboard_period";
const valid = (v: unknown): v is PeriodValue => PERIOD_PRESETS.some(p => p.value === v);

/** The remembered period. Read after mount (not in the initial state) so the first render matches the server. */
export function usePersistedPeriod(initial: PeriodValue): [PeriodValue, (v: PeriodValue) => void] {
  const [value, setValue] = useState<PeriodValue>(initial);
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(KEY);
      if (valid(saved)) setValue(saved);
    } catch { /* storage unavailable: keep the default */ }
  }, []);
  const set = useCallback((v: PeriodValue) => {
    setValue(v);
    try { window.localStorage.setItem(KEY, v); } catch { /* ignore */ }
  }, []);
  return [value, set];
}

export function PeriodBar({ value, onChange, extra, caption, className, custom }: {
  value: string; onChange: (v: string) => void; extra?: ReactNode; caption?: ReactNode; className?: string;
  /** Show a fifth "Custom" choice (the Command Center has date pickers for it). */
  custom?: boolean;
}) {
  const items = custom ? [...PERIOD_PRESETS, { value: "custom", label: "Custom" }] : PERIOD_PRESETS;
  return (
    <div className={cn("sticky top-0 z-20 -mx-3 border-b border-[var(--haip-border)] bg-[var(--haip-card)]/95 px-3 py-2 backdrop-blur supports-[backdrop-filter]:bg-[var(--haip-card)]/80 sm:-mx-6 sm:px-6", className)}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <div role="tablist" aria-label="Date range" className="flex max-w-full gap-1 overflow-x-auto rounded-xl bg-[var(--haip-surface)] p-1">
          {items.map(p => {
            const on = value === p.value;
            return (
              <button key={p.value} type="button" role="tab" aria-selected={on} onClick={() => onChange(p.value)}
                className={cn("min-h-11 shrink-0 rounded-lg px-3 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 lg:min-h-8",
                  on ? "bg-[var(--haip-card)] text-primary shadow-sm" : "text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)]")}>
                {p.label}
              </button>
            );
          })}
        </div>
        {extra}
        {caption && <p className="text-[12px] text-[var(--haip-fg-subtle)]">{caption}</p>}
      </div>
    </div>
  );
}
