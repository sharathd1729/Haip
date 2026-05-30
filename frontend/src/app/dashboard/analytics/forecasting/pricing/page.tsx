"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from "recharts";
import { Zap, TrendingUp, TrendingDown, DollarSign } from "lucide-react";
import { KpiCard } from "@/components/analytics/KpiCard";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface PricingRow {
  property_id: string;
  property_name: string;
  current_price: number;
  suggested_price: number;
  delta_pct: number;
  reason: string;
  occupancy_pct: number;
  confidence: "high" | "medium" | "low";
}
interface PricingStats {
  avg_suggested_uplift_pct: number;
  properties_suggesting_increase: number;
  properties_suggesting_decrease: number;
  suggestions: PricingRow[];
}

function fmt(n: number) {
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(0)}k`;
  return `₹${Math.round(n)}`;
}

const CONFIDENCE_CFG = {
  high:   { bg: "bg-green-100",  text: "text-green-700",  label: "High" },
  medium: { bg: "bg-amber-100",  text: "text-amber-700",  label: "Medium" },
  low:    { bg: "bg-red-100",    text: "text-red-700",    label: "Low" },
};

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-56 rounded-xl" />
      <div className="grid grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}
      </div>
      <Skeleton className="h-72 rounded-2xl" />
      <Skeleton className="h-48 rounded-2xl" />
    </div>
  );
}

export default function PricingPage() {
  const { data: s, isLoading, isError } = useQuery<PricingStats>({
    queryKey: ["pricing-forecast"],
    queryFn: () => api.get("/analytics/forecasting/pricing").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  if (isLoading) return <PageSkeleton />;
  if (isError || !s) return <div className="p-6 text-center text-sm text-gray-400">Failed to load pricing suggestions.</div>;

  const chartData = s.suggestions.map(r => ({
    name: r.property_name.length > 16 ? r.property_name.slice(0, 14) + "…" : r.property_name,
    current: r.current_price,
    suggested: r.suggested_price,
    delta: r.delta_pct,
  }));

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 tracking-tight">Dynamic Pricing</h1>
        <p className="text-[12px] mt-0.5 text-gray-400">Occupancy-based price suggestions for the next 30 days</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <KpiCard label="Avg Suggested Uplift"
          value={`${s.avg_suggested_uplift_pct > 0 ? "+" : ""}${s.avg_suggested_uplift_pct}%`}
          icon={<Zap size={14} className="text-teal-500" />} />
        <KpiCard label="Properties: Increase"
          value={s.properties_suggesting_increase}
          icon={<TrendingUp size={14} className="text-green-500" />} />
        <KpiCard label="Properties: Decrease"
          value={s.properties_suggesting_decrease}
          icon={<TrendingDown size={14} className="text-red-400" />} />
      </div>

      {/* Current vs suggested bar chart */}
      <div className="bg-white border border-gray-100 rounded-2xl p-5">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">Current vs Suggested Price / Night</h2>
        {chartData.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-8">No pricing data yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={chartData} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={v => fmt(v)} tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} width={60} />
              <Tooltip formatter={(v: any) => fmt(Number(v))} />
              <Bar dataKey="current" fill="#e5e7eb" radius={[4, 4, 0, 0]} name="Current" />
              <Bar dataKey="suggested" radius={[4, 4, 0, 0]} name="Suggested">
                {chartData.map((r, i) => (
                  <Cell key={i} fill={r.delta > 0 ? "#14b8a6" : r.delta < 0 ? "#f97316" : "#9ca3af"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Suggestion cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {s.suggestions.map(row => {
          const conf = CONFIDENCE_CFG[row.confidence] ?? CONFIDENCE_CFG.medium;
          const isUp = row.delta_pct > 0;
          const isDown = row.delta_pct < 0;
          return (
            <div key={row.property_id} className="bg-white border border-gray-100 rounded-2xl p-4">
              <div className="flex items-start justify-between mb-2">
                <p className="text-sm font-semibold text-gray-800">{row.property_name}</p>
                <span className={cn("text-[10px] font-medium px-2 py-0.5 rounded-full", conf.bg, conf.text)}>
                  {conf.label} confidence
                </span>
              </div>
              <div className="flex items-center gap-3 mb-2">
                <div className="text-center">
                  <p className="text-[10px] text-gray-400">Current</p>
                  <p className="text-base font-bold text-gray-700">{fmt(row.current_price)}</p>
                </div>
                <span className={cn("text-lg font-bold", isUp ? "text-green-500" : isDown ? "text-red-500" : "text-gray-400")}>
                  {isUp ? "↑" : isDown ? "↓" : "→"}
                </span>
                <div className="text-center">
                  <p className="text-[10px] text-gray-400">Suggested</p>
                  <p className={cn("text-base font-bold", isUp ? "text-teal-600" : isDown ? "text-orange-500" : "text-gray-700")}>
                    {fmt(row.suggested_price)}
                  </p>
                </div>
                <div className={cn("ml-auto text-xs font-semibold px-2 py-1 rounded-lg",
                  isUp ? "bg-teal-50 text-teal-700" : isDown ? "bg-orange-50 text-orange-700" : "bg-gray-50 text-gray-500")}>
                  {row.delta_pct > 0 ? "+" : ""}{row.delta_pct}%
                </div>
              </div>
              <p className="text-[11px] text-gray-500">{row.reason}</p>
              <div className="mt-2 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-teal-400 rounded-full" style={{ width: `${row.occupancy_pct}%` }} />
              </div>
              <p className="text-[10px] text-gray-400 mt-0.5">{row.occupancy_pct}% occupancy next 30d</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
