"use client";

import { useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { Inbox, Users, BarChart2, Sparkles, History, IndianRupee } from "@/lib/icons";
import { SectionHeading } from "./shared/SectionHeading";
import { InboxMockup } from "./mockups/InboxMockup";
import { CrmMockup } from "./mockups/CrmMockup";
import { AnalyticsMockup } from "./mockups/AnalyticsMockup";
import { AiAssistantMockup } from "./mockups/AiAssistantMockup";
import { GuestTimelineMockup } from "./mockups/GuestTimelineMockup";
import { RevenueMockup } from "./mockups/RevenueMockup";

const tabs = [
  { id: "inbox", icon: Inbox, label: "Inbox", node: <InboxMockup /> },
  { id: "crm", icon: Users, label: "CRM", node: <CrmMockup /> },
  { id: "analytics", icon: BarChart2, label: "Analytics", node: <AnalyticsMockup /> },
  { id: "assistant", icon: Sparkles, label: "AI Assistant", node: <AiAssistantMockup /> },
  { id: "timeline", icon: History, label: "Guest Timeline", node: <GuestTimelineMockup /> },
  { id: "revenue", icon: IndianRupee, label: "Revenue", node: <RevenueMockup /> },
] as const;

export function ProductShowcaseSection() {
  const [active, setActive] = useState<(typeof tabs)[number]["id"]>("inbox");
  const reduced = useReducedMotion();
  const current = tabs.find((t) => t.id === active)!;

  return (
    <section className="py-16 sm:py-24">
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <SectionHeading
          eyebrow="Product tour"
          title="See the platform, module by module"
          subtitle="The same guest record powers every screen — switch between modules without losing context."
        />

        {/* Tab bar — horizontally scrollable on mobile */}
        <div
          className="mt-10 flex gap-2 overflow-x-auto pb-2 -mx-5 px-5 sm:mx-0 sm:px-0 sm:justify-center scrollbar-hide"
          role="tablist"
          aria-label="Product modules"
        >
          {tabs.map((t) => {
            const selected = t.id === active;
            return (
              <button
                key={t.id}
                role="tab"
                aria-selected={selected}
                onClick={() => setActive(t.id)}
                className="inline-flex items-center gap-1.5 px-4 py-2.5 min-h-[44px] rounded-lg text-[13px] font-semibold whitespace-nowrap border transition-colors duration-150 shrink-0"
                style={
                  selected
                    ? { backgroundColor: "var(--home-accent)", color: "#FFFFFF", borderColor: "var(--home-accent)" }
                    : { backgroundColor: "var(--home-card)", color: "var(--home-text-muted)", borderColor: "var(--home-border)" }
                }
              >
                <t.icon size={14} />
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Stage */}
        <div className="mt-6 max-w-2xl mx-auto min-h-[380px]">
          <AnimatePresence mode="wait">
            <motion.div
              key={active}
              role="tabpanel"
              initial={reduced ? { opacity: 1 } : { opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduced ? { opacity: 1 } : { opacity: 0, y: -8 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
            >
              {current.node}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}
