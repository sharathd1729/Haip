"use client";

import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { Eye, Users, UserPlus, Instagram, Heart, MessageSquare, Send, Image as ImageIcon } from "@/lib/icons";
import { KpiCard } from "@/components/analytics/KpiCard";
import { Skeleton } from "@/components/ui/skeleton";
import api from "@/lib/api";
import { useIsPhone } from "@/lib/useIsPhone";

const TEAL = "var(--primary)"; const PINK = "#e1306c"; const AMBER = "#fbbf24"; const GRAY = "#e5e7eb";

interface InstagramInsightPoint {
  date: string;
  reach: number | null;
  profile_views: number | null;
  follower_count: number | null;
}

interface InstagramOverview {
  followers_count: number | null;
  following_count: number | null;
  media_count: number | null;
  accounts_engaged: number | null;
  total_interactions: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  replies: number | null;
  profile_links_taps: number | null;
}

interface DemographicResult { label: string; value: number }

interface InstagramPost {
  media_id: string;
  caption: string | null;
  media_type: string | null;
  permalink: string | null;
  thumbnail_url: string | null;
  posted_at: string | null;
  like_count: number | null;
  comments_count: number | null;
  reach: number | null;
  saved: number | null;
  shares: number | null;
  total_interactions: number | null;
}

interface InstagramInsightsResponse {
  connected: boolean;
  overview: InstagramOverview | null;
  trend: InstagramInsightPoint[];
  demographics: Record<string, DemographicResult[]>;
  posts: InstagramPost[];
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-5">
      <Skeleton className="h-7 w-52 rounded-xl" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">{[1,2,3,4].map(i => <Skeleton key={i} className="h-24 rounded-2xl" />)}</div>
      <Skeleton className="h-72 rounded-2xl" />
    </div>
  );
}

