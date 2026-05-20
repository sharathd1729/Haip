"use client";

/**
 * X8 — Global status bar
 *
 * Polls /health/dashboard every 30s. Shows per-integration health pills.
 * Click pill → detail modal with diagnostics + reconnect action.
 * Red state → one-time toast notification.
 */

import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, RefreshCw, ExternalLink, CheckCircle2, AlertTriangle, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import Link from "next/link";

// ── Types ─────────────────────────────────────────────────────────────────────

type HealthStatus = "green" | "yellow" | "red" | "unknown";

interface ServiceHealth {
  name: string;
  label: string;
  status: HealthStatus;
  last_sync?: string | null;
  queue_depth?: number;
  message?: string;
  reconnect_href?: string;
}

interface DashboardHealth {
  services: ServiceHealth[];
  overall: HealthStatus;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_DOT: Record<HealthStatus, string> = {
  green:   "bg-green-400",
  yellow:  "bg-yellow-400",
  red:     "bg-red-500 animate-pulse",
  unknown: "bg-gray-400",
};

const STATUS_ICON: Record<HealthStatus, React.ReactNode> = {
  green:   <CheckCircle2 size={13} className="text-green-600" />,
  yellow:  <AlertTriangle size={13} className="text-yellow-600" />,
  red:     <AlertCircle size={13} className="text-red-600" />,
  unknown: <AlertCircle size={13} className="text-gray-400" />,
};

function relativeTime(iso?: string | null): string {
  if (!iso) return "never";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function StatusBar() {
  const [detail, setDetail] = useState<ServiceHealth | null>(null);
  const prevRedRef = useRef<Set<string>>(new Set());

  const { data, isLoading, refetch } = useQuery<DashboardHealth>({
    queryKey: ["health-dashboard"],
    queryFn: () => api.get("/health/dashboard").then(r => r.data),
    refetchInterval: 30_000,
    staleTime: 25_000,
    retry: false,
  });

  // One-time toast on red state change
  useEffect(() => {
    if (!data) return;
    const newReds = data.services.filter(s => s.status === "red").map(s => s.name);
    for (const name of newReds) {
      if (!prevRedRef.current.has(name)) {
        // Simple DOM toast (avoid circular dep with toast provider)
        const existing = document.querySelector(`[data-health-toast="${name}"]`);
        if (!existing) {
          const el = document.createElement("div");
          el.setAttribute("data-health-toast", name);
          el.className = "fixed bottom-20 right-4 z-50 bg-red-600 text-white text-xs font-medium rounded-xl px-4 py-2.5 shadow-lg flex items-center gap-2";
          const svc = data.services.find(s => s.name === name);
          el.innerHTML = `<span>⚠️ ${svc?.label ?? name} is down — check integrations</span>`;
          document.body.appendChild(el);
          setTimeout(() => el.remove(), 6000);
        }
      }
    }
    prevRedRef.current = new Set(newReds);
  }, [data]);

  if (isLoading || !data) return null;

  // Don't render bar if everything is green — keep UI quiet
  const hasIssues = data.services.some(s => s.status !== "green");
  if (!hasIssues) return null;

  return (
    <>
      <div className="border-b flex-shrink-0" style={{ borderColor: "rgba(255,255,255,0.06)", backgroundColor: "rgba(0,0,0,0.15)" }}>
        <div className="px-4 py-1.5 flex items-center gap-3 overflow-x-auto">
          {data.services.map(svc => (
            <button
              key={svc.name}
              onClick={() => setDetail(d => d?.name === svc.name ? null : svc)}
              className={cn(
                "flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] font-medium transition-colors flex-shrink-0",
                svc.status === "red"    ? "bg-red-500/15 text-red-300 hover:bg-red-500/25" :
                svc.status === "yellow" ? "bg-yellow-500/15 text-yellow-300 hover:bg-yellow-500/25" :
                                          "bg-white/5 text-white/40 hover:bg-white/8"
              )}
            >
              <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", STATUS_DOT[svc.status])} />
              {svc.label}
            </button>
          ))}
          <button
            onClick={() => refetch()}
            className="ml-auto text-white/25 hover:text-white/50 flex-shrink-0 transition-colors"
            title="Refresh health"
          >
            <RefreshCw size={11} />
          </button>
        </div>
      </div>

      {/* Detail panel */}
      {detail && (
        <div className="border-b px-4 py-3 flex-shrink-0" style={{ borderColor: "rgba(255,255,255,0.06)", backgroundColor: "rgba(0,0,0,0.1)" }}>
          <div className="flex items-start gap-3">
            {STATUS_ICON[detail.status]}
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-white/80">{detail.label}</p>
              {detail.message && <p className="text-[11px] text-white/50 mt-0.5">{detail.message}</p>}
              <div className="flex items-center gap-3 mt-1.5 text-[10px] text-white/35">
                <span>Last sync: {relativeTime(detail.last_sync)}</span>
                {detail.queue_depth !== undefined && detail.queue_depth > 0 && (
                  <span>Queue: {detail.queue_depth} items</span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              {detail.reconnect_href && (
                <Link
                  href={detail.reconnect_href}
                  className="text-[11px] font-semibold text-teal-400 hover:text-teal-300 flex items-center gap-1"
                >
                  Fix <ExternalLink size={10} />
                </Link>
              )}
              <button onClick={() => setDetail(null)} className="text-white/25 hover:text-white/60 transition-colors">
                <X size={13} />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
