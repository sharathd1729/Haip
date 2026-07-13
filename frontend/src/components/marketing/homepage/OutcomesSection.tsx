"use client";

import { motion, useReducedMotion } from "framer-motion";
import {
  Timer, Target, MessagesSquare, TrendingUp, UsersRound, HeartHandshake,
} from "lucide-react";
import { SectionHeading } from "./shared/SectionHeading";
import { fadeUp, staggerChildren, viewportOnce, reducedVariants } from "./shared/motion";

const outcomes = [
  {
    icon: Timer,
    title: "Reply faster",
    desc: "Drafted responses with live availability and rates — answer in seconds, not hours.",
  },
  {
    icon: Target,
    title: "Never miss a lead",
    desc: "Every inquiry from every channel lands in one queue with an owner and a deadline.",
  },
  {
    icon: MessagesSquare,
    title: "Automate guest support",
    desc: "Common questions answered instantly from your knowledge base, 24/7.",
  },
  {
    icon: TrendingUp,
    title: "Increase direct bookings",
    desc: "Convert OTA and social inquiries into direct, commission-free reservations.",
  },
  {
    icon: UsersRound,
    title: "Reduce staff workload",
    desc: "Routine follow-ups, reminders and data entry handled without human effort.",
  },
  {
    icon: HeartHandshake,
    title: "Improve guest experience",
    desc: "Personal, timely communication at every step — from inquiry to review.",
  },
];

export function OutcomesSection() {
  const reduced = useReducedMotion();
  const item = reduced ? reducedVariants : fadeUp;

  return (
    <section className="py-16 sm:py-24" style={{ backgroundColor: "var(--home-card)" }}>
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <SectionHeading
          eyebrow="Outcomes"
          title="What changes when everything is connected"
          subtitle="Not features for a demo — results your team feels in the first month."
        />

        <motion.div
          className="mt-12 grid sm:grid-cols-2 lg:grid-cols-3 gap-4"
          variants={reduced ? reducedVariants : staggerChildren}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          {outcomes.map((o) => (
            <motion.div
              key={o.title}
              variants={item}
              className="rounded-xl border p-6 transition-all duration-200"
              style={{ borderColor: "var(--home-border)", backgroundColor: "#FAFAF8" }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "rgba(11,107,94,0.35)";
                e.currentTarget.style.boxShadow = "var(--home-shadow-md)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "var(--home-border)";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center mb-4"
                style={{ backgroundColor: "var(--home-accent-soft)", color: "var(--home-accent)" }}
              >
                <o.icon size={18} />
              </div>
              <h3 className="text-base font-semibold mb-1.5" style={{ color: "var(--home-text)" }}>
                {o.title}
              </h3>
              <p className="text-sm leading-relaxed" style={{ color: "var(--home-text-muted)" }}>
                {o.desc}
              </p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
