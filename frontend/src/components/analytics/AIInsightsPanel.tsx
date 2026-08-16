"use client";

/**
 * AI Insights Panel — right-rail component for the Executive Dashboard.
 * Shows up to 5 active insights, severity-sorted.
 * Each card has: severity dot, title, optional body, CTA button, dismiss ×.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles, X, ExternalLink, RefreshCw, AlertCircle, TrendingDown, Zap, Info } from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

// ─── Types ────────────────────────────────────────────────────────────────────

interface InsightItem {
  id: string;
  category_code: string;
  category: string;
  severity: "critical" | "high" | "medium" | "low" | "info";
  title: string;
  body?: string;
  cta_label?: string;
  cta_href?: string;
  detected_at: string;
}

interface InsightList {
  items: InsightItem[];
  total: number;
}

// ─── Severity config ──────────────────────────────────────────────────────────

const SEV_CONFIG = {
  critical: {
    dot:  "bg-red-500",
    ring: "border-red-100",
    bg:   "bg-red-50",
    icon: <AlertCircle size={13} className="text-red-500" />,
    label: "Critical",
  },
  high: {
    dot:  "bg-orange-400",
    ring: "border-orange-100",
    bg:   "bg-orange-50",
    icon: <AlertCircle size={13} className="text-orange-400" />,
    label: "High",
  },
  medium: {
    dot:  "bg-amber-400",
    ring: "border-amber-100",
    bg:   "bg-amber-50",
    icon: <TrendingDown size={13} className="text-amber-500" />,
    label: "Medium",
  },
  low: {
    dot:  "bg-teal-400",
    ring: "border-teal-100",
    bg:   "bg-teal-50",
    icon: <Zap size={13} className="text-teal-500" />,
    label: "Opportunity",
  },
  info: {
    dot:  "bg-gray-300",
    ring: "border-gray-100",
    bg:   "bg-gray-50",
    icon: <Info size={13} className="text-gray-400" />,
    label: "Info",
  },
} as const;

// ─── Single insight card ──────────────────────────────────────────────────────

function InsightCard({
  insight,
  onDismiss,
}: {
  insight: InsightItem;
  onDismiss: (id: string) => void;
}) {
  const router = useRouter();
  const cfg = SEV_CONFIG[insight.severity] ?? SEV_CONFIG.info;

  return (
    <div
      className={cn(
        "rounded-xl border p-3 transition-all",
        cfg.bg,
        cfg.ring,
      )}
    >
      <div className="flex items-start gap-2">
        {/* severity dot */}
        <span className={cn("mt-[3px] w-2 h-2 flex-shrink-0 rounded-full", cfg.dot)} />

        <div className="flex-1 min-w-0">
          <p className="text-[12px] font-semibold leading-tight text-gray-900 pr-4">
            {insight.title}
          </p>
          {insight.body && (
            <p className="text-[11px] text-gray-500 mt-0.5 leading-relaxed">
              {insight.body}
            </p>
          )}

          {insight.cta_label && insight.cta_href && (
            <button
              onClick={() => router.push(insight.cta_href!)}
              className="mt-2 inline-flex items-center gap-1 text-[11px] font-semibold
                         text-teal-700 bg-white border border-teal-200 rounded-lg
                         px-2.5 py-1 hover:bg-teal-50 transition-colors"
            >
              {insight.cta_label}
              <ExternalLink size={9} />
            </button>
          )}
        </div>

        {/* dismiss */}
        <button
          onClick={() => onDismiss(insight.id)}
          title="Dismiss"
          className="flex-shrink-0 text-gray-300 hover:text-gray-500 transition-colors -mt-0.5"
        >
          <X size={13} />
        </button>
      </div>
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export function AIInsightsPanel({ className }: { className?: string }) {
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery<InsightList>({
    queryKey: ["analytics", "insights"],
    queryFn:  () => api.get("/analytics/insights").then(r => r.data),
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    retry: 1,
  });

  // Distinguish "genuinely zero insights" from "failed to load" -- this used
  // to fall through to the same items=[] "All clear" empty state on any
  // error (a disabled module, a DB timeout, anything), which reads as a
  // healthy feed with nothing to report instead of a broken one.
  const errMsg = (() => {
    if (!isError) return null;
    const e = error as { response?: { status?: number; data?: { detail?: { message?: string } | string } } };
    const detail = e?.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message;
    if (e?.response?.status) return `Server returned ${e.response.status}.`;
    return "Couldn't reach the server.";
  })();

  const dismiss = useMutation({
    mutationFn: (id: string) => api.post(`/analytics/insights/${id}/dismiss`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["analytics", "insights"] }),
  });

  const items = data?.items ?? [];

  return (
    <div className={cn("flex flex-col", className)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1.5">
          <Sparkles size={14} className="text-teal-500" />
          <span
            className="text-[13px] font-semibold"
            style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
          >
            AI Insights
          </span>
        </div>
        <button
          onClick={() => refetch()}
          title="Refresh insights"
          className="text-gray-300 hover:text-gray-500 transition-colors"
        >
          <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map(i => (
            <Skeleton key={i} className="h-16 rounded-xl" />
          ))}
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center py-8 text-center px-3">
          <div className="w-8 h-8 rounded-full bg-red-50 flex items-center justify-center mb-2">
            <AlertCircle size={14} className="text-red-400" />
          </div>
          <p className="text-[12px] font-medium text-gray-700">Couldn't load insights</p>
          <p className="text-[11px] text-gray-400 mt-0.5 max-w-[220px]">{errMsg}</p>
          <button
            onClick={() => refetch()}
            className="mt-2.5 inline-flex items-center gap-1.5 text-[11px] font-semibold text-teal-700 bg-white border border-teal-200 rounded-lg px-2.5 py-1 hover:bg-teal-50 transition-colors"
          >
            <RefreshCw size={11} /> Retry
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <div className="w-8 h-8 rounded-full bg-teal-50 flex items-center justify-center mb-2">
            <Sparkles size={14} className="text-teal-400" />
          </div>
          <p className="text-[12px] font-medium text-gray-500">All clear</p>
          <p className="text-[11px] text-gray-400 mt-0.5">No active alerts right now</p>
        </div>
      ) : (
        <div className="space-y-2">
          {items.slice(0, 5).map(insight => (
            <InsightCard
              key={insight.id}
              insight={insight}
              onDismiss={id => dismiss.mutate(id)}
            />
          ))}
          {items.length > 5 && (
            <p className="text-[11px] text-gray-400 text-center pt-1">
              +{items.length - 5} more insights
            </p>
          )}
        </div>
      )}
    </div>
  );
}
