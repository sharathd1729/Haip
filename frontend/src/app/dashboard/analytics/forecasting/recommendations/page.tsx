"use client";


import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles, AlertTriangle, AlertCircle, Info, TrendingUp, CheckCircle2 } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useRouter } from "next/navigation";
import api from "@/lib/api";

interface InsightItem {
  id: string;
  category: string;
  severity: "critical" | "high" | "medium" | "low" | "info";
  title: string;
  body: string | null;
  cta_label: string | null;
  cta_href: string | null;
  is_dismissed: boolean;
  is_auto_resolved: boolean;
  created_at: string;
}
interface InsightList {
  items: InsightItem[];
  total: number;
}

const SEVERITY_CFG = {
  critical: {
    icon: <AlertTriangle size={14} className="text-red-500" />,
    border: "border-red-200",
    badge: "bg-red-100 text-red-700",
    dot: "bg-red-500",
    label: "Critical",
  },
  high: {
    icon: <AlertCircle size={14} className="text-orange-500" />,
    border: "border-orange-200",
    badge: "bg-orange-100 text-orange-700",
    dot: "bg-orange-400",
    label: "High",
  },
  medium: {
    icon: <AlertCircle size={14} className="text-amber-500" />,
    border: "border-amber-200",
    badge: "bg-amber-100 text-amber-700",
    dot: "bg-amber-400",
    label: "Medium",
  },
  low: {
    icon: <Info size={14} className="text-blue-500" />,
    border: "border-blue-200",
    badge: "bg-blue-100 text-blue-700",
    dot: "bg-blue-400",
    label: "Low",
  },
  info: {
    icon: <Info size={14} className="text-gray-400" />,
    border: "border-gray-200",
    badge: "bg-gray-100 text-gray-600",
    dot: "bg-gray-300",
    label: "Info",
  },
};

const CATEGORY_LABELS: Record<string, string> = {
  urgency:   "Urgency",
  occupancy: "Occupancy",
  revenue:   "Revenue",
  quality:   "Quality",
};

function PageSkeleton() {
  return (
    <div className="p-6 space-y-4">
      <Skeleton className="h-7 w-52" />
      <Skeleton className="h-4 w-64" />
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-28 rounded-2xl" />
      ))}
    </div>
  );
}

function InsightCard({ item, onDismiss }: { item: InsightItem; onDismiss: (id: string) => void }) {
  const router = useRouter();
  const cfg = SEVERITY_CFG[item.severity] ?? SEVERITY_CFG.info;

  return (
    <div className={cn("bg-white border rounded-2xl p-4 transition-all", cfg.border)}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 shrink-0">{cfg.icon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full", cfg.badge)}>
              {cfg.label}
            </span>
            <span className="text-[10px] text-gray-400">
              {CATEGORY_LABELS[item.category] ?? item.category}
            </span>
          </div>
          <p className="text-sm font-semibold text-gray-800 mb-1">{item.title}</p>
          {item.body && (
            <p className="text-xs text-gray-500 leading-relaxed">{item.body}</p>
          )}
          <div className="flex items-center gap-3 mt-3">
            {item.cta_label && item.cta_href && (
              <button
                onClick={() => router.push(item.cta_href!)}
                className="text-xs font-medium text-teal-600 hover:text-teal-700 underline underline-offset-2"
              >
                {item.cta_label} â†’
              </button>
            )}
            <button
              onClick={() => onDismiss(item.id)}
              className="text-xs text-gray-400 hover:text-gray-600 ml-auto"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function RecommendationsPage() {
  const qc = useQueryClient();

  const { data, isLoading, isError } = useQuery<InsightList>({
    queryKey: ["insights"],
    queryFn: () => api.get("/analytics/insights").then(r => r.data),
    staleTime: 2 * 60_000,
  });

  const dismiss = useMutation({
    mutationFn: (id: string) => api.post(`/analytics/insights/${id}/dismiss`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["insights"] }),
  });

  if (isLoading) return <PageSkeleton />;
  if (isError || !data) return <div className="p-6 text-center text-sm text-gray-400">Failed to load recommendations.</div>;

  const active = data.items.filter(i => !i.is_dismissed && !i.is_auto_resolved);
  const resolved = data.items.filter(i => i.is_auto_resolved || i.is_dismissed);

  const byCategory: Record<string, InsightItem[]> = {};
  for (const item of active) {
    const cat = item.category ?? "other";
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(item);
  }

  const sortOrder = ["critical", "high", "medium", "low", "info"];
  const sorted = [...active].sort(
    (a, b) => sortOrder.indexOf(a.severity) - sortOrder.indexOf(b.severity),
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Sparkles size={18} className="text-teal-500" />
        <div>
          <h1 className="haip-page-title">AI Recommendations</h1>
          <p className="text-[12px] text-gray-400 mt-0.5">
            {active.length} active insight{active.length !== 1 ? "s" : ""} Â· auto-refreshes every 15 min
          </p>
        </div>
      </div>

      {/* Summary strips */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {(["critical", "high", "medium", "low"] as const).map(sev => {
          const count = active.filter(i => i.severity === sev).length;
          const cfg = SEVERITY_CFG[sev];
          return (
            <div key={sev} className={cn("bg-white border rounded-2xl p-3 flex items-center gap-2", cfg.border)}>
              <span className={cn("w-2 h-2 rounded-full shrink-0", cfg.dot)} />
              <div>
                <p className="text-lg font-bold text-gray-800">{count}</p>
                <p className="text-[10px] text-gray-400">{cfg.label}</p>
              </div>
            </div>
          );
        })}
      </div>

      {sorted.length === 0 ? (
        <div className="haip-card p-10 text-center">
          <CheckCircle2 size={32} className="text-teal-400 mx-auto mb-3" />
          <p className="text-sm font-semibold text-gray-700">All clear</p>
          <p className="text-xs text-gray-400 mt-1">No active recommendations right now. Check back later.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {sorted.map(item => (
            <InsightCard key={item.id} item={item} onDismiss={(id) => dismiss.mutate(id)} />
          ))}
        </div>
      )}

      {/* Resolved section */}
      {resolved.length > 0 && (
        <details className="group">
          <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600 select-none">
            {resolved.length} resolved / dismissed insight{resolved.length !== 1 ? "s" : ""}
          </summary>
          <div className="mt-3 space-y-2 opacity-60">
            {resolved.slice(0, 5).map(item => (
              <div key={item.id} className="bg-gray-50 border border-gray-100 rounded-xl p-3">
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={12} className="text-gray-400" />
                  <p className="text-xs text-gray-500 line-through">{item.title}</p>
                </div>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
