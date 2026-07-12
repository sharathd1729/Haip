"use client";

import { motion, useReducedMotion } from "framer-motion";
import {
  Inbox, Users, Phone, CalendarCheck2, IndianRupee, BarChart2,
  Workflow, Star, MessagesSquare, BookOpen,
} from "lucide-react";
import { SectionHeading } from "./shared/SectionHeading";
import { fadeUp, staggerChildren, viewportOnce, reducedVariants } from "./shared/motion";

const modules = [
  { icon: Inbox, title: "Unified Inbox", desc: "WhatsApp, Instagram, OTA and web chat in one queue with full guest context." },
  { icon: Users, title: "Hospitality CRM", desc: "One guest record across every stay, inquiry and conversation." },
  { icon: Phone, title: "Voice AI", desc: "Every call transcribed, summarised and scored — automatically." },
  { icon: CalendarCheck2, title: "Booking Operations", desc: "Reservations, check-ins and housekeeping handoffs in one flow." },
  { icon: IndianRupee, title: "Revenue Intelligence", desc: "Direct booking growth, upsell tracking and missed-revenue flags." },
  { icon: BarChart2, title: "Analytics", desc: "Occupancy, ADR, channel mix and satisfaction on live dashboards." },
  { icon: Workflow, title: "Automations", desc: "Welcome messages, ID collection, reminders and review requests on autopilot." },
  { icon: Star, title: "Review Management", desc: "Monitor, respond and improve scores across Google and OTAs." },
  { icon: MessagesSquare, title: "Team Collaboration", desc: "Internal notes, assignments and approvals inside every conversation." },
  { icon: BookOpen, title: "Knowledge Base", desc: "House guides, policies and FAQs your team and AI answer from." },
];

export function PlatformOverviewSection() {
  const reduced = useReducedMotion();
  const item = reduced ? reducedVariants : fadeUp;

  return (
    <section className="py-16 sm:py-24" style={{ backgroundColor: "var(--home-card)" }}>
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <SectionHeading
          eyebrow="One platform"
          title="Run your entire hospitality business from one place"
          subtitle="Ten modules that share one guest record — so nothing is re-typed, re-asked or lost between tools."
        />

        <motion.div
          className="mt-12 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4"
          variants={reduced ? reducedVariants : staggerChildren}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          {modules.map((m) => (
            <motion.div
              key={m.title}
              variants={item}
              className="group rounded-xl border p-5 transition-all duration-200 hover:-translate-y-0.5"
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
                className="w-9 h-9 rounded-lg flex items-center justify-center mb-3"
                style={{ backgroundColor: "var(--home-accent-soft)", color: "var(--home-accent)" }}
              >
                <m.icon size={17} />
              </div>
              <h3 className="text-[15px] font-semibold mb-1" style={{ color: "var(--home-text)" }}>
                {m.title}
              </h3>
              <p className="text-[13px] leading-relaxed" style={{ color: "var(--home-text-muted)" }}>
                {m.desc}
              </p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
