"use client";
// Small shared pieces for the quote builder: class strings, a labelled field, a stepper, choice chips and callouts.
// Colours come from tokens only. Touch targets are 44px on phones; inputs are 16px on phones (no zoom on focus).
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export const INPUT =
  "w-full min-h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base sm:min-h-9 sm:text-[13px] " +
  "text-[var(--haip-fg)] placeholder:text-[var(--haip-fg-subtle)] focus:outline-none focus:ring-2 focus:ring-primary/30";
export const BTN =
  "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[13px] " +
  "font-semibold text-[var(--haip-fg)] hover:bg-[var(--haip-surface)] disabled:opacity-50 sm:min-h-9";
export const BTN_PRIMARY =
  "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg bg-primary px-4 text-[13px] font-semibold text-primary-foreground " +
  "hover:bg-[var(--haip-primary-hover)] disabled:opacity-50 sm:min-h-9";
export const BTN_GHOST =
  "inline-flex min-h-11 items-center gap-1 rounded-lg px-1 text-[13px] font-semibold text-primary hover:underline disabled:opacity-50 sm:min-h-8";
export const LABEL = "block text-xs font-semibold text-[var(--haip-fg-2)]";

export function Field({ label, htmlFor, hint, children, className }: { label: ReactNode; htmlFor?: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0 space-y-1", className)}>
      {htmlFor ? <label htmlFor={htmlFor} className={LABEL}>{label}</label> : <span className={LABEL}>{label}</span>}
      {children}
      {hint && <p className="text-[11.5px] leading-snug text-[var(--haip-fg-subtle)]">{hint}</p>}
    </div>
  );
}

export function Stepper({ id, label, value, min, max, onChange }: { id: string; label: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <div className="min-w-0 space-y-1">
      <span id={`${id}-l`} className={LABEL}>{label}</span>
      <div role="group" aria-labelledby={`${id}-l`} className="flex h-11 items-stretch overflow-hidden rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] sm:h-9">
        <button type="button" aria-label={`Fewer ${label.toLowerCase()}`} disabled={value <= min} onClick={() => onChange(value - 1)}
          className="w-11 shrink-0 text-lg font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-40 sm:w-9">−</button>
        <span className="num flex flex-1 items-center justify-center text-[15px] font-semibold tabular-nums" aria-live="polite">{value}</span>
        <button type="button" aria-label={`More ${label.toLowerCase()}`} disabled={value >= max} onClick={() => onChange(value + 1)}
          className="w-11 shrink-0 text-lg font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-40 sm:w-9">+</button>
      </div>
    </div>
  );
}

export function Chip({ on, onClick, children, disabled, className }: { on: boolean; onClick: () => void; children: ReactNode; disabled?: boolean; className?: string }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick} disabled={disabled}
      className={cn(
        "inline-flex min-h-11 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium transition-colors disabled:opacity-40 sm:min-h-8",
        on ? "border-primary/40 bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-2)] hover:border-[var(--haip-border-strong)]",
        className,
      )}>
      {children}
    </button>
  );
}

const TONE = {
  danger: "border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]",
  warning: "border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]",
  success: "border-[var(--haip-status-success-border)] bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]",
  info: "border-[var(--haip-status-info-border)] bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]",
} as const;

export function Callout({ tone, children, action }: { tone: keyof typeof TONE; children: ReactNode; action?: ReactNode }) {
  return (
    <div role={tone === "danger" ? "alert" : undefined} className={cn("flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2.5 text-[13px] leading-snug", TONE[tone])}>
      <span className="min-w-0 flex-1">{children}</span>
      {action}
    </div>
  );
}

/** "Something went wrong" detail from an API error: {message, problems[]} or a plain string. */
export function apiProblems(e: unknown): { message: string; problems: string[] } {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (d && typeof d === "object" && "message" in d) {
    const o = d as { message: string; problems?: string[] };
    return { message: o.message, problems: o.problems ?? [] };
  }
  return { message: typeof d === "string" ? d : "Something went wrong. Try again.", problems: [] };
}
