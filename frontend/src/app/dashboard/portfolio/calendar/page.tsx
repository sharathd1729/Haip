"use client";

/**
 * Portfolio Calendar — PMS-style booking bar view
 *
 * Layout: Property sidebar (left) + scrollable date grid (right)
 * Each stay renders as a horizontal colored bar spanning check-in → check-out
 * Channel source drives the bar color (direct=teal, airbnb=rose, booking=blue, etc.)
 */

import { useState, useMemo, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  addDays, format, parseISO, isToday,
} from "date-fns";
import {
  ChevronLeft, ChevronRight, Calendar,
  Bed, Zap, TrendingUp, RefreshCw, Users, CloudDownload, CheckCircle2, AlertCircle,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Constants ─────────────────────────────────────────────────────────────────

const DAY_COL_PX = 36;          // px width of each day column
const ROW_H_PX   = 52;          // px height of each property row
const SIDEBAR_W  = 200;         // px width of property name sidebar

const VIEW_DAYS = {
  "14": 14,
  "30": 30,
  "60": 60,
} as const;
type ViewWindow = keyof typeof VIEW_DAYS;

// Channel → bar color classes
const CHANNEL_COLOR: Record<string, { bg: string; text: string; border: string }> = {
  airbnb:     { bg: "bg-rose-500",     text: "text-white",    border: "border-rose-600" },
  "booking.com": { bg: "bg-blue-500",  text: "text-white",    border: "border-blue-600" },
  vrbo:       { bg: "bg-orange-500",   text: "text-white",    border: "border-orange-600" },
  expedia:    { bg: "bg-yellow-500",   text: "text-white",    border: "border-yellow-600" },
  makemytrip: { bg: "bg-red-500",      text: "text-white",    border: "border-red-600" },
  direct:     { bg: "bg-teal-500",     text: "text-white",    border: "border-teal-600" },
  hostaway:   { bg: "bg-violet-500",   text: "text-white",    border: "border-violet-600" },
  retalwise:  { bg: "bg-indigo-500",   text: "text-white",    border: "border-indigo-600" },
};
const DEFAULT_COLOR = { bg: "bg-gray-500", text: "text-white", border: "border-gray-600" };

function channelColor(src?: string | null) {
  if (!src) return CHANNEL_COLOR.direct;
  return CHANNEL_COLOR[src.toLowerCase()] ?? DEFAULT_COLOR;
}

// Status → opacity overlay
function statusOpacity(status: string) {
  if (status === "checked_in") return "opacity-100";
  if (status === "confirmed")  return "opacity-90";
  if (status === "quoted")     return "opacity-60";
  return "opacity-40";
}

// Block → background striping
const BLOCK_BG: Record<string, string> = {
  maintenance:      "bg-gray-300",
  personal:         "bg-amber-200",
  owner_use:        "bg-amber-200",
  offline_booking:  "bg-slate-400",
  other:            "bg-gray-200",
};

const fmt = (n: number) =>
  `₹${Math.round(n).toLocaleString("en-IN")}`;

// ── Types ─────────────────────────────────────────────────────────────────────

interface StayBar {
  id: string;
  check_in: string;
  check_out: string;
  status: string;
  guest_name: string;
  adults: number;
  total_amount?: number | null;
  channel_source: string;
}

interface BlockBar {
  id: string;
  blocked_from: string;
  blocked_to: string;
  reason: string;
  notes?: string;
}

interface CalendarRow {
  property_id: string;
  property_name: string;
  property_type: string;
  bedrooms: number;
  max_adults: number;
  channel_source?: string;
  cells: Record<string, string>;
  stays: StayBar[];
  blocks: BlockBar[];
}

interface CalendarStats {
  occupancy_pct: number;
  revenue_locked: number;
  revenue_quoted: number;
}

interface CalendarResponse {
  from_date: string;
  to_date: string;
  days: string[];
  properties: CalendarRow[];
  stats: CalendarStats;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function OccupancyBadge({ pct }: { pct: number }) {
  const color = pct >= 80 ? "text-green-600 bg-green-50" :
                pct >= 50 ? "text-amber-600 bg-amber-50" :
                            "text-red-600 bg-red-50";
  return (
    <span className={cn("text-xs font-bold px-2 py-0.5 rounded-full tabular-nums", color)}>
      {pct}%
    </span>
  );
}

function ChannelLegend() {
  const entries = [
    { label: "Direct",       color: CHANNEL_COLOR.direct.bg },
    { label: "Airbnb",       color: CHANNEL_COLOR.airbnb.bg },
    { label: "Booking.com",  color: CHANNEL_COLOR["booking.com"].bg },
    { label: "VRBO",         color: CHANNEL_COLOR.vrbo.bg },
    { label: "MakeMyTrip",   color: CHANNEL_COLOR.makemytrip.bg },
    { label: "RentalWise",   color: CHANNEL_COLOR.retalwise.bg },
  ];
  return (
    <div className="flex items-center gap-3 flex-wrap">
      {entries.map(e => (
        <div key={e.label} className="flex items-center gap-1">
          <div className={cn("w-3 h-3 rounded-sm", e.color)} />
          <span className="text-xs text-gray-500">{e.label}</span>
        </div>
      ))}
      <div className="flex items-center gap-1">
        <div className="w-3 h-3 rounded-sm bg-gray-300" />
        <span className="text-xs text-gray-500">Blocked</span>
      </div>
      <div className="flex items-center gap-1">
        <div className="w-3 h-3 rounded-sm bg-amber-200" />
        <span className="text-xs text-gray-500">Owner use</span>
      </div>
    </div>
  );
}

// ── Property row with booking bars ────────────────────────────────────────────

function PropertyRow({
  row,
  days,
  startDate,
}: {
  row: CalendarRow;
  days: string[];
  startDate: Date;
}) {
  const [hoveredStay, setHoveredStay] = useState<StayBar | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  // Property-level occupancy for this window
  const confirmedDays = days.filter(d => {
    const cs = row.cells[d];
    return cs === "confirmed" || cs === "checked_in";
  }).length;
  const occPct = days.length > 0 ? Math.round((confirmedDays / days.length) * 100) : 0;

  return (
    <div
      className="flex border-b border-gray-100 group"
      style={{ height: ROW_H_PX }}
    >
      {/* Property name sidebar */}
      <div
        className="flex-shrink-0 flex items-center gap-2 px-3 bg-white border-r border-gray-100"
        style={{ width: SIDEBAR_W }}
      >
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-800 truncate">{row.property_name}</p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[10px] text-gray-400 flex items-center gap-0.5">
              <Bed size={9} />{row.bedrooms}BR
            </span>
            <span className="text-[10px] text-gray-400 flex items-center gap-0.5">
              <Users size={9} />{row.max_adults}
            </span>
            <OccupancyBadge pct={occPct} />
          </div>
        </div>
      </div>

      {/* Day grid + booking bars */}
      <div
        className="relative flex-1"
        style={{ minWidth: days.length * DAY_COL_PX }}
      >
        {/* Grid lines */}
        <div className="absolute inset-0 flex pointer-events-none">
          {days.map((day, i) => {
            const d = parseISO(day);
            const weekend = d.getDay() === 0 || d.getDay() === 6;
            const todayDay = isToday(d);
            return (
              <div
                key={day}
                className={cn(
                  "h-full border-r border-gray-100 flex-shrink-0",
                  weekend && "bg-gray-50/60",
                  todayDay && "bg-teal-50/40"
                )}
                style={{ width: DAY_COL_PX }}
              />
            );
          })}
        </div>

        {/* Block bars */}
        {row.blocks.map(block => {
          const blockStart = block.blocked_from;
          const blockEnd   = block.blocked_to;
          // Clamp to window
          const winStart = days[0];
          const winEnd   = days[days.length - 1];
          if (blockEnd <= winStart || blockStart > winEnd) return null;

          const startIdx = Math.max(days.indexOf(blockStart), 0);
          const endIdx   = days.indexOf(blockEnd);
          const spanDays = endIdx >= 0
            ? endIdx - startIdx
            : days.length - startIdx;
          if (spanDays <= 0) return null;

          const bg = BLOCK_BG[block.reason] ?? "bg-gray-200";

          return (
            <div
              key={block.id}
              className={cn(
                "absolute top-2 rounded-sm h-7 flex items-center px-1.5 text-[10px] text-gray-600 font-medium select-none overflow-hidden",
                bg
              )}
              style={{
                left: startIdx * DAY_COL_PX + 1,
                width: spanDays * DAY_COL_PX - 2,
              }}
              title={block.notes || block.reason}
            >
              <span className="truncate capitalize">{block.reason.replace(/_/g, " ")}</span>
            </div>
          );
        })}

        {/* Stay booking bars */}
        {row.stays.map(stay => {
          const winStart = days[0];
          const winEnd   = days[days.length - 1];
          if (stay.check_out <= winStart || stay.check_in > winEnd) return null;

          const startIdx = Math.max(days.indexOf(stay.check_in), 0);
          const rawEnd   = days.indexOf(stay.check_out);
          // If check_out is beyond window, span to end
          const spanDays = rawEnd >= 0
            ? rawEnd - startIdx
            : days.length - startIdx;
          if (spanDays <= 0) return null;

          const cc = channelColor(stay.channel_source);

          return (
            <div
              key={stay.id}
              className={cn(
                "absolute top-1.5 rounded-md h-8 flex items-center px-2 gap-1 select-none overflow-hidden cursor-pointer transition-transform active:scale-[0.98] border",
                cc.bg, cc.text, cc.border, statusOpacity(stay.status)
              )}
              style={{
                left: startIdx * DAY_COL_PX + 2,
                width: spanDays * DAY_COL_PX - 4,
                zIndex: 2,
              }}
              title={`${stay.guest_name || "Guest"} · ${stay.status} · ${spanDays}n${stay.total_amount ? ` · ${fmt(stay.total_amount)}` : ""}`}
              onMouseEnter={(e) => {
                setHoveredStay(stay);
                setTooltipPos({ x: e.clientX, y: e.clientY });
              }}
              onMouseLeave={() => setHoveredStay(null)}
            >
              {spanDays >= 2 && (
                <span className="text-[10px] font-semibold truncate leading-none">
                  {stay.guest_name || "Guest"}
                  {spanDays >= 3 && stay.adults > 1 && ` · ${stay.adults}p`}
                </span>
              )}
              {spanDays === 1 && (
                <span className="text-[9px] font-semibold truncate">
                  {(stay.guest_name || "Guest")[0]}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

// ── Channel filter options ─────────────────────────────────────────────────

const CHANNEL_FILTERS = [
  { value: "",           label: "All channels" },
  { value: "rentalwise", label: "RentalWise" },
  { value: "airbnb",     label: "Airbnb" },
  { value: "booking.com",label: "Booking.com" },
  { value: "vrbo",       label: "VRBO" },
  { value: "direct",     label: "Direct" },
] as const;

// ── RentalWise sync status toast ───────────────────────────────────────────

function SyncStatusBadge({ status }: { status: "idle" | "loading" | "success" | "error" }) {
  if (status === "idle") return null;
  if (status === "loading") return (
    <span className="flex items-center gap-1 text-xs text-indigo-600 bg-indigo-50 px-2 py-1 rounded-xl animate-pulse">
      <CloudDownload size={11} className="animate-bounce" /> Syncing RentalWise…
    </span>
  );
  if (status === "success") return (
    <span className="flex items-center gap-1 text-xs text-green-600 bg-green-50 px-2 py-1 rounded-xl">
      <CheckCircle2 size={11} /> RentalWise synced
    </span>
  );
  return (
    <span className="flex items-center gap-1 text-xs text-red-600 bg-red-50 px-2 py-1 rounded-xl">
      <AlertCircle size={11} /> Sync failed
    </span>
  );
}

export default function PortfolioCalendarPage() {
  const [startDate, setStartDate] = useState<Date>(() => {
    const d = new Date();
    d.setDate(1);
    return d;
  });
  const [viewWindow, setViewWindow] = useState<ViewWindow>("30");
  const [search, setSearch] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const gridRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const numDays = VIEW_DAYS[viewWindow];
  const fromDate = format(startDate, "yyyy-MM-dd");
  const toDate   = format(addDays(startDate, numDays), "yyyy-MM-dd");

  const { data, isLoading, isError, refetch, isFetching } = useQuery<CalendarResponse>({
    queryKey: ["portfolio-calendar", fromDate, toDate],
    queryFn: () =>
      api.get(`/calendar?from_date=${fromDate}&to_date=${toDate}`)
         .then(r => r.data),
    staleTime: 2 * 60_000,
  });

  // RentalWise on-demand sync mutation
  const syncMutation = useMutation({
    mutationFn: () => api.post("/calendar/sync-rentalwise", {}).then(r => r.data),
    onSuccess: () => {
      // Invalidate calendar after a short delay to let Celery process
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["portfolio-calendar"] });
      }, 3000);
    },
  });

  const days  = data?.days ?? [];
  const stats = data?.stats;

  const properties = useMemo(() => {
    if (!data?.properties) return [];
    let list = data.properties;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(p => p.property_name.toLowerCase().includes(q));
    }
    if (channelFilter) {
      // Show properties that have at least one stay from the selected channel,
      // OR whose channel_source matches.
      list = list.filter(p =>
        p.channel_source?.toLowerCase() === channelFilter ||
        p.stays.some(s => s.channel_source?.toLowerCase() === channelFilter)
      );
    }
    return list;
  }, [data?.properties, search, channelFilter]);

  // Scroll "today" into view on first load
  const scrollToToday = () => {
    if (!gridRef.current) return;
    const todayIdx = days.indexOf(format(new Date(), "yyyy-MM-dd"));
    if (todayIdx >= 0) {
      gridRef.current.scrollLeft = Math.max(0, todayIdx * DAY_COL_PX - 100);
    }
  };

  const prevPeriod = () => setStartDate(d => addDays(d, -numDays));
  const nextPeriod = () => setStartDate(d => addDays(d, numDays));
  const goToToday  = () => { setStartDate(new Date()); setTimeout(scrollToToday, 100); };

  // ── Month groupings for header ─────────────────────────────────────────────
  const monthGroups = useMemo(() => {
    const groups: { label: string; count: number }[] = [];
    let curMonth = "";
    let count = 0;
    for (const day of days) {
      const m = format(parseISO(day), "MMM yyyy");
      if (m !== curMonth) {
        if (curMonth) groups.push({ label: curMonth, count });
        curMonth = m;
        count = 1;
      } else {
        count++;
      }
    }
    if (curMonth) groups.push({ label: curMonth, count });
    return groups;
  }, [days]);

  return (
    <div className="h-full flex flex-col bg-gray-50">

      {/* ── Top bar ─────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 bg-white border-b border-gray-200 px-4 py-3">
        <div className="flex items-center gap-3 flex-wrap">
          {/* Title */}
          <div className="flex items-center gap-2 mr-2">
            <Calendar size={18} className="text-teal-500" />
            <h1 className="text-base font-bold text-gray-900">Portfolio Calendar</h1>
          </div>

          {/* Date navigation */}
          <div className="flex items-center gap-1 bg-gray-100 rounded-xl p-1">
            <button
              onClick={prevPeriod}
              className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-white transition-colors text-gray-600"
            >
              <ChevronLeft size={15} />
            </button>
            <button
              onClick={goToToday}
              className="px-3 py-1 text-xs font-semibold text-gray-700 hover:bg-white rounded-lg transition-colors"
            >
              Today
            </button>
            <button
              onClick={nextPeriod}
              className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-white transition-colors text-gray-600"
            >
              <ChevronRight size={15} />
            </button>
          </div>

          {/* Period label */}
          <span className="text-sm font-semibold text-gray-700 min-w-[120px]">
            {format(startDate, "dd MMM")} – {format(addDays(startDate, numDays - 1), "dd MMM yyyy")}
          </span>

          {/* View selector */}
          <div className="flex items-center gap-1 bg-gray-100 rounded-xl p-1">
            {(Object.keys(VIEW_DAYS) as ViewWindow[]).map(v => (
              <button
                key={v}
                onClick={() => setViewWindow(v)}
                className={cn(
                  "px-3 py-1 text-xs font-semibold rounded-lg transition-colors",
                  viewWindow === v ? "bg-white text-teal-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
                )}
              >
                {v}d
              </button>
            ))}
          </div>

          {/* Channel filter */}
          <select
            value={channelFilter}
            onChange={e => setChannelFilter(e.target.value)}
            className="text-xs border border-gray-200 rounded-xl px-2 py-1.5 outline-none focus:ring-2 focus:ring-teal-300 bg-white text-gray-700 cursor-pointer"
          >
            {CHANNEL_FILTERS.map(f => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>

          {/* Property search */}
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter properties…"
            className="text-xs border border-gray-200 rounded-xl px-3 py-1.5 outline-none focus:ring-2 focus:ring-teal-300 w-36"
          />

          <div className="flex-1" />

          {/* Stats chips */}
          {stats && (
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 bg-teal-50 text-teal-700 px-3 py-1.5 rounded-xl text-xs font-semibold">
                <TrendingUp size={12} />
                {stats.occupancy_pct}% occ
              </div>
              <div className="flex items-center gap-1.5 bg-green-50 text-green-700 px-3 py-1.5 rounded-xl text-xs font-semibold">
                <Zap size={12} />
                {fmt(stats.revenue_locked)} locked
              </div>
              {stats.revenue_quoted > 0 && (
                <div className="flex items-center gap-1.5 bg-amber-50 text-amber-700 px-3 py-1.5 rounded-xl text-xs font-semibold">
                  {fmt(stats.revenue_quoted)} quoted
                </div>
              )}
            </div>
          )}

          {/* Sync status badge */}
          <SyncStatusBadge
            status={
              syncMutation.isPending ? "loading"
              : syncMutation.isSuccess ? "success"
              : syncMutation.isError ? "error"
              : "idle"
            }
          />

          {/* RentalWise sync button */}
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors",
              syncMutation.isPending
                ? "bg-indigo-100 text-indigo-400 cursor-not-allowed"
                : "bg-indigo-50 text-indigo-600 hover:bg-indigo-100"
            )}
            title="Sync bookings and availability from RentalWise"
          >
            <CloudDownload size={12} className={syncMutation.isPending ? "animate-pulse" : ""} />
            RentalWise Sync
          </button>

          {/* Refresh */}
          <button
            onClick={() => refetch()}
            className="w-8 h-8 flex items-center justify-center rounded-xl hover:bg-gray-100 text-gray-500 transition-colors"
            title="Refresh calendar"
          >
            <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Legend */}
        <div className="mt-2">
          <ChannelLegend />
        </div>
      </div>

      {/* ── Calendar grid ─────────────────────────────────────────── */}
      {isError ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-red-500 font-medium">Failed to load calendar</p>
            <button onClick={() => refetch()} className="mt-2 text-sm text-teal-600 hover:underline">
              Try again
            </button>
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-hidden flex flex-col">
          {/* Sticky header row */}
          <div className="flex flex-shrink-0 bg-white border-b border-gray-200 shadow-sm">
            {/* Sidebar header */}
            <div
              className="flex-shrink-0 bg-white border-r border-gray-200 flex items-end pb-1 px-3"
              style={{ width: SIDEBAR_W, height: 56 }}
            >
              <span className="text-xs font-semibold text-gray-500">
                {isLoading ? "…" : `${properties.length} properties`}
              </span>
            </div>

            {/* Scrollable date header — synced with grid scroll */}
            <div
              ref={gridRef}
              className="flex-1 overflow-x-auto scrollbar-hide"
            >
              {/* Month grouping row */}
              <div className="flex">
                {monthGroups.map(g => (
                  <div
                    key={g.label}
                    className="flex-shrink-0 text-[10px] font-bold text-gray-400 uppercase px-2 pt-1 border-r border-gray-100 last:border-r-0"
                    style={{ width: g.count * DAY_COL_PX }}
                  >
                    {g.label}
                  </div>
                ))}
              </div>
              {/* Day number row */}
              <div className="flex">
                {days.map(day => {
                  const d = parseISO(day);
                  const todayDay = isToday(d);
                  const weekend  = d.getDay() === 0 || d.getDay() === 6;
                  return (
                    <div
                      key={day}
                      className={cn(
                        "flex-shrink-0 flex flex-col items-center justify-end pb-1 border-r border-gray-100 last:border-r-0",
                        weekend && "bg-gray-50",
                        todayDay && "bg-teal-50"
                      )}
                      style={{ width: DAY_COL_PX, height: 32 }}
                    >
                      <span className={cn(
                        "text-[10px] font-semibold leading-none",
                        todayDay ? "text-teal-600 bg-teal-500 text-white rounded-full w-4 h-4 flex items-center justify-center" : "text-gray-500"
                      )}>
                        {format(d, "d")}
                      </span>
                      <span className="text-[8px] text-gray-300 mt-0.5 leading-none">
                        {format(d, "EEE")[0]}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Property rows — scroll x synced with header */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden haip-scrollbar">
            {isLoading ? (
              <div className="space-y-0">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div
                    key={i}
                    className="flex border-b border-gray-100 animate-pulse"
                    style={{ height: ROW_H_PX }}
                  >
                    <div
                      className="flex-shrink-0 bg-gray-100 border-r border-gray-100"
                      style={{ width: SIDEBAR_W }}
                    />
                    <div className="flex-1 bg-gray-50" />
                  </div>
                ))}
              </div>
            ) : properties.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-16">
                <Bed size={32} className="text-gray-300 mb-3" />
                <p className="text-gray-500 font-medium">No properties found</p>
                <p className="text-xs text-gray-400 mt-1">Add properties in Portfolio settings</p>
              </div>
            ) : (
              // Scroll container for rows — x-scrollable, synced via shared ref
              <div
                className="overflow-x-auto haip-scrollbar-x"
                onScroll={e => {
                  // Sync header scroll
                  if (gridRef.current) {
                    gridRef.current.scrollLeft = (e.target as HTMLElement).scrollLeft;
                  }
                }}
                style={{ minWidth: "100%" }}
              >
                <div style={{ minWidth: SIDEBAR_W + days.length * DAY_COL_PX }}>
                  {properties.map(row => (
                    <PropertyRow
                      key={row.property_id}
                      row={row}
                      days={days}
                      startDate={startDate}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
