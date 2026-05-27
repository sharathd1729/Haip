"use client";

/**
 * Analytics page — Owner dashboard
 *
 * A1: KPI card click → MetricDrillDown side panel
 * A2: "Compare to previous period" toggle → delta chips + overlay line
 * A3: Property filter → multi-select, persisted in URL
 * A4: Lost-reason theme click → LostReasonModal
 * A5: Per-chart CSV export button
 */

import { useState } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ReferenceDot,
} from "recharts";
import {
  TrendingUp, TrendingDown, Minus, Phone, Star, Clock,
  AlertCircle, Download, ChevronDown, ArrowUpRight, ArrowDownRight,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { MetricDrillDown } from "@/components/analytics/MetricDrillDown";
import { LostReasonModal } from "@/components/analytics/LostReasonModal";

// ─── Constants ────────────────────────────────────────────────────────────────

const TEAL_500 = "#14b8a6";
const TEAL_200 = "#99f6e4";
const AMBER_400 = "#fbbf24";
const RED_400 = "#f87171";
const GRAY_200 = "#e5e7eb";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Objection { text: string; count: number; }
interface LostTheme { theme: string; count: number; root_cause?: string; }
interface CallsWeekPoint { date: string; count: number; avg_score: number; }
interface KPIDelta { pct: number; direction: "up" | "down" | "neutral"; }

// A8: anomaly shape returned by /analytics/anomalies
interface AnomalyPoint {
  date: string;
  count: number;
  z_score: number;
  is_anomaly: boolean;
  direction: "high" | "low" | null;
  rolling_mean: number;
  rolling_std: number;
}

interface OwnerStats {
  today_queue: number;
  calls_today: number;
  p95_response_time_seconds: number;
  qa_avg_score: number;
  calls_week: CallsWeekPoint[];
  top_objections: Objection[];
  lost_reason_themes: LostTheme[];
  occupancy_rate?: number;
  revenue_at_risk?: number;
  deltas?: Record<string, KPIDelta>;
  calls_week_prev?: CallsWeekPoint[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function exportChartCSV(data: CallsWeekPoint[], chartName: string) {
  const header = `# Chart: ${chartName}\n# Generated: ${new Date().toISOString()}\n`;
  const cols = "Date,Calls,Avg QA Score\n";
  const body = data.map(d => `${d.date},${d.count},${d.avg_score}`).join("\n");
  const blob = new Blob([header + cols + body], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `haip_${chartName.toLowerCase().replace(/ /g, "_")}_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Delta chip ───────────────────────────────────────────────────────────────

function DeltaChip({ delta, invertColor = false }: { delta: KPIDelta; invertColor?: boolean }) {
  const isUp = delta.direction === "up";
  const isDown = delta.direction === "down";
  // For metrics like response time, "up" is bad, so invert
  const positive = invertColor ? isDown : isUp;
  const negative = invertColor ? isUp : isDown;

  return (
    <span className={cn(
      "inline-flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded-full",
      positive ? "bg-teal-100 text-teal-700" :
      negative ? "bg-red-100 text-red-600" :
      "bg-gray-100 text-gray-500"
    )}>
      {isUp ? <ArrowUpRight size={9} /> : isDown ? <ArrowDownRight size={9} /> : <Minus size={8} />}
      {Math.abs(delta.pct)}%
    </span>
  );
}

// ─── Anomaly tooltip (A8) ─────────────────────────────────────────────────────

interface AnomalyTooltipProps {
  active?: boolean;
  // recharts TooltipPayloadEntry.value is ValueType | undefined — keep loose
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload?: readonly any[];
  label?: string | number;
  anomalyMap?: Record<string, AnomalyPoint>;
}

function AnomalyTooltip({ active, payload, label, anomalyMap = {} }: AnomalyTooltipProps) {
  if (!active || !payload?.length) return null;
  const labelStr = label != null ? String(label) : undefined;
  const anomaly = labelStr ? anomalyMap[labelStr] : null;
  return (
    <div
      className="bg-white border border-gray-200 rounded-xl p-3 shadow-md text-xs"
      style={{ minWidth: 152 }}
    >
      <p className="font-semibold text-gray-900 mb-1.5">
        {labelStr
          ? new Date(labelStr).toLocaleDateString("en-IN", {
              weekday: "short",
              day: "numeric",
              month: "short",
            })
          : labelStr}
      </p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="mb-0.5">
          {p.name}:{" "}
          <span className="font-mono font-bold">{p.value ?? "—"}</span>
        </p>
      ))}
      {anomaly?.is_anomaly && (
        <div
          className={cn(
            "mt-2 pt-2 border-t flex items-center gap-1.5 font-semibold",
            anomaly.direction === "high"
              ? "border-red-100 text-red-600"
              : "border-amber-100 text-amber-600",
          )}
        >
          <AlertCircle size={10} />
          <span>
            {anomaly.direction === "high" ? "Unusually high" : "Unusually low"}
            {" "}
            ({Math.abs(anomaly.z_score).toFixed(1)}σ)
          </span>
        </div>
      )}
    </div>
  );
}

// ─── KPI card ─────────────────────────────────────────────────────────────────

interface KPICardProps {
  label: string;
  value: string | number;
  subtext?: string;
  trend?: "up" | "down" | "neutral";
  icon: React.ReactNode;
  variant?: "default" | "warning" | "danger";
  metricKey?: string;
  delta?: KPIDelta;
  invertDeltaColor?: boolean;
  onClick?: () => void;
}

function KPICard({ label, value, subtext, trend, icon, variant = "default", delta, invertDeltaColor, onClick }: KPICardProps) {
  const TrendIcon =
    trend === "up" ? TrendingUp :
    trend === "down" ? TrendingDown :
    Minus;
  const trendColor =
    trend === "up" ? "#14B8A6" :
    trend === "down" ? "#f87171" :
    "#94a3b8";

  const iconBg =
    variant === "warning" ? "rgba(245,158,11,0.12)" :
    variant === "danger"  ? "rgba(248,113,113,0.12)" :
    "rgba(20,184,166,0.10)";
  const iconColor =
    variant === "warning" ? "#D97706" :
    variant === "danger"  ? "#ef4444" :
    "#0F766E";

  return (
    <div
      className="haip-card rounded-2xl p-5 transition-all"
      style={{
        border: variant === "warning"
          ? "1px solid rgba(245,158,11,0.3)"
          : variant === "danger"
          ? "1px solid rgba(248,113,113,0.3)"
          : "1px solid var(--haip-border)",
        cursor: onClick ? "pointer" : "default",
      }}
      onClick={onClick}
      onMouseEnter={e => {
        if (onClick) {
          (e.currentTarget as HTMLElement).style.borderColor = "#14B8A6";
          (e.currentTarget as HTMLElement).style.boxShadow = "0 0 0 1px #14B8A6";
        }
      }}
      onMouseLeave={e => {
        if (onClick) {
          (e.currentTarget as HTMLElement).style.borderColor =
            variant === "warning" ? "rgba(245,158,11,0.3)"
            : variant === "danger" ? "rgba(248,113,113,0.3)"
            : "var(--haip-border)";
          (e.currentTarget as HTMLElement).style.boxShadow = "";
        }
      }}
      title={onClick ? "Click to drill down" : undefined}
    >
      <div className="flex items-start justify-between mb-3">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
          style={{ background: iconBg, color: iconColor }}
        >
          {icon}
        </div>
        <div className="flex items-center gap-1.5">
          {delta && <DeltaChip delta={delta} invertColor={invertDeltaColor} />}
          {trend && <TrendIcon size={16} style={{ color: trendColor }} />}
        </div>
      </div>
      <p
        className="text-2xl font-black leading-none"
        style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}
      >
        {value}
      </p>
      <p className="text-[12px] mt-1" style={{ color: "var(--haip-fg-muted)" }}>{label}</p>
      {subtext && <p className="text-[11px] mt-0.5" style={{ color: "rgba(100,116,139,0.6)" }}>{subtext}</p>}
      {onClick && (
        <p className="text-[10px] mt-2 font-medium" style={{ color: "#14B8A6" }}>Drill down →</p>
      )}
    </div>
  );
}

// ─── Property filter dropdown ─────────────────────────────────────────────────

interface Property { id: string; name: string; }

function PropertyFilter({
  value,
  onChange,
}: {
  value: string[];
  onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const { data: props = [] } = useQuery<Property[]>({
    queryKey: ["properties-list-analytics"],
    queryFn: () => api.get("/properties").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  const label = value.length === 0
    ? "All properties"
    : value.length === 1
    ? (props.find(p => p.id === value[0])?.name ?? "1 property")
    : `${value.length} properties`;

  function toggle(id: string) {
    onChange(value.includes(id) ? value.filter(v => v !== id) : [...value, id]);
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 text-sm bg-white border border-gray-200 text-gray-700 px-3 py-2 rounded-xl font-medium hover:border-gray-300 transition-colors"
      >
        {label}
        <ChevronDown size={13} className="text-gray-400" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-1 z-40 w-52 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
            <div
              className={cn(
                "flex items-center gap-2 px-3 py-2.5 text-sm cursor-pointer hover:bg-gray-50 transition-colors",
                value.length === 0 && "bg-teal-50 text-teal-700"
              )}
              onClick={() => { onChange([]); setOpen(false); }}
            >
              <span className="flex-1 font-medium">All properties</span>
              {value.length === 0 && <span className="text-teal-500 text-xs">✓</span>}
            </div>
            {props.map(p => (
              <div
                key={p.id}
                className={cn(
                  "flex items-center gap-2 px-3 py-2.5 text-sm cursor-pointer hover:bg-gray-50 transition-colors",
                  value.includes(p.id) && "bg-teal-50 text-teal-700"
                )}
                onClick={() => toggle(p.id)}
              >
                <input
                  type="checkbox"
                  checked={value.includes(p.id)}
                  readOnly
                  className="w-3.5 h-3.5 accent-teal-500"
                />
                <span className="flex-1 truncate">{p.name}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // URL-persisted filter state (A2, A3)
  const compareTo = searchParams.get("compare_to") ?? "none";
  const propertyIdsParam = searchParams.get("property_ids") ?? "";
  const propertyIds = propertyIdsParam ? propertyIdsParam.split(",").filter(Boolean) : [];
  const rangeDays = searchParams.get("range_days") ?? "7";

  function setParam(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "" || value === "none") params.delete(key);
    else params.set(key, value);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  // A1 drill-down state
  const [drillMetric, setDrillMetric] = useState<{ key: string; label: string } | null>(null);

  // A4 lost-reason modal state
  const [lostTheme, setLostTheme] = useState<{ theme: string; label: string; count: number } | null>(null);

  const queryString = [
    `range_days=${rangeDays}`,
    compareTo !== "none" ? `compare_to=${compareTo}` : "",
    propertyIds.length > 0 ? `property_ids=${propertyIds.join(",")}` : "",
  ].filter(Boolean).join("&");

  const { data: stats, isLoading } = useQuery<OwnerStats>({
    queryKey: ["analytics", "owner-daily", queryString],
    queryFn: () => api.get(`/analytics/owner-daily?${queryString}`).then(r => r.data),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });

  // A8: anomaly detection data — fetched in parallel, not blocking
  const { data: anomalies = [] } = useQuery<AnomalyPoint[]>({
    queryKey: ["analytics", "anomalies", rangeDays, propertyIdsParam],
    queryFn: () =>
      api
        .get(`/analytics/anomalies?range_days=${rangeDays}${propertyIdsParam ? `&property_ids=${propertyIdsParam}` : ""}`)
        .then(r => r.data),
    staleTime: 5 * 60_000,
  });

  if (isLoading) return <AnalyticsSkeleton />;

  const s = stats ?? {} as OwnerStats;
  const p95Mins = Math.round((s.p95_response_time_seconds ?? 0) / 60);
  const p95Ok = p95Mins <= 3;

  // Merge current + previous series for comparison overlay
  const mergedCalls = (s.calls_week ?? []).map(d => ({
    ...d,
    count_prev: s.calls_week_prev?.find(p => {
      // align by day offset rather than absolute date
      return true; // simplified — just zip by index
    })?.count ?? null,
  }));
  // Zip by index for overlay
  const zippedCalls = (s.calls_week ?? []).map((d, i) => ({
    date: d.date,
    count: d.count,
    avg_score: d.avg_score,
    count_prev: s.calls_week_prev?.[i]?.count ?? null,
  }));

  // A8: build a date → AnomalyPoint lookup for O(1) tooltip + dot access
  const anomalyMap: Record<string, AnomalyPoint> = Object.fromEntries(
    anomalies.map(a => [a.date, a]),
  );
  const anomalyDots = anomalies.filter(a => a.is_anomaly);

  return (
    <div className="h-full flex flex-col" style={{ background: "var(--haip-surface)" }}>
      {/* ── Dark page header ─────────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 px-6 py-5"
        style={{
          background: "#FFFFFF",
          borderBottom: "1px solid #E5E7EB",
        }}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1
              className="text-[22px] font-bold leading-tight"
              style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
            >
              Analytics
            </h1>
            <p className="text-[13px] mt-0.5" style={{ color: "#6B7280" }}>
              {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
            </p>
          </div>

          {/* Filter controls (A2 + A3) */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Range selector */}
            <div className="relative">
              <select
                value={rangeDays}
                onChange={e => setParam("range_days", e.target.value)}
                className="appearance-none text-[13px] px-3 py-2 pr-7 rounded-xl font-medium cursor-pointer focus:outline-none"
                style={{
                  background: "#F9FAFB",
                  border: "1px solid #E5E7EB",
                  color: "#374151",
                }}
              >
                <option value="7">Last 7 days</option>
                <option value="14">Last 14 days</option>
                <option value="30">Last 30 days</option>
                <option value="90">Last 90 days</option>
              </select>
              <ChevronDown size={11} className="absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: "#9CA3AF" }} />
            </div>

            {/* Property filter (A3) */}
            <PropertyFilter
              value={propertyIds}
              onChange={ids => setParam("property_ids", ids.join(","))}
            />

            {/* Compare toggle (A2) */}
            <button
              onClick={() => setParam("compare_to", compareTo === "none" ? "previous_period" : "none")}
              className="text-[13px] px-3 py-2 rounded-xl font-semibold border transition-colors"
              style={
                compareTo !== "none"
                  ? { background: "#14B8A6", color: "#fff", border: "1px solid #14B8A6" }
                  : { background: "#F9FAFB", color: "#374151", border: "1px solid #E5E7EB" }
              }
            >
              {compareTo !== "none" ? "✓ Comparing" : "Compare period"}
            </button>
          </div>
        </div>
      </div>

      {/* ── Scrollable content ───────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto haip-scrollbar p-6 space-y-6 max-w-7xl mx-auto w-full">

      {/* KPI grid (A1: click to drill, A2: delta chips) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="Today's queue"
          value={s.today_queue ?? 0}
          subtext="Unanswered inquiries"
          icon={<Phone size={18} />}
          variant={(s.today_queue ?? 0) > 10 ? "warning" : "default"}
          delta={s.deltas?.today_queue}
          metricKey="today_queue"
          onClick={() => setDrillMetric({ key: "today_queue", label: "Today's queue" })}
        />
        <KPICard
          label="QA avg score"
          value={`${Math.round(s.qa_avg_score ?? 0)}`}
          subtext="This period · out of 100"
          trend={(s.qa_avg_score ?? 0) >= 75 ? "up" : "down"}
          icon={<Star size={18} />}
          variant={(s.qa_avg_score ?? 0) < 60 ? "danger" : "default"}
          delta={s.deltas?.qa_avg_score}
          metricKey="qa_avg_score"
          onClick={() => setDrillMetric({ key: "qa_avg_score", label: "QA avg score" })}
        />
        <KPICard
          label="p95 response time"
          value={`${p95Mins}m`}
          subtext="95th percentile · target ≤3m"
          trend={p95Ok ? "up" : "down"}
          icon={<Clock size={18} />}
          variant={!p95Ok ? "warning" : "default"}
          delta={s.deltas?.p95_response_time_seconds}
          invertDeltaColor
          metricKey="p95_response_time_seconds"
          onClick={() => setDrillMetric({ key: "p95_response_time_seconds", label: "p95 response time" })}
        />
        {s.revenue_at_risk != null ? (
          <KPICard
            label="Revenue at risk"
            value={`₹${((s.revenue_at_risk ?? 0) / 1000).toFixed(0)}k`}
            subtext="From unscored lost calls"
            icon={<AlertCircle size={18} />}
            variant={(s.revenue_at_risk ?? 0) > 100000 ? "danger" : "warning"}
            metricKey="revenue_at_risk"
            onClick={() => setDrillMetric({ key: "revenue_at_risk", label: "Revenue at risk" })}
          />
        ) : (
          <KPICard
            label="Occupancy rate"
            value={s.occupancy_rate != null ? `${Math.round(s.occupancy_rate * 100)}%` : "—"}
            subtext="This period"
            trend={s.occupancy_rate != null && s.occupancy_rate >= 0.7 ? "up" : "neutral"}
            icon={<TrendingUp size={18} />}
            metricKey="occupancy_rate"
            onClick={() => setDrillMetric({ key: "occupancy_rate", label: "Occupancy rate" })}
          />
        )}
      </div>

      <div className="grid grid-cols-12 gap-5">
        {/* Calls chart (A2: comparison overlay, A5: CSV export) */}
        <div className="col-span-12 lg:col-span-8 haip-card rounded-2xl p-5"
          style={{ border: "1px solid var(--haip-border)" }}
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <h2 className="text-[13px] font-semibold" style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}>
                Calls — last {rangeDays} days
                {compareTo !== "none" && (
                  <span className="ml-2 text-[11px] font-normal text-gray-400">(vs. previous period)</span>
                )}
              </h2>
              {/* A8: anomaly badge */}
              {anomalyDots.length > 0 && (
                <span
                  title={`${anomalyDots.length} day${anomalyDots.length > 1 ? "s" : ""} with unusual call volume detected`}
                  className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-red-50 text-red-500 border border-red-100 cursor-default select-none"
                >
                  <AlertCircle size={9} />
                  {anomalyDots.length} anomal{anomalyDots.length > 1 ? "ies" : "y"}
                </span>
              )}
            </div>
            {/* A5: CSV export */}
            {(s.calls_week?.length ?? 0) > 0 && (
              <button
                onClick={() => exportChartCSV(s.calls_week, "Calls this period")}
                title="Export CSV"
                className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 hover:bg-gray-100 px-2 py-1 rounded-lg transition-colors"
              >
                <Download size={12} /> CSV
              </button>
            )}
          </div>
          {(s.calls_week?.length ?? 0) > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={zippedCalls} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRAY_200} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: "#9ca3af" }}
                  tickLine={false} axisLine={false}
                  tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { weekday: "short" })}
                />
                <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                {/* A8: custom tooltip shows anomaly info on hover */}
                <Tooltip
                  content={(props) => (
                    <AnomalyTooltip
                      {...props}
                      anomalyMap={anomalyMap}
                    />
                  )}
                />
                <Bar dataKey="count" name="Calls" fill={TEAL_500} radius={[6, 6, 0, 0]} />
                {compareTo !== "none" && (
                  <Bar dataKey="count_prev" name="Prev. period" fill={TEAL_200} radius={[6, 6, 0, 0]} opacity={0.6} />
                )}
                {compareTo !== "none" && <Legend wrapperStyle={{ fontSize: "11px" }} />}
                {/* A8: anomaly marker dots — pulsing red (high) or amber (low) */}
                {anomalyDots.map((a) => (
                  <ReferenceDot
                    key={a.date}
                    x={a.date}
                    y={a.count}
                    r={6}
                    fill={a.direction === "high" ? RED_400 : AMBER_400}
                    stroke="white"
                    strokeWidth={2}
                    label={{
                      value: a.direction === "high" ? "▲" : "▼",
                      position: a.direction === "high" ? "top" : "bottom" as const,
                      fontSize: 9,
                      fill: a.direction === "high" ? RED_400 : AMBER_400,
                    }}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[220px] flex items-center justify-center text-sm text-gray-400">No data yet</div>
          )}
        </div>

        {/* Top objections */}
        <div className="col-span-12 lg:col-span-4 haip-card rounded-2xl p-5"
          style={{ border: "1px solid var(--haip-border)" }}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[13px] font-semibold" style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}>Top objections</h2>
          </div>
          {(s.top_objections?.length ?? 0) > 0 ? (
            <div className="space-y-2.5">
              {s.top_objections.slice(0, 5).map((obj, i) => {
                const maxCount = s.top_objections[0].count;
                const pct = (obj.count / maxCount) * 100;
                return (
                  <div key={i}>
                    <div className="flex justify-between text-[12px] mb-1">
                      <span className="truncate" style={{ color: "var(--haip-fg)" }}>{obj.text}</span>
                      <span className="font-mono ml-2" style={{ color: "var(--haip-fg-muted)" }}>{obj.count}</span>
                    </div>
                    <div className="h-1.5 rounded-full" style={{ background: "var(--haip-border)" }}>
                      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: "#F59E0B" }} />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-[12px] py-6 text-center" style={{ color: "var(--haip-fg-muted)" }}>No objection data yet</p>
          )}
        </div>
      </div>

      {/* Lost reason themes (A4: clickable) */}
      {(s.lost_reason_themes?.length ?? 0) > 0 && (
        <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[13px] font-semibold" style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}>Lost inquiry themes</h2>
            <p className="text-[11px]" style={{ color: "var(--haip-fg-muted)" }}>Click a theme to see inquiries</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {s.lost_reason_themes.map((t, i) => (
              <button
                key={i}
                onClick={() => setLostTheme({ theme: t.theme, label: t.theme.replace(/_/g, " "), count: t.count })}
                className="bg-red-50 border border-red-100 rounded-xl p-4 text-left hover:bg-red-100/60 hover:border-red-200 transition-colors group"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-semibold text-red-800 capitalize">
                    {t.theme.replace(/_/g, " ")}
                  </span>
                  <Badge variant="destructive" className="text-[10px]">{t.count}</Badge>
                </div>
                {t.root_cause && (
                  <p className="text-xs text-red-600">{t.root_cause}</p>
                )}
                <p className="text-[10px] text-red-400 mt-2 group-hover:text-red-600 transition-colors font-medium">
                  View inquiries →
                </p>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Drill-down panel (A1) */}
      {drillMetric && (
        <MetricDrillDown
          metricKey={drillMetric.key}
          metricLabel={drillMetric.label}
          onClose={() => setDrillMetric(null)}
        />
      )}

      {/* Lost-reason modal (A4) */}
      {lostTheme && (
        <LostReasonModal
          theme={lostTheme.theme}
          themeLabel={lostTheme.label}
          count={lostTheme.count}
          onClose={() => setLostTheme(null)}
        />
      )}
      </div> {/* end scrollable content */}
    </div>
  );
}

function AnalyticsSkeleton() {
  return (
    <div className="p-6 space-y-6">
      <div className="flex justify-between">
        <div className="space-y-2">
          <Skeleton className="h-6 w-40 rounded-xl" />
          <Skeleton className="h-4 w-28 rounded-xl" />
        </div>
        <div className="flex gap-2">
          {[1, 2, 3].map(i => <Skeleton key={i} className="h-10 w-28 rounded-xl" />)}
        </div>
      </div>
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
      </div>
      <div className="grid grid-cols-12 gap-5">
        <Skeleton className="col-span-8 h-64 rounded-2xl" />
        <Skeleton className="col-span-4 h-64 rounded-2xl" />
      </div>
    </div>
  );
}
