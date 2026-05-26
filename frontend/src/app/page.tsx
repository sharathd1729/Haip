"use client";

import Link from "next/link";
import { MarketingNav } from "@/components/marketing/MarketingNav";
import { MarketingFooter } from "@/components/marketing/MarketingFooter";
import { GuestJourney } from "@/components/marketing/GuestJourney";
import { AnalyticsTabs } from "@/components/marketing/AnalyticsTabs";
import {
  ArrowRight, CheckCircle2, Sparkles, ChevronRight,
  Users, MessageSquare, Calendar, BarChart2, Zap, LineChart,
  X, ArrowDown,
} from "lucide-react";

// ─────────────────────────────────────────────────────────────────────────────
// Static data
// ─────────────────────────────────────────────────────────────────────────────

const workflowSteps = [
  { label: "WhatsApp Inquiry", sub: "Lead arrives via Meta Cloud API", color: "#3D9E7E", dot: "#3D9E7E" },
  { label: "Call Received", sub: "Auto-transcribed · AI scored", color: "#A6732A", dot: "#A6732A" },
  { label: "Guest Profile Created", sub: "Unified history · All channels", color: "#2D8A6A", dot: "#2D8A6A" },
  { label: "Booking Confirmed", sub: "Revenue tracked · Inquiry closed", color: "#A6732A", dot: "#A6732A" },
  { label: "Revenue Tracked", sub: "Attribution · Lifetime value", color: "#C8964A", dot: "#C8964A" },
];

const capabilities = [
  {
    icon: Users,
    title: "Guest Intelligence",
    desc: "Know every guest before answering the phone. Full history of calls, messages, stays and preferences — instantly accessible.",
    color: "#3D9E7E",
    highlight: "Guest 360°",
    preview: ["Last stay: Sunset Villa · Dec 2024", "Total visits: 3 · LTV: ₹2.4L", "Preferred: Early check-in · Private chef"],
  },
  {
    icon: MessageSquare,
    title: "Communication Hub",
    desc: "Manage WhatsApp, Instagram DMs and calls from one workspace. Full conversation history. Team handoffs. AI suggestions.",
    color: "#A6732A",
    highlight: "Omnichannel",
    preview: ["WhatsApp · 3 unread from Priya", "Instagram · New inquiry: anniversary", "Call · 4m 32s · AI: Booking intent"],
  },
  {
    icon: Calendar,
    title: "Booking Intelligence",
    desc: "Track every inquiry through the pipeline. Know which conversations become bookings and why leads are lost.",
    color: "#2D8A6A",
    highlight: "CRM Pipeline",
    preview: ["12 open inquiries · ₹8.4L pipeline", "Conversion: 34% this month", "Avg response: 8 minutes"],
  },
  {
    icon: BarChart2,
    title: "Revenue Intelligence",
    desc: "Measure booking performance by property, channel and agent. Surface missed upsell opportunities automatically.",
    color: "#C8964A",
    highlight: "AI-powered",
    preview: ["Revenue this month: ₹28.4L", "Top channel: WhatsApp (52%)", "Upsells identified: ₹3.2L"],
  },
  {
    icon: Zap,
    title: "Hospitality Automations",
    desc: "Automate follow-ups, booking confirmations and pre-arrival checklists. AI drafts replies for agent approval.",
    color: "#3D9E7E",
    highlight: "AI Concierge",
    preview: ["Auto follow-up sent: 18 guests", "AI drafts approved: 94%", "Pre-arrival checklist triggered"],
  },
  {
    icon: LineChart,
    title: "Operational Insights",
    desc: "Monitor agent performance, QA scores and team response times. Every call and conversation is scored automatically.",
    color: "#A6732A",
    highlight: "QA Scoring",
    preview: ["Avg QA score: 87/100", "Fastest response: 2 minutes", "Team leaderboard updated"],
  },
];

