// A small bar chart for a dashboard card (owner, 28 Nov 2026; dataviz rules): one hue per chart, the latest bar at full
// strength with its value and "Today" under it, earlier bars lighter. An optional second value stacks on top (calls: missed on
// top of answered, the one validated two-colour pair). Each bar carries its full text as a native tooltip and for screen
// readers; the grid is recessive; values are text tokens, never the series colour. Drawn as SVG with geometry in attributes
// (no inline styles). It adapts to its own width: on a narrow card every other day label is hidden.
import { cn } from "@/lib/utils";

export interface Bar {
  /** Short x label, e.g. "27" or "M". */
  label: string;
  value: number;
  /** A second amount stacked on top (e.g. missed calls). */
  top?: number;
  /** Tooltip and screen-reader text, e.g. "Fri 27 Nov: 4 new leads". */
  tip: string;
  /** The latest bucket (today): drawn at full strength and labelled. */
  now?: boolean;
}

/** A round axis maximum at or above `v` (4, 5, 10, 20, 40, 50, 100, ...). Exported for tests. */
export function niceMax(v: number): number {
  if (v <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 4, 5, 10]) if (v <= m * pow) return m * pow;
  return 10 * pow;
}

const TOP_PAD = 20;      // room for the value above the latest bar

export function MiniBars({ bars, height = 112, yAxis = false, nowLabel = "Today", label, className }: {
  bars: Bar[];
  height?: number;
  /** Show three y ticks on the left (desktop cards). */
  yAxis?: boolean;
  nowLabel?: string;
  /** What the chart shows, for screen readers. */
  label: string;
  className?: string;
}) {
  const stacked = bars.some(b => b.top != null);
  // Round the scale up only when ticks are drawn; a tick-less chart (phone) lets its tallest bar use the full height.
  const peak = Math.max(1, ...bars.map(b => b.value + (b.top ?? 0)));
  const max = yAxis ? niceMax(peak) : peak;
  const usable = height - TOP_PAD;
  const px = (v: number) => (v <= 0 ? 0 : Math.max(3, (v / max) * usable));
  const n = Math.max(1, bars.length);
  const slot = 100 / n;                                  // % of the width per bar
  const barW = Math.min(slot * 0.62, 100 / Math.max(n, 14) * 1.1);
  const ticks = yAxis ? [0, max / 2, max] : [];
  return (
    <div className={cn("@container min-w-0", className)}>
      <div className={cn(yAxis && "pl-7")}>
      <svg role="img" aria-label={`${label}: ${bars.map(b => b.tip).join("; ")}`} width="100%" height={height} className="block overflow-visible">
        {ticks.map(t => {
          const y = height - (t / max) * usable;
          return (
            <g key={t} aria-hidden>
              <line x1="0" x2="100%" y1={y} y2={y} strokeDasharray={t === 0 ? undefined : "3 3"} className="stroke-[var(--haip-border)]" />
              <text x="-6" y={y + 4} textAnchor="end" className="fill-[var(--haip-fg-subtle)] text-[11px] tabular-nums">{t}</text>
            </g>
          );
        })}
        {!yAxis && <line aria-hidden x1="0" x2="100%" y1={height} y2={height} className="stroke-[var(--haip-border)]" />}
        {bars.map((b, i) => {
          const x = i * slot + (slot - barW) / 2;
          const hv = px(b.value), ht = px(b.top ?? 0);
          return (
            <g key={i} className="hover:brightness-90">
              <title>{b.tip}</title>
              <rect x={`${i * slot}%`} y="0" width={`${slot}%`} height={height} fill="transparent" />
              <rect x={`${x}%`} y={height - hv} width={`${barW}%`} height={hv} rx={stacked && ht > 0 ? 0 : 3}
                className={stacked ? "fill-[var(--haip-viz-answered)]" : b.now ? "fill-primary" : "fill-[var(--haip-viz-soft)]"} />
              {stacked && ht > 0 && <rect x={`${x}%`} y={height - hv - ht - 2} width={`${barW}%`} height={ht} rx="3" className="fill-[var(--haip-viz-missed)]" />}
              {b.now && !stacked && (
                <text x={`${i * slot + slot / 2}%`} y={height - hv - 6} textAnchor="middle" aria-hidden className="fill-[var(--haip-fg)] text-[12px] font-bold tabular-nums">{b.value}</text>
              )}
            </g>
          );
        })}
      </svg>
      </div>
      <div aria-hidden className={cn("mt-1 flex", yAxis && "pl-7")}>
        {bars.map((b, i) => (
          <span key={i} className={cn("min-w-0 flex-1 whitespace-nowrap text-center text-[11px] tabular-nums",
            b.now ? "font-bold text-[var(--haip-fg)]" : "text-[var(--haip-fg-subtle)]",
            !b.now && bars.length > 8 && i % 2 === 1 && "invisible @[520px]:visible")}>
            {b.now ? nowLabel : b.label}
          </span>
        ))}
      </div>
    </div>
  );
}
