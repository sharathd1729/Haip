"use client";

/**
 * Portfolio Calendar — Hostaway / RentalWise / Airbnb-style Multi-Calendar
 *
 * Modes  : Bookings | Rates | Availability | Revenue
 * Perf   : Virtual row scrolling · React.memo · useCallback · useMemo
 * Layout : Sticky property sidebar (L) + scrollable date grid (R)
 * UX     : Hover card (portal) · per-stay source badge · nightly rate row
 */

import {
  useState, useMemo, useRef, useCallback, useEffect, memo,
} from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { canCreateBookings } from "@/lib/permissions";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { addDays, addMonths, format, parseISO, isToday, startOfMonth, startOfWeek } from "date-fns";
import { daysBetween } from "@/lib/bookingAgenda";
import { cleanName, holdLabel, nightsWord, splitWaiting, type HoldBlock } from "@/lib/calendarHolds";
import { useSegment, type Segment } from "@/lib/segments";
import { ChevronLeft, ChevronRight, Calendar, RefreshCw, CloudDownload, CheckCircle2, AlertCircle, DollarSign, BarChart2, Eye, Phone, Hash } from "@/lib/icons";
import { Bed } from "lucide-react";
import { BLOCK_TONE, DUE_TONE, EntrySheet, WAITING_STRIPE, moneyDue, type Entry } from "@/components/calendar/CalendarParts";
import { CalendarStats } from "@/components/calendar/CalendarStats";
import { MonthGrid } from "@/components/calendar/MonthGrid";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Constants ─────────────────────────────────────────────────────────────────

const SIDEBAR_W = 176;   // px — sticky unit column: the full name and what it holds in the window

const DAY_W     = 40;    // px — each day column

const RATE_H    = 26;    // px — nightly-rate sub-row height (Rates mode)

const ROW_H: Record<CalendarMode, number> = {
  bookings:     60,
  rates:        60 + RATE_H + 1,
  availability: 54,
  revenue:      80,
};

type CalendarMode = "bookings" | "rates" | "availability" | "revenue";
type ViewWindow   = "14" | "30" | "60" | "90";

const VIEW_DAYS: Record<ViewWindow, number> = {
  "14": 14, "30": 30, "60": 60, "90": 90,
};

// ── Channel config ─────────────────────────────────────────────────────────────

interface ChConfig {
  bg: string; text: string; border: string; dot: string;
  label: string; short: string;
}

const CH: Record<string, ChConfig> = {
  airbnb:         { bg:"bg-rose-500",    text:"text-white", border:"border-rose-600",    dot:"bg-rose-400",    label:"Airbnb",       short:"ABB" },
  "booking.com":  { bg:"bg-blue-600",    text:"text-white", border:"border-blue-700",    dot:"bg-blue-500",    label:"Booking.com",  short:"BDC" },
  direct:         { bg:"bg-[var(--haip-cal-direct)]", text:"text-white", border:"border-[var(--haip-cal-direct)]", dot:"bg-[var(--haip-cal-direct)]", label:"Direct",       short:"DIR" },
  makemytrip:     { bg:"bg-orange-500",  text:"text-white", border:"border-orange-600",  dot:"bg-orange-400",  label:"MMT",          short:"MMT" },
  vrbo:           { bg:"bg-purple-500",  text:"text-white", border:"border-purple-600",  dot:"bg-purple-400",  label:"VRBO",         short:"VBO" },
  expedia:        { bg:"bg-yellow-500",  text:"text-white", border:"border-yellow-600",  dot:"bg-yellow-400",  label:"Expedia",      short:"EXP" },
  hostaway:       { bg:"bg-violet-500",  text:"text-white", border:"border-violet-600",  dot:"bg-violet-400",  label:"Hostaway",     short:"HA"  },
  retalwise:      { bg:"bg-indigo-500",  text:"text-white", border:"border-indigo-600",  dot:"bg-indigo-400",  label:"RentalWise",   short:"RW"  },
};
const CH_DEFAULT: ChConfig = { bg:"bg-gray-500", text:"text-white", border:"border-gray-600", dot:"bg-[var(--haip-border-strong)]", label:"Other",       short:"OTH" };
const CH_BLOCKED: ChConfig = { bg:"bg-[var(--haip-cal-block)]", text:"text-[var(--haip-cal-block-fg)]", border:"border-[var(--haip-border-strong)]", dot:"bg-[var(--haip-cal-block)]", label:"Blocked", short:"BLK" };
const CH_MAINT:   ChConfig = { bg:"bg-[var(--haip-cal-maint)]",  text:"text-white",  border:"border-[var(--haip-cal-maint)]",  dot:"bg-[var(--haip-cal-maint)]",  label:"Maint.",  short:"MNT" };

function chConfig(src?: string | null): ChConfig {
  if (!src) return CH.direct;
  return CH[src.toLowerCase()] ?? CH_DEFAULT;
}

// Availability cell colours
const AVAIL_BG: Record<string, string> = {
  free:            "bg-emerald-100",
  available:       "bg-emerald-100",
  confirmed:       "bg-slate-200",
  checked_in:      "bg-slate-300",
  quoted:          "bg-amber-100",
  inquiry:         "bg-sky-100",
  blocked:         "bg-[var(--haip-border-strong)]",
  maintenance:     "bg-red-400",
  owner_use:       "bg-[var(--haip-border-strong)]",
  offline_booking: "bg-slate-300",
  other:           "bg-[var(--haip-border)]",
};
const AVAIL_LABEL: Record<string, string> = {
  free: "Available", available: "Available", confirmed: "Booked",
  checked_in: "Checked In", quoted: "Quoted", inquiry: "Inquiry",
  blocked: "Blocked", maintenance: "Maintenance", owner_use: "Owner Use",
  offline_booking: "Offline Booking",
};

