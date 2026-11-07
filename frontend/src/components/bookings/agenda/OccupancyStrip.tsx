"use client";
// The next 14 days of each unit (caravans: Ratha 1 / Ratha 2 as R1 / R2; villas: their full names). One block per booking, check-in
// day up to the check-out day; back-to-back calendar holds are one bar; a Google Calendar event that names no unit is shown once,
// in the "Which villa?" row, not on every unit. Tap a booking to open it, a hold to open the Calendar's sheet (and pick its unit),
// an empty day to start a booking for that unit. Terracotta light with a terracotta left edge = money still due.
// With many units (segment.sections.bookings.stripCollapsedAbove) the strip starts folded to one line; each person's choice is
// remembered in this browser (localStorage, read after the first render so the server and client render the same).
import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Calendar } from "@/lib/icons";
import { Card } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { WAITING_STRIPE } from "@/components/calendar/CalendarParts";
import { useHydrated, addDays, freeColumns, newBookingHref, shortDay, stripBlocks, stripUnits, type Occupancy, type StripBlock } from "@/lib/bookingAgenda";
import type { HoldBlock } from "@/lib/calendarHolds";
import { placeholderLabel, useSegment } from "@/lib/segments";

const DAYS = 14;
const NARROW = ["S", "M", "T", "W", "T", "F", "S"];
// Written out in full so Tailwind sees every class: column 1 is the unit label (short tags for a couple of caravans, the full name
// otherwise), days are columns 2 to 15.
const GRID_SHORT = "grid grid-cols-[64px_repeat(14,minmax(0,1fr))]";
const GRID_WIDE = "grid grid-cols-[112px_repeat(14,minmax(0,1fr))]";
const COL_START = ["col-start-2", "col-start-3", "col-start-4", "col-start-5", "col-start-6", "col-start-7", "col-start-8",
  "col-start-9", "col-start-10", "col-start-11", "col-start-12", "col-start-13", "col-start-14", "col-start-15"];
const COL_SPAN = ["col-span-1", "col-span-2", "col-span-3", "col-span-4", "col-span-5", "col-span-6", "col-span-7",
  "col-span-8", "col-span-9", "col-span-10", "col-span-11", "col-span-12", "col-span-13", "col-span-14"];
const SLOT_BG: Record<number, string> = {
  0: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]",
  1: "bg-[var(--haip-cal-vehicle-1)] text-[var(--haip-cal-vehicle-fg)]",
  2: "bg-[var(--haip-cal-vehicle-2)] text-[var(--haip-cal-vehicle-fg)]",
};
const STORE = "haip.bookings.strip";   // "open" | "closed"

export const shortVehicle = (name: string) => /^ratha\s*(\d+)$/i.test(name.trim()) ? `R${name.trim().match(/(\d+)$/)![1]}` : name.slice(0, 4);

type Unit = Occupancy["vehicles"][number];

/** "9 of 11 villas free tonight · 4 check-ins · 2 calendar events need a villa": the folded strip's one line. */
export function stripSummary(units: Unit[], waiting: number, today: string, unit: { one: string; many: string }): string {
  const real = units.filter(u => !u.placeholder);
  const busy = (u: Unit) => u.bookings.some(b => b.check_in <= today && today < b.check_out) || u.holds.some(h => h.from <= today && today < h.to);
  const free = real.filter(u => !busy(u)).length;
  const checkIns = units.reduce((n, u) => n + u.bookings.filter(b => b.check_in >= today).length, 0);
  return [`${free} of ${real.length} ${real.length === 1 ? unit.one : unit.many} free tonight`,
    `${checkIns} check-in${checkIns === 1 ? "" : "s"}`,
    waiting ? `${waiting} calendar event${waiting === 1 ? "" : "s"} need${waiting === 1 ? "s" : ""} a ${unit.one}` : ""].filter(Boolean).join(" · ");
}

