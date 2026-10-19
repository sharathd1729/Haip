"use client";
// The next 14 days of each caravan (Ratha 1, Ratha 2): one block per booking, pickup day up to the drop day (noon to noon).
// Tap a block to open the booking; tap an empty day to start a new booking for that vehicle and day. A coral underline means money is still due on it. Grey = the vehicle is blocked.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { addDays, freeColumns, newBookingHref, shortDay, stripBlocks, type Occupancy } from "@/lib/bookingAgenda";

const DAYS = 14;
const NARROW = ["S", "M", "T", "W", "T", "F", "S"];
// Written out in full so Tailwind sees every class: column 1 is the vehicle label, days are columns 2 to 15.
const GRID = "grid grid-cols-[44px_repeat(14,minmax(0,1fr))]";
const COL_START = ["col-start-2", "col-start-3", "col-start-4", "col-start-5", "col-start-6", "col-start-7", "col-start-8",
  "col-start-9", "col-start-10", "col-start-11", "col-start-12", "col-start-13", "col-start-14", "col-start-15"];
const COL_SPAN = ["col-span-1", "col-span-2", "col-span-3", "col-span-4", "col-span-5", "col-span-6", "col-span-7",
  "col-span-8", "col-span-9", "col-span-10", "col-span-11", "col-span-12", "col-span-13", "col-span-14"];
const SLOT_BG: Record<number, string> = {
  0: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]",
  1: "bg-[var(--haip-cal-vehicle-1)] text-[var(--haip-cal-vehicle-fg)]",
  2: "bg-[var(--haip-cal-vehicle-2)] text-[var(--haip-cal-vehicle-fg)]",
};

export const shortVehicle = (name: string) => /^ratha\s*(\d+)$/i.test(name.trim()) ? `R${name.trim().match(/(\d+)$/)![1]}` : name.slice(0, 4);

export function OccupancyStrip({ onOpen, selectedId }: { onOpen: (bookingId: string) => void; selectedId?: string }) {
  const { data, isLoading, isError, refetch } = useQuery<Occupancy>({
    queryKey: ["bookings-occupancy", DAYS], queryFn: () => api.get("/bookings/occupancy", { params: { days: DAYS } }).then(r => r.data),
    staleTime: 30_000,
  });

  return (
    <Card className="grid gap-1.5 px-3 py-3 sm:px-4" aria-label="Next 14 days">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <strong className="text-[14px] text-[var(--haip-fg)]">Next 14 days</strong>
        <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">noon to noon</span>
      </div>
      {isLoading ? <Skeleton className="h-24 rounded-xl" /> : isError || !data ? (
        <p role="alert" className="text-[13px] text-[var(--haip-status-danger-fg)]">
          Couldn&apos;t load the vehicles. <button type="button" className="min-h-11 font-semibold underline" onClick={() => refetch()}>Try again</button>
        </p>
      ) : data.vehicles.length === 0 ? (
        <p className="py-3 text-[13px] text-[var(--haip-fg-subtle)]">No vehicles set up yet.</p>
      ) : (
        <>
          <div className={cn(GRID, "items-end")} aria-hidden>
            <span />
            {Array.from({ length: DAYS }, (_, i) => {
              const iso = addDays(data.from, i);
              const d = new Date(`${iso}T00:00:00Z`);
              const today = iso === data.today;
              return (
                <span key={iso} className="text-center text-[10.5px] leading-tight text-[var(--haip-fg-subtle)]">
                  {NARROW[d.getUTCDay()]}
                  <b className={cn("block text-[12.5px]", today ? "text-[var(--haip-accent-ink)]" : "text-[var(--haip-fg)]")}>{d.getUTCDate()}</b>
                </span>
              );
            })}
          </div>
          {data.vehicles.map(v => (
            <div key={v.property_id} className={cn(GRID, "items-center")} role="group" aria-label={v.name}>
              <span className="col-start-1 row-start-1 truncate text-[12px] font-bold text-[var(--haip-fg-2)]" title={v.name}>{shortVehicle(v.name)}</span>
              {!v.placeholder && freeColumns(stripBlocks(v, data.from, DAYS), DAYS).map(i => {
                const iso = addDays(data.from, i);
                return (
                  <Link key={`free:${i}`} href={newBookingHref(v.property_id, iso)} aria-label={`New booking on ${v.name}, ${shortDay(iso)}`}
                    className={cn("row-start-1 mx-px h-9 rounded-lg border border-dashed border-transparent hover:border-[var(--haip-border-strong)] hover:bg-[var(--haip-surface)] focus-visible:border-primary", COL_START[i], "col-span-1")} />
                );
              })}
              {stripBlocks(v, data.from, DAYS).map(blk => {
                const cls = cn("row-start-1", COL_START[blk.start], COL_SPAN[blk.span - 1], "mx-px h-9 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap rounded-lg px-1 text-[12px] font-bold",
                  blk.hold ? "bg-[var(--haip-cal-block)] text-[var(--haip-cal-block-fg)]" : SLOT_BG[v.placeholder ? 0 : v.slot] ?? SLOT_BG[1],
                  blk.due && "shadow-[inset_0_-3px_0_var(--haip-accent)]",
                  blk.bookingId && blk.bookingId === selectedId && "ring-2 ring-primary");
                return blk.bookingId ? (
                  <button key={blk.key} type="button" className={cls} title={blk.title} aria-label={blk.title}
                    data-due={blk.due ? "true" : undefined} onClick={() => onOpen(blk.bookingId!)}>
                    {blk.label}
                  </button>
                ) : (
                  <span key={blk.key} className={cn(cls, "flex items-center")} title={blk.title} aria-label={blk.title}>{blk.label}</span>
                );
              })}
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-[var(--haip-fg-subtle)]">
            <span className="inline-flex items-center gap-1.5"><i className="inline-block h-1 w-3.5 rounded-sm bg-[var(--haip-accent)]" aria-hidden />money still due</span>
            <span>Tap a block to open it, an empty day to book it</span>
          </div>
        </>
      )}
    </Card>
  );
}
