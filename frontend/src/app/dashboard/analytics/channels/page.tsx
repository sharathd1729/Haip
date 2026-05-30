"use client";

import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, LineChart, Line, Legend, AreaChart, Area,
} from "recharts";
import { MessageSquare, Clock, Truck, BookOpen, Bot } from "lucide-react";
import { KpiCard, deltaBetween } from "@/components/analytics/KpiCard";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

const TEAL = "#14b8a6"; const AMBER = "#fbbf24"; const GRAY = "#e5e7eb";
const CHAN_COLORS: Record<string, string> = {
  WHATSAPP: "#25d366", INSTAGRAM: "#e1306c", VOICE: "#3b82f6",
  WEBCHAT: "#8b5cf6", EMAIL: "#f59e0b",
};

function fmtTime(s: number) {
  if (s >= 3600) return `${(s/3600).toFixed(1)}h`;
  if (s >= 60)   return `${Math.round(s/60)}m`;
  return `${Math.round(s)}s`;
}

interface ChannelStats {
  total_messages: number; total_messages_prev: number;
  delivery_rate_pct: number; delivery_rate_prev: number;
  read_rate_pct: number; read_rate_prev: number;
  avg_response_time_s: number; avg_response_time_prev: number;
  ai_acceptance_pct: number; ai_acceptance_prev: number;
  channel_breakdown: { channel: string; messages: number; delivered_pct: number; read_pct: number; ai_gen_pct: number }[];
  response_time_by_channel: { channel: string; median_s: number; p95_s: number }[];
  attribution_funnel: { source: string; inquiries: number; converted: number; conversion_pct: number }[];
  volume_trend: { date: string; whatsapp: number; instagram: number; voice: number; webchat: number }[];
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-44 rounded-xl" />
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">{[1,2,3,4,5].map(i => <Skeleton key={i} className="h-28 rounded-2xl" />)}</div>
      <div className="grid grid-cols-12 gap-5"><Skeleton className="col-span-8 h-64 rounded-2xl" /><Skeleton className="col-span-4 h-64 rounded-2xl" /></div>
    </div>
  );
}