export function OccupancyStrip({ onOpen, onOpenHold, selectedId }: {
  onOpen: (bookingId: string) => void; onOpenHold?: (block: HoldBlock, unitName: string) => void; selectedId?: string;
}) {
  // Pending until hydrated: the server and the first client render show the same skeleton, whatever the cache holds.
  const hydrated = useHydrated();
  const seg = useSegment();
  const [stored, setStored] = useState<"open" | "closed" | null>(null);
  useEffect(() => {
    try { const v = window.localStorage.getItem(STORE); if (v === "open" || v === "closed") setStored(v); } catch { /* storage blocked: use the default */ }
  }, []);
  const { data, isPending, isError, refetch } = useQuery<Occupancy>({
    queryKey: ["bookings-occupancy", DAYS], queryFn: () => api.get("/bookings/occupancy", { params: { days: DAYS } }).then(r => r.data),
    staleTime: 30_000,
  });
  const split = data ? stripUnits(data) : null;
  const realCount = split ? split.units.filter(u => !u.placeholder).length : 0;
  const open = stored ? stored === "open" : realCount <= seg.sections.bookings.stripCollapsedAbove;
  const toggle = () => {
    const next = open ? "closed" : "open";
    setStored(next);
    try { window.localStorage.setItem(STORE, next); } catch { /* not remembered, still toggles */ }
  };
  const wide = !seg.unitTint;
  const GRID = wide ? GRID_WIDE : GRID_SHORT;

  // Units in order; the waiting holds join the placeholder row when there is one and a villa business calls both "Which villa?",
  // else get their own row (a caravan keeps "Unassigned" for bookings and "Which vehicle?" for calendar events).
  const rows: (Unit & { label: string; waitingRow?: boolean })[] = [];
  if (split) {
    const place = split.units.find(u => u.placeholder);
    const merge = !!place && placeholderLabel(seg) === seg.whichUnit;
    if (split.waiting.length && !merge) {
      rows.push({ property_id: "__waiting__", name: seg.whichUnit, slot: 0, placeholder: true, bookings: [], holds: split.waiting, label: seg.whichUnit, waitingRow: true });
    }
    for (const u of split.units) {
      if (u.placeholder) rows.push({ ...u, holds: merge ? [...u.holds, ...split.waiting] : u.holds, label: placeholderLabel(seg), waitingRow: merge });
      else rows.push({ ...u, label: wide ? u.name : shortVehicle(u.name) });
    }
  }
  const stripes = split?.waiting ?? [];

  return (
    <Card className="grid gap-1.5 px-3 py-3 sm:px-4" aria-label="Next 14 days">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="grid min-w-0 gap-0.5">
          <strong className="text-[14px] text-[var(--haip-fg)]">Next 14 days</strong>
          {split && !open && <span className="text-[12.5px] text-[var(--haip-fg-2)]">{stripSummary(split.units, split.waiting.length, data!.today, seg.unit)}</span>}
        </div>
        <span className="flex items-center gap-2 text-[12.5px] text-[var(--haip-fg-subtle)]">
          {open && seg.timing}
          {split && (
            <button type="button" onClick={toggle} aria-expanded={open}
              className="min-h-11 rounded-full border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3.5 text-[12.5px] font-semibold text-primary md:min-h-9">
              {open ? `Hide ${seg.unit.many}` : `Show ${seg.unit.many}`}
            </button>
          )}
        </span>
      </div>
      {!hydrated || isPending ? <Skeleton className="h-24 rounded-xl" /> : isError || !data ? (
        <p role="alert" className="text-[13px] text-[var(--haip-status-danger-fg)]">
          Couldn&apos;t load the {seg.unit.many}. <button type="button" className="min-h-11 font-semibold underline" onClick={() => refetch()}>Try again</button>
        </p>
      ) : !open ? null : realCount === 0 ? (
        <p className="py-3 text-[13px] text-[var(--haip-fg-subtle)]">No {seg.unit.many} set up yet.</p>
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
          {rows.map(v => {
            const blocks = stripBlocks(v, data.from, DAYS);
            const ghosts = v.placeholder ? [] : stripBlocks({ ...v, bookings: [], holds: stripes }, data.from, DAYS);
            return (
              <div key={v.property_id} className={cn(GRID, "relative items-center rounded-lg", v.waitingRow && "bg-[var(--haip-status-warning-bg)]/40")} role="group" aria-label={v.label}>
                <span className={cn("col-start-1 row-start-1 pr-1", v.placeholder ? "text-[11px] font-bold leading-tight text-[var(--haip-status-warning-fg)]" : "truncate text-[12px] font-bold text-[var(--haip-fg-2)]")}
                  title={v.name}>{v.label}</span>
                {ghosts.map(g => (
                  <i key={`ghost:${g.key}`} aria-hidden className={cn("pointer-events-none row-start-1 mx-1 h-[5px] self-end rounded-full", COL_START[g.start], COL_SPAN[g.span - 1], WAITING_STRIPE)} />
                ))}
                {/* a "Which villa?" day is not offered as free: the event may be this unit's, and the server would refuse it */}
                {!v.placeholder && freeColumns([...blocks, ...ghosts], DAYS).map(i => {
                  const iso = addDays(data.from, i);
                  return (
                    <Link key={`free:${i}`} href={newBookingHref(v.property_id, iso)} aria-label={`New booking on ${v.name}, ${shortDay(iso)}`}
                      className={cn("row-start-1 mx-px h-9 rounded-lg border border-dashed border-transparent hover:border-[var(--haip-border-strong)] hover:bg-[var(--haip-surface)] focus-visible:border-primary", COL_START[i], "col-span-1")} />
                  );
                })}
                {blocks.map(blk => <Bar key={blk.key} blk={blk} unit={v} waitingRow={!!v.waitingRow} selectedId={selectedId} wide={wide}
                  onOpen={onOpen} onOpenHold={b => onOpenHold?.(b, v.waitingRow ? seg.whichUnit : v.name)} pick={`Pick ${seg.unit.one}`} />)}
              </div>
            );
          })}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-[var(--haip-fg-subtle)]">
            <span className="inline-flex items-center gap-1.5"><i className="inline-block h-3 w-3.5 rounded-sm bg-[var(--haip-cal-due-bg)] shadow-[inset_3px_0_0_var(--haip-cal-due-edge)]" aria-hidden />money still due</span>
            <span className="inline-flex items-center gap-1.5"><i className="inline-block h-3 w-3.5 rounded-sm bg-[var(--haip-cal-block)]" aria-hidden />from Google Calendar or blocked</span>
            {stripes.length > 0 && <span className="inline-flex items-center gap-1.5"><i className={cn("inline-block h-3 w-3.5 rounded-sm", WAITING_STRIPE)} aria-hidden />{seg.whichUnit}</span>}
            <span>Tap a {seg.booking.one} or a hold to open it, an empty day to book it</span>
          </div>
        </>
      )}
    </Card>
  );
}

