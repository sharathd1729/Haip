"use client";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from "recharts";
import { TrendingUp, TrendingDown, Minus, Phone, Star, Clock, AlertCircle } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface OwnerStats {
  today_queue: number;
  p95_response_time_seconds: number;
  qa_avg_score: number;
  top_objections: Array<{ text: string; count: number }>;
  lost_reason_themes: Array<{ theme: string; count: number; root_cause?: string }>;
  occupancy_rate?: number;
  calls_today: number;
  calls_week: Array<{ date: string; count: number; avg_score: number }>;
  revenue_at_risk?: number;
}

const TEAL_500 = "#14b8a6";
const AMBER_400 = "#fbbf24";
const RED_400 = "#f87171";
const GRAY_200 = "#e5e7eb";

const PIE_COLORS = [TEAL_500, AMBER_400, "#60a5fa", "#a78bfa", RED_400];

// ─── KPI card ─────────────────────────────────────────────────────────────────

interface KPICardProps {
  label: string;
  value: string | number;
  subtext?: string;
  trend?: "up" | "down" | "neutral";
  icon: React.ReactNode;
  variant?: "default" | "warning" | "danger";
}

function KPICard({ label, value, subtext, trend, icon, variant = "default" }: KPICardProps) {
  const TrendIcon =
    trend === "up" ? TrendingUp :
    trend === "down" ? TrendingDown :
    Minus;
  const trendColor =
    trend === "up" ? "text-teal-500" :
    trend === "down" ? "text-red-400" :
    "text-gray-400";

  return (
    <div className={cn(
      "bg-white border rounded-2xl p-5 shadow-sm",
      variant === "warning" ? "border-amber-200 bg-amber-50/30" :
      variant === "danger" ? "border-red-200 bg-red-50/30" :
      "border-gray-100"
    )}>
      <div className="flex items-start justify-between mb-3">
        <div className={cn(
          "w-9 h-9 rounded-xl flex items-center justify-center",
          variant === "warning" ? "bg-amber-100 text-amber-600" :
          variant === "danger" ? "bg-red-100 text-red-500" :
          "bg-teal-50 text-teal-600"
        )}>
          {icon}
        </div>
        {trend && <TrendIcon size={16} className={trendColor} />}
      </div>
      <p className="text-2xl font-black text-gray-900">{value}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
      {subtext && <p className="text-[11px] text-gray-400 mt-1">{subtext}</p>}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const { data: stats, isLoading } = useQuery<OwnerStats>({
    queryKey: ["analytics", "owner-daily"],
    queryFn: () => api.get("/analytics/owner-daily").then(r => r.data),
    staleTime: 60_000,
    refetchInterval: 5 * 60 * 1000, // refresh every 5 min
  });

  if (isLoading) return <AnalyticsSkeleton />;

  const s = stats ?? {} as OwnerStats;
  const p95Mins = Math.round((s.p95_response_time_seconds ?? 0) / 60);
  const p95Ok = p95Mins <= 3;

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Owner dashboard</h1>
        <p className="text-sm text-gray-400 mt-0.5">
          {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
        </p>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="Today's queue"
          value={s.today_queue ?? 0}
          subtext="Unanswered inquiries"
          icon={<Phone size={18} />}
          variant={(s.today_queue ?? 0) > 10 ? "warning" : "default"}
        />
        <KPICard
          label="QA avg score"
          value={`${Math.round(s.qa_avg_score ?? 0)}`}
          subtext="Last 30 days · out of 100"
          trend={(s.qa_avg_score ?? 0) >= 75 ? "up" : "down"}
          icon={<Star size={18} />}
          variant={(s.qa_avg_score ?? 0) < 60 ? "danger" : "default"}
        />
        <KPICard
          label="p95 response time"
          value={`${p95Mins}m`}
          subtext="95th percentile · target ≤3m"
          trend={p95Ok ? "up" : "down"}
          icon={<Clock size={18} />}
          variant={!p95Ok ? "warning" : "default"}
        />
        {s.revenue_at_risk != null ? (
          <KPICard
            label="Revenue at risk"
            value={`₹${(s.revenue_at_risk / 1000).toFixed(0)}k`}
            subtext="From unscored lost calls"
            icon={<AlertCircle size={18} />}
            variant={s.revenue_at_risk > 100000 ? "danger" : "warning"}
          />
        ) : (
          <KPICard
            label="Occupancy rate"
            value={s.occupancy_rate != null ? `${Math.round(s.occupancy_rate * 100)}%` : "—"}
            subtext="This month"
            trend={s.occupancy_rate != null && s.occupancy_rate >= 0.7 ? "up" : "neutral"}
            icon={<TrendingUp size={18} />}
          />
        )}
      </div>

      <div className="grid grid-cols-12 gap-5">
        {/* Calls this week */}
        <div className="col-span-12 lg:col-span-8 bg-white border border-gray-100 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Calls this week</h2>
          {(s.calls_week?.length ?? 0) > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={s.calls_week} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRAY_200} />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                  tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { weekday: "short" })} />
                <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{ borderRadius: "12px", border: "1px solid #e5e7eb", boxShadow: "0 4px 6px -1px rgba(0,0,0,.1)" }}
                  labelStyle={{ fontSize: "12px", fontWeight: 600 }}
                  itemStyle={{ fontSize: "12px" }}
                />
                <Bar dataKey="count" name="Calls" fill={TEAL_500} radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[220px] flex items-center justify-center text-sm text-gray-400">No data yet</div>
          )}
        </div>

        {/* Top objections / lost reasons */}
        <div className="col-span-12 lg:col-span-4 bg-white border border-gray-100 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Top objections</h2>
          {(s.top_objections?.length ?? 0) > 0 ? (
            <>
              <div className="space-y-2.5 mb-4">
                {s.top_objections.slice(0, 5).map((obj, i) => {
                  const maxCount = s.top_objections[0].count;
                  const pct = (obj.count / maxCount) * 100;
                  return (
                    <div key={i}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-gray-700 truncate">{obj.text}</span>
                        <span className="text-gray-400 font-mono ml-2">{obj.count}</span>
                      </div>
                      <div className="h-1.5 bg-gray-100 rounded-full">
                        <div className="h-full bg-amber-400 rounded-full" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <p className="text-xs text-gray-400 py-6 text-center">No objection data yet</p>
          )}
        </div>
      </div>

      {/* Lost reason themes */}
      {(s.lost_reason_themes?.length ?? 0) > 0 && (
        <div className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Lost inquiry themes</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {s.lost_reason_themes.map((t, i) => (
              <div key={i} className="bg-red-50 border border-red-100 rounded-xl p-4">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-semibold text-red-800">{t.theme}</span>
                  <Badge variant="destructive" className="text-[10px]">{t.count}</Badge>
                </div>
                {t.root_cause && (
                  <p className="text-xs text-red-600">{t.root_cause}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AnalyticsSkeleton() {
  return (
    <div className="p-6 space-y-6">
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
      </div>
      <Skeleton className="h-64 rounded-2xl" />
    </div>
  );
}
