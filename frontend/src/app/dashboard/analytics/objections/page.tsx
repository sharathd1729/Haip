"use client";


/**
 * /dashboard/analytics/objections â€” Objection Intelligence
 * âœ¦ HAIP Hospitality Intelligence
 *
 * Why are bookings lost? Pareto of objections, revenue lost, competitor intel.
 */

import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, AreaChart, Area, Legend, Cell,
} from "recharts";
import { AlertTriangle, DollarSign, Swords, TrendingDown } from "lucide-react";
import { KpiCard } from "@/components/analytics/KpiCard";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

const GRAY = "#e5e7eb";
const OBJECTION_COLORS: Record<string, string> = {
  budget:        "#ef4444",
  dates:         "#f59e0b",
  weather:       "#3b82f6",
  competition:   "#8b5cf6",
  response_delay:"#f97316",
  capacity:      "#6366f1",
  undecided:     "#9ca3af",
  property_fit:  "#14b8a6",
  other:         "#d1d5db",
};

function fmt_inr(n: number) {
  if (n >= 10000000) return `â‚¹${(n/10000000).toFixed(1)}Cr`;
  if (n >= 100000) return `â‚¹${(n/100000).toFixed(1)}L`;
  if (n >= 1000)   return `â‚¹${(n/1000).toFixed(0)}k`;
  return `â‚¹${Math.round(n)}`;
}

interface ObjCat { code: string; label: string; count: number; pct: number; revenue_lost: number; cumulative_pct: number; }
interface Competitor { name: string; count: number; pct: number; }
interface ObjTrend { date: string; budget: number; dates: number; competition: number; other: number; }
interface ObjStats {
  total_lost: number; total_revenue_lost: number; top_objection?: string;
  top_objection_revenue_lost: number; budget_objection_pct: number; competitor_mention_count: number;
  objections: ObjCat[];
  competitors: Competitor[];
  trend: ObjTrend[];
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-44 rounded-xl" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[1,2,3,4].map(i => <Skeleton key={i} className="h-28 rounded-2xl" />)}</div>
      <div className="grid grid-cols-12 gap-5"><Skeleton className="col-span-8 h-64 rounded-2xl" /><Skeleton className="col-span-4 h-64 rounded-2xl" /></div>
    </div>
  );
}