function DemographicBar({ title, results }: { title: string; results: DemographicResult[] }) {
  const max = Math.max(...results.map(r => r.value), 1);
  return (
    <div>
      <p className="text-[11px] font-semibold text-[var(--haip-fg-subtle)] mb-2">{title}</p>
      {results.length === 0 ? (
        <p className="text-[11px] text-[var(--haip-fg-subtle)]">Not enough data yet</p>
      ) : (
        <div className="space-y-1.5">
          {results.map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="w-24 text-[10px] text-[var(--haip-fg-subtle)] flex-shrink-0 truncate" title={r.label}>{r.label}</span>
              <div className="flex-1 h-3.5 rounded-full overflow-hidden" style={{ background: GRAY }}>
                <div className="h-full rounded-full" style={{ width: `${(r.value / max) * 100}%`, background: PINK }} />
              </div>
              <span className="w-8 text-right text-[10px] font-mono font-bold text-[var(--haip-fg-2)]">{r.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function InstagramInsightsPage() {
  const { data: s, isLoading } = useQuery<InstagramInsightsResponse>({
    queryKey: ["instagram-insights"],
    queryFn: () => api.get("/instagram-insights", { params: { range_days: 30 } }).then(r => r.data),
    staleTime: 5 * 60_000,
  });
  const phone = useIsPhone();

  if (isLoading) return <PageSkeleton />;

  const trend = s?.trend ?? [];
  const overview = s?.overview;
  const posts = s?.posts ?? [];
  const demographics = s?.demographics ?? {};
  const hasDemographics = Object.values(demographics).some(v => v.length > 0);

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--haip-surface)" }}>
      <div className="flex-shrink-0 px-6 py-4 border-b bg-white" style={{ borderColor: "var(--haip-border)" }}>
        <div className="flex items-center gap-2">
          <Instagram size={16} style={{ color: PINK }} />
          <h1 className="haip-page-title">Instagram Insights</h1>
        </div>
        <p className="text-[12px] mt-0.5 text-[var(--haip-fg-subtle)]">Followers, engagement, audience &amp; post performance &mdash; last 30 days</p>
      </div>

      <div className="flex-1 overflow-y-auto haip-scrollbar px-6 py-5 space-y-5">
        {!s?.connected ? (
          <div className="haip-card rounded-2xl p-8 text-center" style={{ border: "1px solid var(--haip-border)" }}>
            <Instagram size={28} style={{ color: PINK, margin: "0 auto" }} className="mb-3" />
            <p className="text-sm font-semibold text-[var(--haip-fg-2)] mb-1">No Instagram insights yet</p>
            <p className="text-[12px] text-[var(--haip-fg-subtle)]">
              Snapshots are collected once daily once Instagram is connected in Settings &rarr; Integrations.
              Check back tomorrow, or reconnect if it was recently disconnected.
            </p>
          </div>
        ) : (
          <>
            {/* Account overview */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <KpiCard label="Followers" value={overview?.followers_count?.toLocaleString("en-IN") ?? "—"}
                icon={<Users size={18} />} />
              <KpiCard label="Following" value={overview?.following_count?.toLocaleString("en-IN") ?? "—"}
                icon={<UserPlus size={18} />} />
              <KpiCard label="Posts" value={overview?.media_count?.toLocaleString("en-IN") ?? "—"}
                icon={<ImageIcon size={18} />} />
              <KpiCard label="Reach (yesterday)" value={trend[trend.length - 1]?.reach?.toLocaleString("en-IN") ?? "—"}
                icon={<Eye size={18} />} />
            </div>

            {/* Engagement totals */}
            <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
              <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
                Engagement (yesterday)
              </h2>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <KpiCard label="Accounts Engaged" value={overview?.accounts_engaged?.toLocaleString("en-IN") ?? "—"} icon={<Users size={16} />} />
                <KpiCard label="Total Interactions" value={overview?.total_interactions?.toLocaleString("en-IN") ?? "—"} icon={<Heart size={16} />} />
                <KpiCard label="Likes" value={overview?.likes?.toLocaleString("en-IN") ?? "—"} icon={<Heart size={16} />} />
                <KpiCard label="Comments" value={overview?.comments?.toLocaleString("en-IN") ?? "—"} icon={<MessageSquare size={16} />} />
                <KpiCard label="Shares" value={overview?.shares?.toLocaleString("en-IN") ?? "—"} icon={<Send size={16} />} />
                <KpiCard label="Saves" value={overview?.saves?.toLocaleString("en-IN") ?? "—"} icon={<Heart size={16} />} />
                <KpiCard label="Replies" value={overview?.replies?.toLocaleString("en-IN") ?? "—"} icon={<MessageSquare size={16} />} />
                <KpiCard label="Bio Link Taps" value={overview?.profile_links_taps?.toLocaleString("en-IN") ?? "—"} icon={<Send size={16} />} />
              </div>
            </div>

            {/* Trend charts */}
            <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
              <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
                Reach &amp; Profile Views Over Time
              </h2>
              {/* Phones: the two totals for the period instead of a two-line chart (mobile-first plan). */}
              {phone ? (
                <dl className="grid grid-cols-2 gap-3 text-[13px]">
                  {([["Reach", "reach"], ["Profile views", "profile_views"]] as const).map(([label, key]) => (
                    <div key={key}>
                      <dt className="text-[var(--haip-fg-subtle)]">{label}</dt>
                      <dd className="font-[family-name:var(--font-display)] text-[22px] font-semibold tabular-nums text-[var(--haip-fg)]">
                        {trend.reduce((n, d) => n + (Number(d[key]) || 0), 0).toLocaleString("en-IN")}
                      </dd>
                    </div>
                  ))}
                  <p className="col-span-2 text-[12px] text-[var(--haip-fg-subtle)]">Last 30 days, added up per day</p>
                </dl>
              ) : (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={trend} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                    interval={Math.max(0, Math.floor(trend.length / 6) - 1)} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <Tooltip labelFormatter={d => new Date(d as string).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} />
                  <Legend wrapperStyle={{ fontSize: "11px" }} />
                  <Line type="monotone" dataKey="reach" name="Reach" stroke={PINK} strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="profile_views" name="Profile Views" stroke={TEAL} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
              )}
            </div>

            <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
              <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
                Follower Count Trend
              </h2>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={trend} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRAY} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                    tickFormatter={d => new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                    interval={Math.max(0, Math.floor(trend.length / 6) - 1)} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <Tooltip labelFormatter={d => new Date(d as string).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} />
                  <Line type="monotone" dataKey="follower_count" name="Followers" stroke={AMBER} strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Audience demographics */}
            <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
              <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
                Audience Demographics
              </h2>
              {!hasDemographics ? (
                <p className="text-[12px] text-[var(--haip-fg-subtle)]">
                  Not enough follower data yet for a demographic breakdown. This fills in automatically once Meta has enough audience data for this account.
                </p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-5">
                  <DemographicBar title="Top Cities" results={demographics.city ?? []} />
                  <DemographicBar title="Top Countries" results={demographics.country ?? []} />
                  <DemographicBar title="Age Range" results={demographics.age ?? []} />
                  <DemographicBar title="Gender" results={demographics.gender ?? []} />
                </div>
              )}
            </div>

            {/* Recent posts */}
            <div className="haip-card rounded-2xl p-5" style={{ border: "1px solid var(--haip-border)" }}>
              <h2 className="text-[13px] font-semibold mb-4" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}>
                Recent Posts
              </h2>
              {posts.length === 0 ? (
                <p className="text-[12px] text-[var(--haip-fg-subtle)] py-4 text-center">No posts synced yet</p>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                  {posts.map(p => (
                    <a key={p.media_id} href={p.permalink ?? "#"} target="_blank" rel="noopener noreferrer"
                      className="block rounded-xl overflow-hidden border hover:shadow-md transition-shadow"
                      style={{ borderColor: "var(--haip-border)" }}>
                      <div className="aspect-square bg-[var(--haip-status-neutral-bg)] flex items-center justify-center overflow-hidden">
                        {p.thumbnail_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={p.thumbnail_url} alt={p.caption ?? "Instagram post"} className="w-full h-full object-cover" />
                        ) : (
                          <ImageIcon size={24} className="text-[var(--haip-fg-subtle)]/70" />
                        )}
                      </div>
                      <div className="p-2.5">
                        <p className="text-[10px] text-[var(--haip-fg-subtle)] truncate mb-1">{p.caption ?? "—"}</p>
                        <div className="flex items-center gap-2.5 text-[10px] text-[var(--haip-fg-subtle)]">
                          <span className="flex items-center gap-0.5"><Heart size={10} />{p.like_count ?? 0}</span>
                          <span className="flex items-center gap-0.5"><MessageSquare size={10} />{p.comments_count ?? 0}</span>
                          {p.reach != null && <span className="flex items-center gap-0.5"><Eye size={10} />{p.reach}</span>}
                        </div>
                      </div>
                    </a>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
