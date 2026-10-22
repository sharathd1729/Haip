import type { ComponentType, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type Tone } from "@/components/ui/page";

/** `default` white card; `dark` forest card for the one headline figure; `olive` for a calmer secondary group;
 *  `accent` (terracotta) ONLY for money due / needs attention. */
export type StatVariant = "default" | "dark" | "olive" | "accent";

// Written out in full so Tailwind sees every class. The tinted variants cannot reuse .haip-card: it is plain (unlayered)
// CSS, so its white background would beat any Tailwind bg-* utility. SURFACE repeats its shape instead.
const SURFACE = "rounded-[calc(var(--radius)+4px)] border shadow-[var(--haip-shadow-sm)]";
const VARIANTS: Record<StatVariant, { card: string; label: string; value: string; hint: string; chip: string }> = {
  default: {
    card: "haip-card",
    label: "text-[var(--haip-fg-muted)]", value: "text-[var(--haip-fg)]", hint: "text-[var(--haip-fg-subtle)]",
    chip: "bg-[var(--haip-chip-bg)] text-[var(--haip-chip-fg)]",
  },
  dark: {
    card: cn(SURFACE, "border-transparent bg-[var(--haip-stat-dark-bg)]"),
    label: "text-[var(--haip-stat-dark-muted)]", value: "text-[var(--haip-stat-dark-fg)]", hint: "text-[var(--haip-stat-dark-muted)]",
    chip: "bg-[var(--haip-stat-dark-chip)] text-[var(--haip-stat-dark-chip-fg)]",
  },
  olive: {
    card: cn(SURFACE, "border-[var(--haip-olive-border)] bg-[var(--haip-olive-bg)]"),
    label: "text-[var(--haip-olive-fg)]", value: "text-[var(--haip-olive-fg)]", hint: "text-[var(--haip-olive-fg)] opacity-80",
    chip: "bg-[var(--haip-stat-olive-chip)] text-[var(--haip-olive-fg)]",
  },
  accent: {
    card: cn(SURFACE, "border-[var(--haip-accent-line)] bg-[var(--haip-accent-light)]"),
    label: "text-[var(--haip-accent-ink)]", value: "text-[var(--haip-accent-ink)]", hint: "text-[var(--haip-accent-ink)] opacity-85",
    chip: "bg-[var(--haip-accent)] text-[var(--haip-stat-accent-chip-fg)]",
  },
};

/** One headline number. It says what period it covers (`hint`), never clips the value (it wraps its
 *  container and exposes the full text on hover), and shows a change only when there is a real baseline.
 *  `icon` adds a 30px chip beside the label. */
export function Stat({
  label, value, hint, change, loading, icon: Icon, variant = "default", className,
}: {
  label: ReactNode;
  value: ReactNode;
  /** What the number covers, e.g. "last 7 days" or "all time". */
  hint?: ReactNode;
  /** Pass null when there is nothing to compare against: no "-100%" against an empty period. */
  change?: { text: string; tone: Tone } | null;
  loading?: boolean;
  icon?: ComponentType<{ size?: number; className?: string }>;
  variant?: StatVariant;
  className?: string;
}) {
  const v = VARIANTS[variant];
  return (
    <div className={cn("min-w-0 px-4 py-4", v.card, className)}>
      <div className="flex items-start gap-2.5">
        <p className={cn("min-w-0 flex-1 truncate text-[13px] font-medium", Icon && "pt-[5px]", v.label)}>{label}</p>
        {Icon && (
          <span aria-hidden className={cn("flex size-[30px] shrink-0 items-center justify-center rounded-[9px]", v.chip)}>
            <Icon size={16} />
          </span>
        )}
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-8 w-24" />
      ) : (
        <p className={cn("mt-1.5 font-[family-name:var(--font-display)] text-[28px] font-semibold leading-none tracking-[-0.02em] tabular-nums [overflow-wrap:anywhere]", v.value)} title={typeof value === "string" ? value : undefined}>
          {value}
        </p>
      )}
      <div className="mt-2 flex min-h-5 flex-wrap items-center gap-x-2 gap-y-1">
        {change && !loading && <StatusPill tone={change.tone}>{change.text}</StatusPill>}
        {hint && <span className={cn("text-[12.5px]", v.hint)}>{hint}</span>}
      </div>
    </div>
  );
}
