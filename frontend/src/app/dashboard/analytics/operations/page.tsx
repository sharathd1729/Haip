"use client";


import { useState } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Users, Phone, ShieldCheck, MessageSquare, Clock, Wifi, WifiOff, ChevronUp, ChevronDown } from "@/lib/icons";
import { KpiCard, deltaBetween } from "@/components/analytics/KpiCard";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

const TEAL = "#14b8a6"; const RED = "#ef4444"; const GRAY = "#e5e7eb";
const ROLE_LABELS: Record<string, string> = {
  owner: "Owner", manager: "Manager", concierge: "Concierge",
  reservations: "Reservations", foh: "FOH", marketing: "Marketing"
};

function fmtTime(s: number) {
  if (s >= 3600) return `${(s/3600).toFixed(1)}h`;
  if (s >= 60)   return `${Math.round(s/60)}m`;
  return `${Math.round(s)}s`;
}
function timeAgo(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60)   return "Just now";
  if (diff < 3600) return `${Math.round(diff/60)}m ago`;
  if (diff < 86400) return `${Math.round(diff/3600)}h ago`;
  return `${Math.round(diff/86400)}d ago`;
}

interface AgentRow {
  id: string; name: string; role: string; calls_handled: number; avg_qa_score: number;
  inquiries_handled: number; sla_compliance_pct: number; avg_response_time_s: number; last_seen_at?: string;
}
interface OpsStats {
  team_size: number; calls_today: number;
  sla_compliance_pct: number; sla_compliance_prev: number;
  open_conversations: number;
  avg_response_time_s: number; avg_response_time_prev: number;
  agents: AgentRow[];
  sla_trend: { date: string; compliant: number; breached: number; compliance_pct: number }[];
  integrations: { kind: string; status: string; last_health_at?: string; is_healthy: boolean }[];
}

type SortKey = "avg_qa_score" | "calls_handled" | "inquiries_handled" | "sla_compliance_pct";

function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? TEAL : score >= 60 ? "#f59e0b" : RED;
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-gray-100 max-w-[50px]">
        <div className="h-full rounded-full" style={{ width: `${score}%`, background: color }} />
      </div>
      <span className="text-[11px] font-bold" style={{ color }}>{score}</span>
    </div>
  );
}

function IntegrationBadge({ kind, healthy, lastAt }: { kind: string; healthy: boolean; lastAt?: string }) {
  return (
    <div className={cn("rounded-xl border p-3 flex items-center gap-3", healthy ? "border-teal-100 bg-teal-50" : "border-red-100 bg-red-50")}>
      <span className={healthy ? "text-teal-500" : "text-red-400"}>
        {healthy ? <Wifi size={16}/> : <WifiOff size={16}/>}
      </span>
      <div className="min-w-0">
        <p className="text-[12px] font-semibold text-gray-800 capitalize">{kind.replace(/_/g, " ")}</p>
        <p className="text-[10px] text-gray-400">{lastAt ? timeAgo(lastAt) : "Never synced"}</p>
      </div>
      <span className={cn("ml-auto text-[10px] font-bold px-2 py-0.5 rounded-full",
        healthy ? "bg-teal-100 text-teal-700" : "bg-red-100 text-red-600")}>
        {healthy ? "Active" : "Error"}
      </span>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-44 rounded-xl" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[1,2,3,4].map(i => <Skeleton key={i} className="h-28 rounded-2xl" />)}</div>
      <div className="grid grid-cols-12 gap-5"><Skeleton className="col-span-8 h-64 rounded-2xl" /><Skeleton className="col-span-4 h-64 rounded-2xl" /></div>
      <Skeleton className="h-64 rounded-2xl" />
    </div>
  );
}

