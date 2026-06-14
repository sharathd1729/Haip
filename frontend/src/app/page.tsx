"use client";

import Link from "next/link";
import { motion, useInView, animate } from "framer-motion";
import { useRef, useEffect, useState } from "react";
import { MarketingNav } from "@/components/marketing/MarketingNav";
import { MarketingFooter } from "@/components/marketing/MarketingFooter";
import { GuestJourney } from "@/components/marketing/GuestJourney";
import { AnalyticsTabs } from "@/components/marketing/AnalyticsTabs";
import {
  ArrowRight, CheckCircle2, Sparkles, ChevronRight,
  Users, MessageSquare, Calendar, BarChart2, Zap, LineChart,
  X, ArrowDown,
} from "lucide-react";

// ─── Shared Framer Motion variants ───────────────────────────────────────────
const fadeUp = {
  hidden:  { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};
const fadeIn = {
  hidden:  { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.4, ease: "easeOut" as const } },
};
const scaleUp = {
  hidden:  { opacity: 0, scale: 0.97 },
  visible: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: "easeOut" as const } },
};
const stagger = {
  visible: { transition: { staggerChildren: 0.08 } },
};
const VP = { once: true, margin: "-50px" } as const;

// ─── Counter sub-component (used in Guest 360 stats) ─────────────────────────
function CountUp({ to, prefix = "", suffix = "" }: { to: number; prefix?: string; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    if (!inView) return;
    const ctrl = animate(0, to, {
      duration: 1.2,
      ease: "easeOut" as const,
      onUpdate: v => setDisplay(Math.round(v)),
    });
    return ctrl.stop;
  }, [inView, to]);
  return <span ref={ref}>{prefix}{display}{suffix}</span>;
}

// ─── Guest stats with animated counters ──────────────────────────────────────
function GuestStats() {
  return (
    <div className="grid grid-cols-4 border-b" style={{ borderColor: "#E2E8F0" }}>
      {[
        { label: "Calls",    node: <CountUp to={8} /> },
        { label: "Messages", node: <CountUp to={47} /> },
        { label: "Bookings", node: <CountUp to={3} /> },
        { label: "Revenue",  node: <>₹2.4L</> },
      ].map(s => (
        <div key={s.label} className="text-center py-4 border-r last:border-0" style={{ borderColor: "#E2E8F0" }}>
          <p className="text-2xl font-black tabular-nums" style={{ color: "#00555a" }}>{s.node}</p>
          <p className="text-[10px] mt-1" style={{ color: "#94A3B8" }}>{s.label}</p>
        </div>
      ))}
    </div>
  );
}

// ─── Integrations section (marquee + category filter) ────────────────────────
type Integration = { name: string; color: string; category: string };

function IntegrationCard({ int }: { int: Integration }) {
  return (
    <div
      className="flex items-center gap-3 bg-white rounded-xl border px-5 py-3.5 mx-3 flex-shrink-0 cursor-default transition-all duration-200"
      style={{ borderColor: "#E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.06)" }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLElement).style.boxShadow = "0 6px 20px rgba(0,0,0,0.10)";
        (e.currentTarget as HTMLElement).style.borderColor = "rgba(0,85,90,0.25)";
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLElement).style.boxShadow = "0 1px 3px rgba(0,0,0,0.06)";
        (e.currentTarget as HTMLElement).style.borderColor = "#E2E8F0";
      }}
    >
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-black text-white flex-shrink-0"
        style={{ backgroundColor: int.color }}
      >
        {int.name[0]}
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold whitespace-nowrap" style={{ color: "#0F172A" }}>{int.name}</p>
        <p className="text-[10px] mt-0.5" style={{ color: "#94A3B8" }}>{int.category}</p>
      </div>
    </div>
  );
}

function IntegrationsSection({ integrations }: { integrations: Integration[] }) {
  const [activeCategory, setActiveCategory] = useState("All");
  const categories = ["All", "Messaging", "Telephony", "PMS", "Payments", "Marketing", "Data"];

  const filtered = activeCategory === "All"
    ? integrations
    : integrations.filter(i => i.category === activeCategory);

  // Repeat 4× so marquee is continuous even with few items
  const row1 = [...filtered, ...filtered, ...filtered, ...filtered];
  const row2 = [...filtered.slice().reverse(), ...filtered.slice().reverse(), ...filtered.slice().reverse(), ...filtered.slice().reverse()];

  return (
    <section className="py-24 relative overflow-hidden" style={{ backgroundColor: "#003d41" }}>
      {/* Dot grid */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: "radial-gradient(circle, #00555a30 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      />
      {/* Bottom glow */}
      <div
        className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[600px] h-[280px] pointer-events-none"
        style={{ background: "radial-gradient(ellipse at center bottom, rgba(0,85,90,0.4) 0%, transparent 70%)" }}
      />

      <div className="relative max-w-5xl mx-auto px-5 sm:px-8 text-center mb-10">
        <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}>
          <p className="text-xs font-bold uppercase tracking-widest mb-4" style={{ color: "rgba(255,201,75,0.7)" }}>
            Integrations ecosystem
          </p>
          <h2
            className="font-display font-bold leading-[1.0] tracking-tight mb-4"
            style={{ fontSize: "clamp(30px, 4vw, 48px)", color: "#ffffff" }}
          >
            Works with the tools
            <br />
            <span style={{ color: "#ffc94b" }}>your team already uses.</span>
          </h2>
          <p className="text-sm mb-10 max-w-xl mx-auto" style={{ color: "rgba(255,255,255,0.60)" }}>
            Connect your IVR, PMS, messaging and marketing tools. GenHaip unifies data from
            every system into one guest intelligence platform — no manual data entry.
          </p>

          {/* Category filter tabs */}
          <div className="flex flex-wrap justify-center gap-2 mb-10">
            {categories.map(cat => (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat)}
                className="rounded-full px-4 py-1.5 text-xs font-medium transition-all duration-150"
                style={cat === activeCategory
                  ? { backgroundColor: "#00555a", color: "#ffffff" }
                  : { color: "#94A3B8" }
                }
                onMouseEnter={e => {
                  if (cat !== activeCategory) (e.currentTarget as HTMLElement).style.color = "#ffc94b";
                }}
                onMouseLeave={e => {
                  if (cat !== activeCategory) (e.currentTarget as HTMLElement).style.color = "#94A3B8";
                }}
              >
                {cat}
              </button>
            ))}
          </div>
        </motion.div>
      </div>

      {/* Marquee rows — overflow hidden on section, no px padding here */}
      <div className="space-y-4">
        {/* Row 1: scrolls left */}
        <div className="overflow-hidden">
          <div className="flex marquee-left" style={{ width: "max-content" }}>
            {row1.map((int, i) => <IntegrationCard key={`r1-${i}`} int={int} />)}
          </div>
        </div>

        {/* Row 2: scrolls right */}
        <div className="overflow-hidden">
          <div className="flex marquee-right" style={{ width: "max-content" }}>
            {row2.map((int, i) => <IntegrationCard key={`r2-${i}`} int={int} />)}
          </div>
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Static data — updated to teal palette
// ─────────────────────────────────────────────────────────────────────────────

const workflowSteps = [
  { label: "WhatsApp Inquiry",       sub: "Lead arrives via Meta Cloud API",  color: "#00555a" },
  { label: "Call Received",          sub: "Auto-transcribed · AI scored",     color: "#00666d" },
  { label: "Guest Profile Created",  sub: "Unified history · All channels",   color: "#00555a" },
  { label: "Booking Confirmed",      sub: "Revenue tracked · Inquiry closed", color: "#00666d" },
  { label: "Revenue Tracked",        sub: "Attribution · Lifetime value",     color: "#00555a" },
];

