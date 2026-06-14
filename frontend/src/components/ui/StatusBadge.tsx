/**
 * StatusBadge — HAIP stage/status pills
 *
 * Covers all inquiry stages + ad-hoc status strings.
 * Uses explicit light + dark: classes — no CSS variable hacks.
 * Shape: rounded-full px-2.5 py-0.5 text-xs font-medium
 */
import { cn } from "@/lib/utils";

// ─── Stage map ────────────────────────────────────────────────────────────────

const STAGE_CLASSES: Record<string, string> = {
  // Pipeline stages
  new:
    "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
  responding:
    "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  quoted:
    "bg-violet-50 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
  site_visit_scheduled:
    "bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300",
  site_visit_done:
    "bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300",
  site_visit:
    "bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300",
  booked:
    "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  lost:
    "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
  ghosted:
    "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
  closed:
    "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",

  // Generic status
  active:
    "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  inactive:
    "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
  pending:
    "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  error:
    "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  live:
    "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
};

// Human-readable labels for pipeline stages
const STAGE_LABELS: Record<string, string> = {
  new:                    "New",
  responding:             "Responding",
  quoted:                 "Quoted",
  site_visit_scheduled:   "Site Visit",
  site_visit_done:        "Visit Done",
  site_visit:             "Site Visit",
  booked:                 "Booked",
  lost:                   "Lost",
  ghosted:                "Ghosted",
  closed:                 "Closed",
};

// ─── Component ────────────────────────────────────────────────────────────────

interface StatusBadgeProps {
  /** Stage key (case-insensitive) — e.g. "new", "RESPONDING", "site_visit_scheduled" */
  stage: string;
  /** Override the display label — defaults to formatted stage key */
  label?: string;
  className?: string;
}

export function StatusBadge({ stage, label, className }: StatusBadgeProps) {
  const key = stage.toLowerCase().replace(/ /g, "_");
  const classes = STAGE_CLASSES[key] ?? "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400";
  const displayLabel = label ?? STAGE_LABELS[key] ?? stage.charAt(0).toUpperCase() + stage.slice(1).toLowerCase().replace(/_/g, " ");

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        classes,
        className,
      )}
    >
      {displayLabel}
    </span>
  );
}
