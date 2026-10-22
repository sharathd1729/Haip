"use client";
// Operations view (was the Home "Owner Daily" page; owners and managers now land on the Owner Command Center, this
// stays at /dashboard/operations and remains the landing page for every other role). Top to bottom: greeting + channel/agent
// filters, the Today strip and the people waiting (shared with the owner view), the period bar, four KPI tiles (two more behind a toggle), revenue chart
// next to the lead funnel, team next to lead sources, then what the AI
// noticed. One page for every role -- /dashboard/overview scopes the data
// (agents see only their own numbers; the team table is owner/manager only).
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { PeriodBar, PERIOD_PRESETS, useDashboardPeriod } from "@/components/dashboard/PeriodBar";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/page";
import { useToast } from "@/components/ui/toast";
import { TodayStrip, istDay } from "@/components/dashboard/today/TodayStrip";
import { WaitingForYou } from "@/components/dashboard/today/WaitingForYou";
import { KpiTiles } from "@/components/dashboard/home/KpiTiles";
import { RevenueChart, LeadFunnel, TeamTable, LeadSources, AiNoticed } from "@/components/dashboard/home/Panels";
import type { OverviewResponse } from "@/components/dashboard/home/types";

const RANGES = PERIOD_PRESETS;

const CHANNELS = [
  { value: "", label: "All channels" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "instagram", label: "Instagram" },
  { value: "voice", label: "Calls" },
  { value: "website", label: "Website" },
];

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

const selectCls = "min-h-10 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] font-semibold text-[var(--haip-fg)] outline-none focus-visible:ring-2 focus-visible:ring-primary sm:text-[13.5px] max-md:min-h-11";

export function OperationsHome() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const isOwnerView = role === "owner" || role === "manager";
  const firstName = (session?.user?.name || "").split(" ")[0];
  const qc = useQueryClient();
  const { toast } = useToast();

  // Today on every load, like the owner view; a pick is kept only for this tab's session (useDashboardPeriod).
  const [range, setRange] = useDashboardPeriod();
  const [channel, setChannel] = useState("");

  // The channel, too, is kept only for this tab's session, never per device (a filter silently left on a phone made its
  // numbers look wrong next to the laptop's).
  useEffect(() => {
    try {
      window.localStorage.removeItem("haip_dashboard_filters");
      const saved = JSON.parse(window.sessionStorage.getItem("haip_dashboard_filters") || "{}");
      if (CHANNELS.some(c => c.value === saved.channel)) setChannel(saved.channel);
    } catch { /* storage unavailable: keep defaults */ }
  }, []);
  useEffect(() => {
    try { window.sessionStorage.setItem("haip_dashboard_filters", JSON.stringify({ channel })); } catch { /* ignore */ }
  }, [channel]);
  const [agentId, setAgentId] = useState("");
  const rangeLabel = RANGES.find(r => r.value === range)?.label ?? "";

  const params: Record<string, string> = { date_preset: range };
  if (channel) params.channel = channel;
  if (isOwnerView && agentId) params.agent_id = agentId;

  const { data, isPending, isError } = useQuery<OverviewResponse>({
    queryKey: ["dashboard-overview", istDay(0), params],
    queryFn: () => api.get("/dashboard/overview", { params }).then(r => r.data),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  // The team list comes from /users/lite, not the overview response --
  // the overview omits `agents` once an agent is picked, which used to make
  // this dropdown vanish the moment it was used.
  const { data: team = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["users-lite"],
    queryFn: () => api.get("/users/lite").then(r => r.data),
    staleTime: 300_000,
    enabled: isOwnerView,
  });

  const dismiss = useMutation({
    mutationFn: (id: string) => api.post(`/analytics/insights/${id}/dismiss`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboard-overview"] }),
    onError: () => toast({ variant: "error", title: "Couldn't dismiss that insight", description: "Try again." }),
  });

  const agentName = team.find(t => t.id === agentId)?.name;
  const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });
  const scope = isOwnerView ? (agentName ? `${agentName}'s numbers` : "Whole team") : "Your numbers";
  const showTeam = isOwnerView && !agentId && !!data?.agents;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1360px] space-y-4 px-3 py-3 sm:space-y-5 sm:px-6 sm:py-5">
        {/* Header */}
        <PageHeader keepOnPhone className="gap-3 lg:justify-between"
          title={<>{greeting()}{firstName ? `, ${firstName}` : ""}</>}
          subtitle={<>{today} · {scope} · {rangeLabel.toLowerCase()}</>}
          actions={
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label="Channel" value={channel} onChange={e => setChannel(e.target.value)} className={selectCls}>
              {CHANNELS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
            {isOwnerView && team.length > 0 && (
              <select aria-label="Agent" value={agentId} onChange={e => setAgentId(e.target.value)} className={selectCls}>
                <option value="">All agents</option>
                {team.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            )}
          </div>
          } />

        <TodayStrip role={role ?? ""} />
        <WaitingForYou role={role ?? ""} />

        <PeriodBar value={range} onChange={v => setRange(v as typeof range)} />

        {isError ? (
          <div className="haip-card p-8 text-center text-sm text-[var(--haip-fg-muted)]">
            Couldn't load the dashboard. Check your connection and refresh.
          </div>
        ) : isPending || !data ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-32" />)}</div>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-24" />)}</div>
            <Skeleton className="h-72 w-full" />
          </div>
        ) : (
          <>
            <KpiTiles data={data} rangeLabel={rangeLabel} />
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
              <RevenueChart series={data.series} rangeLabel={rangeLabel} />
              <LeadFunnel data={data} rangeLabel={rangeLabel} />
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
              {showTeam && <TeamTable agents={data.agents ?? []} rangeLabel={rangeLabel} />}
              <LeadSources sources={data.sources} rangeLabel={rangeLabel} className={showTeam ? undefined : "lg:col-span-5"} />
            </div>
            <AiNoticed insights={data.top_insights} onDismiss={id => dismiss.mutate(id)} dismissing={dismiss.isPending ? dismiss.variables : null} />
          </>
        )}
      </div>
    </div>
  );
}
