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
import { X, RefreshCw, ExternalLink, CheckCircle2, AlertTriangle, AlertCircle } from "@/lib/icons";
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
  green:   "bg-[var(--haip-green)]",
  yellow:  "bg-[var(--haip-amber)]",
  red:     "bg-[var(--haip-red)] motion-safe:animate-pulse",
  unknown: "bg-[var(--haip-border-strong)]",
};

const STATUS_ICON: Record<HealthStatus, React.ReactNode> = {
  green:   <CheckCircle2 size={15} className="text-[var(--haip-status-success-fg)]" />,
  yellow:  <AlertTriangle size={15} className="text-[var(--haip-status-warning-fg)]" />,
  red:     <AlertCircle size={15} className="text-[var(--haip-status-danger-fg)]" />,
  unknown: <AlertCircle size={13} className="text-[var(--haip-fg-subtle)]" />,
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
          el.className = "fixed bottom-20 right-4 z-50 bg-[var(--haip-cal-maint)] text-white text-[13px] font-semibold rounded-xl px-4 py-2.5 shadow-lg flex items-center gap-2";
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

  // Quiet unless something is actually wrong. "unknown" (the AI queue could not be asked) is not a
  // fault, and a connected channel is healthy -- the same rule the Integrations page uses.
  const hasIssues = data.services.some(s => s.status === "red" || s.status === "yellow");
  if (!hasIssues) return null;

  return (
    <>
      <div className="flex-shrink-0 border-b border-[var(--haip-border)] bg-[var(--haip-card)]">
        <div className="flex items-center gap-2 overflow-x-auto px-4 py-1.5 lg:px-6">
          <span className="flex-shrink-0 text-[12.5px] font-semibold text-[var(--haip-fg-muted)]">Connections</span>
          {data.services.map(svc => (
            <button
              key={svc.name}
              onClick={() => setDetail(d => d?.name === svc.name ? null : svc)}
              className={cn(
                "flex min-h-8 flex-shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-semibold transition-colors",
                svc.status === "red"    ? "border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]" :
                svc.status === "yellow" ? "border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]" :
                                          "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-muted)] hover:bg-[var(--hover-bg)]"
              )}
            >
              <span className={cn("size-2 flex-shrink-0 rounded-full", STATUS_DOT[svc.status])} />
              {svc.label}
            </button>
          ))}
          <button
            onClick={() => refetch()}
            className="ml-auto flex size-8 flex-shrink-0 items-center justify-center rounded-lg text-[var(--haip-icon-neutral)] transition-colors hover:bg-[var(--hover-bg)] hover:text-[var(--haip-fg)]"
            title="Refresh health" aria-label="Refresh connection health"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* Detail panel */}
      {detail && (
        <div className="flex-shrink-0 border-b border-[var(--haip-border)] bg-[var(--haip-surface)] px-4 py-3 lg:px-6">
          <div className="flex items-start gap-3">
            {STATUS_ICON[detail.status]}
            <div className="flex-1 min-w-0">
              <p className="text-[13.5px] font-semibold text-[var(--haip-fg)]">{detail.label}</p>
              {detail.message && <p className="mt-0.5 text-[13px] text-[var(--haip-fg-2)]">{detail.message}</p>}
              <div className="mt-1.5 flex items-center gap-3 text-[12px] text-[var(--haip-fg-subtle)]">
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
                  className="flex min-h-9 items-center gap-1 rounded-lg bg-primary px-3 text-[13px] font-semibold text-primary-foreground hover:bg-[var(--haip-primary-hover)]"
                >
                  Fix <ExternalLink size={12} />
                </Link>
              )}
              <button onClick={() => setDetail(null)} aria-label="Close details" className="flex size-9 items-center justify-center rounded-lg text-[var(--haip-icon-neutral)] transition-colors hover:bg-[var(--hover-bg)] hover:text-[var(--haip-fg)]">
                <X size={15} />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
