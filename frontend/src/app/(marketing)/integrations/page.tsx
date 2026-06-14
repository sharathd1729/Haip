"use client";

import Link from "next/link";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, MessageSquare, Phone, Database, Globe, CreditCard, Sparkles, Zap } from "lucide-react";

// ─── Motion variants ──────────────────────────────────────────────────────────
const fadeUp = { hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } } };
const scaleUp = { hidden: { opacity: 0, scale: 0.95 }, visible: { opacity: 1, scale: 1, transition: { duration: 0.4, ease: "easeOut" as const } } };
const stagger = { visible: { transition: { staggerChildren: 0.06 } } };
const VP = { once: true, margin: "-50px" } as const;

// ─── Integration data ─────────────────────────────────────────────────────────
type Integration = {
  name: string;
  cat: string;
  status: "Live" | "Coming soon";
  desc: string;
  initial: string;
  bg: string;
  text: string;
};

const INTEGRATIONS: Integration[] = [
  { name: "WhatsApp Business", cat: "Messaging", status: "Live", desc: "Official Meta Cloud API with Embedded Signup. Connect in minutes — no developer needed.", initial: "W", bg: "#166534", text: "#86efac" },
  { name: "Instagram DM", cat: "Messaging", status: "Live", desc: "Instagram DMs and mentions managed from your HAIP inbox, linked to guest profiles.", initial: "IG", bg: "#831843", text: "#f9a8d4" },
  { name: "CallerDesk", cat: "Telephony", status: "Live", desc: "India's leading cloud telephony. Auto-transcription and QA scoring for every call.", initial: "CD", bg: "#1e3a8a", text: "#93c5fd" },
  { name: "Acefone", cat: "Telephony", status: "Live", desc: "Multi-property cloud telephony with DID management and call flow analytics.", initial: "AC", bg: "#4c1d95", text: "#c4b5fd" },
  { name: "Servetel", cat: "Telephony", status: "Live", desc: "Enterprise-grade IVR with HAIP's AI call intelligence layer on every recording.", initial: "SV", bg: "#1e40af", text: "#a5b4fc" },
  { name: "MCube", cat: "Telephony", status: "Live", desc: "Click-to-call, IVR and call tracking for high-volume hospitality sales teams.", initial: "MC", bg: "#065f46", text: "#6ee7b7" },
  { name: "Hostaway", cat: "PMS", status: "Coming soon", desc: "Two-way sync of bookings, guests and inquiry data from your Hostaway account.", initial: "HA", bg: "#7c2d12", text: "#fdba74" },
  { name: "eZee Absolute", cat: "PMS", status: "Coming soon", desc: "Property-level sync of room availability, stay records, and guest data.", initial: "EZ", bg: "#134e4a", text: "#99f6e4" },
  { name: "Cloudbeds", cat: "PMS", status: "Coming soon", desc: "Bidirectional booking and guest profile sync from your Cloudbeds PMS.", initial: "CB", bg: "#1e3a8a", text: "#bfdbfe" },
  { name: "MakeMyTrip", cat: "OTA", status: "Coming soon", desc: "Sync bookings and guest data from MakeMyTrip and Goibibo listings.", initial: "MT", bg: "#7f1d1d", text: "#fca5a5" },
  { name: "Booking.com", cat: "OTA", status: "Coming soon", desc: "Automatic guest message sync and booking alerts from Booking.com inbox.", initial: "BK", bg: "#1e3a5f", text: "#93c5fd" },
  { name: "Airbnb", cat: "OTA", status: "Coming soon", desc: "Guest messages, review nudges, and booking data from your Airbnb listings.", initial: "AB", bg: "#881337", text: "#fda4af" },
  { name: "Razorpay", cat: "Payments", status: "Coming soon", desc: "Payment links in WhatsApp conversations, booking confirmation on payment success.", initial: "RZ", bg: "#1e3a8a", text: "#c7d2fe" },
  { name: "Cashfree", cat: "Payments", status: "Coming soon", desc: "Instant payment links with UPI, card and net banking — inside the guest thread.", initial: "CF", bg: "#14532d", text: "#86efac" },
];

const CATEGORIES = ["All", "Messaging", "Telephony", "PMS", "OTA", "Payments"];

