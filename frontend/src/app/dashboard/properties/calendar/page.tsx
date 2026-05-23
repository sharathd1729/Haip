"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  addDays, format, startOfMonth, endOfMonth, startOfWeek, endOfWeek,
  parseISO, differenceInDays, isSameDay,
} from "date-fns";
import {
  Calendar, ChevronLeft, ChevronRight, Download, Plus, X,
  Bed, Users, Wifi, AlertCircle, Zap, BrainCircuit,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";

// ── Types ─────────────────────────────────────────────────────────────────────

type ViewMode = "14days" | "month" | "quarter";

type CellStatus =
  | "free"
  | "inquiry"
  | "quoted"
  | "confirmed"
  | "checked_in"
  | "maintenance"
  | "offline_booking"
  | "personal"    // owner use
  | "other";

interface CalendarProperty {
  property_id: string;
  property_name: string;
  property_type: string;
  bedrooms: number;
  max_adults: number;
  channel_source?: string;
  cells: Record<string, CellStatus>;
  stays: {
    id: string;
    check_in: string;
    check_out: string;
    status: string;
    total_amount?: number;
  }[];
  blocks: {
    id: string;
    blocked_from: string;
    blocked_to: string;
    reason: string;
    notes?: string;
    is_active: boolean;
  }[];
}

interface CalendarStats {
  occupancy_pct: number;
  revenue_locked: number;
  revenue_quoted: number;
  total_properties: number;
  window_days: number;
}

interface Suggestion {
  type: string;
  property: string;
  date: string;
  message: string;
}

interface CalendarData {
  from_date: string;
  to_date: string;
  days: string[];
  properties: CalendarProperty[];
  stats: CalendarStats;
  suggestions: Suggestion[];
}

// ── Status colour map (matches the mockup) ────────────────────────────────────

const STATUS_COLORS: Record<CellStatus, string> = {
  free:             "bg-emerald-100 border-emerald-200",
  inquiry:          "bg-amber-100 border-amber-200",
  quoted:           "bg-yellow-100 border-yellow-200",
  confirmed:        "bg-emerald-400 border-emerald-500",
  checked_in:       "bg-teal-500 border-teal-600",
  maintenance:      "bg-slate-200 border-slate-300",
  offline_booking:  "bg-violet-200 border-violet-300",
  personal:         "bg-pink-100 border-pink-200",
  other:            "bg-slate-200 border-slate-300",
};

const STATUS_LABELS: Record<CellStatus, string> = {
  free:            "Free",
  inquiry:         "Inquiry",
  quoted:          "Quoted",
  confirmed:       "Booked",
  checked_in:      "Checked in",
  maintenance:     "Maintenance",
  offline_booking: "Blocked",
  personal:        "Owner use",
  other:           "Blocked",
};

const LEGEND: { status: CellStatus; label: string }[] = [
  { status: "free",            label: "Free" },
  { status: "inquiry",         label: "Inquiry" },
  { status: "quoted",          label: "Quoted" },
  { status: "confirmed",       label: "Booked" },
  { status: "checked_in",      label: "Checked in" },
  { status: "offline_booking", label: "Blocked" },
  { status: "maintenance",     label: "Maintenance" },
  { status: "personal",        label: "Owner use" },
];

// ── Helper: build date window ─────────────────────────────────────────────────

function buildWindow(anchor: Date, mode: ViewMode): { from: string; to: string } {
  let from: Date, to: Date;
  if (mode === "14days") {
    from = anchor;
    to = addDays(anchor, 14);
  } else if (mode === "month") {
    from = startOfMonth(anchor);
    to = addDays(endOfMonth(anchor), 1);
  } else {
    // quarter = ~90 days
    from = anchor;
    to = addDays(anchor, 90);
  }
  return {
    from: format(from, "yyyy-MM-dd"),
    to:   format(to,   "yyyy-MM-dd"),
  };
}

function fmt(iso: string): string {
  const d = parseISO(iso);
  return format(d, "MMM d");
}

function fmtAmount(n: number): string {
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000)   return `₹${(n / 1000).toFixed(1)}K`;
  return `₹${n}`;
}

// ── Block dates modal ─────────────────────────────────────────────────────────

interface BlockModalProps {
  properties: CalendarProperty[];
  defaultPropertyId?: string;
  defaultDate?: string;
  onClose: () => void;
  onSave: (data: {
    property_id: string;
    blocked_from: string;
    blocked_to: string;
    reason: string;
    notes: string;
  }) => void;
}

