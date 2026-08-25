"use client";

import Link from "next/link";
import { useRef, useState, useEffect } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, ArrowRight, Inbox, Phone, Users, MessageSquare, Star, BarChart2 } from "@/lib/icons";
import { InboxMockup, CallsMockup, CRMMockup, WhatsAppMockup, QAMockup, InsightsMockup } from "@/components/marketing/FeatureMockups";

// ─── Shared motion variants ───────────────────────────────────────────────────
const fadeUp = { hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } } };
const scaleUp = { hidden: { opacity: 0, scale: 0.97 }, visible: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: "easeOut" as const } } };
const VP = { once: true, margin: "-60px" } as const;

// ─── Feature data ─────────────────────────────────────────────────────────────
const features = [
  {
    id: "inbox", num: "01", icon: <Inbox size={20} />, title: "Unified Inbox",
    desc: "All guest communication channels in one place. WhatsApp, Instagram DMs, and calls unified with full history and AI-powered suggested replies.",
    bullets: ["WhatsApp Business API (Meta official)", "Instagram DMs & mentions", "Phone call thread with transcript", "AI reply suggestions", "Team assignment & handoffs"],
    Mockup: InboxMockup,
  },
  {
    id: "calls", num: "02", icon: <Phone size={20} />, title: "AI Call Intelligence",
    desc: "Every call transcribed, scored, and analyzed automatically. Surface missed revenue, coaching opportunities, and guest signals—without listening to a single recording.",
    bullets: ["Auto-transcription in Indian English", "Agent QA scoring (0–100)", "Sentiment analysis", "Missed revenue opportunity flags", "Integrates with CallerDesk, Acefone, Servetel, MCube"],
    Mockup: CallsMockup,
  },
  {
    id: "crm", num: "03", icon: <Users size={20} />, title: "Hospitality CRM",
    desc: "A CRM purpose-built for hospitality. Guest profiles, property management, inquiry tracking, and booking history—all connected.",
    bullets: ["Rich guest profiles with communication history", "Property & villa management", "Inquiry pipeline with Kanban view", "Stay history & preferences", "Hostaway & PMS sync"],
    Mockup: CRMMockup,
  },
  {
    id: "whatsapp", num: "04", icon: <MessageSquare size={20} />, title: "WhatsApp Automation",
    desc: "Send targeted campaigns, automate booking confirmations, and run drip sequences via WhatsApp—using the official Meta Cloud API.",
    bullets: ["Bulk broadcast to opted-in guests", "Template message library", "Automated booking confirmations", "No-code campaign builder", "Meta Embedded Signup (no developer needed)"],
    Mockup: WhatsAppMockup,
  },
  {
    id: "qa", num: "05", icon: <Star size={20} />, title: "Auto QA & Compliance",
    desc: "Automated quality review for every guest interaction. DPDP-compliant archiving. No manual audit required.",
    bullets: ["100% call coverage scoring", "Customizable QA rubrics", "DPDP-compliant archiving", "Agent performance trends", "Exportable compliance reports"],
    Mockup: QAMockup,
  },
  {
    id: "insights", num: "06", icon: <BarChart2 size={20} />, title: "AI Insights",
    desc: "Revenue intelligence and demand forecasting from your call and message data. Know what guests want before they ask.",
    bullets: ["Demand pattern analysis", "Revenue gap identification", "Agent coaching recommendations", "Seasonal trend detection", "Weekly insights digest"],
    Mockup: InsightsMockup,
  },
];

