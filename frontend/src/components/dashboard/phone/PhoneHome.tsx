"use client";
// Home on a phone, for owners and managers (mobile-first plan, approved mockup 24 Oct 2026): a greeting and the period, how
// many people are waiting (the ONE work queue, same query and key as My day and the Now button), today's four numbers, then
// the trips of the next 7 days and leads by check-in month. "What the AI noticed", the definitions and the wide desktop blocks
// are left off the phone. Every figure comes from the server: the business overview (GET /dashboard/business-overview) for
// new leads / booked / collected, GET /leads?validity=valid for the valid enquiries, the bookings list (GET /bookings, needs
// bookings.read) for the trips and the money due on them, and GET /reports/checkin-months for leads by check-in.
// A figure the role may not see is hidden, never shown as 0.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { ChevronRight } from "@/lib/icons";
import { cn, formatINR } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { CompactRow, RowList, RowSection, Stat } from "@/components/ui/kit";
import { PeriodBar, PERIOD_PRESETS, useDashboardPeriod } from "@/components/dashboard/PeriodBar";
import { overviewProblem, useBusinessOverview } from "@/components/dashboard/command/CommandCenter";
import { lakh, restricted } from "@/components/dashboard/command/owner";
import { addDays, guestName, shortDay, todayIST, type AgendaList, type AgendaRow } from "@/lib/bookingAgenda";
import { WaitingBanner } from "./WaitingBanner";
import { CheckinMonthRows } from "./CheckinMonthRows";

const TRIPS_SHOWN = 8;

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

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

/** Valid enquiries received in the period: GET /leads?validity=valid (lead_validity.effective, D-28: a person's review, else
 *  the workspace's valid-lead rule of name + phone + location, check-in optional). The one valid-lead definition; nothing is
 *  re-derived here. Guest enquiries only; `total` is the count, no rows are needed. */
export function useValidEnquiries(period: string) {
  return useQuery<{ total: number }>({
    queryKey: ["leads", "phone-home-valid", period],
    queryFn: () => api.get("/leads", { params: { validity: "valid", lead_type: "guest", enquiry_date_preset: period, page: 1, page_size: 1 } })
      .then(r => r.data),
    staleTime: 60_000,
  });
}

export function dueThisWeek(rows: AgendaRow[]): { amount: number; count: number } {
  const owing = rows.filter(r => r.raw_status !== "cancelled" && r.total_outstanding > 0);
  return { amount: owing.reduce((s, r) => s + r.total_outstanding, 0), count: owing.length };
}

function TripRow({ r }: { r: AgendaRow }) {
  const name = guestName(r);
  const guests = r.adults + r.children;
  const owes = r.total_outstanding > 0;
  return (
    <CompactRow href={`/dashboard/bookings/${r.id}`} avatar={<GuestAvatar name={name} />}
      title={[name, r.trip].filter(Boolean).join(" · ")}
      subtitle={[shortDay(r.checkin), r.property?.name, guests ? `${guests} guest${guests === 1 ? "" : "s"}` : null].filter(Boolean).join(" · ")}
      meta={owes ? `${formatINR(r.total_outstanding)} due` : r.total > 0 ? "Paid" : undefined}
      metaTone={owes ? (r.payment_overdue ? "danger" : "warning") : "success"} />
  );
}