const CAT_ICONS: Record<string, React.ReactNode> = {
  All: <Sparkles size={14} />,
  Messaging: <MessageSquare size={14} />,
  Telephony: <Phone size={14} />,
  PMS: <Database size={14} />,
  OTA: <Globe size={14} />,
  Payments: <CreditCard size={14} />,
};

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function IntegrationsPage() {
  const [activeCategory, setActiveCategory] = useState("All");

  const filtered = INTEGRATIONS.filter(i => activeCategory === "All" || i.cat === activeCategory);
  const liveCount = INTEGRATIONS.filter(i => i.status === "Live").length;
  const soonCount = INTEGRATIONS.filter(i => i.status === "Coming soon").length;

  return (
    <div className="bg-white">

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden py-24 px-5 sm:px-8" style={{ backgroundColor: "#003d41" }}>
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-24 -right-24 rounded-full" style={{ width: 480, height: 480, background: "radial-gradient(circle, rgba(255,201,75,0.07) 0%, transparent 70%)" }} />
          <div className="absolute bottom-0 left-0 rounded-full" style={{ width: 320, height: 320, background: "radial-gradient(circle, rgba(0,85,90,0.40) 0%, transparent 70%)" }} />
        </div>
        <div className="max-w-2xl mx-auto text-center relative">
          <motion.div variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.09 } } }} initial="hidden" animate="visible">
            <motion.div variants={fadeUp} className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 mb-6" style={{ backgroundColor: "rgba(255,201,75,0.15)", border: "1px solid rgba(255,201,75,0.25)" }}>
              <Zap size={11} style={{ color: "#ffc94b" }} />
              <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#ffc94b" }}>Integrations</span>
            </motion.div>
            <motion.h1 variants={fadeUp} className="font-black tracking-tight text-white mb-5" style={{ fontSize: "clamp(36px, 5vw, 56px)", lineHeight: 1.08 }}>
              Works with your<br />
              <span style={{ color: "#ffc94b" }}>existing tools</span>
            </motion.h1>
            <motion.p variants={fadeUp} className="text-lg leading-relaxed" style={{ color: "rgba(255,255,255,0.60)" }}>
              HAIP connects to the platforms you already use.<br className="hidden sm:block" />
              Set up in minutes, not days.
            </motion.p>
          </motion.div>
        </div>
      </section>

      {/* ── Category filter ───────────────────────────────────────────────── */}
      <section className="py-10 px-5 sm:px-8 border-b" style={{ borderColor: "#E2E8F0" }}>
        <div className="max-w-4xl mx-auto flex flex-wrap items-center justify-center gap-2">
          {CATEGORIES.map(cat => {
            const active = activeCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-sm font-semibold transition-all duration-150"
                style={active
                  ? { backgroundColor: "#00555a", color: "#ffffff" }
                  : { backgroundColor: "#F8FAFC", color: "#64748B", border: "1px solid #E2E8F0" }
                }
                onMouseEnter={e => { if (!active) (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
                onMouseLeave={e => { if (!active) (e.currentTarget as HTMLElement).style.color = "#64748B"; }}
              >
                <span style={{ color: active ? "#ffc94b" : "currentColor" }}>{CAT_ICONS[cat]}</span>
                {cat}
              </button>
            );
          })}
        </div>
      </section>

      {/* ── Cards grid ───────────────────────────────────────────────────── */}
      <section className="py-16 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeCategory}
              className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4"
              variants={stagger}
              initial="hidden"
              animate="visible"
              exit={{ opacity: 0, transition: { duration: 0.15 } }}
            >
              {filtered.map(int => {
                const live = int.status === "Live";
                return (
                  <motion.div
                    key={int.name}
                    variants={scaleUp}
                    className="relative rounded-2xl p-6 bg-white transition-all duration-200 overflow-hidden"
                    style={{
                      border: "1px solid #E2E8F0",
                      boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
                      opacity: live ? 1 : 0.75,
                    }}
                    onMouseEnter={e => {
                      if (live) {
                        (e.currentTarget as HTMLElement).style.borderColor = "rgba(0,85,90,0.25)";
                        (e.currentTarget as HTMLElement).style.boxShadow = "0 6px 20px rgba(0,0,0,0.08)";
                      }
                    }}
                    onMouseLeave={e => {
                      (e.currentTarget as HTMLElement).style.borderColor = "#E2E8F0";
                      (e.currentTarget as HTMLElement).style.boxShadow = "0 1px 3px rgba(0,0,0,0.04)";
                    }}
                  >
                    {/* Coming soon overlay badge */}
                    {!live && (
                      <div className="absolute top-3 right-3 text-[10px] font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: "#F1F5F9", color: "#94A3B8" }}>
                        Coming soon
                      </div>
                    )}

                    {/* Top row: logo + name + live badge */}
                    <div className="flex items-center gap-3 mb-4">
                      <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 text-xs font-black" style={{ backgroundColor: int.bg, color: int.text }}>
                        {int.initial}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-bold" style={{ color: "#0F172A" }}>{int.name}</p>
                        {live && (
                          <div className="flex items-center gap-1 mt-0.5">
                            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "#22c55e" }} />
                            <span className="text-[10px] font-semibold" style={{ color: "#16a34a" }}>Live</span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Description */}
                    <p className="text-sm leading-relaxed mb-4" style={{ color: "#475569" }}>{int.desc}</p>

                    {/* Category tag */}
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-full" style={{ backgroundColor: "#F8FAFC", color: "#64748B", border: "1px solid #E2E8F0" }}>
                      {CAT_ICONS[int.cat]}
                      {int.cat}
                    </span>
                  </motion.div>
                );
              })}
            </motion.div>
          </AnimatePresence>
        </div>
      </section>

      {/* ── Stats row ────────────────────────────────────────────────────── */}
      <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
        className="py-6 px-5 text-center text-sm border-t" style={{ borderColor: "#E2E8F0", color: "#94A3B8" }}>
        <span className="font-semibold" style={{ color: "#0F172A" }}>{liveCount} integrations live</span>
        {" · "}
        <span>{soonCount} coming soon</span>
        {" · "}
        <span>Built on official APIs</span>
      </motion.div>

      {/* ── Don't see your tool ───────────────────────────────────────────── */}
      <section className="py-16 px-5 sm:px-8" style={{ backgroundColor: "#F8FAFC" }}>
        <div className="max-w-2xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl p-10 text-center relative overflow-hidden" style={{ backgroundColor: "#003d41" }}>
            <div className="absolute right-0 top-0 pointer-events-none" style={{ width: 280, height: 280, background: "radial-gradient(circle, rgba(255,201,75,0.06) 0%, transparent 70%)" }} />
            <h2 className="text-2xl font-bold text-white mb-3 relative">Don&apos;t see your tool?</h2>
            <p className="mb-8 relative" style={{ color: "rgba(255,255,255,0.50)" }}>
              We&apos;re constantly adding new integrations.<br />Vote for what you need or reach out to our team.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center relative">
              <a href="mailto:integrations@haip.app"
                className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl font-bold text-sm transition-all duration-200"
                style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                Request an integration
              </a>
              <Link href="/register"
                className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl font-semibold text-sm text-white transition-all duration-200"
                style={{ border: "1px solid rgba(255,255,255,0.20)" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.40)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.20)"; }}>
                Start free trial <ArrowRight size={14} />
              </Link>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── Final CTA ─────────────────────────────────────────────────────── */}
      <section className="py-28 px-5 sm:px-8 relative overflow-hidden" style={{ background: "linear-gradient(135deg, #003d41 0%, #00555a 100%)" }}>
        <div className="absolute right-0 top-0 pointer-events-none" style={{ width: 400, height: 400, background: "rgba(255,201,75,0.05)", filter: "blur(72px)" }} />
        <div className="max-w-3xl mx-auto text-center relative">
          <motion.div variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.10 } } }} whileInView="visible" initial="hidden" viewport={VP}>
            <motion.h2 variants={fadeUp} className="font-black text-white mb-4" style={{ fontSize: "clamp(32px, 5vw, 52px)", lineHeight: 1.1 }}>
              Start with 14 days free
            </motion.h2>
            <motion.p variants={fadeUp} className="text-lg mb-10" style={{ color: "rgba(255,255,255,0.55)" }}>
              No credit card. No commitment.<br className="hidden sm:block" />
              See the platform working for your property in minutes.
            </motion.p>
            <motion.div variants={fadeUp} className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link href="/register"
                className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all duration-200"
                style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                Start free trial <ArrowRight size={18} />
              </Link>
              <Link href="/book-demo"
                className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-semibold text-base text-white transition-all duration-200"
                style={{ border: "2px solid rgba(255,255,255,0.20)" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.40)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.20)"; }}>
                Book a demo
              </Link>
            </motion.div>
          </motion.div>
        </div>
      </section>
    </div>
  );
}