// ─── Sticky feature nav ───────────────────────────────────────────────────────
function FeatureNav({ activeId }: { activeId: string }) {
  function scrollTo(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div
      className="sticky top-[80px] z-30 bg-white/95 backdrop-blur-md border-b overflow-x-auto scrollbar-hide"
      style={{ borderColor: "#E2E8F0" }}
    >
      <div className="max-w-7xl mx-auto px-5 sm:px-8 flex gap-0">
        {features.map(f => (
          <button
            key={f.id}
            onClick={() => scrollTo(f.id)}
            className="flex items-center gap-1.5 px-4 py-4 text-sm font-medium whitespace-nowrap border-b-2 transition-all duration-150 flex-shrink-0"
            style={f.id === activeId
              ? { color: "#00555a", borderColor: "#00555a" }
              : { color: "#64748B", borderColor: "transparent" }
            }
            onMouseEnter={e => { if (f.id !== activeId) (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
            onMouseLeave={e => { if (f.id !== activeId) (e.currentTarget as HTMLElement).style.color = "#64748B"; }}
          >
            {f.title}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function FeaturesPage() {
  const [activeId, setActiveId] = useState(features[0].id);
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    const observer = new IntersectionObserver(
      entries => {
        entries.forEach(e => { if (e.isIntersecting) setActiveId(e.target.id); });
      },
      { rootMargin: "-40% 0px -55% 0px" }
    );
    features.forEach(f => {
      const el = document.getElementById(f.id);
      if (el) { sectionRefs.current[f.id] = el; observer.observe(el); }
    });
    return () => observer.disconnect();
  }, []);

  return (
    <div className="bg-white">

      {/* ── Hero ──────────────────────────────────────────────────────── */}
      <section className="py-24 px-5 sm:px-8" style={{ backgroundColor: "#003d41" }}>
        <div className="max-w-3xl mx-auto text-center">
          <motion.div variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.08 } } }} initial="hidden" animate="visible">
            <motion.span
              variants={fadeUp}
              className="inline-block rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider mb-6"
              style={{ backgroundColor: "rgba(255,201,75,0.18)", color: "#ffc94b" }}
            >
              Platform Features
            </motion.span>
            <motion.h1
              variants={fadeUp}
              className="font-black tracking-tight text-white mb-5"
              style={{ fontSize: "clamp(36px, 5vw, 56px)" }}
            >
              Everything your team needs
            </motion.h1>
            <motion.p variants={fadeUp} className="text-lg max-w-xl mx-auto" style={{ color: "rgba(255,201,75,0.65)" }}>
              One platform, built specifically for luxury hospitality operations.
            </motion.p>
          </motion.div>
        </div>
      </section>

      {/* ── Sticky nav ────────────────────────────────────────────────── */}
      <FeatureNav activeId={activeId} />

      {/* ── Feature sections ──────────────────────────────────────────── */}
      {features.map((f, idx) => {
        const isEven = idx % 2 === 0;
        const { Mockup } = f;

        const textBlock = (
          <motion.div
            variants={{ hidden: { opacity: 0, x: isEven ? -24 : 24 }, visible: { opacity: 1, x: 0, transition: { duration: 0.5, ease: "easeOut" as const } } }}
            whileInView="visible" initial="hidden" viewport={VP}
          >
            <span className="text-sm font-black block mb-2" style={{ color: "#ffc94b" }}>{f.num}</span>
            <h2 className="text-3xl font-bold mb-4" style={{ color: "#0F172A" }}>{f.title}</h2>
            <p className="text-lg leading-relaxed mb-6" style={{ color: "#475569" }}>{f.desc}</p>
            <ul className="space-y-2.5 mb-8">
              {f.bullets.map(b => (
                <li key={b} className="flex items-start gap-3">
                  <CheckCircle2 size={18} className="flex-shrink-0 mt-0.5" style={{ color: "#00555a" }} />
                  <span style={{ color: "#334155" }}>{b}</span>
                </li>
              ))}
            </ul>
            <Link
              href="/register"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-sm text-white transition-all duration-200"
              style={{ backgroundColor: "#00555a" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#004a4f"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#00555a"; }}
            >
              Try free for 14 days <ArrowRight size={14} />
            </Link>
          </motion.div>
        );

        const mockBlock = (
          <motion.div
            variants={scaleUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl p-6 border"
            style={{ backgroundColor: "#F8FAFC", borderColor: "#E2E8F0", boxShadow: "0 16px 40px rgba(0,0,0,0.07)", outline: "1px solid rgba(0,85,90,0.05)" }}
          >
            <Mockup />
          </motion.div>
        );

        return (
          <section
            key={f.id}
            id={f.id}
            className="py-24 px-5 sm:px-8 scroll-mt-32"
            style={{ borderBottom: idx < features.length - 1 ? "1px solid #E2E8F0" : "none" }}
          >
            <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
              {isEven ? <>{textBlock}{mockBlock}</> : <>{mockBlock}{textBlock}</>}
            </div>
          </section>
        );
      })}

      {/* ── Final CTA ─────────────────────────────────────────────────── */}
      <section
        className="py-28 px-5 sm:px-8 relative overflow-hidden"
        style={{ background: "linear-gradient(135deg, #003d41 0%, #00555a 100%)" }}
      >
        <div className="absolute right-0 top-0 rounded-full pointer-events-none" style={{ width: 320, height: 320, background: "rgba(255,201,75,0.05)", filter: "blur(72px)" }} />
        <div className="max-w-3xl mx-auto text-center relative">
          <motion.div variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.1 } } }} whileInView="visible" initial="hidden" viewport={VP}>
            <motion.h2 variants={fadeUp} className="font-black text-white mb-4" style={{ fontSize: "clamp(32px, 5vw, 52px)" }}>
              Ready to see it in action?
            </motion.h2>
            <motion.p variants={fadeUp} className="text-lg mb-8" style={{ color: "rgba(255,201,75,0.65)" }}>
              Book a personalised demo and see how GenHaip works for your property.
            </motion.p>
            <motion.div variants={fadeUp} className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link
                href="/book-demo"
                className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all duration-200"
                style={{ backgroundColor: "#ffc94b", color: "#00555a", boxShadow: "0 8px 24px rgba(255,201,75,0.28)" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}
              >
                Book a Demo <ArrowRight size={18} />
              </Link>
              <Link
                href="/register"
                className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-semibold text-base text-white transition-all duration-200"
                style={{ border: "2px solid rgba(255,255,255,0.22)" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.42)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.22)"; }}
              >
                Try free for 14 days
              </Link>
            </motion.div>
          </motion.div>
        </div>
      </section>
    </div>
  );
}
