"use client";

/**
 * /dashboard/analytics/intent — Guest Intent Analytics
 * ✦ HAIP Hospitality Intelligence
 *
 * Why do guests travel? Which intent converts best?
 * Data: call.occasion + inquiry.occasion → normalized intent buckets
 */

import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, Legend,
} from "recharts";
import { Target, TrendingUp, DollarSign, Moon, Sparkles } from "lucide-react";
import { KpiCard } from "@/components/analytics/KpiCard";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

// ─── Intent config ────────────────────────────────────────────────────────────

const INTENT_CONFIG: Record<string, { label: string; emoji: string; color: string }> = {
  honeymoon:      { label: "Honeymoon",       emoji: "💑", color: "#ec4899" },
  anniversary:    { label: "Anniversary",     emoji: "🥂", color: "#8b5cf6" },
  birthday:       { label: "Birthday",        emoji: "🎂", color: "#f59e0b" },
  friends_trip:   { label: "Friends Trip",    emoji: "🎉", color: "#06b6d4" },
  workcation:     { label: "Workcation",      emoji: "💻", color: "#3b82f6" },
  corporate:      { label: "Corporate",       emoji: "🏢", color: "#6366f1" },
  family_vacation:{ label: "Family Vacation", emoji: "👨‍👩‍👧", color: "#10b981" },
  long_stay:      { label: "Long Stay",       emoji: "📅", color: "#14b8a6" },
  weekend_getaway:{ label: "Weekend Getaway", emoji: "🌅", color: "#f97316" },
  other:          { label: "Other",           emoji: "✈️", color: "#9ca3af" },
};

function fmt_inr(n: number) {
  if (n >= 100000) return `₹${(n/100000).toFixed(1)}L`;
  if (n >= 1000)   return `₹${(n/1000).toFixed(0)}k`;
  return `₹${Math.round(n)}`;
}

