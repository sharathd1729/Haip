"use client";


/**
 * /dashboard/analytics/attribution â€” Revenue Attribution Intelligence
 * âœ¦ HAIP Hospitality Intelligence
 *
 * First-touch / last-touch channel breakdown, journey paths, days to convert.
 */

import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Cell,
} from "recharts";
import { Clock, Zap, TrendingUp } from "@/lib/icons";
import { GitBranch } from "lucide-react";
import { KpiCard } from "@/components/analytics/KpiCard";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

// â”€â”€â”€ Channel colour palette â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const CH_COLORS: Record<string, string> = {
  WHATSAPP:  "#25d366",
  INSTAGRAM: "#e1306c",
  META_IG:   "#e1306c",
  PHONE:     "#3b82f6",
  CALL:      "#3b82f6",
  EMAIL:     "#f59e0b",
  DIRECT:    "#14b8a6",
  WEBSITE:   "#6366f1",
  OTA:       "#8b5cf6",
  AIRBNB:    "#ff5a5f",
  BOOKING:   "#003580",
  WALK_IN:   "#10b981",
};

function chColor(source: string) {
  return CH_COLORS[source.toUpperCase()] ?? "#9ca3af";
}

function fmt_inr(n: number) {
  if (n >= 10000000) return `â‚¹${(n / 10000000).toFixed(1)}Cr`;
  if (n >= 100000)   return `â‚¹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000)     return `â‚¹${(n / 1000).toFixed(0)}k`;
  return `â‚¹${Math.round(n)}`;
}

function fmt_pct(n: number) {
  return `${n.toFixed(1)}%`;
}

// â”€â”€â”€ Types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

interface AttributionSourceRow {
  source: string;
  inquiries: number;
  converted: number;
  conversion_pct: number;
  revenue: number;
  avg_days_to_convert: number;
}

interface JourneyPathRow {
  path: string;
  count: number;
  conversion_pct: number;
  avg_days: number;
}

interface AttributionStats {
  total_bookings: number;
  avg_touchpoints: number;
  avg_days_to_convert: number;
  top_first_touch?: string;
  top_first_touch_revenue: number;
  top_last_touch?: string;
  top_last_touch_revenue: number;
  fastest_channel?: string;
  first_touch_breakdown: AttributionSourceRow[];
  last_touch_breakdown: AttributionSourceRow[];
  journey_paths: JourneyPathRow[];
}

// â”€â”€â”€ Skeleton â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-56 rounded-xl" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-64 rounded-2xl" />
      <Skeleton className="h-64 rounded-2xl" />
    </div>
  );
}

// â”€â”€â”€ Range selector â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const RANGES = [
  { label: "7d",  days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];

// â”€â”€â”€ Source label normalizer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function srcLabel(s: string) {
  const map: Record<string, string> = {
    WHATSAPP: "WhatsApp",
    INSTAGRAM: "Instagram",
    META_IG: "Meta/IG",
    PHONE: "Phone",
    CALL: "Call",
    EMAIL: "Email",
    DIRECT: "Direct",
    WEBSITE: "Website",
    OTA: "OTA",
    AIRBNB: "Airbnb",
    BOOKING: "Booking.com",
    WALK_IN: "Walk-in",
  };
  return map[s.toUpperCase()] ?? s;
}

// â”€â”€â”€ Custom bar tooltip â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function SourceTooltip({ active, payload }: { active?: boolean; payload?: { payload: AttributionSourceRow }[] }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-lg p-3 text-xs space-y-0.5">
      <p className="font-semibold text-gray-800">{srcLabel(row.source)}</p>
      <p className="text-gray-500">Inquiries: <span className="text-gray-800 font-medium">{row.inquiries}</span></p>
      <p className="text-gray-500">Converted: <span className="text-gray-800 font-medium">{row.converted}</span></p>
      <p className="text-gray-500">CVR: <span className="text-teal-600 font-semibold">{fmt_pct(row.conversion_pct)}</span></p>
      <p className="text-gray-500">Revenue: <span className="text-teal-600 font-semibold">{fmt_inr(row.revenue)}</span></p>
      <p className="text-gray-500">Avg days: <span className="text-gray-800 font-medium">{row.avg_days_to_convert}d</span></p>
    </div>
  );
}

// â”€â”€â”€ Page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export default function AttributionPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const rangeDays = Number(searchParams.get("range_days") ?? "30");

  function setRange(days: number) {
    const p = new URLSearchParams(searchParams.toString());
    p.set("range_days", String(days));
    router.push(`${pathname}?${p.toString()}`);
  }

  const { data: s, isLoading, isError } = useQuery<AttributionStats>({
    queryKey: ["analytics-attribution", rangeDays],
    queryFn: () =>
      api.get("/analytics/attribution", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5 * 60_000,
  });

  if (isLoading) return <PageSkeleton />;
  if (isError || !s) {
    return (
      <div className="p-6 text-center text-sm text-gray-400">
        Failed to load attribution data.
      </div>
    );
  }

  const firstRows = s.first_touch_breakdown.slice(0, 8);
  const lastRows  = s.last_touch_breakdown.slice(0, 8);
  const paths     = s.journey_paths.slice(0, 8);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="haip-page-title">Revenue Attribution</h1>
          <p className="text-[12px] mt-0.5 text-gray-400">First-touch & last-touch channel credit, journey paths</p>
        </div>
        <div className="flex items-center gap-1 bg-gray-100 rounded-xl p-1">
          {RANGES.map(r => (
            <button
              key={r.days}
              onClick={() => setRange(r.days)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                rangeDays === r.days
                  ? "bg-white shadow text-gray-900"
                  : "text-gray-500 hover:text-gray-700",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard
          label="Total Bookings"
          value={s.total_bookings}
          icon={<TrendingUp size={14} className="text-teal-500" />}
        />
        <KpiCard
          label="Avg Touchpoints"
          value={s.avg_touchpoints.toFixed(1)}
          icon={<GitBranch size={14} className="text-teal-500" />}
        />
        <KpiCard
          label="Avg Days to Convert"
          value={`${s.avg_days_to_convert}d`}
          icon={<Clock size={14} className="text-teal-500" />}
        />
        <KpiCard
          label="Fastest Channel"
          value={s.fastest_channel ? srcLabel(s.fastest_channel) : "â€”"}
          icon={<Zap size={14} className="text-teal-500" />}
        />
      </div>

      {/* AI Insights */}
      <AIInsightsPanel />

      {/* First-touch breakdown */}
      <div className="haip-card p-5">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">First-Touch Revenue by Channel</h2>
        {firstRows.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-8">No data for this period.</p>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={firstRows} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis
                dataKey="source"
                tickFormatter={srcLabel}
                tick={{ fontSize: 11, fill: "#9ca3af" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tickFormatter={v => fmt_inr(v)}
                tick={{ fontSize: 11, fill: "#9ca3af" }}
                axisLine={false}
                tickLine={false}
                width={60}
              />
              <Tooltip content={<SourceTooltip />} />
              <Bar dataKey="revenue" radius={[6, 6, 0, 0]}>
                {firstRows.map((row, i) => (
                  <Cell key={i} fill={chColor(row.source)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Last-touch breakdown */}
      <div className="haip-card p-5">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">Last-Touch Revenue by Channel</h2>
        {lastRows.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-8">No data for this period.</p>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={lastRows} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis
                dataKey="source"
                tickFormatter={srcLabel}
                tick={{ fontSize: 11, fill: "#9ca3af" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tickFormatter={v => fmt_inr(v)}
                tick={{ fontSize: 11, fill: "#9ca3af" }}
                axisLine={false}
                tickLine={false}
                width={60}
              />
              <Tooltip content={<SourceTooltip />} />
              <Bar dataKey="revenue" radius={[6, 6, 0, 0]}>
                {lastRows.map((row, i) => (
                  <Cell key={i} fill={chColor(row.source)} fillOpacity={0.75} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Comparison table: first vs last touch */}
      <div className="haip-card p-5 overflow-x-auto">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">Channel Comparison</h2>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-400 border-b border-gray-100">
              <th className="text-left pb-2 font-medium">Channel</th>
              <th className="text-right pb-2 font-medium">First-touch CVR</th>
              <th className="text-right pb-2 font-medium">First-touch Rev</th>
              <th className="text-right pb-2 font-medium">Last-touch CVR</th>
              <th className="text-right pb-2 font-medium">Last-touch Rev</th>
              <th className="text-right pb-2 font-medium">Avg Days</th>
            </tr>
          </thead>
          <tbody>
            {firstRows.map((row, i) => {
              const last = s.last_touch_breakdown.find(r => r.source === row.source);
              return (
                <tr
                  key={i}
                  className="border-b border-gray-50 hover:bg-gray-50/60 transition-colors"
                >
                  <td className="py-2.5 flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full inline-block"
                      style={{ background: chColor(row.source) }}
                    />
                    <span className="font-medium text-gray-800">{srcLabel(row.source)}</span>
                  </td>
                  <td className="text-right py-2.5 text-teal-600 font-medium">{fmt_pct(row.conversion_pct)}</td>
                  <td className="text-right py-2.5 text-gray-700">{fmt_inr(row.revenue)}</td>
                  <td className="text-right py-2.5 text-teal-600 font-medium">{last ? fmt_pct(last.conversion_pct) : "â€”"}</td>
                  <td className="text-right py-2.5 text-gray-700">{last ? fmt_inr(last.revenue) : "â€”"}</td>
                  <td className="text-right py-2.5 text-gray-500">{row.avg_days_to_convert}d</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Journey paths */}
      <div className="haip-card p-5">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">Top Booking Journeys</h2>
        {paths.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-8">No journey data yet.</p>
        ) : (
          <div className="space-y-2">
            {paths.map((p, i) => {
              const maxCount = paths[0].count;
              const pct = Math.round((p.count / maxCount) * 100);
              return (
                <div key={i} className="flex items-center gap-3 group">
                  <span className="text-[11px] text-gray-400 w-4 text-right">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-xs font-medium text-gray-700 truncate">{p.path}</span>
                      <span className="text-[11px] text-gray-400 ml-2 shrink-0">
                        {p.count} inquiries Â· {fmt_pct(p.conversion_pct)} CVR Â· {p.avg_days}d
                      </span>
                    </div>
                    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-teal-400 rounded-full transition-all"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
