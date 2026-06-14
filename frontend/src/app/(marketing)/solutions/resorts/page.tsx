"use client";

import Link from "next/link";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowRight, MessageSquare, Phone, Inbox, Sparkles, Trees,
  Users, BarChart2, TrendingUp, Shield, ChevronDown, ChevronRight, CheckCircle2, Wine, Bike, Star,
} from "lucide-react";

const fadeUp = { hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" } } };
const scaleUp = { hidden: { opacity: 0, scale: 0.97 }, visible: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: "easeOut" } } };
const stagger = { visible: { transition: { staggerChildren: 0.08 } } };
const VP = { once: true, margin: "-50px" } as const;

const painPoints = [
  { icon: <MessageSquare size={18} />, title: "Activity, spa and F&B enquiries scatter across teams", desc: "Front desk fields requests for spa bookings, dining, water sports, kids' club. Every team has its own WhatsApp group. Nothing reaches the guest record." },
  { icon: <Phone size={18} />, title: "Reservations and FOH speak past each other", desc: "Reservations sells a package. FOH doesn't know what was promised. Guest arrives expecting things nobody told the property about." },
  { icon: <BarChart2 size={18} />, title: "Ancillary revenue leaks at every touchpoint", desc: "Spa, F&B, transport, photographer — high-margin add-ons get mentioned inconsistently or not at all. Revenue management has no visibility." },
  { icon: <Users size={18} />, title: "Group bookings are operationally chaotic", desc: "Weddings, MICE, family retreats — every department gets messages in their own channel. The guest experience suffers." },
];

const features = [
  { icon: <Inbox size={20} />, title: "Unified inbox across departments", desc: "Reservations, FOH, F&B, Spa, Activities — every WhatsApp / IG / call thread routes to the right team with full guest context, and a copy lands on the central guest record." },
  { icon: <Sparkles size={20} />, title: "Multi-property AI Concierge", desc: "Trained per property on inventory, packages, F&B menus and activity calendars. Drafts replies that match each property's voice, in shadow mode by default." },
  { icon: <Wine size={20} />, title: "Ancillary revenue intelligence", desc: "HAIP surfaces missed F&B / spa / activity upsell opportunities on every call and chat. Weekly digest of which agents/properties consistently leave revenue on the table." },
  { icon: <Trees size={20} />, title: "Per-property scoping", desc: "Resort A's FOH only sees Resort A. Group GM sees the whole portfolio. Role × Property × Department permissions, set once." },
  { icon: <Bike size={20} />, title: "Group booking workspace", desc: "Wedding / MICE / family retreat enquiries get a dedicated thread with parallel sub-threads for F&B, transport, spa, decor — all linked to one master record." },
  { icon: <Shield size={20} />, title: "Compliance that scales with staff count", desc: "Hash-chained audit log, recording consent, per-tenant KMS, role-scoped exports. Built for the headache of audit-ready ops at multi-site scale." },
];

const stats = [
  { value: "+18%", label: "Avg. ancillary revenue lift" },
  { value: "100%", label: "Calls auto-scored" },
  { value: "<5min", label: "Cross-dept handoff time" },
  { value: "11", label: "Roles supported" },
];

const roles = [
  { role: "Owner / GM", desc: "Portfolio · 7 properties", bg: "#003d41", text: "#ffc94b", initials: "OG" },
  { role: "Reservations", desc: "All villas · pipeline", bg: "#0f766e", text: "#ccfbf1", initials: "RL" },
  { role: "Concierge", desc: "Today · queue", bg: "#7c3aed", text: "#ede9fe", initials: "CG" },
  { role: "Marketing", desc: "Campaigns · ROAS", bg: "#b45309", text: "#fef3c7", initials: "MK" },
  { role: "FOH", desc: "Property · today", bg: "#0369a1", text: "#e0f2fe", initials: "FH" },
  { role: "Compliance", desc: "Audit · exports", bg: "#9f1239", text: "#ffe4e6", initials: "CP" },
];