export default function ChannelAnalyticsPage() {
  const router = useRouter(); const pathname = usePathname(); const sp = useSearchParams();
  const rangeDays = parseInt(sp.get("range_days") ?? "30");

  const { data: s, isLoading } = useQuery<ChannelStats>({
    queryKey: ["analytics","channels", rangeDays],
    queryFn: () => api.get("/analytics/channels", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5*60_000,
  });

  const setRange = (d: number) => {
    const p = new URLSearchParams(sp.toString()); p.set("range_days", String(d));
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  if (isLoading) return <PageSkeleton />;
  if (!s) return null;

  const maxFunnel = Math.max(...(s.attribution_funnel.map(r => r.inquiries)), 1);

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>
      <div className="flex-shrink-0 px-6 py-4 border-b bg-white" style={{ borderColor: "var(--haip-border)" }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-[20px] font-bold" style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}>Channel Analytics</h1>
            <p className="text-[12px] mt-0.5 text-gray-400">Delivery rates, response times & attribution funnel</p>
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
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <KpiCard label="Total Messages" value={s.total_messages.toLocaleString("en-IN")}
            icon={<MessageSquare size={18}/>} delta={deltaBetween(s.total_messages, s.total_messages_prev)} />
          <KpiCard label="Delivery Rate" value={`${s.delivery_rate_pct}%`}
            icon={<Truck size={18}/>} delta={deltaBetween(s.delivery_rate_pct, s.delivery_rate_prev)}
            variant={s.delivery_rate_pct < 80 ? "warning" : "default"} />
          <KpiCard label="Read Rate" value={`${s.read_rate_pct}%`}
            icon={<BookOpen size={18}/>} delta={deltaBetween(s.read_rate_pct, s.read_rate_prev)} />
          <KpiCard label="Avg Response Time" value={fmtTime(s.avg_response_time_s)}
            icon={<Clock size={18}/>} invertDelta
            delta={deltaBetween(s.avg_response_time_s, s.avg_response_time_prev)}
            variant={s.avg_response_time_s > 7200 ? "warning" : "default"} />
          <KpiCard label="AI Acceptance" value={`${s.ai_acceptance_pct}%`}
            icon={<Bot size={18}/>} delta={deltaBetween(s.ai_acceptance_pct, s.ai_acceptance_prev)} />
        </div>

        {/* Volume trend + AI Insights */}
        <div className="grid grid-cols-12 gap-5">
          <div className="col-span-12 lg:col-span-8 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Message Volume by Channel — last {rangeDays} days
            </h2>
            {s.volume_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={s.volume_trend} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day:"numeric", month:"short" })}
                    interval={Math.max(0, Math.floor(s.volume_trend.length/6)-1)} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: "11px" }} />
                  <Area type="monotone" dataKey="whatsapp" name="WhatsApp" stroke="#25d366" fill="#25d36620" stackId="1" />
                  <Area type="monotone" dataKey="instagram" name="Instagram" stroke="#e1306c" fill="#e1306c20" stackId="1" />
                  <Area type="monotone" dataKey="voice" name="Voice" stroke="#3b82f6" fill="#3b82f620" stackId="1" />
                  <Area type="monotone" dataKey="webchat" name="Web Chat" stroke="#8b5cf6" fill="#8b5cf620" stackId="1" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-sm text-gray-400">No message data yet</div>
            )}
          </div>
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <AIInsightsPanel />
          </div>
        </div>

        {/* Attribution funnel + Channel breakdown table */}
        <div className="grid grid-cols-12 gap-5">

          {/* Attribution funnel */}
          <div className="col-span-12 lg:col-span-6 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Source → Booking Attribution
            </h2>
            {s.attribution_funnel.length > 0 ? (
              <div className="space-y-2">
                {s.attribution_funnel.slice(0, 8).map((row, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="w-28 text-[11px] text-gray-500 flex-shrink-0 truncate capitalize">
                      {row.source.replace(/_/g, " ").toLowerCase()}
                    </span>
                    <div className="flex-1 h-5 rounded-full overflow-hidden" style={{ background: GRAY }}>
                      <div className="h-full rounded-full" style={{ width: `${(row.inquiries/maxFunnel)*100}%`, background: TEAL }} />
                    </div>
                    <span className="w-8 text-right text-[11px] font-mono font-bold text-gray-700">{row.inquiries}</span>
                    <span className="w-12 text-right text-[11px] font-mono text-teal-600 font-bold">{row.conversion_pct}%</span>
                  </div>
                ))}
                <p className="text-[10px] text-gray-400 mt-2">Bar = inquiries • % = conversion to booking</p>
              </div>
            ) : (
              <div className="h-[200px] flex items-center justify-center text-sm text-gray-400">No funnel data yet</div>
            )}
          </div>

          {/* Channel breakdown table */}
          <div className="col-span-12 lg:col-span-6 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Per-Channel Delivery Stats
            </h2>
            {s.channel_breakdown.length > 0 ? (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b" style={{ borderColor: "var(--haip-border)" }}>
                    {["Channel","Messages","Delivered","Read","AI%"].map(h => (
                      <th key={h} className="text-left py-1.5 font-semibold text-gray-500 first:pl-0 last:text-right">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {s.channel_breakdown.map((r, i) => (
                    <tr key={i} className="border-b last:border-0" style={{ borderColor: "var(--haip-border)" }}>
                      <td className="py-2">
                        <span className="flex items-center gap-1.5">
                          <span className="w-2 h-2 rounded-full" style={{ background: CHAN_COLORS[r.channel] ?? "#9ca3af" }} />
                          <span className="capitalize font-medium text-gray-700">{r.channel.toLowerCase()}</span>
                        </span>
                      </td>
                      <td className="py-2 font-mono text-gray-700">{r.messages.toLocaleString("en-IN")}</td>
                      <td className="py-2 font-bold" style={{ color: r.delivered_pct > 90 ? "#10b981" : "#f59e0b" }}>{r.delivered_pct}%</td>
                      <td className="py-2 font-bold text-teal-600">{r.read_pct}%</td>
                      <td className="py-2 text-right font-mono text-gray-500">{r.ai_gen_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-sm text-gray-400 py-4 text-center">No channel data yet</p>
            )}
          </div>
        </div>

        {/* Response time bar */}
        {s.response_time_by_channel.length > 0 && (
          <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              First Response Time by Channel (median & p95)
            </h2>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={s.response_time_by_channel} layout="vertical" margin={{ left: 16 }}>
                <XAxis type="number" tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                  tickFormatter={v => fmtTime(v)} />
                <YAxis type="category" dataKey="channel" tick={{ fontSize: 11, fill: "#6b7280" }} tickLine={false} axisLine={false} width={80}
                  tickFormatter={v => v.charAt(0) + v.slice(1).toLowerCase()} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: "11px" }} />
                <Bar dataKey="median_s" name="Median" fill={TEAL} radius={[0,4,4,0]} />
                <Bar dataKey="p95_s" name="p95" fill={AMBER} radius={[0,4,4,0]} opacity={0.7} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

      </div>
    </div>
  );
}
