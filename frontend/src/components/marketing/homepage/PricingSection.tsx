"use client";

import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import { Check, ArrowRight } from "lucide-react";
import { SectionHeading } from "./shared/SectionHeading";
import { fadeUp, staggerChildren, viewportOnce, reducedVariants } from "./shared/motion";

const plans = [
  {
    name: "Starter",
    price: "₹3,999",
    period: "/mo",
    desc: "For independent properties getting organised.",
    features: [
      "Unified inbox — WhatsApp & Instagram",
      "Guest CRM & timeline",
      "Basic automations",
      "1 property · 3 team members",
    ],
    cta: "Book demo",
    highlighted: false,
  },
  {
    name: "Growth",
    price: "₹6,999",
    period: "/mo",
    desc: "For teams ready to grow direct bookings.",
    features: [
      "Everything in Starter",
      "Voice AI call intelligence",
      "OTA messaging",
      "AI-suggested replies",
      "Review management",
    ],
    cta: "Book demo",
    highlighted: false,
  },
  {
    name: "Scale",
    price: "₹9,999",
    period: "/mo",
    desc: "For multi-property operators.",
    features: [
      "Everything in Growth",
      "Multi-property dashboards",
      "Advanced automations",
      "Revenue intelligence",
      "Priority support",
    ],
    cta: "Book demo",
    highlighted: false,
  },
  {
    name: "Enterprise",
    price: "₹15,000",
    period: "+/mo",
    desc: "For chains and management companies.",
    features: [
      "Everything in Scale",
      "Unlimited properties & users",
      "Custom integrations",
      "Dedicated success manager",
      "SLA & enterprise security review",
    ],
    cta: "Talk to sales",
    highlighted: true,
  },
];

export function PricingSection() {
  const reduced = useReducedMotion();
  const item = reduced ? reducedVariants : fadeUp;

  return (
    <section className="py-16 sm:py-24" id="pricing">
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <SectionHeading
          eyebrow="Pricing"
          title="Plans that grow with your property"
          subtitle="Transparent monthly pricing. No setup fees, no per-conversation charges."
        />

        <motion.div
          className="mt-12 grid sm:grid-cols-2 xl:grid-cols-4 gap-4 items-stretch"
          variants={reduced ? reducedVariants : staggerChildren}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          {plans.map((plan) => (
            <motion.div
              key={plan.name}
              variants={item}
              className="rounded-2xl border p-6 flex flex-col relative"
              style={
                plan.highlighted
                  ? {
                      borderColor: "var(--home-accent)",
                      backgroundColor: "var(--home-card)",
                      boxShadow: "var(--home-shadow-lg)",
                    }
                  : { borderColor: "var(--home-border)", backgroundColor: "var(--home-card)" }
              }
            >
              {plan.highlighted && (
                <span
                  className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full text-[11px] font-semibold text-white whitespace-nowrap"
                  style={{ backgroundColor: "var(--home-accent)" }}
                >
                  Recommended
                </span>
              )}
              <h3 className="text-lg font-bold" style={{ color: "var(--home-text)" }}>
                {plan.name}
              </h3>
              <p className="text-[13px] mt-1 min-h-[2.5rem]" style={{ color: "var(--home-text-muted)" }}>
                {plan.desc}
              </p>
              <p className="mt-4 mb-6">
                <span className="text-3xl font-bold tracking-tight" style={{ color: "var(--home-text)" }}>
                  {plan.price}
                </span>
                <span className="text-sm" style={{ color: "var(--home-text-subtle)" }}>
                  {plan.period}
                </span>
              </p>
              <ul className="space-y-2.5 flex-1">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-[13px]" style={{ color: "var(--home-text-muted)" }}>
                    <Check size={14} className="shrink-0 mt-0.5" style={{ color: "var(--home-success)" }} />
                    {f}
                  </li>
                ))}
              </ul>
              <Link
                href={plan.highlighted ? "/contact" : "/book-demo"}
                className="mt-6 inline-flex items-center justify-center gap-1.5 w-full px-4 py-3 min-h-[46px] rounded-xl text-sm font-semibold transition-colors duration-200"
                style={
                  plan.highlighted
                    ? { backgroundColor: "var(--home-accent)", color: "#FFFFFF" }
                    : {
                        backgroundColor: "transparent",
                        color: "var(--home-accent)",
                        border: "1px solid var(--home-border)",
                      }
                }
                onMouseEnter={(e) => {
                  if (plan.highlighted) e.currentTarget.style.backgroundColor = "var(--home-accent-hover)";
                  else e.currentTarget.style.borderColor = "var(--home-accent)";
                }}
                onMouseLeave={(e) => {
                  if (plan.highlighted) e.currentTarget.style.backgroundColor = "var(--home-accent)";
                  else e.currentTarget.style.borderColor = "var(--home-border)";
                }}
              >
                {plan.cta} <ArrowRight size={14} />
              </Link>
            </motion.div>
          ))}
        </motion.div>

        <p className="mt-8 text-center text-[13px]" style={{ color: "var(--home-text-subtle)" }}>
          All plans include onboarding, data migration and DPDP-compliant data handling.
        </p>
      </div>
    </section>
  );
}
