"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Workflow, Clock, ShieldCheck } from "@/lib/icons";
import { SectionHeading } from "./shared/SectionHeading";
import { fadeUp, staggerChildren, viewportOnce, reducedVariants } from "./shared/motion";
import { AutomationFlowMockup } from "./mockups/AutomationFlowMockup";

const points = [
  {
    icon: Workflow,
    title: "Build once, run for every booking",
    desc: "Design the guest journey once — HAIP runs it for every reservation, on every channel.",
  },
  {
    icon: Clock,
    title: "Perfectly timed",
    desc: "Reminders before check-in, guides on arrival, review requests after checkout. Never early, never forgotten.",
  },
  {
    icon: ShieldCheck,
    title: "Human where it matters",
    desc: "Sensitive steps pause for approval — automation handles the routine, your team handles judgment.",
  },
];

export function AutomationSection() {
  const reduced = useReducedMotion();
  const item = reduced ? reducedVariants : fadeUp;

  return (
    <section className="py-16 sm:py-24" style={{ backgroundColor: "var(--home-card)" }}>
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <div className="grid lg:grid-cols-2 gap-10 lg:gap-14 items-center">
          <div>
            <SectionHeading
              align="left"
              eyebrow="Automations"
              title="The guest journey, on autopilot"
              subtitle="From booking confirmation to the next-stay upsell — every step fires automatically at the right moment."
            />
            <motion.div
              className="mt-8 flex flex-col gap-5"
              variants={reduced ? reducedVariants : staggerChildren}
              initial="hidden"
              whileInView="visible"
              viewport={viewportOnce}
            >
              {points.map((p) => (
                <motion.div key={p.title} variants={item} className="flex gap-3">
                  <div
                    className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                    style={{ backgroundColor: "var(--home-accent-soft)", color: "var(--home-accent)" }}
                  >
                    <p.icon size={16} />
                  </div>
                  <div>
                    <h3 className="text-[15px] font-semibold mb-1" style={{ color: "var(--home-text)" }}>
                      {p.title}
                    </h3>
                    <p className="text-[13px] leading-relaxed" style={{ color: "var(--home-text-muted)" }}>
                      {p.desc}
                    </p>
                  </div>
                </motion.div>
              ))}
            </motion.div>
          </div>

          <div className="max-w-md mx-auto w-full">
            <AutomationFlowMockup />
          </div>
        </div>
      </div>
    </section>
  );
}
