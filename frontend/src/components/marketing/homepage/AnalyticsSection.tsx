"use client";

import { motion, useReducedMotion } from "framer-motion";
import { SectionHeading } from "./shared/SectionHeading";
import { fadeUp, scaleIn, staggerChildren, viewportOnce, reducedVariants } from "./shared/motion";
import { AnalyticsMockup } from "./mockups/AnalyticsMockup";
import { RevenueMockup } from "./mockups/RevenueMockup";

const metrics = [
  "Occupancy", "Revenue", "Lead sources", "Channel mix",
  "Guest satisfaction", "Review score", "ADR", "Booking trends",
];

export function AnalyticsSection() {
  const reduced = useReducedMotion();
  const item = reduced ? reducedVariants : fadeUp;

  return (
    <section className="py-16 sm:py-24">
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <SectionHeading
          eyebrow="Analytics"
          title="Decisions backed by your own numbers"
          subtitle="Live dashboards for the metrics that run a property — no exports, no spreadsheets, no waiting for month-end."
        />

        <motion.div
          className="mt-10 flex flex-wrap justify-center gap-2"
          variants={reduced ? reducedVariants : staggerChildren}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          {metrics.map((m) => (
            <motion.span
              key={m}
              variants={item}
              className="px-3.5 py-1.5 rounded-full border text-[13px] font-medium"
              style={{
                borderColor: "var(--home-border)",
                backgroundColor: "var(--home-card)",
                color: "var(--home-text-muted)",
              }}
            >
              {m}
            </motion.span>
          ))}
        </motion.div>

        <motion.div
          className="mt-10 grid md:grid-cols-2 gap-5 max-w-4xl mx-auto items-start"
          variants={reduced ? reducedVariants : scaleIn}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          <AnalyticsMockup />
          <RevenueMockup />
        </motion.div>
      </div>
    </section>
  );
}
