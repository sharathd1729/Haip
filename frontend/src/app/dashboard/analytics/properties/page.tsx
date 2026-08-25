"use client";


import { useState } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Home, TrendingUp, DollarSign, BarChart2, ChevronUp, ChevronDown } from "@/lib/icons";
import { KpiCard, deltaBetween } from "@/components/analytics/KpiCard";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

function fmt_inr(n: number) {
  if (n >= 10000000) return `â‚¹${(n/10000000).toFixed(1)}Cr`;
  if (n >= 100000)   return `â‚¹${(n/100000).toFixed(1)}L`;
  if (n >= 1000)     return `â‚¹${(n/1000).toFixed(0)}k`;
  return `â‚¹${Math.round(n)}`;
}

interface PropertyRow {
  id: string; name: string; type: string; city?: string;
  occupancy_pct: number; revenue_mtd: number; adr: number; revpar: number;
  total_stays: number; direct_pct: number; ota_pct: number;
}
interface PropertyStats {
  total_properties: number;
  portfolio_occupancy: number; portfolio_occupancy_prev: number;
  portfolio_revenue_mtd: number; portfolio_revenue_prev: number;
  portfolio_adr: number;
  properties: PropertyRow[];
}

type SortKey = "revenue_mtd" | "occupancy_pct" | "adr" | "revpar" | "total_stays";

function OccupancyBar({ pct }: { pct: number }) {
  const color = pct >= 70 ? "#14b8a6" : pct >= 40 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-gray-100 max-w-[60px]">
        <div className="h-full rounded-full" style={{ width: `${Math.min(pct, 100)}%`, background: color }} />
      </div>
      <span className="text-[11px] font-bold" style={{ color }}>{pct}%</span>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-44 rounded-xl" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[1,2,3,4].map(i => <Skeleton key={i} className="h-28 rounded-2xl" />)}</div>
      <Skeleton className="h-80 rounded-2xl" />
    </div>
  );
}

