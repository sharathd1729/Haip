"use client";
// Owner dashboard, layout A ("Action first", approved 19 Oct 2026; mock-up docs/design/dashboard-mockup/dashboard.html). The landing
// page for owners and managers. Composes ONE server response (GET /dashboard/business-overview, its `owner` block); nothing on this
// page computes a business figure. Order: what needs a person now, this period's numbers, the month's target next to arrivals,
// demand / sources / stages, caravans next to AI and calls, the team, then Since HAIP. Every block renders on a phone too (no
// block hides behind a tab), and the period starts on Today on every load (PeriodBar.useDashboardPeriod).
import { useMemo, useState } from "react";
import Link from "next/link";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { AlertTriangle, RefreshCw } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useBusinessType } from "@/components/providers/WorkspaceProvider";
import { AiNoticed } from "@/components/dashboard/home/Panels";
import { istDay } from "@/components/dashboard/today/TodayStrip";
import { PeriodBar, PERIOD_PRESETS, useDashboardPeriod, type PeriodValue } from "../PeriodBar";
import { Controls, type Filters } from "./Controls";
import { LeadsRowCards } from "./LeadsRow";
import { NeedsAttention } from "./NeedsAttention";
import { AiCallsCard, CaravansCard, TeamCard } from "./OpsRow";
import { OwnerKpis } from "./OwnerKpis";
import { SinceHaip } from "./SinceHaip";
import { ArrivalsCard, TargetCard } from "./TargetAndArrivals";
import { periodLabel, type BusinessOverview } from "./types";
import type { OwnerBlock } from "./owner";

const INITIAL: Filters = { preset: "today", customFrom: "", customTo: "", channel: "", propertyId: "", agentId: "", trend: "day" };
export type Overview = BusinessOverview & { owner?: OwnerBlock };

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

/** The overview query. The key carries the workspace and the IST day as well as the filters, so a cached answer can never be
 *  shown for another workspace or for yesterday's "Today" (and the query is never written to the persisted cache). */
export function useBusinessOverview(f: Filters, windowDays = 7, enabled = true) {
  const { data: session } = useSession();
  const tenant = (session?.user as { tenantId?: string } | undefined)?.tenantId ?? "";
  const custom = f.preset === "custom";
  const ready = !custom || (!!f.customFrom && !!f.customTo && f.customFrom <= f.customTo);
  const params = {
    date_preset: f.preset,
    ...(custom ? { date_from: f.customFrom, date_to: f.customTo } : {}),
    ...(f.channel ? { channel: f.channel } : {}),
    ...(f.propertyId ? { property_id: f.propertyId } : {}),
    ...(f.agentId ? { agent_id: f.agentId } : {}),
    ...(f.trend !== "day" ? { trend: f.trend } : {}),
    ...(windowDays !== 7 ? { window_days: windowDays } : {}),
  };
  return useQuery<Overview>({
    queryKey: ["business-overview", tenant, istDay(0), params],
    queryFn: () => api.get("/dashboard/business-overview", { params }).then(r => r.data),
    enabled: enabled && ready,
    placeholderData: keepPreviousData,        // changing a filter keeps the old numbers on screen, dimmed, until the new ones land
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
}

/** Why the overview did not load, in the words that fit the cause (a 403 can be the workspace's plan or the person's role). */
export function overviewProblem(error: unknown): { title: string; body: string; canRetry: boolean } {
  const res = (error as { response?: { status?: number; data?: { detail?: unknown } } } | null)?.response;
  const detail = res?.data?.detail;
  if (res?.status === 403 && detail && typeof detail === "object" && (detail as { error?: string }).error === "module_not_enabled") {
    return { title: "Analytics isn’t switched on for this workspace.", body: "Ask your HAIP account manager to enable it. Your team’s work queue and calls are still available below.", canRetry: false };
  }
  if (res?.status === 403) {
    return { title: "Your role doesn’t include the business overview.", body: "You can still see your own work queue, calls and leads. Ask an owner if you need the overview.", canRetry: false };
  }
  if (res?.status === 401) {
    return { title: "You’ve been signed out.", body: "Sign in again to see the overview.", canRetry: false };
  }
  return { title: "The business overview didn’t load.", body: "Check your connection and try again.", canRetry: true };
}

function Loading() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading the owner dashboard">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-44" />)}</div>
      <Skeleton className="h-28 w-full" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2"><Skeleton className="h-56" /><Skeleton className="h-56" /></div>
    </div>
  );
}

