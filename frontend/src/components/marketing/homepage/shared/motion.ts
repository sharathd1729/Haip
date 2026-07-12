import type { Variants } from "framer-motion";

/**
 * Shared Framer Motion variants for the homepage.
 * All entrance animations are subtle (fade / small translate / slight scale).
 * Components should pair these with `useReducedMotion()` — see `useHomeMotion`.
 */

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.55, ease: [0.21, 0.47, 0.32, 0.98] },
  },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.5, ease: "easeOut" } },
};

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.55, ease: [0.21, 0.47, 0.32, 0.98] },
  },
};

export const blurIn: Variants = {
  hidden: { opacity: 0, filter: "blur(6px)" },
  visible: {
    opacity: 1,
    filter: "blur(0px)",
    transition: { duration: 0.6, ease: "easeOut" },
  },
};

export const staggerChildren: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08, delayChildren: 0.05 } },
};

/** Standard in-view config: animate once, start slightly before fully visible. */
export const viewportOnce = { once: true, margin: "-60px" } as const;

/** Variants that collapse to a no-op for prefers-reduced-motion users. */
export const reducedVariants: Variants = {
  hidden: { opacity: 1 },
  visible: { opacity: 1 },
};
