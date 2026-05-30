"use client";

import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend, AreaChart, Area,
} from "recharts";
import { Bot, CheckCircle, XCircle, DollarSign, Loader, Zap, AlertCircle } from "lucide-react";
import { KpiCard, deltaBetween } from "@/components/analytics/KpiCard";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

const TEAL = "#14b8a6"; const RED = "#ef4444"; const AMBER = "#f59e0b"; const GRAY = "#e5e7eb";

interface AIStats {
  total_ai_drafts: number; total_ai_drafts_prev: number;
  acceptance_rate_pct: number; acceptance_rate_prev: number;
  rejection_rate_pct: number; edit_rate_pct: number;
  total_cost_mtd_usd: number; total_cost_prev_usd: number;
  avg_cost_per_call_usd: number;
  calls_auto_scored_pct: number;
  pipeline_pending_transcription: number; pipeline_pending_scoring: number;
  pipeline_done_today: number; pipeline_failed_today: number;
  acceptance_trend: { date: string; approved: number; rejected: number; edited: number; total: number }[];
  cost_trend: { date: string; transcription_usd: number; llm_usd: number; total_usd: number }[];
  acceptance_by_agent: { agent_name: string; drafts: number; approved: number; rejected: number; acceptance_pct: number }[];
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

function PipelineCard({ label, value, icon, color }: { label: string; value: number; icon: React.ReactNode; color: string }) {
  return (
    <div className="rounded-xl border p-3 flex items-center gap-3" style={{ borderColor: "var(--haip-border)" }}>
      <span style={{ color }}>{icon}</span>
      <div>
        <p className="text-[22px] font-black leading-none" style={{ fontFamily: "var(--font-display), sans-serif", color }}>{value}</p>
        <p className="text-[11px] text-gray-500 mt-0.5">{label}</p>
      </div>
    </div>
  );
}

export default function AIAnalyticsPage() {
  const router = useRouter(); const pathname = usePathname(); const sp = useSearchParams();
  const rangeDays = parseInt(sp.get("range_days") ?? "30");

  const { data: s, isLoading } = useQuery<AIStats>({
    queryKey: ["analytics","ai", rangeDays],
    queryFn: () => api.get("/analytics/ai", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5*60_000,
  });

  const setRange = (d: number) => {
    const p = new URLSearchParams(sp.toString()); p.set("range_days", String(d));
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  if (isLoading) return <PageSkeleton />;
  if (!s) return null;

  const maxAgent = Math.max(...(s.acceptance_by_agent.map(a => a.drafts)), 1);

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>
      <div className="flex-shrink-0 px-6 py-4 border-b bg-white" style={{ borderColor: "var(--haip-border)" }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-[20px] font-bold" style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}>AI Intelligence Analytics</h1>
            <p className="text-[12px] mt-0.5 text-gray-400">AI acceptance rate, cost trends & pipeline health</p>
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
          <KpiCard label="AI Drafts" value={s.total_ai_drafts.toLocaleString("en-IN")}
            icon={<Bot size={18}/>} delta={deltaBetween(s.total_ai_drafts, s.total_ai_drafts_prev)} />
          <KpiCard label="Acceptance Rate" value={`${s.acceptance_rate_pct}%`}
            icon={<CheckCircle size={18}/>}
            delta={deltaBetween(s.acceptance_rate_pct, s.acceptance_rate_prev)}
            variant={s.acceptance_rate_pct < 50 ? "warning" : "default"} />
          <KpiCard label="Rejection Rate" value={`${s.rejection_rate_pct}%`}
            icon={<XCircle size={18}/>}
            variant={s.rejection_rate_pct > 30 ? "danger" : "default"} />
          <KpiCard label="Cost MTD (USD)" value={`$${s.total_cost_mtd_usd.toFixed(2)}`}
            icon={<DollarSign size={18}/>}
            delta={deltaBetween(s.total_cost_mtd_usd, s.total_cost_prev_usd)} invertDelta
            subtext={`$${s.avg_cost_per_call_usd.toFixed(4)}/call`} />
          <KpiCard label="Auto-Scored Calls" value={`${s.calls_auto_scored_pct}%`}
            icon={<Zap size={18}/>}
            variant={s.calls_auto_scored_pct < 70 ? "warning" : "default"} />
        </div>

        {/* Pipeline health */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <PipelineCard label="Pending transcription" value={s.pipeline_pending_transcription}
            icon={<Loader size={16}/>} color={s.pipeline_pending_transcription > 10 ? AMBER : TEAL} />
          <PipelineCard label="Pending scoring" value={s.pipeline_pending_scoring}
            icon={<Loader size={16}/>} color={s.pipeline_pending_scoring > 10 ? AMBER : TEAL} />
          <PipelineCard label="Completed today" value={s.pipeline_done_today}
            icon={<CheckCircle size={16}/>} color={TEAL} />
          <PipelineCard label="Failed today" value={s.pipeline_failed_today}
            icon={<AlertCircle size={16}/>} color={s.pipeline_failed_today > 0 ? RED : "#9ca3af"} />
        </div>

        {/* Acceptance trend + AI Insights */}
        <div className="grid grid-cols-12 gap-5">
          <div className="col-span-12 lg:col-span-8 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              AI Draft Acceptance — last {rangeDays} days
            </h2>
            {s.acceptance_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={s.acceptance_trend} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day:"numeric", month:"short" })}
                    interval={Math.max(0, Math.floor(s.acceptance_trend.length/6)-1)} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: "11px" }} />
                  <Area type="monotone" dataKey="approved" name="Approved" stroke={TEAL} fill="#14b8a630" stackId="1" />
                  <Area type="monotone" dataKey="edited"   name="Edited"   stroke={AMBER} fill="#f59e0b30" stackId="1" />
                  <Area type="monotone" dataKey="rejected" name="Rejected" stroke={RED}   fill="#ef444430" stackId="1" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-sm text-gray-400">No AI draft data yet</div>
            )}
          </div>
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <AIInsightsPanel />
          </div>
        </div>

        {/* Cost trend + Acceptance by agent */}
        <div className="grid grid-cols-12 gap-5">

          {/* Cost trend */}
          <div className="col-span-12 lg:col-span-6 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              AI Processing Cost (USD/day)
            </h2>
            {s.cost_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={s.cost_trend} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day:"numeric", month:"short" })}
                    interval={Math.max(0, Math.floor(s.cost_trend.length/5)-1)} />
                  <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={v => `$${v.toFixed(2)}`} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: "10px" }} />
                  <Bar dataKey="transcription_usd" name="Transcription" fill={TEAL} stackId="a" radius={[0,0,0,0]} />
                  <Bar dataKey="llm_usd" name="LLM" fill="#6366f1" stackId="a" radius={[4,4,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[180px] flex items-center justify-center text-sm text-gray-400">No cost data yet</div>
            )}
          </div>

          {/* Acceptance by agent */}
          <div className="col-span-12 lg:col-span-6 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Acceptance Rate by Agent
            </h2>
            {s.acceptance_by_agent.length > 0 ? (
              <div className="space-y-2.5">
                {s.acceptance_by_agent.map((a, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="w-24 text-[11px] text-gray-600 truncate flex-shrink-0">{a.agent_name}</span>
                    <div className="flex-1 h-5 rounded-full overflow-hidden" style={{ background: GRAY }}>
                      <div className="h-full rounded-full"
                        style={{ width: `${a.acceptance_pct}%`, background: a.acceptance_pct > 70 ? TEAL : a.acceptance_pct > 50 ? AMBER : RED }} />
                    </div>
                    <span className="w-10 text-right text-[11px] font-bold"
                      style={{ color: a.acceptance_pct > 70 ? TEAL : a.acceptance_pct > 50 ? AMBER : RED }}>
                      {a.acceptance_pct}%
                    </span>
                    <span className="w-14 text-right text-[10px] text-gray-400">{a.drafts} drafts</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400 py-4 text-center">No agent data yet</p>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}