interface IntentBucket {
  intent: string; count: number; conversion_pct: number;
  avg_booking_value: number; avg_stay_nights: number; revenue: number;
}
interface IntentTrend { date: string; intent: string; count: number; }
interface IntentStats {
  total_classified: number; top_intent?: string; top_intent_conversion: number;
  top_revenue_intent?: string; top_revenue_intent_value: number; avg_stay_by_top_intent: number;
  intent_distribution: IntentBucket[];
  intent_trend: IntentTrend[];
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

export default function IntentAnalyticsPage() {
  const router = useRouter(); const pathname = usePathname(); const sp = useSearchParams();
  const rangeDays = parseInt(sp.get("range_days") ?? "30");

  const { data: s, isLoading } = useQuery<IntentStats>({
    queryKey: ["analytics","intent", rangeDays],
    queryFn: () => api.get("/analytics/intent", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5*60_000,
  });

  const setRange = (d: number) => {
    const p = new URLSearchParams(sp.toString()); p.set("range_days", String(d));
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  if (isLoading) return <PageSkeleton />;
  if (!s) return null;

  const dist = s.intent_distribution ?? [];
  const topLabel = s.top_intent ? (INTENT_CONFIG[s.top_intent]?.label ?? s.top_intent) : "—";
  const topRevLabel = s.top_revenue_intent ? (INTENT_CONFIG[s.top_revenue_intent]?.label ?? s.top_revenue_intent) : "—";

  // Pivot intent_trend for multi-line chart
  const trendDates = [...new Set((s.intent_trend ?? []).map(t => t.date))].sort();
  const topIntents = dist.slice(0, 4).map(b => b.intent);
  const trendByDate = trendDates.map(date => {
    const row: Record<string, number|string> = { date };
    topIntents.forEach(intent => {
      row[intent] = (s.intent_trend ?? []).find(t => t.date === date && t.intent === intent)?.count ?? 0;
    });
    return row;
  });

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>
      {/* Header */}
      <div className="flex-shrink-0 px-6 py-4 border-b bg-white" style={{ borderColor: "var(--haip-border)" }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs px-2 py-0.5 rounded-full bg-teal-100 text-teal-700 font-bold">✦ Hospitality Intelligence</span>
            </div>
            <h1 className="text-[20px] font-bold mt-1" style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}>
              Guest Intent Analytics
            </h1>
            <p className="text-[12px] mt-0.5 text-gray-400">Why guests travel · What drives conversion · Booking value by intent</p>
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
          <KpiCard label="Classified Records" value={s.total_classified.toLocaleString("en-IN")}
            icon={<Target size={18}/>}
            subtext={`Calls + inquiries with intent data`} />
          <KpiCard label={`Top Intent: ${topLabel}`} value={`${s.top_intent_conversion}% conv.`}
            icon={<span className="text-xl">{s.top_intent ? INTENT_CONFIG[s.top_intent]?.emoji : "✈️"}</span>}
            subtext={`Best converting travel purpose`} />
          <KpiCard label={`Top Revenue: ${topRevLabel}`} value={fmt_inr(s.top_revenue_intent_value)}
            icon={<DollarSign size={18}/>}
            subtext={`Highest revenue intent segment`} />
          <KpiCard label="Avg Stay (Top Intent)" value={`${s.avg_stay_by_top_intent} nights`}
            icon={<Moon size={18}/>}
            subtext={`For ${topLabel} guests`} />
        </div>

        {/* Distribution + AI Insights */}
        <div className="grid grid-cols-12 gap-5">

          {/* Intent donut */}
          <div className="col-span-12 lg:col-span-5 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Intent Distribution
            </h2>
            {dist.length > 0 ? (
              <div className="flex items-start gap-4">
                <ResponsiveContainer width={150} height={150}>
                  <PieChart>
                    <Pie data={dist} dataKey="count" nameKey="intent" cx="50%" cy="50%"
                      innerRadius={38} outerRadius={68} paddingAngle={2}>
                      {dist.map((b, i) => (
                        <Cell key={i} fill={INTENT_CONFIG[b.intent]?.color ?? "#9ca3af"} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v: number, n: string) => [v, INTENT_CONFIG[n]?.label ?? n]} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex-1 space-y-1.5 mt-1">
                  {dist.slice(0, 6).map(b => (
                    <div key={b.intent} className="flex items-center gap-2">
                      <span style={{ background: INTENT_CONFIG[b.intent]?.color ?? "#9ca3af" }}
                        className="w-2 h-2 rounded-full flex-shrink-0" />
                      <span className="text-[11px] flex-1 text-gray-600 truncate">
                        {INTENT_CONFIG[b.intent]?.emoji ?? "✈️"} {INTENT_CONFIG[b.intent]?.label ?? b.intent}
                      </span>
                      <span className="text-[11px] font-bold text-gray-700">{b.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="h-[150px] flex items-center justify-center text-sm text-gray-400">No intent data yet</div>
            )}
          </div>

          {/* Conversion by intent */}
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Conversion Rate by Intent
            </h2>
            {dist.length > 0 ? (
              <div className="space-y-2">
                {dist.slice(0, 7).map(b => (
                  <div key={b.intent} className="flex items-center gap-2">
                    <span className="text-sm w-5 text-center flex-shrink-0">
                      {INTENT_CONFIG[b.intent]?.emoji ?? "✈️"}
                    </span>
                    <div className="flex-1 h-4 rounded-full overflow-hidden" style={{ background: "#e5e7eb" }}>
                      <div className="h-full rounded-full transition-all"
                        style={{ width: `${b.conversion_pct}%`, background: INTENT_CONFIG[b.intent]?.color ?? "#14b8a6" }} />
                    </div>
                    <span className="text-[11px] font-bold w-10 text-right"
                      style={{ color: INTENT_CONFIG[b.intent]?.color ?? "#14b8a6" }}>
                      {b.conversion_pct}%
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="h-[180px] flex items-center justify-center text-sm text-gray-400">No conversion data yet</div>
            )}
          </div>

          {/* AI Insights */}
          <div className="col-span-12 lg:col-span-3 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <AIInsightsPanel />
          </div>
        </div>

        {/* Revenue by intent + Avg booking value */}
        <div className="grid grid-cols-12 gap-5">

          {/* Revenue bar */}
          <div className="col-span-12 lg:col-span-7 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Revenue by Intent Segment
            </h2>
            {dist.some(b => b.revenue > 0) ? (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart
                  data={dist.filter(b => b.revenue > 0).map(b => ({
                    name: INTENT_CONFIG[b.intent]?.label ?? b.intent,
                    revenue: b.revenue,
                    fill: INTENT_CONFIG[b.intent]?.color ?? "#14b8a6",
                  }))}
                  layout="vertical"
                  margin={{ left: 8 }}
                >
                  <XAxis type="number" tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={v => fmt_inr(v)} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "#6b7280" }} tickLine={false} axisLine={false} width={100} />
                  <Tooltip formatter={(v: number) => [fmt_inr(v), "Revenue"]} />
                  <Bar dataKey="revenue" radius={[0,4,4,0]}>
                    {dist.filter(b => b.revenue > 0).map((b, i) => (
                      <Cell key={i} fill={INTENT_CONFIG[b.intent]?.color ?? "#14b8a6"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[200px] flex items-center justify-center text-sm text-gray-400">No revenue data yet</div>
            )}
          </div>

          {/* Avg booking value + stay nights table */}
          <div className="col-span-12 lg:col-span-5 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Avg Booking Value & Stay Length
            </h2>
            {dist.length > 0 ? (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b" style={{ borderColor: "var(--haip-border)" }}>
                    <th className="text-left py-1.5 font-semibold text-gray-400">Intent</th>
                    <th className="text-right py-1.5 font-semibold text-gray-400">Avg Value</th>
                    <th className="text-right py-1.5 font-semibold text-gray-400">Avg Nights</th>
                  </tr>
                </thead>
                <tbody>
                  {dist.filter(b => b.avg_booking_value > 0 || b.avg_stay_nights > 0).map((b, i) => (
                    <tr key={i} className="border-b last:border-0" style={{ borderColor: "var(--haip-border)" }}>
                      <td className="py-2">
                        <span className="flex items-center gap-1.5">
                          <span>{INTENT_CONFIG[b.intent]?.emoji ?? "✈️"}</span>
                          <span className="text-gray-700 font-medium">{INTENT_CONFIG[b.intent]?.label ?? b.intent}</span>
                        </span>
                      </td>
                      <td className="py-2 text-right font-bold text-teal-700">
                        {b.avg_booking_value > 0 ? fmt_inr(b.avg_booking_value) : "—"}
                      </td>
                      <td className="py-2 text-right font-mono text-gray-600">
                        {b.avg_stay_nights > 0 ? `${b.avg_stay_nights}n` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-sm text-gray-400 py-4 text-center">No data yet</p>
            )}
          </div>
        </div>

        {/* Intent trend (top 4 intents over time) */}
        {trendByDate.length > 0 && (
          <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Intent Trend (weekly) — Top 4 segments
            </h2>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={trendByDate} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                  tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day:"numeric", month:"short" })} />
                <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: "11px" }} />
                {topIntents.map(intent => (
                  <Line key={intent} type="monotone" dataKey={intent}
                    name={INTENT_CONFIG[intent]?.label ?? intent}
                    stroke={INTENT_CONFIG[intent]?.color ?? "#14b8a6"}
                    strokeWidth={2} dot={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

      </div>
    </div>
  );
}
