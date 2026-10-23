"use client";
// The next 7 days of each vehicle on a phone (Ratha 1 / Ratha 2 as R1 / R2 rows), one bar per booking, vehicle tints as on the
// 14-day strip, money still due in terracotta light with a terracotta edge (the same --haip-cal-due-* rule as the 14-day strip and the calendar). Tap a bar to
// open that booking's sheet. Same endpoint as the desktop strip: GET /bookings/occupancy (days=7).
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { shortVehicle } from "@/components/bookings/agenda/OccupancyStrip";
import { addDays, stripBlocks, useHydrated, type Occupancy } from "@/lib/bookingAgenda";

const DAYS = 7;
const NARROW = ["S", "M", "T", "W", "T", "F", "S"];
// Written out in full so Tailwind sees every class: column 1 is the vehicle label, days are columns 2 to 8.
const GRID = "grid grid-cols-[32px_repeat(7,minmax(0,1fr))] gap-x-0.5";
const COL_START = ["col-start-2", "col-start-3", "col-start-4", "col-start-5", "col-start-6", "col-start-7", "col-start-8"];
const COL_SPAN = ["col-span-1", "col-span-2", "col-span-3", "col-span-4", "col-span-5", "col-span-6", "col-span-7"];

export function WeekStrip({ onOpen }: { onOpen: (bookingId: string) => void }) {
  const hydrated = useHydrated();
  const { data, isPending, isError, refetch } = useQuery<Occupancy>({
    queryKey: ["bookings-occupancy", DAYS], queryFn: () => api.get("/bookings/occupancy", { params: { days: DAYS } }).then(r => r.data),
    staleTime: 30_000,
  });
  if (!hydrated || isPending) return <Skeleton className="h-[104px] rounded-2xl" />;
  if (isError || !data) {
    return (
      <p role="alert" className="haip-card px-4 py-3 text-[13px] text-[var(--haip-fg-2)]">
        Couldn&apos;t load the next 7 days. <button type="button" className="min-h-11 font-semibold text-primary underline" onClick={() => refetch()}>Try again</button>
      </p>
    );
  }
  const vehicles = data.vehicles.filter(v => !v.placeholder || v.bookings.length > 0);
  return (
    <section aria-label="Next 7 days" className="haip-card grid gap-1.5 px-2.5 py-2.5">
      <div className={cn(GRID, "items-end")} aria-hidden>
        <span />
        {Array.from({ length: DAYS }, (_, i) => {
          const iso = addDays(data.from, i);
          const d = new Date(`${iso}T00:00:00Z`);
          const today = iso === data.today;
          return (
            <span key={iso} className="text-center text-[10.5px] leading-tight text-[var(--haip-fg-subtle)]">
              {NARROW[d.getUTCDay()]}
              <b className={cn("mx-auto block w-6 rounded-md text-[12.5px]", today ? "bg-[var(--haip-accent)] text-[var(--haip-on-accent)]" : "text-[var(--haip-fg)]")}>{d.getUTCDate()}</b>
            </span>
          );
        })}
      </div>
      {vehicles.length === 0 ? <p className="py-2 text-center text-[13px] text-[var(--haip-fg-subtle)]">No vehicles set up yet.</p> : vehicles.map(v => (
        <div key={v.property_id} className={cn(GRID, "items-center")} role="group" aria-label={v.name}>
          <span className="col-start-1 row-start-1 truncate text-[12px] font-bold text-primary" title={v.name}>{shortVehicle(v.name)}</span>
          {stripBlocks(v, data.from, DAYS).map(b => {
            const cls = cn("row-start-1 flex h-7 min-w-0 items-center overflow-hidden whitespace-nowrap rounded-md px-1.5 text-[11.5px] font-bold",
              COL_START[b.start], COL_SPAN[b.span - 1],
              b.hold ? "bg-[var(--haip-cal-block)] text-[var(--haip-cal-block-fg)]"
                : b.due ? "bg-[var(--haip-cal-due-bg)] text-[var(--haip-cal-due-fg)] shadow-[inset_3px_0_0_var(--haip-cal-due-edge)]"
                  : v.slot === 2 ? "bg-[var(--haip-cal-vehicle-2)] text-[var(--haip-cal-vehicle-fg)]" : "bg-[var(--haip-cal-vehicle-1)] text-[var(--haip-cal-vehicle-fg)]");
            return b.bookingId ? (
              <button key={b.key} type="button" className={cn(cls, "relative before:absolute before:-inset-y-2 before:inset-x-0 before:content-['']")}
                title={b.title} aria-label={b.title} onClick={() => onOpen(b.bookingId!)}>{b.label}</button>
            ) : <span key={b.key} className={cls} title={b.title} aria-label={b.title}>{b.label}</span>;
          })}
        </div>
      ))}
    </section>
  );
}
