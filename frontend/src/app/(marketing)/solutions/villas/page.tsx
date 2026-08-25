"use client";

import Link from "next/link";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, CheckCircle2, MessageSquare, Phone, Inbox, Sparkles, Building2, Users, Star, BarChart2, TrendingUp, Shield, ChevronDown, ChevronRight } from "@/lib/icons";

// ─── Motion variants ──────────────────────────────────────────────────────────
const fadeUp = { hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } } };
const scaleUp = { hidden: { opacity: 0, scale: 0.97 }, visible: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: "easeOut" as const } } };
const stagger = { visible: { transition: { staggerChildren: 0.08 } } };
const VP = { once: true, margin: "-50px" } as const;

// ─── Data (copy unchanged) ────────────────────────────────────────────────────
const painPoints = [
  { icon: <MessageSquare size={18} />, title: "Guests message on 5 different channels", desc: "WhatsApp, Instagram DMs, calls, OTA inboxes, email — your reservations team juggles 6 tabs before they reply." },
  { icon: <Phone size={18} />, title: "Calls go unanswered or unreviewed", desc: "High-intent inquiry calls drop. The few that connect are never reviewed for missed upsells or quality." },
  { icon: <Users size={18} />, title: "No single source of truth for guests", desc: "Repeat guests get treated like strangers. Preferences, past stays and special requests live in someone's WhatsApp." },
  { icon: <BarChart2 size={18} />, title: "No visibility into what's working", desc: "Which channels drive bookings? Which agents close best? Which villas convert? Nobody knows — it's all in heads." },
];

const useCases = [
  { icon: <Inbox size={20} />, title: "One inbox for every villa enquiry", desc: "Direct WhatsApp, Instagram DMs, phone enquiries and form submissions — all unified per guest. Assign by villa, by team, or by language." },
  { icon: <Sparkles size={20} />, title: "AI concierge replies in seconds", desc: "HAIP drafts contextual replies trained on your villa inventory, pricing rules, and tone — your team approves with one tap." },
  { icon: <Phone size={20} />, title: "Every inquiry call analyzed", desc: "Auto-transcribed, sentiment-scored, QA-graded. Surfaces missed upsells (private chef, airport pickup, spa add-ons) automatically." },
  { icon: <Building2 size={20} />, title: "Multi-villa pipeline", desc: "Inquiry Kanban broken down by villa with rate-card awareness, availability checks, and one-tap quote generation." },
  { icon: <Star size={20} />, title: "Guest profiles that remember", desc: "Stay history, dietary preferences, anniversaries, past complaints — surfaced the second a guest pings you again." },
  { icon: <Shield size={20} />, title: "DPDP-compliant by default", desc: "Indian-hosted data, consent capture for marketing, encrypted call recordings, role-based access for finance and ops." },
];

const workflows = [
  { step: "01", title: "Capture", desc: "Guest pings on WhatsApp, calls your IVR, or DMs your Instagram — HAIP routes everything into one unified inbox." },
  { step: "02", title: "Qualify", desc: "AI tags the inquiry (dates, party size, villa preference, source), enriches with past stays, and surfaces matched availability." },
  { step: "03", title: "Quote & convert", desc: "Send rate cards, brochures, and payment links from inside the conversation. Track quote-to-booking conversion per agent." },
  { step: "04", title: "Onboard the stay", desc: "Automated pre-arrival sequences, dietary collection, transport coordination — all on WhatsApp, all logged." },
  { step: "05", title: "Learn & improve", desc: "Weekly AI digest: missed revenue, top objections, agent QA, channel ROI. Coach your team with real data." },
];

const stats = [
  { value: "3.2×", label: "Faster guest response" },
  { value: "+22%", label: "Inquiry-to-booking conversion" },
  { value: "₹2.4L", label: "Avg. monthly upsell recovered" },
  { value: "100%", label: "Calls auto-reviewed" },
];

const faqs = [
  { q: "Do you work with a single-villa owner or only with groups?", a: "Both. Our Starter plan is built for single-property owners and unlocks the full unified inbox + AI call intelligence. Most villa groups land on the Growth plan once they cross 3 properties." },
  { q: "Can HAIP work alongside our existing PMS (Hostaway, eZee, Cloudbeds)?", a: "Yes. HAIP is the communication & intelligence layer, not a replacement for your PMS. We sync bookings and guest data — Hostaway is live, others are on the roadmap." },
  { q: "How do guests message us on WhatsApp officially?", a: "HAIP gives you a verified WhatsApp Business number via the official Meta Cloud API. Embedded signup means you're live in under 20 minutes — no developer or BSP middleman needed." },
  { q: "What about our existing phone numbers and IVR?", a: "We integrate with CallerDesk, Acefone, Servetel and MCube. Your numbers and IVR stay the same — HAIP just adds transcription, scoring and inbox sync on top." },
  { q: "Is guest data stored in India?", a: "Yes. Primary data, call recordings and message archives are stored in AWS Mumbai (ap-south-1). HAIP is DPDP-Act ready with consent capture, data subject rights workflows, and retention controls." },
];

