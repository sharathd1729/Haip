"use client";

import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, Legend,
} from "recharts";
import { Users, RefreshCw, Star, DollarSign } from "lucide-react";
import { KpiCard } from "@/components/analytics/KpiCard";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface CohortRow {
  cohort: string;
  guests: number;
  returned_pct: number;
  avg_stays: number;
  avg_ltv: number;
  vip_pct: number;
}
interface CohortStats {
  total_guests: number;
  repeat_rate: number;
  avg_ltv: number;
  vip_rate: number;
  cohorts: CohortRow[];
}

function fmt(n: number) {
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(0)}k`;
  return `₹${Math.round(n)}`;
}

const COHORT_COLORS = ["#14b8a6", "#6366f1", "#f59e0b", "#ec4899", "#3b82f6", "#10b981", "#f97316", "#8b5cf6"];

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-48" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}
      </div>
      <Skeleton className="h-64 rounded-2xl" />
      <Skeleton className="h-64 rounded-2xl" />
    </div>
  );
}

export default function CohortsPage() {
  const { data: s, isLoading, isError } = useQuery<CohortStats>({
    queryKey: ["cohorts"],
    queryFn: () => api.get("/analytics/forecasting/cohorts").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  if (isLoading) return <PageSkeleton />;
  if (isError || !s) return <div className="p-6 text-center text-sm text-gray-400">Failed to load cohort data.</div>;

  const retentionChart = s.cohorts.map((c, i) => ({
    cohort: c.cohort,
    returned: c.returned_pct,
    vip: c.vip_pct,
    fill: COHORT_COLORS[i % COHORT_COLORS.length],
  }));

  const ltvChart = s.cohorts.map((c, i) => ({
    cohort: c.cohort,
    ltv: c.avg_ltv,
    stays: c.avg_stays,
    fill: COHORT_COLORS[i % COHORT_COLORS.length],
  }));

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 tracking-tight">Guest Cohorts</h1>
        <p className="text-[12px] mt-0.5 text-gray-400">Acquisition quarter retention & LTV analysis</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Total Guests" value={s.total_guests}
          icon={<Users size={14} className="text-teal-500" />} />
        <KpiCard label="Repeat Rate" value={`${s.repeat_rate}%`}
          icon={<RefreshCw size={14} className="text-teal-500" />} />
        <KpiCard label="Avg LTV" value={fmt(s.avg_ltv)}
          icon={<DollarSign size={14} className="text-teal-500" />} />
        <KpiCard label="VIP Rate" value={`${s.vip_rate}%`}
          icon={<Star size={14} className="text-amber-500" />} />
      </div>

      {/* Retention chart */}
      <div className="bg-white border border-gray-100 rounded-2xl p-5">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">Retention Rate by Acquisition Cohort</h2>
        {retentionChart.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-8">No cohort data yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={retentionChart} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="cohort" tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={v => `${v}%`} tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} domain={[0, 100]} />
              <Tooltip formatter={(v: any) => `${Number(v)?.toFixed(1)}%`} />
              <Bar dataKey="returned" radius={[4, 4, 0, 0]} name="Returned %">
                {retentionChart.map((r, i) => <Cell key={i} fill={r.fill} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Cohort table */}
      <div className="bg-white border border-gray-100 rounded-2xl p-5 overflow-x-auto">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">Cohort Breakdown</h2>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-400 border-b border-gray-100">
              <th className="text-left pb-2 font-medium">Cohort</th>
              <th className="text-right pb-2 font-medium">Guests</th>
              <th className="text-right pb-2 font-medium">Returned %</th>
              <th className="text-right pb-2 font-medium">Avg Stays</th>
              <th className="text-right pb-2 font-medium">Avg LTV</th>
              <th className="text-right pb-2 font-medium">VIP %</th>
            </tr>
          </thead>
          <tbody>
            {s.cohorts.map((c, i) => (
              <tr key={c.cohort} className="border-b border-gray-50 hover:bg-gray-50/60">
                <td className="py-2.5 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full inline-block" style={{ background: COHORT_COLORS[i % COHORT_COLORS.length] }} />
                  <span className="font-medium text-gray-800">{c.cohort}</span>
                </td>
                <td className="text-right py-2.5 text-gray-700">{c.guests}</td>
                <td className="text-right py-2.5">
                  <span className={cn("font-semibold", c.returned_pct >= 50 ? "text-teal-600" : "text-gray-600")}>
                    {c.returned_pct}%
                  </span>
                </td>
                <td className="text-right py-2.5 text-gray-700">{c.avg_stays}</td>
                <td className="text-right py-2.5 text-gray-700">{fmt(c.avg_ltv)}</td>
                <td className="text-right py-2.5">
                  <span className={cn("font-semibold", c.vip_pct >= 10 ? "text-amber-600" : "text-gray-500")}>
                    {c.vip_pct}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
