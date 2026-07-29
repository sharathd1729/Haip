import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

/** Accent colour for the 3px bar across the top of the tile. Maps to the
 *  prototype's .kpi / .kpi.green / .kpi.gold / … variants. */
export type MetricAccent = "teal" | "green" | "gold" | "purple" | "blue" | "red";

const ACCENT_VAR: Record<MetricAccent, string> = {
  teal:   "var(--primary)",
  green:  "var(--haip-green)",
  gold:   "var(--haip-gold)",
  purple: "#8b5cf6",
  blue:   "#3b82f6",
  red:    "var(--haip-red)",
};

interface MetricCardProps {
  /** Lucide icon element — rendered small and muted beside the label */
  icon?: ReactNode;
  /** The big number / value */
  value: string | number;
  /** Label above the value */
  label: string;
  /** Trend text — e.g. "↑ 12%" or "↓ 3%" */
  trend?: string;
  /** Controls trend colour — positive = emerald, negative = rose, neutral = muted */
  trendDir?: "positive" | "negative" | "neutral";
  /** Colour of the top accent bar. Defaults to brand teal. */
  accent?: MetricAccent;
  className?: string;
}

export function MetricCard({
  icon,
  value,
  label,
  trend,
  trendDir = "neutral",
  accent = "teal",
  className,
}: MetricCardProps) {
  const trendColor =
    trendDir === "positive"
      ? "text-emerald-600 dark:text-emerald-400"
      : trendDir === "negative"
      ? "text-rose-600 dark:text-rose-400"
      : "text-muted-foreground";

  return (
    <div
      className={cn("haip-kpi", className)}
      style={{ ["--kpi-accent" as string]: ACCENT_VAR[accent] }}
    >
      {/* Label row — uppercase micro-label, with the icon kept as a quiet
          secondary cue rather than the boxed chip it used to be */}
      <div className="flex items-center justify-between gap-2">
        <span className="haip-kpi-label">{label}</span>
        {icon && (
          <span style={{ color: "var(--haip-fg-subtle)", flexShrink: 0 }}>{icon}</span>
        )}
      </div>

      {/* Value */}
      <div className="haip-kpi-value">{value}</div>

      {/* Delta */}
      {trend && (
        <div className={cn("haip-kpi-delta", trendColor)}>{trend}</div>
      )}
    </div>
  );
}
