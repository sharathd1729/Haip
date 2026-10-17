"use client";
// Owner Command Center: the landing page for owners and managers. Composes ONE server response
// (GET /dashboard/business-overview); nothing on this page computes a business figure.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { AlertTriangle, RefreshCw } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { AiNoticed } from "@/components/dashboard/home/Panels";
import { Acquisition } from "./Acquisition";
import { AttentionStrip } from "./AttentionStrip";
import { Breakdowns } from "./Breakdowns";
import { ChannelPanels } from "./ChannelPanels";
import { KpiGrid } from "./KpiGrid";
import { LeadFlow } from "./LeadFlow";
import { Team } from "./Team";
import { Controls, type Filters } from "./Controls";
import { PeriodBar, usePersistedPeriod, type PeriodValue } from "../PeriodBar";
import { periodLabel } from "./types";
import { JourneyBand } from "./JourneyBand";
import { Ledger } from "./Ledger";
import { Trends } from "./Trends";
import { isRestricted, type BusinessOverview } from "./types";

const INITIAL: Filters = { preset: "this_month", customFrom: "", customTo: "", channel: "", propertyId: "", agentId: "", trend: "day" };

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export function useBusinessOverview(f: Filters, enabled = true) {
  const custom = f.preset === "custom";
  const ready = !custom || (!!f.customFrom && !!f.customTo && f.customFrom <= f.customTo);
  const params = {
    date_preset: f.preset,
    ...(custom ? { date_from: f.customFrom, date_to: f.customTo } : {}),
    ...(f.channel ? { channel: f.channel } : {}),
    ...(f.propertyId ? { property_id: f.propertyId } : {}),
    ...(f.agentId ? { agent_id: f.agentId } : {}),
    ...(f.trend !== "day" ? { trend: f.trend } : {}),
  };
  return useQuery<BusinessOverview>({
    queryKey: ["business-overview", params],
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
    <div className="space-y-5" aria-busy="true" aria-label="Loading the business overview">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">{[0, 1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-24" />)}</div>
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-44 w-full" />
      <Skeleton className="h-72 w-full" />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3"><Skeleton className="h-72 lg:col-span-2" /><Skeleton className="h-72" /></div>
    </div>
  );
}

export function CommandCenter() {
  const { data: session } = useSession();
  const firstName = (session?.user?.name || "").split(" ")[0];
  const [filters, setFilters] = useState<Filters>(INITIAL);
  const [remembered, remember] = usePersistedPeriod("this_month");
  // The remembered period applies once it has been read from this device; "custom" is never remembered.
  useEffect(() => { setFilters(f => (f.preset === "custom" || f.preset === remembered ? f : { ...f, preset: remembered })); }, [remembered]);
  const pickPeriod = (v: string) => { setFilters(f => ({ ...f, preset: v })); if (v !== "custom") remember(v as PeriodValue); };
  const qc = useQueryClient();
  const { toast } = useToast();

  const { data, error, isLoading, isError, isFetching, isPlaceholderData, refetch } = useBusinessOverview(filters);
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

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[1360px] space-y-3 px-3 py-2.5 sm:space-y-5 sm:px-6 sm:py-5">
        <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1 sm:gap-y-2">
          <div>
            <h1 className="font-[family-name:var(--font-display)] text-xl font-semibold tracking-tight text-[var(--haip-fg)] sm:text-[26px]">
              {greeting()}{firstName ? `, ${firstName}` : ""}
            </h1>
            <p className="mt-0.5 hidden text-[13px] text-[var(--haip-fg-subtle)] sm:block">Leads, bookings and revenue across the business.</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-[var(--haip-fg-subtle)]" aria-live="polite">
            {isFetching && <span className="inline-flex items-center gap-1.5"><RefreshCw size={13} className="motion-safe:animate-spin" aria-hidden />Updating…</span>}
            {asOf && !isFetching && <span>As of {asOf} IST</span>}
            <Link href="/dashboard/operations" className="inline-flex min-h-11 items-center font-semibold text-primary hover:underline lg:min-h-0">Team, calls and response times</Link>
          </div>
        </header>

        <PeriodBar custom value={filters.preset} onChange={pickPeriod}
          caption={data ? <><span className="font-semibold text-[var(--haip-fg-2)]">{periodLabel(data.period.date_from, data.period.date_to)}</span><span className="hidden sm:inline"> · India time (IST), full days · compared with the equal period before it</span><span className="sm:hidden"> · IST · vs the period before</span></> : undefined} />

        <Controls value={filters} onChange={setFilters} properties={properties} agents={agents}
          from={data?.period.date_from} to={data?.period.date_to} tenantWide={tenantWide} />

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
        })() : isLoading || !data ? (
          <Loading />
        ) : (
          <div className={isPlaceholderData ? "space-y-4 opacity-60 motion-safe:transition-opacity motion-safe:duration-150 sm:space-y-5" : "space-y-4 motion-safe:transition-opacity motion-safe:duration-150 sm:space-y-5"}>
            <KpiGrid data={data} />
            <LeadFlow data={data} />
            <AttentionStrip data={data} />
            <JourneyBand data={data} />
            <Ledger data={data} />
            <Trends data={data} trend={filters.trend} onTrend={trend => setFilters(f => ({ ...f, trend }))} />
            <Breakdowns data={data} />
            <Acquisition data={data} />
            {data.agents && <Team rows={data.agents} />}
            <ChannelPanels ready={!isPlaceholderData} />
            {data.insights.length > 0 && <AiNoticed insights={data.insights} onDismiss={id => dismiss.mutate(id)} dismissing={dismiss.isPending ? dismiss.variables : null} />}
            <Definitions data={data} />
          </div>
        )}
      </div>
    </div>
  );
}

function Definitions({ data }: { data: BusinessOverview }) {
  const rows = [
    ["Lead", data.leads.definition],
    ["Counts", "Leads are people we hold a phone number for (each counted once, whichever channel they used); enquiries are records, and one person can have several. They are never added together."],
    ["Journey", data.funnel.note],
    ...(!isRestricted(data.bookings) ? [["Bookings", data.bookings.basis]] : []),
    ...(!isRestricted(data.revenue) ? [["Revenue", data.revenue.basis]] : []),
    ["Time", "Every period is whole India (IST) days. Comparisons use the equal-length period immediately before."],
  ];
  return (
    <details className="haip-card px-5 py-3 text-[13px] text-[var(--haip-fg-2)] sm:px-6">
      <summary className="cursor-pointer rounded py-3 font-semibold lg:py-2 text-[var(--haip-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">How these numbers are defined</summary>
      <dl className="mt-3 space-y-2">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-1 gap-x-4 sm:grid-cols-[7rem_1fr]">
            <dt className="font-semibold text-[var(--haip-fg)]">{k}</dt>
            <dd className="text-[var(--haip-fg-subtle)]">{v}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