const integrations = [
  { name: "WhatsApp Business", angle: 0, color: "#25D366", category: "Messaging" },
  { name: "Instagram", angle: 40, color: "#E1306C", category: "Messaging" },
  { name: "CallerDesk", angle: 80, color: "#3B82F6", category: "Telephony" },
  { name: "Acefone", angle: 120, color: "#8B5CF6", category: "Telephony" },
  { name: "RentalWise", angle: 160, color: "#F59E0B", category: "PMS" },
  { name: "Hostaway", angle: 200, color: "#EF4444", category: "PMS" },
  { name: "Razorpay", angle: 240, color: "#3B82F6", category: "Payments" },
  { name: "Google Sheets", angle: 280, color: "#34A853", category: "Data" },
  { name: "Meta Ads", angle: 320, color: "#0066FF", category: "Marketing" },
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
      {/* MOD 1 — HERO: Updated copy + workflow visualization                */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="relative min-h-screen flex items-center overflow-hidden pt-16">
        {/* Coordinate-grid background */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage:
              "linear-gradient(rgba(166,115,42,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(166,115,42,0.06) 1px, transparent 1px)",
            backgroundSize: "64px 64px",
          }}
        />
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: "radial-gradient(ellipse 80% 80% at 65% 45%, transparent 25%, var(--mkt-bg) 80%)",
          }}
        />
        <div
          className="absolute bottom-0 left-0 right-0 h-40 pointer-events-none"
          style={{ background: "linear-gradient(transparent, var(--mkt-bg))" }}
        />

        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 py-24 lg:py-32 w-full">
          <div className="grid lg:grid-cols-2 gap-16 lg:gap-20 items-center">

            {/* Left: copy */}
            <div>
              <div
                className="inline-flex items-center gap-2.5 border rounded-full px-4 py-1.5 mb-10"
                style={{
                  borderColor: "rgba(166,115,42,0.35)",
                  animation: "haipFadeUp 0.7s cubic-bezier(0.16,1,0.3,1) both",
                }}
              >
                <div
                  className="w-1.5 h-1.5 rounded-full"
                  style={{
                    backgroundColor: "var(--mkt-gold)",
                    animation: "haipShimmer 2s ease-in-out infinite",
                  }}
                />
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--mkt-gold)" }}>
                  Hospitality intelligence platform
                </span>
              </div>

              <h1
                className="font-display leading-[1.0] tracking-tight mb-8"
                style={{
                  fontSize: "clamp(48px, 6.5vw, 82px)",
                  fontWeight: 400,
                  animation: "haipFadeUp 0.7s cubic-bezier(0.16,1,0.3,1) 0.1s both",
                  color: "var(--mkt-text)",
                }}
              >
                The Intelligence
                <br />Layer for
                <br />
                <em
                  className="font-display italic"
                  style={{ color: "var(--mkt-gold)", fontWeight: 600 }}
                >
                  Hospitality.
                </em>
              </h1>

              <p
                className="text-lg leading-relaxed max-w-lg mb-10"
                style={{
                  color: "var(--mkt-text)",
                  opacity: 0.55,
                  animation: "haipFadeUp 0.7s cubic-bezier(0.16,1,0.3,1) 0.2s both",
                }}
              >
                Connect calls, WhatsApp conversations, bookings, guest history and
                operational insights in one platform built for hospitality teams.
              </p>

              <div
                className="flex flex-col sm:flex-row gap-4 mb-8"
                style={{ animation: "haipFadeUp 0.7s cubic-bezier(0.16,1,0.3,1) 0.3s both" }}
              >
                <Link
                  href="/book-demo"
                  className="inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all hover:-translate-y-0.5"
                  style={{
                    backgroundColor: "var(--mkt-gold)",
                    color: "#fff",
                    boxShadow: "0 8px 32px rgba(166,115,42,0.28)",
                  }}
                >
                  Book a Demo <ArrowRight size={18} />
                </Link>
                <Link
                  href="/features"
                  className="inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-semibold text-base transition-all"
                  style={{
                    border: "1px solid rgba(0,0,0,0.12)",
                    color: "var(--mkt-text)",
                    opacity: 0.7,
                  }}
                >
                  Watch Product Tour
                </Link>
              </div>

              <p
                className="text-xs"
                style={{
                  color: "var(--mkt-text)",
                  opacity: 0.28,
                  animation: "haipFadeUp 0.7s cubic-bezier(0.16,1,0.3,1) 0.4s both",
                }}
              >
                No credit card required · Setup in under 10 minutes · Cancel anytime
              </p>
            </div>

            {/* Right: Workflow visualization */}
            <div
              className="hidden lg:block"
              style={{ animation: "haipFadeUp 0.9s cubic-bezier(0.16,1,0.3,1) 0.25s both" }}
            >
              <div style={{ animation: "haipFloat 7s ease-in-out 1.2s infinite" }}>
                <div
                  className="rounded-2xl border p-6 shadow-2xl"
                  style={{
                    backgroundColor: "var(--mkt-panel)",
                    borderColor: "rgba(0,0,0,0.08)",
                    boxShadow: "0 32px 80px rgba(0,0,0,0.14)",
                  }}
                >
                  {/* Header */}
                  <div className="flex items-center gap-3 mb-6 pb-4 border-b" style={{ borderColor: "rgba(0,0,0,0.06)" }}>
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-black"
                      style={{ backgroundColor: "var(--mkt-gold)", color: "#fff" }}
                    >
                      G
                    </div>
                    <div>
                      <p className="text-sm font-bold" style={{ color: "var(--mkt-text)" }}>GenHaip — Guest Journey</p>
                      <p className="text-xs" style={{ color: "var(--mkt-text)", opacity: 0.4 }}>Live pipeline view</p>
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
                              boxShadow: `0 4px 12px ${step.color}40`,
                              animation: `haipFadeUp 0.5s cubic-bezier(0.16,1,0.3,1) ${i * 0.1 + 0.5}s both`,
                            }}
                          >
                            {i + 1}
                          </div>
                          {i < workflowSteps.length - 1 && (
                            <div className="w-px h-8 mt-1" style={{ backgroundColor: `${step.color}25` }} />
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
                          <p className="text-xs" style={{ color: "var(--mkt-text)", opacity: 0.42 }}>
                            {step.sub}
                          </p>
                        </div>
                        <div
                          className="mt-2 w-2 h-2 rounded-full flex-shrink-0"
                          style={{ backgroundColor: `${step.color}50` }}
                        />
                      </div>
                    ))}
                  </div>

                  {/* Footer summary */}
                  <div
                    className="mt-4 pt-4 border-t rounded-xl px-3 py-2.5"
                    style={{
                      borderColor: "rgba(0,0,0,0.06)",
                      backgroundColor: "rgba(166,115,42,0.06)",
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <Sparkles size={12} style={{ color: "var(--mkt-gold)" }} />
                      <p className="text-xs font-medium" style={{ color: "var(--mkt-gold)" }}>
                        Every guest interaction, tracked in one timeline
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MOD 3 — FRAGMENTATION PROBLEM                                      */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section
        className="py-24 px-5 sm:px-8"
        style={{ backgroundColor: "var(--mkt-panel)" }}
      >
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-16">
            <p
              className="text-xs font-bold uppercase tracking-widest mb-4"
              style={{ color: "var(--mkt-gold)" }}
            >
              The problem
            </p>
            <h2
              className="font-display leading-[1.05] tracking-tight mb-5"
              style={{ fontSize: "clamp(34px, 4.5vw, 54px)", fontWeight: 400, color: "var(--mkt-text)" }}
            >
              Hospitality operations
              <br />
              <em className="font-display italic" style={{ color: "var(--mkt-text)", opacity: 0.4, fontWeight: 300 }}>
                are fragmented.
              </em>
            </h2>
          </div>

          <div className="grid lg:grid-cols-[1fr_80px_1fr] gap-6 items-center">

            {/* Left: Disconnected */}
            <div
              className="rounded-2xl border p-6"
              style={{ backgroundColor: "var(--mkt-bg)", borderColor: "rgba(225,29,72,0.2)" }}
            >
              <div className="flex items-center gap-2 mb-5">
                <X size={14} className="text-rose-500" />
                <p className="text-sm font-bold text-rose-500">Without GenHaip</p>
              </div>
              <div className="space-y-3">
                {[
                  { tool: "WhatsApp", note: "Guest inquiries arrive on personal phones" },
                  { tool: "Phone Calls", note: "Recordings buried in IVR dashboard" },
                  { tool: "PMS Software", note: "Booking details siloed per property" },
                  { tool: "Spreadsheets", note: "Guest history manually maintained" },
                  { tool: "Email", note: "Follow-ups forgotten or delayed" },
                ].map((item) => (
                  <div
                    key={item.tool}
                    className="flex items-start gap-3 p-3 rounded-xl border"
                    style={{ backgroundColor: "rgba(225,29,72,0.04)", borderColor: "rgba(225,29,72,0.1)" }}
                  >
                    <X size={12} className="text-rose-400 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs font-semibold" style={{ color: "var(--mkt-text)" }}>{item.tool}</p>
                      <p className="text-[11px]" style={{ color: "var(--mkt-text)", opacity: 0.45 }}>{item.note}</p>
                    </div>
                  </div>
                ))}
              </div>
              <div
                className="mt-4 p-3 rounded-xl text-center"
                style={{ backgroundColor: "rgba(225,29,72,0.08)", border: "1px solid rgba(225,29,72,0.15)" }}
              >
                <p className="text-xs font-semibold text-rose-500">
                  Teams never see the complete guest journey
                </p>
              </div>
            </div>

            {/* Center arrow */}
            <div className="flex flex-col items-center justify-center gap-3 py-4">
              <div
                className="w-10 h-10 rounded-full flex items-center justify-center"
                style={{ backgroundColor: "var(--mkt-gold)", boxShadow: "0 4px 16px rgba(166,115,42,0.3)" }}
              >
                <ArrowRight size={18} color="#fff" />
              </div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-center" style={{ color: "var(--mkt-gold)", opacity: 0.7 }}>
                vs
              </p>
            </div>

            {/* Right: Unified */}
            <div
              className="rounded-2xl border p-6"
              style={{ backgroundColor: "var(--mkt-bg)", borderColor: "rgba(45,138,106,0.25)" }}
            >
              <div className="flex items-center gap-2 mb-5">
                <CheckCircle2 size={14} className="text-emerald-600" />
                <p className="text-sm font-bold text-emerald-700">With GenHaip</p>
              </div>
              <div className="space-y-3">
                {[
                  { event: "WhatsApp inquiry arrives", time: "09:14" },
                  { event: "Call received · Auto-transcribed", time: "09:31" },
                  { event: "Guest profile matched · History loaded", time: "09:31" },
                  { event: "AI suggests personalised reply", time: "09:32" },
                  { event: "Booking confirmed · Revenue tracked", time: "09:45" },
                ].map((item, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="text-[10px] font-mono flex-shrink-0 w-10" style={{ color: "var(--mkt-text)", opacity: 0.3 }}>
                      {item.time}
                    </span>
                    <div
                      className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                      style={{ backgroundColor: "var(--mkt-jade)" }}
                    />
                    <p className="text-xs" style={{ color: "var(--mkt-text)", opacity: 0.75 }}>{item.event}</p>
                  </div>
                ))}
              </div>
              <div
                className="mt-4 p-3 rounded-xl text-center"
                style={{ backgroundColor: "rgba(45,138,106,0.08)", border: "1px solid rgba(45,138,106,0.2)" }}
              >
                <p className="text-xs font-semibold" style={{ color: "var(--mkt-jade)" }}>
                  GenHaip connects every interaction into one timeline
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MOD 5 — PLATFORM CAPABILITIES: 6 product cards                     */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" id="features">
        <div className="max-w-7xl mx-auto">
          <div className="mb-16">
            <p className="text-xs font-bold uppercase tracking-widest mb-5" style={{ color: "var(--mkt-gold)" }}>
              Platform capabilities
            </p>
            <h2
              className="font-display leading-[1.0] tracking-tight"
              style={{ fontSize: "clamp(36px, 5vw, 58px)", fontWeight: 400, color: "var(--mkt-text)" }}
            >
              Built for how hospitality
              <br />
              <em className="font-display italic" style={{ color: "var(--mkt-text)", opacity: 0.35, fontWeight: 300 }}>
                teams actually work.
              </em>
            </h2>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {capabilities.map((cap) => {
              const Icon = cap.icon;
              return (
                <div
                  key={cap.title}
                  className="group rounded-2xl border p-6 transition-all duration-300 cursor-default hover:-translate-y-1"
                  style={{
                    backgroundColor: "var(--mkt-panel)",
                    borderColor: "rgba(0,0,0,0.07)",
                    boxShadow: "0 2px 12px rgba(0,0,0,0.04)",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLDivElement).style.borderColor = `${cap.color}35`;
                    (e.currentTarget as HTMLDivElement).style.boxShadow = `0 16px 40px ${cap.color}15`;
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLDivElement).style.borderColor = "rgba(0,0,0,0.07)";
                    (e.currentTarget as HTMLDivElement).style.boxShadow = "0 2px 12px rgba(0,0,0,0.04)";
                  }}
                >
                  {/* Icon + badge */}
                  <div className="flex items-start justify-between mb-4">
                    <div
                      className="w-10 h-10 rounded-xl flex items-center justify-center"
                      style={{ backgroundColor: `${cap.color}15` }}
                    >
                      <Icon size={20} style={{ color: cap.color }} />
                    </div>
                    <span
                      className="text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded-full"
                      style={{
                        backgroundColor: `${cap.color}10`,
                        color: cap.color,
                        border: `1px solid ${cap.color}25`,
                      }}
                    >
                      {cap.highlight}
                    </span>
                  </div>

                  {/* Text */}
                  <h3 className="text-base font-bold mb-2" style={{ color: "var(--mkt-text)" }}>
                    {cap.title}
                  </h3>
                  <p className="text-sm leading-relaxed mb-4" style={{ color: "var(--mkt-text)", opacity: 0.5 }}>
                    {cap.desc}
                  </p>

                  {/* Mini preview */}
                  <div
                    className="rounded-xl p-3 space-y-1.5"
                    style={{ backgroundColor: "var(--mkt-surface)", border: `1px solid ${cap.color}12` }}
                  >
                    {cap.preview.map((line, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <div className="w-1 h-1 rounded-full flex-shrink-0" style={{ backgroundColor: cap.color, opacity: 0.6 }} />
                        <p className="text-[11px] truncate" style={{ color: "var(--mkt-text)", opacity: 0.55 }}>
                          {line}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MOD 4 — CONNECTED GUEST JOURNEY: Interactive                       */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-panel)" }} id="guest-journey">
        <div className="max-w-6xl mx-auto">
          <div className="mb-14">
            <p className="text-xs font-bold uppercase tracking-widest mb-5" style={{ color: "var(--mkt-gold)" }}>
              Connected guest journey
            </p>
            <h2
              className="font-display leading-[1.0] tracking-tight mb-5"
              style={{ fontSize: "clamp(34px, 4.5vw, 54px)", fontWeight: 400, color: "var(--mkt-text)" }}
            >
              Follow every guest from
              <br />
              <em className="font-display italic" style={{ color: "var(--mkt-gold)", fontWeight: 500 }}>
                first message to fifth stay.
              </em>
            </h2>
            <p className="text-base max-w-xl" style={{ color: "var(--mkt-text)", opacity: 0.5 }}>
              Click any stage to see the corresponding screen and data GenHaip captures automatically.
            </p>
          </div>
          <GuestJourney />
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MOD 6 — GUEST 360 SHOWCASE                                         */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8">
        <div className="max-w-7xl mx-auto">
          <div className="grid lg:grid-cols-2 gap-16 items-center">
            <div>
              <p className="text-xs font-bold uppercase tracking-widest mb-5" style={{ color: "var(--mkt-gold)" }}>
                Guest Intelligence
              </p>
              <h2
                className="font-display leading-[1.0] tracking-tight mb-6"
                style={{ fontSize: "clamp(34px, 4.5vw, 54px)", fontWeight: 400, color: "var(--mkt-text)" }}
              >
                Everything about
                <br />
                <em className="font-display italic" style={{ color: "var(--mkt-gold)" }}>
                  every guest.
                </em>
              </h2>
              <p className="text-base leading-relaxed mb-8 max-w-md" style={{ color: "var(--mkt-text)", opacity: 0.5 }}>
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
                  <li key={i} className="flex items-start gap-3 text-sm" style={{ color: "var(--mkt-text)", opacity: 0.6 }}>
                    <CheckCircle2 size={16} className="flex-shrink-0 mt-0.5" style={{ color: "var(--mkt-jade)" }} />
                    {item}
                  </li>
                ))}
              </ul>
              <Link
                href="/features#guests"
                className="inline-flex items-center gap-2 py-2 text-sm font-semibold transition-colors group"
                style={{ color: "var(--mkt-gold)" }}
              >
                Explore Guest Intelligence{" "}
                <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
              </Link>
            </div>

            {/* Guest 360 profile mockup */}
            <div
              className="rounded-2xl border shadow-2xl overflow-hidden"
              style={{
                backgroundColor: "var(--mkt-panel)",
                borderColor: "rgba(0,0,0,0.08)",
                boxShadow: "0 32px 80px rgba(0,0,0,0.12)",
              }}
            >
              {/* Profile header */}
              <div
                className="px-6 py-5 border-b"
                style={{ borderColor: "rgba(0,0,0,0.06)", backgroundColor: "var(--mkt-surface)" }}
              >
                <div className="flex items-center gap-4">
                  <div
                    className="w-12 h-12 rounded-full flex items-center justify-center text-lg font-black text-white"
                    style={{ backgroundColor: "#3D9E7E" }}
                  >
                    P
                  </div>
                  <div className="flex-1">
                    <p className="text-base font-bold" style={{ color: "var(--mkt-text)" }}>Priya Sharma</p>
                    <p className="text-xs" style={{ color: "var(--mkt-text)", opacity: 0.45 }}>
                      +91 98765 43210 · priya@example.com
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs font-bold" style={{ color: "var(--mkt-gold)" }}>VIP Guest</p>
                    <p className="text-[10px]" style={{ color: "var(--mkt-text)", opacity: 0.35 }}>3 stays · ₹2.4L LTV</p>
                  </div>
                </div>
              </div>

              {/* Stats row */}
              <div className="grid grid-cols-4 border-b" style={{ borderColor: "rgba(0,0,0,0.06)" }}>
                {[
                  { label: "Calls", value: "8" },
                  { label: "Messages", value: "47" },
                  { label: "Bookings", value: "3" },
                  { label: "Revenue", value: "₹2.4L" },
                ].map((stat) => (
                  <div
                    key={stat.label}
                    className="text-center py-4 border-r last:border-0"
                    style={{ borderColor: "rgba(0,0,0,0.06)" }}
                  >
                    <p className="font-display text-xl font-light" style={{ color: "var(--mkt-gold)" }}>
                      {stat.value}
                    </p>
                    <p className="text-[10px]" style={{ color: "var(--mkt-text)", opacity: 0.38 }}>
                      {stat.label}
                    </p>
                  </div>
                ))}
              </div>

              {/* Preferences */}
              <div className="px-6 py-4 border-b" style={{ borderColor: "rgba(0,0,0,0.06)" }}>
                <p className="text-[10px] font-bold uppercase tracking-widest mb-3" style={{ color: "var(--mkt-text)", opacity: 0.35 }}>
                  Preferences · Auto-captured
                </p>
                <div className="flex flex-wrap gap-2">
                  {["Early check-in", "Private chef", "Pool-facing room", "Anniversary setup", "Veg meals"].map((pref) => (
                    <span
                      key={pref}
                      className="text-[11px] font-medium px-2.5 py-1 rounded-full border"
                      style={{
                        backgroundColor: "rgba(45,138,106,0.08)",
                        borderColor: "rgba(45,138,106,0.2)",
                        color: "var(--mkt-jade)",
                      }}
                    >
                      {pref}
                    </span>
                  ))}
                </div>
              </div>

              {/* Timeline */}
              <div className="px-6 py-4">
                <p className="text-[10px] font-bold uppercase tracking-widest mb-4" style={{ color: "var(--mkt-text)", opacity: 0.35 }}>
                  Recent timeline
                </p>
                <div className="space-y-3">
                  {[
                    { icon: "📞", event: "Inbound call · 8m 12s · AI Score: 91", time: "Today 11:24 AM", color: "#A6732A" },
                    { icon: "💬", event: "WhatsApp · Booking inquiry · Sunset Villa", time: "Today 09:14 AM", color: "#3D9E7E" },
                    { icon: "✅", event: "Booking confirmed · Dec 20–26 · ₹84,000", time: "Yesterday", color: "#2D8A6A" },
                    { icon: "⭐", event: "5-star review submitted on Google", time: "Jan 2025", color: "#C8964A" },
                  ].map((item, i) => (
                    <div key={i} className="flex items-start gap-3">
                      <span className="text-sm flex-shrink-0 mt-0.5">{item.icon}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs truncate" style={{ color: "var(--mkt-text)", opacity: 0.7 }}>{item.event}</p>
                        <p className="text-[10px]" style={{ color: "var(--mkt-text)", opacity: 0.3 }}>{item.time}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* Communication Hub spotlight (existing — kept)                      */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center">
          <div>
            <div
              className="inline-flex items-center gap-2 border rounded-full px-3 py-1.5 mb-8"
              style={{ backgroundColor: "rgba(45,138,106,0.08)", borderColor: "rgba(45,138,106,0.25)" }}
            >
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-600" />
              <span className="text-xs font-semibold text-emerald-700">Communication Hub</span>
            </div>
            <h2
              className="font-display leading-[1.05] tracking-tight mb-5"
              style={{ fontSize: "clamp(30px, 4vw, 50px)", fontWeight: 400, color: "var(--mkt-text)" }}
            >
              One inbox for every
              <br />
              <em className="font-display italic" style={{ color: "var(--mkt-gold)" }}>guest touchpoint.</em>
            </h2>
            <p className="text-base leading-relaxed mb-8 max-w-md" style={{ color: "var(--mkt-text)", opacity: 0.5 }}>
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
                <li key={i} className="flex items-start gap-3 text-sm" style={{ color: "var(--mkt-text)", opacity: 0.55 }}>
                  <CheckCircle2 size={16} className="flex-shrink-0 mt-0.5" style={{ color: "var(--mkt-jade)" }} />
                  {item}
                </li>
              ))}
            </ul>
            <Link
              href="/features#inbox"
              className="inline-flex items-center gap-2 py-2 text-sm font-semibold group"
              style={{ color: "var(--mkt-gold)" }}
            >
              Explore Communication Hub <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </div>

          {/* Inbox mockup */}
          <div
            className="rounded-2xl border p-5 shadow-2xl"
            style={{ backgroundColor: "var(--mkt-surface)", borderColor: "rgba(0,0,0,0.07)", boxShadow: "0 24px 64px rgba(0,0,0,0.09)" }}
          >
            <div className="flex items-center gap-2 mb-5">
              <div className="text-xs font-semibold" style={{ color: "var(--mkt-text)", opacity: 0.3 }}>INBOX</div>
              <div className="px-2 py-0.5 text-[10px] font-bold rounded-full" style={{ backgroundColor: "var(--mkt-gold)", color: "#fff" }}>
                12 new
              </div>
            </div>
            {[
              { channel: "WA", name: "Priya Sharma", msg: "Booking inquiry — Sunset Villa Dec 20–26", time: "now", tag: "Inquiry", dot: "#25D366" },
              { channel: "IG", name: "Rohit & Kavya", msg: "Anniversary package — do you have availability?", time: "3m", tag: "Inquiry", dot: "#E1306C" },
              { channel: "☎", name: "+91 98765 43210", msg: "Call · 4m 32s · AI: Booking query detected", time: "8m", tag: "Call", dot: "#3B82F6" },
              { channel: "WA", name: "Suresh Kumar", msg: "Can we extend by 2 nights? We love it here", time: "15m", tag: "Guest", dot: "#25D366" },
            ].map((item, i) => (
              <div
                key={i}
                className="flex items-center gap-3 p-3 rounded-xl border-b last:border-0 transition-colors"
                style={{ borderColor: "rgba(0,0,0,0.04)" }}
              >
                <div
                  className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
                  style={{ backgroundColor: item.dot }}
                >
                  {item.channel}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-semibold truncate" style={{ color: "var(--mkt-text)" }}>{item.name}</span>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded-md font-medium"
                      style={
                        item.tag === "Inquiry"
                          ? { backgroundColor: "rgba(166,115,42,0.12)", color: "var(--mkt-gold)" }
                          : { backgroundColor: "rgba(0,0,0,0.05)", color: "var(--mkt-text)", opacity: 0.5 }
                      }
                    >
                      {item.tag}
                    </span>
                  </div>
                  <p className="text-xs truncate" style={{ color: "var(--mkt-text)", opacity: 0.38 }}>{item.msg}</p>
                </div>
                <span className="text-[10px] flex-shrink-0" style={{ color: "var(--mkt-text)", opacity: 0.22 }}>{item.time}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* AI Call Intelligence spotlight (existing — kept + refreshed)       */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8">
        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center">
          {/* Visual */}
          <div
            className="order-2 lg:order-1 rounded-2xl border p-5 shadow-2xl"
            style={{ backgroundColor: "var(--mkt-panel)", borderColor: "rgba(0,0,0,0.08)", boxShadow: "0 24px 64px rgba(0,0,0,0.08)" }}
          >
            <div className="flex items-center justify-between mb-5">
              <span className="text-xs font-semibold" style={{ color: "var(--mkt-text)", opacity: 0.35 }}>
                CALL ANALYSIS — Priya Sharma
              </span>
              <span className="text-xs" style={{ color: "var(--mkt-text)", opacity: 0.25 }}>Today, 11:24 AM · 8m 12s</span>
            </div>
            <div className="grid grid-cols-3 gap-3 mb-5">
              {[
                { label: "QA Score", value: "91", color: "#2D8A6A" },
                { label: "Sentiment", value: "Positive", color: "#2D8A6A" },
                { label: "Outcome", value: "Booked", color: "#A6732A" },
              ].map((card) => (
                <div key={card.label} className="rounded-xl p-3 text-center" style={{ backgroundColor: "var(--mkt-surface)" }}>
                  <div className="text-lg font-black mb-0.5" style={{ color: card.color }}>{card.value}</div>
                  <div className="text-[10px]" style={{ color: "var(--mkt-text)", opacity: 0.35 }}>{card.label}</div>
                </div>
              ))}
            </div>
            <div className="rounded-xl p-3 mb-3 space-y-2.5" style={{ backgroundColor: "var(--mkt-surface)" }}>
              <div className="flex gap-2">
                <span className="text-[10px] font-bold flex-shrink-0" style={{ color: "var(--mkt-gold)" }}>AGENT</span>
                <p className="text-xs" style={{ color: "var(--mkt-text)", opacity: 0.55 }}>
                  Good morning! Thank you for calling. How may I assist you today?
                </p>
              </div>
              <div className="flex gap-2">
                <span className="text-[10px] font-bold flex-shrink-0" style={{ color: "var(--mkt-text)", opacity: 0.35 }}>GUEST</span>
                <p className="text-xs" style={{ color: "var(--mkt-text)", opacity: 0.55 }}>
                  I&apos;d like to book the pool villa for New Year&apos;s week. What&apos;s the availability?
                </p>
              </div>
            </div>
            <div className="space-y-2">
              <div
                className="flex items-center gap-2 border rounded-lg px-3 py-2"
                style={{ backgroundColor: "rgba(166,115,42,0.07)", borderColor: "rgba(166,115,42,0.2)" }}
              >
                <Sparkles size={11} style={{ color: "var(--mkt-gold)" }} />
                <span className="text-xs" style={{ color: "var(--mkt-gold)", opacity: 0.9 }}>
                  Missed upsell: Private chef not offered (₹8,000 opportunity)
                </span>
              </div>
              <div
                className="flex items-center gap-2 border rounded-lg px-3 py-2"
                style={{ backgroundColor: "rgba(45,138,106,0.07)", borderColor: "rgba(45,138,106,0.2)" }}
              >
                <CheckCircle2 size={11} style={{ color: "var(--mkt-jade)" }} />
                <span className="text-xs" style={{ color: "var(--mkt-jade)", opacity: 0.9 }}>
                  Agent handled pricing objection well — closing rate maintained
                </span>
              </div>
            </div>
          </div>

          <div className="order-1 lg:order-2">
            <div
              className="inline-flex items-center gap-2 border rounded-full px-3 py-1.5 mb-8"
              style={{ backgroundColor: "rgba(166,115,42,0.08)", borderColor: "rgba(166,115,42,0.25)" }}
            >
              <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "var(--mkt-gold)" }} />
              <span className="text-xs font-semibold" style={{ color: "var(--mkt-gold)" }}>AI Call Intelligence</span>
            </div>
            <h2
              className="font-display leading-[1.05] tracking-tight mb-5"
              style={{ fontSize: "clamp(30px, 4vw, 50px)", fontWeight: 400, color: "var(--mkt-text)" }}
            >
              Every call,
              <br />
              <em className="font-display italic" style={{ color: "var(--mkt-gold)" }}>automatically analyzed.</em>
            </h2>
            <p className="text-base leading-relaxed mb-8 max-w-md" style={{ color: "var(--mkt-text)", opacity: 0.5 }}>
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
                <li key={i} className="flex items-start gap-3 text-sm" style={{ color: "var(--mkt-text)", opacity: 0.55 }}>
                  <CheckCircle2 size={16} className="flex-shrink-0 mt-0.5" style={{ color: "var(--mkt-jade)" }} />
                  {item}
                </li>
              ))}
            </ul>
            <Link
              href="/features#calls"
              className="inline-flex items-center gap-2 py-2 text-sm font-semibold group"
              style={{ color: "var(--mkt-gold)" }}
            >
              Explore AI Call Intelligence <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MOD 7 — INTEGRATIONS ECOSYSTEM                                     */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-24 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-5xl mx-auto text-center">
          <p className="text-xs font-bold uppercase tracking-widest mb-5" style={{ color: "var(--mkt-gold)" }}>
            Integrations ecosystem
          </p>
          <h2
            className="font-display leading-[1.0] tracking-tight mb-5"
            style={{ fontSize: "clamp(30px, 4vw, 48px)", fontWeight: 400, color: "var(--mkt-text)" }}
          >
            Works with the tools
            <br />
            <em className="font-display italic" style={{ color: "var(--mkt-text)", opacity: 0.4, fontWeight: 300 }}>
              your team already uses.
            </em>
          </h2>
          <p className="text-sm mb-14 max-w-xl mx-auto" style={{ color: "var(--mkt-text)", opacity: 0.45 }}>
            Connect your IVR, PMS, messaging and marketing tools. GenHaip unifies data from
            every system into one guest intelligence platform — no manual data entry.
          </p>

          {/* Integration grid */}
          <div className="grid grid-cols-3 sm:grid-cols-5 gap-3 mb-10">
            {integrations.map((int) => (
              <div
                key={int.name}
                className="group rounded-2xl border p-4 transition-all duration-200 hover:-translate-y-1 cursor-default"
                style={{
                  backgroundColor: "var(--mkt-bg)",
                  borderColor: "rgba(0,0,0,0.07)",
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLDivElement).style.borderColor = `${int.color}40`;
                  (e.currentTarget as HTMLDivElement).style.boxShadow = `0 8px 24px ${int.color}15`;
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLDivElement).style.borderColor = "rgba(0,0,0,0.07)";
                  (e.currentTarget as HTMLDivElement).style.boxShadow = "none";
                }}
              >
                <div
                  className="w-8 h-8 rounded-lg mx-auto mb-2 flex items-center justify-center text-xs font-black text-white"
                  style={{ backgroundColor: int.color }}
                >
                  {int.name[0]}
                </div>
                <p className="text-xs font-semibold leading-tight" style={{ color: "var(--mkt-text)" }}>
                  {int.name}
                </p>
                <p className="text-[10px] mt-0.5" style={{ color: "var(--mkt-text)", opacity: 0.35 }}>
                  {int.category}
                </p>
              </div>
            ))}
            <div
              className="rounded-2xl border p-4 flex flex-col items-center justify-center"
              style={{ backgroundColor: "var(--mkt-bg)", borderColor: "rgba(0,0,0,0.05)", borderStyle: "dashed" }}
            >
              <p className="text-xs font-semibold" style={{ color: "var(--mkt-text)", opacity: 0.3 }}>More</p>
              <p className="text-[10px]" style={{ color: "var(--mkt-text)", opacity: 0.2 }}>Coming soon</p>
            </div>
          </div>

          {/* Category pills */}
          <div className="flex flex-wrap justify-center gap-2">
            {["Messaging", "Telephony", "PMS", "Payments", "Marketing", "Data"].map((cat) => (
              <span
                key={cat}
                className="text-xs font-semibold px-3 py-1.5 rounded-full border"
                style={{
                  backgroundColor: "rgba(166,115,42,0.07)",
                  borderColor: "rgba(166,115,42,0.2)",
                  color: "var(--mkt-gold)",
                }}
              >
                {cat}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MOD 8 — ANALYTICS SECTION: Interactive tabs                        */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8">
        <div className="max-w-5xl mx-auto">
          <div className="mb-14">
            <p className="text-xs font-bold uppercase tracking-widest mb-5" style={{ color: "var(--mkt-gold)" }}>
              Operational insights
            </p>
            <h2
              className="font-display leading-[1.0] tracking-tight mb-5"
              style={{ fontSize: "clamp(34px, 4.5vw, 54px)", fontWeight: 400, color: "var(--mkt-text)" }}
            >
              Answers to the questions
              <br />
              <em className="font-display italic" style={{ color: "var(--mkt-gold)" }}>
                that drive revenue.
              </em>
            </h2>
            <p className="text-base max-w-xl" style={{ color: "var(--mkt-text)", opacity: 0.5 }}>
              Select any area to see the metrics and insights GenHaip surfaces automatically
              from your calls, conversations and bookings.
            </p>
          </div>
          <AnalyticsTabs />
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MOD 9 — WHY GENHAIP: Comparison                                   */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-bold uppercase tracking-widest mb-5" style={{ color: "var(--mkt-gold)" }}>
              Why GenHaip?
            </p>
            <h2
              className="font-display leading-[1.0] tracking-tight mb-5"
              style={{ fontSize: "clamp(34px, 4.5vw, 54px)", fontWeight: 400, color: "var(--mkt-text)" }}
            >
              Every tool does one thing.
              <br />
              <em className="font-display italic" style={{ color: "var(--mkt-gold)" }}>
                GenHaip connects them all.
              </em>
            </h2>
            <p className="text-base max-w-2xl mx-auto" style={{ color: "var(--mkt-text)", opacity: 0.5 }}>
              Messaging tools manage conversations. PMS software manages bookings.
              Call software stores recordings. CRMs manage contacts.
              None of them talk to each other — so your team never has the full picture.
            </p>
          </div>

          {/* Comparison table */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left py-3 pr-6 font-semibold" style={{ color: "var(--mkt-text)", opacity: 0.5, width: "30%" }}>
                    Capability
                  </th>
                  {["Messaging App", "IVR / Call Tool", "PMS Software", "CRM Tool", "GenHaip"].map((col) => (
                    <th
                      key={col}
                      className="py-3 px-4 text-center text-xs font-bold rounded-t-lg"
                      style={{
                        color: col === "GenHaip" ? "#fff" : "var(--mkt-text)",
                        backgroundColor: col === "GenHaip" ? "var(--mkt-gold)" : "var(--mkt-surface)",
                        opacity: col === "GenHaip" ? 1 : 0.7,
                      }}
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  ["Guest communication", "✓", "—", "—", "partial", "✓"],
                  ["Call transcription + QA", "—", "partial", "—", "—", "✓"],
                  ["Guest history & profile", "—", "—", "partial", "✓", "✓"],
                  ["Booking pipeline CRM", "—", "—", "✓", "partial", "✓"],
                  ["AI-powered insights", "—", "—", "—", "—", "✓"],
                  ["Hospitality-specific", "—", "partial", "✓", "—", "✓"],
                  ["Omnichannel (WA + IG + calls)", "partial", "—", "—", "—", "✓"],
                ].map((row, i) => (
                  <tr
                    key={i}
                    className="border-t"
                    style={{ borderColor: "rgba(0,0,0,0.05)" }}
                  >
                    <td className="py-3 pr-6 text-xs" style={{ color: "var(--mkt-text)", opacity: 0.65 }}>{row[0]}</td>
                    {row.slice(1).map((cell, j) => (
                      <td
                        key={j}
                        className="py-3 px-4 text-center text-xs"
                        style={{
                          backgroundColor: j === 4
                            ? i % 2 === 0 ? "rgba(166,115,42,0.08)" : "rgba(166,115,42,0.04)"
                            : "transparent",
                          color: cell === "✓"
                            ? j === 4 ? "var(--mkt-gold)" : "var(--mkt-jade)"
                            : cell === "partial"
                            ? "var(--mkt-text)"
                            : "var(--mkt-text)",
                          opacity: cell === "✓" ? 1 : cell === "partial" ? 0.4 : 0.2,
                          fontWeight: cell === "✓" ? "700" : "400",
                        }}
                      >
                        {cell === "partial" ? "◐" : cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* TESTIMONIALS — kept, refreshed brand name                         */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8">
        <div className="max-w-5xl mx-auto">
          <p
            className="text-xs font-bold uppercase tracking-widest mb-16 text-center"
            style={{ color: "var(--mkt-text)", opacity: 0.25 }}
          >
            Trusted by hospitality teams
          </p>
          <div className="grid md:grid-cols-2 gap-16 md:gap-20">
            {testimonials.map((t, i) => (
              <div key={i}>
                <div
                  className="font-display leading-none select-none mb-4"
                  style={{ fontSize: "96px", color: "var(--mkt-gold)", opacity: 0.18, lineHeight: 0.8, fontWeight: 300 }}
                >
                  &ldquo;
                </div>
                <p className="text-xl leading-relaxed mb-7 font-display italic" style={{ color: "var(--mkt-text)", opacity: 0.75, fontWeight: 400 }}>
                  {t.quote}
                </p>
                <div className="h-px mb-6" style={{ backgroundColor: "var(--mkt-gold)", opacity: 0.15 }} />
                <div>
                  <div className="text-sm font-semibold" style={{ color: "var(--mkt-text)" }}>{t.author}</div>
                  <div className="text-xs mt-0.5" style={{ color: "var(--mkt-text)", opacity: 0.38 }}>
                    {t.role} · {t.company}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MOD 10 — PRICING: Starter / Growth / Enterprise                    */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8" id="pricing" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-5xl mx-auto text-center">
          <p className="text-xs font-bold uppercase tracking-widest mb-4" style={{ color: "var(--mkt-gold)" }}>
            Pricing
          </p>
          <h2
            className="font-display leading-[1.0] tracking-tight mb-4"
            style={{ fontSize: "clamp(34px, 4.5vw, 54px)", fontWeight: 400, color: "var(--mkt-text)" }}
          >
            Simple plans for every
            <br />
            <em className="font-display italic" style={{ color: "var(--mkt-gold)" }}>
              stage of growth.
            </em>
          </h2>
          <p className="text-base mb-14 max-w-xl mx-auto" style={{ color: "var(--mkt-text)", opacity: 0.5 }}>
            From boutique villas to multi-property resort groups — GenHaip scales with your portfolio.
          </p>

          <div className="grid sm:grid-cols-3 gap-4 mb-8">
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
            ].map((plan) => (
              <div
                key={plan.name}
                className="rounded-2xl border p-6 text-left transition-all"
                style={
                  plan.popular
                    ? { backgroundColor: "var(--mkt-bg)", borderColor: "rgba(166,115,42,0.4)", boxShadow: "0 8px 32px rgba(166,115,42,0.12)" }
                    : { backgroundColor: "var(--mkt-bg)", borderColor: "rgba(0,0,0,0.08)" }
                }
              >
                {plan.popular && (
                  <div className="text-[10px] font-bold uppercase tracking-widest mb-3" style={{ color: "var(--mkt-gold)" }}>
                    Most Popular
                  </div>
                )}
                <h3 className="font-display text-2xl font-light mb-3" style={{ color: "var(--mkt-text)" }}>
                  {plan.name}
                </h3>
                <p className="text-xs leading-relaxed mb-5" style={{ color: "var(--mkt-text)", opacity: 0.5 }}>
                  {plan.ideal}
                </p>
                <ul className="space-y-2 mb-6">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-xs" style={{ color: "var(--mkt-text)", opacity: 0.65 }}>
                      <CheckCircle2 size={13} className="flex-shrink-0 mt-0.5" style={{ color: "var(--mkt-jade)" }} />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/contact"
                  className="w-full inline-flex items-center justify-center gap-2 px-5 py-3 rounded-xl text-sm font-bold transition-all"
                  style={
                    plan.popular
                      ? { backgroundColor: "var(--mkt-gold)", color: "#fff" }
                      : { backgroundColor: "var(--mkt-surface)", color: "var(--mkt-text)", border: "1px solid rgba(0,0,0,0.1)" }
                  }
                >
                  {plan.cta} <ChevronRight size={14} />
                </Link>
              </div>
            ))}
          </div>
          <p className="text-xs" style={{ color: "var(--mkt-text)", opacity: 0.25 }}>
            GST (18%) applicable · Annual plans available · No credit card to start
          </p>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MOD 11 — FINAL CTA: Updated copy                                   */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <section className="py-28 px-5 sm:px-8 relative overflow-hidden">
        <div
          className="absolute inset-0 pointer-events-none"
          style={{ background: "radial-gradient(ellipse 70% 60% at 50% 50%, rgba(166,115,42,0.08) 0%, transparent 70%)" }}
        />
        <div
          className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-px"
          style={{ background: "linear-gradient(90deg, transparent, rgba(166,115,42,0.5), transparent)" }}
        />

        <div className="max-w-3xl mx-auto text-center relative">
          <div
            className="w-14 h-14 rounded-2xl border flex items-center justify-center mx-auto mb-8"
            style={{ backgroundColor: "rgba(166,115,42,0.1)", borderColor: "rgba(166,115,42,0.25)" }}
          >
            <ArrowDown size={24} style={{ color: "var(--mkt-gold)" }} />
          </div>
          <h2
            className="font-display leading-[1.0] tracking-tight mb-5"
            style={{ fontSize: "clamp(38px, 5.5vw, 64px)", fontWeight: 400, color: "var(--mkt-text)" }}
          >
            Turn guest conversations
            <br />
            <em className="font-display italic" style={{ color: "var(--mkt-gold)", fontWeight: 600 }}>
              into revenue.
            </em>
          </h2>
          <p className="text-base leading-relaxed mb-12 max-w-xl mx-auto" style={{ color: "var(--mkt-text)", opacity: 0.5 }}>
            See every guest interaction, booking opportunity and operational insight
            in one platform built for hospitality teams.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/book-demo"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all hover:-translate-y-0.5"
              style={{
                backgroundColor: "var(--mkt-gold)",
                color: "#fff",
                boxShadow: "0 8px 32px rgba(166,115,42,0.3)",
              }}
            >
              Book a Demo <ArrowRight size={18} />
            </Link>
            <Link
              href="/features"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-semibold text-base transition-all"
              style={{ border: "1px solid rgba(0,0,0,0.12)", color: "var(--mkt-text)", opacity: 0.7 }}
            >
              Watch Product Tour
            </Link>
          </div>
          <p className="text-xs mt-7" style={{ color: "var(--mkt-text)", opacity: 0.22 }}>
            No credit card required · Setup in under 10 minutes · Cancel anytime
          </p>
        </div>
      </section>

      <MarketingFooter />
    </div>
  );
}
