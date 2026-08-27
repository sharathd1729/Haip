"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Users, Clock, CheckCircle2, Phone, CalendarCheck, TrendingUp, IndianRupee, ListChecks, AlertTriangle, PhoneMissed, Bot, Sparkles, Settings2 } from "@/lib/icons";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { DateRangeFilterBar, DateRangeValue } from "@/components/dashboard/DateRangeFilterBar";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";
import { WidgetShell } from "@/components/dashboard/WidgetShell";
import { useDashboardWidgets, useInvalidateDashboardWidgets, type WidgetSnapshot } from "@/hooks/useDashboardWidgets";

// Widget library picker pulls in its own icon set + form chrome -- keep it
// out of the initial dashboard chunk, same reasoning as overview.tsx's
// original (never-wired-in) use of this component.
const WidgetLibraryModal = dynamic(
  () => import("@/components/dashboard/WidgetLibraryModal").then(m => m.WidgetLibraryModal),
  { ssr: false }
);

// Role-aware Analytics Dashboard (V1) -- claude-fable-5-lovely-biscuit.md.
// One page, one component tree, for both owner and agent roles -- the
// backend (/dashboard/overview) does the scoping (tenant-wide + all-agents
// table for owner/manager, self-only for agent roles), so this page just
// renders whatever it gets back and conditionally shows the agents table.

interface KPI {
  total_leads: number; qualified_leads: number; avg_response_seconds: number;
  followups_total: number; followups_completed: number; calls: number;
  bookings: number; conversion_rate: number; revenue: number;
}
interface KPIDelta { pct: number; direction: "up" | "down" | "neutral"; }
interface FunnelRow { stage: string; count: number; pct: number; }
interface Communication {
  total_inbound_messages: number; no_automated_response: number;
  automation_coverage_pct: number; ai_drafts_total: number;
  ai_drafts_approved: number; ai_drafts_rejected: number; ai_draft_acceptance_pct: number;
}
interface CallsSection {
  total: number; answered: number; missed: number;
  missed_recovered: number; callback_rate_pct: number;
}
interface NeedsAttention {
  leads_no_response: number; missed_calls_not_recovered: number; followups_overdue: number;
}
interface AgentRow {
  agent_id: string; agent_name: string; leads_handled: number;
  avg_response_seconds: number; response_count: number;
  followups_total: number; followups_completed: number; followups_overdue: number;
  calls_answered: number; calls_missed: number; calls_missed_recovered: number;
  ai_drafts_total: number; ai_drafts_approved: number; ai_drafts_rejected: number;
  conversions: number;
}
interface OverviewResponse {
  date_from: string; date_to: string; role_scope: string;
  kpi: KPI; kpi_deltas: Record<string, KPIDelta>;
  funnel: FunnelRow[]; communication: Communication; calls: CallsSection;
  needs_attention: NeedsAttention; top_insights: unknown[];
  agents?: AgentRow[];
}

function formatSeconds(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return rem ? `${m}m ${rem}s` : `${m}m`;
}

function DeltaBadge({ delta }: { delta?: KPIDelta }) {
  if (!delta || delta.direction === "neutral") return null;
  const up = delta.direction === "up";
  return (
    <span className="text-[10px] font-semibold" style={{ color: up ? "var(--haip-green, #16a34a)" : "var(--haip-red, #dc2626)" }}>
      {up ? "↑" : "↓"} {Math.abs(delta.pct)}%
    </span>
  );
}

function KpiTile({ icon, label, value, delta }: { icon: React.ReactNode; label: string; value: string; delta?: KPIDelta }) {
  return (
    <div className="p-3 rounded-xl border flex-1 min-w-[130px]" style={{ borderColor: "var(--haip-border)", background: "var(--haip-card)" }}>
      <div className="flex items-center gap-1.5 mb-1" style={{ color: "var(--haip-fg-subtle)" }}>
        {icon}
        <span className="text-[10px] font-medium uppercase tracking-wide">{label}</span>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-lg font-bold" style={{ color: "var(--haip-fg)" }}>{value}</span>
        <DeltaBadge delta={delta} />
      </div>
    </div>
  );
}

