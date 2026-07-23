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
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { addDays, format, parseISO, isToday } from "date-fns";
import {
  ChevronLeft, ChevronRight, Calendar, Bed, Users, TrendingUp,
  RefreshCw, CloudDownload, CheckCircle2, AlertCircle,
  LogIn, LogOut, Home, DollarSign, BarChart2, Eye, Phone, Hash,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useBusinessType } from "@/components/providers/WorkspaceProvider";

// ── Constants ─────────────────────────────────────────────────────────────────

const SIDEBAR_W = 224;   // px — sticky property sidebar column

const DAY_W     = 40;    // px — each day column

const RATE_H    = 26;    // px — nightly-rate sub-row height (Rates mode)

const ROW_H: Record<CalendarMode, number> = {
  bookings:     88,
  rates:        88 + RATE_H + 1,
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
  direct:         { bg:"bg-emerald-500", text:"text-white", border:"border-emerald-600", dot:"bg-emerald-400", label:"Direct",       short:"DIR" },
  makemytrip:     { bg:"bg-orange-500",  text:"text-white", border:"border-orange-600",  dot:"bg-orange-400",  label:"MMT",          short:"MMT" },
  vrbo:           { bg:"bg-purple-500",  text:"text-white", border:"border-purple-600",  dot:"bg-purple-400",  label:"VRBO",         short:"VBO" },
  expedia:        { bg:"bg-yellow-500",  text:"text-white", border:"border-yellow-600",  dot:"bg-yellow-400",  label:"Expedia",      short:"EXP" },
  hostaway:       { bg:"bg-violet-500",  text:"text-white", border:"border-violet-600",  dot:"bg-violet-400",  label:"Hostaway",     short:"HA"  },
  retalwise:      { bg:"bg-indigo-500",  text:"text-white", border:"border-indigo-600",  dot:"bg-indigo-400",  label:"RentalWise",   short:"RW"  },
};
const CH_DEFAULT: ChConfig = { bg:"bg-gray-500", text:"text-white", border:"border-gray-600", dot:"bg-gray-400", label:"Other",       short:"OTH" };
const CH_BLOCKED: ChConfig = { bg:"bg-gray-300", text:"text-gray-700", border:"border-gray-400", dot:"bg-gray-300", label:"Blocked", short:"BLK" };
const CH_MAINT:   ChConfig = { bg:"bg-red-200",  text:"text-red-700",  border:"border-red-300",  dot:"bg-red-200",  label:"Maint.",  short:"MNT" };

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
  blocked:         "bg-gray-300",
  maintenance:     "bg-red-200",
  owner_use:       "bg-amber-200",
  offline_booking: "bg-slate-300",
  other:           "bg-gray-200",
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
  paid_amount?: number | null;
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
  image_url?: string;
  channel_source?: string;
  monthly_revenue?: number;
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

// ── TopSummaryBar ──────────────────────────────────────────────────────────────

