"use client";

/**
 * X11 — Tooltip discovery hotspot
 *
 * Wraps a UI element with a pulsing dot that shows on first N sessions.
 * Click → tooltip with description + optional Loom link. Auto-dismiss.
 *
 * State persisted in localStorage keyed by `hotspot:{key}`.
 */

import { useState, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { X, ExternalLink } from "lucide-react";

interface HotspotProps {
  /** Unique key for this hotspot — persisted in localStorage */
  hotspotKey: string;
  /** Tooltip title */
  title: string;
  /** Tooltip body */
  description: string;
  /** Optional Loom or doc link */
  learnMoreUrl?: string;
  /** How many sessions to show before auto-hiding (default 3) */
  maxSessions?: number;
  /** Dot position relative to children */
  position?: "top-right" | "top-left" | "bottom-right" | "bottom-left";
  children: React.ReactNode;
  className?: string;
}

const STORAGE_PREFIX = "hotspot:";

function getSessionCount(key: string): number {
  try {
    return parseInt(localStorage.getItem(`${STORAGE_PREFIX}${key}:sessions`) ?? "0", 10);
  } catch {
    return 0;
  }
}

function markSession(key: string): void {
  try {
    const count = getSessionCount(key) + 1;
    localStorage.setItem(`${STORAGE_PREFIX}${key}:sessions`, String(count));
  } catch { /* private mode */ }
}

function isDismissed(key: string): boolean {
  try {
    return localStorage.getItem(`${STORAGE_PREFIX}${key}:dismissed`) === "true";
  } catch {
    return false;
  }
}

function dismiss(key: string): void {
  try {
    localStorage.setItem(`${STORAGE_PREFIX}${key}:dismissed`, "true");
  } catch { /* private mode */ }
}

const DOT_POSITIONS = {
  "top-right":    "-top-1.5 -right-1.5",
  "top-left":     "-top-1.5 -left-1.5",
  "bottom-right": "-bottom-1.5 -right-1.5",
  "bottom-left":  "-bottom-1.5 -left-1.5",
};

const TOOLTIP_POSITIONS = {
  "top-right":    "top-6 right-0",
  "top-left":     "top-6 left-0",
  "bottom-right": "bottom-6 right-0",
  "bottom-left":  "bottom-6 left-0",
};

export function Hotspot({
  hotspotKey,
  title,
  description,
  learnMoreUrl,
  maxSessions = 3,
  position = "top-right",
  children,
  className,
}: HotspotProps) {
  const [visible, setVisible] = useState(false);
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const sessions = getSessionCount(hotspotKey);
    if (isDismissed(hotspotKey)) return;
    if (sessions >= maxSessions) return;
    markSession(hotspotKey);
    setVisible(true);
  }, [hotspotKey, maxSessions]);

  // Close on outside click
  useEffect(() => {
    if (!tooltipOpen) return;
    const handler = (e: MouseEvent) => {
      if (tooltipRef.current && !tooltipRef.current.contains(e.target as Node)) {
        setTooltipOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [tooltipOpen]);

  const handleDismiss = () => {
    dismiss(hotspotKey);
    setVisible(false);
    setTooltipOpen(false);
  };

  if (!visible) return <>{children}</>;

  return (
    <div className={cn("relative inline-flex", className)}>
      {children}

      {/* Pulsing dot */}
      <button
        onClick={() => setTooltipOpen(v => !v)}
        aria-label="What's this?"
        className={cn(
          "absolute z-20 w-3 h-3 rounded-full bg-indigo-500 border-2 border-white shadow-sm",
          DOT_POSITIONS[position]
        )}
      >
        <span className="absolute inset-0 rounded-full bg-indigo-400 animate-ping opacity-75" />
      </button>

      {/* Tooltip */}
      {tooltipOpen && (
        <div
          ref={tooltipRef}
          className={cn(
            "absolute z-30 w-64 bg-[#0f2744] border border-white/10 rounded-2xl shadow-2xl p-4",
            TOOLTIP_POSITIONS[position]
          )}
        >
          <div className="flex items-start justify-between gap-2 mb-2">
            <p className="text-sm font-bold text-white">{title}</p>
            <button onClick={handleDismiss} className="text-white/30 hover:text-white/70 flex-shrink-0 transition-colors">
              <X size={13} />
            </button>
          </div>
          <p className="text-xs text-white/60 leading-relaxed mb-3">{description}</p>
          <div className="flex items-center justify-between">
            {learnMoreUrl ? (
              <a
                href={learnMoreUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300 font-medium"
              >
                <ExternalLink size={11} />
                Watch demo
              </a>
            ) : <span />}
            <button
              onClick={handleDismiss}
              className="text-[11px] text-white/30 hover:text-white/60 transition-colors"
            >
              Got it
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
