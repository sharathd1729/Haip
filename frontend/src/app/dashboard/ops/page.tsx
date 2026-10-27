"use client";
// Ops Today -- "what needs me right now?" (owner pick 25 Oct 2026: direction A "Needs you", unit cards on top for <= 6 units).
// One read, GET /ops/files/today (ops_today_service), so every rule (what is a problem, how ready a vehicle is) is the server's.
// A calm day shows a green "All on track" and the short day list; nothing else to read.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useHydrated } from "@/lib/bookingAgenda";
import { showUnitCards, type OpsToday } from "@/lib/ops";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, EmptyState, PageHeader } from "@/components/ui/kit";
import { DayList, NeedCard, UnitCards } from "@/components/ops/TodayParts";

export default function OpsTodayPage() {
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data, isPending, isError, refetch } = useQuery<OpsToday>({
    queryKey: ["ops-today"],
    queryFn: () => api.get("/ops/files/today").then(r => r.data),
    staleTime: 15_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
  const resolve = useMutation({
    mutationFn: (id: string) => api.post(`/ops/items/${id}/resolve`, {}),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ops-today"] }); toast({ title: "Marked as sorted", variant: "success" }); },
    onError: () => toast({ title: "Could not save", description: "Check your connection and try again.", variant: "error" }),
  });

  const red = data?.needs.filter(n => n.level === "red").length ?? 0;
  const subtitle = !data ? "Trips, checks and problems" :
    data.needs.length === 0 ? "Nothing needs you right now" :
    `${data.needs.length} thing${data.needs.length === 1 ? "" : "s"} need${data.needs.length === 1 ? "s" : ""} you${red ? `, ${red} now` : ""}`;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5 p-4 sm:p-6">
      <PageHeader title="Ops today" subtitle={subtitle} />

      {!hydrated || isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3"><Skeleton className="h-[88px]" /><Skeleton className="h-[88px]" /></div>
          <Skeleton className="h-36" /><Skeleton className="h-36" />
        </div>
      ) : isError || !data ? (
        <Card>
          <EmptyState title="Couldn't load today" hint="Check your connection, then try again."
            action={<button type="button" className="haip-btn-primary min-h-12" onClick={() => refetch()}>Try again</button>} />
        </Card>
      ) : (
        <>
          {showUnitCards(data.units) && <UnitCards units={data.units} />}

          <section aria-labelledby="needs-h" className="flex flex-col gap-3">
            <h2 id="needs-h" className="sr-only">Needs you</h2>
            {data.needs.length === 0 ? (
              <p className="rounded-2xl border border-[var(--haip-status-success-border)] bg-[var(--haip-status-success-bg)] px-4 py-3.5 text-[15px] font-semibold text-[var(--haip-status-success-fg)]">
                All on track. Nothing needs you.
              </p>
            ) : data.needs.map(n => (
              <NeedCard key={n.key} need={n} onResolve={id => resolve.mutate(id)}
                resolving={resolve.isPending && resolve.variables === n.item_id} />
            ))}
          </section>

          <section aria-labelledby="day-h" className="flex flex-col gap-2">
            <h2 id="day-h" className="text-[13px] font-bold uppercase tracking-[0.08em] text-[var(--haip-fg-subtle)]">Today and tomorrow</h2>
            {data.day.length === 0
              ? <Card><EmptyState title={`No ${data.file_word}s today or tomorrow`} hint={`New bookings show up here once they are confirmed.`} /></Card>
              : <DayList day={data.day} today={data.date} />}
          </section>
        </>
      )}
    </div>
  );
}