// Revenue heatmap gradient
function revenueBg(rate: number | undefined, maxRate: number): string {
  if (!rate || maxRate <= 0) return "bg-white";
  const pct = Math.min(1, rate / maxRate);
  if (pct > 0.75) return "bg-emerald-200";
  if (pct > 0.50) return "bg-emerald-100";
  if (pct > 0.25) return "bg-emerald-50";
  return "bg-white";
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface StayBar {
  id: string;
  external_id?: string;
  check_in: string;
  check_out: string;
  status: string;
  guest_id?: string | null;
  guest_name: string;
  guest_phone?: string;
  adults: number;
  total_amount?: number | null;
  paid_amount?: number | null;   // with revenue.read only, like the total
  channel_source: string;
  inquiry_id?: string | null;   // the lead this booking came from
  notes?: string;               // staff notes (which caravan: Black / White)
}

// A hold: hand-made, or read from an imported calendar (event: title, link name, key shared by every copy of an event held on
// all units, waiting for a unit or not; amounts only with revenue.read).
type BlockBar = HoldBlock;

interface CalendarRow {
  property_id: string;
  property_name: string;
  property_type: string;
  bedrooms: number;
  max_adults: number;
  image_url?: string;
  channel_source?: string;
  monthly_revenue?: number;
  booked_nights?: number;        // in the window: HAIP bookings
  held_nights?: number;          // in the window: nights held by a calendar event naming this unit
  cells: Record<string, string>;
  stays: StayBar[];
  blocks: BlockBar[];
  rates?: Record<string, number>;
}

interface CalendarStats {
  occupancy_pct: number;
  revenue_locked: number;
  revenue_quoted: number;
  total_properties: number;
  window_days: number;
  check_ins_today?: number;
  check_outs_today?: number;
  vacant_today?: number;
  booked_nights?: number; held_nights?: number; possible_nights?: number; occupancy_with_holds_pct?: number;
  free_today?: number; waiting_events?: number; revenue_restricted?: boolean;
}

interface CalendarResponse {
  from_date: string;
  to_date: string;
  days: string[];
  properties: CalendarRow[];
  stats: CalendarStats;
  suggestions?: { type: string; property: string; date: string; message: string }[];
}

// ── Utilities ──────────────────────────────────────────────────────────────────

const fmt  = (n?: number | null) => n != null ? `₹${Math.round(n).toLocaleString("en-IN")}` : "—";
const fmtK = (n?: number | null) => {
  if (n == null) return "—";
  if (n >= 100_000) return `₹${(n / 100_000).toFixed(1)}L`;
  if (n >=   1_000) return `₹${Math.round(n / 1000)}k`;
  return `₹${Math.round(n)}`;
};
const fmtRate = (r?: number) =>
  r ? (r >= 10_000 ? `₹${Math.round(r / 1000)}k` : `₹${Math.round(r).toLocaleString("en-IN")}`) : "—";

// ── Custom hook: virtual rows ─────────────────────────────────────────────────

function useVirtualRows(
  scrollRef: React.RefObject<HTMLDivElement | null>,
  totalRows: number,
  rowH: number,
  overscan = 4,
) {
  const [scrollTop, setScrollTop] = useState(0);
  const [viewH, setViewH] = useState(800);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    setViewH(el.clientHeight);
    const ro = new ResizeObserver(() => setViewH(el.clientHeight));
    ro.observe(el);
    const onScroll = () => setScrollTop(el.scrollTop);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => { ro.disconnect(); el.removeEventListener("scroll", onScroll); };
  }, [scrollRef]);

  const start  = Math.max(0, Math.floor(scrollTop / rowH) - overscan);
  const end    = Math.min(totalRows - 1, Math.ceil((scrollTop + viewH) / rowH) + overscan);
  const padTop = start * rowH;
  const padBot = Math.max(0, (totalRows - end - 1) * rowH);
  return { start, end, padTop, padBot };
}

// ── HoverCard (portal) ─────────────────────────────────────────────────────────

const HoverCard = memo(function HoverCard({
  stay, pos,
}: {
  stay: StayBar; pos: { x: number; y: number };
}) {
  const cc = chConfig(stay.channel_source);
  const nights = stay.check_in && stay.check_out
    ? Math.max(1, Math.round((+new Date(stay.check_out) - +new Date(stay.check_in)) / 86_400_000))
    : 0;
  const outstanding = (stay.total_amount ?? 0) - (stay.paid_amount ?? 0);

  // Clamp card inside viewport
  const cardW = 252, cardH = 300;
  const left = Math.min(pos.x + 14, (typeof window !== "undefined" ? window.innerWidth : 1200) - cardW - 8);
  const top  = Math.min(pos.y + 6,  (typeof window !== "undefined" ? window.innerHeight : 900) - cardH - 8);

  const card = (
    <div
      className="fixed z-[9999] w-[252px] rounded-2xl shadow-2xl overflow-hidden pointer-events-none border border-[var(--haip-border)]"
      style={{ left, top }}
    >
      {/* Colour header */}
      <div className={cn("px-4 py-3", cc.bg)}>
        <div className="flex items-start justify-between">
          <div>
            <p className={cn("font-bold text-sm leading-tight", cc.text)}>
              {stay.guest_name || "Guest"}
            </p>
            <p className={cn("text-[11px] mt-0.5 opacity-80", cc.text)}>
              {cc.label} · {stay.adults} guest{stay.adults !== 1 ? "s" : ""}
            </p>
          </div>
          <span className={cn("text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-white/25 ml-2", cc.text)}>
            {cc.short}
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="bg-white px-4 py-3 space-y-2 text-xs">
        {stay.guest_phone && (
          <div className="flex items-center gap-2 text-[var(--haip-fg-muted)]">
            <Phone size={11} className="text-[var(--haip-fg-subtle)] shrink-0" />
            <span className="tabular-nums">{stay.guest_phone}</span>
          </div>
        )}
        {stay.external_id && (
          <div className="flex items-center gap-2 text-[var(--haip-fg-muted)]">
            <Hash size={11} className="text-[var(--haip-fg-subtle)] shrink-0" />
            <span className="font-mono text-[11px]">{stay.external_id}</span>
          </div>
        )}

        {/* Dates */}
        <div className="flex items-center justify-between pt-1.5 border-t border-[var(--haip-border)]">
          <div>
            <p className="text-[9px] text-[var(--haip-fg-subtle)] uppercase tracking-wide">Check-in</p>
            <p className="font-semibold text-[var(--haip-fg)]">{stay.check_in}</p>
          </div>
          <span className="text-[var(--haip-fg-subtle)]/70 text-base">→</span>
          <div className="text-right">
            <p className="text-[9px] text-[var(--haip-fg-subtle)] uppercase tracking-wide">Check-out</p>
            <p className="font-semibold text-[var(--haip-fg)]">{stay.check_out}</p>
          </div>
        </div>
        <p className="text-[10px] text-[var(--haip-fg-subtle)] text-center -mt-1">
          {nights} night{nights !== 1 ? "s" : ""}
        </p>

        {/* Financials */}
        <div className="pt-1.5 border-t border-[var(--haip-border)] space-y-1.5">
          <div className="flex justify-between">
            <span className="text-[var(--haip-fg-subtle)]">Total amount</span>
            <span className="font-bold text-[var(--haip-fg)]">{fmt(stay.total_amount)}</span>
          </div>
          {stay.paid_amount != null && (
            <div className="flex justify-between">
              <span className="text-[var(--haip-fg-subtle)]">Paid</span>
              <span className="font-semibold text-[var(--haip-status-success-fg)]">{fmt(stay.paid_amount)}</span>
            </div>
          )}
          {stay.paid_amount != null && stay.total_amount != null && (
            <div className="flex justify-between">
              <span className="text-[var(--haip-fg-subtle)]">Outstanding</span>
              <span className={cn("font-semibold", outstanding > 0 ? "text-[var(--haip-cal-due-fg)]" : "text-[var(--haip-fg-subtle)]")}>
                {fmt(outstanding)}
              </span>
            </div>
          )}
        </div>

        {/* Status badge */}
        <div className="pt-0.5">
          <span className={cn(
            "text-[10px] px-2 py-0.5 rounded-full font-semibold capitalize",
            ["confirmed","checked_in"].includes(stay.status)
              ? "bg-green-100 text-green-700"
              : stay.status === "quoted"
              ? "bg-amber-100 text-amber-700"
              : "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-muted)]",
          )}>
            {stay.status.replace("_", " ")}
          </span>
        </div>
      </div>
    </div>
  );

  if (typeof document === "undefined") return null;
  return createPortal(card, document.body);
});