const capabilities = [
  {
    icon: Users,
    title: "Guest Intelligence",
    desc: "Know every guest before answering the phone. Full history of calls, messages, stays and preferences — instantly accessible.",
    color: "#0F766E",
    highlight: "Guest 360°",
    preview: ["Last stay: Sunset Villa · Dec 2024", "Total visits: 3 · LTV: ₹2.4L", "Preferred: Early check-in · Private chef"],
  },
  {
    icon: MessageSquare,
    title: "Communication Hub",
    desc: "Manage WhatsApp, Instagram DMs and calls from one workspace. Full conversation history. Team handoffs. AI suggestions.",
    color: "#14B8A6",
    highlight: "Omnichannel",
    preview: ["WhatsApp · 3 unread from Priya", "Instagram · New inquiry: anniversary", "Call · 4m 32s · AI: Booking intent"],
  },
  {
    icon: Calendar,
    title: "Booking Intelligence",
    desc: "Track every inquiry through the pipeline. Know which conversations become bookings and why leads are lost.",
    color: "#0F766E",
    highlight: "CRM Pipeline",
    preview: ["12 open inquiries · ₹8.4L pipeline", "Conversion: 34% this month", "Avg response: 8 minutes"],
  },
  {
    icon: BarChart2,
    title: "Revenue Intelligence",
    desc: "Measure booking performance by property, channel and agent. Surface missed upsell opportunities automatically.",
    color: "#14B8A6",
    highlight: "AI-powered",
    preview: ["Revenue this month: ₹28.4L", "Top channel: WhatsApp (52%)", "Upsells identified: ₹3.2L"],
  },
  {
    icon: Zap,
    title: "Hospitality Automations",
    desc: "Automate follow-ups, booking confirmations and pre-arrival checklists. AI drafts replies for agent approval.",
    color: "#0F766E",
    highlight: "AI Concierge",
    preview: ["Auto follow-up sent: 18 guests", "AI drafts approved: 94%", "Pre-arrival checklist triggered"],
  },
  {
    icon: LineChart,
    title: "Operational Insights",
    desc: "Monitor agent performance, QA scores and team response times. Every call and conversation is scored automatically.",
    color: "#14B8A6",
    highlight: "QA Scoring",
    preview: ["Avg QA score: 87/100", "Fastest response: 2 minutes", "Team leaderboard updated"],
  },
];

const integrations = [
  { name: "WhatsApp Business", color: "#25D366", category: "Messaging" },
  { name: "Instagram", color: "#E1306C", category: "Messaging" },
  { name: "CallerDesk", color: "#3B82F6", category: "Telephony" },
  { name: "Acefone", color: "#8B5CF6", category: "Telephony" },
  { name: "RentalWise", color: "#F59E0B", category: "PMS" },
  { name: "Hostaway", color: "#EF4444", category: "PMS" },
  { name: "Razorpay", color: "#3B82F6", category: "Payments" },
  { name: "Google Sheets", color: "#34A853", category: "Data" },
  { name: "Meta Ads", color: "#0066FF", category: "Marketing" },
];

