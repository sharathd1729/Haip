"use client";
// This month at a glance: bookings checking in this month (cancelled not counted), what they are worth, what has come in and
// what is still due. Money needs revenue.read; without it the server sends {restricted: true} and we say so (never ₹0).
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";
import { Card } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { isRestricted, lakh, type Money, type MonthSummary as Summary } from "@/lib/bookingAgenda";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const monthName = (ym: string) => { const [y, m] = ym.split("-").map(Number); return `${MONTHS[m - 1]} ${y}`; };

function Figure({ label, value, sub, due, className }: { label: string; value: React.ReactNode; sub?: React.ReactNode; due?: boolean; className?: string }) {
  return (
    <div className={cn("grid min-w-0 content-start", className)}>
      <span className="text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{label}</span>
      <span className={cn("font-[family-name:var(--font-display)] text-[22px] font-semibold leading-tight tabular-nums md:text-[26px]",
        due ? "text-[var(--haip-accent-ink)]" : "text-[var(--haip-fg)]")}>{value}</span>
      {sub && <span className="text-[12px] text-[var(--haip-fg-subtle)] [overflow-wrap:anywhere]">{sub}</span>}
    </div>
  );
}

function money(m: Money) {
  return isRestricted(m) ? { value: "Hidden", sub: "needs revenue access" } : { value: lakh(m), sub: formatINR(m) };
}

export function MonthSummary() {
  const { data, isLoading, isError, refetch } = useQuery<Summary>({
    queryKey: ["bookings-summary"], queryFn: () => api.get("/bookings/summary").then(r => r.data), staleTime: 30_000,
  });
  return (
    <Card className="grid gap-2.5 px-4 py-3.5" aria-label="This month">
      {isLoading ? <Skeleton className="h-[78px] rounded-xl" /> : isError || !data ? (
        <p role="alert" className="text-[13px] text-[var(--haip-status-danger-fg)]">
          Couldn&apos;t load this month&apos;s figures. <button type="button" className="min-h-11 font-semibold underline" onClick={() => refetch()}>Try again</button>
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <strong className="text-[14px] text-[var(--haip-fg)]">{monthName(data.month)}</strong>
            <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">by check-in date · cancelled not counted</span>
          </div>
          <div className="grid grid-cols-3 gap-2 md:grid-cols-4">
            <Figure label="Bookings" value={data.bookings}
              sub={data.by_vehicle.length ? data.by_vehicle.map(v => `${v.count} on ${v.name}`).join(" · ") : "none yet"} />
            <Figure label="Booked value" {...money(data.booked_value)} />
            <Figure label="Collected" className="hidden md:grid" {...money(data.collected)}
              sub={isRestricted(data.collected) ? "needs revenue access" : `${formatINR(data.collected)} · deposits not included`} />
            {(() => {
              const d = money(data.still_due);
              const sub = isRestricted(data.overdue) ? d.sub : data.overdue > 0 ? `${formatINR(data.overdue)} overdue` : "nothing overdue";
              return <Figure label="Still due" value={d.value} sub={sub} due={!isRestricted(data.still_due) && data.still_due > 0} />;
            })()}
          </div>
        </>
      )}
    </Card>
  );
}