const faqs = [
  { q: "Can each property have its own knowledge base, brand voice and rate card?", a: "Yes. HAIP supports per-property RAG knowledge bases and brand voice guides. The AI Concierge for Resort A will quote Resort A's rates, packages and house rules — never Resort B's." },
  { q: "What about housekeeping and FOH on the ground?", a: "FOH cockpit is mobile-first: today's arrivals/departures, transfers, housekeeping checklist, in-villa staff log, special requests. Works on any phone, no app to install." },
  { q: "How do you handle wedding & MICE enquiries?", a: "Group enquiries open a master thread with sub-threads per department (F&B, decor, accommodation, transport, spa). Every department sees only their tasks, but the master view shows the full guest picture." },
  { q: "Will HAIP work with Hostaway or another channel manager?", a: "Hostaway is the live integration; Guesty and Cloudbeds are on the H2 2026 roadmap. We sync bookings and guest data — your channel manager remains the source of truth for OTAs." },
  { q: "Where is data stored?", a: "AWS Mumbai (ap-south-1) by default. Recordings, transcripts and PII never leave India unless your tenancy is explicitly multi-region (Enterprise tier only)." },
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

export default function ResortsSolutionPage() {
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
                <Trees size={12} style={{ color: "#ffc94b" }} />
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#ffc94b" }}>For resorts</span>
              </motion.div>
              <motion.h1 variants={fadeUp} className="font-black tracking-tight text-white mb-5" style={{ fontSize: "clamp(36px, 5vw, 58px)", lineHeight: 1.08 }}>
                One platform for the<br />
                <span style={{ color: "#ffc94b" }}>whole resort.</span>
              </motion.h1>
              <motion.p variants={fadeUp} className="text-lg leading-relaxed mb-8" style={{ color: "rgba(255,255,255,0.60)", maxWidth: 520 }}>
                Reservations, FOH, F&amp;B, spa, activities — every department on one intelligent workspace. AI Concierge per property, auto-QA on every call, role-scoped access for staff at scale.
              </motion.p>
              <motion.div variants={fadeUp} className="flex flex-col sm:flex-row gap-3 mb-5">
                <Link href="/register?plan=scale&segment=resorts"
                  className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-bold text-sm transition-all duration-200"
                  style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                  Start 14-day free trial <ArrowRight size={16} />
                </Link>
                <Link href="/book-demo?segment=resorts"
                  className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-semibold text-sm text-white transition-all duration-200"
                  style={{ border: "1px solid rgba(255,255,255,0.18)" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.35)"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.18)"; }}>
                  Book a 30-min demo
                </Link>
              </motion.div>
              <motion.p variants={fadeUp} className="text-xs" style={{ color: "rgba(255,255,255,0.30)" }}>Multi-property · Multi-department · Indian-hosted &amp; DPDP-ready</motion.p>
            </motion.div>
          </div>

          {/* Hero mockup: dept routing card */}
          <div className="lg:col-span-5">
            <motion.div variants={scaleUp} initial="hidden" animate="visible"
              className="rounded-2xl p-5" style={{ backgroundColor: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)" }}>
              <div className="flex items-center justify-between mb-4">
                <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "rgba(255,255,255,0.40)" }}>Routing · Today, 14:42</p>
                <span className="text-[10px] px-2 py-1 rounded-md font-semibold" style={{ backgroundColor: "rgba(0,85,90,0.30)", color: "#5eead4" }}>36 in queue</span>
              </div>
              <div className="space-y-2">
                {[
                  { dept: "Reservations", icon: <Inbox size={12} />, bg: "rgba(0,85,90,0.20)", text: "#5eead4", count: 14, last: "Anniversary suite for Dec 20–24" },
                  { dept: "F&B", icon: <Wine size={12} />, bg: "rgba(251,191,36,0.15)", text: "#fbbf24", count: 8, last: "Vegan dinner · 6pm · 4 pax" },
                  { dept: "Spa", icon: <Sparkles size={12} />, bg: "rgba(168,85,247,0.15)", text: "#c084fc", count: 5, last: "Couples massage · pre-arrival" },
                  { dept: "Activities", icon: <Bike size={12} />, bg: "rgba(6,182,212,0.15)", text: "#22d3ee", count: 6, last: "Kayak hire · family of 5" },
                  { dept: "FOH (today)", icon: <Trees size={12} />, bg: "rgba(34,197,94,0.15)", text: "#4ade80", count: 3, last: "Late checkout · Villa 4" },
                ].map(d => (
                  <div key={d.dept} className="flex items-center gap-3 rounded-xl px-3 py-2.5" style={{ backgroundColor: "rgba(255,255,255,0.04)" }}>
                    <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: d.bg }}>
                      <span style={{ color: d.text }}>{d.icon}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-white">{d.dept}</span>
                        <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.40)" }}>{d.count}</span>
                      </div>
                      <p className="text-[11px] truncate" style={{ color: "rgba(255,255,255,0.45)" }}>{d.last}</p>
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-4 rounded-xl p-3 flex items-start gap-2" style={{ backgroundColor: "rgba(255,201,75,0.08)", border: "1px solid rgba(255,201,75,0.20)" }}>
                <Sparkles size={11} style={{ color: "#ffc94b" }} className="flex-shrink-0 mt-0.5" />
                <p className="text-[11px] leading-relaxed" style={{ color: "rgba(255,201,75,0.85)" }}>3 ancillary upsell suggestions ready · Spa for Villa 7 family, photographer for honeymoon couple, helicopter transfer for VIP.</p>
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
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#f43f5e" }}>Resort operations reality</p>
            <h2 className="text-3xl sm:text-4xl font-bold mb-4" style={{ color: "#0F172A" }}>The bigger you get, the more leaks between teams</h2>
            <p className="text-base" style={{ color: "#475569", maxWidth: 520, margin: "0 auto" }}>Resorts grow into 6+ departments and inevitably 6+ siloed WhatsApp groups. HAIP gives every team the same picture of every guest.</p>
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
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#00555a" }}>Built for resorts</p>
            <h2 className="text-3xl sm:text-4xl font-bold" style={{ color: "#0F172A" }}>Six things HAIP does that your current stack can&apos;t</h2>
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

      {/* ── Roles & permissions ──────────────────────────────────────────── */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto grid lg:grid-cols-2 gap-12 items-center">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}>
            <div className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 mb-6" style={{ backgroundColor: "rgba(0,85,90,0.08)", border: "1px solid rgba(0,85,90,0.15)" }}>
              <Users size={12} style={{ color: "#00555a" }} />
              <span className="text-xs font-semibold" style={{ color: "#00555a" }}>Roles &amp; permissions</span>
            </div>
            <h2 className="text-3xl font-bold mb-4" style={{ color: "#0F172A", lineHeight: 1.2 }}>A workspace tuned to each role — eleven by default</h2>
            <p className="text-base leading-relaxed mb-6" style={{ color: "#475569" }}>
              Owners get the strategic dashboard. Reservations gets the pipeline. Concierge gets pre-call prep and post-call wrap-up. FOH gets today&apos;s arrivals on mobile. Compliance gets the audit log. Each role sees exactly what they need — nothing more, nothing less.
            </p>
            <ul className="space-y-2.5">
              {[
                "Owner / GM — Owner Daily + portfolio dashboards",
                "Reservations — Pipeline, quote-to-book, AI Concierge",
                "Concierge — Pre-call prep, click-to-call, after-call wrap-up",
                "Marketing — VoG, lost-reason themes, channel ROAS",
                "FOH — Mobile cockpit: arrivals, transfers, requests",
                "Compliance — Hash-chained audit log, exports, DPDP",
                "QA / Coach — Rubrics, agent trends, coaching nudges",
              ].map(item => (
                <li key={item} className="flex items-start gap-3 text-sm" style={{ color: "#475569" }}>
                  <CheckCircle2 size={16} className="flex-shrink-0 mt-0.5" style={{ color: "#00555a" }} /> {item}
                </li>
              ))}
            </ul>
          </motion.div>
          <motion.div variants={stagger} whileInView="visible" initial="hidden" viewport={VP} className="grid grid-cols-2 gap-3">
            {roles.map(r => (
              <motion.div key={r.role} variants={scaleUp} className="rounded-2xl p-4 transition-all duration-200" style={{ border: "1px solid #E2E8F0", backgroundColor: "#F8FAFC" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(0,85,90,0.25)"; (e.currentTarget as HTMLElement).style.backgroundColor = "#fff"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "#E2E8F0"; (e.currentTarget as HTMLElement).style.backgroundColor = "#F8FAFC"; }}>
                <div className="w-10 h-10 rounded-full flex items-center justify-center mb-3 font-bold text-xs" style={{ backgroundColor: r.bg, color: r.text }}>{r.initials}</div>
                <p className="text-sm font-bold" style={{ color: "#0F172A" }}>{r.role}</p>
                <p className="text-[11px] mt-0.5" style={{ color: "#64748B" }}>{r.desc}</p>
              </motion.div>
            ))}
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
              &ldquo;We operate four resort properties across two states. Before HAIP, ancillary revenue from spa, F&amp;B and excursions was completely invisible at the portfolio level. Now we see it daily — and our spa upsell rate doubled in 11 weeks because every concierge gets a nudge when it&apos;s relevant.&rdquo;
            </p>
            <div className="flex items-center gap-4">
              <div className="w-11 h-11 rounded-full flex items-center justify-center font-bold text-sm" style={{ backgroundColor: "rgba(255,201,75,0.20)", color: "#ffc94b" }}>SP</div>
              <div>
                <p className="font-semibold text-white">Suresh Pillai</p>
                <p className="text-sm" style={{ color: "rgba(255,255,255,0.40)" }}>COO, Backwaters Collection (resort group)</p>
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
            <h2 className="text-2xl font-bold" style={{ color: "#0F172A" }}>Resort operator questions</h2>
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
              <Trees size={24} style={{ color: "#ffc94b" }} />
            </motion.div>
            <motion.h2 variants={fadeUp} className="font-black text-white mb-4" style={{ fontSize: "clamp(30px, 5vw, 50px)", lineHeight: 1.1 }}>Run a resort group like a single resort</motion.h2>
            <motion.p variants={fadeUp} className="text-lg mb-10" style={{ color: "rgba(255,255,255,0.55)", maxWidth: 500, margin: "0 auto 2.5rem" }}>
              One inbox. One AI brain. One source of truth — no matter how many properties, departments and staff you grow into.
            </motion.p>
            <motion.div variants={fadeUp} className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link href="/register?plan=scale&segment=resorts"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all duration-200"
                style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                Start free trial <ArrowRight size={18} />
              </Link>
              <Link href="/book-demo?segment=resorts"
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

