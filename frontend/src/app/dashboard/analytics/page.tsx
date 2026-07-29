"use client";


/**
 * /dashboard/analytics â€” Executive Dashboard
 *
 * Phase 1:
 *  - 6 KPI cards (Revenue MTD, Occupancy, Active Inquiries, QA Score, SLA, AI Draft Rate)
 *  - Revenue bar chart (confirmed vs quoted, daily)
 *  - Inquiry funnel chart
 *  - Channel mix donut
 *  - Occupancy heatmap (per property)
 *  - AI Insights Panel (right rail)
 *
 * Existing QA/calls analytics are preserved below as a secondary section.
 */

import { useState, useMemo, useCallback, memo } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, Cell, PieChart, Pie,
  ReferenceDot, LineChart, Line,
} from "recharts";
import {
  TrendingUp, TrendingDown, Minus, Phone, Star, Clock,
  AlertCircle, Download, ChevronDown, ArrowUpRight, ArrowDownRight,
  DollarSign, Home, Users, ShieldCheck, Bot, Calendar,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { MetricDrillDown } from "@/components/analytics/MetricDrillDown";
import { LostReasonModal } from "@/components/analytics/LostReasonModal";
import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";

// â”€â”€â”€ Design tokens â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const TEAL    = "#14b8a6";
const TEAL_D  = "#0f766e";
const TEAL_L  = "#99f6e4";
const AMBER   = "#fbbf24";
const RED     = "#f87171";
const GRAY    = "#e5e7eb";
const GRAY_D  = "#9ca3af";

// Channel donut colors
const CHANNEL_COLORS = [
  "#14b8a6","#0ea5e9","#f59e0b","#8b5cf6","#ef4444","#10b981","#f97316","#6366f1",
];

// â”€â”€â”€ Types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

interface KPIDelta { pct: number; direction: "up" | "down" | "neutral"; }

interface ExecutiveStats {
  revenue_mtd: number;       revenue_mtd_prev: number;
  occupancy_pct: number;     occupancy_prev: number;
  active_inquiries: number;  active_inquiries_prev: number;
  qa_avg_score: number;      qa_prev: number;
  sla_compliance_pct: number; sla_prev: number;
  ai_draft_rate_pct: number; ai_draft_prev: number;
  revenue_chart: { date: string; confirmed: number; quoted: number }[];
  funnel: { stage: string; count: number; pct: number }[];
  channel_mix: { source: string; count: number; pct: number }[];
  occupancy_heatmap: { property_id: string; property_name: string; pct: number }[];
}

interface OwnerStats {
  today_queue: number; calls_today: number;
  p95_response_time_seconds: number; qa_avg_score: number;
  calls_week: { date: string; count: number; avg_score: number }[];
  top_objections: { text: string; count: number }[];
  lost_reason_themes: { theme: string; count: number; root_cause?: string }[];
  occupancy_rate?: number; revenue_at_risk?: number;
  deltas?: Record<string, KPIDelta>;
  calls_week_prev?: { date: string; count: number; avg_score: number }[];
}

interface AnomalyPoint {
  date: string; count: number; z_score: number;
  is_anomaly: boolean; direction: "high" | "low" | null;
  rolling_mean: number; rolling_std: number;
}

interface Property { id: string; name: string; }

// â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function fmt_inr(n: number): string {
  if (n >= 10000000) return `â‚¹${(n / 10000000).toFixed(1)}Cr`;
  if (n >= 100000)   return `â‚¹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000)     return `â‚¹${(n / 1000).toFixed(0)}k`;
  return `â‚¹${n.toFixed(0)}`;
}

function delta_from(curr: number, prev: number): KPIDelta {
  if (prev === 0) return { pct: 0, direction: "neutral" };
  const pct = Math.round((curr - prev) / prev * 100 * 10) / 10;
  return { pct, direction: pct > 0 ? "up" : pct < 0 ? "down" : "neutral" };
}

// â”€â”€â”€ Delta chip â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function DeltaChip({ delta, invert = false }: { delta: KPIDelta; invert?: boolean }) {
  const positive = invert ? delta.direction === "down" : delta.direction === "up";
  const negative = invert ? delta.direction === "up"  : delta.direction === "down";
  return (
    <span className={cn(
      "inline-flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded-full",
      positive ? "bg-teal-100 text-teal-700" :
      negative ? "bg-red-100 text-red-600"   : "bg-gray-100 text-gray-500",
    )}>
      {delta.direction === "up"   ? <ArrowUpRight size={9}   /> :
       delta.direction === "down" ? <ArrowDownRight size={9} /> : <Minus size={8} />}
      {Math.abs(delta.pct)}%
    </span>
  );
}

// â”€â”€â”€ KPI Card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

interface KPICardProps {
  label: string;
  value: string | number;
  subtext?: string;
  icon: React.ReactNode;
  variant?: "default" | "warning" | "danger";
  delta?: KPIDelta;
  invertDelta?: boolean;
  onClick?: () => void;
}

const KPICard = memo(function KPICard({
  label, value, subtext, icon, variant = "default", delta, invertDelta, onClick,
}: KPICardProps) {
  const iconBg    = variant === "warning" ? "rgba(245,158,11,0.12)"
                  : variant === "danger"  ? "rgba(248,113,113,0.12)"
                  : "rgba(20,184,166,0.10)";
  const iconColor = variant === "warning" ? "#D97706"
                  : variant === "danger"  ? "#ef4444"
                  : "#0F766E";
  return (
    <div
      onClick={onClick}
      className={cn(
        "haip-card rounded-2xl p-5 transition-all",
        onClick && "cursor-pointer hover:shadow-md",
      )}
      style={{ border: "1px solid var(--haip-border)" }}
    >
      <div className="flex items-start justify-between mb-3">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
          style={{ background: iconBg, color: iconColor }}
        >
          {icon}
        </div>
        {delta && <DeltaChip delta={delta} invert={invertDelta} />}
      </div>
      <p
        className="text-2xl font-black leading-none"
        style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}
      >
        {value}
      </p>
      <p className="text-[12px] mt-1" style={{ color: "var(--haip-fg-muted)" }}>{label}</p>
      {subtext && (
        <p className="text-[11px] mt-0.5" style={{ color: "rgba(100,116,139,0.55)" }}>{subtext}</p>
      )}
      {onClick && (
        <p className="text-[10px] mt-2 font-medium" style={{ color: TEAL }}>Drill down â†’</p>
      )}
    </div>
  );
});

// â”€â”€â”€ Custom tooltip for Revenue chart â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function RevTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-100 rounded-xl shadow-md p-3 text-xs min-w-[140px]">
      <p className="font-semibold text-gray-800 mb-1.5">
        {label ? new Date(label).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : label}
      </p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="mb-0.5">
          {p.name}: <span className="font-mono font-bold">{fmt_inr(p.value)}</span>
        </p>
      ))}
    </div>
  );
}

// â”€â”€â”€ Funnel chart (horizontal bars) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const FUNNEL_COLORS: Record<string, string> = {
  NEW: "#3b82f6", RESPONDING: "#8b5cf6", QUOTED: "#f59e0b",
  SITE_VISIT: "#06b6d4", BOOKED: "#10b981", LOST: "#ef4444", GHOSTED: "#9ca3af",
};

function FunnelChart({ data }: { data: { stage: string; count: number; pct: number }[] }) {
  if (!data.length) return (
    <div className="h-[200px] flex items-center justify-center text-sm text-gray-400">
      No inquiry data yet
    </div>
  );
  const max = Math.max(...data.map(d => d.count), 1);
  return (
    <div className="space-y-2 mt-2">
      {data.map(row => (
        <div key={row.stage} className="flex items-center gap-3">
          <span className="w-20 text-[11px] font-medium text-gray-500 flex-shrink-0 capitalize">
            {row.stage.toLowerCase().replace("_", " ")}
          </span>
          <div className="flex-1 h-5 rounded-full overflow-hidden" style={{ background: GRAY }}>
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${(row.count / max) * 100}%`,
                background: FUNNEL_COLORS[row.stage] ?? TEAL,
              }}
            />
          </div>
          <span className="w-10 text-right text-[11px] font-mono font-bold text-gray-700">
            {row.count}
          </span>
          <span className="w-10 text-right text-[10px] text-gray-400">
            {row.pct}%
          </span>
        </div>
      ))}
    </div>
  );
}

