"use client";
// The on/off switch used by Lead workflows (playbook toggles, team alerts, the profile's WhatsApp-alert opt-in).
import { cn } from "@/lib/utils";

export function Switch({ on, label, disabled, onChange }: { on: boolean; label: string; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
      className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center disabled:cursor-not-allowed disabled:opacity-50">
      <span className={cn("relative block h-6 w-11 rounded-full transition-colors", on ? "bg-primary" : "bg-[var(--haip-border-strong,var(--haip-border))]")}>
        <span className={cn("absolute left-0 top-0.5 h-5 w-5 rounded-full bg-[var(--haip-card)] shadow transition-transform", on ? "translate-x-[22px]" : "translate-x-0.5")} />
      </span>
    </button>
  );
}
