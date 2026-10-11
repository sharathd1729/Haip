"use client";
import { cn } from "@/lib/utils";

interface ScoreRingProps {
  score: number; // 0–100
  size?: number;
  strokeWidth?: number;
  className?: string;
  showLabel?: boolean;
}

function scoreColor(score: number) {
  if (score >= 80) return { stroke: "var(--primary)", text: "text-primary" }; // teal
  if (score >= 60) return { stroke: "var(--haip-status-warning-fg)", text: "text-[var(--haip-status-warning-fg)]" }; // amber
  return { stroke: "var(--haip-status-danger-fg)", text: "text-[var(--haip-status-danger-fg)]" };  // red
}

export function ScoreRing({
  score,
  size = 72,
  strokeWidth = 7,
  className,
  showLabel = true,
}: ScoreRingProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const offset = circumference * (1 - pct);
  const { stroke, text } = scoreColor(score);

  return (
  <div className={cn("relative inline-flex items-center justify-center", className)}>
  <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
  {/* Track */}
  <circle
  cx={size / 2}
  cy={size / 2}
  r={radius}
  fill="none"
  stroke="currentColor"
  strokeWidth={strokeWidth}
  className="text-[var(--haip-border)]"
  />
  {/* Fill */}
  <circle
  cx={size / 2}
  cy={size / 2}
  r={radius}
  fill="none"
  stroke={stroke}
  strokeWidth={strokeWidth}
  strokeLinecap="round"
  strokeDasharray={circumference}
  strokeDashoffset={offset}
  style={{ transition: "stroke-dashoffset 0.6s ease" }}
  />
  </svg>
  {showLabel && (
  <div className="absolute inset-0 flex flex-col items-center justify-center">
  <span className={cn("font-bold leading-none", text, size >= 72 ? "text-xl" : "text-base")}>
  {Math.round(score)}
  </span>
  <span className="text-[9px] text-[var(--haip-fg-subtle)] uppercase tracking-wide leading-tight mt-0.5">
  score
  </span>
  </div>
  )}
  </div>
  );
}
