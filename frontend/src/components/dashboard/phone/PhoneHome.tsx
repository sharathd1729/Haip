"use client";
// Home on a phone, for owners and managers (one-glance layout, owner 28 Nov 2026; mockup: the "Home, phone" board). The first
// screen holds, in order: who is waiting (the ONE work queue, same query and key as My day and the Now button), the period's
// four numbers as compact domain-coloured tiles with their trend, new leads per day, lead to booking, and the next 7 days
// (check-ins and money to collect, then who arrives next). Leads by check-in month and the team link follow below the fold.
// The period is chosen from a pill beside the tabs (CommandCenter passes it in), so it takes no row here.
// Every figure comes from the server: GET /dashboard/business-overview, GET /work-queue, GET /bookings (needs bookings.read)
// and GET /reports/checkin-months. A figure the role may not see is hidden, never shown as 0.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useSegment } from "@/lib/segments";
import { ChevronRight } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { PERIOD_PRESETS, useDashboardPeriod, type PeriodValue } from "@/components/dashboard/PeriodBar";
import { overviewProblem, useBusinessOverview } from "@/components/dashboard/command/CommandCenter";
import { addDays, todayIST, type AgendaList, type AgendaRow } from "@/lib/bookingAgenda";
import { ArrivalsList, FunnelCard, LeadsChart, OverviewTiles, WaitingStrip, WeekRow } from "@/components/dashboard/overview/OverviewParts";
import { CheckinMonthRows } from "./CheckinMonthRows";

/** Bookings checking in from today to 6 days ahead (cancelled ones dropped), soonest first. */
export function useTripsNext7(enabled: boolean) {
  const today = todayIST();
  return useQuery<AgendaList>({
    queryKey: ["bookings", "phone-home-trips", today],
    queryFn: () => api.get("/bookings", {
      params: { check_in_from: today, check_in_to: addDays(today, 6), sort: "check_in_asc", per_page: 100, page: 1 },
    }).then(r => r.data),
    enabled,
    staleTime: 60_000,
  });
}

export function dueThisWeek(rows: AgendaRow[]): { amount: number; count: number } {
  const owing = rows.filter(r => r.raw_status !== "cancelled" && r.total_outstanding > 0);
  return { amount: owing.reduce((s, r) => s + r.total_outstanding, 0), count: owing.length };
}

export function PhoneHome({ period: fromParent }: {
  /** The period picked beside the tabs. Left out (tests, a standalone render), Home keeps its own, starting on Today. */
  period?: PeriodValue;
}) {
  const b = useSegment().booking;   // trips | stays
  const [own] = useDashboardPeriod();
  const period = fromParent ?? own;
  const overview = useBusinessOverview({ preset: period, customFrom: "", customTo: "", channel: "", propertyId: "", agentId: "", trend: "day" });
  const data = overview.data;
  const canBookings = !!data?.access.bookings;
  const trips = useTripsNext7(canBookings);
  const tripRows = (trips.data?.data ?? []).filter(r => r.raw_status !== "cancelled");
  const periodLabel = PERIOD_PRESETS.find(p => p.value === period)?.label ?? "";
  const due = dueThisWeek(tripRows);

  return (
    <div className="h-full overflow-y-auto overscroll-contain bg-[var(--haip-bg,var(--background))]">
      <div className="grid gap-2 px-3 pb-8 pt-2">
        <WaitingStrip />

        {overview.isError && !data ? (() => {
          const p = overviewProblem(overview.error);
          return (
            <div role="alert" className="haip-card px-4 py-5 text-center">
              <p className="text-[14px] font-semibold text-[var(--haip-fg)]">{p.title}</p>
              <p className="mt-1 text-[13px] text-[var(--haip-fg-subtle)]">{p.body}</p>
              {p.canRetry && <button type="button" onClick={() => overview.refetch()} className="haip-btn-secondary mt-3 min-h-11 cursor-pointer">Try again</button>}
            </div>
          );
        })() : !data || !data.owner ? (
          <div className="grid gap-2" aria-busy="true" aria-label={`Loading the numbers for ${periodLabel.toLowerCase()}`}>
            <div className="grid grid-cols-2 gap-2">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-[66px] rounded-[14px]" />)}</div>
            <Skeleton className="h-[132px] rounded-[var(--radius)]" />
          </div>
        ) : (
          <div className={cn("grid gap-2", overview.isPlaceholderData && "opacity-60")}>
            <OverviewTiles data={data} periodLabel={periodLabel} />
            <LeadsChart data={data} height={44} />
            <FunnelCard data={data} periodLabel={periodLabel} />
          </div>
        )}

        {canBookings && (
          <>
            <WeekRow loading={trips.isPending} checkIns={trips.isError ? null : tripRows.length} checkOuts={null}
              due={trips.isError ? null : due.amount} />
            <ArrivalsList rows={tripRows} total={tripRows.length} loading={trips.isPending} error={trips.isError}
              onRetry={() => trips.refetch()} limit={2} many={b.many} />
          </>
        )}

        <CheckinMonthRows />

        <Link href="/dashboard/operations" className="inline-flex min-h-11 items-center gap-1 text-[13px] font-semibold text-primary">
          Team, calls and response times <ChevronRight size={14} aria-hidden />
        </Link>
      </div>
    </div>
  );
}