export default function OperationsAnalyticsPage() {
  const router = useRouter(); const pathname = usePathname(); const sp = useSearchParams();
  const rangeDays = parseInt(sp.get("range_days") ?? "30");
  const [sortKey, setSortKey] = useState<SortKey>("avg_qa_score");
  const [sortAsc, setSortAsc] = useState(false);

  const { data: s, isLoading } = useQuery<OpsStats>({
    queryKey: ["analytics","operations", rangeDays],
    queryFn: () => api.get("/analytics/operations", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5*60_000,
  });

  const setRange = (d: number) => {
    const p = new URLSearchParams(sp.toString()); p.set("range_days", String(d));
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  const toggleSort = (k: SortKey) => { if (sortKey === k) setSortAsc(a => !a); else { setSortKey(k); setSortAsc(false); } };

  if (isLoading) return <PageSkeleton />;
  if (!s) return null;

  const sorted = [...(s.agents ?? [])].sort((a, b) => sortAsc ? a[sortKey] - b[sortKey] : b[sortKey] - a[sortKey]);
  const SortIcon = ({ k }: { k: SortKey }) => sortKey === k ? (sortAsc ? <ChevronUp size={10}/> : <ChevronDown size={10}/>) : null;

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>
      <div className="flex-shrink-0 px-6 py-4 border-b bg-white" style={{ borderColor: "var(--haip-border)" }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="haip-page-title">Operations Analytics</h1>
            <p className="text-[12px] mt-0.5 text-gray-400">Agent leaderboard, SLA compliance & integration health</p>
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
          <KpiCard label="Team Size" value={s.team_size} icon={<Users size={18}/>} />
          <KpiCard label="SLA Compliance" value={`${s.sla_compliance_pct}%`}
            icon={<ShieldCheck size={18}/>}
            delta={deltaBetween(s.sla_compliance_pct, s.sla_compliance_prev)}
            variant={s.sla_compliance_pct < 80 ? "danger" : s.sla_compliance_pct < 90 ? "warning" : "default"} />
          <KpiCard label="Open Conversations" value={s.open_conversations}
            icon={<MessageSquare size={18}/>}
            variant={s.open_conversations > 20 ? "warning" : "default"} />
          <KpiCard label="Avg Response Time" value={fmtTime(s.avg_response_time_s)}
            icon={<Clock size={18}/>}
            delta={deltaBetween(s.avg_response_time_s, s.avg_response_time_prev)}
            invertDelta
            variant={s.avg_response_time_s > 7200 ? "warning" : "default"} />
        </div>

        {/* SLA trend + AI Insights */}
        <div className="grid grid-cols-12 gap-5">
          <div className="col-span-12 lg:col-span-8 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              SLA Compliance Trend â€” last {rangeDays} days
            </h2>
            {s.sla_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={s.sla_trend} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day:"numeric", month:"short" })}
                    interval={Math.max(0, Math.floor(s.sla_trend.length/6)-1)} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: "11px" }} />
                  <Bar dataKey="compliant" name="On Time" fill={TEAL} stackId="a" radius={[0,0,0,0]} />
                  <Bar dataKey="breached"  name="Breached" fill={RED}  stackId="a" radius={[4,4,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-sm text-gray-400">No SLA data yet</div>
            )}
          </div>
          <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <AIInsightsPanel />
          </div>
        </div>

        {/* Agent leaderboard */}
        {sorted.length > 0 && (
          <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Agent Leaderboard
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] min-w-[500px]">
                <thead>
                  <tr className="border-b" style={{ borderColor: "var(--haip-border)" }}>
                    <th className="text-left py-2 font-semibold text-gray-500 pr-4">Agent</th>
                    {([
                      { k: "avg_qa_score" as SortKey, l: "QA Score" },
                      { k: "calls_handled" as SortKey, l: "Calls" },
                      { k: "inquiries_handled" as SortKey, l: "Inquiries" },
                      { k: "sla_compliance_pct" as SortKey, l: "SLA %" },
                    ]).map(col => (
                      <th key={col.k} onClick={() => toggleSort(col.k)}
                        className="text-right py-2 font-semibold text-gray-500 pr-4 cursor-pointer hover:text-teal-600 select-none">
                        <span className="flex items-center justify-end gap-1">{col.l}<SortIcon k={col.k}/></span>
                      </th>
                    ))}
                    <th className="text-right py-2 font-semibold text-gray-500">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((a, i) => (
                    <tr key={a.id} className={cn("border-b last:border-0 hover:bg-gray-50 transition-colors")}
                      style={{ borderColor: "var(--haip-border)" }}>
                      <td className="py-3 pr-4">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-full bg-teal-100 text-teal-700 flex items-center justify-center text-[11px] font-bold flex-shrink-0">
                            {a.name.charAt(0)}
                          </div>
                          <div>
                            <p className="font-semibold text-gray-800">{a.name}</p>
                            <p className="text-[10px] text-gray-400 capitalize">{ROLE_LABELS[a.role] ?? a.role}</p>
                          </div>
                          {i === 0 && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-bold ml-1">â­ Top</span>}
                        </div>
                      </td>
                      <td className="py-3 pr-4 text-right"><ScoreBar score={a.avg_qa_score} /></td>
                      <td className="py-3 pr-4 text-right font-mono text-gray-700">{a.calls_handled}</td>
                      <td className="py-3 pr-4 text-right font-mono text-gray-700">{a.inquiries_handled}</td>
                      <td className="py-3 pr-4 text-right">
                        <span className={cn("font-bold text-[11px]", a.sla_compliance_pct >= 90 ? "text-teal-600" : a.sla_compliance_pct >= 75 ? "text-amber-500" : "text-red-500")}>
                          {a.sla_compliance_pct}%
                        </span>
                      </td>
                      <td className="py-3 text-right text-gray-400">{a.last_seen_at ? timeAgo(a.last_seen_at) : "â€”"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Integration health */}
        {s.integrations.length > 0 && (
          <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <h2 className="text-[13px] font-semibold mb-3" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
              Integration Health
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {s.integrations.map((intg, i) => (
                <IntegrationBadge key={i} kind={intg.kind} healthy={intg.is_healthy} lastAt={intg.last_health_at} />
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
