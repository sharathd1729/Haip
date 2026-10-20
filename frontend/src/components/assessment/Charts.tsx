"use client";
// Two small SVG pictures for the assessment report. Geometry comes from the backend (zoning rectangles on a 600 x 400
// canvas); nothing here computes a figure.
import type { AssessmentReport } from "@/lib/assessment";
import { pct } from "@/lib/assessment";

// Written out in full so Tailwind sees every class.
const ZONE_FILL: Record<string, string> = {
  rooms: "fill-[var(--mkt-gold)]",
  common: "fill-[var(--mkt-jade)]",
  venue: "fill-[var(--haip-accent)]",
  amenities: "fill-[var(--haip-status-warning-border)]",
  parking: "fill-[var(--haip-status-neutral-border)]",
  green: "fill-[var(--haip-status-success-bg)]",
};
const ZONE_SWATCH: Record<string, string> = {
  rooms: "bg-[var(--mkt-gold)]",
  common: "bg-[var(--mkt-jade)]",
  venue: "bg-[var(--haip-accent)]",
  amenities: "bg-[var(--haip-status-warning-border)]",
  parking: "bg-[var(--haip-status-neutral-border)]",
  green: "bg-[var(--haip-status-success-bg)]",
};
const ON_DARK = new Set(["rooms", "common", "venue"]);

export function ZoningSketch({ zoning }: { zoning: AssessmentReport["zoning"] }) {
  return (
    <figure>
      <svg viewBox={`0 0 ${zoning.width} ${zoning.height}`} className="w-full h-auto rounded-xl border border-[var(--mkt-border)]"
        role="img" aria-label="Indicative zoning sketch of the plot">
        {zoning.zones.map(z => (
          <g key={z.key}>
            <rect x={z.x} y={z.y} width={z.w} height={z.h} className={`${ZONE_FILL[z.key] ?? "fill-[var(--mkt-panel)]"} stroke-white`} strokeWidth={3} />
            {z.w > 110 && z.h > 44 && (
              <text x={z.x + 10} y={z.y + 24} className={`text-[15px] font-semibold ${ON_DARK.has(z.key) ? "fill-white" : "fill-[var(--mkt-text)]"}`}>
                {z.label.length > 22 ? `${z.label.slice(0, 21)}…` : z.label}
              </text>
            )}
          </g>
        ))}
      </svg>
      <ul className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5 text-[13px] text-[var(--mkt-muted)]">
        {zoning.zones.map(z => (
          <li key={z.key} className="flex items-center gap-2 min-w-0">
            <span className={`h-3 w-3 flex-shrink-0 rounded-sm ${ZONE_SWATCH[z.key] ?? ""}`} aria-hidden="true" />
            <span className="truncate">{z.label}</span>
            <span className="ml-auto tabular-nums whitespace-nowrap">{z.sqft.toLocaleString("en-IN")} sq ft · {z.pct}%</span>
          </li>
        ))}
      </ul>
      <figcaption className="mt-2 text-[12px] text-[var(--mkt-muted)]">
        Indicative block plan sized to your plot ({zoning.plot_sqft.toLocaleString("en-IN")} sq ft, rooms on {zoning.floors} floor{zoning.floors === 1 ? "" : "s"}).
        Not an architectural drawing.
      </figcaption>
    </figure>
  );
}

export function OccupancyCurve({ monthly }: { monthly: AssessmentReport["monthly"] }) {
  const W = 360, H = 150, top = 18, bottom = 22, gap = 6;
  const barW = (W - gap * 13) / 12;
  const peak = Math.max(0.01, ...monthly.map(m => m.occupancy.high));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img"
      aria-label={`Likely occupancy by month: ${monthly.map(m => `${m.month} ${pct(m.occupancy.likely)}`).join(", ")}`}>
      {monthly.map((m, i) => {
        const x = gap + i * (barW + gap);
        const span = H - top - bottom;
        const hi = (m.occupancy.high / peak) * span;
        const lk = (m.occupancy.likely / peak) * span;
        return (
          <g key={m.month}>
            <rect x={x} y={top + span - hi} width={barW} height={hi} rx={3} className="fill-[var(--mkt-surface)]" />
            <rect x={x} y={top + span - lk} width={barW} height={lk} rx={3} className="fill-[var(--mkt-gold)]" />
            <text x={x + barW / 2} y={top + span - lk - 4} textAnchor="middle" className="text-[9px] fill-[var(--mkt-muted)] tabular-nums">
              {Math.round(m.occupancy.likely * 100)}
            </text>
            <text x={x + barW / 2} y={H - 6} textAnchor="middle" className="text-[10px] fill-[var(--mkt-muted)]">{m.month}</text>
          </g>
        );
      })}
    </svg>
  );
}
