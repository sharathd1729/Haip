"use client";
// The Calendar's summary cards (desktop). Every number says what it covers: the window shown for occupancy and money, tonight for
// free units. Occupancy counts HAIP bookings plus nights held by a calendar event that names its unit (owner, 7 Nov), drawn as
// two parts of one bar; events still waiting for a unit ("Which villa?") never count. Money due is terracotta, the one accent.
import { format, parseISO } from "date-fns";
import { cn } from "@/lib/utils";
import type { Segment } from "@/lib/segments";

export interface CalendarStatsData {
  booked_nights?: number; held_nights?: number; possible_nights?: number; occupancy_with_holds_pct?: number;
  free_today?: number; waiting_events?: number; total_properties: number; check_ins_today?: number;
}

const card = "flex min-w-0 flex-col gap-1 rounded-2xl border bg-[var(--haip-card)] px-3.5 py-2.5";
const big = "font-[family-name:var(--font-display)] text-[22px] font-semibold leading-tight tabular-nums";
const span = (from: string, to: string) => `${format(parseISO(from), "d MMM")} – ${format(parseISO(to), "d MMM")}`;
const inr = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

export function CalendarStats({ stats, from, lastDay, seg, due, onWaiting }: {
  stats: CalendarStatsData; from: string; lastDay: string; seg: Segment;
  due: { amount: number; stays: number } | null;          // null = amounts hidden for this role
  onWaiting: () => void;
}) {
  const possible = stats.possible_nights ?? 0;
  const booked = stats.booked_nights ?? 0, held = stats.held_nights ?? 0;
  const pct = (n: number) => (possible ? `${Math.min(100, (n / possible) * 100)}%` : "0%");
  const waiting = stats.waiting_events ?? 0;
  return (
    <div className="grid flex-shrink-0 grid-cols-2 gap-2.5 border-b border-[var(--haip-border)] bg-[var(--haip-app-bg)] px-4 py-3 lg:grid-cols-5">
      <div className={cn(card, "border-[var(--haip-border)]")}>
        <span className="text-[12px] text-[var(--haip-fg-subtle)]">Occupancy · {span(from, lastDay)}</span>
        <b className={big}>{possible ? `${Math.round(stats.occupancy_with_holds_pct ?? 0)}%` : "No data"}</b>
        <span className="flex h-1.5 overflow-hidden rounded-full bg-[var(--haip-status-neutral-bg)]" aria-hidden>
          <i className="bg-primary" style={{ width: pct(booked) }} /><i className="bg-[var(--haip-cal-held)]" style={{ width: pct(held) }} />
        </span>
        <span className="text-[11.5px] text-[var(--haip-fg-subtle)]">{booked} nights booked + {held} held by calendar, of {possible}</span>
      </div>
      <div className={cn(card, "border-[var(--haip-border)]")}>
        <span className="text-[12px] text-[var(--haip-fg-subtle)]">Free tonight · {format(new Date(), "EEE d MMM")}</span>
        <b className={big}>{stats.free_today ?? "–"} of {stats.total_properties} {seg.unit.many}</b>
      </div>
      <div className={cn(card, "border-[var(--haip-border)]")}>
        <span className="text-[12px] text-[var(--haip-fg-subtle)]">Check-ins · today</span>
        <b className={big}>{stats.check_ins_today ?? 0}</b>
      </div>
      <div className={cn(card, "border-[var(--haip-accent-line)]")}>
        <span className="text-[12px] text-[var(--haip-accent-ink)]">Money still due · {seg.booking.many} shown</span>
        {due ? (
          <>
            <b className={cn(big, due.amount > 0 && "text-[var(--haip-accent-ink)]")}>{due.amount > 0 ? inr(due.amount) : "Nothing due"}</b>
            <span className="text-[11.5px] text-[var(--haip-fg-subtle)]">{due.stays} {due.stays === 1 ? seg.booking.one : seg.booking.many}</span>
          </>
        ) : <b className={big}>Hidden</b>}
      </div>
      {waiting > 0 ? (
        <button type="button" onClick={onWaiting}
          className={cn(card, "border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] text-left text-[var(--haip-status-warning-fg)]")}>
          <span className="text-[12px]">{seg.whichUnit} · from Google Calendar</span>
          <b className={big}>{waiting} event{waiting === 1 ? "" : "s"}</b>
          <span className="text-[11.5px] underline">Pick a {seg.unit.one} for each</span>
        </button>
      ) : (
        <div className={cn(card, "border-[var(--haip-border)]")}>
          <span className="text-[12px] text-[var(--haip-fg-subtle)]">{seg.whichUnit}</span>
          <b className={big}>None</b>
          <span className="text-[11.5px] text-[var(--haip-fg-subtle)]">Every calendar event names its {seg.unit.one}</span>
        </div>
      )}
    </div>
  );
}