const TopSummaryBar = memo(function TopSummaryBar({
  revenue, occupancy, checkIns, checkOuts, vacant, totalProps,
}: {
  revenue: number; occupancy: number; checkIns: number;
  checkOuts: number; vacant: number; totalProps: number;
}) {
  const chips = [
    {
      icon: <DollarSign size={13} />,
      label: "Portfolio Revenue",
      value: fmtK(revenue),
      cls: "text-emerald-700 bg-emerald-50 ring-emerald-200",
    },
    {
      icon: <TrendingUp size={13} />,
      label: "Occupancy",
      value: `${occupancy}%`,
      cls: occupancy >= 70 ? "text-green-700 bg-green-50 ring-green-200"
         : occupancy >= 40 ? "text-amber-700 bg-amber-50 ring-amber-200"
                           : "text-red-700 bg-red-50 ring-red-200",
    },
    {
      icon: <LogIn size={13} />,
      label: "Check-ins",
      value: String(checkIns),
      cls: "text-sky-700 bg-sky-50 ring-sky-200",
    },
    {
      icon: <LogOut size={13} />,
      label: "Check-outs",
      value: String(checkOuts),
      cls: "text-orange-700 bg-orange-50 ring-orange-200",
    },
    {
      icon: <Home size={13} />,
      label: "Vacant",
      value: `${vacant}/${totalProps}`,
      cls: "text-gray-600 bg-gray-50 ring-gray-200",
    },
  ];

  return (
    <div className="flex items-center gap-2.5 px-4 py-2 bg-white border-b border-gray-100 flex-wrap">
      {chips.map(c => (
        <div key={c.label} className={cn("flex items-center gap-1.5 px-3 py-1.5 rounded-xl ring-1 text-xs font-semibold", c.cls)}>
          {c.icon}
          <span className="font-normal opacity-70">{c.label}</span>
          <span className="tabular-nums font-bold">{c.value}</span>
        </div>
      ))}
    </div>
  );
});

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
      className="fixed z-[9999] w-[252px] rounded-2xl shadow-2xl overflow-hidden pointer-events-none border border-gray-100"
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
          <div className="flex items-center gap-2 text-gray-600">
            <Phone size={11} className="text-gray-400 shrink-0" />
            <span className="tabular-nums">{stay.guest_phone}</span>
          </div>
        )}
        {stay.external_id && (
          <div className="flex items-center gap-2 text-gray-600">
            <Hash size={11} className="text-gray-400 shrink-0" />
            <span className="font-mono text-[11px]">{stay.external_id}</span>
          </div>
        )}

        {/* Dates */}
        <div className="flex items-center justify-between pt-1.5 border-t border-gray-100">
          <div>
            <p className="text-[9px] text-gray-400 uppercase tracking-wide">Check-in</p>
            <p className="font-semibold text-gray-800">{stay.check_in}</p>
          </div>
          <span className="text-gray-300 text-base">→</span>
          <div className="text-right">
            <p className="text-[9px] text-gray-400 uppercase tracking-wide">Check-out</p>
            <p className="font-semibold text-gray-800">{stay.check_out}</p>
          </div>
        </div>
        <p className="text-[10px] text-gray-400 text-center -mt-1">
          {nights} night{nights !== 1 ? "s" : ""}
        </p>

        {/* Financials */}
        <div className="pt-1.5 border-t border-gray-100 space-y-1.5">
          <div className="flex justify-between">
            <span className="text-gray-500">Total amount</span>
            <span className="font-bold text-gray-900">{fmt(stay.total_amount)}</span>
          </div>
          {stay.paid_amount != null && (
            <div className="flex justify-between">
              <span className="text-gray-500">Paid</span>
              <span className="font-semibold text-emerald-600">{fmt(stay.paid_amount)}</span>
            </div>
          )}
          {stay.paid_amount != null && stay.total_amount != null && (
            <div className="flex justify-between">
              <span className="text-gray-500">Outstanding</span>
              <span className={cn("font-semibold", outstanding > 0 ? "text-red-500" : "text-gray-400")}>
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
              : "bg-gray-100 text-gray-600",
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

const PROP_TYPE_ICON: Record<string, string> = {
  hotel: "🏨", resort: "🏖️", caravan: "🚌", villa: "🏡",
  rental_apartment: "🏢", travel: "✈️",
};

const PropertySidebarCell = memo(function PropertySidebarCell({
  row, rowH, occupancyPct,
}: {
  row: CalendarRow; rowH: number; occupancyPct: number;
}) {
  const typeIcon = PROP_TYPE_ICON[row.property_type] ?? "🏡";
  const rev = row.monthly_revenue;

  return (
    <div
      className="flex-shrink-0 flex items-center gap-2.5 px-2.5 bg-white border-r border-gray-200 sticky left-0 z-20"
      style={{ width: SIDEBAR_W, height: rowH }}
    >
      {/* Thumbnail */}
      <div className="flex-shrink-0 w-10 h-10 rounded-xl overflow-hidden bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center shadow-sm">
        {row.image_url ? (
          <img src={row.image_url} alt={row.property_name} className="w-full h-full object-cover" loading="lazy" />
        ) : (
          <span className="text-lg leading-none">{typeIcon}</span>
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="text-[12px] font-bold text-gray-900 truncate leading-tight">
          {row.property_name}
        </p>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className="text-[10px] text-gray-400 flex items-center gap-0.5 capitalize">
            {row.property_type}
          </span>
          <span className="text-gray-200">·</span>
          <span className="text-[10px] text-gray-400 flex items-center gap-0.5">
            <Bed size={9} className="inline" />{row.bedrooms}BR
          </span>
          <span className="text-[10px] text-gray-400 flex items-center gap-0.5">
            <Users size={9} className="inline" />{row.max_adults}
          </span>
        </div>

        {/* Occupancy bar */}
        <div className="mt-1.5 flex items-center gap-1.5">
          <div className="flex-1 h-1 bg-gray-100 rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                occupancyPct >= 80 ? "bg-emerald-400" : occupancyPct >= 50 ? "bg-amber-400" : "bg-red-400",
              )}
              style={{ width: `${Math.min(100, occupancyPct)}%` }}
            />
          </div>
          <span className={cn(
            "text-[10px] font-bold tabular-nums",
            occupancyPct >= 80 ? "text-emerald-600" : occupancyPct >= 50 ? "text-amber-600" : "text-red-500",
          )}>
            {occupancyPct}%
          </span>
        </div>

        {rev != null && rev > 0 && (
          <p className="text-[10px] text-gray-500 tabular-nums mt-0.5">{fmtK(rev)}</p>
        )}
      </div>
    </div>
  );
});

// ── BookingBar ─────────────────────────────────────────────────────────────────

const BookingBar = memo(function BookingBar({
  stay, days, onHover, onLeave,
}: {
  stay: StayBar; days: string[];
  onHover: (stay: StayBar, e: React.MouseEvent) => void;
  onLeave: () => void;
}) {
  if (!days.length) return null;
  const winStart = days[0];
  const winEnd   = days[days.length - 1];
  if (stay.check_out <= winStart || stay.check_in > winEnd) return null;

  const rawStart = days.indexOf(stay.check_in);
  const startIdx = Math.max(rawStart, 0);
  const clipped  = rawStart < 0;          // stay starts before window
  const rawEnd   = days.indexOf(stay.check_out);
  const spanDays = rawEnd >= 0 ? rawEnd - startIdx : days.length - startIdx;
  if (spanDays <= 0) return null;

  const cc = chConfig(stay.channel_source);
  const faded = stay.status === "cancelled" ? "opacity-25"
              : stay.status === "quoted"    ? "opacity-55"
              : "";

  return (
    <div
      className={cn(
        "absolute flex items-center cursor-pointer select-none",
        "rounded-xl border overflow-hidden",
        "transition-all duration-100 hover:brightness-105 hover:shadow-md",
        cc.bg, cc.text, cc.border, faded,
      )}
      style={{
        left:   startIdx * DAY_W + (clipped ? 0 : 3),
        width:  spanDays * DAY_W - (clipped ? 0 : 6),
        top:    8,
        height: 46,
        zIndex: 3,
        borderRadius: clipped ? "0 12px 12px 0" : undefined,
      }}
      onMouseEnter={e => onHover(stay, e)}
      onMouseLeave={onLeave}
    >
      {/* Content */}
      <div className="flex-1 min-w-0 px-2.5 flex items-center justify-between gap-1">
        {spanDays >= 3 ? (
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-bold leading-none truncate">
              {stay.guest_name || "Guest"}
            </p>
            {spanDays >= 4 && (
              <div className="flex items-center gap-2 mt-1">
                {stay.adults > 0 && (
                  <span className="text-[9px] opacity-80 flex items-center gap-0.5">
                    <Users size={8} />{stay.adults}
                  </span>
                )}
                {stay.total_amount && (
                  <span className="text-[9px] font-extrabold opacity-90 tabular-nums">
                    {fmtK(stay.total_amount)}
                  </span>
                )}
              </div>
            )}
          </div>
        ) : spanDays === 2 ? (
          <p className="text-[10px] font-bold truncate">
            {(stay.guest_name || "Guest").split(" ")[0]}
          </p>
        ) : (
          <p className="text-[9px] font-extrabold">
            {(stay.guest_name || "?")[0]}
          </p>
        )}

        {/* Source badge */}
        {spanDays >= 5 && (
          <span className="flex-shrink-0 text-[8px] font-extrabold px-1.5 py-0.5 rounded-md bg-white/25 leading-none">
            {cc.short}
          </span>
        )}
      </div>
    </div>
  );
});

// ── BlockBar ───────────────────────────────────────────────────────────────────

const BLOCK_CLS: Record<string, string> = {
  maintenance:      "bg-red-100 border-red-300 text-red-600",
  personal:         "bg-amber-100 border-amber-300 text-amber-700",
  owner_use:        "bg-amber-100 border-amber-300 text-amber-700",
  offline_booking:  "bg-slate-200 border-slate-300 text-slate-600",
  other:            "bg-gray-200 border-gray-300 text-gray-600",
};

const BlockBar = memo(function BlockBar({ block, days }: { block: BlockBar; days: string[] }) {
  const winStart = days[0];
  const winEnd   = days[days.length - 1];
  if (block.blocked_to <= winStart || block.blocked_from > winEnd) return null;

  const startIdx = Math.max(days.indexOf(block.blocked_from), 0);
  const rawEnd   = days.indexOf(block.blocked_to);
  const spanDays = rawEnd >= 0 ? rawEnd - startIdx : days.length - startIdx;
  if (spanDays <= 0) return null;

  const cls = BLOCK_CLS[block.reason] ?? BLOCK_CLS.other;

  return (
    <div
      className={cn("absolute rounded-md border flex items-center overflow-hidden select-none", cls)}
      style={{ left: startIdx * DAY_W + 2, width: spanDays * DAY_W - 4, top: 8, height: 38, zIndex: 2 }}
      title={block.notes || block.reason}
    >
      <span className="px-2 text-[9px] font-bold uppercase tracking-wide truncate">
        {block.reason.replace(/_/g, " ")}
      </span>
    </div>
  );
});

// ── PropertyCalendarRow ────────────────────────────────────────────────────────

const PropertyCalendarRow = memo(function PropertyCalendarRow({
  row, days, mode, onHover, onLeave, isEven, maxRate,
}: {
  row: CalendarRow; days: string[]; mode: CalendarMode; isEven: boolean; maxRate: number;
  onHover: (stay: StayBar, e: React.MouseEvent) => void;
  onLeave: () => void;
}) {
  const rowH = ROW_H[mode];
  const today = format(new Date(), "yyyy-MM-dd");

  const confirmedDays = useMemo(
    () => days.filter(d => ["confirmed","checked_in"].includes(row.cells[d] ?? "")).length,
    [days, row.cells],
  );
  const occupancyPct = days.length > 0 ? Math.round((confirmedDays / days.length) * 100) : 0;

  return (
    <div
      className={cn("flex border-b border-gray-100", isEven ? "bg-white" : "bg-gray-50/50")}
      style={{ height: rowH }}
    >
      {/* Sticky sidebar */}
      <PropertySidebarCell row={row} rowH={rowH} occupancyPct={occupancyPct} />

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
                    AVAIL_BG[status] ?? "bg-gray-100",
                    todayDy && "ring-1 ring-inset ring-teal-400",
                  )}
                  style={{ width: DAY_W }}
                  title={AVAIL_LABEL[status] ?? status}
                >
                  <span className="text-[8px] font-bold text-gray-500/60 uppercase">
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
                    "flex-shrink-0 h-full border-r border-gray-100/60 flex flex-col items-center justify-center gap-0.5",
                    isBooked ? revenueBg(rate, maxRate) : "bg-white",
                    todayDy && "ring-1 ring-inset ring-teal-400",
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
                      "h-full border-r border-gray-100 flex-shrink-0",
                      weekend && "bg-gray-50/70",
                      todayDy && "bg-teal-50/50",
                    )}
                    style={{ width: DAY_W }}
                  />
                );
              })}
            </div>

            {/* Block bars (z-index 2) */}
            {row.blocks.map(block => (
              <BlockBar key={block.id} block={block} days={days} />
            ))}

            {/* Booking bars (z-index 3) */}
            {row.stays.map(stay => (
              <BookingBar key={stay.id} stay={stay} days={days} onHover={onHover} onLeave={onLeave} />
            ))}

            {/* Rate sub-row (Rates mode only) */}
            {mode === "rates" && (
              <div
                className="absolute left-0 right-0 bottom-0 flex border-t border-gray-100"
                style={{ height: RATE_H }}
              >
                {days.map(day => {
                  const rate = row.rates?.[day];
                  return (
                    <div
                      key={day}
                      className="flex-shrink-0 flex items-center justify-center border-r border-gray-100"
                      style={{ width: DAY_W }}
                    >
                      <span className="text-[9px] font-semibold tabular-nums text-gray-500">
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

const CalendarHeader = memo(function CalendarHeader({
  days, headerRef, mode,
}: {
  days: string[]; headerRef: React.RefObject<HTMLDivElement | null>; mode: CalendarMode;
}) {
  const monthGroups = useMemo(() => {
    const groups: { label: string; count: number }[] = [];
    let cur = ""; let cnt = 0;
    for (const day of days) {
      const m = format(parseISO(day), "MMM yyyy");
      if (m !== cur) { if (cur) groups.push({ label: cur, count: cnt }); cur = m; cnt = 1; }
      else cnt++;
    }
    if (cur) groups.push({ label: cur, count: cnt });
    return groups;
  }, [days]);

  return (
    <div className="flex flex-shrink-0 border-b border-gray-200 shadow-sm sticky top-0 z-30 bg-white">
      {/* Corner cell */}
      <div
        className="flex-shrink-0 sticky left-0 z-40 bg-white border-r border-gray-200 flex items-end pb-1 px-3"
        style={{ width: SIDEBAR_W, height: 52 }}
      >
        <span className="text-[10px] font-extrabold text-gray-400 uppercase tracking-wider">
          Properties
        </span>
      </div>

      {/* Date columns — horizontally overflow-hidden (synced by JS) */}
      <div ref={headerRef} className="flex-1 overflow-x-hidden" style={{ minWidth: 0 }}>
        {/* Month labels */}
        <div className="flex">
          {monthGroups.map(g => (
            <div
              key={g.label}
              className="flex-shrink-0 text-[10px] font-extrabold text-gray-500 uppercase tracking-wider px-2 pt-1.5 border-r border-gray-100 last:border-0"
              style={{ width: g.count * DAY_W }}
            >
              {g.label}
            </div>
          ))}
        </div>
        {/* Day numbers */}
        <div className="flex">
          {days.map(day => {
            const d       = parseISO(day);
            const todayDy = isToday(d);
            const weekend = d.getDay() === 0 || d.getDay() === 6;
            return (
              <div
                key={day}
                className={cn(
                  "flex-shrink-0 flex flex-col items-center justify-end pb-1 border-r border-gray-100",
                  weekend && "bg-gray-50",
                  todayDy && "bg-teal-50",
                )}
                style={{ width: DAY_W, height: 30 }}
              >
                <span className={cn(
                  "text-[10px] font-semibold leading-none",
                  todayDy
                    ? "bg-teal-500 text-white rounded-full w-4 h-4 flex items-center justify-center"
                    : weekend ? "text-gray-400" : "text-gray-500",
                )}>
                  {format(d, "d")}
                </span>
                <span className="text-[7px] text-gray-300 mt-0.5 leading-none uppercase">
                  {format(d, "EEE")[0]}
                </span>
              </div>
            );
          })}
        </div>
        {/* Rate header row — only in rates mode */}
        {mode === "rates" && (
          <div
            className="flex border-t border-gray-100"
            style={{ height: RATE_H }}
          >
            {days.map(day => (
              <div
                key={day}
                className="flex-shrink-0 flex items-center justify-center border-r border-gray-100"
                style={{ width: DAY_W }}
              >
                <span className="text-[8px] font-bold text-gray-400 uppercase">₹</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
});

// ── Legend ─────────────────────────────────────────────────────────────────────

// Caravan tenants have no OTA/PMS channel integrations (no Airbnb, Booking.com,
// VRBO, MMT, RentalWise) -- every booking is either direct or blocked/maintenance.
const OTA_LEGEND_ITEMS = [
  { dot: "bg-rose-500",    label: "Airbnb" },
  { dot: "bg-blue-600",    label: "Booking.com" },
  { dot: "bg-purple-500",  label: "VRBO" },
  { dot: "bg-orange-500",  label: "MMT" },
  { dot: "bg-indigo-500",  label: "RentalWise" },
];

function buildLegend(isCaravan: boolean) {
  return [
    { dot: "bg-emerald-500", label: "Direct" },
    ...(isCaravan ? [] : OTA_LEGEND_ITEMS),
    { dot: "bg-gray-300",    label: "Blocked" },
    { dot: "bg-red-200",     label: "Maintenance" },
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

function buildChannelOpts(isCaravan: boolean) {
  return [
    { value: "",       label: "All channels" },
    { value: "direct", label: "Direct"       },
    ...(isCaravan ? [] : OTA_CHANNEL_OPTS),
  ];
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function PortfolioCalendarPage() {
  const businessType = useBusinessType();
  const isCaravan = businessType === "caravan";
  const LEGEND = useMemo(() => buildLegend(isCaravan), [isCaravan]);
  const CHANNEL_OPTS = useMemo(() => buildChannelOpts(isCaravan), [isCaravan]);
  const [startDate, setStartDate]     = useState<Date>(() => { const d = new Date(); d.setDate(1); return d; });
  const [viewWindow, setViewWindow]   = useState<ViewWindow>("30");
  const [mode, setMode]               = useState<CalendarMode>("bookings");
  const [search, setSearch]           = useState("");
  const [channelFilter, setChan]      = useState("");
  const [hovered, setHovered]         = useState<{ stay: StayBar; pos: { x: number; y: number } } | null>(null);

  const queryClient  = useQueryClient();
  const gridRef      = useRef<HTMLDivElement>(null);   // main scroll container (x + y)
  const headerRef    = useRef<HTMLDivElement>(null);   // header date columns (x sync)

  // Date range
  const numDays  = VIEW_DAYS[viewWindow];
  const fromDate = format(startDate, "yyyy-MM-dd");
  const toDate   = format(addDays(startDate, numDays), "yyyy-MM-dd");

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

  // Max rate (for revenue mode heatmap scale)
  const maxRate = useMemo(() =>
    properties.reduce((mx, p) => {
      const propMax = Object.values(p.rates ?? {}).reduce((m, r) => Math.max(m, r), 0);
      return Math.max(mx, propMax);
    }, 0),
  [properties]);

  // Today summary (computed from data so no extra API call needed)
  const today = format(new Date(), "yyyy-MM-dd");
  const todaySummary = useMemo(() => {
    if (!data?.properties) return null;
    const allStays = data.properties.flatMap(p => p.stays);
    return {
      checkIns:  stats?.check_ins_today  ?? allStays.filter(s => s.check_in  === today).length,
      checkOuts: stats?.check_outs_today ?? allStays.filter(s => s.check_out === today).length,
      vacant:    stats?.vacant_today     ?? data.properties.filter(p =>
        !p.stays.some(s =>
          s.check_in <= today && today < s.check_out &&
          ["confirmed","checked_in"].includes(s.status)
        )
      ).length,
    };
  }, [data?.properties, stats, today]);

  // Virtual rows
  const rowH = ROW_H[mode];
  const { start, end, padTop, padBot } = useVirtualRows(gridRef, properties.length, rowH);

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
    <div className="h-full flex flex-col bg-gray-50 overflow-hidden">

      {/* ── Top summary bar ──────────────────────────────────── */}
      {stats && todaySummary && (
        <TopSummaryBar
          revenue={(stats.revenue_locked ?? 0) + (stats.revenue_quoted ?? 0)}
          occupancy={stats.occupancy_pct ?? 0}
          checkIns={todaySummary.checkIns}
          checkOuts={todaySummary.checkOuts}
          vacant={todaySummary.vacant}
          totalProps={stats.total_properties ?? properties.length}
        />
      )}

      {/* ── Controls ─────────────────────────────────────────── */}
      <div className="flex-shrink-0 bg-white border-b border-gray-200 px-4 py-2.5 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">

          {/* Mode tabs */}
          <div className="flex items-center bg-gray-100 rounded-xl p-0.5">
            {MODE_TABS.map(t => (
              <button
                key={t.key}
                onClick={() => setMode(t.key)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all",
                  mode === t.key ? "bg-white text-teal-700 shadow-sm" : "text-gray-500 hover:text-gray-700",
                )}
              >
                {t.icon}{t.label}
              </button>
            ))}
          </div>

          {/* Date nav */}
          <div className="flex items-center gap-0.5 bg-gray-100 rounded-xl p-0.5">
            <button
              onClick={prevPeriod}
              title={`Previous ${numDays} days`}
              aria-label={`Previous ${numDays} days`}
              className="flex items-center gap-1 px-2 h-7 rounded-lg hover:bg-white text-gray-600 text-[11px] font-medium"
            >
              <ChevronLeft size={14} /> Past
            </button>
            <button onClick={goToToday} className="px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-white rounded-lg">
              Today
            </button>
            <button
              onClick={nextPeriod}
              title={`Next ${numDays} days`}
              aria-label={`Next ${numDays} days`}
              className="flex items-center gap-1 px-2 h-7 rounded-lg hover:bg-white text-gray-600 text-[11px] font-medium"
            >
              Future <ChevronRight size={14} />
            </button>
          </div>

          <span className="text-sm font-bold text-gray-700 min-w-[130px]">
            {format(startDate, "dd MMM")} – {format(addDays(startDate, numDays - 1), "dd MMM yyyy")}
          </span>

          {/* Window */}
          <div className="flex items-center gap-0.5 bg-gray-100 rounded-xl p-0.5">
            {(["14","30","60","90"] as ViewWindow[]).map(v => (
              <button
                key={v}
                onClick={() => setViewWindow(v)}
                className={cn(
                  "px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors",
                  viewWindow === v ? "bg-white text-teal-600 shadow-sm" : "text-gray-500 hover:text-gray-700",
                )}
              >
                {v}d
              </button>
            ))}
          </div>

          {/* Channel filter */}
          <select
            value={channelFilter}
            onChange={e => setChan(e.target.value)}
            className="text-xs border border-gray-200 rounded-xl px-2 py-1.5 bg-white text-gray-700 outline-none focus:ring-2 focus:ring-teal-300 cursor-pointer"
          >
            {CHANNEL_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>

          {/* Search -- not useful for caravan tenants, who run a small enough
              fleet that scanning the row list directly is easier than typing */}
          {!isCaravan && (
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search properties…"
              className="text-xs border border-gray-200 rounded-xl px-3 py-1.5 outline-none focus:ring-2 focus:ring-teal-300 w-36"
            />
          )}

          <div className="flex-1" />

          {/* Sync -- RentalWise-only, no PMS/channel sync exists for caravan tenants */}
          {!isCaravan && (
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
          <button onClick={() => refetch()} className="w-8 h-8 flex items-center justify-center rounded-xl hover:bg-gray-100 text-gray-500">
            <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 flex-wrap">
          {LEGEND.map(l => (
            <div key={l.label} className="flex items-center gap-1">
              <div className={cn("w-2.5 h-2.5 rounded-sm", l.dot)} />
              <span className="text-[10px] text-gray-500">{l.label}</span>
            </div>
          ))}
          <span className="text-[10px] text-gray-400 ml-auto tabular-nums">
            {properties.length} {properties.length === 1 ? "property" : "properties"} · {days.length} days
          </span>
        </div>
      </div>

      {/* ── Calendar grid ─────────────────────────────────────── */}
      {isError ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-sm font-semibold text-red-500">Failed to load calendar</p>
            <button onClick={() => refetch()} className="mt-2 text-sm text-teal-600 hover:underline">Try again</button>
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-hidden flex flex-col">
          {/* Sticky header */}
          <CalendarHeader days={days} headerRef={headerRef} mode={mode} />

          {/* Scrollable body */}
          <div
            ref={gridRef}
            className="flex-1 overflow-auto haip-scrollbar"
            onScroll={handleGridScroll}
          >
            {isLoading ? (
              <div>
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="flex border-b border-gray-100 animate-pulse" style={{ height: rowH }}>
                    <div className="flex-shrink-0 bg-gray-100 border-r border-gray-100" style={{ width: SIDEBAR_W }} />
                    <div className="flex-1 bg-gray-50" />
                  </div>
                ))}
              </div>
            ) : properties.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 text-center">
                <Bed size={40} className="text-gray-200 mb-4" />
                <p className="text-gray-500 font-semibold">No properties found</p>
                <p className="text-xs text-gray-400 mt-1">
                  {search || channelFilter ? "Clear your filters to see all properties" : "Add properties in Portfolio settings"}
                </p>
              </div>
            ) : (
              <div
                style={{
                  minWidth: SIDEBAR_W + days.length * DAY_W,
                  paddingTop: padTop,
                }}
              >
                {properties.slice(start, end + 1).map((row, relIdx) => (
                  <PropertyCalendarRow
                    key={row.property_id}
                    row={row}
                    days={days}
                    mode={mode}
                    onHover={handleHover}
                    onLeave={handleLeave}
                    isEven={(start + relIdx) % 2 === 0}
                    maxRate={maxRate}
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
    </div>
  );
}
