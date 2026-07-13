"use client";

import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight, PlayCircle, CreditCard, Zap, ShieldCheck } from "lucide-react";
import { fadeUp, staggerChildren, viewportOnce, reducedVariants } from "./shared/motion";
import { InboxMockup } from "./mockups/InboxMockup";
import { AiAssistantMockup } from "./mockups/AiAssistantMockup";
import { RevenueMockup } from "./mockups/RevenueMockup";

const trustItems = [
  { icon: CreditCard, label: "No credit card required" },
  { icon: Zap, label: "Fast setup" },
  { icon: ShieldCheck, label: "Enterprise security" },
];

export function HeroSection() {
  const reduced = useReducedMotion();
  const item = reduced ? reducedVariants : fadeUp;

  return (
    <section className="relative overflow-hidden pt-28 sm:pt-36 pb-16 sm:pb-24">
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <div className="grid lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] gap-12 lg:gap-10 items-center">
          {/* ── Copy ─────────────────────────────────────────────── */}
          <motion.div
            variants={reduced ? reducedVariants : staggerChildren}
            initial="hidden"
            animate="visible"
            className="max-w-xl"
          >
            <motion.p
              variants={item}
              className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] mb-5 px-3 py-1.5 rounded-full border"
              style={{
                color: "var(--home-accent)",
                borderColor: "rgba(11,107,94,0.25)",
                backgroundColor: "var(--home-accent-soft)",
              }}
            >
              Hospitality CRM & Operations Platform
            </motion.p>

            <motion.h1
              variants={item}
              className="text-4xl sm:text-5xl lg:text-[3.4rem] font-bold leading-[1.08] tracking-tight"
              style={{
                color: "var(--home-text)",
                fontFamily: "var(--font-display), ui-sans-serif, system-ui, sans-serif",
              }}
            >
              The Hospitality CRM built for modern hotels, resorts &amp; vacation rentals.
            </motion.h1>

            <motion.p
              variants={item}
              className="mt-5 text-base sm:text-lg leading-relaxed"
              style={{ color: "var(--home-text-muted)" }}
            >
              Manage WhatsApp, Instagram, OTA conversations, Voice AI, bookings, guest
              relationships and automations from one unified platform.
            </motion.p>

            <motion.div variants={item} className="mt-8 flex flex-col sm:flex-row gap-3">
              <Link
                href="/book-demo"
                className="inline-flex items-center justify-center gap-2 px-6 py-3.5 min-h-[48px] text-[15px] font-semibold rounded-xl text-white transition-colors duration-200"
                style={{ backgroundColor: "var(--home-accent)" }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "var(--home-accent-hover)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "var(--home-accent)"; }}
              >
                Book demo <ArrowRight size={16} />
              </Link>
              <Link
                href="/features"
                className="inline-flex items-center justify-center gap-2 px-6 py-3.5 min-h-[48px] text-[15px] font-semibold rounded-xl border transition-colors duration-200"
                style={{
                  color: "var(--home-text)",
                  borderColor: "var(--home-border)",
                  backgroundColor: "var(--home-card)",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--home-accent)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--home-border)"; }}
              >
                <PlayCircle size={16} /> Watch product tour
              </Link>
            </motion.div>

            <motion.ul variants={item} className="mt-7 flex flex-wrap gap-x-5 gap-y-2">
              {trustItems.map((t) => (
                <li
                  key={t.label}
                  className="inline-flex items-center gap-1.5 text-[13px]"
                  style={{ color: "var(--home-text-muted)" }}
                >
                  <t.icon size={14} style={{ color: "var(--home-accent)" }} />
                  {t.label}
                </li>
              ))}
            </motion.ul>
          </motion.div>

          {/* ── Product showcase — layered cards ─────────────────── */}
          <motion.div
            className="relative max-w-[560px] mx-auto lg:mx-0 lg:ml-auto"
            initial={reduced ? undefined : { opacity: 0, y: 28 }}
            animate={reduced ? undefined : { opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.15, ease: [0.21, 0.47, 0.32, 0.98] }}
          >
            {/* Main inbox card */}
            <InboxMockup className="relative z-10 w-full" />

            {/* Floating cards — positioned relative to this same 560px box, lg+ only.
                Below lg there isn't reliably enough room beside the inbox card to
                float without overlapping it, so both stack below instead. */}
            <motion.div
              className="hidden lg:block absolute -bottom-10 -left-12 z-20 w-[230px]"
              initial={reduced ? undefined : { opacity: 0, y: 20 }}
              animate={reduced ? undefined : { opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.45, ease: "easeOut" }}
            >
              <AiAssistantMockup />
            </motion.div>

            <motion.div
              className="hidden lg:block absolute -top-10 -right-8 xl:-right-16 z-0 w-[210px]"
              initial={reduced ? undefined : { opacity: 0, y: -16 }}
              animate={reduced ? undefined : { opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.6, ease: "easeOut" }}
            >
              <RevenueMockup />
            </motion.div>

            {/* Mobile & tablet: stacked below instead of floating */}
            <div className="lg:hidden mt-4">
              <AiAssistantMockup />
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
