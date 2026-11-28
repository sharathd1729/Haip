"use client";
// The period as one small pill for a phone header row ("Today", opens a sheet with the other periods), so the choice costs
// no row of its own above the numbers (owner, 28 Nov 2026). Same presets and the same per-tab memory as PeriodBar.
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Check, ChevronDown } from "@/lib/icons";
import { BottomSheet } from "@/components/ui/kit";
import { PERIOD_PRESETS, type PeriodValue } from "./PeriodBar";

export function PeriodPill({ value, onChange, className }: { value: PeriodValue; onChange: (v: PeriodValue) => void; className?: string }) {
  const [open, setOpen] = useState(false);
  const label = PERIOD_PRESETS.find(p => p.value === value)?.label ?? "Period";
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-label={`Period: ${label}. Change`}
        className={cn("inline-flex min-h-11 shrink-0 cursor-pointer items-center gap-1 rounded-full border border-[var(--haip-border)] bg-[var(--haip-card)] pl-3.5 pr-2.5 text-[13.5px] font-semibold text-[var(--haip-fg)] transition-transform duration-150 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50", className)}>
        {label}<ChevronDown size={15} aria-hidden />
      </button>
      <BottomSheet open={open} onOpenChange={setOpen} title="Show numbers for">
        <ul role="radiogroup" aria-label="Period" className="grid gap-1 pb-2">
          {PERIOD_PRESETS.map(p => {
            const on = p.value === value;
            return (
              <li key={p.value}>
                <button type="button" role="radio" aria-checked={on} onClick={() => { onChange(p.value); setOpen(false); }}
                  className={cn("flex min-h-12 w-full cursor-pointer items-center justify-between rounded-xl px-3.5 text-left text-[15px] font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
                    on ? "bg-[var(--haip-primary-tint)] text-primary" : "text-[var(--haip-fg)] active:bg-[var(--haip-surface)]")}>
                  {p.label}{on && <Check size={18} aria-hidden />}
                </button>
              </li>
            );
          })}
        </ul>
      </BottomSheet>
    </>
  );
}