export default function PropertyAnalyticsPage() {
  const router = useRouter(); const pathname = usePathname(); const sp = useSearchParams();
  const rangeDays = parseInt(sp.get("range_days") ?? "30");
  const [sortKey, setSortKey] = useState<SortKey>("revenue_mtd");
  const [sortAsc, setSortAsc] = useState(false);

  const { data: s, isLoading } = useQuery<PropertyStats>({
    queryKey: ["analytics","properties_analytics", rangeDays],
    queryFn: () => api.get("/analytics/properties", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5*60_000,
  });

  const setRange = (d: number) => {
    const p = new URLSearchParams(sp.toString()); p.set("range_days", String(d));
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(a => !a);
    else { setSortKey(key); setSortAsc(false); }
  };

  if (isLoading) return <PageSkeleton />;
  if (!s) return null;

  const sorted = [...(s.properties ?? [])].sort((a, b) =>
    sortAsc ? a[sortKey] - b[sortKey] : b[sortKey] - a[sortKey]
  );

  const SortIcon = ({ k }: { k: SortKey }) => sortKey === k
    ? (sortAsc ? <ChevronUp size={11}/> : <ChevronDown size={11}/>)
    : null;

  const COLS: { key: SortKey; label: string }[] = [
    { key: "revenue_mtd",   label: "Revenue MTD" },
    { key: "occupancy_pct", label: "Occupancy" },
    { key: "adr",           label: "ADR" },
    { key: "revpar",        label: "RevPAR" },
    { key: "total_stays",   label: "Stays" },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>
      <div className="flex-shrink-0 px-6 py-4 border-b bg-white" style={{ borderColor: "var(--haip-border)" }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="haip-page-title">Property Analytics</h1>
            <p className="text-[12px] mt-0.5 text-gray-400">RevPAR, ADR, occupancy & revenue comparison matrix</p>
          </div>
          <div className="flex gap-2">
            {([7,14,30,90] as const).map(d => (
              <button key={d} onClick={() => setRange(d)}
                className={cn("px-3 py-1.5 rounded-xl text-[12px] font-medium border transition-colors",
                  rangeDays === d ? "bg-teal-600 text-white border-teal-600" : "bg-white text-gray-600 border-gray-200 hover:border-teal-300"
                )}>{d}d</button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto haip-scrollbar px-6 py-5 space-y-5">

        {/* KPIs */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Properties" value={s.total_properties} icon={<Home size={18}/>} />
          <KpiCard label="Portfolio Occupancy" value={`${s.portfolio_occupancy}%`}
            icon={<BarChart2 size={18}/>}
            delta={deltaBetween(s.portfolio_occupancy, s.portfolio_occupancy_prev)}
            variant={s.portfolio_occupancy < 40 ? "warning" : "default"} />
          <KpiCard label="Revenue MTD" value={fmt_inr(s.portfolio_revenue_mtd)}
            icon={<DollarSign size={18}/>}
            delta={deltaBetween(s.portfolio_revenue_mtd, s.portfolio_revenue_prev)} />
          <KpiCard label="Portfolio ADR" value={fmt_inr(s.portfolio_adr)} icon={<TrendingUp size={18}/>} />
        </div>

        {/* Matrix table + AI Insights */}
        <div className="grid grid-cols-12 gap-5">
          <div className="col-span-12 lg:col-span-8 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Property Comparison Matrix
            </h2>
            {sorted.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-[11px] min-w-[580px]">
                  <thead>
                    <tr className="border-b" style={{ borderColor: "var(--haip-border)" }}>
                      <th className="text-left py-2 font-semibold text-gray-500 pr-3">Property</th>
                      {COLS.map(col => (
                        <th key={col.key} className="text-right py-2 font-semibold text-gray-500 pr-3 cursor-pointer hover:text-teal-600 select-none"
                          onClick={() => toggleSort(col.key)}>
                          <span className="flex items-center justify-end gap-1">{col.label}<SortIcon k={col.key} /></span>
                        </th>
                      ))}
                      <th className="text-right py-2 font-semibold text-gray-500">Direct%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((p, i) => (
                      <tr key={p.id} className={cn("border-b last:border-0 hover:bg-gray-50 transition-colors", i % 2 === 0 && "bg-gray-50/40")}
                        style={{ borderColor: "var(--haip-border)" }}>
                        <td className="py-3 pr-3">
                          <div>
                            <p className="font-semibold text-gray-800 truncate max-w-[140px]">{p.name}</p>
                            {p.city && <p className="text-[10px] text-gray-400">{p.city}</p>}
                          </div>
                        </td>
                        <td className="py-3 pr-3 text-right font-bold text-teal-700">{fmt_inr(p.revenue_mtd)}</td>
                        <td className="py-3 pr-3 text-right"><OccupancyBar pct={p.occupancy_pct} /></td>
                        <td className="py-3 pr-3 text-right font-mono text-gray-700">{fmt_inr(p.adr)}</td>
                        <td className="py-3 pr-3 text-right font-mono text-gray-700">{fmt_inr(p.revpar)}</td>
                        <td className="py-3 pr-3 text-right font-mono text-gray-700">{p.total_stays}</td>
                        <td className="py-3 text-right">
                          <span className="text-[11px] font-semibold text-teal-600">{p.direct_pct}%</span>
                          <span className="text-[10px] text-gray-400 ml-1">direct</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="h-[200px] flex items-center justify-center text-sm text-gray-400">No property data yet</div>
            )}
          </div>
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <AIInsightsPanel />
          </div>
        </div>

        {/* Occupancy heatmap tiles */}
        {sorted.length > 0 && (
          <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Occupancy Heatmap
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
              {sorted.map(p => {
                const pct = p.occupancy_pct;
                const cls = pct >= 80 ? "bg-teal-500 text-white" : pct >= 60 ? "bg-teal-300 text-teal-900" :
                            pct >= 40 ? "bg-amber-200 text-amber-900" : pct >= 20 ? "bg-orange-200 text-orange-900" : "bg-red-100 text-red-700";
                return (
                  <div key={p.id} className={cn("rounded-xl p-2.5 text-center", cls)} title={p.name}>
                    <p className="text-[20px] font-black leading-none">{pct}%</p>
                    <p className="text-[10px] mt-1 truncate font-medium opacity-80">{p.name}</p>
                  </div>
                );
              })}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