function Bar({ blk, unit, waitingRow, selectedId, wide, onOpen, onOpenHold, pick }: {
  blk: StripBlock; unit: Unit; waitingRow: boolean; selectedId?: string; wide: boolean; pick: string;
  onOpen: (bookingId: string) => void; onOpenHold: (b: HoldBlock) => void;
}) {
  const waitingHold = waitingRow && blk.hold;
  const cls = cn("row-start-1 mx-px flex h-9 min-w-0 items-center gap-1 overflow-hidden whitespace-nowrap rounded-lg px-1.5 text-left text-[12px] font-bold",
    COL_START[blk.start], COL_SPAN[blk.span - 1],
    waitingHold ? "border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]"
      : blk.hold ? (blk.block?.reason === "maintenance" ? "bg-[var(--haip-cal-maint)] text-white" : "bg-[var(--haip-cal-block)] text-[var(--haip-cal-block-fg)]")
      : blk.due ? "bg-[var(--haip-cal-due-bg)] text-[var(--haip-cal-due-fg)] shadow-[inset_3px_0_0_var(--haip-cal-due-edge)]"
      : wide ? "bg-[var(--haip-cal-direct)] text-white"
      : SLOT_BG[unit.placeholder ? 0 : unit.slot] ?? SLOT_BG[1],
    blk.bookingId && blk.bookingId === selectedId && "ring-2 ring-primary");
  if (blk.bookingId) {
    return (
      <button type="button" className={cls} title={blk.title} aria-label={blk.title} data-due={blk.due ? "true" : undefined} onClick={() => onOpen(blk.bookingId!)}>
        <span className="truncate">{blk.label}</span>
      </button>
    );
  }
  return (
    <button type="button" className={cls} title={blk.title} aria-label={`${blk.title}. Open details`} onClick={() => blk.block && onOpenHold(blk.block)}>
      {blk.cal && <Calendar size={11} aria-hidden className="shrink-0" />}
      <span className="min-w-0 flex-1 truncate">{blk.label}</span>
      {waitingHold && blk.span >= 3 && <span className="shrink-0 rounded-full bg-[var(--haip-card)] px-1.5 py-0.5 text-[10.5px]">{pick}</span>}
    </button>
  );
}
