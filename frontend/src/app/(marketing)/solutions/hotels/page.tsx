"use client";

import Link from "next/link";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowRight, MessageSquare, Phone, Inbox, Sparkles,
  Hotel, Users, Star, BarChart2, TrendingUp, Shield, ChevronDown, ChevronRight, CheckCircle2,
} from "lucide-react";

const fadeUp = { hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" } } };
const scaleUp = { hidden: { opacity: 0, scale: 0.97 }, visible: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: "easeOut" } } };
const stagger = { visible: { transition: { staggerChildren: 0.08 } } };
const VP = { once: true, margin: "-50px" } as const;

const painPoints = [
  { icon: <MessageSquare size={18} />, title: "OTA inboxes, WhatsApp and front-desk calls live in 4 different places", desc: "Reservations switches between Booking.com extranet, Airbnb messages, WhatsApp Web, and the phone — losing context every hop." },
  { icon: <Phone size={18} />, title: "After-hours calls get missed or mis-handled", desc: "Late-night room enquiries go to voicemail. The next morning nobody knows what was asked or whether it was followed up." },
  { icon: <BarChart2 size={18} />, title: "Direct vs OTA mix is invisible", desc: "You suspect OTA commissions are eating you alive — but you can't prove how many direct enquiries you actually convert." },
  { icon: <Users size={18} />, title: "Returning guests get treated like first-timers", desc: "No central guest record. Repeat business depends entirely on which staff happens to be on shift." },
];

const features = [
  { icon: <Inbox size={20} />, title: "Unified inbox for every channel", desc: "WhatsApp, Instagram, IVR calls, and direct web enquiries — one inbox, one timeline per guest, with auto-routing by language and shift." },
  { icon: <Sparkles size={20} />, title: "24/7 AI Concierge", desc: "Drafts replies on WhatsApp & web chat using your room types, packages, F&B menus and house rules. Shadow mode for the first 30 days, then autonomous on high-confidence enquiries." },
  { icon: <Phone size={20} />, title: "Every front-desk call auto-reviewed", desc: "Calls forward to your reservations team's mobile via CallerDesk or Acefone. HAIP pulls the recording, transcribes it, and scores it on your QA rubric — 100% coverage, no manual sampling." },
  { icon: <Hotel size={20} />, title: "Multi-property awareness", desc: "Per-property phone numbers, per-property AI knowledge bases, per-property FOH staff scoping. Role-based access so Property A's team only sees Property A." },
  { icon: <TrendingUp size={20} />, title: "Direct vs OTA visibility", desc: "Source attribution from first touch through booking. See exactly how much commission you save by closing direct, and which channels actually pay back." },
  { icon: <Shield size={20} />, title: "DPDP-ready compliance", desc: "Per-tenant KMS keys, hash-chained audit log, consent capture in the IVR greeting, recording retention controls. Audit-ready from day one." },
];

const stats = [
  { value: "<5min", label: "p95 first response (24/7)" },
  { value: "+15pp", label: "Direct booking share" },
  { value: "100%", label: "Call QA coverage" },
  { value: "₹0", label: "Per-call HAIP cost (cost mode)" },
];

const callSteps = [
  { step: "Guest dials", detail: "Calls your published CallerDesk/Acefone number", color: { bg: "rgba(99,102,241,0.12)", text: "#818cf8" } },
  { step: "IVR greets + consent", detail: "Plays brand greeting, captures recording consent", color: { bg: "rgba(168,85,247,0.12)", text: "#c084fc" } },
  { step: "Forward to agent mobile", detail: "Round-robin or sticky to on-duty reservations staff", color: { bg: "rgba(251,191,36,0.12)", text: "#fbbf24" } },
  { step: "Normal phone conversation", detail: "Agent takes the call on their own phone, no app", color: { bg: "rgba(255,255,255,0.05)", text: "rgba(255,255,255,0.50)" } },
  { step: "Webhook → HAIP", detail: "Recording pulled, transcribed, AI-judged, stored on S3", color: { bg: "rgba(0,85,90,0.15)", text: "#5eead4" } },
  { step: "Wrap-up in 90 sec", detail: "AI summary + disposition + next-action in cockpit", color: { bg: "rgba(0,85,90,0.15)", text: "#5eead4" } },
];

