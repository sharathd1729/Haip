import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface MetricCardProps {
  /** Lucide icon element — will be rendered inside a soft bg-primary/10 container */
  icon: ReactNode;
  /** The big number / value */
  value: string | number;
  /** Label below the value */
  label: string;
  /** Trend text — e.g. "↑ 12%" or "↓ 3%" */
  trend?: string;
  /** Controls trend colour — positive = emerald, negative = rose, neutral = muted */
  trendDir?: "positive" | "negative" | "neutral";
  className?: string;
}

export function MetricCard({
  icon,
  value,
  label,
  trend,
  trendDir = "neutral",
  className,
}: MetricCardProps) {
  const trendColor =
    trendDir === "positive"
      ? "text-emerald-600 dark:text-emerald-400"
      : trendDir === "negative"
      ? "text-rose-600 dark:text-rose-400"
      : "text-muted-foreground";

  return (
    <div className={cn("bg-card rounded-xl p-5 space-y-3 shadow-sm dark:shadow-none", className)}>
      {/* Icon row */}
      <div className="flex items-center justify-between">
        <div
          className="p-2 rounded-lg flex items-center justify-center"
          style={{ background: "color-mix(in srgb, var(--primary) 10%, transparent)" }}
        >
          <span style={{ color: "var(--primary)" }}>{icon}</span>
        </div>
        {trend && (
          <span className={cn("text-xs font-medium", trendColor)}>{trend}</span>
        )}
      </div>

      {/* Value + label */}
      <div>
        <p className="text-2xl font-bold tabular-nums" style={{ color: "var(--haip-fg)" }}>
          {value}
        </p>
        <p className="text-xs mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
          {label}
        </p>
      </div>
    </div>
  );
}