function BlockModal({ properties, defaultPropertyId, defaultDate, onClose, onSave }: BlockModalProps) {
  const today = format(new Date(), "yyyy-MM-dd");
  const [propertyId, setPropertyId] = useState(defaultPropertyId || (properties[0]?.property_id ?? ""));
  const [from, setFrom] = useState(defaultDate || today);
  const [to, setTo]     = useState(defaultDate ? format(addDays(parseISO(defaultDate), 1), "yyyy-MM-dd") : format(addDays(new Date(), 1), "yyyy-MM-dd"));
  const [reason, setReason] = useState("maintenance");
  const [notes, setNotes]   = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-[#1a1a2e] border border-white/10 rounded-2xl w-full max-w-md p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-white font-semibold text-lg">Block Dates</h2>
          <button onClick={onClose} className="text-white/40 hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4">
          {/* Property */}
          <div>
            <label className="text-xs text-white/50 mb-1 block">Property</label>
            <select
              value={propertyId}
              onChange={e => setPropertyId(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-white/30"
            >
              {properties.map(p => (
                <option key={p.property_id} value={p.property_id} className="bg-[#1a1a2e]">
                  {p.property_name}
                </option>
              ))}
            </select>
          </div>

          {/* Dates */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-white/50 mb-1 block">From</label>
              <input
                type="date"
                value={from}
                onChange={e => setFrom(e.target.value)}
                className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-white/30"
              />
            </div>
            <div>
              <label className="text-xs text-white/50 mb-1 block">To (exclusive)</label>
              <input
                type="date"
                value={to}
                onChange={e => setTo(e.target.value)}
                className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-white/30"
              />
            </div>
          </div>

          {/* Reason */}
          <div>
            <label className="text-xs text-white/50 mb-1 block">Reason</label>
            <select
              value={reason}
              onChange={e => setReason(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-white/30"
            >
              <option value="maintenance"     className="bg-[#1a1a2e]">Maintenance / Repair</option>
              <option value="personal"        className="bg-[#1a1a2e]">Owner / Personal use</option>
              <option value="offline_booking" className="bg-[#1a1a2e]">Offline Booking</option>
              <option value="other"           className="bg-[#1a1a2e]">Other</option>
            </select>
          </div>

          {/* Notes */}
          <div>
            <label className="text-xs text-white/50 mb-1 block">Notes (optional)</label>
            <input
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="e.g. AC repair, family trip..."
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm placeholder:text-white/25 focus:outline-none focus:border-white/30"
            />
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 border border-white/10 text-white/60 rounded-lg py-2 text-sm hover:bg-white/5 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave({ property_id: propertyId, blocked_from: from, blocked_to: to, reason, notes })}
            className="flex-1 bg-violet-600 hover:bg-violet-500 text-white rounded-lg py-2 text-sm font-medium transition-colors"
          >
            Save Block
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CalendarPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [anchor, setAnchor]   = useState(new Date());
  const [mode, setMode]       = useState<ViewMode>("14days");
  const [showBlock, setShowBlock] = useState(false);
  const [blockDefault, setBlockDefault] = useState<{ propertyId?: string; date?: string }>({});

  const window = useMemo(() => buildWindow(anchor, mode), [anchor, mode]);

  const { data, isLoading } = useQuery<CalendarData>({
    queryKey: ["calendar", window.from, window.to],
    queryFn: () =>
      api.get("/calendar", { params: { from_date: window.from, to_date: window.to } }).then(r => r.data),
    staleTime: 60_000,
  });

  const createBlock = useMutation({
    mutationFn: (payload: {
      property_id: string;
      blocked_from: string;
      blocked_to: string;
      reason: string;
      notes: string;
    }) => api.post("/calendar/blocked-dates", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["calendar"] });
      setShowBlock(false);
      toast({ title: "Dates blocked", variant: "success" });
    },
    onError: () => toast({ title: "Failed to block dates", variant: "destructive" }),
  });

  const deleteBlock = useMutation({
    mutationFn: (blockId: string) => api.delete(`/calendar/blocked-dates/${blockId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["calendar"] });
      toast({ title: "Block removed", variant: "success" });
    },
  });

  // Navigate anchor
  function navPrev() {
    if (mode === "14days") setAnchor(d => addDays(d, -14));
    else if (mode === "month") setAnchor(d => new Date(d.getFullYear(), d.getMonth() - 1, 1));
    else setAnchor(d => addDays(d, -90));
  }
  function navNext() {
    if (mode === "14days") setAnchor(d => addDays(d, 14));
    else if (mode === "month") setAnchor(d => new Date(d.getFullYear(), d.getMonth() + 1, 1));
    else setAnchor(d => addDays(d, 90));
  }

  const days = data?.days ?? [];
  const properties = data?.properties ?? [];
  const stats = data?.stats;
  const suggestions = data?.suggestions ?? [];

  // Column width depends on how many days (shrink for quarter)
  const colW = mode === "quarter" ? "w-8" : mode === "month" ? "w-10" : "w-14";

  return (
    <div className="flex flex-col h-full bg-[#0f0f1a] text-white overflow-hidden">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="px-6 py-4 border-b border-white/5 flex-shrink-0">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold text-white">Villas &amp; Calendar</h1>
            <p className="text-xs text-white/40 mt-0.5">
              {properties.length} propert{properties.length === 1 ? "y" : "ies"} · next {stats?.window_days ?? "–"} days
              {data && <span className="ml-2 text-emerald-400/60">· all channel managers synced</span>}
            </p>
          </div>

          <div className="flex items-center gap-2">
            {/* Nav */}
            <button onClick={navPrev} className="p-1.5 rounded-lg border border-white/10 hover:bg-white/5 transition-colors">
              <ChevronLeft size={14} />
            </button>
            <button onClick={navNext} className="p-1.5 rounded-lg border border-white/10 hover:bg-white/5 transition-colors">
              <ChevronRight size={14} />
            </button>

            {/* View mode */}
            <div className="flex items-center border border-white/10 rounded-lg overflow-hidden text-xs">
              {(["14days", "month", "quarter"] as ViewMode[]).map(v => (
                <button
                  key={v}
                  onClick={() => setMode(v)}
                  className={cn(
                    "px-3 py-1.5 transition-colors",
                    mode === v ? "bg-white/10 text-white" : "text-white/40 hover:text-white/70"
                  )}
                >
                  {v === "14days" ? "14 days" : v === "month" ? "Month" : "Quarter"}
                </button>
              ))}
            </div>

            {/* Export ICS */}
            <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-white/10 rounded-lg text-white/60 hover:bg-white/5 transition-colors">
              <Download size={13} />
              Export ICS
            </button>

            {/* Block dates */}
            <button
              onClick={() => { setBlockDefault({}); setShowBlock(true); }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-violet-600 hover:bg-violet-500 rounded-lg text-white font-medium transition-colors"
            >
              <Plus size={13} />
              Block dates
            </button>
          </div>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 mt-3 flex-wrap">
          {LEGEND.map(({ status, label }) => (
            <div key={status} className="flex items-center gap-1.5">
              <div className={cn("w-3 h-3 rounded-sm border", STATUS_COLORS[status])} />
              <span className="text-[11px] text-white/45">{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Calendar grid ──────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-48 text-white/30 text-sm gap-2">
            <Calendar size={16} className="animate-spin" />
            Loading calendar…
          </div>
        ) : (
          <table className="min-w-full border-collapse text-xs">
            <thead className="sticky top-0 z-20 bg-[#0f0f1a]">
              <tr>
                {/* Property name column */}
                <th className="w-44 min-w-44 text-left px-4 py-2 border-b border-r border-white/5 text-white/30 font-medium uppercase tracking-widest text-[10px]">
                  VILLA
                </th>
                {days.map(day => {
                  const d = parseISO(day);
                  const isWeekend = d.getDay() === 0 || d.getDay() === 6;
                  return (
                    <th
                      key={day}
                      className={cn(
                        colW,
                        "border-b border-r border-white/5 text-center py-1 font-medium",
                        isWeekend ? "text-amber-400/70" : "text-white/35"
                      )}
                    >
                      <div className="text-[9px] uppercase leading-none">
                        {format(d, "EEE")}
                      </div>
                      <div className={cn("text-[11px] font-semibold mt-0.5", isWeekend && "text-amber-400")}>
                        {format(d, "d")}
                      </div>
                      {mode !== "quarter" && (
                        <div className="text-[9px] text-white/20 leading-none mt-0.5">
                          {format(d, "MMM")}
                        </div>
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>

            <tbody>
              {properties.map(prop => (
                <tr key={prop.property_id} className="group hover:bg-white/[0.02] transition-colors">
                  {/* Property info cell */}
                  <td className="px-4 py-2 border-b border-r border-white/5 align-middle sticky left-0 bg-[#0f0f1a] z-10 group-hover:bg-[#12122a]">
                    <div className="font-semibold text-white/85 text-xs leading-tight">{prop.property_name}</div>
                    <div className="text-[10px] text-white/30 mt-0.5">
                      {prop.bedrooms}BR · {prop.max_adults} pax
                      {prop.channel_source && (
                        <span className="ml-1.5 text-emerald-400/50">⟳ {prop.channel_source}</span>
                      )}
                    </div>
                  </td>

                  {/* Day cells */}
                  {days.map(day => {
                    const status = (prop.cells[day] || "free") as CellStatus;
                    const isFree = status === "free";

                    return (
                      <td
                        key={day}
                        className={cn(
                          colW,
                          "border-b border-r border-white/5 p-px cursor-pointer transition-opacity",
                          isFree && "hover:opacity-80"
                        )}
                        title={`${prop.property_name} · ${fmt(day)} · ${STATUS_LABELS[status]}`}
                        onClick={() => {
                          if (isFree) {
                            setBlockDefault({ propertyId: prop.property_id, date: day });
                            setShowBlock(true);
                          }
                        }}
                      >
                        <div
                          className={cn(
                            "h-7 w-full rounded-sm border",
                            STATUS_COLORS[status],
                          )}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}

              {properties.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={days.length + 1} className="text-center py-16 text-white/25 text-sm">
                    No properties found. Add properties in the Portfolio tab.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Stats + AI suggestions footer ──────────────────────────────────── */}
      {stats && (
        <div className="flex-shrink-0 border-t border-white/5 grid grid-cols-3 divide-x divide-white/5">

          {/* Occupancy */}
          <div className="px-6 py-4">
            <div className="text-[11px] text-white/35 uppercase tracking-widest mb-2 flex items-center gap-1.5">
              <Calendar size={11} />
              Occupancy this {stats.window_days}d
            </div>
            <div className="text-3xl font-bold text-white">{stats.occupancy_pct}%</div>
            <div className="mt-2 h-1.5 rounded-full bg-white/5 w-full overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-400 transition-all duration-700"
                style={{ width: `${stats.occupancy_pct}%` }}
              />
            </div>
            <div className="text-[10px] text-white/25 mt-1.5">
              {stats.total_properties} properties · {stats.window_days}-day window
            </div>
          </div>

          {/* Revenue */}
          <div className="px-6 py-4">
            <div className="text-[11px] text-white/35 uppercase tracking-widest mb-2 flex items-center gap-1.5">
              <Zap size={11} />
              Revenue locked-in ({stats.window_days}d)
            </div>
            <div className="text-3xl font-bold text-white">{fmtAmount(stats.revenue_locked)}</div>
            {stats.revenue_quoted > 0 && (
              <div className="text-[11px] text-amber-400/60 mt-1">
                + {fmtAmount(stats.revenue_quoted)} pending in Quoted
              </div>
            )}
            {stats.revenue_locked === 0 && (
              <div className="text-[11px] text-white/20 mt-1">No bookings with amounts set yet</div>
            )}
          </div>

          {/* HAIP suggests */}
          <div className="px-6 py-4">
            <div className="text-[11px] text-white/35 uppercase tracking-widest mb-2 flex items-center gap-1.5">
              <BrainCircuit size={11} />
              HAIP suggests
            </div>

            {suggestions.length === 0 ? (
              <div className="text-[11px] text-white/20">
                No gaps or pressure points detected in this window.
              </div>
            ) : (
              <div className="space-y-2">
                {suggestions.map((s, i) => (
                  <div key={i} className="text-[11px] text-white/55 leading-relaxed">
                    <span className={cn(
                      "font-semibold",
                      s.type === "gap" ? "text-amber-400" : "text-violet-400"
                    )}>
                      {s.type === "gap" ? "Open gap" : "Pressure"} — {s.property} {fmt(s.date)}:{" "}
                    </span>
                    {s.message.split(s.property + " " + s.date + ": ")[1] || s.message}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Block dates modal ──────────────────────────────────────────────── */}
      {showBlock && (
        <BlockModal
          properties={properties}
          defaultPropertyId={blockDefault.propertyId}
          defaultDate={blockDefault.date}
          onClose={() => setShowBlock(false)}
          onSave={payload => createBlock.mutate(payload)}
        />
      )}
    </div>
  );
}
