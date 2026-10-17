"use client";

/**
 * Shared KPI card for all analytics dashboard pages.
 * Shows icon, value, label, optional delta chip, optional subtext, optional drill-down cue.
 */

import { memo } from "react";
import { ArrowUpRight, ArrowDownRight, Minus } from "@/lib/icons";
import { cn } from "@/lib/utils";

// ─── Delta chip ───────────────────────────────────────────────────────────────

export interface KPIDelta {
  pct: number;
  direction: "up" | "down" | "neutral";
}

export function deltaBetween(curr: number, prev: number): KPIDelta {
  if (!prev) return { pct: 0, direction: "neutral" };
  const pct = Math.round((curr - prev) / prev * 100 * 10) / 10;
  return { pct, direction: pct > 0 ? "up" : pct < 0 ? "down" : "neutral" };
}

export function DeltaChip({
  delta,
  invert = false,
}: {
  delta: KPIDelta;
  invert?: boolean;
}) {
  const positive = invert ? delta.direction === "down" : delta.direction === "up";
  const negative = invert ? delta.direction === "up"  : delta.direction === "down";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded-full",
        positive ? "bg-[var(--haip-primary-tint)] text-primary" :
        negative ? "bg-red-100 text-red-600"   : "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-subtle)]",
      )}
    >
      {delta.direction === "up"   ? <ArrowUpRight size={9} />   :
       delta.direction === "down" ? <ArrowDownRight size={9} /> : <Minus size={8} />}
      {Math.abs(delta.pct)}%
    </span>
  );
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

export interface KpiCardProps {
  label: string;
  value: string | number;
  subtext?: string;
  icon: React.ReactNode;
  variant?: "default" | "warning" | "danger";
  delta?: KPIDelta;
  invertDelta?: boolean;
  onClick?: () => void;
}

export const KpiCard = memo(function KpiCard({
  label,
  value,
  subtext,
  icon,
  variant = "default",
  delta,
  invertDelta,
  onClick,
}: KpiCardProps) {
  const iconBg =
    variant === "warning" ? "rgba(245,158,11,0.12)" :
    variant === "danger"  ? "rgba(248,113,113,0.12)" :
    "var(--haip-primary-tint)";
  const iconColor =
    variant === "warning" ? "#D97706" :
    variant === "danger"  ? "#ef4444" : "var(--primary)";

  return (
    <div
      onClick={onClick}
      className={cn(
        "haip-card rounded-2xl p-5 transition-all",
        onClick && "cursor-pointer hover:shadow-md",
      )}
      style={{ border: "1px solid var(--haip-border)" }}
    >
      <div className="flex items-start justify-between mb-3">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
          style={{ background: iconBg, color: iconColor }}
        >
          {icon}
        </div>
        {delta && <DeltaChip delta={delta} invert={invertDelta} />}
      </div>

      <p
        className="text-2xl font-black leading-none"
        style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}
      >
        {value}
      </p>
      <p className="text-[12px] mt-1" style={{ color: "var(--haip-fg-muted)" }}>
        {label}
      </p>
      {subtext && (
        <p className="text-[11px] mt-0.5" style={{ color: "rgba(100,116,139,0.55)" }}>
          {subtext}
        </p>
      )}
      {onClick && (
        <p className="text-[10px] mt-2 font-medium" style={{ color: "var(--primary)" }}>
          Drill down →
        </p>
      )}
    </div>
  );
});
