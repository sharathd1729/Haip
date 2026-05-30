"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart, Bar, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Legend,
} from "recharts";
import { DollarSign, TrendingUp, Calendar, Star } from "lucide-react";
import { KpiCard } from "@/components/analytics/KpiCard";
import { Skeleton } from "@/components/ui/skeleton";
import api from "@/lib/api";

interface RevPoint {
  month: string;
  actual: number | null;
  forecast: number | null;
  lower_bound: number | null;
  upper_bound: number | null;
}
interface RevStats {
  mtd_actual: number;
  mtd_forecast: number;
  full_month_forecast: number;
  ytd_actual: number;
  ytd_forecast: number;
  best_month: string | null;
  best_month_revenue: number;
  series: RevPoint[];
}

function fmt(n: number) {
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(1)}Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(0)}k`;
  return `₹${Math.round(n)}`;
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-56 rounded-xl" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}
      </div>
      <Skeleton className="h-72 rounded-2xl" />
    </div>
  );
}

export default function RevenueForecastPage() {
  const { data: s, isLoading, isError } = useQuery<RevStats>({
    queryKey: ["rev-forecast"],
    queryFn: () => api.get("/analytics/forecasting/revenue").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  if (isLoading) return <PageSkeleton />;
  if (isError || !s) return <div className="p-6 text-center text-sm text-gray-400">Failed to load revenue forecast.</div>;

  const currentMonth = new Date().toISOString().slice(0, 7);

  const chartData = s.series.map(pt => ({
    month: pt.month.slice(2),  // YY-MM
    actual: pt.actual ?? undefined,
    forecast: pt.forecast ?? undefined,
    lower: pt.lower_bound ?? undefined,
    upper: pt.upper_bound ?? undefined,
    confidence: pt.lower_bound != null && pt.upper_bound != null
      ? pt.upper_bound - pt.lower_bound
      : undefined,
  }));

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 tracking-tight">Revenue Forecast</h1>
        <p className="text-[12px] mt-0.5 text-gray-400">MTD actuals + trend-based 12-month projection</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="MTD Actual" value={fmt(s.mtd_actual)}
          icon={<DollarSign size={14} className="text-teal-500" />} />
        <KpiCard label="Full Month Forecast" value={fmt(s.full_month_forecast)}
          icon={<TrendingUp size={14} className="text-teal-500" />} />
        <KpiCard label="YTD Actual" value={fmt(s.ytd_actual)}
          icon={<Calendar size={14} className="text-teal-500" />} />
        <KpiCard label="Best Month" value={s.best_month ?? "—"}
          icon={<Star size={14} className="text-amber-500" />} />
      </div>

      <div className="bg-white border border-gray-100 rounded-2xl p-5">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">12-Month Revenue — Actuals & Forecast</h2>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={chartData} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
            <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={v => fmt(v)} tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} width={64} />
            <Tooltip formatter={(v: any) => fmt(Number(v))} />
            <ReferenceLine x={currentMonth.slice(2)} stroke="#6366f1" strokeDasharray="4 2" />
            <Bar dataKey="actual" fill="#14b8a6" radius={[4, 4, 0, 0]} name="Actual" />
            <Area type="monotone" dataKey="forecast" stroke="#6366f1" fill="#ede9fe" strokeWidth={2}
              strokeDasharray="5 3" name="Forecast" connectNulls />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* YTD summary strip */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-teal-50 border border-teal-100 rounded-2xl p-5">
          <p className="text-xs text-teal-600 font-medium mb-1">YTD Actual</p>
          <p className="text-2xl font-bold text-teal-700">{fmt(s.ytd_actual)}</p>
        </div>
        <div className="bg-indigo-50 border border-indigo-100 rounded-2xl p-5">
          <p className="text-xs text-indigo-600 font-medium mb-1">YTD Forecast (incl. remaining year)</p>
          <p className="text-2xl font-bold text-indigo-700">{fmt(s.ytd_forecast)}</p>
          {s.best_month && (
            <p className="text-[11px] text-indigo-400 mt-1">Best month: {s.best_month} — {fmt(s.best_month_revenue)}</p>
          )}
        </div>
      </div>
    </div>
  );
}
