"use client";


import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Send, Users, BookOpen, Truck, Layers } from "@/lib/icons";
import { KpiCard, deltaBetween } from "@/components/analytics/KpiCard";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

const TEAL = "#14b8a6"; const GRAY = "#e5e7eb";
const STATUS_CFG: Record<string, { bg: string; text: string; label: string }> = {
  draft:     { bg: "bg-gray-100",   text: "text-gray-600",   label: "Draft" },
  scheduled: { bg: "bg-blue-100",   text: "text-blue-700",   label: "Scheduled" },
  running:   { bg: "bg-teal-100",   text: "text-teal-700",   label: "Running" },
  completed: { bg: "bg-green-100",  text: "text-green-700",  label: "Completed" },
  paused:    { bg: "bg-amber-100",  text: "text-amber-700",  label: "Paused" },
};

interface CampaignRow { id: string; name: string; status: string; sent: number; delivered: number; read: number; failed: number; delivery_rate: number; read_rate: number; scheduled_at?: string; }
interface CampaignStats {
  total_campaigns: number; active_campaigns: number;
  avg_delivery_rate_pct: number; avg_read_rate_pct: number;
  subscriber_count: number; subscriber_count_prev: number;
  campaigns: CampaignRow[];
  template_performance: { name: string; category: string; status: string; times_used: number; avg_delivery_rate: number; avg_read_rate: number }[];
  subscriber_trend: { date: string; opted_in: number; opted_out: number; cumulative: number }[];
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-44 rounded-xl" />
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">{[1,2,3,4,5].map(i => <Skeleton key={i} className="h-28 rounded-2xl" />)}</div>
      <div className="grid grid-cols-12 gap-5"><Skeleton className="col-span-8 h-64 rounded-2xl" /><Skeleton className="col-span-4 h-64 rounded-2xl" /></div>
      <Skeleton className="h-48 rounded-2xl" />
    </div>
  );
}

function RateBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full" style={{ background: GRAY }}>
        <div className="h-full rounded-full" style={{ width: `${Math.min(pct, 100)}%`, background: color }} />
      </div>
      <span className="text-[11px] font-mono font-bold w-10 text-right" style={{ color }}>{pct}%</span>
    </div>
  );
}

export default function CampaignAnalyticsPage() {
  const router = useRouter(); const pathname = usePathname(); const sp = useSearchParams();
  const rangeDays = parseInt(sp.get("range_days") ?? "30");

  const { data: s, isLoading } = useQuery<CampaignStats>({
    queryKey: ["analytics","campaigns", rangeDays],
    queryFn: () => api.get("/analytics/campaigns", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5*60_000,
  });

  const setRange = (d: number) => {
    const p = new URLSearchParams(sp.toString()); p.set("range_days", String(d));
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  if (isLoading) return <PageSkeleton />;
  if (!s) return null;

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>
      <div className="flex-shrink-0 px-6 py-4 border-b bg-white" style={{ borderColor: "var(--haip-border)" }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="haip-page-title">Campaign Analytics</h1>
            <p className="text-[12px] mt-0.5 text-gray-400">WhatsApp campaigns, template performance & subscriber growth</p>
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
          <KpiCard label="Total Campaigns" value={s.total_campaigns} icon={<Layers size={18}/>} />
          <KpiCard label="Active" value={s.active_campaigns} icon={<Send size={18}/>}
            variant={s.active_campaigns > 0 ? "default" : "warning"} />
          <KpiCard label="Avg Delivery" value={`${s.avg_delivery_rate_pct}%`} icon={<Truck size={18}/>}
            variant={s.avg_delivery_rate_pct < 80 ? "warning" : "default"} />
          <KpiCard label="Avg Read Rate" value={`${s.avg_read_rate_pct}%`} icon={<BookOpen size={18}/>} />
          <KpiCard label="Subscribers" value={s.subscriber_count.toLocaleString("en-IN")} icon={<Users size={18}/>}
            delta={deltaBetween(s.subscriber_count, s.subscriber_count_prev)} />
        </div>

        {/* Subscriber growth + AI Insights */}
        <div className="grid grid-cols-12 gap-5">
          <div className="col-span-12 lg:col-span-8 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Subscriber Growth
            </h2>
            {s.subscriber_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={s.subscriber_trend} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day:"numeric", month:"short" })}
                    interval={Math.max(0, Math.floor(s.subscriber_trend.length/6)-1)} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: "11px" }} />
                  <Area type="monotone" dataKey="cumulative" name="Total subscribers" stroke={TEAL} fill="#14b8a620" />
                  <Area type="monotone" dataKey="opted_in" name="Opted in (daily)" stroke="#6366f1" fill="#6366f110" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-sm text-gray-400">No subscriber data yet</div>
            )}
          </div>
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <AIInsightsPanel />
          </div>
        </div>

        {/* Campaign table */}
        {s.campaigns.length > 0 && (
          <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Campaign Performance
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] min-w-[600px]">
                <thead>
                  <tr className="border-b" style={{ borderColor: "var(--haip-border)" }}>
                    {["Campaign","Status","Sent","Delivery Rate","Read Rate","Scheduled"].map(h => (
                      <th key={h} className="text-left py-2 font-semibold text-gray-500 pr-4">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {s.campaigns.map(c => {
                    const cfg = STATUS_CFG[c.status] ?? STATUS_CFG.draft;
                    return (
                      <tr key={c.id} className="border-b last:border-0 hover:bg-gray-50" style={{ borderColor: "var(--haip-border)" }}>
                        <td className="py-3 font-medium text-gray-800 pr-4 max-w-[160px] truncate">{c.name}</td>
                        <td className="py-3 pr-4">
                          <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-semibold", cfg.bg, cfg.text)}>{cfg.label}</span>
                        </td>
                        <td className="py-3 font-mono text-gray-700 pr-4">{c.sent.toLocaleString("en-IN")}</td>
                        <td className="py-3 pr-4 w-32"><RateBar pct={c.delivery_rate} color={c.delivery_rate > 90 ? "#10b981" : "#f59e0b"} /></td>
                        <td className="py-3 pr-4 w-32"><RateBar pct={c.read_rate} color={TEAL} /></td>
                        <td className="py-3 text-gray-400">
                          {c.scheduled_at ? new Date(c.scheduled_at).toLocaleDateString("en-IN", { day:"numeric", month:"short" }) : "â€”"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Template performance */}
        {s.template_performance.length > 0 && (
          <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Template Library
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {s.template_performance.map((t, i) => (
                <div key={i} className="rounded-xl border p-3" style={{ borderColor: "var(--haip-border)" }}>
                  <div className="flex items-start justify-between mb-2">
                    <span className="text-[12px] font-semibold text-gray-800 truncate">{t.name}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-500 ml-2 flex-shrink-0">{t.category}</span>
                  </div>
                  <div className="space-y-1">
                    <div className="flex justify-between text-[11px]">
                      <span className="text-gray-400">Delivery</span>
                      <span className="font-bold" style={{ color: t.avg_delivery_rate > 90 ? "#10b981" : "#f59e0b" }}>{t.avg_delivery_rate}%</span>
                    </div>
                    <div className="flex justify-between text-[11px]">
                      <span className="text-gray-400">Read</span>
                      <span className="font-bold text-teal-600">{t.avg_read_rate}%</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