// ── PropertySidebarCell ────────────────────────────────────────────────────────

const PropertySidebarCell = memo(function PropertySidebarCell({
  row, rowH, nights,
}: {
  row: CalendarRow; rowH: number; nights: number;
}) {
  const booked = row.booked_nights ?? bookedIn(row.cells).booked;
  const held = row.held_nights ?? 0;
  const sub = booked || held
    ? `${[booked && `${booked} booked`, held && `${held} held by calendar`].filter(Boolean).join(", ")} · of ${nights}`
    : `All ${nights} nights free`;
  return (
    <div
      className="flex-shrink-0 flex flex-col justify-center gap-0.5 px-3.5 bg-[var(--haip-card)] border-r border-[var(--haip-border)] sticky left-0 z-20"
      style={{ width: SIDEBAR_W, height: rowH }}
      title={`${row.property_name} · ${row.property_type} · ${row.bedrooms} BR · up to ${row.max_adults} guests`}
    >
      <p className="truncate text-[13px] font-bold text-[var(--haip-fg)]">{row.property_name}</p>
      <p className="truncate text-[11px] text-[var(--haip-fg-subtle)]">{sub}</p>
    </div>
  );
});

function bookedIn(cells: Record<string, string>) {
  return { booked: Object.values(cells).filter(v => v === "confirmed" || v === "checked_in").length };
}

// ── BookingBar ─────────────────────────────────────────────────────────────────

const BookingBar = memo(function BookingBar({
  stay, days, onHover, onLeave, onOpen,
}: {
  stay: StayBar; days: string[];
  onHover: (stay: StayBar, e: React.MouseEvent) => void;
  onLeave: () => void;
  onOpen: (stay: StayBar) => void;
}) {
  if (!days.length) return null;
  const s = daysBetween(days[0], stay.check_in), e = daysBetween(days[0], stay.check_out);
  // A stay runs from the afternoon of check-in to the morning of check-out (as on the phone grid); a same-day stay still shows.
  const from = s === e ? s + 0.1 : s + 0.5, to = s === e ? s + 0.9 : e + 0.5;
  const a = Math.max(0, from), z = Math.min(days.length, to);
  if (z - a <= 0.05) return null;
  const clipL = from < 0, clipR = to > days.length;
  const due = moneyDue(stay);
  const tone = due ? DUE_TONE : chConfig(stay.channel_source);
  const name = cleanName(stay.guest_name) || "Guest";
  const n = e - s;
  const faded = stay.status === "cancelled" ? "opacity-25" : stay.status === "quoted" ? "opacity-55" : "";
  return (
    <div
      className={cn(
        "absolute flex items-center gap-1.5 overflow-hidden pl-1 pr-2.5 text-[12px] font-bold cursor-pointer select-none hover:brightness-105",
        tone.bg, tone.text, due ? DUE_TONE.edge : "shadow-[var(--haip-shadow-sm)]", faded,
        clipL ? "rounded-l-none" : "rounded-l-full", clipR ? "rounded-r-none" : "rounded-r-full",
      )}
      style={{ left: a * DAY_W + 1, width: (z - a) * DAY_W - 2, top: 12, height: 36, zIndex: 3 }}
      onMouseEnter={ev => onHover(stay, ev)}
      onMouseLeave={onLeave}
      role="button" tabIndex={0}
      aria-label={`${name}, ${stay.check_in} to ${stay.check_out}${due ? ", money still due" : ""}. Open details`}
      data-due={due ? "true" : undefined}
      onClick={() => { onLeave(); onOpen(stay); }}
      onKeyDown={ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onOpen(stay); } }}
    >
      {!clipL && (
        <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[rgb(255_255_255/0.22)] text-[11px]">
          {name.charAt(0).toUpperCase()}
        </span>
      )}
      <span className={cn("truncate", clipL && "pl-1.5")}>
        {name}{n > 0 ? ` · ${n} night${n === 1 ? "" : "s"}` : ""}{due ? " · due" : ""}
      </span>
    </div>
  );
});

// ── BlockBar ───────────────────────────────────────────────────────────────────

/** A hold: grey-green with a calendar icon when a Google Calendar event made it, red for maintenance; one bar for all its days. */
const BlockBar = memo(function BlockBar({ block, days, onOpen, waiting, unit }: {
  block: BlockBar; days: string[]; onOpen: (block: BlockBar) => void; waiting?: boolean; unit?: string;
}) {
  if (!days.length) return null;
  const s = daysBetween(days[0], block.blocked_from);
  const e = Math.max(daysBetween(days[0], block.blocked_to), s + 1);       // a one-day hold still shows
  const a = Math.max(0, s), z = Math.min(days.length, e);
  if (z <= a) return null;
  const tone = BLOCK_TONE(block.reason, waiting);
  const label = holdLabel(block);
  const span = e - s > 1 ? ` · ${nightsWord(block.blocked_from, block.blocked_to)}` : "";
  return (
    <button type="button" onClick={() => onOpen(block)}
      className={cn("absolute flex items-center gap-1.5 overflow-hidden whitespace-nowrap rounded-full px-2.5 text-[12px] font-bold hover:brightness-105",
        tone.bg, tone.text, waiting && "border")}
      style={{ left: a * DAY_W + 2, width: (z - a) * DAY_W - 4, top: 12, height: 36, zIndex: 2 }}
      aria-label={`${label}${block.event ? " (Google Calendar)" : ""}, ${block.blocked_from} to ${block.blocked_to}${waiting ? `, ${unit ?? "unit"} not chosen` : ""}. Open details`}
      title={`${label}${span}`}
    >
      {block.event && <Calendar size={12} aria-hidden className="shrink-0" />}
      <span className="min-w-0 flex-1 truncate text-left">{label}{span}</span>
      {waiting && z - a >= 3 && <span className="shrink-0 rounded-full bg-[var(--haip-card)] px-2 py-0.5 text-[11px]">Pick {unit}</span>}
    </button>
  );
});

