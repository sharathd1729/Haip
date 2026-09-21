"use client";
// Six KPI tiles, each with a per-day sparkline (when the backend has a
// series for it) and a change-vs-previous-period pill.
import { cn } from "@/lib/utils";
import { formatRupees, formatSeconds, type KPIDelta, type OverviewResponse } from "./types";

function Sparkline({ values, color }: { values: (number | null)[]; color: string }) {
  const pts = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] != null);
  if (pts.length < 2) return null;
  const W = 84, H = 34;
  const max = Math.max(...pts.map(p => p[1]));
  const min = Math.min(...pts.map(p => p[1]));
  const span = max - min || 1;
  const x = (i: number) => (i / (values.length - 1)) * (W - 4) + 2;
  const y = (v: number) => H - 3 - ((v - min) / span) * (H - 8);
  const line = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(pts[pts.length - 1][0]).toFixed(1)},${H} L${x(pts[0][0]).toFixed(1)},${H} Z`;
  const last = pts[pts.length - 1];
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden className="flex-shrink-0">
      <path d={area} fill={color} opacity={0.08} />
      <path d={line} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" />
      <circle cx={x(last[0])} cy={y(last[1])} r={2.6} fill={color} />
    </svg>
  );
}

function Pill({ text, good }: { text: string; good: boolean | null }) {
  return (
    <span className={cn("text-[11px] font-bold px-2 py-0.5 rounded-full tabular-nums",
      good == null ? "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"
        : good ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
          : "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300")}>
      {text}
    </span>
  );
}

function pctPill(d?: KPIDelta, lowerIsBetter = false) {
  if (!d || d.direction === "neutral") return null;
  const up = d.direction === "up";
  return <Pill text={`${up ? "+" : "−"}${Math.abs(d.pct)}%`} good={lowerIsBetter ? !up : up} />;
}

interface Tile { label: string; value: string; spark?: (number | null)[]; pill: React.ReactNode }

export function KpiTiles({ data }: { data: OverviewResponse }) {
  const { kpi, kpi_deltas: d, series, calls } = data;
  const inbound = calls.answered + calls.missed;
  const answeredPct = inbound ? Math.round((100 * calls.answered) / inbound) : null;

  const tiles: Tile[] = [
    { label: "New leads", value: String(kpi.total_leads), spark: series.leads, pill: pctPill(d.total_leads) },
    { label: "Avg first reply", value: formatSeconds(kpi.avg_response_seconds), pill: pctPill(d.avg_response_seconds, true) },
    {
      label: "Calls answered", value: answeredPct != null ? `${answeredPct}%` : "—", spark: series.calls_answered_pct,
      pill: calls.missed ? <Pill text={`${calls.missed} missed`} good={null} /> : null,
    },
    { label: "Bookings", value: String(kpi.bookings), spark: series.bookings, pill: pctPill(d.bookings) },
    { label: "Revenue", value: formatRupees(kpi.revenue), spark: series.revenue, pill: pctPill(d.revenue) },
    { label: "Lead → booking", value: `${kpi.conversion_rate}%`, pill: pctPill(d.conversion_rate) },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
      {tiles.map(t => (
        <div key={t.label} className="haip-card px-4 py-3 flex flex-col gap-1.5 min-w-0">
          <span className="text-xs font-semibold truncate" style={{ color: "var(--haip-fg-subtle)" }}>{t.label}</span>
          <div className="flex items-end justify-between gap-2">
            <span className="text-2xl font-bold tabular-nums truncate" style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display)" }}>
              {t.value}
            </span>
            {t.spark && <Sparkline values={t.spark} color="#0F766E" />}
          </div>
          <span className="h-5">{t.pill}</span>
        </div>
      ))}
    </div>
  );
}
