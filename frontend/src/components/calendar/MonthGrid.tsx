"use client";
// A month calendar for ONE property, the way a booking site shows availability: a 7-column date grid, bookings and holds as bars
// that span their dates (a stay runs from the afternoon of check-in to the morning of check-out), tap a bar for its details.
// Colours come from the caller (green direct, gray blocked, red maintenance, one colour per other channel).
import { useMemo } from "react";
import { addDays, differenceInCalendarDays, format, isSameMonth, isToday, parseISO } from "date-fns";
import { cn } from "@/lib/utils";
import { BLOCK_TONE, type Entry, type RowLite } from "./CalendarParts";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const LANE_H = 20;           // px per bar
const DAY_NUM_H = 22;        // px reserved for the date number above the bars

interface Seg { key: string; entry: Entry; col: number; end: number; lane: number; startsHere: boolean; endsHere: boolean; label: string; tone: { bg: string; text: string }; faded: boolean; dashed: boolean; mark: string }

/** Lay one week's bars into lanes so overlapping ones stack instead of covering each other. */
function layout(segs: Omit<Seg, "lane">[]): { segs: Seg[]; lanes: number } {
  const sorted = [...segs].sort((a, b) => a.col - b.col || b.end - a.end);
  const laneEnd: number[] = [];
  const out: Seg[] = sorted.map(s => {
    let lane = laneEnd.findIndex(e => e <= s.col + 1e-6);
    if (lane < 0) { lane = laneEnd.length; laneEnd.push(0); }
    laneEnd[lane] = s.end;
    return { ...s, lane };
  });
  return { segs: out, lanes: Math.max(1, laneEnd.length) };
}

export function MonthGrid({ row, monthStart, gridStart, onOpen, chColor, channelLabel }: {
  row: RowLite | undefined; monthStart: Date; gridStart: Date; onOpen: (e: Entry) => void;
  chColor: (src: string) => { bg: string; text: string }; channelLabel: (src: string) => string;
}) {
  const weeks = useMemo(() => {
    const out: { days: Date[]; segs: Seg[]; lanes: number }[] = [];
    for (let w = 0; w < 6; w++) {
      const start = addDays(gridStart, w * 7);
      const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
      const raw: Omit<Seg, "lane">[] = [];
      const place = (key: string, entry: Entry, from: number, to: number, label: string, tone: { bg: string; text: string }, extra: Partial<Seg> = {}) => {
        // from/to are positions in days since the week start (fractions allowed); clip to this week
        const col = Math.max(0, from), end = Math.min(7, to);
        if (end - col <= 0.01) return;
        raw.push({ key: `${key}-${w}`, entry, col, end, startsHere: from >= 0, endsHere: to <= 7, label, tone, faded: false, dashed: false, mark: "", ...extra });
      };
      for (const s of row?.stays ?? []) {
        if (s.status === "cancelled") continue;
        const a = differenceInCalendarDays(parseISO(s.check_in), start), b = differenceInCalendarDays(parseISO(s.check_out), start);
        const [f, t] = a === b ? [a + 0.1, a + 0.9] : [a + 0.5, b + 0.5];            // a same-day stay still gets a bar
        place(`s${s.id}`, { kind: "stay", stay: s, propertyName: row?.property_name ?? "" }, f, t, (s.guest_name || "Guest").split(" ")[0] || "Guest",
          chColor(s.channel_source), { faded: s.status === "quoted", dashed: s.status === "quoted", mark: s.status === "checked_in" ? "✓ " : "" });
      }
      for (const b of row?.blocks ?? []) {
        const a = differenceInCalendarDays(parseISO(b.blocked_from), start);
        const z = Math.max(differenceInCalendarDays(parseISO(b.blocked_to), start), a + 1);   // a one-day hold still shows
        const tone = BLOCK_TONE(b.reason);
        place(`b${b.id}`, { kind: "block", block: b, propertyName: row?.property_name ?? "" }, a, z,
          b.event?.details.guest_name?.split(" ")[0] || tone.label, { bg: tone.bg, text: tone.text });
      }
      const { segs, lanes } = layout(raw);
      out.push({ days, segs, lanes });
    }
    return out;
  }, [row, gridStart]);

  return (
    <div role="grid" aria-label={`${format(monthStart, "MMMM yyyy")} availability`} className="select-none">
      <div role="row" className="sticky top-0 z-10 grid grid-cols-7 border-b border-gray-200 bg-white text-[11px] font-semibold uppercase tracking-wide text-gray-500">
        {WEEKDAYS.map(d => <div key={d} role="columnheader" className="py-1.5 text-center">{d}</div>)}
      </div>
      {weeks.map((w, wi) => {
        const height = DAY_NUM_H + w.lanes * LANE_H + 8;
        return (
          <div key={wi} role="row" className="relative grid grid-cols-7 border-b border-gray-100" style={{ minHeight: Math.max(64, height) }}>
            {w.days.map(d => {
              const inMonth = isSameMonth(d, monthStart);
              return (
                <div key={d.toISOString()} role="gridcell" aria-label={format(d, "EEEE d MMMM")}
                  className={cn("border-r border-gray-100 px-1 pt-1 last:border-r-0", !inMonth && "bg-gray-50")}>
                  <span className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded-full text-[11px] tabular-nums",
                    isToday(d) ? "bg-teal-600 font-bold text-white" : inMonth ? "text-gray-700" : "text-gray-300")}>
                    {d.getDate() === 1 ? format(d, "d MMM") : d.getDate()}
                  </span>
                </div>
              );
            })}
            {w.segs.map(s => {
              const e = s.entry;
              const name = e.kind === "stay" ? `${e.stay.guest_name || "Guest"} (${channelLabel(e.stay.channel_source)}), ${e.stay.check_in} to ${e.stay.check_out}`
                : `${BLOCK_TONE(e.block.reason).label}, ${e.block.blocked_from} to ${e.block.blocked_to}`;
              return (
                <button key={s.key} type="button" onClick={() => onOpen(s.entry)} aria-label={`${name}. Open details`}
                  className={cn("absolute flex items-center overflow-hidden border px-1.5 text-left text-[11px] font-semibold leading-none shadow-sm active:brightness-95",
                    s.tone.bg, s.tone.text, s.faded && "opacity-60", s.dashed ? "border-dashed border-gray-600" : "border-transparent",
                    s.startsHere ? "rounded-l-full" : "rounded-l-none", s.endsHere ? "rounded-r-full" : "rounded-r-none")}
                  style={{ left: `calc(${(s.col / 7) * 100}% + 1px)`, width: `calc(${((s.end - s.col) / 7) * 100}% - 2px)`, top: DAY_NUM_H + s.lane * LANE_H, height: LANE_H - 2 }}>
                  <span className="truncate">{s.mark}{s.startsHere || s.col === 0 ? s.label : ""}</span>
                </button>
              );
            })}
          </div>
        );
      })}
      <p className="px-3 py-2 text-[11px] text-gray-500">
        A stay runs from the afternoon of check-in to the morning of check-out. Dashed = a quote, ✓ = checked in.
        {row ? "" : " No property selected."}
      </p>
    </div>
  );
}
