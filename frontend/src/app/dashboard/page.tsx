"use client";
// Home ("Owner Daily"). Top to bottom: greeting + range/agent/channel
// filters, the four "Needs you now" queues, four KPI tiles (two more behind a toggle), revenue chart
// next to the lead funnel, team next to lead sources, then what the AI
// noticed. One page for every role -- /dashboard/overview scopes the data
// (agents see only their own numbers; the team table is owner/manager only).
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { NeedsYouNowCards } from "@/components/dashboard/home/NeedsYouNowCards";
import { KpiTiles } from "@/components/dashboard/home/KpiTiles";
import { RevenueChart, LeadFunnel, TeamTable, LeadSources, AiNoticed } from "@/components/dashboard/home/Panels";
import type { OverviewResponse } from "@/components/dashboard/home/types";

const RANGES = [
  { value: "today", label: "Today" },
  { value: "last_7d", label: "Last 7 days" },
  { value: "this_month", label: "This month" },
] as const;
type RangeValue = (typeof RANGES)[number]["value"];

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

const selectCls = "text-xs font-semibold rounded-lg px-2.5 py-2 outline-none focus-visible:ring-2 focus-visible:ring-teal-600";
const selectStyle = { background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" };

export default function DashboardPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const isOwnerView = role === "owner" || role === "manager";
  const firstName = (session?.user?.name || "").split(" ")[0];
  const qc = useQueryClient();
  const { toast } = useToast();

  const [range, setRange] = useState<RangeValue>("last_7d");
  const [channel, setChannel] = useState("");

  // Remember the last range and channel on this device. Read after mount (not in the initial state)
  // so the first render matches the server.
  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("haip_dashboard_filters") || "{}");
      if (RANGES.some(r => r.value === saved.range)) setRange(saved.range);
      if (CHANNELS.some(c => c.value === saved.channel)) setChannel(saved.channel);
    } catch { /* storage unavailable: keep defaults */ }
  }, []);
  useEffect(() => {
    try { window.localStorage.setItem("haip_dashboard_filters", JSON.stringify({ range, channel })); } catch { /* ignore */ }
  }, [range, channel]);
  const [agentId, setAgentId] = useState("");
  const rangeLabel = RANGES.find(r => r.value === range)?.label ?? "";

  const params: Record<string, string> = { date_preset: range };
  if (channel) params.channel = channel;
  if (isOwnerView && agentId) params.agent_id = agentId;

  const { data, isLoading, isError } = useQuery<OverviewResponse>({
    queryKey: ["dashboard-overview", params],
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
    <div className="h-full overflow-y-auto" style={{ background: "var(--haip-bg, var(--background))" }}>
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 py-5 space-y-5">
        {/* Header */}
        <header className="flex flex-col lg:flex-row lg:items-center gap-3 lg:justify-between">
          <div>
            <h1 className="text-2xl font-bold" style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display)" }}>
              {greeting()}{firstName ? `, ${firstName}` : ""}
            </h1>
            <p className="text-sm mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
              {today} · {scope} · {rangeLabel.toLowerCase()}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label="Channel" value={channel} onChange={e => setChannel(e.target.value)} className={selectCls} style={selectStyle}>
              {CHANNELS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
            {isOwnerView && team.length > 0 && (
              <select aria-label="Agent" value={agentId} onChange={e => setAgentId(e.target.value)} className={selectCls} style={selectStyle}>
                <option value="">All agents</option>
                {team.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            )}
            <div className="flex gap-1 p-1 rounded-xl" style={{ background: "var(--muted)" }} role="tablist" aria-label="Date range">
              {RANGES.map(r => (
                <button key={r.value} type="button" role="tab" aria-selected={range === r.value} onClick={() => setRange(r.value)}
                  className={cn("text-xs font-bold px-3 py-1.5 rounded-lg transition-colors outline-none focus-visible:ring-2 focus-visible:ring-teal-600",
                    range === r.value ? "shadow-sm" : "hover:bg-[color:var(--haip-card)]")}
                  style={range === r.value ? { background: "var(--haip-card)", color: "var(--primary)" } : { color: "var(--haip-fg-muted)" }}>
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </header>

        {isError ? (
          <div className="haip-card p-8 text-center text-sm" style={{ color: "var(--haip-fg-muted)" }}>
            Couldn't load the dashboard. Check your connection and refresh.
          </div>
        ) : isLoading || !data ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-32" />)}</div>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-24" />)}</div>
            <Skeleton className="h-72 w-full" />
          </div>
        ) : (
          <>
            <NeedsYouNowCards data={data.needs_you_now} />
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