/** The faint stripe a unit row gets on the days a "Which villa?" event might be its own. */
function WaitingStripes({ stripes, days, rowH }: { stripes: BlockBar[]; days: string[]; rowH: number }) {
  return (
    <>
      {stripes.map(b => {
        const a = Math.max(0, daysBetween(days[0], b.blocked_from)), z = Math.min(days.length, daysBetween(days[0], b.blocked_to));
        return z > a ? (
          <i key={b.id} aria-hidden className={cn("pointer-events-none absolute h-[5px] rounded-full", WAITING_STRIPE)}
            style={{ left: a * DAY_W + 4, width: (z - a) * DAY_W - 8, top: rowH - 10, zIndex: 1 }} />
        ) : null;
      })}
    </>
  );
}

// ── PropertyCalendarRow ────────────────────────────────────────────────────────

const PropertyCalendarRow = memo(function PropertyCalendarRow({
  row, days, mode, onHover, onLeave, onOpen, isEven, maxRate, stripes,
}: {
  row: CalendarRow; days: string[]; mode: CalendarMode; isEven: boolean; maxRate: number; stripes: BlockBar[];
  onHover: (stay: StayBar, e: React.MouseEvent) => void;
  onLeave: () => void;
  onOpen: (entry: Entry) => void;
}) {
  const rowH = ROW_H[mode];
  const today = format(new Date(), "yyyy-MM-dd");


  return (
    <div
      className={cn("flex border-b border-[var(--haip-border)]", isEven ? "bg-[var(--haip-card)]" : "bg-[var(--haip-surface)]/50")}
      style={{ height: rowH }}
    >
      {/* Sticky sidebar */}
      <PropertySidebarCell row={row} rowH={rowH} nights={days.length} />

      {/* Scrollable day area */}
      <div className="relative flex-1" style={{ minWidth: days.length * DAY_W }}>

        {mode === "availability" ? (
          /* ── Availability mode: one coloured cell per day ── */
          <div className="absolute inset-0 flex">
            {days.map(day => {
              const status  = row.cells[day] || "free";
              const todayDy = day === today;
              return (
                <div
                  key={day}
                  className={cn(
                    "flex-shrink-0 border-r border-white/60 h-full flex items-center justify-center",
                    AVAIL_BG[status] ?? "bg-[var(--haip-status-neutral-bg)]",
                    todayDy && "ring-1 ring-inset ring-primary",
                  )}
                  style={{ width: DAY_W }}
                  title={AVAIL_LABEL[status] ?? status}
                >
                  <span className="text-[8px] font-bold text-[var(--haip-fg-subtle)]/60 uppercase">
                    {status === "confirmed" || status === "checked_in" ? "●" : ""}
                  </span>
                </div>
              );
            })}
          </div>

        ) : mode === "revenue" ? (
          /* ── Revenue mode: rate heatmap ── */
          <div className="absolute inset-0 flex">
            {days.map(day => {
              const rate    = row.rates?.[day];
              const todayDy = day === today;
              const isBooked = ["confirmed","checked_in"].includes(row.cells[day] ?? "");
              return (
                <div
                  key={day}
                  className={cn(
                    "flex-shrink-0 h-full border-r border-[var(--haip-border)]/60 flex flex-col items-center justify-center gap-0.5",
                    isBooked ? revenueBg(rate, maxRate) : "bg-white",
                    todayDy && "ring-1 ring-inset ring-primary",
                  )}
                  style={{ width: DAY_W }}
                >
                  {rate && isBooked && (
                    <span className="text-[9px] font-bold text-emerald-700 tabular-nums leading-none">
                      {rate >= 1_000 ? `${(rate / 1000).toFixed(0)}k` : String(Math.round(rate))}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

        ) : (
          /* ── Bookings + Rates modes: booking bars ── */
          <>
            {/* Grid background */}
            <div className="absolute inset-0 flex pointer-events-none">
              {days.map(day => {
                const d       = parseISO(day);
                const weekend = d.getDay() === 0 || d.getDay() === 6;
                const todayDy = isToday(d);
                return (
                  <div
                    key={day}
                    className={cn(
                      "h-full border-r border-[var(--haip-border)] flex-shrink-0",
                      weekend && "bg-[var(--haip-surface)]/70",
                      todayDy && "bg-[var(--haip-accent-light)]",
                    )}
                    style={{ width: DAY_W }}
                  />
                );
              })}
            </div>

            <WaitingStripes stripes={stripes} days={days} rowH={rowH} />

            {/* Block bars (z-index 2) */}
            {row.blocks.map(block => (
              <BlockBar key={block.id} block={block} days={days} onOpen={b => onOpen({ kind: "block", block: b, propertyName: row.property_name })} />
            ))}

            {/* Booking bars (z-index 3) */}
            {row.stays.map(stay => (
              <BookingBar key={stay.id} stay={stay} days={days} onHover={onHover} onLeave={onLeave} onOpen={st => onOpen({ kind: "stay", stay: st, propertyName: row.property_name })} />
            ))}

            {/* Rate sub-row (Rates mode only) */}
            {mode === "rates" && (
              <div
                className="absolute left-0 right-0 bottom-0 flex border-t border-[var(--haip-border)]"
                style={{ height: RATE_H }}
              >
                {days.map(day => {
                  const rate = row.rates?.[day];
                  return (
                    <div
                      key={day}
                      className="flex-shrink-0 flex items-center justify-center border-r border-[var(--haip-border)]"
                      style={{ width: DAY_W }}
                    >
                      <span className="text-[9px] font-semibold tabular-nums text-[var(--haip-fg-subtle)]">
                        {fmtRate(rate)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
});

// ── CalendarHeader ─────────────────────────────────────────────────────────────

const WHICH_H = 58;   // px: the "Which villa?" row under the dates

const CalendarHeader = memo(function CalendarHeader({
  days, headerRef, mode, unitsLabel, which, whichLabel, unit, onOpenWhich, whichRef,
}: {
  days: string[]; headerRef: React.RefObject<HTMLDivElement | null>; mode: CalendarMode; unitsLabel: string;
  which: BlockBar[]; whichLabel: string; unit: string; onOpenWhich: (b: BlockBar) => void;
  whichRef: React.RefObject<HTMLDivElement | null>;
}) {
  const monthGroups = useMemo(() => {
    const groups: { label: string; count: number }[] = [];
    let cur = ""; let cnt = 0;
    for (const day of days) {
      const m = format(parseISO(day), "MMMM yyyy");
      if (m !== cur) { if (cur) groups.push({ label: cur, count: cnt }); cur = m; cnt = 1; }
      else cnt++;
    }
    if (cur) groups.push({ label: cur, count: cnt });
    return groups;
  }, [days]);
  const showWhich = mode !== "availability" && mode !== "revenue" && which.length > 0;

  return (
    <div className="flex flex-shrink-0 border-b border-[var(--haip-border)] sticky top-0 z-30 bg-[var(--haip-card)]">
      {/* Corner cells */}
      <div className="flex-shrink-0 sticky left-0 z-40 flex flex-col border-r border-[var(--haip-border)] bg-[var(--haip-card)]" style={{ width: SIDEBAR_W }}>
        <div className="flex items-end px-3.5 pb-1.5 text-[12px] font-bold text-[var(--haip-fg-2)]" style={{ height: 52 + (mode === "rates" ? RATE_H : 0) }}>
          {unitsLabel}
        </div>
        {showWhich && (
          <div ref={whichRef} className="flex flex-col justify-center gap-0.5 border-t border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3.5 text-[var(--haip-status-warning-fg)]" style={{ height: WHICH_H }}>
            <b className="text-[13px]">{whichLabel}</b>
            <Link href="/dashboard/my-day" className="text-[11px] underline">{which.length} event{which.length === 1 ? "" : "s"} · tasks on My day</Link>
          </div>
        )}
      </div>

      {/* Date columns — horizontally overflow-hidden (synced by JS) */}
      <div ref={headerRef} className="flex-1 overflow-x-hidden" style={{ minWidth: 0 }}>
        <div className="flex">
          {monthGroups.map(g => (
            <div key={g.label} className="flex-shrink-0 px-2 pt-1.5 text-[12px] font-bold text-[var(--haip-fg-2)] border-r border-[var(--haip-border)] last:border-0"
              style={{ width: g.count * DAY_W }}>
              {g.label}
            </div>
          ))}
        </div>
        <div className="flex">
          {days.map(day => {
            const d       = parseISO(day);
            const todayDy = isToday(d);
            const weekend = d.getDay() === 0 || d.getDay() === 6;
            return (
              <div key={day} className={cn("flex-shrink-0 flex flex-col items-center justify-end pb-1 border-r border-[var(--haip-border)]", weekend && "bg-[var(--haip-surface)]")}
                style={{ width: DAY_W, height: 30 }}>
                <span className="text-[9px] leading-none text-[var(--haip-fg-subtle)]">{format(d, "EEE")}</span>
                <span className={cn("mt-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-0.5 text-[11px] font-bold leading-none",
                  todayDy ? "bg-[var(--haip-accent)] text-[var(--haip-on-accent)]" : "text-[var(--haip-fg)]")}>
                  {format(d, "d")}
                </span>
              </div>
            );
          })}
        </div>
        {mode === "rates" && (
          <div className="flex border-t border-[var(--haip-border)]" style={{ height: RATE_H }}>
            {days.map(day => (
              <div key={day} className="flex-shrink-0 flex items-center justify-center border-r border-[var(--haip-border)]" style={{ width: DAY_W }}>
                <span className="text-[8px] font-bold text-[var(--haip-fg-subtle)] uppercase">₹</span>
              </div>
            ))}
          </div>
        )}
        {showWhich && (
          <div className="relative border-t border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)]/40" style={{ height: WHICH_H, width: days.length * DAY_W }}>
            {which.map(b => <BlockBar key={b.id} block={b} days={days} onOpen={onOpenWhich} waiting unit={unit} />)}
          </div>
        )}
      </div>
    </div>
  );
});

// ── Legend ─────────────────────────────────────────────────────────────────────

// Channel colours are shown only for channels that have a booking in view (a villa business with no OTA sees none).
const OTA_LEGEND_ITEMS = [
  { key: "airbnb",      dot: "bg-rose-500",    label: "Airbnb" },
  { key: "booking.com", dot: "bg-blue-600",    label: "Booking.com" },
  { key: "vrbo",        dot: "bg-purple-500",  label: "VRBO" },
  { key: "makemytrip",  dot: "bg-orange-500",  label: "MMT" },
  { key: "retalwise",   dot: "bg-indigo-500",  label: "RentalWise" },
];

function buildLegend(seg: Segment, channels: Set<string>) {
  return [
    { dot: "bg-[var(--haip-cal-direct)]", label: "Direct booking" },
    { dot: "bg-[var(--haip-cal-due-bg)] shadow-[inset_3px_0_0_var(--haip-cal-due-edge)]", label: "Money due" },
    ...OTA_LEGEND_ITEMS.filter(i => channels.has(i.key)),
    { dot: "bg-[var(--haip-cal-block)]", label: "From Google Calendar or blocked" },
    { dot: "bg-[var(--haip-cal-maint)]", label: "Maintenance" },
    { dot: WAITING_STRIPE, label: `${seg.whichUnit} (held on every ${seg.unit.one})` },
  ];
}

const MODE_TABS: { key: CalendarMode; icon: React.ReactNode; label: string }[] = [
  { key: "bookings",     icon: <Calendar size={12} />,    label: "Bookings"     },
  { key: "rates",        icon: <DollarSign size={12} />,  label: "Rates"        },
  { key: "availability", icon: <Eye size={12} />,         label: "Availability" },
  { key: "revenue",      icon: <BarChart2 size={12} />,   label: "Revenue"      },
];

const OTA_CHANNEL_OPTS = [
  { value: "airbnb",      label: "Airbnb"       },
  { value: "booking.com", label: "Booking.com"  },
  { value: "makemytrip",  label: "MMT"          },
  { value: "vrbo",        label: "VRBO"         },
  { value: "retalwise",   label: "RentalWise"   },
];

function buildChannelOpts(seg: Segment) {
  return [
    { value: "",       label: "All channels" },
    { value: "direct", label: "Direct"       },
    ...(seg.sections.calendar.channelFilter ? OTA_CHANNEL_OPTS : []),
  ];
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function PortfolioCalendarPage() {
  const { data: session } = useSession();
  const canBook = canCreateBookings(session?.user?.role);
  const seg = useSegment();
  const CHANNEL_OPTS = useMemo(() => buildChannelOpts(seg), [seg]);
  // Opens a few days before today so the coming bookings are in view, not the days of this month already gone
  const [startDate, setStartDate]     = useState<Date>(() => { const d = new Date(); d.setHours(0, 0, 0, 0); return addDays(d, -3); });
  const [viewWindow, setViewWindow]   = useState<ViewWindow>("30");
  const [mode, setMode]               = useState<CalendarMode>("bookings");
  const [search, setSearch]           = useState("");
  const [channelFilter, setChan]      = useState("");
  const [hovered, setHovered]         = useState<{ stay: StayBar; pos: { x: number; y: number } } | null>(null);
  const [opened, setOpened]           = useState<Entry | null>(null);
  const [fullscreen, setFullscreen]   = useState(false);
  // Phones get a month grid for one property (a 30-column timeline is unusable at 375px); tablets and up keep the timeline.
  const [isPhone, setIsPhone]         = useState(false);
  const [monthStart, setMonthStart]   = useState<Date>(() => startOfMonth(new Date()));
  const [propertyId, setPropertyId]   = useState("");
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const apply = () => setIsPhone(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  // My day's "Calendar clashes" link here with ?date=YYYY-MM-DD (and &property=<id>): open on that day and vehicle.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const day = q.get("date");
    if (day && /^\d{4}-\d{2}-\d{2}$/.test(day)) {
      const d = parseISO(day);
      if (!Number.isNaN(d.getTime())) {
        setStartDate(addDays(d, -3));
        setMonthStart(startOfMonth(d));
      }
    }
    const prop = q.get("property");
    if (prop) setPropertyId(prop);
  }, []);
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  const queryClient  = useQueryClient();
  const gridRef      = useRef<HTMLDivElement>(null);   // main scroll container (x + y)
  const headerRef    = useRef<HTMLDivElement>(null);   // header date columns (x sync)
  const whichRef     = useRef<HTMLDivElement>(null);   // the "Which villa?" row (summary card scrolls to it)

  // Date range
  // Phone: the six weeks of the shown month (starting on the Monday before the 1st); desktop: the chosen window.
  const gridStart = useMemo(() => startOfWeek(monthStart, { weekStartsOn: 1 }), [monthStart]);
  const numDays  = isPhone ? 42 : VIEW_DAYS[viewWindow];
  const rangeStart = isPhone ? gridStart : startDate;
  const fromDate = format(rangeStart, "yyyy-MM-dd");
  const toDate   = format(addDays(rangeStart, numDays), "yyyy-MM-dd");

  // Data
  const { data, isLoading, isError, refetch, isFetching } = useQuery<CalendarResponse>({
    queryKey: ["portfolio-calendar", fromDate, toDate],
    queryFn: () => api.get(`/calendar?from_date=${fromDate}&to_date=${toDate}`).then(r => r.data),
    staleTime: 2 * 60_000,
  });

  const syncMutation = useMutation({
    mutationFn: () => api.post("/calendar/sync-rentalwise", {}).then(r => r.data),
    onSuccess: () => {
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["portfolio-calendar"] }), 3000);
    },
  });

  const days  = data?.days ?? [];
  const stats = data?.stats;

  // Filtered properties
  const properties = useMemo(() => {
    if (!data?.properties) return [];
    let list = data.properties;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(p => p.property_name.toLowerCase().includes(q));
    }
    if (channelFilter) {
      list = list.filter(p =>
        p.channel_source?.toLowerCase() === channelFilter ||
        p.stays.some(s => s.channel_source?.toLowerCase() === channelFilter)
      );
    }
    return list;
  }, [data?.properties, search, channelFilter]);

  // "Which villa?" events once (not on every unit), each unit's own holds with back-to-back days merged into one bar.
  const split = useMemo(() => splitWaiting(properties), [properties]);
  const rows = split.rows;
  const waiting = split.waiting;
  const LEGEND = useMemo(() => buildLegend(seg, new Set(properties.flatMap(p => p.stays.map(s => (s.channel_source || "direct").toLowerCase())))), [seg, properties]);
  // Money still due on the bookings in view (null = amounts are hidden for this role).
  const due = useMemo(() => {
    if (stats?.revenue_restricted) return null;
    const owing = properties.flatMap(p => p.stays).filter(moneyDue);
    return { amount: owing.reduce((t, s) => t + (s.total_amount ?? 0) - (s.paid_amount ?? 0), 0), stays: owing.length };
  }, [properties, stats?.revenue_restricted]);

  // Phone grid shows one property at a time: the chosen one, else the first
  // "all" draws every vehicle on one grid (Ratha 1 and Ratha 2 side by side); otherwise the chosen one
  const showAll = propertyId === "all" || (propertyId === "" && rows.length > 1 && rows.length <= 4);
  const selected = useMemo(() => {
    if (showAll && rows.length > 0) {
      return {
        property_id: "all", property_name: seg.allUnits,
        stays: rows.flatMap(p => p.stays.map(s => ({ ...s, vehicle: p.property_name }))),
        blocks: rows.flatMap(p => p.blocks.map(b => ({ ...b, vehicle: p.property_name }))),
      };
    }
    return rows.find(p => p.property_id === propertyId) ?? rows[0];
  }, [showAll, rows, propertyId, seg.allUnits]);

  // Max rate (for revenue mode heatmap scale)
  const maxRate = useMemo(() =>
    properties.reduce((mx, p) => {
      const propMax = Object.values(p.rates ?? {}).reduce((m, r) => Math.max(m, r), 0);
      return Math.max(mx, propMax);
    }, 0),
  [properties]);

  // Virtual rows
  const rowH = ROW_H[mode];
  const { start, end, padTop, padBot } = useVirtualRows(gridRef, rows.length, rowH);

  // Sync horizontal scroll: grid body → header
  const handleGridScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    if (headerRef.current) headerRef.current.scrollLeft = e.currentTarget.scrollLeft;
  }, []);

  // Hover
  const handleHover  = useCallback((stay: StayBar, e: React.MouseEvent) =>
    setHovered({ stay, pos: { x: e.clientX, y: e.clientY } }), []);
  const handleLeave  = useCallback(() => setHovered(null), []);

  // Navigation
  const prevPeriod = useCallback(() => setStartDate(d => addDays(d, -numDays)), [numDays]);
  const nextPeriod = useCallback(() => setStartDate(d => addDays(d, numDays)), [numDays]);
  const goToToday  = useCallback(() => { setStartDate(new Date()); }, []);

  return (
    <div
      className={cn("flex flex-col overflow-hidden bg-[var(--haip-card)]", fullscreen ? "fixed inset-0 z-[70]" : "h-full")}
      style={fullscreen ? { paddingTop: "env(safe-area-inset-top)", paddingBottom: "env(safe-area-inset-bottom)" } : undefined}
    >

      {/* ── Top summary bar ──────────────────────────────────── */}
      {stats && days.length > 0 && !isPhone && (
        <CalendarStats stats={stats} from={days[0]} lastDay={days[days.length - 1]} seg={seg} due={due}
          onWaiting={() => { if (mode !== "bookings" && mode !== "rates") setMode("bookings"); whichRef.current?.scrollIntoView({ block: "nearest" }); }} />
      )}

      {/* ── Controls ─────────────────────────────────────────── */}
      <div className="flex-shrink-0 bg-[var(--haip-card)] border-b border-[var(--haip-border)] px-3 py-2 md:px-4 md:py-2.5 space-y-2">
        {/* Phone: month navigation + property + channel in two short rows */}
        {isPhone && (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <button onClick={() => setMonthStart(m => addMonths(m, -1))} aria-label="Previous month"
                className="flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-2)] active:bg-[var(--haip-border)]"><ChevronLeft size={18} /></button>
              <h2 className="min-w-0 flex-1 text-center text-base font-bold text-[var(--haip-fg)]" aria-live="polite">{format(monthStart, "MMMM yyyy")}</h2>
              <button onClick={() => setMonthStart(m => addMonths(m, 1))} aria-label="Next month"
                className="flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-2)] active:bg-[var(--haip-border)]"><ChevronRight size={18} /></button>
              <button onClick={() => setMonthStart(startOfMonth(new Date()))}
                className="h-11 rounded-xl bg-[var(--haip-status-neutral-bg)] px-3 text-xs font-semibold text-[var(--haip-fg-2)] active:bg-[var(--haip-border)]">Today</button>
              <button onClick={() => refetch()} aria-label="Refresh" className="flex h-11 w-11 items-center justify-center rounded-xl text-[var(--haip-fg-subtle)] active:bg-[var(--haip-status-neutral-bg)]">
                <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
              </button>
            </div>
            <div className="flex items-center gap-1.5">
              <select value={showAll ? "all" : (selected?.property_id ?? "")} onChange={e => setPropertyId(e.target.value)} aria-label="Property"
                className="min-h-11 min-w-0 flex-1 rounded-xl border border-[var(--haip-border)] bg-white px-2 text-base text-[var(--haip-fg)] outline-none focus:ring-2 focus:ring-primary">
                {rows.length === 0 && <option value="">No {seg.unit.many}</option>}
                {rows.length > 1 && <option value="all">{seg.allUnits}</option>}
                {rows.map(p => <option key={p.property_id} value={p.property_id}>{p.property_name}</option>)}
              </select>
              {canBook && (
                <Link href={!showAll && selected?.property_id ? `/dashboard/bookings/new?property=${selected.property_id}` : "/dashboard/bookings/new"}
                  className="flex h-11 shrink-0 items-center rounded-xl bg-primary px-3 text-xs font-semibold text-primary-foreground">New booking</Link>
              )}
              {seg.sections.calendar.channelFilter && (
                <select value={channelFilter} onChange={e => setChan(e.target.value)} aria-label="Channel"
                  className="min-h-11 w-32 rounded-xl border border-[var(--haip-border)] bg-white px-2 text-base text-[var(--haip-fg-2)] outline-none focus:ring-2 focus:ring-primary">
                  {CHANNEL_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              )}
            </div>
          </div>
        )}
        <div className={cn("flex items-center gap-2 flex-wrap", isPhone && "hidden")}>

          {/* Mode tabs (timeline only: the phone agenda has nothing to switch) */}
          <div className="hidden md:flex items-center bg-[var(--haip-status-neutral-bg)] rounded-xl p-0.5">
            {MODE_TABS.map(t => (
              <button
                key={t.key}
                onClick={() => setMode(t.key)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all",
                  mode === t.key ? "bg-white text-primary shadow-sm" : "text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-2)]",
                )}
              >
                {t.icon}{t.label}
              </button>
            ))}
          </div>

          {/* Date nav */}
          <div className="flex items-center gap-0.5 bg-[var(--haip-status-neutral-bg)] rounded-xl p-0.5">
            <button
              onClick={prevPeriod}
              title={`Previous ${numDays} days`}
              aria-label={`Previous ${numDays} days`}
              className="flex items-center gap-1 px-2 min-h-11 md:min-h-0 md:h-7 rounded-lg hover:bg-white text-[var(--haip-fg-muted)] text-[11px] font-medium"
            >
              <ChevronLeft size={14} /> Past
            </button>
            <button onClick={goToToday} className="px-3 min-h-11 md:min-h-0 md:py-1 text-xs font-semibold text-[var(--haip-fg-2)] hover:bg-white rounded-lg">
              Today
            </button>
            <button
              onClick={nextPeriod}
              title={`Next ${numDays} days`}
              aria-label={`Next ${numDays} days`}
              className="flex items-center gap-1 px-2 min-h-11 md:min-h-0 md:h-7 rounded-lg hover:bg-white text-[var(--haip-fg-muted)] text-[11px] font-medium"
            >
              Future <ChevronRight size={14} />
            </button>
          </div>

          <span className="text-sm font-bold text-[var(--haip-fg-2)] min-w-[130px]">
            {format(startDate, "dd MMM")} – {format(addDays(startDate, numDays - 1), "dd MMM yyyy")}
          </span>

          {/* Window */}
          <div className="hidden md:flex items-center gap-0.5 bg-[var(--haip-status-neutral-bg)] rounded-xl p-0.5">
            {(["14","30","60","90"] as ViewWindow[]).map(v => (
              <button
                key={v}
                onClick={() => setViewWindow(v)}
                className={cn(
                  "px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors",
                  viewWindow === v ? "bg-white text-primary shadow-sm" : "text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-2)]",
                )}
              >
                {v}d
              </button>
            ))}
          </div>

          {/* Channel filter */}
          {seg.sections.calendar.channelFilter && <select
            value={channelFilter}
            onChange={e => setChan(e.target.value)}
            className="text-base md:text-xs border border-[var(--haip-border)] rounded-xl px-2 min-h-11 md:min-h-0 md:py-1.5 bg-white text-[var(--haip-fg-2)] outline-none focus:ring-2 focus:ring-primary cursor-pointer"
          >
            {CHANNEL_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>}

          {/* Search -- not useful for caravan tenants, who run a small enough
              fleet that scanning the row list directly is easier than typing */}
          {seg.key !== "caravan" && (
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={`Search ${seg.unit.many}…`}
              className="text-base md:text-xs border border-[var(--haip-border)] rounded-xl px-3 min-h-11 md:min-h-0 md:py-1.5 outline-none focus:ring-2 focus:ring-primary w-full md:w-36"
            />
          )}

          <div className="flex-1" />

          {/* Sync -- RentalWise-only, no PMS/channel sync exists for caravan tenants */}
          {seg.sections.calendar.rentalwiseSync && (
            <>
              {syncMutation.isSuccess && (
                <span className="flex items-center gap-1 text-xs text-green-600 bg-green-50 px-2 py-1 rounded-xl">
                  <CheckCircle2 size={11} /> Synced
                </span>
              )}
              {syncMutation.isError && (
                <span className="flex items-center gap-1 text-xs text-red-600 bg-red-50 px-2 py-1 rounded-xl">
                  <AlertCircle size={11} /> Failed
                </span>
              )}
              <button
                onClick={() => syncMutation.mutate()}
                disabled={syncMutation.isPending}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors",
                  syncMutation.isPending ? "bg-indigo-100 text-indigo-400 cursor-not-allowed" : "bg-indigo-50 text-indigo-600 hover:bg-indigo-100",
                )}
              >
                <CloudDownload size={12} className={syncMutation.isPending ? "animate-pulse" : ""} />
                RW Sync
              </button>
            </>
          )}
          {canBook && (
            <Link href="/dashboard/bookings/new" className="flex min-h-11 md:min-h-8 items-center rounded-xl bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-[var(--haip-primary-hover)]">
              New booking
            </Link>
          )}
          <button onClick={() => refetch()} aria-label="Refresh" className="w-11 h-11 md:w-8 md:h-8 flex items-center justify-center rounded-xl hover:bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-subtle)]">
            <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
          </button>
          <button
            onClick={() => setFullscreen(f => !f)} aria-pressed={fullscreen}
            className="min-h-11 md:min-h-8 px-3 rounded-xl text-xs font-semibold text-[var(--haip-fg-muted)] bg-[var(--haip-status-neutral-bg)] hover:bg-[var(--haip-border)]"
          >
            {fullscreen ? "Exit full screen" : "Full screen"}
          </button>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 flex-wrap">
          {LEGEND.map(l => (
            <div key={l.label} className="flex items-center gap-1">
              <div className={cn("h-2.5 w-[18px] rounded-full", l.dot)} />
              <span className="text-[11px] text-[var(--haip-fg-2)]">{l.label}</span>
            </div>
          ))}
          {!isPhone && (
            <span className="text-[10px] text-[var(--haip-fg-subtle)] ml-auto tabular-nums">
              A {seg.booking.one} runs from the afternoon of {seg.start} to the morning of {seg.end} · {rows.length} {rows.length === 1 ? seg.unit.one : seg.unit.many}
            </span>
          )}
        </div>
      </div>

      {/* ── Calendar grid ─────────────────────────────────────── */}
      {isError ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-sm font-semibold text-red-500">Failed to load calendar</p>
            <button onClick={() => refetch()} className="mt-2 text-sm text-primary hover:underline">Try again</button>
          </div>
        </div>
      ) : isPhone ? (
        <div className="flex-1 overflow-y-auto overscroll-contain">
          {isLoading ? (
            <div className="space-y-2 p-4">{[0, 1, 2].map(i => <div key={i} className="h-14 animate-pulse rounded-xl bg-[var(--haip-status-neutral-bg)]" />)}</div>
          ) : !selected ? (
            <p className="px-4 py-10 text-center text-sm text-[var(--haip-fg-subtle)]">
              {search || channelFilter ? `No ${seg.unit.one} matches this channel. Choose “All channels”.` : `No ${seg.unit.many} yet. Add them in Portfolio settings.`}
            </p>
          ) : (
            <>
            {waiting.length > 0 && (
              <div className="mx-3 mt-2 rounded-2xl border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] p-3 text-[var(--haip-status-warning-fg)]">
                <p className="text-[13px] leading-snug"><b>{seg.whichUnit} {waiting.length} Google Calendar event{waiting.length === 1 ? "" : "s"}</b><br />
                  Held on every {seg.unit.one} until you pick one (striped days). Tap one to pick.</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {waiting.map(b => (
                    <button key={b.id} type="button" onClick={() => setOpened({ kind: "block", block: b, propertyName: seg.whichUnit })}
                      className="min-h-11 rounded-full bg-[var(--haip-card)] px-3 text-[12.5px] font-semibold">
                      {holdLabel(b)} · {format(parseISO(b.blocked_from), "d MMM")}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <MonthGrid
              stripes={waiting}
              legend={`Green = direct booking · terracotta = money due · grey-green = from Google Calendar · red = maintenance. A ${seg.booking.one} runs from the afternoon of ${seg.start} to the morning of ${seg.end}.`}
              row={selected} monthStart={monthStart} gridStart={gridStart} onOpen={setOpened}
              chColor={src => { const c = chConfig(src); return { bg: c.bg, text: c.text }; }}
              channelLabel={src => chConfig(src).label}
            />
            </>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-hidden flex flex-col">
          {/* Sticky header */}
          <CalendarHeader days={days} headerRef={headerRef} mode={mode} unitsLabel={`${rows.length} ${rows.length === 1 ? seg.unit.one : seg.unit.many}`}
            which={waiting} whichLabel={seg.whichUnit} unit={seg.unit.one} whichRef={whichRef}
            onOpenWhich={b => setOpened({ kind: "block", block: b, propertyName: seg.whichUnit })} />

          {/* Scrollable body */}
          <div
            ref={gridRef}
            className="flex-1 overflow-auto haip-scrollbar"
            onScroll={handleGridScroll}
          >
            {isLoading ? (
              <div>
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="flex border-b border-[var(--haip-border)] animate-pulse" style={{ height: rowH }}>
                    <div className="flex-shrink-0 bg-[var(--haip-status-neutral-bg)] border-r border-[var(--haip-border)]" style={{ width: SIDEBAR_W }} />
                    <div className="flex-1 bg-[var(--haip-surface)]" />
                  </div>
                ))}
              </div>
            ) : rows.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 text-center">
                <Bed size={40} className="text-[var(--haip-fg-subtle)]/70 mb-4" />
                <p className="text-[var(--haip-fg-subtle)] font-semibold">No {seg.unit.many} found</p>
                <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">
                  {search || channelFilter ? `Clear your filters to see all ${seg.unit.many}` : `Add ${seg.unit.many} in Portfolio settings`}
                </p>
              </div>
            ) : (
              <div
                style={{
                  minWidth: SIDEBAR_W + days.length * DAY_W,
                  paddingTop: padTop,
                }}
              >
                {rows.slice(start, end + 1).map((row, relIdx) => (
                  <PropertyCalendarRow
                    key={row.property_id}
                    row={row}
                    days={days}
                    mode={mode}
                    onHover={handleHover}
                    onLeave={handleLeave}
                    onOpen={setOpened}
                    isEven={(start + relIdx) % 2 === 0}
                    maxRate={maxRate}
                    stripes={waiting}
                  />
                ))}
                <div style={{ height: padBot }} />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Hover card (fixed portal — escapes overflow containers) */}
      {hovered && <HoverCard stay={hovered.stay} pos={hovered.pos} />}

      {/* Tap or click an entry: details, plus the booking and the lead it came from */}
      <EntrySheet entry={opened} onClose={() => setOpened(null)} channelLabel={src => chConfig(src).label} />
    </div>
  );
}