// â”€â”€â”€ Occupancy heatmap â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function OccupancyHeatmap({ data }: { data: { property_id: string; property_name: string; pct: number }[] }) {
  if (!data.length) return (
    <div className="h-[120px] flex items-center justify-center text-sm text-gray-400">
      No property data yet
    </div>
  );
  function color(pct: number) {
    if (pct >= 80) return "bg-teal-500 text-white";
    if (pct >= 60) return "bg-teal-300 text-teal-900";
    if (pct >= 40) return "bg-amber-200 text-amber-900";
    if (pct >= 20) return "bg-orange-200 text-orange-900";
    return "bg-red-100 text-red-700";
  }
  return (
    <div className="mt-2 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
      {data.slice(0, 12).map(p => (
        <div
          key={p.property_id}
          className={cn("rounded-xl p-2.5 text-center", color(p.pct))}
          title={`${p.property_name}: ${p.pct}%`}
        >
          <p className="text-[18px] font-black leading-none">{p.pct}%</p>
          <p className="text-[10px] mt-1 truncate font-medium opacity-80">{p.property_name}</p>
        </div>
      ))}
    </div>
  );
}

// â”€â”€â”€ Property filter â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function PropertyFilter({ value, onChange }: { value: string[]; onChange: (ids: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const { data: props = [] } = useQuery<Property[]>({
    queryKey: ["properties-list-analytics"],
    queryFn: () => api.get("/properties").then(r => r.data),
    staleTime: 5 * 60_000,
  });
  const allSelected = value.length === 0;
  const label = allSelected ? "All properties" : `${value.length} selected`;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-[12px] font-medium
                   border transition-colors"
        style={{
          background: "white", borderColor: "var(--haip-border)",
          color: "var(--haip-fg)",
        }}
      >
        <Home size={13} />
        {label}
        <ChevronDown size={12} className={cn("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-50 w-56 rounded-xl border
                     shadow-xl overflow-hidden"
          style={{ background: "white", borderColor: "var(--haip-border)" }}
        >
          <button
            onClick={() => { onChange([]); setOpen(false); }}
            className={cn(
              "w-full text-left px-3 py-2.5 text-[12px] hover:bg-gray-50 transition-colors",
              allSelected && "text-teal-600 font-semibold",
            )}
          >
            All properties
          </button>
          {props.map(p => (
            <button
              key={p.id}
              onClick={() => {
                onChange(
                  value.includes(p.id) ? value.filter(id => id !== p.id) : [...value, p.id]
                );
              }}
              className={cn(
                "w-full text-left px-3 py-2.5 text-[12px] hover:bg-gray-50 transition-colors",
                value.includes(p.id) && "text-teal-600 font-semibold",
              )}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// â”€â”€â”€ Anomaly tooltip (preserved from existing page) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function AnomalyTooltip({ active, payload, label, anomalyMap = {} }: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
  anomalyMap?: Record<string, AnomalyPoint>;
}) {
  if (!active || !payload?.length) return null;
  const anomaly = label ? anomalyMap[label] : null;
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 shadow-md text-xs" style={{ minWidth: 152 }}>
      <p className="font-semibold text-gray-900 mb-1.5">
        {label ? new Date(label).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" }) : label}
      </p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="mb-0.5">
          {p.name}: <span className="font-mono font-bold">{p.value ?? "â€”"}</span>
        </p>
      ))}
      {anomaly?.is_anomaly && (
        <div className={cn("mt-2 pt-2 border-t flex items-center gap-1.5 font-semibold",
          anomaly.direction === "high" ? "border-red-100 text-red-600" : "border-amber-100 text-amber-600",
        )}>
          <AlertCircle size={10} />
          <span>{anomaly.direction === "high" ? "Unusually high" : "Unusually low"} ({Math.abs(anomaly.z_score).toFixed(1)}Ïƒ)</span>
        </div>
      )}
    </div>
  );
}

