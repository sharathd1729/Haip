"use client";

/**
 * S7 — Meta WABA Quality Rating widget
 *
 * Shows current quality_rating (GREEN/YELLOW/RED) + messaging_limit_tier,
 * a 30-day trend chart (recharts), and actionable guidance when rating drops.
 *
 * Backend: GET /integrations/meta/quality?days=30
 * Data is polled hourly by the `meta_quality.poll_all_tenants` Celery beat task.
 */

import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { Shield, Wifi, AlertTriangle, CheckCircle2, RefreshCw, ExternalLink, Info, TrendingUp, TrendingDown, Minus } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import Link from "next/link";

// ── Types ─────────────────────────────────────────────────────────────────────

interface QualitySnapshot {
  ts: string | null;
  quality_rating: "GREEN" | "YELLOW" | "RED" | "UNKNOWN" | null;
  messaging_limit_tier: string | null;
}

interface QualityResponse {
  current: {
    quality_rating: string | null;
    messaging_limit_tier: string | null;
    polled_at: string | null;
  };
  snapshots: QualitySnapshot[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const RATING_CONFIG = {
  GREEN: {
    label: "Green — Healthy",
    color: "#16a34a",
    bg: "bg-green-50",
    border: "border-green-200",
    text: "text-green-700",
    icon: <CheckCircle2 size={18} className="text-green-600" />,
    dot: "bg-green-500",
  },
  YELLOW: {
    label: "Yellow — At Risk",
    color: "#ca8a04",
    bg: "bg-yellow-50",
    border: "border-yellow-300",
    text: "text-yellow-700",
    icon: <AlertTriangle size={18} className="text-yellow-600" />,
    dot: "bg-yellow-400",
  },
  RED: {
    label: "Red — Critical",
    color: "#dc2626",
    bg: "bg-red-50",
    border: "border-red-300",
    text: "text-red-700",
    icon: <AlertTriangle size={18} className="text-red-600" />,
    dot: "bg-red-500",
  },
  UNKNOWN: {
    label: "Unknown",
    color: "#9ca3af",
    bg: "bg-gray-50",
    border: "border-gray-200",
    text: "text-gray-600",
    icon: <Info size={18} className="text-gray-400" />,
    dot: "bg-gray-400",
  },
};

const ratingScore = (r: string | null) => {
  if (r === "GREEN") return 3;
  if (r === "YELLOW") return 2;
  if (r === "RED") return 1;
  return 0;
};

const TIER_LABELS: Record<string, string> = {
  TIER_1K:    "1,000 conversations/day",
  TIER_10K:   "10,000 conversations/day",
  TIER_100K:  "100,000 conversations/day",
  TIER_UNLIMITED: "Unlimited",
};

function formatTier(tier: string | null): string {
  if (!tier) return "—";
  return TIER_LABELS[tier] ?? tier.replace(/_/g, " ");
}

const YELLOW_FIXES = [
  "Review template opt-out rates — remove templates with >10% opt-outs",
  "Ensure all marketing messages have clear value and aren't misleading",
  "Check for high block rates by reviewing recent broadcast reports",
  "Verify templates follow the approved category (utility vs. marketing)",
  "Reduce send frequency if guests are getting too many messages",
];

const RED_FIXES = [
  "Immediately pause all non-utility (marketing) template broadcasts",
  "Submit a review request via Meta Business Support Center",
  "Audit and delete any templates rejected or with very high opt-outs",
  "Contact Meta directly if messaging tier has been restricted",
  "Review all recent WhatsApp activity for policy violations",
  "Set AI concierge to manual-only mode until rating recovers",
];

// ── Component ─────────────────────────────────────────────────────────────────

export default function MetaQualityPage() {
  const { data, isLoading, isError, refetch, isFetching } = useQuery<QualityResponse>({
    queryKey: ["meta-quality"],
    queryFn: () => api.get("/integrations/meta/quality?days=30").then(r => r.data),
    refetchInterval: 60_000, // re-poll every 60s to stay current
    staleTime: 30_000,
  });

  const current = data?.current;
  const rating = (current?.quality_rating ?? "UNKNOWN") as keyof typeof RATING_CONFIG;
  const ratingCfg = RATING_CONFIG[rating] ?? RATING_CONFIG.UNKNOWN;

  // Build chart data — sample to 1 per hour for readability
  const chartData = (data?.snapshots ?? []).map(s => ({
    ts: s.ts ? new Date(s.ts).toLocaleString("en-IN", { month: "short", day: "numeric", hour: "numeric" }) : "",
    score: ratingScore(s.quality_rating),
    rating: s.quality_rating ?? "UNKNOWN",
  }));

  // Trend: compare last 3 points
  const trend = (() => {
    const pts = chartData.slice(-4);
    if (pts.length < 2) return "stable";
    const first = pts[0].score;
    const last = pts[pts.length - 1].score;
    if (last > first) return "up";
    if (last < first) return "down";
    return "stable";
  })();

  const TrendIcon = trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus;
  const trendColor = trend === "up" ? "text-green-600" : trend === "down" ? "text-red-500" : "text-gray-400";

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="haip-page-title haip-page-title--keep flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-[#1877F2]/10 flex items-center justify-center">
              <Wifi size={16} className="text-[#1877F2]" />
            </div>
            Meta WABA Quality
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            WhatsApp Business API quality rating and messaging tier — polled hourly
          </p>
        </div>
        <div className="flex items-center gap-3">
          {current?.polled_at && (
            <span className="text-xs text-gray-400">
              Last polled {new Date(current.polled_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-900 border border-gray-200 hover:border-gray-300 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={cn(isFetching && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="grid sm:grid-cols-2 gap-4">
          {[1, 2].map(i => (
            <div key={i} className="h-28 bg-gray-100 rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : isError ? (
        <div className="bg-gray-50 border border-gray-200 rounded-2xl p-8 text-center">
          <p className="text-sm text-gray-500">Could not load quality data. Make sure WhatsApp is connected and the poll task is running.</p>
          <Link href="/dashboard/settings/integrations" className="text-sm text-teal-600 hover:underline mt-2 inline-block">
            Check integrations →
          </Link>
        </div>
      ) : (
        <>
          {/* ── Current state cards ── */}
          <div className="grid sm:grid-cols-2 gap-4">
            {/* Quality rating */}
            <div className={cn("rounded-2xl border p-5 shadow-sm", ratingCfg.bg, ratingCfg.border)}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Quality Rating</p>
                  <div className="flex items-center gap-2">
                    {ratingCfg.icon}
                    <span className={cn("text-lg font-bold", ratingCfg.text)}>{ratingCfg.label}</span>
                  </div>
                </div>
                <div className={cn("w-3 h-3 rounded-full mt-1 flex-shrink-0", ratingCfg.dot)} />
              </div>
              <div className="flex items-center gap-1.5 mt-3">
                <TrendIcon size={13} className={trendColor} />
                <span className={cn("text-xs font-medium", trendColor)}>
                  {trend === "up" ? "Improving" : trend === "down" ? "Declining" : "Stable"} (30d)
                </span>
              </div>
            </div>

            {/* Messaging tier */}
            <div className="rounded-2xl border border-gray-200 p-5 bg-white shadow-sm">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Messaging Tier</p>
              <div className="flex items-center gap-2">
                <Shield size={18} className="text-blue-500" />
                <span className="text-lg font-bold text-gray-900">
                  {formatTier(current?.messaging_limit_tier ?? null)}
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-3">
                Maximum conversations per rolling 24-hour window.{" "}
                <a
                  href="https://developers.facebook.com/docs/whatsapp/api/rate-limits#messaging"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-500 hover:underline inline-flex items-center gap-0.5"
                >
                  Learn more <ExternalLink size={10} />
                </a>
              </p>
            </div>
          </div>

          {/* ── Alert banners ── */}
          {rating === "YELLOW" && (
            <div className="bg-yellow-50 border border-yellow-300 rounded-2xl p-5">
              <div className="flex items-start gap-3">
                <AlertTriangle size={18} className="text-yellow-600 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-bold text-yellow-800 mb-2">Rating at risk — action recommended</p>
                  <p className="text-xs text-yellow-700 mb-3">
                    Meta may restrict your messaging tier if the quality score doesn&apos;t improve.
                    Take these steps to recover:
                  </p>
                  <ul className="space-y-1.5">
                    {YELLOW_FIXES.map((fix, i) => (
                      <li key={i} className="flex gap-2 text-xs text-yellow-800">
                        <span className="font-bold flex-shrink-0">{i + 1}.</span>
                        {fix}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {rating === "RED" && (
            <div className="bg-red-50 border border-red-300 rounded-2xl p-5">
              <div className="flex items-start gap-3">
                <AlertTriangle size={18} className="text-red-600 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-bold text-red-800 mb-2">⚠️ Critical — messaging may be restricted</p>
                  <p className="text-xs text-red-700 mb-3">
                    Your WABA quality is RED. Meta may have already reduced your messaging tier.
                    Take immediate action:
                  </p>
                  <ul className="space-y-1.5">
                    {RED_FIXES.map((fix, i) => (
                      <li key={i} className="flex gap-2 text-xs text-red-800">
                        <span className="font-bold flex-shrink-0">{i + 1}.</span>
                        {fix}
                      </li>
                    ))}
                  </ul>
                  <a
                    href="https://business.facebook.com/business-support-home"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 mt-4 text-xs font-semibold bg-red-600 hover:bg-red-700 text-white px-3 py-1.5 rounded-lg transition-colors"
                  >
                    Open Meta Business Support <ExternalLink size={11} />
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* ── 30-day trend chart ── */}
          <div className="haip-card p-5 shadow-sm">
            <p className="text-sm font-semibold text-gray-800 mb-1">30-day Quality Trend</p>
            <p className="text-xs text-gray-400 mb-5">
              3 = Green · 2 = Yellow · 1 = Red · Polled hourly
            </p>

            {chartData.length < 2 ? (
              <div className="h-40 flex items-center justify-center text-sm text-gray-400">
                Not enough data yet — check back after the first few poll cycles.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={chartData} margin={{ top: 4, right: 4, bottom: 4, left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis
                    dataKey="ts"
                    tick={{ fontSize: 10, fill: "#9ca3af" }}
                    interval={Math.max(0, Math.floor(chartData.length / 6))}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    domain={[0, 3]}
                    ticks={[1, 2, 3]}
                    tick={{ fontSize: 10, fill: "#9ca3af" }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => v === 3 ? "🟢" : v === 2 ? "🟡" : "🔴"}
                  />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e5e7eb" }}
                    formatter={(v) => {
                      const n = typeof v === "number" ? v : Number(v);
                      const map: Record<number, string> = { 3: "GREEN", 2: "YELLOW", 1: "RED", 0: "UNKNOWN" };
                      return [map[n] ?? String(n), "Rating"] as [string, string];
                    }}
                  />
                  {/* Reference lines for thresholds */}
                  <ReferenceLine y={2} stroke="#fbbf24" strokeDasharray="4 2" strokeWidth={1} />
                  <ReferenceLine y={1} stroke="#ef4444" strokeDasharray="4 2" strokeWidth={1} />
                  <Line
                    type="stepAfter"
                    dataKey="score"
                    stroke="#0f766e"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, fill: "#0f766e" }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* ── How the rating works ── */}
          <div className="bg-gray-50 border border-gray-200 rounded-2xl p-5">
            <p className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-4 flex items-center gap-1.5">
              <Info size={12} />
              How Meta quality rating works
            </p>
            <div className="grid sm:grid-cols-3 gap-4 text-xs text-gray-700">
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 font-semibold text-green-700">
                  <span className="w-2 h-2 rounded-full bg-green-500" />
                  Green
                </div>
                <p className="text-gray-500 leading-relaxed">
                  Low block &amp; opt-out rates. Full messaging tier available. Keep it by maintaining relevant, opted-in audiences.
                </p>
              </div>
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 font-semibold text-yellow-700">
                  <span className="w-2 h-2 rounded-full bg-yellow-400" />
                  Yellow
                </div>
                <p className="text-gray-500 leading-relaxed">
                  Moderate issues. Meta is monitoring. Tier may be reduced. Act within 7 days to avoid escalation to Red.
                </p>
              </div>
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 font-semibold text-red-700">
                  <span className="w-2 h-2 rounded-full bg-red-500" />
                  Red
                </div>
                <p className="text-gray-500 leading-relaxed">
                  High violations. Tier already restricted or at risk of account suspension. Immediate action required.
                </p>
              </div>
            </div>
            <div className="mt-4 pt-4 border-t border-gray-200">
              <a
                href="https://developers.facebook.com/docs/whatsapp/api/quality-rating"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 font-medium"
              >
                Meta official quality rating docs <ExternalLink size={11} />
              </a>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
