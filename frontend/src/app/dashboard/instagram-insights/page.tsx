"use client";

import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { Eye, Users, UserPlus, Instagram } from "@/lib/icons";
import { KpiCard } from "@/components/analytics/KpiCard";
import { Skeleton } from "@/components/ui/skeleton";
import api from "@/lib/api";

const TEAL = "#14b8a6"; const PINK = "#e1306c"; const AMBER = "#fbbf24"; const GRAY = "#e5e7eb";

interface InstagramInsightPoint {
  date: string;
  reach: number | null;
  profile_views: number | null;
  follower_count: number | null;
}

interface InstagramInsightsResponse {
  connected: boolean;
  points: InstagramInsightPoint[];
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-52 rounded-xl" />
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">{[1,2,3].map(i => <Skeleton key={i} className="h-28 rounded-2xl" />)}</div>
      <Skeleton className="h-72 rounded-2xl" />
    </div>
  );
}

export default function InstagramInsightsPage() {
  const { data: s, isLoading } = useQuery<InstagramInsightsResponse>({
    queryKey: ["analytics", "instagram-insights"],
    queryFn: () => api.get("/instagram-insights", { params: { range_days: 30 } }).then(r => r.data),
    staleTime: 5 * 60_000,
  });

  if (isLoading) return <PageSkeleton />;

  const points = s?.points ?? [];
  const latest = points[points.length - 1];
  const prev = points[points.length - 2];

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>
      <div className="flex-shrink-0 px-6 py-4 border-b bg-white" style={{ borderColor: "var(--haip-border)" }}>
        <div className="flex items-center gap-2">
          <Instagram size={16} style={{ color: PINK }} />
          <h1 className="haip-page-title">Instagram Insights</h1>
        </div>
        <p className="text-[12px] mt-0.5 text-gray-400">Organic reach, profile views &amp; follower growth &mdash; last 30 days</p>
      </div>

      <div className="flex-1 overflow-y-auto haip-scrollbar px-6 py-5 space-y-5">
        {!s?.connected ? (
          <div className="haip-card rounded-2xl p-8 text-center" style={{ border: "1px solid var(--haip-border)" }}>
            <Instagram size={28} style={{ color: PINK, margin: "0 auto" }} className="mb-3" />
            <p className="text-sm font-semibold text-gray-700 mb-1">No Instagram insights yet</p>
            <p className="text-[12px] text-gray-400">
              Snapshots are collected once daily once Instagram is connected in Settings &rarr; Integrations.
              Check back tomorrow, or reconnect if it was recently disconnected.
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <KpiCard label="Reach (yesterday)" value={latest?.reach?.toLocaleString("en-IN") ?? "—"}
                icon={<Eye size={18} />} />
              <KpiCard label="Profile Views (yesterday)" value={latest?.profile_views?.toLocaleString("en-IN") ?? "—"}
                icon={<UserPlus size={18} />} />
              <KpiCard label="Followers" value={latest?.follower_count?.toLocaleString("en-IN") ?? "—"}
                icon={<Users size={18} />} />
            </div>

            <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
              <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
                Reach &amp; Profile Views Over Time
              </h2>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={points} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                    interval={Math.max(0, Math.floor(points.length / 6) - 1)} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <Tooltip labelFormatter={d => new Date(d as string).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} />
                  <Legend wrapperStyle={{ fontSize: "11px" }} />
                  <Line type="monotone" dataKey="reach" name="Reach" stroke={PINK} strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="profile_views" name="Profile Views" stroke={TEAL} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
              <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
                Follower Count Trend
              </h2>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={points} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                    interval={Math.max(0, Math.floor(points.length / 6) - 1)} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <Tooltip labelFormatter={d => new Date(d as string).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} />
                  <Line type="monotone" dataKey="follower_count" name="Followers" stroke={AMBER} strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