// â”€â”€â”€ Skeleton â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <div className="flex justify-between">
        <Skeleton className="h-7 w-44 rounded-xl" />
        <div className="flex gap-2">
          {[1,2,3].map(i => <Skeleton key={i} className="h-9 w-28 rounded-xl" />)}
        </div>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        {Array.from({length:6}).map((_,i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
      </div>
      <div className="grid grid-cols-12 gap-5">
        <Skeleton className="col-span-12 lg:col-span-8 h-64 rounded-2xl" />
        <Skeleton className="col-span-12 lg:col-span-4 h-64 rounded-2xl" />
      </div>
      <div className="grid grid-cols-12 gap-5">
        {[8,4].map((c,i) => <Skeleton key={i} className={`col-span-${c} h-52 rounded-2xl`} />)}
      </div>
    </div>
  );
}

// â”€â”€â”€ Main page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export default function AnalyticsPage() {
  const router      = useRouter();
  const pathname    = usePathname();
  const searchParams = useSearchParams();

  // â”€â”€ URL-persisted filters â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const rangeDays  = parseInt(searchParams.get("range_days") ?? "30");
  const compareTo  = searchParams.get("compare_to") ?? "none";
  const propFilter = searchParams.get("property_ids") ?? "";

  const [selectedProps, setSelectedProps] = useState<string[]>(
    propFilter ? propFilter.split(",").filter(Boolean) : []
  );
  const [drillMetric, setDrillMetric] = useState<{ key: string; label: string } | null>(null);
  const [lostTheme,   setLostTheme]   = useState<{ theme: string; label: string; count: number } | null>(null);

  const propIdsParam = selectedProps.join(",") || undefined;

  const updateParams = useCallback((updates: Record<string, string>) => {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(updates).forEach(([k, v]) => v ? params.set(k, v) : params.delete(k));
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }, [searchParams, pathname, router]);

  // â”€â”€ Data fetching â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  const { data: exec, isLoading: execLoading } = useQuery<ExecutiveStats>({
    queryKey: ["analytics", "executive", rangeDays, propIdsParam],
    queryFn: () => api.get("/analytics/executive", {
      params: { range_days: rangeDays, ...(propIdsParam && { property_ids: propIdsParam }) },
    }).then(r => r.data),
    staleTime: 5 * 60_000,
    placeholderData: undefined,
  });

  // Legacy owner-daily for the QA/calls section below
  const { data: ownerStats } = useQuery<OwnerStats>({
    queryKey: ["analytics", "owner-daily", rangeDays, compareTo, propIdsParam],
    queryFn: () => api.get("/analytics/owner-daily", {
      params: { range_days: rangeDays, compare_to: compareTo, ...(propIdsParam && { property_ids: propIdsParam }) },
    }).then(r => r.data),
    staleTime: 5 * 60_000,
  });

  const { data: anomalies = [] } = useQuery<AnomalyPoint[]>({
    queryKey: ["analytics", "anomalies", rangeDays, propIdsParam],
    queryFn: () => api.get("/analytics/anomalies", { params: { range_days: rangeDays } }).then(r => r.data),
    staleTime: 5 * 60_000,
  });

  // â”€â”€ Derived values â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  const e = exec;
  const s = ownerStats ?? {} as OwnerStats;

  const revDelta     = e ? delta_from(e.revenue_mtd,        e.revenue_mtd_prev)        : null;
  const occDelta     = e ? delta_from(e.occupancy_pct,      e.occupancy_prev)          : null;
  const inqDelta     = e ? delta_from(e.active_inquiries,   e.active_inquiries_prev)   : null;
  const qaDelta      = e ? delta_from(e.qa_avg_score,       e.qa_prev)                 : null;
  const slaDelta     = e ? delta_from(e.sla_compliance_pct, e.sla_prev)                : null;
  const aiDelta      = e ? delta_from(e.ai_draft_rate_pct,  e.ai_draft_prev)           : null;

  const anomalyMap   = useMemo(() => Object.fromEntries(anomalies.map(a => [a.date, a])), [anomalies]);
  const anomalyDots  = useMemo(() => anomalies.filter(a => a.is_anomaly), [anomalies]);

  const zippedCalls  = useMemo(() => (s.calls_week ?? []).map((d, i) => ({
    ...d,
    count_prev: s.calls_week_prev?.[i]?.count ?? null,
  })), [s.calls_week, s.calls_week_prev]);

  if (execLoading) return <PageSkeleton />;

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>

      {/* â”€â”€ Top bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div
        className="flex-shrink-0 px-6 py-4 border-b"
        style={{ background: "white", borderColor: "var(--haip-border)" }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1
              className="haip-page-title"
            >
              Executive Dashboard
            </h1>
            <p className="text-[12px] mt-0.5 text-gray-400">
              {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Range selector */}
            {([7, 14, 30, 90] as const).map(d => (
              <button
                key={d}
                onClick={() => updateParams({ range_days: String(d) })}
                className={cn(
                  "px-3 py-1.5 rounded-xl text-[12px] font-medium border transition-colors",
                  rangeDays === d
                    ? "bg-teal-600 text-white border-teal-600"
                    : "bg-white text-gray-600 border-gray-200 hover:border-teal-300",
                )}
              >
                {d}d
              </button>
            ))}
            <PropertyFilter value={selectedProps} onChange={ids => {
              setSelectedProps(ids);
              updateParams({ property_ids: ids.join(",") });
            }} />
          </div>
        </div>
      </div>

      {/* â”€â”€ Scrollable content â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="flex-1 overflow-y-auto haip-scrollbar px-6 py-5 space-y-5">

        {/* â”€â”€ 6 KPI cards â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-4">
          <KPICard
            label="Revenue MTD"
            value={e ? fmt_inr(e.revenue_mtd) : "â€”"}
            subtext={e ? `Prev: ${fmt_inr(e.revenue_mtd_prev)}` : undefined}
            icon={<DollarSign size={18} />}
            delta={revDelta ?? undefined}
          />
          <KPICard
            label="Occupancy %"
            value={e ? `${e.occupancy_pct}%` : "â€”"}
            subtext={e ? `Prev: ${e.occupancy_prev}%` : undefined}
            icon={<Calendar size={18} />}
            variant={e && e.occupancy_pct < 40 ? "warning" : "default"}
            delta={occDelta ?? undefined}
            onClick={() => setDrillMetric({ key: "occupancy_rate", label: "Occupancy" })}
          />
          <KPICard
            label="Active Inquiries"
            value={e?.active_inquiries ?? "â€”"}
            subtext={e ? `Prev: ${e.active_inquiries_prev}` : undefined}
            icon={<Users size={18} />}
            delta={inqDelta ?? undefined}
            onClick={() => setDrillMetric({ key: "today_queue", label: "Active inquiries" })}
          />
          <KPICard
            label="Avg QA Score"
            value={e ? `${e.qa_avg_score}` : "â€”"}
            subtext={e ? `Prev: ${e.qa_prev}` : undefined}
            icon={<Star size={18} />}
            variant={e && e.qa_avg_score < 60 ? "danger" : e && e.qa_avg_score < 75 ? "warning" : "default"}
            delta={qaDelta ?? undefined}
            onClick={() => setDrillMetric({ key: "qa_avg_score", label: "QA Score" })}
          />
          <KPICard
            label="SLA Compliance"
            value={e ? `${e.sla_compliance_pct}%` : "â€”"}
            subtext={e ? `Prev: ${e.sla_prev}%` : undefined}
            icon={<ShieldCheck size={18} />}
            variant={e && e.sla_compliance_pct < 80 ? "danger" : e && e.sla_compliance_pct < 90 ? "warning" : "default"}
            delta={slaDelta ?? undefined}
          />
          <KPICard
            label="AI Draft Rate"
            value={e ? `${e.ai_draft_rate_pct}%` : "â€”"}
            subtext={e ? `Prev: ${e.ai_draft_prev}%` : undefined}
            icon={<Bot size={18} />}
            delta={aiDelta ?? undefined}
          />
        </div>

        {/* â”€â”€ Revenue chart + AI Insights Panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <div className="grid grid-cols-12 gap-5">

          {/* Revenue chart */}
          <div
            className="col-span-12 lg:col-span-8 haip-card rounded-2xl p-5"
            style={{ border: "1px solid var(--haip-border)" }}
          >
            <h2
              className="text-[13px] font-semibold mb-4"
              style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
            >
              Revenue â€” last {rangeDays} days
            </h2>
            {(e?.revenue_chart?.length ?? 0) > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={e!.revenue_chart} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11, fill: GRAY_D }}
                    tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                    interval={Math.floor((e!.revenue_chart.length - 1) / 5)}
                  />
                  <YAxis tick={{ fontSize: 11, fill: GRAY_D }} tickLine={false} axisLine={false}
                    tickFormatter={v => fmt_inr(v)} />
                  <Tooltip content={<RevTooltip />} />
                  <Legend wrapperStyle={{ fontSize: "11px" }} />
                  <Bar dataKey="confirmed" name="Confirmed" fill={TEAL}    radius={[4,4,0,0]} />
                  <Bar dataKey="quoted"    name="Quoted"    fill={TEAL_L}  radius={[4,4,0,0]} opacity={0.75} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-sm text-gray-400">
                No revenue data for this period
              </div>
            )}
          </div>

          {/* AI Insights Panel */}
          <div
            className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5"
            style={{ border: "1px solid var(--haip-border)" }}
          >
            <AIInsightsPanel />
          </div>
        </div>

        {/* â”€â”€ Inquiry funnel + Channel mix â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <div className="grid grid-cols-12 gap-5">

          {/* Inquiry funnel */}
          <div
            className="col-span-12 lg:col-span-7 haip-card rounded-2xl p-5"
            style={{ border: "1px solid var(--haip-border)" }}
          >
            <h2
              className="text-[13px] font-semibold"
              style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
            >
              Inquiry Funnel
            </h2>
            <FunnelChart data={e?.funnel ?? []} />
          </div>

          {/* Channel mix donut */}
          <div
            className="col-span-12 lg:col-span-5 haip-card rounded-2xl p-5"
            style={{ border: "1px solid var(--haip-border)" }}
          >
            <h2
              className="text-[13px] font-semibold mb-2"
              style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
            >
              Channel Mix
            </h2>
            {(e?.channel_mix?.length ?? 0) > 0 ? (
              <div className="flex items-center gap-4">
                <ResponsiveContainer width={130} height={130}>
                  <PieChart>
                    <Pie
                      data={e!.channel_mix}
                      dataKey="count"
                      nameKey="source"
                      cx="50%" cy="50%"
                      innerRadius={36}
                      outerRadius={60}
                      paddingAngle={2}
                    >
                      {e!.channel_mix.map((_, i) => (
                        <Cell key={i} fill={CHANNEL_COLORS[i % CHANNEL_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex-1 space-y-1.5">
                  {e!.channel_mix.slice(0, 6).map((c, i) => (
                    <div key={c.source} className="flex items-center gap-2">
                      <span
                        className="w-2 h-2 rounded-full flex-shrink-0"
                        style={{ background: CHANNEL_COLORS[i % CHANNEL_COLORS.length] }}
                      />
                      <span className="text-[11px] truncate flex-1 text-gray-600 capitalize">
                        {c.source.replace(/_/g, " ").toLowerCase()}
                      </span>
                      <span className="text-[11px] font-mono font-bold text-gray-700">{c.pct}%</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="h-[130px] flex items-center justify-center text-sm text-gray-400">
                No channel data yet
              </div>
            )}
          </div>
        </div>

        {/* â”€â”€ Occupancy heatmap â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <div
          className="haip-card rounded-2xl p-5"
          style={{ border: "1px solid var(--haip-border)" }}
        >
          <h2
            className="text-[13px] font-semibold"
            style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
          >
            Property Occupancy â€” MTD
          </h2>
          <OccupancyHeatmap data={e?.occupancy_heatmap ?? []} />
        </div>

        {/* â”€â”€ QA / Calls section (preserved from original analytics page) â”€â”€â”€â”€ */}
        <div className="pt-2">
          <h2
            className="text-[14px] font-semibold mb-4"
            style={{ color: "var(--haip-fg-muted)", fontFamily: "var(--font-display), sans-serif" }}
          >
            Calls & QA Intelligence
          </h2>
        </div>

        {/* Calls chart */}
        <div className="grid grid-cols-12 gap-5">
          <div
            className="col-span-12 lg:col-span-8 haip-card rounded-2xl p-5"
            style={{ border: "1px solid var(--haip-border)" }}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <h2
                  className="text-[13px] font-semibold"
                  style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
                >
                  Calls â€” last {rangeDays} days
                </h2>
                {anomalyDots.length > 0 && (
                  <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-red-50 text-red-500 border border-red-100">
                    <AlertCircle size={9} />
                    {anomalyDots.length} anomal{anomalyDots.length > 1 ? "ies" : "y"}
                  </span>
                )}
              </div>
              {/* Compare toggle */}
              <button
                onClick={() => updateParams({ compare_to: compareTo === "none" ? "previous_period" : "none" })}
                className={cn(
                  "text-[11px] px-2.5 py-1 rounded-lg border transition-colors",
                  compareTo !== "none"
                    ? "bg-teal-600 text-white border-teal-600"
                    : "bg-white text-gray-500 border-gray-200 hover:border-teal-300",
                )}
              >
                Compare
              </button>
            </div>
            {zippedCalls.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={zippedCalls} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: GRAY_D }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { weekday: "short" })} />
                  <YAxis tick={{ fontSize: 11, fill: GRAY_D }} tickLine={false} axisLine={false} />
                  <Tooltip content={(p) => <AnomalyTooltip {...(p as any)} anomalyMap={anomalyMap} />} />
                  <Bar dataKey="count" name="Calls" fill={TEAL} radius={[6,6,0,0]} />
                  {compareTo !== "none" && (
                    <Bar dataKey="count_prev" name="Prev. period" fill={TEAL_L} radius={[6,6,0,0]} opacity={0.6} />
                  )}
                  {compareTo !== "none" && <Legend wrapperStyle={{ fontSize: "11px" }} />}
                  {anomalyDots.map(a => (
                    <ReferenceDot key={a.date} x={a.date} y={a.count} r={6}
                      fill={a.direction === "high" ? RED : AMBER} stroke="white" strokeWidth={2}
                      label={{ value: a.direction === "high" ? "â–²" : "â–¼",
                        position: a.direction === "high" ? "top" : "bottom" as const,
                        fontSize: 9, fill: a.direction === "high" ? RED : AMBER }}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-sm text-gray-400">No call data yet</div>
            )}
          </div>

          {/* Top objections */}
          <div
            className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5"
            style={{ border: "1px solid var(--haip-border)" }}
          >
            <h2 className="text-[13px] font-semibold mb-4"
              style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}>
              Top objections
            </h2>
            {(s.top_objections?.length ?? 0) > 0 ? (
              <div className="space-y-2.5">
                {s.top_objections.slice(0, 5).map((obj, i) => {
                  const max = s.top_objections[0].count;
                  const pct = (obj.count / max) * 100;
                  return (
                    <div key={i}>
                      <div className="flex justify-between text-[12px] mb-1">
                        <span className="truncate" style={{ color: "var(--haip-fg)" }}>{obj.text}</span>
                        <span className="font-mono ml-2" style={{ color: "var(--haip-fg-muted)" }}>{obj.count}</span>
                      </div>
                      <div className="h-1.5 rounded-full" style={{ background: "var(--haip-border)" }}>
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: AMBER }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-[12px] py-6 text-center" style={{ color: "var(--haip-fg-muted)" }}>
                No objection data yet
              </p>
            )}
          </div>
        </div>

        {/* Lost reason themes */}
        {(s.lost_reason_themes?.length ?? 0) > 0 && (
          <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[13px] font-semibold"
                style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}>
                Lost inquiry themes
              </h2>
              <p className="text-[11px]" style={{ color: "var(--haip-fg-muted)" }}>
                Click a theme to see inquiries
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {s.lost_reason_themes.map((t, i) => (
                <button
                  key={i}
                  onClick={() => setLostTheme({ theme: t.theme, label: t.theme.replace(/_/g, " "), count: t.count })}
                  className="bg-red-50 border border-red-100 rounded-xl p-4 text-left
                             hover:bg-red-100/60 hover:border-red-200 transition-colors group"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-semibold text-red-800 capitalize">
                      {t.theme.replace(/_/g, " ")}
                    </span>
                    <Badge variant="destructive" className="text-[10px]">{t.count}</Badge>
                  </div>
                  {t.root_cause && <p className="text-xs text-red-600">{t.root_cause}</p>}
                  <p className="text-[10px] text-red-400 mt-2 group-hover:text-red-600 transition-colors font-medium">
                    View inquiries â†’
                  </p>
                </button>
              ))}
            </div>
          </div>
        )}

      </div>{/* end scrollable */}

      {/* â”€â”€ Panels â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      {drillMetric && (
        <MetricDrillDown
          metricKey={drillMetric.key}
          metricLabel={drillMetric.label}
          onClose={() => setDrillMetric(null)}
        />
      )}
      {lostTheme && (
        <LostReasonModal
          theme={lostTheme.theme}
          themeLabel={lostTheme.label}
          count={lostTheme.count}
          onClose={() => setLostTheme(null)}
        />
      )}
    </div>
  );
}
