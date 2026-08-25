"use client";


import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, ReferenceLine,
} from "recharts";
import { Building2, TrendingUp, TrendingDown, Minus, CalendarX } from "@/lib/icons";
import { KpiCard } from "@/components/analytics/KpiCard";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface OccForecastPoint {
  date: string;
  actual_pct: number | null;
  forecast_pct: number | null;
  is_blocked: boolean;
}
interface PropertyForecast {
  property_id: string;
  property_name: string;
  current_occ_pct: number;
  forecast_30d_pct: number;
  trend: "up" | "down" | "flat";
  series: OccForecastPoint[];
}
interface OccStats {
  portfolio_current_occ: number;
  portfolio_forecast_30d: number;
  highest_demand_date: string | null;
  lowest_demand_date: string | null;
  properties: PropertyForecast[];
}

const RANGES = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "60d", days: 60 },
];

const PROP_COLORS = ["#14b8a6", "#6366f1", "#f59e0b", "#ec4899", "#3b82f6", "#10b981"];

function TrendIcon({ trend }: { trend: string }) {
  if (trend === "up") return <TrendingUp size={14} className="text-green-500" />;
  if (trend === "down") return <TrendingDown size={14} className="text-red-500" />;
  return <Minus size={14} className="text-gray-400" />;
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-56 rounded-xl" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}
      </div>
      <Skeleton className="h-72 rounded-2xl" />
      <Skeleton className="h-48 rounded-2xl" />
    </div>
  );
}

export default function OccupancyForecastPage() {
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const rangeDays = Number(sp.get("range_days") ?? "30");

  function setRange(d: number) {
    const p = new URLSearchParams(sp.toString());
    p.set("range_days", String(d));
    router.push(`${pathname}?${p.toString()}`);
  }

  const { data: s, isLoading, isError } = useQuery<OccStats>({
    queryKey: ["occ-forecast", rangeDays],
    queryFn: () => api.get("/analytics/forecasting/occupancy", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5 * 60_000,
  });

  if (isLoading) return <PageSkeleton />;
  if (isError || !s) return <div className="p-6 text-center text-sm text-gray-400">Failed to load occupancy forecast.</div>;

  const today = new Date().toISOString().slice(0, 10);

  // Build portfolio chart series from first property (or aggregate)
  const portfolioSeries = s.properties.length > 0
    ? s.properties[0].series.map(pt => ({
        date: pt.date.slice(5),  // MM-DD
        actual: pt.actual_pct,
        forecast: pt.forecast_pct,
        blocked: pt.is_blocked ? 0 : null,
      }))
    : [];

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="haip-page-title">Occupancy Forecast</h1>
          <p className="text-[12px] mt-0.5 text-gray-400">Trend-based projection for the next {rangeDays} days</p>
        </div>
        <div className="flex items-center gap-1 bg-gray-100 rounded-xl p-1">
          {RANGES.map(r => (
            <button key={r.days} onClick={() => setRange(r.days)}
              className={cn("px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                rangeDays === r.days ? "bg-white shadow text-gray-900" : "text-gray-500 hover:text-gray-700")}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Portfolio Occupancy (30d)" value={`${s.portfolio_current_occ}%`}
          icon={<Building2 size={14} className="text-teal-500" />} />
        <KpiCard label={`Forecast (${rangeDays}d)`} value={`${s.portfolio_forecast_30d}%`}
          icon={<TrendingUp size={14} className="text-teal-500" />} />
        <KpiCard label="Peak Demand Date"
          value={s.highest_demand_date ? s.highest_demand_date.slice(5) : "â€”"}
          icon={<TrendingUp size={14} className="text-green-500" />} />
        <KpiCard label="Lowest Demand Date"
          value={s.lowest_demand_date ? s.lowest_demand_date.slice(5) : "â€”"}
          icon={<CalendarX size={14} className="text-red-400" />} />
      </div>

      {/* Portfolio chart */}
      {s.properties.length > 0 && (
        <div className="haip-card p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-4">
            {s.properties[0].property_name} â€” Occupancy Trend & Forecast
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={portfolioSeries} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} interval={6} />
              <YAxis tickFormatter={v => `${v}%`} tick={{ fontSize: 11, fill: "#9ca3af" }} axisLine={false} tickLine={false} domain={[0, 100]} />
              <Tooltip formatter={(v: any) => `${Number(v)?.toFixed(0)}%`} />
              <ReferenceLine x={today.slice(5)} stroke="#6366f1" strokeDasharray="4 2" label={{ value: "Today", fontSize: 10, fill: "#6366f1" }} />
              <Area type="monotone" dataKey="actual" stroke="#14b8a6" fill="#ccfbf1" strokeWidth={2} name="Actual" connectNulls />
              <Line type="monotone" dataKey="forecast" stroke="#6366f1" strokeWidth={2} strokeDasharray="5 3" dot={false} name="Forecast" connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Property table */}
      <div className="haip-card p-5 overflow-x-auto">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">Property Breakdown</h2>
        {s.properties.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-8">No property data available.</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-400 border-b border-gray-100">
                <th className="text-left pb-2 font-medium">Property</th>
                <th className="text-right pb-2 font-medium">Current Occ %</th>
                <th className="text-right pb-2 font-medium">Forecast %</th>
                <th className="text-right pb-2 font-medium">Trend</th>
              </tr>
            </thead>
            <tbody>
              {s.properties.map((p, i) => (
                <tr key={p.property_id} className="border-b border-gray-50 hover:bg-gray-50/60">
                  <td className="py-2.5 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full inline-block" style={{ background: PROP_COLORS[i % PROP_COLORS.length] }} />
                    <span className="font-medium text-gray-800">{p.property_name}</span>
                  </td>
                  <td className="text-right py-2.5 text-gray-700">{p.current_occ_pct}%</td>
                  <td className="text-right py-2.5 text-teal-600 font-semibold">{p.forecast_30d_pct}%</td>
                  <td className="text-right py-2.5">
                    <span className="flex items-center justify-end gap-1">
                      <TrendIcon trend={p.trend} />
                      <span className={p.trend === "up" ? "text-green-500" : p.trend === "down" ? "text-red-500" : "text-gray-400"}>
                        {p.trend}
                      </span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
