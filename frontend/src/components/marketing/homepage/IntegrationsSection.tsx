"use client";

import { useRef, useEffect, useState } from "react";
import type { ComponentType, CSSProperties } from "react";
import { motion, useInView, animate, useReducedMotion } from "framer-motion";
import { MessageCircle, Camera, Phone, Home, Building2, Search, Building, Wallet, CreditCard, Sparkles, Zap, ShieldCheck, Rocket } from "@/lib/icons";
import { SectionHeading } from "./shared/SectionHeading";
import { fadeUp, staggerChildren, viewportOnce, reducedVariants } from "./shared/motion";
import { IntegrationOrbit } from "./mockups/IntegrationOrbit";

type IconComponent = ComponentType<{ size?: number; className?: string; style?: CSSProperties }>;

const mobileNodes: { label: string; icon: IconComponent }[] = [
  { label: "WhatsApp", icon: MessageCircle },
  { label: "Instagram", icon: Camera },
  { label: "Voice AI", icon: Phone },
  { label: "Airbnb", icon: Home },
  { label: "Booking.com", icon: Building2 },
  { label: "Google", icon: Search },
  { label: "RentalWise", icon: Building },
  { label: "Razorpay", icon: Wallet },
  { label: "Stripe", icon: CreditCard },
  { label: "AI Engine", icon: Sparkles },
];

const features = [
  {
    icon: Zap,
    title: "Real-time sync",
    desc: "Every booking, guest message and payment updates instantly across your stack.",
  },
  {
    icon: ShieldCheck,
    title: "Enterprise security",
    desc: "Secure OAuth authentication with encrypted data transfer on every connection.",
  },
  {
    icon: Rocket,
    title: "Setup in minutes",
    desc: "Connect your hospitality stack in a few clicks — no engineering required.",
  },
];

const stats = [
  { value: 15, decimals: 0, prefix: "", suffix: "+", label: "Integrations" },
  { value: 99.99, decimals: 2, prefix: "", suffix: "%", label: "Sync reliability" },
  { value: 2, decimals: 0, prefix: "<", suffix: " sec", label: "Average sync time" },
  { value: 24, decimals: 0, prefix: "", suffix: "/7", label: "Background monitoring" },
];

function StatCounter({
  value,
  decimals = 0,
  prefix = "",
  suffix = "",
}: {
  value: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (!inView) return;
    if (reduced) {
      setDisplay(value);
      return;
    }
    const ctrl = animate(0, value, {
      duration: 1.3,
      ease: "easeOut",
      onUpdate: (v) => setDisplay(v),
    });
    return ctrl.stop;
  }, [inView, value, reduced]);

  return (
    <span ref={ref} className="tabular-nums">
      {prefix}
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
}

export function IntegrationsSection() {
  const reduced = useReducedMotion();
  const item = reduced ? reducedVariants : fadeUp;

  return (
    <section className="py-16 sm:py-24 overflow-hidden">
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <SectionHeading
          eyebrow="Integrations"
          title="Everything works together."
          subtitle="Connect every guest touchpoint into one intelligent hospitality workspace. Manage conversations, bookings, payments, reviews and operations without switching between apps."
        />

        {/* Orbit visual — desktop/tablet */}
        <div className="hidden md:block mt-14">
          <IntegrationOrbit />
        </div>

        {/* Stacked grid fallback — mobile */}
        <motion.div
          className="md:hidden mt-10 grid grid-cols-2 gap-3"
          variants={reduced ? reducedVariants : staggerChildren}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          {mobileNodes.map((n) => (
            <motion.div
              key={n.label}
              variants={item}
              className="rounded-2xl border flex items-center gap-2.5 px-3.5 py-3"
              style={{ borderColor: "var(--home-border)", backgroundColor: "var(--home-card)" }}
            >
              <div
                className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
                style={{ backgroundColor: "var(--home-accent-soft)" }}
              >
                <n.icon size={16} style={{ color: "var(--home-accent)" }} />
              </div>
              <div className="min-w-0">
                <p className="text-[13px] font-semibold truncate" style={{ color: "var(--home-text)" }}>
                  {n.label}
                </p>
                <p className="text-[10px] font-medium flex items-center gap-1" style={{ color: "var(--home-success)" }}>
                  <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: "var(--home-success)" }} />
                  Connected
                </p>
              </div>
            </motion.div>
          ))}
        </motion.div>

        <p className="mt-6 text-center text-[13px]" style={{ color: "var(--home-text-subtle)" }}>
          Plus Email, Calendar, CRM and more — new integrations shipping regularly.
        </p>

        {/* Feature cards */}
        <motion.div
          className="mt-16 grid sm:grid-cols-3 gap-4 max-w-4xl mx-auto"
          variants={reduced ? reducedVariants : staggerChildren}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          {features.map((f) => (
            <motion.div
              key={f.title}
              variants={item}
              className="rounded-xl border p-6"
              style={{ borderColor: "var(--home-border)", backgroundColor: "var(--home-card)" }}
            >
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center mb-4"
                style={{ backgroundColor: "var(--home-accent-soft)", color: "var(--home-accent)" }}
              >
                <f.icon size={18} />
              </div>
              <h3 className="text-[15px] font-semibold mb-1.5" style={{ color: "var(--home-text)" }}>
                {f.title}
              </h3>
              <p className="text-[13px] leading-relaxed" style={{ color: "var(--home-text-muted)" }}>
                {f.desc}
              </p>
            </motion.div>
          ))}
        </motion.div>

        {/* Stats */}
        <motion.div
          className="mt-14 grid grid-cols-2 sm:grid-cols-4 gap-4 sm:gap-6 rounded-2xl border py-8 px-4 sm:px-8"
          style={{ borderColor: "var(--home-border)", backgroundColor: "#FAFAF8" }}
          variants={reduced ? reducedVariants : staggerChildren}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          {stats.map((s) => (
            <motion.div key={s.label} variants={item} className="text-center">
              <p
                className="text-2xl sm:text-3xl font-bold tracking-tight"
                style={{
                  color: "var(--home-accent)",
                  fontFamily: "var(--font-display), ui-sans-serif, system-ui, sans-serif",
                }}
              >
                <StatCounter value={s.value} decimals={s.decimals} prefix={s.prefix} suffix={s.suffix} />
              </p>
              <p className="mt-1 text-[11px] sm:text-xs" style={{ color: "var(--home-text-muted)" }}>
                {s.label}
              </p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
