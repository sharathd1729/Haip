"use client";

import { motion, useReducedMotion } from "framer-motion";
import {
  Accordion, AccordionContent, AccordionItem, AccordionTrigger,
} from "@/components/ui/accordion";
import { SectionHeading } from "./shared/SectionHeading";
import { fadeUp, viewportOnce, reducedVariants } from "./shared/motion";

const faqs = [
  {
    q: "How long does setup take?",
    a: "Most properties are live within a few days. We connect your WhatsApp Business account, Instagram and OTA channels, import your guest data, and train your team — onboarding is included in every plan.",
  },
  {
    q: "Do I need to change my phone number or WhatsApp account?",
    a: "No. HAIP connects to your existing WhatsApp Business account through Meta's official Cloud API. Your number, chat history and verified business profile stay exactly as they are.",
  },
  {
    q: "Does HAIP replace my property management system?",
    a: "No — HAIP works alongside your PMS. We sync bookings and availability so your PMS remains the source of truth, while HAIP handles guest communication, CRM and automation on top of it.",
  },
  {
    q: "How does the AI handle guest conversations?",
    a: "The AI drafts replies using your live availability, rates and each guest's history. Your team reviews and sends — or you can allow automatic replies for routine questions. You control exactly how much runs on autopilot.",
  },
  {
    q: "Is guest data secure and compliant?",
    a: "Yes. Data is encrypted at rest and in transit, hosted in India (AWS Mumbai), and handled in line with the DPDP Act — including consent tracking and deletion workflows.",
  },
  {
    q: "Can I use HAIP across multiple properties?",
    a: "Yes. Scale and Enterprise plans support multi-property dashboards with per-property teams, reporting and automations — all under one login.",
  },
];

export function FaqSection() {
  const reduced = useReducedMotion();

  return (
    <section className="py-16 sm:py-24" style={{ backgroundColor: "var(--home-card)" }}>
      <div className="max-w-3xl mx-auto px-5 sm:px-8">
        <SectionHeading
          eyebrow="FAQ"
          title="Frequently asked questions"
        />

        <motion.div
          className="mt-10"
          variants={reduced ? reducedVariants : fadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
        >
          <Accordion multiple={false} className="w-full">
            {faqs.map((f, i) => (
              <AccordionItem
                key={f.q}
                value={`faq-${i}`}
                className="border-b"
                style={{ borderColor: "var(--home-border)" }}
              >
                <AccordionTrigger
                  className="text-left text-[15px] font-semibold py-5 hover:no-underline"
                  style={{ color: "var(--home-text)" }}
                >
                  {f.q}
                </AccordionTrigger>
                <AccordionContent
                  className="text-sm leading-relaxed pb-5"
                  style={{ color: "var(--home-text-muted)" }}
                >
                  {f.a}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </motion.div>
      </div>
    </section>
  );
}
