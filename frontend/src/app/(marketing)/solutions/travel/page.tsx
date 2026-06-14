"use client";

import Link from "next/link";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowRight, MessageSquare, Phone, Sparkles, Map, Compass,
  BarChart2, TrendingUp, Shield, ChevronDown, ChevronRight, Plane, Calendar, FileText, Star,
} from "lucide-react";

const fadeUp = { hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } } };
const scaleUp = { hidden: { opacity: 0, scale: 0.97 }, visible: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: "easeOut" as const } } };
const stagger = { visible: { transition: { staggerChildren: 0.08 } } };
const VP = { once: true, margin: "-50px" } as const;

const painPoints = [
  { icon: <MessageSquare size={18} />, title: "Enquiry-to-quote takes 6+ hours on a good day", desc: "Trip designers manually pull itineraries, rates, transport options into a quote PDF. By the time you reply, the guest has booked elsewhere." },
  { icon: <Map size={18} />, title: "Itinerary knowledge lives in someone's head", desc: "The founder knows the best stops. The new trip designer doesn't. Quality drops the moment volume scales past one person." },
  { icon: <Calendar size={18} />, title: "Multi-day pre-trip engagement is ad hoc", desc: "Dietary preferences, special occasions, transport details — collected via 14 separate WhatsApp messages over 2 weeks. Half get missed." },
  { icon: <BarChart2 size={18} />, title: "You can't tell which marketing actually works", desc: "Direct ~70%, referral ~25% — sure. But which campaigns? Which keywords? Which Instagram posts? Pure guesswork." },
];

const features = [
  { icon: <Sparkles size={20} />, title: "AI Trip Designer", desc: "Drafts complete itineraries from your knowledge base — activities, restaurants, photographers, transfers, route options. You curate, then send as a beautiful quote PDF in minutes, not hours." },
  { icon: <FileText size={20} />, title: "Brand-voice grounded replies", desc: "RAG knowledge base of your past itineraries, FAQs, rate plans, transfer options. The AI Concierge reads like your founder wrote it — because it learned from your founder." },
  { icon: <Calendar size={20} />, title: "Multi-day pre-trip sequences", desc: "Automated D-14 itinerary doc, D-7 dietary + occasion check, D-1 driver briefing, D-day welcome. On WhatsApp, on schedule, every time." },
  { icon: <Phone size={20} />, title: "Every discovery call auto-scored", desc: "CallerDesk forwards your number to the founder/trip designer's mobile. HAIP auto-transcribes, scores discovery quality, flags missed upsells, and writes a wrap-up — within 90 seconds." },
  { icon: <Compass size={20} />, title: "Lost-reason intelligence", desc: "Wrong dates · weather concern · budget mismatch · couldn't decide on route — weekly clustered themes from your lost enquiries, so you know exactly what to fix next." },
  { icon: <Shield size={20} />, title: "Guest 360 for repeat clients", desc: "Lifetime stays, past objections, predicted CSAT, suggested opener — surfaced the moment a repeat client messages. Perfect for high-value experiential travel." },
];

const stats = [
  { value: "<30min", label: "Enquiry-to-quote (vs 6+ hrs)" },
  { value: ">60%", label: "Enquiries auto-handled" },
  { value: ">80%", label: "Direct booking target" },
  { value: ">90%", label: "Pre-trip prefs collected" },
];

const faqs = [
  { q: "Is HAIP only for big DMCs or also for solo travel founders?", a: "Both. Our design partner Ratha — a luxury caravan / experiential journey operator — runs HAIP as a founder-led team. The Starter plan is built for that exact shape. As you scale to a team of trip designers, role-scoped access and coaching kick in." },
  { q: "Does the AI actually understand niche itineraries?", a: "It understands what you teach it. The RAG knowledge base ingests your past itineraries, sample quote PDFs, rate plans, partner network. Day-1 the AI Concierge stays in shadow mode — drafts replies, you approve. After 30 days it goes autonomous on high-confidence enquiries." },
  { q: "What about visa, payments, partner coordination?", a: "HAIP centralises the conversation; we integrate with your existing payment links and partner WhatsApp groups. Visa workflows and supplier orchestration are on the H2 2026 roadmap." },
  { q: "Can we run multiple brands or sub-brands on one account?", a: "Yes — per-brand workspaces with their own number, knowledge base, AI Concierge voice and team. Roll-up reporting at the parent level for owners." },
  { q: "We deal with international clients. Does WhatsApp / IVR work globally?", a: "WhatsApp Cloud API works globally; we provision an Indian DID by default. International virtual numbers via CallerDesk/Acefone are on case-by-case basis." },
];

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ borderBottom: "1px solid #E2E8F0" }}>
      <button className="w-full flex items-center justify-between py-5 text-left gap-4" onClick={() => setOpen(o => !o)}>
        <span className="font-semibold" style={{ color: "#0F172A" }}>{q}</span>
        <ChevronDown size={16} className="flex-shrink-0 transition-transform duration-200" style={{ color: "#00555a", transform: open ? "rotate(180deg)" : "rotate(0deg)" }} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1, transition: { duration: 0.2 } }} exit={{ height: 0, opacity: 0, transition: { duration: 0.15 } }} className="overflow-hidden">
            <p className="pb-5 leading-relaxed" style={{ color: "#475569" }}>{a}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

