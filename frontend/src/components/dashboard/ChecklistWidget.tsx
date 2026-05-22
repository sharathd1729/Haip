"use client";

/**
 * O5 — Setup checklist widget.
 *
 * Floats bottom-right on the dashboard. Derives completion state from:
 * - /tenants/me  (tenant.config JSONB — tracks skipped/completed steps)
 * - /integrations (to know if WA / IVR are connected)
 * - /properties (to know if ≥1 property exists)
 *
 * Items are deep-linked. Confetti fires when all items are done.
 * Dismissed state is persisted in localStorage so it doesn't reappear.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  CheckCircle2, Circle, ChevronDown, ChevronUp,
  X, Building2, MessageSquare, Phone, Users,
  ShieldCheck, Zap, Layers, Trophy,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TenantConfig {
  onboarding_step?: number;
  step_3_skipped?: boolean;
  step_4_skipped?: boolean;
  step_5_skipped?: boolean;
  step_6_skipped?: boolean;
  step_7_skipped?: boolean;
  [key: string]: unknown;
}

interface Tenant {
  id: string;
  name: string;
  config?: TenantConfig;
}

interface Integration {
  kind: string;
  status: string;
}

interface Property {
  id: string;
}

// ---------------------------------------------------------------------------
// Checklist item definition
// ---------------------------------------------------------------------------

interface ChecklistItem {
  id: string;
  label: string;
  description: string;
  icon: React.ReactNode;
  href: string;
  required: boolean;
}

const ITEMS: ChecklistItem[] = [
  {
    id: "brand",
    label: "Set up your brand",
    description: "Name, logo, city and segment",
    icon: <Building2 size={13} />,
    href: "/onboarding?step=0",
    required: true,
  },
  {
    id: "property",
    label: "Add a property",
    description: "Your first hotel or villa",
    icon: <Layers size={13} />,
    href: "/dashboard/properties/new",
    required: true,
  },
  {
    id: "whatsapp",
    label: "Connect WhatsApp",
    description: "Start receiving guest messages",
    icon: <MessageSquare size={13} />,
    href: "/dashboard/settings/integrations",
    required: false,
  },
  {
    id: "ivr",
    label: "Connect your IVR",
    description: "Acefone, CallerDesk, or other",
    icon: <Phone size={13} />,
    href: "/dashboard/settings/integrations",
    required: false,
  },
  {
    id: "invite",
    label: "Invite a teammate",
    description: "Add your front desk or manager",
    icon: <Users size={13} />,
    href: "/dashboard/settings/team",
    required: false,
  },
  {
    id: "dpdp",
    label: "Review DPDP settings",
    description: "Consent, deletion, and compliance",
    icon: <ShieldCheck size={13} />,
    href: "/dashboard/compliance",
    required: false,
  },
  {
    id: "concierge",
    label: "Enable AI concierge",
    description: "Shadow or autonomous mode",
    icon: <Zap size={13} />,
    href: "/dashboard/settings",
    required: false,
  },
];

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

const LS_DISMISSED = "checklist_dismissed_v1";

function isDismissed(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(LS_DISMISSED) === "1";
}

function setDismissed() {
  if (typeof window === "undefined") return;
  localStorage.setItem(LS_DISMISSED, "1");
}

// ---------------------------------------------------------------------------
// Confetti burst (CSS-only, no library dependency)
// ---------------------------------------------------------------------------

function ConfettiBurst() {
  const colors = ["#4361EE", "#3b82f6", "#a855f7", "#f59e0b", "#ef4444", "#22c55e"];
  return (
    <div className="fixed inset-0 pointer-events-none z-[100] overflow-hidden">
      {Array.from({ length: 36 }).map((_, i) => {
        const color = colors[i % colors.length];
        const left = Math.random() * 100;
        const delay = Math.random() * 0.4;
        const size = 6 + Math.random() * 8;
        const duration = 0.9 + Math.random() * 0.6;
        return (
          <div
            key={i}
            className="absolute top-0 rounded-sm"
            style={{
              left: `${left}%`,
              width: size,
              height: size * (0.4 + Math.random() * 0.6),
              backgroundColor: color,
              opacity: 0,
              animation: `confettiFall ${duration}s ease-in ${delay}s forwards`,
              transform: `rotate(${Math.random() * 360}deg)`,
            }}
          />
        );
      })}
      <style>{`
        @keyframes confettiFall {
          0%   { transform: translateY(-20px) rotate(0deg); opacity: 1; }
          100% { transform: translateY(100vh) rotate(720deg); opacity: 0; }
        }
      `}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

export function ChecklistWidget() {
  const [dismissed, setDismissedState] = useState(true); // start hidden, set after mount
  const [collapsed, setCollapsed] = useState(false);
  const [showConfetti, setShowConfetti] = useState(false);
  const [prevComplete, setPrevComplete] = useState(false);

  useEffect(() => {
    setDismissedState(isDismissed());
  }, []);

  const { data: tenant } = useQuery<Tenant>({
    queryKey: ["tenant-me"],
    queryFn: () => api.get("/tenants/me").then(r => r.data),
    staleTime: 60_000,
  });

  const { data: integrations = [] } = useQuery<Integration[]>({
    queryKey: ["integrations-list"],
    queryFn: () => api.get("/integrations").then(r => r.data),
    staleTime: 60_000,
  });

  const { data: properties = [] } = useQuery<Property[]>({
    queryKey: ["properties-list"],
    queryFn: () => api.get("/properties").then(r => r.data),
    staleTime: 60_000,
  });

  // ---------------------------------------------------------------------------
  // Derive completion state
  // ---------------------------------------------------------------------------
  const cfg = tenant?.config ?? {};
  const onboardingStep = cfg.onboarding_step ?? 0;
  // Backend stores kind as "whatsapp" (not "whatsapp_meta") and status as "active" (not "connected")
  const waConnected = integrations.some(i => (i.kind === "whatsapp" || i.kind === "whatsapp_meta") && (i.status === "active" || i.status === "connected"));
  const ivrConnected = integrations.some(
    i => (i.kind === "callerdesk" || i.kind === "acefone") && (i.status === "active" || i.status === "connected")
  );

  const completionMap: Record<string, boolean> = {
    brand: onboardingStep >= 1,
    property: properties.length > 0,
    whatsapp: waConnected,
    ivr: ivrConnected,
    invite: onboardingStep >= 3,
    concierge: onboardingStep >= 4,
    dpdp: onboardingStep >= 5,
  };

  const completedCount = Object.values(completionMap).filter(Boolean).length;
  const totalCount = ITEMS.length;
  const allComplete = completedCount === totalCount;
  const requiredComplete = ITEMS.filter(i => i.required).every(i => completionMap[i.id]);

  // Confetti on first full completion
  useEffect(() => {
    if (allComplete && !prevComplete) {
      setShowConfetti(true);
      setTimeout(() => setShowConfetti(false), 2500);
    }
    setPrevComplete(allComplete);
  }, [allComplete, prevComplete]);

  const handleDismiss = useCallback(() => {
    setDismissed();
    setDismissedState(true);
  }, []);

  // Don't show if:
  // - Dismissed by user
  // - All items complete AND required steps done (no need to nag)
  if (dismissed) return null;
  if (allComplete && requiredComplete) return null;

  const pct = Math.round((completedCount / totalCount) * 100);

  return (
    <>
      {showConfetti && <ConfettiBurst />}

      <div
        className="fixed bottom-6 right-5 z-40 w-72 rounded-2xl shadow-2xl shadow-black/60 overflow-hidden"
        style={{
          backgroundColor: "#0a1929",
          border: "1px solid rgba(255,255,255,0.10)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center gap-2 px-4 py-3 border-b border-white/6 cursor-pointer select-none"
          onClick={() => setCollapsed(c => !c)}
        >
          {allComplete ? (
            <Trophy size={14} className="text-amber-400 flex-shrink-0" />
          ) : (
            <div className="relative w-7 h-7 flex-shrink-0">
              {/* Progress ring */}
              <svg width="28" height="28" viewBox="0 0 28 28" className="-rotate-90">
                <circle cx="14" cy="14" r="11" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
                <circle
                  cx="14" cy="14" r="11"
                  fill="none"
                  stroke="#4361EE"
                  strokeWidth="3"
                  strokeDasharray={`${2 * Math.PI * 11}`}
                  strokeDashoffset={`${2 * Math.PI * 11 * (1 - pct / 100)}`}
                  strokeLinecap="round"
                  className="transition-all duration-500"
                />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-[8px] font-bold text-white/50">
                {pct}%
              </span>
            </div>
          )}

          <div className="flex-1 min-w-0">
            <p className="text-xs font-bold text-white/80 leading-tight">
              {allComplete ? "Setup complete! 🎉" : "Finish your setup"}
            </p>
            <p className="text-[10px] text-white/30">
              {completedCount}/{totalCount} steps done
            </p>
          </div>

          <div className="flex items-center gap-1">
            {collapsed
              ? <ChevronUp size={13} className="text-white/30" />
              : <ChevronDown size={13} className="text-white/30" />
            }
            <button
              onClick={e => { e.stopPropagation(); handleDismiss(); }}
              className="ml-0.5 w-5 h-5 rounded flex items-center justify-center text-white/20 hover:text-white/50 hover:bg-white/8 transition-colors"
              title="Dismiss"
            >
              <X size={11} />
            </button>
          </div>
        </div>

        {/* Items */}
        {!collapsed && (
          <div className="py-1.5">
            {ITEMS.map(item => {
              const done = completionMap[item.id];
              return (
                <Link
                  key={item.id}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-3 px-4 py-2 transition-colors group",
                    done
                      ? "opacity-50 hover:opacity-70"
                      : "hover:bg-white/4"
                  )}
                >
                  {done ? (
                    <CheckCircle2 size={15} className="text-indigo-400 flex-shrink-0" />
                  ) : (
                    <Circle size={15} className="text-white/20 flex-shrink-0 group-hover:text-white/40 transition-colors" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className={cn(
                      "text-xs font-medium leading-tight",
                      done ? "text-white/40 line-through" : "text-white/75"
                    )}>
                      {item.label}
                      {item.required && !done && (
                        <span className="ml-1 text-[8px] text-red-400/70 font-bold uppercase">required</span>
                      )}
                    </p>
                    {!done && (
                      <p className="text-[10px] text-white/25 mt-0.5 truncate">{item.description}</p>
                    )}
                  </div>
                  <span className="text-white/10 group-hover:text-white/30 transition-colors text-xs">→</span>
                </Link>
              );
            })}
          </div>
        )}

        {/* Progress bar */}
        {!collapsed && (
          <div className="px-4 pb-3 pt-1">
            <div className="h-1 rounded-full bg-white/5 overflow-hidden">
              <div
                className="h-full rounded-full bg-indigo-500 transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </>
  );
}