// ─── FAQ accordion ────────────────────────────────────────────────────────────
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

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function VillasSolutionPage() {
  return (
    <div className="bg-white">

      {/* ── Hero ────────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden py-24 px-5 sm:px-8" style={{ backgroundColor: "#003d41" }}>
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-24 -right-24 rounded-full" style={{ width: 480, height: 480, background: "radial-gradient(circle, rgba(255,201,75,0.07) 0%, transparent 70%)" }} />
          <div className="absolute bottom-0 left-0 rounded-full" style={{ width: 320, height: 320, background: "radial-gradient(circle, rgba(0,85,90,0.40) 0%, transparent 70%)" }} />
        </div>
        <div className="max-w-7xl mx-auto relative grid lg:grid-cols-12 gap-12 items-center">
          <div className="lg:col-span-7">
            <motion.div variants={stagger} initial="hidden" animate="visible">
              <motion.div variants={fadeUp} className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 mb-6" style={{ backgroundColor: "rgba(255,201,75,0.15)", border: "1px solid rgba(255,201,75,0.25)" }}>
                <Building2 size={12} style={{ color: "#ffc94b" }} />
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#ffc94b" }}>For luxury villas</span>
              </motion.div>
              <motion.h1 variants={fadeUp} className="font-black tracking-tight text-white mb-5" style={{ fontSize: "clamp(36px, 5vw, 58px)", lineHeight: 1.08 }}>
                Every villa enquiry,<br />
                <span style={{ color: "#ffc94b" }}>converted with intelligence.</span>
              </motion.h1>
              <motion.p variants={fadeUp} className="text-lg leading-relaxed mb-8" style={{ color: "rgba(255,255,255,0.60)", maxWidth: 520 }}>
                HAIP is the AI-first communication platform for villa operators. Unified WhatsApp + Calls + Instagram, AI-drafted replies trained on your inventory, and a hospitality CRM that remembers every guest.
              </motion.p>
              <motion.div variants={fadeUp} className="flex flex-col sm:flex-row gap-3 mb-5">
                <Link href="/register?plan=growth&segment=villas"
                  className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-bold text-sm transition-all duration-200"
                  style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                  Start 14-day free trial <ArrowRight size={16} />
                </Link>
                <Link href="/book-demo?segment=villas"
                  className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-semibold text-sm text-white transition-all duration-200"
                  style={{ border: "1px solid rgba(255,255,255,0.18)" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.35)"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.18)"; }}>
                  Book a 30-min demo
                </Link>
              </motion.div>
              <motion.p variants={fadeUp} className="text-xs" style={{ color: "rgba(255,255,255,0.30)" }}>No credit card · Live in under 20 minutes · DPDP-ready</motion.p>
            </motion.div>
          </div>

          {/* Hero mockup card */}
          <div className="lg:col-span-5">
            <motion.div variants={scaleUp} initial="hidden" animate="visible" className="rounded-2xl p-5" style={{ backgroundColor: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", backdropFilter: "blur(12px)" }}>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <div className="w-9 h-9 rounded-full flex items-center justify-center" style={{ backgroundColor: "rgba(74,222,128,0.15)" }}>
                    <MessageSquare size={14} style={{ color: "#4ade80" }} />
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-white">Priya Sharma</p>
                    <p className="text-[10px]" style={{ color: "rgba(255,255,255,0.40)" }}>WhatsApp · New enquiry</p>
                  </div>
                </div>
                <span className="text-[10px] px-2 py-1 rounded-md font-semibold" style={{ backgroundColor: "rgba(0,85,90,0.30)", color: "#5eead4" }}>High intent</span>
              </div>
              <div className="space-y-2 mb-4">
                <div className="rounded-2xl rounded-tl-sm px-3 py-2.5 max-w-[85%]" style={{ backgroundColor: "rgba(255,255,255,0.07)" }}>
                  <p className="text-xs leading-relaxed" style={{ color: "rgba(255,255,255,0.75)" }}>Hi! Looking for a 4BR villa in North Goa for Dec 24-28, family of 8 with 2 kids. Budget around ₹1.2L/night. Need private chef and pool heating.</p>
                </div>
                <div className="rounded-2xl rounded-tr-sm px-3 py-2.5 max-w-[85%] ml-auto" style={{ backgroundColor: "rgba(0,85,90,0.25)" }}>
                  <p className="text-xs leading-relaxed" style={{ color: "rgba(255,255,255,0.85)" }}>Hi Priya! 🌊 Sunset Villa (4BR, private pool, sea view) is available for those dates at ₹1.1L/night. Private chef and heated pool both included. Sending the brochure now.</p>
                </div>
              </div>
              <div className="rounded-xl p-3 space-y-2" style={{ backgroundColor: "rgba(255,201,75,0.08)", border: "1px solid rgba(255,201,75,0.20)" }}>
                <div className="flex items-start gap-2">
                  <Sparkles size={11} style={{ color: "#ffc94b" }} className="flex-shrink-0 mt-0.5" />
                  <p className="text-[11px] font-medium" style={{ color: "#ffc94b" }}>AI auto-tagged: <span className="font-semibold">Dec 24–28 · 4BR · Goa · Family · ₹1.2L budget</span></p>
                </div>
                <div className="flex items-start gap-2">
                  <TrendingUp size={11} style={{ color: "#fbbf24" }} className="flex-shrink-0 mt-0.5" />
                  <p className="text-[11px]" style={{ color: "rgba(251,191,36,0.85)" }}>Upsell opportunity flagged: airport pickup, spa, photographer</p>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2">
                <button className="rounded-lg py-2 text-[11px] font-medium" style={{ backgroundColor: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.55)" }}>Send quote</button>
                <button className="rounded-lg py-2 text-[11px] font-medium" style={{ backgroundColor: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.55)" }}>Block dates</button>
                <button className="rounded-lg py-2 text-[11px] font-semibold text-white" style={{ backgroundColor: "#00555a" }}>Approve reply</button>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* ── Stats ───────────────────────────────────────────────────────── */}
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

      {/* ── Pain points ─────────────────────────────────────────────────── */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} className="text-center mb-14">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#f43f5e" }}>The villa operator&apos;s reality</p>
            <h2 className="text-3xl sm:text-4xl font-bold mb-4" style={{ color: "#0F172A" }}>Running villas shouldn&apos;t feel like running a call center</h2>
            <p className="text-base" style={{ color: "#475569", maxWidth: 520, margin: "0 auto" }}>Most villa businesses lose 20-30% of inbound revenue not because guests don&apos;t want to book — but because operations can&apos;t keep up.</p>
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

      {/* ── Solutions ───────────────────────────────────────────────────── */}
      <section className="py-20 px-5 sm:px-8" style={{ backgroundColor: "#F8FAFC" }}>
        <div className="max-w-6xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} className="text-center mb-14">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#00555a" }}>How HAIP works for villas</p>
            <h2 className="text-3xl sm:text-4xl font-bold" style={{ color: "#0F172A" }}>Six things your team will stop doing manually</h2>
          </motion.div>
          <motion.div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4" variants={stagger} whileInView="visible" initial="hidden" viewport={VP}>
            {useCases.map(u => (
              <motion.div key={u.title} variants={scaleUp} className="rounded-2xl p-6 bg-white transition-all duration-200" style={{ border: "1px solid #E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(0,85,90,0.25)"; (e.currentTarget as HTMLElement).style.boxShadow = "0 6px 20px rgba(0,0,0,0.08)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "#E2E8F0"; (e.currentTarget as HTMLElement).style.boxShadow = "0 1px 3px rgba(0,0,0,0.04)"; }}>
                <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-4" style={{ backgroundColor: "rgba(0,85,90,0.08)" }}>
                  <span style={{ color: "#00555a" }}>{u.icon}</span>
                </div>
                <h3 className="text-base font-bold mb-2" style={{ color: "#0F172A" }}>{u.title}</h3>
                <p className="text-sm leading-relaxed" style={{ color: "#475569" }}>{u.desc}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ── Workflow ─────────────────────────────────────────────────────── */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-4xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} className="text-center mb-14">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#00555a" }}>The villa workflow, automated</p>
            <h2 className="text-3xl sm:text-4xl font-bold" style={{ color: "#0F172A" }}>From first ping to five-star review</h2>
          </motion.div>
          <div className="space-y-3">
            {workflows.map((w, i) => (
              <motion.div key={w.step} variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} transition={{ delay: i * 0.07 }}
                className="flex gap-5 items-start rounded-2xl p-6" style={{ backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0" }}>
                <div className="flex-shrink-0 w-12 h-12 rounded-xl flex items-center justify-center font-black text-sm" style={{ backgroundColor: "rgba(0,85,90,0.08)", color: "#00555a" }}>
                  {w.step}
                </div>
                <div>
                  <h3 className="text-base font-bold mb-1.5" style={{ color: "#0F172A" }}>{w.title}</h3>
                  <p className="text-sm leading-relaxed" style={{ color: "#475569" }}>{w.desc}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Testimonial ─────────────────────────────────────────────────── */}
      <section className="py-16 px-5 sm:px-8" style={{ backgroundColor: "#F8FAFC" }}>
        <div className="max-w-3xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl p-10 relative overflow-hidden" style={{ backgroundColor: "#003d41" }}>
            <div className="absolute right-0 top-0 pointer-events-none" style={{ width: 280, height: 280, background: "radial-gradient(circle, rgba(255,201,75,0.07) 0%, transparent 70%)" }} />
            <div className="flex gap-1 mb-6">
              {[...Array(5)].map((_, i) => <Star key={i} size={16} fill="#ffc94b" style={{ color: "#ffc94b" }} />)}
            </div>
            <p className="text-lg leading-relaxed mb-8" style={{ color: "rgba(255,255,255,0.80)", fontStyle: "italic" }}>
              &ldquo;We run 11 villas across Goa and Coorg. Before HAIP, my reservations team was missing 30% of WhatsApp enquiries during peak hours. Now every enquiry is captured, auto-qualified, and quote-ready in under 4 minutes. Revenue is up 27% YoY and my team is calmer.&rdquo;
            </p>
            <div className="flex items-center gap-4">
              <div className="w-11 h-11 rounded-full flex items-center justify-center font-bold text-sm" style={{ backgroundColor: "rgba(255,201,75,0.20)", color: "#ffc94b" }}>VR</div>
              <div>
                <p className="font-semibold text-white">Vikrant Rao</p>
                <p className="text-sm" style={{ color: "rgba(255,255,255,0.40)" }}>Founder, Ananta Villa Collection</p>
              </div>
              <Link href="/case-studies/ananta" className="ml-auto inline-flex items-center gap-1 text-xs font-semibold" style={{ color: "#ffc94b" }}>
                Read case study <ChevronRight size={12} />
              </Link>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── FAQ ─────────────────────────────────────────────────────────── */}
      <section className="py-16 px-5 sm:px-8">
        <div className="max-w-2xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} className="text-center mb-10">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#00555a" }}>FAQ</p>
            <h2 className="text-2xl font-bold" style={{ color: "#0F172A" }}>Villa-specific questions</h2>
          </motion.div>
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl bg-white p-6 sm:p-8" style={{ border: "1px solid #E2E8F0" }}>
            {faqs.map(f => <FAQItem key={f.q} {...f} />)}
          </motion.div>
        </div>
      </section>

      {/* ── Final CTA ───────────────────────────────────────────────────── */}
      <section className="py-28 px-5 sm:px-8 relative overflow-hidden" style={{ background: "linear-gradient(135deg, #003d41 0%, #00555a 100%)" }}>
        <div className="absolute right-0 top-0 pointer-events-none" style={{ width: 400, height: 400, background: "rgba(255,201,75,0.05)", filter: "blur(72px)" }} />
        <div className="max-w-3xl mx-auto text-center relative">
          <motion.div variants={stagger} whileInView="visible" initial="hidden" viewport={VP}>
            <motion.div variants={fadeUp} className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-6" style={{ backgroundColor: "rgba(255,201,75,0.15)", border: "1px solid rgba(255,201,75,0.25)" }}>
              <Building2 size={24} style={{ color: "#ffc94b" }} />
            </motion.div>
            <motion.h2 variants={fadeUp} className="font-black text-white mb-4" style={{ fontSize: "clamp(30px, 5vw, 50px)", lineHeight: 1.1 }}>Run your villas like a luxury brand</motion.h2>
            <motion.p variants={fadeUp} className="text-lg mb-10" style={{ color: "rgba(255,255,255,0.55)", maxWidth: 480, margin: "0 auto 2.5rem" }}>
              Join villa operators across India who use HAIP to capture every enquiry, convert more bookings, and remember every guest.
            </motion.p>
            <motion.div variants={fadeUp} className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link href="/register?plan=growth&segment=villas"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all duration-200"
                style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                Start 14-day free trial <ArrowRight size={18} />
              </Link>
              <Link href="/book-demo?segment=villas"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-semibold text-base text-white transition-all duration-200"
                style={{ border: "2px solid rgba(255,255,255,0.20)" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.40)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.20)"; }}>
                Talk to sales
              </Link>
            </motion.div>
          </motion.div>
        </div>
      </section>
    </div>
  );
}

