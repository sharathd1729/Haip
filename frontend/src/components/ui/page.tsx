import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Title row for a dashboard page: a plain heading and one line of context on the left, actions on the right.
 *  No icon tile: the sidebar already says where you are, and a coloured square above every title is what
 *  makes pages look templated. */
export function PageHeader({
  title, subtitle, actions, className,
}: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <header className={cn("flex flex-wrap items-end gap-x-4 gap-y-3", className)}>
      <div className="min-w-0 flex-1">
        <h1 className="haip-page-title">{title}</h1>
        {subtitle && <p className="mt-0.5 text-[13px] leading-snug" style={{ color: "var(--haip-fg-subtle)" }}>{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** What to show when a list is empty: say what the list is for and offer the next step. */
export function EmptyState({
  title, hint, action, className,
}: { title: ReactNode; hint?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-1.5 px-6 py-16 text-center", className)}>
      <p className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>{title}</p>
      {hint && <p className="max-w-sm text-xs leading-relaxed" style={{ color: "var(--haip-fg-subtle)" }}>{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

const TONES = {
  neutral: "bg-gray-100 text-gray-700 border-gray-200",
  info:    "bg-blue-50 text-blue-700 border-blue-100",
  success: "bg-emerald-50 text-emerald-700 border-emerald-100",
  warning: "bg-amber-50 text-amber-800 border-amber-100",
  danger:  "bg-red-50 text-red-700 border-red-100",
  brand:   "bg-teal-50 text-teal-700 border-teal-100",
} as const;

export type Tone = keyof typeof TONES;

/** A small label for a state (booking status, payment status, channel). The words carry the meaning;
 *  the colour only reinforces it, so it still reads for colour-blind users and in greyscale prints. */
export function StatusPill({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold leading-4", TONES[tone], className)}>
      {children}
    </span>
  );
}
