"use client";

import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { fadeUp, viewportOnce, reducedVariants } from "./shared/motion";

export function FinalCtaSection() {
  const reduced = useReducedMotion();

  return (
    <section className="py-16 sm:py-24">
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <motion.div
          className="rounded-3xl px-6 py-14 sm:px-12 sm:py-20 text-center"
          style={{ backgroundColor: "var(--home-accent)" }}
          variants={reduced ? reducedVariants : fadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          <h2
            className="text-3xl sm:text-4xl lg:text-[2.75rem] font-bold leading-[1.12] tracking-tight text-white max-w-2xl mx-auto"
            style={{ fontFamily: "var(--font-display), ui-sans-serif, system-ui, sans-serif" }}
          >
            Ready to modernize your hospitality operations?
          </h2>
          <p className="mt-4 text-base sm:text-lg text-white/70 max-w-xl mx-auto">
            See how HAIP unifies your guest conversations, bookings and team — in a 30-minute walkthrough.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row justify-center gap-3">
            <Link
              href="/book-demo"
              className="inline-flex items-center justify-center gap-2 px-7 py-3.5 min-h-[48px] rounded-xl text-[15px] font-semibold transition-colors duration-200"
              style={{ backgroundColor: "#FFFFFF", color: "var(--home-accent)" }}
              onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#F0F0EC"; }}
              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "#FFFFFF"; }}
            >
              Book demo <ArrowRight size={16} />
            </Link>
            <Link
              href="/contact"
              className="inline-flex items-center justify-center gap-2 px-7 py-3.5 min-h-[48px] rounded-xl text-[15px] font-semibold text-white border border-white/30 transition-colors duration-200"
              onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.10)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
            >
              Talk to sales
            </Link>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