function StageFunnel({ stages }: { stages: FunnelRow[] }) {
  const display = stages.map(s => ({
    stage: s.stage.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
    count: s.count,
  }));
  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={display} layout="vertical" margin={{ top: 0, right: 32, left: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--haip-border)" horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 10, fill: "var(--haip-fg-subtle)" }} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="stage" tick={{ fontSize: 11, fill: "var(--haip-fg-muted)" }} tickLine={false} axisLine={false} width={80} />
        <Tooltip
          contentStyle={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", borderRadius: 8, fontSize: 12 }}
          cursor={{ fill: "color-mix(in srgb, var(--primary) 6%, transparent)" }}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]} fill="var(--primary)" opacity={0.85} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// Grafted from the never-wired-in overview.tsx (see CLAUDE.md-adjacent
// investigation notes) -- this is the one widget system in the codebase
// that already implements "don't show empty/fake metrics" for real, via
// WidgetShell's unavailable/early_signal/full_insight states.
function AdaptiveInsights() {
  const [rangeDays] = useState(30);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [localWidgets, setLocalWidgets] = useState<WidgetSnapshot[] | null>(null);
  const invalidate = useInvalidateDashboardWidgets();

  const { data, isLoading } = useDashboardWidgets(rangeDays);
  const widgets = localWidgets ?? data?.widgets ?? [];

  function handleRefresh(key: string, fresh: WidgetSnapshot) {
    setLocalWidgets((prev) => {
      const base = prev ?? data?.widgets ?? [];
      return base.map((w) => (w.key === key ? fresh : w));
    });
  }

  function handleSaved() {
    invalidate();
    setLocalWidgets(null);
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="haip-label flex items-center gap-1.5">
          <Sparkles size={12} style={{ color: "var(--primary)" }} />
          AI insights
        </p>
        <button
          onClick={() => setPickerOpen(true)}
          className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg border"
          style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
          title="Customize widgets"
        >
          <Settings2 size={11} />
          Customize
        </button>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="rounded-xl border h-44 animate-pulse" style={{ background: "var(--muted)", borderColor: "var(--haip-border)" }} />
          ))}
        </div>
      ) : widgets.length === 0 ? (
        <div className="haip-card p-8 text-center">
          <Sparkles size={20} style={{ color: "var(--haip-fg-subtle)" }} className="mx-auto mb-2" />
          <p className="text-sm font-medium" style={{ color: "var(--haip-fg)" }}>
            No insight widgets selected
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--haip-fg-muted)" }}>
            Pick the signals you want tracked and HAIP will keep them current.
          </p>
          <button
            onClick={() => setPickerOpen(true)}
            className="mt-3 inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold"
            style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
          >
            <Settings2 size={12} />
            Choose widgets
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {widgets.map((snap) => (
            <WidgetShell key={snap.key} snap={snap} onRefresh={handleRefresh} />
          ))}
        </div>
      )}

      {pickerOpen && (
        <WidgetLibraryModal
          selected={widgets.map((w) => w.key)}
          onClose={() => setPickerOpen(false)}
          onSaved={handleSaved}
        />
      )}
    </div>
  );
}

