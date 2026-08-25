"use client";

import { motion, useReducedMotion } from "framer-motion";
import { MessageSquare, Camera, Phone, Mail, Globe, Table2, Database, ArrowDown, ArrowRight, LayoutGrid } from "@/lib/icons";
import { SectionHeading } from "./shared/SectionHeading";
import { fadeUp, staggerChildren, viewportOnce, reducedVariants } from "./shared/motion";

const scattered = [
  { icon: MessageSquare, label: "WhatsApp" },
  { icon: Camera, label: "Instagram" },
  { icon: Phone, label: "Calls" },
  { icon: Mail, label: "Email" },
  { icon: Globe, label: "OTA messages" },
  { icon: Table2, label: "Google Sheets" },
  { icon: Database, label: "CRM" },
];

export function ProblemSolutionSection() {
  const reduced = useReducedMotion();
  const item = reduced ? reducedVariants : fadeUp;

  return (
    <section className="py-16 sm:py-24">
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <SectionHeading
          eyebrow="The problem"
          title="Guest conversations are scattered across seven tools"
          subtitle="Every missed message is a missed booking. Teams juggle apps, spreadsheets and call logs — and the guest experience pays for it."
        />

        <motion.div
          className="mt-12 grid lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] gap-6 lg:gap-8 items-stretch"
          variants={reduced ? reducedVariants : staggerChildren}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          {/* Without HAIP */}
          <motion.div
            variants={item}
            className="rounded-2xl border p-6 sm:p-8"
            style={{ borderColor: "var(--home-border)", backgroundColor: "var(--home-card)" }}
          >
            <p className="text-sm font-semibold mb-1" style={{ color: "var(--home-error)" }}>
              Without HAIP
            </p>
            <p className="text-[13px] mb-6" style={{ color: "var(--home-text-muted)" }}>
              Seven disconnected tools. No single guest record.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
              {scattered.map((s, i) => (
                <div
                  key={s.label}
                  className="rounded-lg border px-3 py-2.5 flex items-center gap-2"
                  style={{
                    borderColor: "var(--home-border)",
                    backgroundColor: "#F6F6F4",
                    transform: reduced ? undefined : `rotate(${(i % 3) - 1}deg)`,
                  }}
                >
                  <s.icon size={14} className="shrink-0" style={{ color: "var(--home-text-subtle)" }} />
                  <span className="text-[12px] font-medium truncate" style={{ color: "var(--home-text-muted)" }}>
                    {s.label}
                  </span>
                </div>
              ))}
            </div>
            <ul className="mt-6 space-y-1.5">
              {["Inquiries slip through the cracks", "No context when a guest calls back", "Reporting lives in spreadsheets"].map((line) => (
                <li key={line} className="text-[13px] flex items-start gap-2" style={{ color: "var(--home-text-muted)" }}>
                  <span className="mt-[7px] w-1 h-1 rounded-full shrink-0" style={{ backgroundColor: "var(--home-error)" }} />
                  {line}
                </li>
              ))}
            </ul>
          </motion.div>

          {/* Arrow */}
          <motion.div variants={item} className="flex items-center justify-center" aria-hidden="true">
            <div
              className="w-11 h-11 rounded-full flex items-center justify-center border"
              style={{ borderColor: "var(--home-border)", backgroundColor: "var(--home-card)", color: "var(--home-accent)" }}
            >
              <ArrowRight size={18} className="hidden lg:block" />
              <ArrowDown size={18} className="lg:hidden" />
            </div>
          </motion.div>

          {/* With HAIP */}
          <motion.div
            variants={item}
            className="rounded-2xl p-6 sm:p-8 border"
            style={{
              borderColor: "rgba(11,107,94,0.30)",
              backgroundColor: "var(--home-card)",
              boxShadow: "var(--home-shadow-md)",
            }}
          >
            <p className="text-sm font-semibold mb-1" style={{ color: "var(--home-accent)" }}>
              With HAIP
            </p>
            <p className="text-[13px] mb-6" style={{ color: "var(--home-text-muted)" }}>
              Every channel unified into one intelligent workspace.
            </p>

            <div
              className="rounded-xl border p-5 flex flex-col items-center gap-4"
              style={{ borderColor: "var(--home-border)", backgroundColor: "#FAFAF8" }}
            >
              <div className="flex flex-wrap justify-center gap-2">
                {scattered.slice(0, 5).map((s) => (
                  <div
                    key={s.label}
                    className="w-8 h-8 rounded-lg flex items-center justify-center border"
                    style={{ borderColor: "var(--home-border)", backgroundColor: "var(--home-card)", color: "var(--home-accent)" }}
                    title={s.label}
                  >
                    <s.icon size={14} />
                  </div>
                ))}
              </div>
              <ArrowDown size={14} style={{ color: "var(--home-text-subtle)" }} aria-hidden="true" />
              <div
                className="rounded-xl px-5 py-3.5 flex items-center gap-2.5 text-white"
                style={{ backgroundColor: "var(--home-accent)" }}
              >
                <LayoutGrid size={16} />
                <span className="text-sm font-semibold">One HAIP workspace</span>
              </div>
            </div>

            <ul className="mt-6 space-y-1.5">
              {["Every inquiry answered from one inbox", "Full guest history on every conversation", "Bookings, revenue and reviews connected"].map((line) => (
                <li key={line} className="text-[13px] flex items-start gap-2" style={{ color: "var(--home-text-muted)" }}>
                  <span className="mt-[7px] w-1 h-1 rounded-full shrink-0" style={{ backgroundColor: "var(--home-success)" }} />
                  {line}
                </li>
              ))}
            </ul>
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}
