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
  if (score >= 80) return { stroke: "#4361EE", text: "text-indigo-500" }; // indigo
  if (score >= 60) return { stroke: "#f59e0b", text: "text-amber-500" }; // amber
  return { stroke: "#ef4444", text: "text-red-500" };                     // red
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
          className="text-gray-100"
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
          <span className="text-[9px] text-gray-400 uppercase tracking-wide leading-tight mt-0.5">
            score
          </span>
        </div>
      )}
    </div>
  );
}
