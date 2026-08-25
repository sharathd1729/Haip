"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Tags, Sparkles, StickyNote, History } from "@/lib/icons";
import { SectionHeading } from "./shared/SectionHeading";
import { fadeUp, scaleIn, staggerChildren, viewportOnce, reducedVariants } from "./shared/motion";
import { InboxMockup } from "./mockups/InboxMockup";

const features = [
  {
    icon: Tags,
    title: "Labels that route work",
    desc: "Hot leads, VIPs and complaints are tagged automatically and land with the right person.",
  },
  {
    icon: Sparkles,
    title: "AI-suggested replies",
    desc: "Drafts written from live availability, rates and the guest's own history — reviewed before sending.",
  },
  {
    icon: StickyNote,
    title: "Internal notes",
    desc: "Discuss a conversation privately with your team without leaving the thread.",
  },
  {
    icon: History,
    title: "Full guest history",
    desc: "Every past stay, call and message visible beside the conversation — no tab switching.",
  },
];

export function UnifiedInboxSection() {
  const reduced = useReducedMotion();
  const item = reduced ? reducedVariants : fadeUp;

  return (
    <section className="py-16 sm:py-24" style={{ backgroundColor: "var(--home-card)" }}>
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <div className="grid lg:grid-cols-2 gap-10 lg:gap-14 items-center">
          <div>
            <SectionHeading
              align="left"
              eyebrow="Unified Inbox"
              title="Every channel. One timeline."
              subtitle="WhatsApp, Instagram, website chat, OTA messages and Voice AI calls merge into a single conversation per guest."
            />
            <motion.div
              className="mt-8 grid sm:grid-cols-2 gap-5"
              variants={reduced ? reducedVariants : staggerChildren}
              initial="hidden"
              whileInView="visible"
              viewport={viewportOnce}
            >
              {features.map((f) => (
                <motion.div key={f.title} variants={item} className="flex gap-3">
                  <div
                    className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                    style={{ backgroundColor: "var(--home-accent-soft)", color: "var(--home-accent)" }}
                  >
                    <f.icon size={16} />
                  </div>
                  <div>
                    <h3 className="text-[15px] font-semibold mb-1" style={{ color: "var(--home-text)" }}>
                      {f.title}
                    </h3>
                    <p className="text-[13px] leading-relaxed" style={{ color: "var(--home-text-muted)" }}>
                      {f.desc}
                    </p>
                  </div>
                </motion.div>
              ))}
            </motion.div>
          </div>

          <motion.div
            variants={reduced ? reducedVariants : scaleIn}
            initial="hidden"
            whileInView="visible"
            viewport={viewportOnce}
          >
            <InboxMockup />
          </motion.div>
        </div>
      </div>
    </section>
  );
}