export function PhoneHome() {
  const { data: session } = useSession();
  const firstName = (session?.user?.name || "").split(" ")[0];
  const [period, setPeriod] = useDashboardPeriod();
  const overview = useBusinessOverview({ preset: period, customFrom: "", customTo: "", channel: "", propertyId: "", agentId: "", trend: "day" });
  const data = overview.data;
  const canBookings = !!data?.access.bookings;
  const trips = useTripsNext7(canBookings);
  const tripRows = (trips.data?.data ?? []).filter(r => r.raw_status !== "cancelled");
  const today = todayIST();
  const periodLabel = PERIOD_PRESETS.find(p => p.value === period)?.label.toLowerCase() ?? "";
  const kpis = data?.owner?.kpis;
  const due = dueThisWeek(tripRows);
  const valid = useValidEnquiries(period);

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="grid gap-3 px-4 pb-8 pt-3">
        <h1 className="haip-page-title haip-page-title--keep">{greeting()}{firstName ? `, ${firstName}` : ""}</h1>
        <PeriodBar value={period} onChange={v => setPeriod(v as typeof period)} className="-mx-4 px-4" />

        <WaitingBanner />

        {overview.isError && !data ? (() => {
          const p = overviewProblem(overview.error);
          return (
            <div role="alert" className="haip-card px-4 py-5 text-center">
              <p className="text-[14px] font-semibold text-[var(--haip-fg)]">{p.title}</p>
              <p className="mt-1 text-[13px] text-[var(--haip-fg-subtle)]">{p.body}</p>
              {p.canRetry && <button type="button" onClick={() => overview.refetch()} className="haip-btn-secondary mt-3 min-h-11">Try again</button>}
            </div>
          );
        })() : !data || !kpis ? (
          <div className="grid grid-cols-2 gap-2" aria-busy="true" aria-label="Loading today's numbers">
            {[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-[92px] rounded-2xl" />)}
          </div>
        ) : (
          <section aria-label={`Numbers, ${periodLabel}`} className={cn("grid grid-cols-2 gap-2", overview.isPlaceholderData && "opacity-60")}>
            <Stat variant="dark" className="px-3 py-3" label="New leads" value={kpis.new_leads.count}
              hint={valid.data
                ? <span title="Enquiries received in the period that are valid: a person's review, else the workspace's valid-lead rule">{valid.data.total} valid {valid.data.total === 1 ? "enquiry" : "enquiries"} · {periodLabel}</span>
                : <>shared a phone · {periodLabel}</>} />
            {!restricted(kpis.bookings) && (
              <Stat className="px-3 py-3" label="Booked" value={kpis.bookings.count}
                hint={!restricted(kpis.booked_value) ? `${lakh(kpis.booked_value.total)} · ${periodLabel}` : periodLabel} />
            )}
            {!restricted(kpis.payment_received) && (
              <Stat className="px-3 py-3" label="Collected" value={lakh(kpis.payment_received.amount)} hint={periodLabel} />
            )}
            {canBookings && (
              <Stat variant="accent" className="px-3 py-3" label="Due this week" loading={trips.isPending}
                value={trips.isError ? "—" : lakh(due.amount)}
                hint={trips.isError ? "couldn't load" : `${due.count} booking${due.count === 1 ? "" : "s"} · check-in by ${shortDay(addDays(today, 6)).slice(4)}`} />
            )}
          </section>
        )}

        {canBookings && (
          <RowSection title="Trips next 7 days" count={trips.data ? tripRows.length : undefined}
            action={<Link href="/dashboard/portfolio/calendar" className="inline-flex min-h-11 items-center text-[13px] font-bold text-primary">Calendar</Link>}>
            {trips.isPending ? (
              <div className="grid gap-1.5" aria-busy="true">{[0, 1, 2].map(i => <Skeleton key={i} className="h-[60px] rounded-xl" />)}</div>
            ) : trips.isError ? (
              <div role="alert" className="haip-card px-4 py-4 text-[13px] text-[var(--haip-fg-2)]">
                Couldn&apos;t load the trips. <button type="button" onClick={() => trips.refetch()} className="min-h-11 font-semibold text-primary underline">Try again</button>
              </div>
            ) : tripRows.length === 0 ? (
              <p className="haip-card px-4 py-5 text-center text-[13px] text-[var(--haip-fg-subtle)]">No trips start in the next 7 days.</p>
            ) : (
              <>
                <RowList label="Trips next 7 days">{tripRows.slice(0, TRIPS_SHOWN).map(r => <TripRow key={r.id} r={r} />)}</RowList>
                {tripRows.length > TRIPS_SHOWN && (
                  <Link href="/dashboard/bookings" className="inline-flex min-h-11 items-center gap-1 justify-self-start text-[13px] font-bold text-primary">
                    All {tripRows.length} trips <ChevronRight size={14} />
                  </Link>
                )}
              </>
            )}
          </RowSection>
        )}

        <CheckinMonthRows />

        <Link href="/dashboard/operations" className="inline-flex min-h-11 items-center gap-1 text-[13px] font-semibold text-primary">
          Team, calls and response times <ChevronRight size={14} />
        </Link>
      </div>
    </div>
  );
}