const itinerary = [
  { day: "D1–2", title: "Manali · acclimatise + sound bath", bg: "rgba(251,191,36,0.12)", text: "#fbbf24" },
  { day: "D3–4", title: "Kaza · monastery circuit + stargazing", bg: "rgba(168,85,247,0.12)", text: "#c084fc" },
  { day: "D5–6", title: "Kibber · private chef + glacier walk", bg: "rgba(6,182,212,0.12)", text: "#22d3ee" },
  { day: "D7–9", title: "Tabo · monastery + photographer", bg: "rgba(0,85,90,0.18)", text: "#5eead4" },
  { day: "D10–11", title: "Kalpa · descent + spa wrap", bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
];

export default function TravelSolutionPage() {
  return (
    <div className="bg-white">

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden py-24 px-5 sm:px-8" style={{ backgroundColor: "#003d41" }}>
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-24 -right-24 rounded-full" style={{ width: 480, height: 480, background: "radial-gradient(circle, rgba(255,201,75,0.07) 0%, transparent 70%)" }} />
          <div className="absolute bottom-0 left-0 rounded-full" style={{ width: 320, height: 320, background: "radial-gradient(circle, rgba(0,85,90,0.40) 0%, transparent 70%)" }} />
        </div>
        <div className="max-w-7xl mx-auto relative grid lg:grid-cols-12 gap-12 items-center">
          <div className="lg:col-span-7">
            <motion.div variants={stagger} initial="hidden" animate="visible">
              <motion.div variants={fadeUp} className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 mb-6" style={{ backgroundColor: "rgba(255,201,75,0.15)", border: "1px solid rgba(255,201,75,0.25)" }}>
                <Plane size={12} style={{ color: "#ffc94b" }} />
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#ffc94b" }}>For travel &amp; experiential operators</span>
              </motion.div>
              <motion.h1 variants={fadeUp} className="font-black tracking-tight text-white mb-5" style={{ fontSize: "clamp(36px, 5vw, 58px)", lineHeight: 1.08 }}>
                From discovery call<br />
                <span style={{ color: "#ffc94b" }}>to fifth-star review.</span>
              </motion.h1>
              <motion.p variants={fadeUp} className="text-lg leading-relaxed mb-8" style={{ color: "rgba(255,255,255,0.60)", maxWidth: 520 }}>
                HAIP is the AI-first communication platform for experiential travel operators — luxury caravans, multi-day journeys, DMCs, bespoke trip designers. Capture every enquiry, generate quotes in minutes, and remember every traveller.
              </motion.p>
              <motion.div variants={fadeUp} className="flex flex-col sm:flex-row gap-3 mb-5">
                <Link href="/register?plan=growth&segment=travel"
                  className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-bold text-sm transition-all duration-200"
                  style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                  Start 14-day free trial <ArrowRight size={16} />
                </Link>
                <Link href="/book-demo?segment=travel"
                  className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-semibold text-sm text-white transition-all duration-200"
                  style={{ border: "1px solid rgba(255,255,255,0.18)" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.35)"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.18)"; }}>
                  Book a 30-min demo
                </Link>
              </motion.div>
              <motion.p variants={fadeUp} className="text-xs" style={{ color: "rgba(255,255,255,0.30)" }}>Built with Ratha · India&apos;s premier luxury caravan operator</motion.p>
            </motion.div>
          </div>

          {/* Hero mockup: trip-designer quote card */}
          <div className="lg:col-span-5">
            <motion.div variants={scaleUp} initial="hidden" animate="visible"
              className="rounded-2xl p-5" style={{ backgroundColor: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)" }}>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <p className="text-xs font-semibold text-white">Anjali &amp; Rohan</p>
                  <p className="text-[10px]" style={{ color: "rgba(255,255,255,0.40)" }}>Honeymoon · Spiti caravan · 11 nights</p>
                </div>
                <span className="text-[10px] px-2 py-1 rounded-md font-semibold" style={{ backgroundColor: "rgba(0,85,90,0.30)", color: "#5eead4" }}>Quote ready · 18 min</span>
              </div>
              <div className="space-y-2 mb-4">
                {itinerary.map(d => (
                  <div key={d.day} className="flex items-center gap-3 rounded-lg px-3 py-2" style={{ backgroundColor: "rgba(255,255,255,0.04)" }}>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded flex-shrink-0" style={{ backgroundColor: d.bg, color: d.text }}>{d.day}</span>
                    <span className="text-xs truncate" style={{ color: "rgba(255,255,255,0.70)" }}>{d.title}</span>
                  </div>
                ))}
              </div>
              <div className="rounded-xl p-3 space-y-1.5" style={{ backgroundColor: "rgba(255,201,75,0.08)", border: "1px solid rgba(255,201,75,0.18)" }}>
                <div className="flex items-start gap-2">
                  <Sparkles size={11} style={{ color: "#ffc94b" }} className="flex-shrink-0 mt-0.5" />
                  <p className="text-[11px] font-medium" style={{ color: "rgba(255,201,75,0.90)" }}>AI drafted quote in 4 min · founder approved · sent on WhatsApp</p>
                </div>
                <div className="flex items-start gap-2">
                  <TrendingUp size={11} style={{ color: "#fbbf24" }} className="flex-shrink-0 mt-0.5" />
                  <p className="text-[11px]" style={{ color: "rgba(251,191,36,0.80)" }}>Suggested add-ons: photographer (₹65K) · in-caravan chef (₹40K)</p>
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* ── Stats ────────────────────────────────────────────────────────── */}
      <section className="py-14 px-5 sm:px-8 border-b" style={{ borderColor: "#E2E8F0" }}>
        <div className="max-w-4xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-8">
          {stats.map((s, i) => (
            <motion.div key={s.label} variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} transition={{ delay: i * 0.06 }} className="text-center">
              <p className="font-black tabular-nums mb-1" style={{ fontSize: 32, color: "#00555a", lineHeight: 1 }}>{s.value}</p>
              <p className="text-xs" style={{ color: "#64748B" }}>{s.label}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── Pain points ──────────────────────────────────────────────────── */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} className="text-center mb-14">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#f43f5e" }}>The trip designer&apos;s reality</p>
            <h2 className="text-3xl sm:text-4xl font-bold mb-4" style={{ color: "#0F172A" }}>High-deal-value, long-discovery, everything-bespoke</h2>
            <p className="text-base" style={{ color: "#475569", maxWidth: 520, margin: "0 auto" }}>Experiential travel runs on intimate conversations and detailed itineraries. The work is craft. The admin is crushing.</p>
          </motion.div>
          <motion.div className="grid sm:grid-cols-2 gap-4" variants={stagger} whileInView="visible" initial="hidden" viewport={VP}>
            {painPoints.map(p => (
              <motion.div key={p.title} variants={fadeUp} className="rounded-2xl p-6" style={{ backgroundColor: "#FFF1F2", border: "1px solid #FECDD3" }}>
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#FFE4E6" }}>
                    <span style={{ color: "#f43f5e" }}>{p.icon}</span>
                  </div>
                  <div>
                    <h3 className="text-base font-bold mb-1.5" style={{ color: "#0F172A" }}>{p.title}</h3>
                    <p className="text-sm leading-relaxed" style={{ color: "#475569" }}>{p.desc}</p>
                  </div>
                </div>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ── Features ─────────────────────────────────────────────────────── */}
      <section className="py-20 px-5 sm:px-8" style={{ backgroundColor: "#F8FAFC" }}>
        <div className="max-w-6xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} className="text-center mb-14">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#00555a" }}>Built for experiential travel</p>
            <h2 className="text-3xl sm:text-4xl font-bold" style={{ color: "#0F172A" }}>Your trip-designer team, multiplied</h2>
          </motion.div>
          <motion.div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4" variants={stagger} whileInView="visible" initial="hidden" viewport={VP}>
            {features.map(f => (
              <motion.div key={f.title} variants={scaleUp} className="rounded-2xl p-6 bg-white transition-all duration-200" style={{ border: "1px solid #E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(0,85,90,0.25)"; (e.currentTarget as HTMLElement).style.boxShadow = "0 6px 20px rgba(0,0,0,0.08)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "#E2E8F0"; (e.currentTarget as HTMLElement).style.boxShadow = "0 1px 3px rgba(0,0,0,0.04)"; }}>
                <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-4" style={{ backgroundColor: "rgba(0,85,90,0.08)" }}>
                  <span style={{ color: "#00555a" }}>{f.icon}</span>
                </div>
                <h3 className="text-base font-bold mb-2" style={{ color: "#0F172A" }}>{f.title}</h3>
                <p className="text-sm leading-relaxed" style={{ color: "#475569" }}>{f.desc}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ── Testimonial — Ratha ──────────────────────────────────────────── */}
      <section className="py-16 px-5 sm:px-8">
        <div className="max-w-3xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl p-10 relative overflow-hidden" style={{ backgroundColor: "#003d41" }}>
            <div className="absolute right-0 top-0 pointer-events-none" style={{ width: 280, height: 280, background: "radial-gradient(circle, rgba(255,201,75,0.07) 0%, transparent 70%)" }} />
            <div className="flex gap-1 mb-6">
              {[...Array(5)].map((_, i) => <Star key={i} size={16} fill="#ffc94b" style={{ color: "#ffc94b" }} />)}
            </div>
            <p className="text-lg leading-relaxed mb-8" style={{ color: "rgba(255,255,255,0.80)", fontStyle: "italic" }}>
              &ldquo;We design 11-night journeys across Spiti, Ladakh and the Northeast. Every enquiry used to feel like reinventing the wheel. HAIP turned our past 200 itineraries into a knowledge base — and now the first quote draft lands inside 30 minutes. Repeat-client retention is up, and we&apos;ve doubled trip designer capacity without doubling the team.&rdquo;
            </p>
            <div className="flex items-center gap-4">
              <div className="w-11 h-11 rounded-full flex items-center justify-center font-bold text-sm" style={{ backgroundColor: "rgba(255,201,75,0.20)", color: "#ffc94b" }}>R</div>
              <div>
                <p className="font-semibold text-white">Ratha</p>
                <p className="text-sm" style={{ color: "rgba(255,255,255,0.40)" }}>Luxury Caravan Travel &amp; Experiential Journeys · HAIP design partner</p>
              </div>
              <Link href="/case-studies/ratha" className="ml-auto inline-flex items-center gap-1 text-xs font-semibold" style={{ color: "#ffc94b" }}>
                Read case study <ChevronRight size={12} />
              </Link>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── FAQ ──────────────────────────────────────────────────────────── */}
      <section className="py-16 px-5 sm:px-8" style={{ backgroundColor: "#F8FAFC" }}>
        <div className="max-w-2xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} className="text-center mb-10">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#00555a" }}>FAQ</p>
            <h2 className="text-2xl font-bold" style={{ color: "#0F172A" }}>Trip designer questions</h2>
          </motion.div>
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl bg-white p-6 sm:p-8" style={{ border: "1px solid #E2E8F0" }}>
            {faqs.map(f => <FAQItem key={f.q} {...f} />)}
          </motion.div>
        </div>
      </section>

      {/* ── Final CTA ─────────────────────────────────────────────────────── */}
      <section className="py-28 px-5 sm:px-8 relative overflow-hidden" style={{ background: "linear-gradient(135deg, #003d41 0%, #00555a 100%)" }}>
        <div className="absolute right-0 top-0 pointer-events-none" style={{ width: 400, height: 400, background: "rgba(255,201,75,0.05)", filter: "blur(72px)" }} />
        <div className="max-w-3xl mx-auto text-center relative">
          <motion.div variants={stagger} whileInView="visible" initial="hidden" viewport={VP}>
            <motion.div variants={fadeUp} className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-6" style={{ backgroundColor: "rgba(255,201,75,0.15)", border: "1px solid rgba(255,201,75,0.25)" }}>
              <Plane size={24} style={{ color: "#ffc94b" }} />
            </motion.div>
            <motion.h2 variants={fadeUp} className="font-black text-white mb-4" style={{ fontSize: "clamp(30px, 5vw, 50px)", lineHeight: 1.1 }}>Stop typing itineraries.<br />Start designing journeys.</motion.h2>
            <motion.p variants={fadeUp} className="text-lg mb-10" style={{ color: "rgba(255,255,255,0.55)", maxWidth: 480, margin: "0 auto 2.5rem" }}>
              HAIP gives your trip-designer team a 200-itinerary memory and an AI co-pilot that drafts in minutes.
            </motion.p>
            <motion.div variants={fadeUp} className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link href="/register?plan=growth&segment=travel"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all duration-200"
                style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                Start free trial <ArrowRight size={18} />
              </Link>
              <Link href="/book-demo?segment=travel"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-semibold text-base text-white transition-all duration-200"
                style={{ border: "2px solid rgba(255,255,255,0.20)" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.40)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.20)"; }}>
                Talk to a trip designer
              </Link>
            </motion.div>
          </motion.div>
        </div>
      </section>
    </div>
  );
}