export default function DashboardPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const isOwnerView = role === "owner" || role === "manager";

  const [range, setRange] = useState<DateRangeValue>({ preset: "today" });
  const [channel, setChannel] = useState("");
  const [agentId, setAgentId] = useState("");

  const params: Record<string, string> = { date_preset: range.preset };
  if (range.preset === "custom") {
    if (range.date_from) params.date_from = range.date_from;
    if (range.date_to) params.date_to = range.date_to;
  }
  if (channel) params.channel = channel;
  if (isOwnerView && agentId) params.agent_id = agentId;

  const { data, isLoading } = useQuery<OverviewResponse>({
    queryKey: ["dashboard-overview", params],
    queryFn: () => api.get("/dashboard/overview", { params }).then(r => r.data),
    staleTime: 30_000,
  });

  return (
    <div className="h-full flex flex-col overflow-y-auto">
      <div className="px-6 py-5 flex-shrink-0 space-y-3" style={{ background: "var(--haip-card)", borderBottom: "1px solid var(--haip-border)" }}>
        <div>
          <h1 className="haip-page-title">Dashboard</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
            {isOwnerView ? "Your team's numbers, today." : "Your numbers, today."}
          </p>
        </div>
        <DateRangeFilterBar value={range} onChange={setRange}>
          <select
            value={channel}
            onChange={e => setChannel(e.target.value)}
            className="text-[11px] rounded-lg px-2 py-1.5"
            style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
          >
            <option value="">All channels</option>
            <option value="whatsapp">WhatsApp</option>
            <option value="instagram">Instagram</option>
            <option value="voice">Call</option>
            <option value="website">Website</option>
          </select>
          {isOwnerView && data?.agents && data.agents.length > 0 && (
            <select
              value={agentId}
              onChange={e => setAgentId(e.target.value)}
              className="text-[11px] rounded-lg px-2 py-1.5"
              style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
            >
              <option value="">All agents</option>
              {data.agents.map(a => (
                <option key={a.agent_id} value={a.agent_id}>{a.agent_name}</option>
              ))}
            </select>
          )}
        </DateRangeFilterBar>
      </div>

      <div className="flex-1 p-6 space-y-5">
        {isLoading || !data ? (
          <div className="space-y-4">
            <div className="flex gap-3 flex-wrap">
              {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-16 w-36" />)}
            </div>
            <Skeleton className="h-64 w-full" />
          </div>
        ) : (
          <>
            {/* KPI row */}
            <div className="flex gap-3 flex-wrap">
              <KpiTile icon={<Users size={12} />} label="Leads" value={String(data.kpi.total_leads)} delta={data.kpi_deltas.total_leads} />
              <KpiTile icon={<CheckCircle2 size={12} />} label="Qualified" value={String(data.kpi.qualified_leads)} delta={data.kpi_deltas.qualified_leads} />
              <KpiTile icon={<Clock size={12} />} label="Avg response" value={formatSeconds(data.kpi.avg_response_seconds)} delta={data.kpi_deltas.avg_response_seconds} />
              <KpiTile icon={<ListChecks size={12} />} label="Follow-ups" value={`${data.kpi.followups_completed}/${data.kpi.followups_total}`} />
              <KpiTile icon={<Phone size={12} />} label="Calls" value={String(data.kpi.calls)} delta={data.kpi_deltas.calls} />
              <KpiTile icon={<CalendarCheck size={12} />} label="Bookings" value={String(data.kpi.bookings)} delta={data.kpi_deltas.bookings} />
              <KpiTile icon={<TrendingUp size={12} />} label="Conversion" value={`${data.kpi.conversion_rate}%`} delta={data.kpi_deltas.conversion_rate} />
              <KpiTile icon={<IndianRupee size={12} />} label="Revenue" value={`₹${data.kpi.revenue.toLocaleString("en-IN")}`} delta={data.kpi_deltas.revenue} />
            </div>

            <div className={cn("grid gap-4", isOwnerView && data.agents ? "grid-cols-1 lg:grid-cols-2" : "grid-cols-1")}>
              {/* Lead funnel */}
              <div className="p-4 rounded-xl border" style={{ borderColor: "var(--haip-border)", background: "var(--haip-card)" }}>
                <p className="text-[11px] font-bold uppercase tracking-wide mb-3" style={{ color: "var(--haip-fg-subtle)" }}>Lead Funnel</p>
                {data.funnel.length === 0 ? (
                  <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>No leads in this period.</p>
                ) : (
                  <StageFunnel stages={data.funnel} />
                )}
              </div>

              {/* Team activity (owner/manager only) */}
              {isOwnerView && data.agents && (
                <div className="p-4 rounded-xl border overflow-x-auto" style={{ borderColor: "var(--haip-border)", background: "var(--haip-card)" }}>
                  <p className="text-[11px] font-bold uppercase tracking-wide mb-3" style={{ color: "var(--haip-fg-subtle)" }}>Team Activity</p>
                  {data.agents.length === 0 ? (
                    <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>No active agents.</p>
                  ) : (
                    <table className="w-full text-xs">
                      <thead>
                        <tr style={{ color: "var(--haip-fg-subtle)" }}>
                          <th className="text-left font-medium pb-2">Agent</th>
                          <th className="text-right font-medium pb-2">Leads</th>
                          <th className="text-right font-medium pb-2">Response</th>
                          <th className="text-right font-medium pb-2">Follow-ups</th>
                          <th className="text-right font-medium pb-2">Calls</th>
                          <th className="text-right font-medium pb-2">AI accept</th>
                          <th className="text-right font-medium pb-2">Sold</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.agents.map(a => (
                          <tr key={a.agent_id} className="border-t" style={{ borderColor: "var(--haip-border)" }}>
                            <td className="py-1.5 truncate" style={{ color: "var(--haip-fg)" }}>{a.agent_name}</td>
                            <td className="text-right">{a.leads_handled}</td>
                            <td className="text-right">{a.response_count ? formatSeconds(a.avg_response_seconds) : "—"}</td>
                            <td className="text-right">{a.followups_completed}/{a.followups_total}</td>
                            <td className="text-right">{a.calls_answered}{a.calls_missed > 0 ? ` (${a.calls_missed} missed)` : ""}</td>
                            <td className="text-right">{a.ai_drafts_total ? `${Math.round((a.ai_drafts_approved / a.ai_drafts_total) * 100)}%` : "—"}</td>
                            <td className="text-right font-semibold" style={{ color: "var(--primary)" }}>{a.conversions}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>

            {/* Needs attention */}
            {(data.needs_attention.leads_no_response > 0 || data.needs_attention.missed_calls_not_recovered > 0 || data.needs_attention.followups_overdue > 0) && (
              <div className="p-4 rounded-xl border space-y-1.5" style={{ borderColor: "color-mix(in srgb, var(--haip-amber, #d97706) 30%, transparent)", background: "color-mix(in srgb, var(--haip-amber, #d97706) 6%, transparent)" }}>
                <p className="text-[11px] font-bold uppercase tracking-wide flex items-center gap-1.5" style={{ color: "var(--haip-amber, #d97706)" }}>
                  <AlertTriangle size={12} /> Needs Attention
                </p>
                {data.needs_attention.leads_no_response > 0 && (
                  <p className="text-xs" style={{ color: "var(--haip-fg)" }}>{data.needs_attention.leads_no_response} leads haven't received a response.</p>
                )}
                {data.needs_attention.missed_calls_not_recovered > 0 && (
                  <p className="text-xs flex items-center gap-1" style={{ color: "var(--haip-fg)" }}>
                    <PhoneMissed size={11} /> {data.needs_attention.missed_calls_not_recovered} missed calls haven't been called back.
                  </p>
                )}
                {data.needs_attention.followups_overdue > 0 && (
                  <p className="text-xs" style={{ color: "var(--haip-fg)" }}>{data.needs_attention.followups_overdue} follow-ups are overdue.</p>
                )}
              </div>
            )}

            {/* Communication + Calls */}
            <div className="grid gap-4 grid-cols-1 lg:grid-cols-2">
              <div className="p-4 rounded-xl border space-y-1.5" style={{ borderColor: "var(--haip-border)", background: "var(--haip-card)" }}>
                <p className="text-[11px] font-bold uppercase tracking-wide mb-2 flex items-center gap-1.5" style={{ color: "var(--haip-fg-subtle)" }}>
                  <Bot size={12} /> Automation & AI
                </p>
                <p className="text-xs" style={{ color: "var(--haip-fg)" }}>Automation coverage: <strong>{data.communication.automation_coverage_pct}%</strong> ({data.communication.no_automated_response} of {data.communication.total_inbound_messages} messages had no automated reply)</p>
                <p className="text-xs" style={{ color: "var(--haip-fg)" }}>AI draft acceptance: <strong>{data.communication.ai_draft_acceptance_pct}%</strong> ({data.communication.ai_drafts_approved} approved / {data.communication.ai_drafts_rejected} rejected of {data.communication.ai_drafts_total})</p>
              </div>
              <div className="p-4 rounded-xl border space-y-1.5" style={{ borderColor: "var(--haip-border)", background: "var(--haip-card)" }}>
                <p className="text-[11px] font-bold uppercase tracking-wide mb-2 flex items-center gap-1.5" style={{ color: "var(--haip-fg-subtle)" }}>
                  <Phone size={12} /> Calls
                </p>
                <p className="text-xs" style={{ color: "var(--haip-fg)" }}>{data.calls.answered} answered, {data.calls.missed} missed ({data.calls.missed_recovered} called back — {data.calls.callback_rate_pct}% callback rate)</p>
              </div>
            </div>

            {/* AI Intelligence */}
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide mb-2 flex items-center gap-1.5" style={{ color: "var(--haip-fg-subtle)" }}>
                <Sparkles size={12} /> AI Intelligence
              </p>
              <AIInsightsPanel />
            </div>

            {/* Widget grid -- each card only ever shows real data (WidgetShell's
                unavailable/early_signal/full_insight states), never a fabricated
                number for a signal HAIP doesn't have enough of yet. */}
            <AdaptiveInsights />
          </>
        )}
      </div>
    </div>
  );
}
