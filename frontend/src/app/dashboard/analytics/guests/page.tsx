"use client";


import { useState, useMemo } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, LineChart, Line, PieChart, Pie, Cell,
} from "recharts";
import { Users, TrendingUp, Star, RepeatIcon, DollarSign, Home, ChevronDown } from "lucide-react";
import { KpiCard, DeltaChip, deltaBetween } from "@/components/analytics/KpiCard";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

const TEAL = "#14b8a6"; const AMBER = "#fbbf24"; const GRAY = "#e5e7eb";
const VIP_COLORS: Record<string, string> = { platinum: "#7c3aed", gold: "#d97706", silver: "#6b7280" };
const LTV_COLORS = ["#ef4444","#f59e0b","#14b8a6","#6366f1"];

function fmt_inr(n: number) {
  if (n >= 100000) return `â‚¹${(n/100000).toFixed(1)}L`;
  if (n >= 1000)   return `â‚¹${(n/1000).toFixed(0)}k`;
  return `â‚¹${n.toFixed(0)}`;
}

interface GuestStats {
  total_guests: number; total_guests_prev: number;
  new_guests: number; new_guests_prev: number;
  repeat_guests_pct: number; repeat_guests_pct_prev: number;
  avg_ltv: number; avg_ltv_prev: number;
  avg_stays: number;
  ltv_distribution: { bucket: string; count: number }[];
  vip_breakdown: { tier: string|null; count: number; avg_ltv: number }[];
  top_cities: { city: string; count: number; pct: number }[];
  acquisition_trend: { date: string; new_guests: number }[];
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-44 rounded-xl" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[1,2,3,4].map(i => <Skeleton key={i} className="h-28 rounded-2xl" />)}
      </div>
      <div className="grid grid-cols-12 gap-5">
        <Skeleton className="col-span-8 h-64 rounded-2xl" />
        <Skeleton className="col-span-4 h-64 rounded-2xl" />
      </div>
    </div>
  );
}

export default function GuestAnalyticsPage() {
  const router = useRouter(); const pathname = usePathname(); const sp = useSearchParams();
  const rangeDays = parseInt(sp.get("range_days") ?? "30");

  const { data: s, isLoading } = useQuery<GuestStats>({
    queryKey: ["analytics","guests", rangeDays],
    queryFn: () => api.get("/analytics/guests", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5*60_000,
  });

  const setRange = (d: number) => {
    const p = new URLSearchParams(sp.toString()); p.set("range_days", String(d));
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  if (isLoading) return <PageSkeleton />;
  if (!s) return null;

  const totalDelta  = deltaBetween(s.total_guests, s.total_guests_prev);
  const newDelta    = deltaBetween(s.new_guests, s.new_guests_prev);
  const repeatDelta = deltaBetween(s.repeat_guests_pct, s.repeat_guests_pct_prev);
  const ltvDelta    = deltaBetween(s.avg_ltv, s.avg_ltv_prev);

  const maxCity = Math.max(...(s.top_cities.map(c => c.count)), 1);

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>
      {/* Header */}
      <div className="flex-shrink-0 px-6 py-4 border-b bg-white" style={{ borderColor: "var(--haip-border)" }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="haip-page-title">
              Guest Analytics
            </h1>
            <p className="text-[12px] mt-0.5 text-gray-400">Guest lifecycle, LTV distribution & acquisition</p>
          </div>
          <div className="flex gap-2">
            {([7,14,30,90] as const).map(d => (
              <button key={d} onClick={() => setRange(d)}
                className={cn("px-3 py-1.5 rounded-xl text-[12px] font-medium border transition-colors",
                  rangeDays === d ? "bg-teal-600 text-white border-teal-600" : "bg-white text-gray-600 border-gray-200 hover:border-teal-300"
                )}>
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto haip-scrollbar px-6 py-5 space-y-5">

        {/* KPI row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Total Guests" value={s.total_guests.toLocaleString("en-IN")}
            icon={<Users size={18}/>} delta={totalDelta}
            subtext={`+${s.new_guests} new this period`} />
          <KpiCard label="New Guests" value={s.new_guests}
            icon={<TrendingUp size={18}/>} delta={newDelta} />
          <KpiCard label="Repeat Guests" value={`${s.repeat_guests_pct}%`}
            icon={<RepeatIcon size={18}/>} delta={repeatDelta}
            subtext="2+ stays" />
          <KpiCard label="Avg Lifetime Value" value={fmt_inr(s.avg_ltv)}
            icon={<DollarSign size={18}/>} delta={ltvDelta}
            subtext={`Avg stays: ${s.avg_stays}`} />
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-12 gap-5">

          {/* Acquisition trend */}
          <div className="col-span-12 lg:col-span-8 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              New Guest Acquisition â€” last {rangeDays} days
            </h2>
            {s.acquisition_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={s.acquisition_trend} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day:"numeric", month:"short" })}
                    interval={Math.max(0, Math.floor(s.acquisition_trend.length/6)-1)} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Line type="monotone" dataKey="new_guests" name="New guests" stroke={TEAL} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-sm text-gray-400">No acquisition data yet</div>
            )}
          </div>

          {/* AI Insights */}
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <AIInsightsPanel />
          </div>
        </div>

        {/* LTV + VIP + Cities */}
        <div className="grid grid-cols-12 gap-5">

          {/* LTV Distribution */}
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>LTV Distribution</h2>
            {s.ltv_distribution.some(b => b.count > 0) ? (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={s.ltv_distribution} layout="vertical" margin={{ left: 8 }}>
                  <XAxis type="number" tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="bucket" tick={{ fontSize: 11, fill: "#6b7280" }} tickLine={false} axisLine={false} width={60} />
                  <Tooltip />
                  <Bar dataKey="count" name="Guests" radius={[0,4,4,0]}>
                    {s.ltv_distribution.map((_, i) => <Cell key={i} fill={LTV_COLORS[i % LTV_COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[180px] flex items-center justify-center text-sm text-gray-400">No LTV data yet</div>
            )}
          </div>

          {/* VIP Tier */}
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>VIP Tier Breakdown</h2>
            <div className="space-y-3">
              {s.vip_breakdown.length > 0 ? s.vip_breakdown.map((row, i) => (
                <div key={i} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ background: VIP_COLORS[row.tier ?? ""] ?? "#9ca3af" }} />
                    <span className="text-[12px] capitalize text-gray-700">{row.tier ?? "Standard"}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-[13px] font-bold text-gray-800">{row.count}</span>
                    <span className="text-[10px] text-gray-400 ml-1">guests</span>
                  </div>
                  <span className="text-[11px] font-medium text-teal-600">{fmt_inr(row.avg_ltv)} avg</span>
                </div>
              )) : (
                <p className="text-sm text-gray-400 py-4 text-center">No VIP tier data</p>
              )}
            </div>
          </div>

          {/* Top Cities */}
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>Top Cities</h2>
            {s.top_cities.length > 0 ? (
              <div className="space-y-2.5">
                {s.top_cities.map((c, i) => (
                  <div key={i}>
                    <div className="flex justify-between text-[12px] mb-1">
                      <span className="truncate text-gray-700">{c.city}</span>
                      <span className="font-mono ml-2 text-gray-500">{c.count} ({c.pct}%)</span>
                    </div>
                    <div className="h-1.5 rounded-full" style={{ background: GRAY }}>
                      <div className="h-full rounded-full" style={{ width: `${(c.count/maxCity)*100}%`, background: TEAL }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400 py-4 text-center">No city data yet</p>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
