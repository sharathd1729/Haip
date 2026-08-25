"use client";

import { motion, useReducedMotion } from "framer-motion";
import { IndianRupee, Heart, Star } from "@/lib/icons";
import { BedDouble } from "lucide-react";
import { SectionHeading } from "./shared/SectionHeading";
import { fadeUp, scaleIn, staggerChildren, viewportOnce, reducedVariants } from "./shared/motion";
import { CrmMockup } from "./mockups/CrmMockup";
import { GuestTimelineMockup } from "./mockups/GuestTimelineMockup";

const highlights = [
  {
    icon: BedDouble,
    title: "Previous stays & upcoming bookings",
    desc: "The complete stay history and what's next — visible the moment a guest messages.",
  },
  {
    icon: IndianRupee,
    title: "Lifetime revenue",
    desc: "Know exactly what each relationship is worth before you quote.",
  },
  {
    icon: Heart,
    title: "Preferences & tags",
    desc: "Dietary needs, room preferences, occasions — remembered across every stay.",
  },
  {
    icon: Star,
    title: "Sentiment & reviews",
    desc: "How each guest feels, drawn from their conversations and public reviews.",
  },
];

export function CrmSection() {
  const reduced = useReducedMotion();
  const item = reduced ? reducedVariants : fadeUp;

  return (
    <section className="py-16 sm:py-24">
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <div className="grid lg:grid-cols-2 gap-10 lg:gap-14 items-center">
          {/* Mockups first on desktop for left/right rhythm with inbox section */}
          <motion.div
            className="order-2 lg:order-1 grid sm:grid-cols-2 gap-4 items-start"
            variants={reduced ? reducedVariants : scaleIn}
            initial="hidden"
            whileInView="visible"
            viewport={viewportOnce}
          >
            <CrmMockup />
            <GuestTimelineMockup className="hidden sm:block" />
          </motion.div>

          <div className="order-1 lg:order-2">
            <SectionHeading
              align="left"
              eyebrow="Hospitality CRM"
              title="Know every guest like a regular"
              subtitle="One profile holds everything — stays, revenue, preferences, sentiment and reviews — so every interaction feels personal."
            />
            <motion.div
              className="mt-8 grid sm:grid-cols-2 gap-5"
              variants={reduced ? reducedVariants : staggerChildren}
              initial="hidden"
              whileInView="visible"
              viewport={viewportOnce}
            >
              {highlights.map((h) => (
                <motion.div key={h.title} variants={item} className="flex gap-3">
                  <div
                    className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                    style={{ backgroundColor: "var(--home-accent-soft)", color: "var(--home-accent)" }}
                  >
                    <h.icon size={16} />
                  </div>
                  <div>
                    <h3 className="text-[15px] font-semibold mb-1" style={{ color: "var(--home-text)" }}>
                      {h.title}
                    </h3>
                    <p className="text-[13px] leading-relaxed" style={{ color: "var(--home-text-muted)" }}>
                      {h.desc}
                    </p>
                  </div>
                </motion.div>
              ))}
            </motion.div>
          </div>
        </div>
      </div>
    </section>
  );
}