export function CommandCenter() {
  const { data: session } = useSession();
  const firstName = (session?.user?.name || "").split(" ")[0];
  const caravan = useBusinessType() === "caravan";
  const [filters, setFilters] = useState<Filters>(INITIAL);
  const [period, setPeriod] = useDashboardPeriod();
  const [windowDays, setWindowDays] = useState(7);
  const preset = filters.preset === "custom" ? "custom" : period;
  const effective = { ...filters, preset };
  const pickPeriod = (v: string) => {
    if (v === "custom") setFilters(f => ({ ...f, preset: "custom" }));
    else { setFilters(f => ({ ...f, preset: v })); setPeriod(v as PeriodValue); }
  };
  const qc = useQueryClient();
  const { toast } = useToast();

  const { data, error, isPending, isError, isFetching, isPlaceholderData, refetch } = useBusinessOverview(effective, windowDays);
  const tenantWide = data?.access.tenant_wide ?? true;

  const { data: properties = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["bookable-properties"], queryFn: () => api.get("/bookings/properties").then(r => r.data), staleTime: 5 * 60_000,
  });
  const { data: agents = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["users-lite"], queryFn: () => api.get("/users/lite").then(r => r.data), staleTime: 5 * 60_000,
  });
  const dismiss = useMutation({
    mutationFn: (id: string) => api.post(`/analytics/insights/${id}/dismiss`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["business-overview"] }),
    onError: () => toast({ variant: "error", title: "Couldn't dismiss that insight", description: "Try again." }),
  });
  const asOf = useMemo(() => (data ? new Date(data.generated_at).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" }) : null), [data]);
  const presetLabel = preset === "custom" ? "Custom" : PERIOD_PRESETS.find(p => p.value === preset)?.label ?? "";
  const range = data ? periodLabel(data.period.date_from, data.period.date_to) : "";
  const periodText = data ? `${presetLabel} · ${range}` : presetLabel;
  const owner = data?.owner;

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[1360px] space-y-3 px-3 py-2.5 sm:space-y-5 sm:px-6 sm:py-5">
        <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1 sm:gap-y-2">
          <div className="min-w-0">
            <h1 className="font-[family-name:var(--font-display)] text-xl font-semibold tracking-tight text-[var(--haip-fg)] sm:text-[26px]">
              {greeting()}{firstName ? `, ${firstName}` : ""}
            </h1>
            <p className="mt-0.5 text-[13px] text-[var(--haip-fg-subtle)]">{periodText}. What needs you first, then the numbers.</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-[var(--haip-fg-subtle)]" aria-live="polite">
            {isFetching && <span className="inline-flex items-center gap-1.5"><RefreshCw size={13} className="motion-safe:animate-spin" aria-hidden />Updating…</span>}
            {asOf && !isFetching && <span>As of {asOf} IST</span>}
            <Link href="/dashboard/operations" className="inline-flex min-h-11 items-center font-semibold text-primary hover:underline lg:min-h-0">Team, calls and response times</Link>
          </div>
        </header>

        <PeriodBar custom value={preset} onChange={pickPeriod}
          caption={data ? <><span className="font-semibold text-[var(--haip-fg-2)]">{range}</span><span> · India time (IST), full days</span></> : undefined} />
        <Controls value={effective} onChange={next => { setFilters(next); if (next.preset !== "custom" && next.preset !== period) setPeriod(next.preset as PeriodValue); }}
          properties={properties} agents={agents} from={data?.period.date_from} to={data?.period.date_to} tenantWide={tenantWide} />

        {isError && data && (
          <p role="alert" className="flex items-start gap-2 rounded-lg border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 py-2 text-[13px] text-[var(--haip-status-warning-fg)]">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" aria-hidden />
            Couldn’t refresh. Showing the numbers from {asOf} IST.{" "}
            <button type="button" onClick={() => refetch()} className="font-semibold underline">Try again</button>
          </p>
        )}

        {isError && !data ? (() => {
          const problem = overviewProblem(error);
          return (
            <div className="haip-card px-6 py-10 text-center" role="alert">
              <p className="text-[15px] font-semibold text-[var(--haip-fg)]">{problem.title}</p>
              <p className="mt-1 text-[13px] text-[var(--haip-fg-subtle)]">{problem.body}</p>
              <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                {problem.canRetry && (
                  <button type="button" onClick={() => refetch()} className="inline-flex min-h-11 items-center rounded-lg bg-primary px-4 text-[13px] font-semibold text-primary-foreground active:scale-[0.98]">Try again</button>
                )}
                <Link href="/dashboard/operations" className="inline-flex min-h-11 items-center rounded-lg border border-[var(--haip-border)] px-4 text-[13px] font-semibold">Open my team and calls view</Link>
              </div>
            </div>
          );
        })() : isPending || !data ? (
          <Loading />
        ) : !owner ? (
          <div className="haip-card px-6 py-8 text-center text-[13px] text-[var(--haip-fg-2)]" role="alert">
            This dashboard needs the latest server update. <button type="button" onClick={() => refetch()} className="font-semibold text-primary underline">Try again</button>
          </div>
        ) : (
          <div className={isPlaceholderData ? "space-y-4 opacity-60 motion-safe:transition-opacity motion-safe:duration-150 sm:space-y-5" : "space-y-4 motion-safe:transition-opacity motion-safe:duration-150 sm:space-y-5"}>
            <NeedsAttention cards={owner.attention} />
            <OwnerKpis kpis={owner.kpis} period={periodText} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <TargetCard target={owner.target} />
              <ArrivalsCard movements={owner.movements} windowDays={windowDays} onWindow={setWindowDays} pending={isPlaceholderData} />
            </div>
            <LeadsRowCards owner={owner} sources={data.sources} period={periodText} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <CaravansCard caravans={owner.caravans} caravan={caravan} />
              <AiCallsCard data={owner.ai_calls} period={presetLabel} />
            </div>
            <TeamCard team={owner.team} />
            {tenantWide && <SinceHaip />}
            {data.insights.length > 0 && <AiNoticed insights={data.insights} onDismiss={id => dismiss.mutate(id)} dismissing={dismiss.isPending ? dismiss.variables : null} />}
            <Definitions data={data} />
          </div>
        )}
      </div>
    </div>
  );
}

function Definitions({ data }: { data: Overview }) {
  const rows = [
    ["Lead", data.leads.definition],
    ["Not counted", "DMs and contacts without a phone number are handled by the AI; this page never counts or flags them."],
    ["Qualified", "A new lead who has given a check-in date (phone + date)."],
    ["Booked value", "Rental (the stay charge) plus add-ons of the bookings made in the period. The monthly target is measured on it."],
    ["Payment received", "Payments with a payment date in the period; refunds are kept apart."],
    ["Not replying", "A lead whose last message is ours (a person’s, or the AI’s once sent) and who has been silent for 24 hours or more."],
    ["Time", "Every period is whole India (IST) days. Comparisons use the equal-length period immediately before."],
  ];
  return (
    <details className="haip-card px-5 py-3 text-[13px] text-[var(--haip-fg-2)] sm:px-6">
      <summary className="cursor-pointer rounded py-3 font-semibold text-[var(--haip-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 lg:py-2">How these numbers are defined</summary>
      <dl className="mt-3 space-y-2">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-1 gap-x-4 sm:grid-cols-[8rem_1fr]">
            <dt className="font-semibold text-[var(--haip-fg)]">{k}</dt>
            <dd className="text-[var(--haip-fg-subtle)]">{v}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
