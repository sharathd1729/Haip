"use client";


import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { AlertTriangle, Users, DollarSign, Clock } from "lucide-react";
import { KpiCard } from "@/components/analytics/KpiCard";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface ChurnGuest {
  guest_id: string;
  name: string;
  phone: string;
  total_stays: number;
  lifetime_value: number;
  days_since_contact: number;
  risk_score: number;
  risk_label: "high" | "medium" | "low";
}
interface ChurnBucket {
  bucket: string;
  count: number;
  avg_ltv: number;
}
interface ChurnStats {
  total_at_risk: number;
  high_risk_count: number;
  medium_risk_count: number;
  revenue_at_risk: number;
  avg_days_since_contact: number;
  buckets: ChurnBucket[];
  at_risk_guests: ChurnGuest[];
}

function fmt(n: number) {
  if (n >= 100000) return `â‚¹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `â‚¹${(n / 1000).toFixed(0)}k`;
  return `â‚¹${Math.round(n)}`;
}

const RISK_CFG = {
  high:   { bg: "bg-red-100",   text: "text-red-700",   bar: "#ef4444" },
  medium: { bg: "bg-amber-100", text: "text-amber-700", bar: "#f59e0b" },
  low:    { bg: "bg-blue-100",  text: "text-blue-700",  bar: "#60a5fa" },
};

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-52" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}
      </div>
      <Skeleton className="h-52 rounded-2xl" />
      <Skeleton className="h-72 rounded-2xl" />
    </div>
  );
}

export default function ChurnPage() {
  const { data: s, isLoading, isError } = useQuery<ChurnStats>({
    queryKey: ["churn-risk"],
    queryFn: () => api.get("/analytics/forecasting/churn").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  if (isLoading) return <PageSkeleton />;
  if (isError || !s) return <div className="p-6 text-center text-sm text-gray-400">Failed to load churn data.</div>;

  const bucketChart = s.buckets.map(b => ({ name: b.bucket, count: b.count, ltv: b.avg_ltv }));

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="haip-page-title">Guest Churn Risk</h1>
        <p className="text-[12px] mt-0.5 text-gray-400">Returning guests with no recent contact and no open inquiry</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Total At-Risk" value={s.total_at_risk}
          icon={<Users size={14} className="text-amber-500" />} />
        <KpiCard label="High Risk" value={s.high_risk_count}
          icon={<AlertTriangle size={14} className="text-red-500" />} />
        <KpiCard label="Revenue at Risk" value={fmt(s.revenue_at_risk)}
          icon={<DollarSign size={14} className="text-teal-500" />} />
        <KpiCard label="Avg Days Silent" value={`${s.avg_days_since_contact}d`}
          icon={<Clock size={14} className="text-gray-400" />} />
      </div>

      {/* Bucket chart */}
      <div className="haip-card p-5">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">At-Risk Guest Buckets by Days Silent</h2>
        {bucketChart.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-8">No at-risk guests found.</p>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={bucketChart} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
              <Tooltip />
              <Bar dataKey="count" radius={[6, 6, 0, 0]} name="Guests">
                {bucketChart.map((_, i) => (
                  <Cell key={i} fill={i === 0 ? "#f59e0b" : i === 1 ? "#f97316" : "#ef4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Guest table */}
      <div className="haip-card p-5 overflow-x-auto">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">At-Risk Guest List</h2>
        {s.at_risk_guests.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-8">No at-risk guests.</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-400 border-b border-gray-100">
                <th className="text-left pb-2 font-medium">Guest</th>
                <th className="text-right pb-2 font-medium">Stays</th>
                <th className="text-right pb-2 font-medium">LTV</th>
                <th className="text-right pb-2 font-medium">Days Silent</th>
                <th className="text-right pb-2 font-medium">Risk</th>
                <th className="text-right pb-2 font-medium">Score</th>
              </tr>
            </thead>
            <tbody>
              {s.at_risk_guests.map(g => {
                const cfg = RISK_CFG[g.risk_label] ?? RISK_CFG.medium;
                return (
                  <tr key={g.guest_id} className="border-b border-gray-50 hover:bg-gray-50/60">
                    <td className="py-2.5">
                      <p className="font-medium text-gray-800">{g.name}</p>
                      <p className="text-gray-400">{g.phone}</p>
                    </td>
                    <td className="text-right py-2.5 text-gray-700">{g.total_stays}</td>
                    <td className="text-right py-2.5 text-gray-700">{fmt(g.lifetime_value)}</td>
                    <td className="text-right py-2.5 text-gray-700">{g.days_since_contact}d</td>
                    <td className="text-right py-2.5">
                      <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-semibold", cfg.bg, cfg.text)}>
                        {g.risk_label}
                      </span>
                    </td>
                    <td className="text-right py-2.5">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                          <div className="h-full rounded-full"
                            style={{ width: `${g.risk_score}%`, background: g.risk_label === "high" ? "#ef4444" : g.risk_label === "medium" ? "#f59e0b" : "#60a5fa" }} />
                        </div>
                        <span className="text-gray-500">{g.risk_score}</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
