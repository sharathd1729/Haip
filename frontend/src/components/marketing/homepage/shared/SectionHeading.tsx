"use client";

import { motion, useReducedMotion } from "framer-motion";
import { fadeUp, viewportOnce, reducedVariants } from "./motion";

/**
 * Eyebrow + headline + subtitle pattern shared by every homepage section.
 * Renders semantic heading levels and keeps typography rhythm consistent.
 */
export function SectionHeading({
  eyebrow,
  title,
  subtitle,
  align = "center",
  as: Heading = "h2",
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  align?: "left" | "center";
  as?: "h2" | "h3";
}) {
  const reduced = useReducedMotion();
  const variants = reduced ? reducedVariants : fadeUp;
  const alignCls = align === "center" ? "text-center mx-auto" : "text-left";

  return (
    <motion.div
      className={`max-w-3xl ${alignCls}`}
      variants={variants}
      initial="hidden"
      whileInView="visible"
      viewport={viewportOnce}
    >
      {eyebrow && (
        <p
          className="text-xs font-semibold uppercase tracking-[0.14em] mb-3"
          style={{ color: "var(--home-accent)" }}
        >
          {eyebrow}
        </p>
      )}
      <Heading
        className="text-3xl sm:text-4xl lg:text-[2.75rem] font-bold leading-[1.12] tracking-tight"
        style={{
          color: "var(--home-text)",
          fontFamily: "var(--font-display), ui-sans-serif, system-ui, sans-serif",
        }}
      >
        {title}
      </Heading>
      {subtitle && (
        <p
          className="mt-4 text-base sm:text-lg leading-relaxed"
          style={{ color: "var(--home-text-muted)" }}
        >
          {subtitle}
        </p>
      )}
    </motion.div>
  );
}