const testimonials = [
  {
    quote: "GenHaip replaced 4 separate tools. Our team now manages every guest interaction from one screen — calls, WhatsApp, inquiries, everything.",
    author: "Priya R.",
    role: "Operations Head",
    company: "Ratha Travels",
  },
  {
    quote: "The AI call analysis saves us hours every week. It scores every call automatically so I don't have to listen to recordings to review my team.",
    author: "Vikram S.",
    role: "General Manager",
    company: "Jade Resorts",
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────
export default function HomePage() {
  return (
    <div style={{ backgroundColor: "var(--mkt-bg)", color: "var(--mkt-text)" }}>
      <MarketingNav />

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* HERO — teal dot grid + workflow card                               */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="relative min-h-screen flex items-center overflow-hidden pt-20" style={{ backgroundColor: "var(--mkt-bg)" }}>
        {/* Dot grid */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage: "radial-gradient(circle, #00555a15 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
        />
        {/* Large teal orb — top-left */}
        <div
          className="absolute pointer-events-none rounded-full"
          style={{
            width: 700, height: 700,
            background: "#00555a10",
            filter: "blur(80px)",
            top: -200, left: -200,
          }}
        />
        {/* Mimosa glow orb — right */}
        <div
          className="absolute pointer-events-none rounded-full"
          style={{
            width: 300, height: 300,
            background: "#ffc94b08",
            filter: "blur(60px)",
            top: 100, right: "10%",
          }}
        />
        {/* Fade to bg */}
        <div
          className="absolute bottom-0 left-0 right-0 h-40 pointer-events-none"
          style={{ background: "linear-gradient(transparent, var(--mkt-bg))" }}
        />

        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 py-10 lg:py-14 w-full">
          <div className="grid lg:grid-cols-2 gap-16 lg:gap-20 items-center">

            {/* Left: copy */}
            <motion.div variants={stagger} initial="hidden" animate="visible">
              {/* Badge */}
              <motion.div variants={fadeUp} className="mb-10">
                <div
                  className="inline-flex items-center gap-2.5 border rounded-full px-4 py-1.5"
                  style={{
                    borderColor: "rgba(0,85,90,0.35)",
                    backgroundColor: "rgba(0,85,90,0.07)",
                  }}
                >
                  <div
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: "#00555a", animation: "haipShimmer 2s ease-in-out infinite" }}
                  />
                  <span className="text-xs font-bold uppercase tracking-wider" style={{ color: "#00555a" }}>
                    Hospitality intelligence platform
                  </span>
                </div>
              </motion.div>

              {/* Headline */}
              <motion.h1
                variants={fadeUp}
                className="font-display leading-[1.0] tracking-tight mb-8 font-black"
                style={{ fontSize: "clamp(48px, 6.5vw, 82px)", color: "#0F172A" }}
              >
                The Intelligence
                <br />Layer for
                <br />
                <span
                  style={{
                    background: "linear-gradient(135deg, #00555a, #00888f)",
                    WebkitBackgroundClip: "text",
                    WebkitTextFillColor: "transparent",
                    backgroundClip: "text",
                  }}
                >
                  Hospitality.
                </span>
              </motion.h1>

              {/* Subheadline */}
              <motion.p
                variants={fadeUp}
                className="mb-10 text-lg leading-relaxed"
                style={{ maxWidth: 560, color: "#475569" }}
              >
                Connect calls, WhatsApp conversations, bookings, guest history and
                operational insights in one platform built for hospitality teams.
              </motion.p>

              {/* CTAs */}
              <motion.div variants={fadeUp} className="flex flex-col sm:flex-row gap-4 mb-8">
                <Link
                  href="/book-demo"
                  className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-semibold text-base transition-all duration-200"
                  style={{
                    backgroundColor: "#00555a",
                    color: "#ffffff",
                    boxShadow: "0 8px 24px rgba(0,85,90,0.28)",
                  }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLElement).style.backgroundColor = "#004a4f";
                    (e.currentTarget as HTMLElement).style.boxShadow = "0 12px 32px rgba(0,85,90,0.36)";
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLElement).style.backgroundColor = "#00555a";
                    (e.currentTarget as HTMLElement).style.boxShadow = "0 8px 24px rgba(0,85,90,0.28)";
                  }}
                >
                  Book a Demo <ArrowRight size={16} />
                </Link>
                <Link
                  href="/features"
                  className="inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-semibold text-base transition-all duration-200"
                  style={{ border: "2px solid #E2E8F0", color: "#334155" }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLElement).style.borderColor = "#00555a";
                    (e.currentTarget as HTMLElement).style.color = "#00555a";
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLElement).style.borderColor = "#E2E8F0";
                    (e.currentTarget as HTMLElement).style.color = "#334155";
                  }}
                >
                  Watch Product Tour
                </Link>
              </motion.div>

              {/* Trust line */}
              <motion.div variants={fadeIn} className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "#64748B" }}>
                <span
                  className="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0"
                  style={{ animation: "haipShimmer 2s ease-in-out infinite" }}
                />
                <span>No credit card required</span>
                <span className="text-slate-300">·</span>
                <span>Setup in under 10 minutes</span>
                <span className="text-slate-300">·</span>
                <span>Cancel anytime</span>
              </motion.div>
            </motion.div>

            {/* Right: Workflow card */}
            <motion.div
              className="mt-4 lg:mt-0"
              variants={scaleUp}
              initial="hidden"
              animate="visible"
              transition={{ delay: 0.35 }}
            >
              <div style={{ animation: "haipFloat 7s ease-in-out 1.2s infinite" }}>
                <div
                  className="rounded-2xl border p-6"
                  style={{
                    backgroundColor: "#ffffff",
                    borderColor: "#E2E8F0",
                    boxShadow: "0 32px 80px rgba(0,85,90,0.10), 0 4px 24px rgba(0,0,0,0.06)",
                    outline: "1px solid rgba(0,85,90,0.05)",
                  }}
                >
                  {/* Header */}
                  <div className="flex items-center gap-3 mb-6 pb-4 border-b" style={{ borderColor: "#E2E8F0" }}>
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-black"
                      style={{ backgroundColor: "#00555a", color: "#fff" }}
                    >
                      G
                    </div>
                    <div>
                      <p className="text-sm font-bold" style={{ color: "var(--mkt-text)" }}>GenHaip — Guest Journey</p>
                      <p className="text-xs" style={{ color: "var(--mkt-muted)" }}>Live pipeline view</p>
                    </div>
                    <div className="ml-auto flex items-center gap-1.5">
                      <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" style={{ animation: "haipShimmer 2s infinite" }} />
                      <span className="text-[10px] font-semibold text-emerald-600">Live</span>
                    </div>
                  </div>

                  {/* Workflow steps */}
                  <div className="space-y-0">
                    {workflowSteps.map((step, i) => (
                      <div key={i} className="flex items-start gap-4">
                        <div className="flex flex-col items-center">
                          <div
                            className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 text-xs font-black text-white"
                            style={{
                              backgroundColor: step.color,
                              boxShadow: `0 4px 12px ${step.color}30`,
                              animation: `haipFadeUp 0.5s cubic-bezier(0.16,1,0.3,1) ${i * 0.1 + 0.5}s both`,
                            }}
                          >
                            {i + 1}
                          </div>
                          {i < workflowSteps.length - 1 && (
                            <div className="w-px h-8 mt-1" style={{ backgroundColor: `${step.color}20` }} />
                          )}
                        </div>
                        <div
                          className="flex-1 pb-4"
                          style={{
                            animation: `haipFadeUp 0.5s cubic-bezier(0.16,1,0.3,1) ${i * 0.1 + 0.55}s both`,
                          }}
                        >
                          <p className="text-sm font-semibold mb-0.5" style={{ color: "var(--mkt-text)" }}>
                            {step.label}
                          </p>
                          <p className="text-xs" style={{ color: "var(--mkt-muted)" }}>
                            {step.sub}
                          </p>
                        </div>
                        <div
                          className="mt-2 w-2 h-2 rounded-full flex-shrink-0"
                          style={{ backgroundColor: `${step.color}40` }}
                        />
                      </div>
                    ))}
                  </div>

                  {/* Footer */}
                  <div
                    className="mt-4 pt-4 border-t rounded-xl px-3 py-2.5"
                    style={{
                      borderColor: "#E2E8F0",
                      backgroundColor: "rgba(0,85,90,0.05)",
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <Sparkles size={12} style={{ color: "#00555a" }} />
                      <p className="text-xs font-medium" style={{ color: "#00555a" }}>
                        Every guest interaction, tracked in one timeline
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>

          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* FRAGMENTATION PROBLEM — dark #003d41                              */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-24 px-5 sm:px-8" style={{ backgroundColor: "#003d41" }}>
        <div className="max-w-6xl mx-auto">

          {/* Headline */}
          <motion.div
            className="text-center mb-16"
            variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
          >
            <p className="text-xs font-bold uppercase tracking-widest mb-4" style={{ color: "#ffc94b" }}>
              The problem
            </p>
            <h2
              className="font-display font-bold leading-[1.05] tracking-tight mb-5"
              style={{ fontSize: "clamp(34px, 4.5vw, 54px)", color: "#ffffff" }}
            >
              Hospitality operations are
              <br />
              <span style={{ color: "#ffc94b" }}>fragmented.</span>
            </h2>
          </motion.div>

          <div className="grid lg:grid-cols-[1fr_80px_1fr] gap-6 items-start">

            {/* Left: Without GenHaip */}
            <motion.div
              className="rounded-2xl p-6"
              style={{ backgroundColor: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.10)" }}
              variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.07 } } }}
              whileInView="visible" initial="hidden" viewport={VP}
            >
              <p className="text-sm font-semibold mb-4" style={{ color: "#CBD5E1" }}>Without GenHaip</p>
              <div className="space-y-3">
                {[
                  { tool: "WhatsApp",     note: "Guest inquiries arrive on personal phones" },
                  { tool: "Phone Calls",  note: "Recordings buried in IVR dashboard" },
                  { tool: "PMS Software", note: "Booking details siloed per property" },
                  { tool: "Spreadsheets", note: "Guest history manually maintained" },
                  { tool: "Email",        note: "Follow-ups forgotten or delayed" },
                ].map(item => (
                  <motion.div
                    key={item.tool}
                    variants={{ hidden: { opacity: 0, x: -20 }, visible: { opacity: 1, x: 0, transition: { duration: 0.4, ease: "easeOut" as const } } }}
                    className="flex items-start gap-3 p-3 rounded-xl"
                    style={{ backgroundColor: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.15)" }}
                  >
                    <div
                      className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ backgroundColor: "rgba(239,68,68,0.15)" }}
                    >
                      <X size={12} style={{ color: "#f87171" }} />
                    </div>
                    <div>
                      <p className="text-sm font-semibold" style={{ color: "#CBD5E1" }}>{item.tool}</p>
                      <p className="text-xs mt-0.5" style={{ color: "#94A3B8" }}>{item.note}</p>
                    </div>
                  </motion.div>
                ))}
              </div>
              <div
                className="mt-4 p-3 rounded-xl text-center"
                style={{ backgroundColor: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.15)" }}
              >
                <p className="text-sm font-semibold" style={{ color: "#f87171" }}>
                  Teams never see the complete guest journey
                </p>
              </div>
            </motion.div>

            {/* Center vs divider */}
            <div className="flex flex-col items-center justify-center gap-3 py-8">
              <div className="flex-1 w-px min-h-[40px]"
                style={{ background: "linear-gradient(to bottom, transparent, rgba(255,255,255,0.2), transparent)" }} />
              <span
                className="rounded-full px-3 py-1 text-xs font-bold"
                style={{ backgroundColor: "rgba(255,255,255,0.08)", color: "#94A3B8" }}
              >
                vs
              </span>
              <div className="flex-1 w-px min-h-[40px]"
                style={{ background: "linear-gradient(to bottom, transparent, rgba(255,255,255,0.2), transparent)" }} />
            </div>

            {/* Right: With GenHaip */}
            <motion.div
              className="rounded-2xl p-6"
              style={{ backgroundColor: "rgba(255,201,75,0.05)", border: "1px solid rgba(255,201,75,0.20)" }}
              variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.07 } } }}
              whileInView="visible" initial="hidden" viewport={VP}
            >
              <p className="text-sm font-semibold mb-4" style={{ color: "#ffc94b" }}>With GenHaip</p>
              <div className="space-y-3">
                {[
                  { event: "WhatsApp inquiry arrives",              time: "09:14" },
                  { event: "Call received · Auto-transcribed",      time: "09:31" },
                  { event: "Guest profile matched · History loaded",time: "09:31" },
                  { event: "AI suggests personalised reply",        time: "09:32" },
                  { event: "Booking confirmed · Revenue tracked",   time: "09:45" },
                ].map((item, i) => (
                  <motion.div
                    key={i}
                    variants={{ hidden: { opacity: 0, x: 20 }, visible: { opacity: 1, x: 0, transition: { duration: 0.4, ease: "easeOut" as const } } }}
                    className="flex items-center gap-3"
                  >
                    <span className="text-[10px] font-mono flex-shrink-0 w-10 font-semibold" style={{ color: "#ffc94b" }}>
                      {item.time}
                    </span>
                    <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: "#ffc94b" }} />
                    <p className="text-sm" style={{ color: "#e2e8f0" }}>{item.event}</p>
                  </motion.div>
                ))}
              </div>
              <div
                className="mt-4 p-3 rounded-xl text-center"
                style={{ backgroundColor: "rgba(255,201,75,0.08)", border: "1px solid rgba(255,201,75,0.22)" }}
              >
                <p className="text-sm font-semibold" style={{ color: "#ffc94b" }}>
                  GenHaip connects every interaction into one timeline
                </p>
              </div>
            </motion.div>

          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* PLATFORM CAPABILITIES — alternating rows                          */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="px-5 sm:px-8 pb-8" id="features" style={{ backgroundColor: "var(--mkt-bg)" }}>
        <div className="max-w-7xl mx-auto">

          {/* Section header */}
          <motion.div
            className="pt-24 pb-16"
            variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
          >
            <p className="text-xs font-bold uppercase tracking-widest mb-4" style={{ color: "#00555a" }}>
              Platform capabilities
            </p>
            <h2
              className="font-display font-bold leading-[1.0] tracking-tight"
              style={{ fontSize: "clamp(36px, 5vw, 58px)", color: "#0F172A" }}
            >
              Built for how hospitality
              <br />
              <span style={{ color: "#475569", fontWeight: 400 }}>teams actually work.</span>
            </h2>
          </motion.div>

          {/* Alternating rows */}
          {[
            {
              idx: 0,
              pill: "Guest Intelligence",
              title: capabilities[0].title,
              desc: capabilities[0].desc,
              bullets: [
                "Complete call + message history for every guest",
                "Preferences auto-captured from every interaction",
                "Lifetime value and booking timeline across properties",
              ],
              href: "/features#guests",
              preview: capabilities[0].preview,
              Icon: capabilities[0].icon,
            },
            {
              idx: 1,
              pill: "Omnichannel",
              title: capabilities[1].title,
              desc: capabilities[1].desc,
              bullets: [
                "WhatsApp, Instagram DMs and calls in one workspace",
                "AI-suggested replies based on guest history",
                "Real-time team collaboration and handoffs",
              ],
              href: "/features#inbox",
              preview: capabilities[1].preview,
              Icon: capabilities[1].icon,
            },
            {
              idx: 2,
              pill: "CRM Pipeline",
              title: capabilities[2].title,
              desc: capabilities[2].desc,
              bullets: [
                "Track every inquiry through the full pipeline",
                "Know conversion rates and lost reasons automatically",
                "Real-time ₹ pipeline value across all properties",
              ],
              href: "/features#crm",
              preview: capabilities[2].preview,
              Icon: capabilities[2].icon,
            },
            {
              idx: 3,
              pill: "AI-powered",
              title: capabilities[3].title,
              desc: capabilities[3].desc,
              bullets: [
                "Measure booking performance by property and channel",
                "Surface missed upsell opportunities automatically",
                "Attribution across WhatsApp, calls and OTA",
              ],
              href: "/features#insights",
              preview: capabilities[3].preview,
              Icon: capabilities[3].icon,
            },
            {
              idx: 4,
              pill: "AI Concierge",
              title: capabilities[4].title,
              desc: capabilities[4].desc,
              bullets: [
                "AI drafts WhatsApp replies for agent approval",
                "Automated follow-up sequences for open inquiries",
                "Pre-arrival checklists triggered automatically",
              ],
              href: "/features#whatsapp",
              preview: capabilities[4].preview,
              Icon: capabilities[4].icon,
            },
            {
              idx: 5,
              pill: "QA Scoring",
              title: capabilities[5].title,
              desc: capabilities[5].desc,
              bullets: [
                "Agent QA scoring — no manual call listening required",
                "Response time analytics per team and channel",
                "Team leaderboard and performance trends",
              ],
              href: "/features#insights",
              preview: capabilities[5].preview,
              Icon: capabilities[5].icon,
            },
          ].map(({ idx, pill, title, desc, bullets, href, preview, Icon }) => {
            const isEven = idx % 2 === 0; // even → text left; odd → text right
            const textFrom = isEven ? -30 : 30;
            const mockFrom = isEven ? 30 : -30;

            const textBlock = (
              <motion.div
                variants={{ hidden: { opacity: 0, x: textFrom }, visible: { opacity: 1, x: 0, transition: { duration: 0.5, ease: "easeOut" as const } } }}
                whileInView="visible" initial="hidden" viewport={{ once: true, margin: "-100px" }}
              >
                <span
                  className="inline-block rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider mb-4"
                  style={{ backgroundColor: "rgba(0,85,90,0.10)", color: "#00555a" }}
                >
                  {pill}
                </span>
                <h3
                  className="font-bold tracking-tight mb-4"
                  style={{ fontSize: "clamp(22px, 2.5vw, 30px)", color: "#0F172A" }}
                >
                  {title}
                </h3>
                <p className="text-lg leading-relaxed mb-6 max-w-md" style={{ color: "#475569" }}>
                  {desc}
                </p>
                <ul className="space-y-3 mb-6">
                  {bullets.map((b, i) => (
                    <li key={i} className="flex items-start gap-3">
                      <CheckCircle2
                        size={18}
                        className="flex-shrink-0 mt-0.5"
                        style={{ color: "#00555a" }}
                      />
                      <span style={{ color: "#334155" }}>{b}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href={href}
                  className="inline-flex items-center gap-1.5 text-sm font-semibold transition-colors duration-150 group"
                  style={{ color: "#00555a" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#004a4f"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
                >
                  Explore {title}
                  <ArrowRight size={15} className="group-hover:translate-x-0.5 transition-transform duration-150" />
                </Link>
              </motion.div>
            );

            const mockBlock = (
              <motion.div
                variants={{ hidden: { opacity: 0, x: mockFrom }, visible: { opacity: 1, x: 0, transition: { duration: 0.5, ease: "easeOut" as const } } }}
                whileInView="visible" initial="hidden" viewport={{ once: true, margin: "-100px" }}
                className="rounded-2xl p-6 border"
                style={{
                  backgroundColor: "#F8FAFC",
                  borderColor: "#E2E8F0",
                  boxShadow: "0 20px 48px rgba(0,0,0,0.08)",
                  outline: "1px solid rgba(0,85,90,0.05)",
                }}
              >
                {/* Mock header */}
                <div className="flex items-center gap-2.5 mb-5 pb-4 border-b border-slate-100">
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ backgroundColor: "rgba(0,85,90,0.10)" }}
                  >
                    <Icon size={16} style={{ color: "#00555a" }} />
                  </div>
                  <span className="text-sm font-semibold" style={{ color: "#0F172A" }}>{title}</span>
                  <div className="ml-auto flex items-center gap-1.5">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" style={{ animation: "haipShimmer 2s infinite" }} />
                    <span className="text-[10px] font-semibold text-emerald-600">Live</span>
                  </div>
                </div>
                {/* Preview lines */}
                <div className="space-y-2.5">
                  {preview.map((line, i) => (
                    <div key={i} className="flex items-center gap-3 p-2.5 rounded-xl" style={{ backgroundColor: "#ffffff", border: "1px solid #F1F5F9" }}>
                      <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: "#00555a" }} />
                      <p className="text-sm" style={{ color: "#334155" }}>{line}</p>
                    </div>
                  ))}
                </div>
              </motion.div>
            );

            return (
              <div
                key={title}
                className={`grid grid-cols-1 lg:grid-cols-2 gap-16 items-center py-20 ${idx < 5 ? "border-b border-slate-100" : ""}`}
              >
                {isEven ? <>{textBlock}{mockBlock}</> : <>{mockBlock}{textBlock}</>}
              </div>
            );
          })}
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* CONNECTED GUEST JOURNEY — #F8FAFC                                 */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-panel)" }} id="guest-journey">
        <div className="max-w-5xl mx-auto">
          <motion.div
            className="mb-14 text-center"
            variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
          >
            <p className="text-xs font-bold uppercase tracking-widest mb-4" style={{ color: "#00555a" }}>
              Connected guest journey
            </p>
            <h2
              className="font-display font-bold leading-[1.0] tracking-tight mb-4"
              style={{ fontSize: "clamp(34px, 4.5vw, 54px)", color: "#0F172A" }}
            >
              Follow every guest from
              <br />
              <span style={{ color: "#00555a", background: "linear-gradient(transparent 68%, rgba(255,201,75,0.45) 68%)" }}>first message to fifth stay.</span>
            </h2>
            <p className="text-base max-w-xl mx-auto" style={{ color: "#64748B" }}>
              Click any stage to see the screen and data GenHaip captures automatically.
            </p>
          </motion.div>
          <GuestJourney />
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* GUEST 360 SHOWCASE — white                                         */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-bg)" }}>
        <div className="max-w-7xl mx-auto">
          <div className="grid lg:grid-cols-2 gap-16 items-center">

            {/* Left: feature list — slide from left */}
            <motion.div
              variants={{ hidden: { opacity: 0, x: -30 }, visible: { opacity: 1, x: 0, transition: { duration: 0.5, ease: "easeOut" as const } } }}
              whileInView="visible" initial="hidden" viewport={VP}
            >
              <p className="text-xs font-bold uppercase tracking-widest mb-4" style={{ color: "#00555a" }}>
                Guest Intelligence
              </p>
              <h2
                className="font-display font-bold leading-[1.0] tracking-tight mb-6"
                style={{ fontSize: "clamp(34px, 4.5vw, 54px)", color: "#0F172A" }}
              >
                Everything about
                <br />
                <span style={{ color: "#00555a", background: "linear-gradient(transparent 68%, rgba(255,201,75,0.45) 68%)" }}>every guest.</span>
              </h2>
              <p className="text-lg leading-relaxed mb-8 max-w-md" style={{ color: "#475569" }}>
                One profile that unifies calls, WhatsApp conversations, bookings,
                stay preferences and lifetime value — automatically built from every
                interaction across your properties.
              </p>
              <ul className="space-y-3 mb-8">
                {[
                  "Complete communication history — every call and message",
                  "Booking and stay timeline across all properties",
                  "Preferences auto-captured: room type, check-in time, dietary",
                  "Lifetime revenue, visit count and acquisition channel",
                  "DPDP-compliant consent tracking built in",
                ].map((item, i) => (
                  <li key={i} className="flex items-start gap-3">
                    <CheckCircle2 size={18} className="flex-shrink-0 mt-0.5" style={{ color: "#00555a" }} />
                    <span style={{ color: "#334155" }}>{item}</span>
                  </li>
                ))}
              </ul>
              <Link
                href="/features#guests"
                className="inline-flex items-center gap-1.5 text-sm font-semibold transition-colors duration-150 group"
                style={{ color: "#00555a" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#004a4f"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
              >
                Explore Guest Intelligence
                <ArrowRight size={15} className="group-hover:translate-x-0.5 transition-transform duration-150" />
              </Link>
            </motion.div>

            {/* Right: Profile card — scaleUp */}
            <motion.div
              variants={scaleUp} whileInView="visible" initial="hidden" viewport={VP}
              className="rounded-2xl border overflow-hidden"
              style={{
                backgroundColor: "#ffffff",
                borderColor: "#E2E8F0",
                boxShadow: "0 20px 60px rgba(0,0,0,0.08)",
              }}
            >
              {/* Profile header */}
              <div className="px-6 py-5 border-b" style={{ borderColor: "#E2E8F0", backgroundColor: "#F8FAFC" }}>
                <div className="flex items-center gap-4">
                  <div
                    className="w-12 h-12 rounded-full flex items-center justify-center text-lg font-black text-white flex-shrink-0"
                    style={{ backgroundColor: "#00555a" }}
                  >
                    P
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold" style={{ color: "#0F172A" }}>Priya Sharma</p>
                    <p className="text-xs mt-0.5" style={{ color: "#64748B" }}>
                      +91 98765 ···10 · priya@example.com
                    </p>
                  </div>
                  {/* VIP badge — mimosa */}
                  <span
                    className="text-[10px] font-bold px-2.5 py-0.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: "#ffc94b", color: "#00555a" }}
                  >
                    VIP Guest
                  </span>
                </div>
              </div>

              {/* Stats row — counters animate in */}
              <GuestStats />

              {/* Preferences */}
              <div className="px-6 py-4 border-b" style={{ borderColor: "#E2E8F0" }}>
                <p className="text-[10px] font-medium uppercase tracking-widest mb-3" style={{ color: "#94A3B8" }}>
                  Preferences · Auto-captured
                </p>
                <div className="flex flex-wrap gap-2">
                  {["Early check-in", "Private chef", "Pool-facing room", "Anniversary setup", "Veg meals"].map(pref => (
                    <span
                      key={pref}
                      className="text-xs font-medium px-3 py-1 rounded-full"
                      style={{ backgroundColor: "rgba(0,85,90,0.08)", color: "#00555a" }}
                    >
                      {pref}
                    </span>
                  ))}
                </div>
              </div>

              {/* Timeline — stagger */}
              <div className="px-6 py-4">
                <p className="text-[10px] font-medium uppercase tracking-widest mb-4" style={{ color: "#94A3B8" }}>
                  Recent timeline
                </p>
                <motion.div
                  className="space-y-1"
                  variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.08 } } }}
                  whileInView="visible" initial="hidden" viewport={VP}
                >
                  {[
                    { icon: "📞", event: "Inbound call · 8m 12s · AI Score: 91", time: "Today 11:24 AM" },
                    { icon: "💬", event: "WhatsApp · Booking inquiry · Sunset Villa",  time: "Today 09:14 AM" },
                    { icon: "✅", event: "Booking confirmed · Dec 20–26 · ₹84,000",    time: "Yesterday" },
                    { icon: "⭐", event: "5-star review submitted on Google",           time: "Jan 2025" },
                  ].map((item, i) => (
                    <motion.div
                      key={i}
                      variants={{ hidden: { opacity: 0, y: 6 }, visible: { opacity: 1, y: 0, transition: { duration: 0.35 } } }}
                      className="flex items-start gap-3 px-2 py-1.5 rounded-lg transition-colors duration-150"
                      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#F8FAFC"; }}
                      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                    >
                      <span className="text-sm flex-shrink-0 mt-0.5">{item.icon}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium truncate" style={{ color: "#0F172A" }}>{item.event}</p>
                        <p className="text-[10px] mt-0.5" style={{ color: "#94A3B8" }}>{item.time}</p>
                      </div>
                    </motion.div>
                  ))}
                </motion.div>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* COMMUNICATION HUB — #F8FAFC                                       */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center">

          {/* Text — slide from right (mockup is left, text is right) */}
          <motion.div
            variants={{ hidden: { opacity: 0, x: 30 }, visible: { opacity: 1, x: 0, transition: { duration: 0.5, ease: "easeOut" as const } } }}
            whileInView="visible" initial="hidden" viewport={VP}
          >
            <span
              className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold mb-6"
              style={{ backgroundColor: "rgba(0,85,90,0.08)", color: "#00555a" }}
            >
              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "#00555a" }} />
              Communication Hub
            </span>
            <h2
              className="font-display font-bold leading-[1.05] tracking-tight mb-5"
              style={{ fontSize: "clamp(30px, 4vw, 50px)", color: "#0F172A" }}
            >
              One inbox for every
              <br />
              <span style={{ color: "#00555a", background: "linear-gradient(transparent 68%, rgba(255,201,75,0.45) 68%)" }}>guest touchpoint.</span>
            </h2>
            <p className="text-lg leading-relaxed mb-8 max-w-md" style={{ color: "#475569" }}>
              Your team switches between 4 apps to manage guest communications.
              GenHaip combines WhatsApp, Instagram DMs and phone calls in one clean
              workspace — with full conversation history for every guest.
            </p>
            <ul className="space-y-3 mb-8">
              {[
                "WhatsApp Business via official Meta Cloud API",
                "Instagram DMs and mentions",
                "Phone calls with AI transcription",
                "AI-suggested replies based on guest history",
                "Real-time team collaboration and handoffs",
              ].map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <CheckCircle2 size={18} className="flex-shrink-0 mt-0.5" style={{ color: "#00555a" }} />
                  <span style={{ color: "#334155" }}>{item}</span>
                </li>
              ))}
            </ul>
            <Link
              href="/features#inbox"
              className="inline-flex items-center gap-1.5 text-sm font-semibold transition-colors duration-150 group"
              style={{ color: "#00555a" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#004a4f"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
            >
              Explore Communication Hub
              <ArrowRight size={15} className="group-hover:translate-x-0.5 transition-transform duration-150" />
            </Link>
          </motion.div>

          {/* Inbox mockup — slide from left */}
          <motion.div
            variants={{ hidden: { opacity: 0, x: -30 }, visible: { opacity: 1, x: 0, transition: { duration: 0.5, ease: "easeOut" as const } } }}
            whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl border overflow-hidden"
            style={{ backgroundColor: "#ffffff", borderColor: "#E2E8F0", boxShadow: "0 20px 48px rgba(0,0,0,0.08)" }}
          >
            {/* Panel header */}
            <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: "#E2E8F0", backgroundColor: "#F8FAFC" }}>
              <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#94A3B8" }}>Inbox</span>
              {/* Unread badge — mimosa */}
              <span
                className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                style={{ backgroundColor: "#ffc94b", color: "#00555a" }}
              >
                12 new
              </span>
            </div>

            {/* Conversation rows */}
            {[
              { channel: "WA", name: "Priya Sharma",    msg: "Booking inquiry — Sunset Villa Dec 20–26",      time: "now", tag: "Inquiry", channelColor: "#25D366",                                    active: true },
              { channel: "IG", name: "Rohit & Kavya",   msg: "Anniversary package — do you have availability?", time: "3m",  tag: "Inquiry", channelColor: "linear-gradient(135deg,#7C3AED,#EC4899)", active: false },
              { channel: "☎", name: "+91 98765 43210",  msg: "Call · 4m 32s · AI: Booking query detected",   time: "8m",  tag: "Call",    channelColor: "#00555a",                                    active: false },
              { channel: "WA", name: "Suresh Kumar",    msg: "Can we extend by 2 nights? We love it here",    time: "15m", tag: "Guest",   channelColor: "#25D366",                                    active: false },
            ].map((item, i) => (
              <div
                key={i}
                className="flex items-center gap-3 px-4 py-3.5 transition-colors duration-150"
                style={{
                  borderBottom: i < 3 ? "1px solid #F1F5F9" : "none",
                  backgroundColor: item.active ? "rgba(0,85,90,0.05)" : "transparent",
                  borderLeft: item.active ? "2px solid #00555a" : "2px solid transparent",
                }}
              >
                {/* Channel avatar */}
                <div
                  className="w-9 h-9 rounded-full flex items-center justify-center text-[10px] font-bold text-white flex-shrink-0"
                  style={{ background: item.channelColor }}
                >
                  {item.channel}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-semibold truncate" style={{ color: "#0F172A" }}>{item.name}</span>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded-full font-medium flex-shrink-0"
                      style={item.tag === "Inquiry"
                        ? { backgroundColor: "rgba(0,85,90,0.10)", color: "#00555a" }
                        : { backgroundColor: "#F1F5F9", color: "#64748B" }
                      }
                    >
                      {item.tag}
                    </span>
                  </div>
                  <p className="text-xs truncate" style={{ color: "#64748B" }}>{item.msg}</p>
                </div>
                <span className="text-[10px] flex-shrink-0" style={{ color: "#94A3B8" }}>{item.time}</span>
              </div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* AI CALL INTELLIGENCE — white                                       */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-bg)" }}>
        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center">

          {/* Call analysis visual — slide from left */}
          <motion.div
            variants={{ hidden: { opacity: 0, x: -30 }, visible: { opacity: 1, x: 0, transition: { duration: 0.5, ease: "easeOut" as const } } }}
            whileInView="visible" initial="hidden" viewport={VP}
            className="order-2 lg:order-1 rounded-2xl border overflow-hidden"
            style={{ backgroundColor: "#ffffff", borderColor: "#E2E8F0", boxShadow: "0 20px 48px rgba(0,0,0,0.08)" }}
          >
            {/* Panel header */}
            <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: "#E2E8F0", backgroundColor: "#F8FAFC" }}>
              <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#94A3B8" }}>
                Call Analysis — Priya Sharma
              </span>
              <span className="text-xs" style={{ color: "#94A3B8" }}>8m 12s</span>
            </div>

            <div className="p-5">
              {/* QA score badges */}
              <div className="grid grid-cols-3 gap-3 mb-5">
                {[
                  { label: "QA Score",  value: "91",       style: { bg: "rgba(0,85,90,0.08)", color: "#00555a" } },
                  { label: "Sentiment", value: "Positive", style: { bg: "rgba(0,85,90,0.08)", color: "#00555a" } },
                  { label: "Outcome",   value: "Booked",   style: { bg: "#F0FDF4",            color: "#166534" } },
                ].map(card => (
                  <div key={card.label} className="rounded-xl p-3 text-center" style={{ backgroundColor: card.style.bg }}>
                    <div className="text-sm font-black mb-0.5" style={{ color: card.style.color }}>{card.value}</div>
                    <div className="text-[10px]" style={{ color: "#94A3B8" }}>{card.label}</div>
                  </div>
                ))}
              </div>

              {/* Transcript snippet */}
              <div className="rounded-xl p-3 mb-3 space-y-2.5" style={{ backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0" }}>
                <div className="flex gap-2">
                  <span className="text-[10px] font-bold flex-shrink-0" style={{ color: "#00555a" }}>AGENT</span>
                  <p className="text-xs leading-relaxed" style={{ color: "#475569" }}>
                    Good morning! Thank you for calling. How may I assist you today?
                  </p>
                </div>
                <div className="flex gap-2">
                  <span className="text-[10px] font-bold flex-shrink-0" style={{ color: "#94A3B8" }}>GUEST</span>
                  <p className="text-xs leading-relaxed" style={{ color: "#475569" }}>
                    I&apos;d like to book the pool villa for New Year&apos;s week. What&apos;s the availability?
                  </p>
                </div>
              </div>

              {/* Insights */}
              <div className="space-y-2">
                {/* Missed upsell — mimosa alert */}
                <div
                  className="flex items-start gap-2 rounded-xl px-3 py-2.5"
                  style={{ backgroundColor: "rgba(255,201,75,0.12)", border: "1px solid rgba(255,201,75,0.35)" }}
                >
                  <Sparkles size={12} className="flex-shrink-0 mt-0.5" style={{ color: "#e6b000" }} />
                  <span className="text-xs leading-relaxed" style={{ color: "#334155" }}>
                    Missed upsell: Private chef not offered (₹8,000 opportunity)
                  </span>
                </div>
                {/* Positive note — teal */}
                <div
                  className="flex items-start gap-2 rounded-xl px-3 py-2.5"
                  style={{ backgroundColor: "rgba(0,85,90,0.06)", border: "1px solid rgba(0,85,90,0.15)" }}
                >
                  <CheckCircle2 size={12} className="flex-shrink-0 mt-0.5" style={{ color: "#00555a" }} />
                  <span className="text-xs leading-relaxed" style={{ color: "#334155" }}>
                    Agent handled pricing objection well — closing rate maintained
                  </span>
                </div>
              </div>
            </div>
          </motion.div>

          {/* Text — slide from right */}
          <motion.div
            variants={{ hidden: { opacity: 0, x: 30 }, visible: { opacity: 1, x: 0, transition: { duration: 0.5, ease: "easeOut" as const } } }}
            whileInView="visible" initial="hidden" viewport={VP}
            className="order-1 lg:order-2"
          >
            <span
              className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold mb-6"
              style={{ backgroundColor: "rgba(0,85,90,0.08)", color: "#00555a" }}
            >
              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "#00555a" }} />
              AI Call Intelligence
            </span>
            <h2
              className="font-display font-bold leading-[1.05] tracking-tight mb-5"
              style={{ fontSize: "clamp(30px, 4vw, 50px)", color: "#0F172A" }}
            >
              Every call,
              <br />
              <span style={{ color: "#00555a", background: "linear-gradient(transparent 68%, rgba(255,201,75,0.45) 68%)" }}>automatically analyzed.</span>
            </h2>
            <p className="text-lg leading-relaxed mb-8 max-w-md" style={{ color: "#475569" }}>
              Stop manually reviewing call recordings. GenHaip transcribes, scores and
              extracts insights from every call — surfacing missed revenue, agent coaching
              moments and guest intent signals automatically.
            </p>
            <ul className="space-y-3 mb-8">
              {[
                "Auto-transcription optimised for Indian accents",
                "Agent QA scoring — no manual listening required",
                "Missed revenue opportunity detection",
                "Sentiment analysis per call",
                "Works with CallerDesk, Acefone and all major IVR providers",
              ].map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <CheckCircle2 size={18} className="flex-shrink-0 mt-0.5" style={{ color: "#00555a" }} />
                  <span style={{ color: "#334155" }}>{item}</span>
                </li>
              ))}
            </ul>
            <Link
              href="/features#calls"
              className="inline-flex items-center gap-1.5 text-sm font-semibold transition-colors duration-150 group"
              style={{ color: "#00555a" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#004a4f"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
            >
              Explore AI Call Intelligence
              <ArrowRight size={15} className="group-hover:translate-x-0.5 transition-transform duration-150" />
            </Link>
          </motion.div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* INTEGRATIONS — dark brand #003d41 + infinite marquee              */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <IntegrationsSection integrations={integrations} />

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* ANALYTICS — white                                                  */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-bg)" }}>
        <div className="max-w-5xl mx-auto">
          <motion.div
            className="mb-14"
            variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
          >
            <p className="text-xs font-bold uppercase tracking-widest mb-4" style={{ color: "#00555a" }}>
              Operational insights
            </p>
            <h2
              className="font-display font-bold leading-[1.0] tracking-tight mb-4"
              style={{ fontSize: "clamp(34px, 4.5vw, 54px)", color: "#0F172A" }}
            >
              Answers to the questions
              <br />
              <span style={{ color: "#00555a", background: "linear-gradient(transparent 68%, rgba(255,201,75,0.45) 68%)" }}>that drive revenue.</span>
            </h2>
            <p className="text-base max-w-xl" style={{ color: "#475569" }}>
              Select any area to see the metrics and insights GenHaip surfaces automatically
              from your calls, conversations and bookings.
            </p>
          </motion.div>
          <AnalyticsTabs />
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* WHY GENHAIP — comparison table                                    */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-5xl mx-auto">
          <motion.div
            className="text-center mb-14"
            variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
          >
            <p className="text-xs font-bold uppercase tracking-widest mb-4" style={{ color: "#00555a" }}>
              Why GenHaip?
            </p>
            <h2
              className="font-display font-bold leading-[1.0] tracking-tight mb-4"
              style={{ fontSize: "clamp(34px, 4.5vw, 54px)", color: "#0F172A" }}
            >
              Every tool does one thing.
              <br />
              <span style={{ color: "#00555a", background: "linear-gradient(transparent 68%, rgba(255,201,75,0.45) 68%)" }}>GenHaip connects them all.</span>
            </h2>
            <p className="text-base max-w-2xl mx-auto" style={{ color: "#475569" }}>
              Messaging tools manage conversations. PMS software manages bookings.
              Call software stores recordings. CRMs manage contacts.
              None of them talk to each other — so your team never has the full picture.
            </p>
          </motion.div>

          {/* Comparison table */}
          <motion.div
            variants={scaleUp} whileInView="visible" initial="hidden" viewport={VP}
            className="overflow-x-auto"
          >
            <div
              className="rounded-2xl overflow-hidden"
              style={{
                backgroundColor: "#ffffff",
                border: "1px solid #E2E8F0",
                boxShadow: "0 20px 48px rgba(0,0,0,0.08)",
              }}
            >
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr>
                    {/* Capability column header */}
                    <th
                      className="text-left py-4 px-6 text-xs font-semibold uppercase tracking-wider"
                      style={{ backgroundColor: "#0F172A", color: "#94A3B8", width: "30%" }}
                    >
                      Capability
                    </th>
                    {["Messaging App", "IVR / Call Tool", "PMS Software", "CRM Tool", "GenHaip"].map(col => (
                      <th
                        key={col}
                        className="py-4 px-4 text-center text-xs font-semibold relative"
                        style={{
                          backgroundColor: col === "GenHaip" ? "#00555a" : "#0F172A",
                          color: col === "GenHaip" ? "#ffffff" : "#64748B",
                        }}
                      >
                        {col === "GenHaip" && (
                          <span
                            className="absolute -top-3 left-1/2 -translate-x-1/2 text-[10px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap"
                            style={{ backgroundColor: "#ffc94b", color: "#00555a" }}
                          >
                            ✦ Complete
                          </span>
                        )}
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["Guest communication",          "✓", "—", "—",       "partial", "✓"],
                    ["Call transcription + QA",      "—", "partial", "—", "—",       "✓"],
                    ["Guest history & profile",      "—", "—", "partial",  "✓",      "✓"],
                    ["Booking pipeline CRM",         "—", "—", "✓",       "partial", "✓"],
                    ["AI-powered insights",          "—", "—", "—",       "—",       "✓"],
                    ["Hospitality-specific",         "—", "partial", "✓", "—",       "✓"],
                    ["Omnichannel (WA + IG + calls)","partial", "—", "—", "—",       "✓"],
                  ].map((row, i) => (
                    <tr
                      key={i}
                      className="transition-colors duration-150 group"
                      style={{ backgroundColor: i % 2 === 0 ? "#ffffff" : "rgba(248,250,252,0.8)" }}
                      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "rgba(0,85,90,0.03)"; }}
                      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = i % 2 === 0 ? "#ffffff" : "rgba(248,250,252,0.8)"; }}
                    >
                      {/* Capability name */}
                      <td
                        className="py-4 px-6 text-sm font-medium border-b"
                        style={{ color: "#334155", borderColor: "#F1F5F9" }}
                      >
                        {row[0]}
                      </td>

                      {/* Comparison cells */}
                      {row.slice(1).map((cell, j) => {
                        const isHaip = j === 4;
                        const cellColor = cell === "✓"
                          ? isHaip ? "#00555a" : "#94A3B8"
                          : cell === "partial"
                          ? "#e6b000"
                          : "#E2E8F0";
                        return (
                          <td
                            key={j}
                            className="py-4 px-4 text-center text-base border-b"
                            style={{
                              borderColor: "#F1F5F9",
                              backgroundColor: isHaip
                                ? i % 2 === 0 ? "rgba(0,85,90,0.06)" : "rgba(0,85,90,0.04)"
                                : "transparent",
                              color: cellColor,
                              fontWeight: cell === "✓" ? 900 : 400,
                            }}
                          >
                            {cell === "partial" ? "◐" : cell}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* SOCIAL PROOF NUMBERS + TESTIMONIALS                               */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-bg)" }}>
        <div className="max-w-5xl mx-auto">

          {/* Section label */}
          <motion.p
            className="text-xs font-bold uppercase tracking-widest mb-12 text-center"
            style={{ color: "#00555a" }}
            variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
          >
            Trusted by hospitality teams
          </motion.p>

          {/* ── Step 11: Stat boxes ──────────────────────────────────────── */}
          <motion.div
            className="grid grid-cols-1 sm:grid-cols-3 gap-6 mb-16"
            variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.1 } } }}
            whileInView="visible" initial="hidden" viewport={VP}
          >
            {[
              { number: "2+",    label: "Properties Onboarded" },
              { number: "94%",   label: "AI Draft Approval Rate" },
              { number: "8 min", label: "Average Response Time" },
            ].map(stat => (
              <motion.div
                key={stat.label}
                variants={scaleUp}
                className="rounded-2xl p-8 text-center"
                style={{ backgroundColor: "#003d41" }}
              >
                <p
                  className="font-black tabular-nums"
                  style={{ fontSize: "clamp(36px, 5vw, 48px)", color: "#ffc94b", lineHeight: 1 }}
                >
                  {stat.number}
                </p>
                <p className="text-sm mt-2" style={{ color: "#94A3B8" }}>{stat.label}</p>
              </motion.div>
            ))}
          </motion.div>

          {/* ── Step 12: Testimonial quote cards ────────────────────────── */}
          <motion.div
            className="grid md:grid-cols-2 gap-8"
            variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.15 } } }}
            whileInView="visible" initial="hidden" viewport={VP}
          >
            {testimonials.map((t, i) => (
              <motion.div
                key={i}
                variants={scaleUp}
                className="relative rounded-2xl p-8 overflow-hidden"
                style={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #E2E8F0",
                  boxShadow: "0 8px 24px rgba(0,0,0,0.06)",
                }}
              >
                {/* Giant quote mark */}
                <span
                  className="absolute top-4 left-5 font-serif select-none pointer-events-none leading-none"
                  style={{ fontSize: "96px", color: "rgba(255,201,75,0.18)", lineHeight: 0.8 }}
                  aria-hidden
                >
                  &ldquo;
                </span>

                {/* Stars */}
                <div className="flex gap-0.5 mb-5 relative z-10">
                  {[...Array(5)].map((_, s) => (
                    <span key={s} style={{ color: "#ffc94b", fontSize: 16 }}>★</span>
                  ))}
                </div>

                {/* Quote */}
                <p
                  className="text-lg leading-relaxed italic mb-7 relative z-10"
                  style={{ color: "#475569" }}
                >
                  {t.quote}
                </p>

                {/* Divider */}
                <div className="h-px mb-5" style={{ backgroundColor: "#E2E8F0" }} />

                {/* Author */}
                <div className="flex items-center gap-3">
                  <div
                    className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold text-white flex-shrink-0"
                    style={{ backgroundColor: "#00555a" }}
                  >
                    {t.author[0]}
                  </div>
                  <div>
                    <p className="text-sm font-semibold" style={{ color: "#0F172A" }}>{t.author}</p>
                    <p className="text-xs mt-0.5" style={{ color: "#64748B" }}>
                      {t.role} · {t.company}
                    </p>
                  </div>
                </div>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* PRICING                                                           */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" id="pricing" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-5xl mx-auto text-center">

          {/* Header */}
          <motion.div
            variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="mb-14"
          >
            <p className="text-xs font-bold uppercase tracking-widest mb-4" style={{ color: "#00555a" }}>
              Pricing
            </p>
            <h2
              className="font-display font-bold leading-[1.0] tracking-tight mb-4"
              style={{ fontSize: "clamp(34px, 4.5vw, 54px)", color: "#0F172A" }}
            >
              Simple plans for every
              <br />
              <span style={{ color: "#00555a", background: "linear-gradient(transparent 68%, rgba(255,201,75,0.45) 68%)" }}>stage of growth.</span>
            </h2>
            <p className="text-base max-w-xl mx-auto" style={{ color: "#475569" }}>
              From boutique villas to multi-property resort groups — GenHaip scales with your portfolio.
            </p>
          </motion.div>

          {/* Cards — Growth is scale-105 and featured */}
          <motion.div
            className="grid sm:grid-cols-3 gap-4 items-start mb-10"
            variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.1 } } }}
            whileInView="visible" initial="hidden" viewport={VP}
          >
            {[
              {
                name: "Starter",
                ideal: "For boutique properties and independent villa operators getting started with guest intelligence.",
                features: [
                  "Unified inbox (WhatsApp + Instagram)",
                  "AI call transcription & scoring",
                  "Guest profiles & inquiry tracking",
                  "Up to 2 properties",
                  "Email support",
                ],
                popular: false,
                cta: "Contact Sales",
              },
              {
                name: "Growth",
                ideal: "For growing hospitality businesses managing multiple properties and teams.",
                features: [
                  "Everything in Starter",
                  "AI Concierge (auto-reply drafts)",
                  "Revenue & booking analytics",
                  "Team performance dashboards",
                  "Up to 10 properties",
                  "Priority support",
                ],
                popular: true,
                cta: "Contact Sales",
              },
              {
                name: "Enterprise",
                ideal: "For resort groups, hotel chains and large villa operators requiring custom configuration.",
                features: [
                  "Everything in Growth",
                  "Unlimited properties",
                  "Custom integrations & API access",
                  "Dedicated account manager",
                  "SLA-backed support",
                  "Onboarding & training",
                ],
                popular: false,
                cta: "Contact Sales",
              },
            ].map(plan => (
              <motion.div
                key={plan.name}
                variants={plan.popular
                  ? { hidden: { opacity: 0, scale: 0.95 }, visible: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: [0.34, 1.56, 0.64, 1] } } }
                  : scaleUp
                }
                className={`relative rounded-2xl p-8 text-left ${plan.popular ? "scale-[1.04]" : ""}`}
                style={plan.popular
                  ? { backgroundColor: "#ffffff", border: "2px solid #00555a", boxShadow: "0 24px 64px rgba(0,85,90,0.18)" }
                  : { backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0" }
                }
              >
                {/* Most Popular badge */}
                {plan.popular && (
                  <span
                    className="absolute -top-4 left-1/2 -translate-x-1/2 text-xs font-bold px-4 py-1 rounded-full whitespace-nowrap"
                    style={{ backgroundColor: "#ffc94b", color: "#00555a" }}
                  >
                    Most Popular
                  </span>
                )}

                {/* Plan name */}
                <h3
                  className="text-2xl font-semibold mb-2"
                  style={{ color: plan.popular ? "#00555a" : "#0F172A" }}
                >
                  {plan.name}
                </h3>
                <p className="text-sm leading-relaxed mb-6" style={{ color: "#475569" }}>
                  {plan.ideal}
                </p>

                {/* Feature list */}
                <ul className="mb-8 space-y-0">
                  {plan.features.map(f => (
                    <li
                      key={f}
                      className="flex items-center gap-3 py-2 text-sm border-b last:border-0"
                      style={{ borderColor: "#E2E8F0" }}
                    >
                      <CheckCircle2 size={14} className="flex-shrink-0" style={{ color: "#00555a" }} />
                      <span style={{ color: "#334155" }}>{f}</span>
                    </li>
                  ))}
                </ul>

                {/* CTA */}
                <Link
                  href="/contact"
                  className="w-full inline-flex items-center justify-center gap-2 px-5 py-3 rounded-xl text-sm font-bold transition-all duration-200"
                  style={plan.popular
                    ? { backgroundColor: "#00555a", color: "#ffffff" }
                    : { backgroundColor: "transparent", color: "#334155", border: "1px solid #CBD5E1" }
                  }
                  onMouseEnter={e => {
                    if (plan.popular) {
                      (e.currentTarget as HTMLElement).style.backgroundColor = "#004a4f";
                    } else {
                      (e.currentTarget as HTMLElement).style.borderColor = "#00555a";
                      (e.currentTarget as HTMLElement).style.color = "#00555a";
                    }
                  }}
                  onMouseLeave={e => {
                    if (plan.popular) {
                      (e.currentTarget as HTMLElement).style.backgroundColor = "#00555a";
                    } else {
                      (e.currentTarget as HTMLElement).style.borderColor = "#CBD5E1";
                      (e.currentTarget as HTMLElement).style.color = "#334155";
                    }
                  }}
                >
                  {plan.cta} <ArrowRight size={14} />
                </Link>
              </motion.div>
            ))}
          </motion.div>

          {/* Trust badges */}
          <motion.div
            variants={fadeIn} whileInView="visible" initial="hidden" viewport={VP}
            className="flex items-center justify-center flex-wrap gap-6 mt-10"
          >
            {[
              { icon: "🔒", label: "DPDP Compliant" },
              { icon: "🇮🇳", label: "Made in India" },
              { icon: "⚡", label: "Setup in 10 mins" },
              { icon: "💳", label: "No credit card" },
            ].map(b => (
              <span key={b.label} className="flex items-center gap-1.5 text-sm" style={{ color: "#64748B" }}>
                <span>{b.icon}</span>
                <span>{b.label}</span>
              </span>
            ))}
          </motion.div>

          <p className="text-xs mt-4" style={{ color: "#94A3B8" }}>
            GST (18%) applicable · Annual plans available
          </p>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* FINAL CTA — brand gradient                                        */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section
        className="py-32 px-5 sm:px-8 relative overflow-hidden"
        style={{ background: "linear-gradient(135deg, #003d41 0%, #00555a 100%)" }}
      >
        {/* Decorative orbs */}
        <div className="absolute right-0 top-0 rounded-full pointer-events-none"
          style={{ width: 384, height: 384, background: "rgba(255,201,75,0.05)", filter: "blur(80px)" }} />
        <div className="absolute pointer-events-none rounded-full"
          style={{ left: 80, bottom: 40, width: 192, height: 192, background: "rgba(255,201,75,0.07)", filter: "blur(60px)" }} />
        {/* Dot grid */}
        <div className="absolute inset-0 pointer-events-none"
          style={{ backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.04) 1px, transparent 1px)", backgroundSize: "28px 28px" }} />

        <div className="max-w-3xl mx-auto text-center relative">
          <motion.div
            variants={stagger}
            initial="hidden"
            whileInView="visible"
            viewport={VP}
          >
            <motion.h2
              variants={fadeUp}
              className="font-display font-black leading-[1.0] tracking-tight mb-5"
              style={{ fontSize: "clamp(38px, 5.5vw, 60px)", color: "#ffffff" }}
            >
              Turn guest conversations
              <br />
              <span style={{ color: "#ffc94b" }}>into revenue.</span>
            </motion.h2>

            <motion.p
              variants={fadeUp}
              className="text-lg leading-relaxed mb-10 max-w-xl mx-auto"
              style={{ color: "rgba(255,255,255,0.65)" }}
            >
              See every guest interaction, booking opportunity and operational insight
              in one platform built for hospitality teams.
            </motion.p>

            <motion.div
              variants={fadeUp}
              className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-8"
            >
              {/* Primary — mimosa */}
              <Link
                href="/book-demo"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all duration-200"
                style={{ backgroundColor: "#ffc94b", color: "#00555a", boxShadow: "0 8px 24px rgba(255,201,75,0.30)" }}
                onMouseEnter={e => {
                  (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000";
                  (e.currentTarget as HTMLElement).style.boxShadow = "0 12px 32px rgba(255,201,75,0.40)";
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b";
                  (e.currentTarget as HTMLElement).style.boxShadow = "0 8px 24px rgba(255,201,75,0.30)";
                }}
              >
                Book a Demo <ArrowRight size={18} />
              </Link>
              {/* Secondary — ghost */}
              <Link
                href="/features"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-semibold text-base transition-all duration-200"
                style={{ border: "2px solid rgba(255,255,255,0.20)", color: "#ffffff" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.40)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.20)"; }}
              >
                Watch Product Tour
              </Link>
            </motion.div>

            <motion.div
              variants={fadeIn}
              className="flex items-center justify-center gap-2 flex-wrap text-sm"
              style={{ color: "rgba(255,255,255,0.45)" }}
            >
              <span>No credit card required</span>
              <span style={{ color: "rgba(255,255,255,0.20)" }}>·</span>
              <span>Setup in under 10 minutes</span>
              <span style={{ color: "rgba(255,255,255,0.20)" }}>·</span>
              <span>Cancel anytime</span>
            </motion.div>
          </motion.div>
        </div>
      </section>

      <MarketingFooter />
    </div>
  );
}
