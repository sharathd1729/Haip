"use client";

import { motion, useReducedMotion } from "framer-motion";
import {
  CalendarCheck2, MessageSquare, FileCheck2, BellRing, BookOpen, Star, Gift,
} from "lucide-react";
import { viewportOnce } from "../shared/motion";

const steps = [
  { icon: CalendarCheck2, label: "Booking received", detail: "Trigger — any channel", tone: "accent" },
  { icon: MessageSquare, label: "Welcome message", detail: "WhatsApp · instantly", tone: "neutral" },
  { icon: FileCheck2, label: "Collect ID", detail: "Secure link · auto-verified", tone: "neutral" },
  { icon: BellRing, label: "Check-in reminder", detail: "24h before arrival", tone: "neutral" },
  { icon: BookOpen, label: "House guide", detail: "Sent on check-in", tone: "neutral" },
  { icon: Star, label: "Review request", detail: "Day after checkout", tone: "neutral" },
  { icon: Gift, label: "Upsell future stay", detail: "Personalised offer · 30 days", tone: "success" },
] as const;

/**
 * Vertical workflow diagram for the Automation section.
 * Steps stagger in as the section scrolls into view.
 */
export function AutomationFlowMockup({ className = "" }: { className?: string }) {
  const reduced = useReducedMotion();

  return (
    <motion.div
      className={`rounded-xl p-4 sm:p-5 ${className}`}
      style={{
        backgroundColor: "var(--home-card)",
        border: "1px solid var(--home-border)",
        boxShadow: "var(--home-shadow-md)",
      }}
      initial={reduced ? undefined : "hidden"}
      whileInView={reduced ? undefined : "visible"}
      viewport={viewportOnce}
      variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.1 } } }}
    >
      <div className="flex flex-col">
        {steps.map((step, i) => {
          const Icon = step.icon;
          const isFirst = step.tone === "accent";
          const isLast = step.tone === "success";
          return (
            <motion.div
              key={step.label}
              variants={{
                hidden: { opacity: 0, y: 12 },
                visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut" } },
              }}
            >
              <div className="flex items-center gap-3">
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                  style={{
                    backgroundColor: isFirst
                      ? "var(--home-accent)"
                      : isLast
                        ? "rgba(31,157,85,0.12)"
                        : "rgba(11,107,94,0.07)",
                    color: isFirst ? "#FFFFFF" : isLast ? "var(--home-success)" : "var(--home-accent)",
                  }}
                >
                  <Icon size={16} />
                </div>
                <div className="min-w-0 py-1.5">
                  <p className="text-[13px] font-semibold leading-tight" style={{ color: "var(--home-text)" }}>
                    {step.label}
                  </p>
                  <p className="text-[11px]" style={{ color: "var(--home-text-muted)" }}>
                    {step.detail}
                  </p>
                </div>
              </div>
              {i < steps.length - 1 && (
                <div
                  className="w-px h-4 ml-[17px] my-0.5"
                  style={{ backgroundColor: "var(--home-border)" }}
                  aria-hidden="true"
                />
              )}
            </motion.div>
          );
        })}
      </div>
    </motion.div>
  );
}
