"use client";
// "Leads by check-in" on the phone Home: this month and the next two from Reports > By check-in month
// (GET /reports/checkin-months, checkin_month_report, KPI D-30), plus its "Date not given yet" row. One compact row each:
// guest enquiries checking in that month, how many are valid (a person's review, else the workspace's valid-lead rule, D-28),
// won and still open. Nothing is computed here. Owner / manager with analytics.read; anyone else gets no section (a 403).
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { CompactRow, RowList, RowSection } from "@/components/ui/kit";
import { todayIST } from "@/lib/bookingAgenda";

export const HOME_MONTHS = 3;

interface Row { month: string | null; label: string; enquiries: number; valid: number; won: number; lost: number; open: number }
interface Report { rows: Row[]; no_date: Row }

export function checkinLine(r: Row): string {
  return `${r.valid} valid · ${r.won} won · ${r.open} open`;
}

export function CheckinMonthRows() {
  const start = todayIST().slice(0, 7);
  const q = useQuery<Report>({
    queryKey: ["reports", "checkin-months", start, HOME_MONTHS],
    queryFn: () => api.get("/reports/checkin-months", { params: { months: HOME_MONTHS, start } }).then(r => r.data),
    staleTime: 5 * 60_000,
    retry: (n, e) => (e as { response?: { status?: number } })?.response?.status !== 403 && n < 2,
  });
  if ((q.error as { response?: { status?: number } } | null)?.response?.status === 403) return null;
  return (
    <RowSection title="Leads by check-in"
      action={<Link href="/dashboard/reports" className="inline-flex min-h-11 items-center text-[13px] font-bold text-primary">Reports</Link>}>
      {q.isPending ? (
        <div className="grid gap-1.5" aria-busy="true">{[0, 1, 2].map(i => <Skeleton key={i} className="h-[60px] rounded-xl" />)}</div>
      ) : q.isError || !q.data ? (
        <div role="alert" className="haip-card px-4 py-4 text-[13px] text-[var(--haip-fg-2)]">
          Couldn&apos;t load leads by check-in. <button type="button" onClick={() => q.refetch()} className="min-h-11 font-semibold text-primary underline">Try again</button>
        </div>
      ) : (
        <RowList label="Leads by check-in month">
          {[...q.data.rows, q.data.no_date].map(r => (
            <CompactRow key={r.month ?? "no_date"} title={r.label} subtitle={checkinLine(r)}
              meta={`${r.enquiries} ${r.enquiries === 1 ? "enquiry" : "enquiries"}`} metaTone="neutral"
              metaSub={r.month ? "check-in month" : "no check-in date"} />
          ))}
        </RowList>
      )}
    </RowSection>
  );
}