export default function ObjectionIntelligencePage() {
  const router = useRouter(); const pathname = usePathname(); const sp = useSearchParams();
  const rangeDays = parseInt(sp.get("range_days") ?? "30");

  const { data: s, isLoading } = useQuery<ObjStats>({
    queryKey: ["analytics","objections", rangeDays],
    queryFn: () => api.get("/analytics/objections", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5*60_000,
  });

  const setRange = (d: number) => {
    const p = new URLSearchParams(sp.toString()); p.set("range_days", String(d));
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  if (isLoading) return <PageSkeleton />;
  if (!s) return null;

  const objs = s.objections ?? [];

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>
      <div className="flex-shrink-0 px-6 py-4 border-b bg-white" style={{ borderColor: "var(--haip-border)" }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs px-2 py-0.5 rounded-full bg-teal-100 text-teal-700 font-bold">âœ¦ Hospitality Intelligence</span>
            </div>
            <h1 className="haip-page-title mt-1">
              Objection Intelligence
            </h1>
            <p className="text-[12px] mt-0.5 text-gray-400">Why bookings are lost Â· Revenue at risk Â· Competitor intelligence</p>
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
          <KpiCard label="Lost Inquiries" value={s.total_lost}
            icon={<TrendingDown size={18}/>} variant="danger" />
          <KpiCard label="Revenue at Risk" value={fmt_inr(s.total_revenue_lost)}
            icon={<DollarSign size={18}/>} variant="danger"
            subtext={s.top_objection ? `Top: ${s.top_objection}` : undefined} />
          <KpiCard label="Budget Objections" value={`${s.budget_objection_pct}%`}
            icon={<AlertTriangle size={18}/>}
            variant={s.budget_objection_pct > 40 ? "danger" : s.budget_objection_pct > 25 ? "warning" : "default"} />
          <KpiCard label="Competitor Mentions" value={s.competitor_mention_count}
            icon={<Swords size={18}/>}
            variant={s.competitor_mention_count > 10 ? "warning" : "default"} />
        </div>

        {/* Pareto + AI Insights */}
        <div className="grid grid-cols-12 gap-5">
          <div className="col-span-12 lg:col-span-8 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Objection Pareto â€” Frequency & Cumulative %
            </h2>
            {objs.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={objs} margin={{ top: 0, right: 30, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#6b7280" }} tickLine={false} axisLine={false} />
                  <YAxis yAxisId="left" tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10, fill: "#9ca3af" }}
                    tickLine={false} axisLine={false} domain={[0, 100]} tickFormatter={v => `${v}%`} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: "11px" }} />
                  <Bar yAxisId="left" dataKey="count" name="Occurrences" radius={[4,4,0,0]}>
                    {objs.map((o, i) => (
                      <Cell key={i} fill={OBJECTION_COLORS[o.code] ?? "#9ca3af"} />
                    ))}
                  </Bar>
                  <Line yAxisId="right" type="monotone" dataKey="cumulative_pct" name="Cumulative %"
                    stroke="#6366f1" strokeWidth={2} dot={{ r: 3 }} />
                </ComposedChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[240px] flex items-center justify-center text-sm text-gray-400">No objection data yet</div>
            )}
          </div>
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <AIInsightsPanel />
          </div>
        </div>

        {/* Revenue lost + Trend */}
        <div className="grid grid-cols-12 gap-5">

          {/* Revenue lost per objection */}
          <div className="col-span-12 lg:col-span-5 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Revenue Lost by Objection
            </h2>
            {objs.some(o => o.revenue_lost > 0) ? (
              <div className="space-y-2.5">
                {objs.filter(o => o.revenue_lost > 0).map((o, i) => {
                  const maxRev = Math.max(...objs.map(x => x.revenue_lost), 1);
                  return (
                    <div key={i}>
                      <div className="flex justify-between text-[12px] mb-1">
                        <span className="font-medium text-gray-700 flex items-center gap-1.5">
                          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: OBJECTION_COLORS[o.code] ?? "#9ca3af" }} />
                          {o.label}
                        </span>
                        <span className="font-bold text-red-600">{fmt_inr(o.revenue_lost)}</span>
                      </div>
                      <div className="h-1.5 rounded-full" style={{ background: GRAY }}>
                        <div className="h-full rounded-full" style={{ width: `${(o.revenue_lost/maxRev)*100}%`, background: OBJECTION_COLORS[o.code] ?? "#ef4444" }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-gray-400 py-4 text-center">No revenue data yet</p>
            )}
          </div>

          {/* Objection trend */}
          <div className="col-span-12 lg:col-span-7 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Lost Reason Trend (weekly)
            </h2>
            {(s.trend ?? []).length > 0 ? (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={s.trend} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day:"numeric", month:"short" })}
                    interval={Math.max(0, Math.floor((s.trend?.length ?? 0)/5)-1)} />
                  <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: "11px" }} />
                  <Area type="monotone" dataKey="budget" name="Budget" stroke="#ef4444" fill="#ef444430" stackId="1" />
                  <Area type="monotone" dataKey="dates" name="Dates" stroke="#f59e0b" fill="#f59e0b30" stackId="1" />
                  <Area type="monotone" dataKey="competition" name="Competition" stroke="#8b5cf6" fill="#8b5cf630" stackId="1" />
                  <Area type="monotone" dataKey="other" name="Other" stroke="#9ca3af" fill="#9ca3af30" stackId="1" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[200px] flex items-center justify-center text-sm text-gray-400">No trend data yet</div>
            )}
          </div>
        </div>

        {/* Competitor intelligence */}
        {(s.competitors ?? []).length > 0 && (
          <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Competitor Intelligence
              <span className="text-[11px] font-normal text-gray-400 ml-2">Extracted from call transcripts</span>
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {s.competitors.map((c, i) => (
                <div key={i} className="rounded-xl border p-3 text-center" style={{ borderColor: "var(--haip-border)" }}>
                  <p className="text-[20px] font-black text-gray-800">{c.count}</p>
                  <p className="text-[11px] font-semibold text-gray-700 mt-0.5 truncate">{c.name}</p>
                  <p className="text-[10px] text-gray-400">{c.pct}% of calls</p>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