const faqs = [
  { q: "Do we have to switch our PMS to use HAIP?", a: "No. HAIP is the communication and intelligence layer that sits beside your PMS. Hostaway is the live integration today — Guesty, eZee and Cloudbeds are on the roadmap. Until then, HAIP works standalone or via webhook." },
  { q: "What telephony provider do you support?", a: "CallerDesk for low-volume / founder-led properties and Acefone for multi-property hotel groups with predictable call volume. Both are BYOC — you keep your own telephony account and pay them directly. We're adapter-agnostic; Exotel and Twilio are on the roadmap." },
  { q: "How does the AI Concierge avoid making things up?", a: "It's grounded in a per-property knowledge base you control (room types, package rules, rate cards, house rules). For the first 30 days every reply is human-approved (shadow mode); after that, only replies above 0.78 confidence go autonomous, everything else queues for review." },
  { q: "Can we limit access by property?", a: "Yes. FOH staff at Property A can be scoped so they never see Property B's data. Compliance and Owner roles see the whole portfolio." },
  { q: "What about OTA messaging (Booking.com, Airbnb)?", a: "OTA inbox sync via Hostaway is in beta. Direct Booking.com / Airbnb adapters are on the H2 2026 roadmap." },
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

export default function HotelsSolutionPage() {
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
                <Hotel size={12} style={{ color: "#ffc94b" }} />
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#ffc94b" }}>For boutique hotels</span>
              </motion.div>
              <motion.h1 variants={fadeUp} className="font-black tracking-tight text-white mb-5" style={{ fontSize: "clamp(36px, 5vw, 58px)", lineHeight: 1.08 }}>
                Front-desk excellence,<br />
                <span style={{ color: "#ffc94b" }}>running on autopilot.</span>
              </motion.h1>
              <motion.p variants={fadeUp} className="text-lg leading-relaxed mb-8" style={{ color: "rgba(255,255,255,0.60)", maxWidth: 520 }}>
                HAIP is the unified inbox and AI concierge for boutique hotels in India. Capture every enquiry across WhatsApp, IG and calls — convert them direct, recover OTA commissions, and remember every guest who walks through your door.
              </motion.p>
              <motion.div variants={fadeUp} className="flex flex-col sm:flex-row gap-3 mb-5">
                <Link href="/register?plan=growth&segment=hotels"
                  className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-bold text-sm transition-all duration-200"
                  style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                  Start 14-day free trial <ArrowRight size={16} />
                </Link>
                <Link href="/book-demo?segment=hotels"
                  className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-semibold text-sm text-white transition-all duration-200"
                  style={{ border: "1px solid rgba(255,255,255,0.18)" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.35)"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.18)"; }}>
                  Book a 30-min demo
                </Link>
              </motion.div>
              <motion.p variants={fadeUp} className="text-xs" style={{ color: "rgba(255,255,255,0.30)" }}>BYOC telephony · Works with your existing PMS · Indian-hosted</motion.p>
            </motion.div>
          </div>

          {/* Hero mockup: booking mix card */}
          <div className="lg:col-span-5">
            <motion.div variants={scaleUp} initial="hidden" animate="visible"
              className="rounded-2xl p-5" style={{ backgroundColor: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)" }}>
              <div className="flex items-center justify-between mb-4">
                <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "rgba(255,255,255,0.40)" }}>Booking mix · Last 30 days</p>
                <span className="text-[10px] px-2 py-1 rounded-md font-semibold" style={{ backgroundColor: "rgba(0,85,90,0.30)", color: "#5eead4" }}>+14% direct</span>
              </div>
              <div className="space-y-3 mb-4">
                {[
                  { name: "Direct (HAIP inbox)", pct: 58, color: "#00555a", count: "84 bookings" },
                  { name: "Booking.com", pct: 22, color: "#3b82f6", count: "32 bookings · ₹84K commission" },
                  { name: "Airbnb", pct: 14, color: "#f43f5e", count: "20 bookings · ₹56K commission" },
                  { name: "Walk-in / other", pct: 6, color: "rgba(255,255,255,0.25)", count: "9 bookings" },
                ].map(row => (
                  <div key={row.name}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium" style={{ color: "rgba(255,255,255,0.80)" }}>{row.name}</span>
                      <span className="text-xs" style={{ color: "rgba(255,255,255,0.40)" }}>{row.pct}%</span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden" style={{ backgroundColor: "rgba(255,255,255,0.07)" }}>
                      <div className="h-full rounded-full" style={{ width: `${row.pct}%`, backgroundColor: row.color }} />
                    </div>
                    <p className="text-[10px] mt-1" style={{ color: "rgba(255,255,255,0.30)" }}>{row.count}</p>
                  </div>
                ))}
              </div>
              <div className="rounded-xl p-3 flex items-start gap-2" style={{ backgroundColor: "rgba(0,85,90,0.15)", border: "1px solid rgba(0,85,90,0.30)" }}>
                <TrendingUp size={13} style={{ color: "#5eead4" }} className="flex-shrink-0 mt-0.5" />
                <p className="text-[11px] leading-relaxed" style={{ color: "#99f6e4" }}><span className="font-bold">₹1.4L saved this month</span> by closing direct via the unified inbox instead of OTAs.</p>
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
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#f43f5e" }}>Front-desk reality</p>
            <h2 className="text-3xl sm:text-4xl font-bold mb-4" style={{ color: "#0F172A" }}>You shouldn&apos;t need 4 tabs to take a reservation</h2>
            <p className="text-base" style={{ color: "#475569", maxWidth: 520, margin: "0 auto" }}>Boutique hotels lose enquiries between tools, between shifts, and between channels. HAIP collapses all of it into one shift-proof workspace.</p>
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
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#00555a" }}>Built for boutique hotels</p>
            <h2 className="text-3xl sm:text-4xl font-bold" style={{ color: "#0F172A" }}>Six things HAIP automates for your front desk</h2>
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

      {/* ── How calling works ────────────────────────────────────────────── */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto grid lg:grid-cols-2 gap-12 items-center">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}>
            <div className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 mb-6" style={{ backgroundColor: "rgba(0,85,90,0.08)", border: "1px solid rgba(0,85,90,0.15)" }}>
              <Phone size={12} style={{ color: "#00555a" }} />
              <span className="text-xs font-semibold" style={{ color: "#00555a" }}>How calling actually works</span>
            </div>
            <h2 className="text-3xl font-bold mb-4" style={{ color: "#0F172A", lineHeight: 1.2 }}>Your team takes calls on their phone. HAIP makes them 10× smarter.</h2>
            <p className="text-base leading-relaxed mb-6" style={{ color: "#475569" }}>
              We don&apos;t replace your phone system. Your hotel keeps its CallerDesk or Acefone number. Calls forward to the on-duty reservations agent&apos;s personal mobile — exactly like today. The moment the call ends, HAIP processes the recording and posts a wrap-up card within 90 seconds.
            </p>
            <ul className="space-y-3">
              {[
                "Recording consent captured in the IVR greeting",
                "AI transcription with Indian-English accuracy (Whisper + Deepgram)",
                "Auto QA-scored against your rubric — 100% coverage",
                "Click-to-call from any guest record for outbound",
                "No SIP, no headsets, no in-app dialler to learn",
              ].map(item => (
                <li key={item} className="flex items-start gap-3 text-sm" style={{ color: "#475569" }}>
                  <CheckCircle2 size={16} className="flex-shrink-0 mt-0.5" style={{ color: "#00555a" }} /> {item}
                </li>
              ))}
            </ul>
          </motion.div>
          <motion.div variants={scaleUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl p-6" style={{ backgroundColor: "#003d41", boxShadow: "0 20px 60px rgba(0,61,65,0.25)" }}>
            <p className="text-xs font-semibold uppercase tracking-wider mb-5" style={{ color: "rgba(255,255,255,0.40)" }}>Call lifecycle</p>
            <div className="space-y-3">
              {callSteps.map((s, i) => (
                <div key={s.step} className="flex items-start gap-3">
                  <div className="w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-bold flex-shrink-0" style={{ backgroundColor: s.color.bg, color: s.color.text }}>{i + 1}</div>
                  <div className="flex-1 pt-0.5">
                    <p className="text-sm font-semibold text-white">{s.step}</p>
                    <p className="text-xs" style={{ color: "rgba(255,255,255,0.40)" }}>{s.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── Testimonial ──────────────────────────────────────────────────── */}
      <section className="py-16 px-5 sm:px-8" style={{ backgroundColor: "#F8FAFC" }}>
        <div className="max-w-3xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl p-10 relative overflow-hidden" style={{ backgroundColor: "#003d41" }}>
            <div className="absolute right-0 top-0 pointer-events-none" style={{ width: 280, height: 280, background: "radial-gradient(circle, rgba(255,201,75,0.07) 0%, transparent 70%)" }} />
            <div className="flex gap-1 mb-6">
              {[...Array(5)].map((_, i) => <Star key={i} size={16} fill="#ffc94b" style={{ color: "#ffc94b" }} />)}
            </div>
            <p className="text-lg leading-relaxed mb-8" style={{ color: "rgba(255,255,255,0.80)", fontStyle: "italic" }}>
              &ldquo;We used to lose 20-25 enquiries every weekend because the front desk simply could not keep up. HAIP&apos;s unified inbox + AI Concierge captures every single one of them now — and the QA scoring made our reservations team noticeably sharper on objections within 60 days.&rdquo;
            </p>
            <div className="flex items-center gap-4">
              <div className="w-11 h-11 rounded-full flex items-center justify-center font-bold text-sm" style={{ backgroundColor: "rgba(255,201,75,0.20)", color: "#ffc94b" }}>PD</div>
              <div>
                <p className="font-semibold text-white">Priya Deshpande</p>
                <p className="text-sm" style={{ color: "rgba(255,255,255,0.40)" }}>GM, The Postcard Boutique Hotels</p>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── FAQ ──────────────────────────────────────────────────────────── */}
      <section className="py-16 px-5 sm:px-8">
        <div className="max-w-2xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} className="text-center mb-10">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#00555a" }}>FAQ</p>
            <h2 className="text-2xl font-bold" style={{ color: "#0F172A" }}>Boutique hotel questions</h2>
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
              <Hotel size={24} style={{ color: "#ffc94b" }} />
            </motion.div>
            <motion.h2 variants={fadeUp} className="font-black text-white mb-4" style={{ fontSize: "clamp(30px, 5vw, 50px)", lineHeight: 1.1 }}>Turn your front desk into your growth engine</motion.h2>
            <motion.p variants={fadeUp} className="text-lg mb-10" style={{ color: "rgba(255,255,255,0.55)", maxWidth: 480, margin: "0 auto 2.5rem" }}>
              14-day free trial · BYOC telephony · DPDP-compliant. Live in under 20 minutes.
            </motion.p>
            <motion.div variants={fadeUp} className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link href="/register?plan=growth&segment=hotels"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all duration-200"
                style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                Start free trial <ArrowRight size={18} />
              </Link>
              <Link href="/book-demo?segment=hotels"
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

