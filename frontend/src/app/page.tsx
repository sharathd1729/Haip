import Link from "next/link";
import { MarketingNav } from "@/components/marketing/MarketingNav";
import { MarketingFooter } from "@/components/marketing/MarketingFooter";
import {
  ArrowRight, CheckCircle2, Globe, Sparkles, TrendingUp, ChevronRight,
} from "lucide-react";

// ─────────────────────────────────────────────────────────────────────────────
// Data
// ─────────────────────────────────────────────────────────────────────────────
const coreFeatures = [
  {
    title: "Unified Inbox",
    desc: "WhatsApp, Instagram, and phone calls—all in one beautifully organised workspace. Never miss a guest message again.",
    highlight: "Omnichannel",
  },
  {
    title: "AI Call Intelligence",
    desc: "Auto-transcribe every call, detect sentiment, score agent performance, and surface missed revenue opportunities—automatically.",
    highlight: "AI-powered",
  },
  {
    title: "Hospitality CRM",
    desc: "Guest profiles, property management, inquiry tracking and stay history—purpose-built for villa and resort operations.",
    highlight: "Purpose-built",
  },
  {
    title: "WhatsApp Automation",
    desc: "Bulk campaigns, automated replies, and booking confirmations via WhatsApp Business API. No technical setup needed.",
    highlight: "Meta official",
  },
  {
    title: "Auto QA & Compliance",
    desc: "Automated quality scoring for every interaction. DPDP-compliant call archiving with searchable transcripts.",
    highlight: "DPDP-ready",
  },
  {
    title: "AI Insights",
    desc: "Revenue forecasting, guest demand patterns, and competitive intelligence—surfaced automatically from your data.",
    highlight: "Predictive",
  },
];

const integrations = [
  { name: "WhatsApp Business", color: "bg-green-500/10 text-green-400 border-green-500/20" },
  { name: "Instagram", color: "bg-pink-500/10 text-pink-400 border-pink-500/20" },
  { name: "CallerDesk", color: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
  { name: "Acefone", color: "bg-violet-500/10 text-violet-400 border-violet-500/20" },
  { name: "Hostaway", color: "bg-orange-500/10 text-orange-400 border-orange-500/20" },
  { name: "Servetel", color: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20" },
];

const stats = [
  { value: "94%", label: "Avg. QA score improvement" },
  { value: "3.2×", label: "Faster response to guests" },
  { value: "₹2.4L", label: "Avg. monthly revenue recovered" },
  { value: "100%", label: "DPDP compliant" },
];

const testimonials = [
  {
    quote: "HAIP replaced 4 separate tools. Our team now manages every guest interaction from one screen — calls, WhatsApp, inquiries, everything.",
    author: "Priya R.",
    role: "Operations Head",
    company: "Ratha Travels",
  },
  {
    quote: "The AI call analysis saved us hours every week. It scores every call automatically so I don't have to listen to recordings to review my team.",
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

      {/* ──────────────────────────────────────────────────────────────────── */}
      {/* HERO                                                                 */}
      {/* ──────────────────────────────────────────────────────────────────── */}
      <section className="relative min-h-screen flex items-center overflow-hidden pt-16">
        {/* Coordinate-grid background */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage:
              "linear-gradient(rgba(200,150,74,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(200,150,74,0.045) 1px, transparent 1px)",
            backgroundSize: "64px 64px",
          }}
        />
        {/* Radial fade: grid fades toward centre and right */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse 80% 80% at 65% 45%, transparent 25%, var(--mkt-bg) 80%)",
          }}
        />
        {/* Bottom fade */}
        <div
          className="absolute bottom-0 left-0 right-0 h-40 pointer-events-none"
          style={{ background: "linear-gradient(transparent, var(--mkt-bg))" }}
        />

        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 py-24 lg:py-32 w-full">
          <div className="grid lg:grid-cols-2 gap-16 lg:gap-20 items-center">

            {/* ── Left: copy ─────────────────────────────────────────────── */}
            <div>
              {/* Eyebrow */}
              <div
                className="inline-flex items-center gap-2.5 border rounded-full px-4 py-1.5 mb-10"
                style={{
                  borderColor: "rgba(200,150,74,0.35)",
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
                <span
                  className="text-xs font-semibold uppercase tracking-wider"
                  style={{ color: "var(--mkt-gold)" }}
                >
                  Built for India&apos;s luxury hospitality sector
                </span>
              </div>

              {/* Headline — Cormorant Garamond display */}
              <h1
                className="font-display leading-[1.0] tracking-tight mb-8"
                style={{
                  fontSize: "clamp(52px, 7vw, 88px)",
                  fontWeight: 400,
                  animation: "haipFadeUp 0.7s cubic-bezier(0.16,1,0.3,1) 0.1s both",
                }}
              >
                The intelligence
                <br />layer for
                <br />
                <span
                  className="font-display italic"
                  style={{ color: "var(--mkt-gold)", fontWeight: 600 }}
                >
                  luxury<br />hospitality.
                </span>
              </h1>

              {/* Sub-headline */}
              <p
                className="text-lg leading-relaxed max-w-lg mb-10"
                style={{
                  color: "rgba(240,232,208,0.55)",
                  animation: "haipFadeUp 0.7s cubic-bezier(0.16,1,0.3,1) 0.2s both",
                }}
              >
                Unified inbox for WhatsApp, calls, and DMs. AI-powered call
                analysis. Hospitality CRM. Everything your team needs to deliver
                extraordinary guest experiences — in one platform.
              </p>

              {/* CTAs */}
              <div
                className="flex flex-col sm:flex-row gap-4 mb-8"
                style={{
                  animation: "haipFadeUp 0.7s cubic-bezier(0.16,1,0.3,1) 0.3s both",
                }}
              >
                <Link
                  href="/register"
                  className="inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all hover:-translate-y-0.5"
                  style={{
                    backgroundColor: "var(--mkt-gold)",
                    color: "var(--mkt-bg)",
                    boxShadow: "0 8px 32px rgba(200,150,74,0.28)",
                  }}
                >
                  Start 14-day free trial <ArrowRight size={18} />
                </Link>
                <Link
                  href="#demo"
                  className="inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-semibold text-base transition-all"
                  style={{
                    border: "1px solid rgba(240,232,208,0.15)",
                    color: "rgba(240,232,208,0.7)",
                  }}
                >
                  Watch demo
                </Link>
              </div>

              {/* Trust */}
              <p
                className="text-xs"
                style={{
                  color: "rgba(240,232,208,0.25)",
                  animation: "haipFadeUp 0.7s cubic-bezier(0.16,1,0.3,1) 0.4s both",
                }}
              >
                No credit card required · 14-day free trial · Cancel anytime
              </p>
            </div>

            {/* ── Right: dashboard mockup ─────────────────────────────────── */}
            <div
              className="hidden lg:block"
              style={{ animation: "haipFadeUp 0.9s cubic-bezier(0.16,1,0.3,1) 0.25s both" }}
            >
              <div style={{ animation: "haipFloat 7s ease-in-out 1.2s infinite" }}>
                <div
                  className="rounded-2xl overflow-hidden shadow-2xl"
                  style={{
                    backgroundColor: "var(--mkt-panel)",
                    border: "1px solid rgba(240,232,208,0.07)",
                    boxShadow: "0 32px 80px rgba(0,0,0,0.7)",
                  }}
                >
                  {/* Browser chrome */}
                  <div
                    className="flex items-center gap-2 px-4 py-3 border-b"
                    style={{
                      backgroundColor: "rgba(0,0,0,0.25)",
                      borderColor: "rgba(240,232,208,0.05)",
                    }}
                  >
                    <div className="flex gap-1.5">
                      <div className="w-3 h-3 rounded-full bg-red-500/50" />
                      <div className="w-3 h-3 rounded-full bg-amber-500/50" />
                      <div className="w-3 h-3 rounded-full bg-green-500/50" />
                    </div>
                    <div
                      className="flex-1 mx-4 rounded-lg h-5 flex items-center px-3"
                      style={{ backgroundColor: "rgba(240,232,208,0.04)" }}
                    >
                      <span
                        className="text-[10px] font-mono"
                        style={{ color: "rgba(240,232,208,0.2)" }}
                      >
                        app.haip.app/dashboard/inbox
                      </span>
                    </div>
                  </div>

                  {/* Mock inbox */}
                  <div className="flex h-[380px]">
                    {/* Icon sidebar */}
                    <div
                      className="w-14 flex flex-col items-center py-4 gap-3 border-r"
                      style={{
                        backgroundColor: "var(--mkt-bg)",
                        borderColor: "rgba(240,232,208,0.05)",
                      }}
                    >
                      {["H", "✉", "📞", "👥", "📊"].map((icon, i) => (
                        <div
                          key={i}
                          className="w-8 h-8 rounded-lg flex items-center justify-center text-xs"
                          style={
                            i === 0
                              ? { backgroundColor: "var(--mkt-gold)", color: "var(--mkt-bg)" }
                              : { backgroundColor: "rgba(240,232,208,0.04)", color: "rgba(240,232,208,0.25)" }
                          }
                        >
                          {icon}
                        </div>
                      ))}
                    </div>

                    {/* Conversation list */}
                    <div
                      className="w-60 border-r overflow-hidden"
                      style={{ borderColor: "rgba(240,232,208,0.05)" }}
                    >
                      <div
                        className="px-3 py-3 border-b"
                        style={{ borderColor: "rgba(240,232,208,0.05)" }}
                      >
                        <div
                          className="h-7 rounded-lg"
                          style={{ backgroundColor: "rgba(240,232,208,0.04)" }}
                        />
                      </div>
                      {[
                        { name: "Priya Sharma", msg: "Is the villa available for...", time: "2m", unread: true, color: "bg-green-500" },
                        { name: "Arjun Mehta", msg: "Confirm my reservation for...", time: "15m", unread: true, color: "bg-pink-500" },
                        { name: "Sunita K.", msg: "Thanks for the quick reply", time: "1h", unread: false, color: "bg-blue-500" },
                        { name: "Dev & Meera", msg: "Can we extend by 2 nights?", time: "2h", unread: false, color: "bg-violet-500" },
                        { name: "Vikram Singh", msg: "Amazing stay, 5 stars!", time: "3h", unread: false, color: "bg-orange-500" },
                      ].map((conv, i) => (
                        <div
                          key={i}
                          className={`flex items-center gap-3 px-3 py-2.5 border-b ${conv.color}`}
                          style={{
                            borderColor: "rgba(240,232,208,0.03)",
                            backgroundColor: i === 0 ? "rgba(200,150,74,0.08)" : undefined,
                          }}
                        >
                          <div
                            className={`w-7 h-7 rounded-full ${conv.color} flex-shrink-0 flex items-center justify-center text-[11px] font-bold text-white`}
                          >
                            {conv.name[0]}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between">
                              <span
                                className="text-xs font-semibold truncate"
                                style={{ color: "rgba(240,232,208,0.8)" }}
                              >
                                {conv.name}
                              </span>
                              <span
                                className="text-[10px]"
                                style={{ color: "rgba(240,232,208,0.25)" }}
                              >
                                {conv.time}
                              </span>
                            </div>
                            <p
                              className="text-[11px] truncate"
                              style={{ color: "rgba(240,232,208,0.35)" }}
                            >
                              {conv.msg}
                            </p>
                          </div>
                          {conv.unread && (
                            <div
                              className="w-2 h-2 rounded-full flex-shrink-0"
                              style={{ backgroundColor: "var(--mkt-gold)" }}
                            />
                          )}
                        </div>
                      ))}
                    </div>

                    {/* Chat area */}
                    <div className="flex-1 flex flex-col">
                      <div
                        className="flex items-center gap-3 px-4 py-3 border-b"
                        style={{ borderColor: "rgba(240,232,208,0.05)" }}
                      >
                        <div className="w-8 h-8 rounded-full bg-green-500 flex items-center justify-center text-xs font-bold text-white">
                          P
                        </div>
                        <div>
                          <p
                            className="text-xs font-semibold"
                            style={{ color: "rgba(240,232,208,0.8)" }}
                          >
                            Priya Sharma
                          </p>
                          <p
                            className="text-[10px]"
                            style={{ color: "rgba(240,232,208,0.3)" }}
                          >
                            via WhatsApp · Guest
                          </p>
                        </div>
                        <div className="ml-auto flex gap-2">
                          <div
                            className="px-2 py-1 text-[10px] rounded-md"
                            style={{
                              backgroundColor: "rgba(200,150,74,0.15)",
                              color: "var(--mkt-gold)",
                            }}
                          >
                            AI Suggest
                          </div>
                          <div
                            className="px-2 py-1 text-[10px] rounded-md"
                            style={{
                              backgroundColor: "rgba(240,232,208,0.05)",
                              color: "rgba(240,232,208,0.35)",
                            }}
                          >
                            Details
                          </div>
                        </div>
                      </div>

                      <div className="flex-1 px-4 py-3 space-y-3 overflow-hidden">
                        <div className="flex justify-start">
                          <div
                            className="rounded-2xl rounded-tl-sm px-3 py-2 max-w-[72%]"
                            style={{ backgroundColor: "rgba(240,232,208,0.07)" }}
                          >
                            <p
                              className="text-xs"
                              style={{ color: "rgba(240,232,208,0.65)" }}
                            >
                              Hello! Is the Sunset Villa available for Dec 20-26? We&apos;re a family of 6.
                            </p>
                          </div>
                        </div>
                        <div className="flex justify-end">
                          <div
                            className="rounded-2xl rounded-tr-sm px-3 py-2 max-w-[72%]"
                            style={{ backgroundColor: "rgba(200,150,74,0.12)" }}
                          >
                            <p
                              className="text-xs"
                              style={{ color: "rgba(240,232,208,0.8)" }}
                            >
                              Hi Priya! Yes, Sunset Villa is available. It comfortably fits 8 guests. Shall I send the pricing details?
                            </p>
                          </div>
                        </div>
                        {/* AI suggestion */}
                        <div
                          className="flex gap-2 items-start rounded-xl p-2.5 border"
                          style={{
                            backgroundColor: "rgba(200,150,74,0.07)",
                            borderColor: "rgba(200,150,74,0.2)",
                          }}
                        >
                          <Sparkles size={12} className="flex-shrink-0 mt-0.5" style={{ color: "var(--mkt-gold)" }} />
                          <p
                            className="text-[11px]"
                            style={{ color: "rgba(200,150,74,0.9)" }}
                          >
                            AI: &ldquo;Yes, we offer a private chef service at ₹4,000/day. Would you like me to arrange?&rdquo;
                          </p>
                        </div>
                      </div>

                      <div
                        className="px-4 py-3 border-t"
                        style={{ borderColor: "rgba(240,232,208,0.05)" }}
                      >
                        <div
                          className="flex items-center gap-2 rounded-xl px-3 py-2"
                          style={{ backgroundColor: "rgba(240,232,208,0.04)" }}
                        >
                          <span
                            className="text-xs flex-1"
                            style={{ color: "rgba(240,232,208,0.2)" }}
                          >
                            Reply to Priya…
                          </span>
                          <div
                            className="w-6 h-6 rounded-lg flex items-center justify-center"
                            style={{ backgroundColor: "var(--mkt-gold)" }}
                          >
                            <ArrowRight size={11} style={{ color: "var(--mkt-bg)" }} />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* ──────────────────────────────────────────────────────────────────── */}
      {/* STATS                                                                */}
      {/* ──────────────────────────────────────────────────────────────────── */}
      <section
        className="py-16"
        style={{ borderTop: "1px solid rgba(200,150,74,0.12)", borderBottom: "1px solid rgba(200,150,74,0.12)" }}
      >
        <div className="max-w-5xl mx-auto px-5 sm:px-8 grid grid-cols-2 md:grid-cols-4 gap-8">
          {stats.map((s) => (
            <div key={s.value} className="text-center">
              <div
                className="font-display text-5xl sm:text-6xl font-light mb-1"
                style={{ color: "var(--mkt-gold)" }}
              >
                {s.value}
              </div>
              <div
                className="text-xs leading-snug"
                style={{ color: "rgba(240,232,208,0.38)" }}
              >
                {s.label}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ──────────────────────────────────────────────────────────────────── */}
      {/* FEATURES — editorial numbered list                                  */}
      {/* ──────────────────────────────────────────────────────────────────── */}
      <section className="py-28 px-5 sm:px-8" id="features">
        <div className="max-w-4xl mx-auto">
          <div className="mb-16">
            <p
              className="text-xs font-bold uppercase tracking-widest mb-5"
              style={{ color: "var(--mkt-gold)" }}
            >
              Everything in one platform
            </p>
            <h2
              className="font-display leading-[1.0] tracking-tight"
              style={{ fontSize: "clamp(38px, 5vw, 60px)", fontWeight: 400 }}
            >
              Built for how hospitality
              <br />
              <em
                className="font-display"
                style={{ color: "rgba(240,232,208,0.45)", fontStyle: "italic", fontWeight: 300 }}
              >
                teams actually work.
              </em>
            </h2>
          </div>

          <div>
            {coreFeatures.map((f, i) => (
              <div
                key={i}
                className="flex gap-8 sm:gap-12 py-9 group cursor-default transition-all duration-300"
                style={{ borderBottom: "1px solid rgba(200,150,74,0.1)" }}
              >
                {/* Large serif numeral */}
                <div
                  className="font-display leading-none select-none flex-shrink-0 w-14 sm:w-20 pt-1 transition-all duration-300 group-hover:opacity-70"
                  style={{
                    fontSize: "clamp(48px, 6vw, 80px)",
                    fontWeight: 300,
                    color: "rgba(200,150,74,0.22)",
                  }}
                >
                  {String(i + 1).padStart(2, "0")}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0 pt-1">
                  <div className="flex items-start justify-between gap-4 mb-3">
                    <h3
                      className="text-lg sm:text-xl font-semibold transition-colors duration-300 group-hover:text-[#C8964A]"
                      style={{ color: "var(--mkt-text)" }}
                    >
                      {f.title}
                    </h3>
                    <span
                      className="hidden sm:inline-flex flex-shrink-0 text-[10px] font-bold uppercase tracking-widest border rounded-full px-2.5 py-1"
                      style={{
                        color: "rgba(200,150,74,0.55)",
                        borderColor: "rgba(200,150,74,0.2)",
                      }}
                    >
                      {f.highlight}
                    </span>
                  </div>
                  <p
                    className="text-sm leading-relaxed max-w-xl"
                    style={{ color: "rgba(240,232,208,0.45)" }}
                  >
                    {f.desc}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ──────────────────────────────────────────────────────────────────── */}
      {/* INTEGRATIONS                                                         */}
      {/* ──────────────────────────────────────────────────────────────────── */}
      <section className="py-14 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-4xl mx-auto text-center">
          <p
            className="text-xs font-bold uppercase tracking-widest mb-5"
            style={{ color: "rgba(240,232,208,0.25)" }}
          >
            Works with your existing tools
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            {integrations.map((int) => (
              <div
                key={int.name}
                className={`px-4 py-2 rounded-xl border text-sm font-medium ${int.color}`}
              >
                {int.name}
              </div>
            ))}
            <div
              className="px-4 py-2 rounded-xl border text-sm font-medium"
              style={{ borderColor: "rgba(240,232,208,0.1)", color: "rgba(240,232,208,0.25)" }}
            >
              + More coming
            </div>
          </div>
        </div>
      </section>

      {/* ──────────────────────────────────────────────────────────────────── */}
      {/* SPOTLIGHT — Unified Inbox                                            */}
      {/* ──────────────────────────────────────────────────────────────────── */}
      <section className="py-28 px-5 sm:px-8">
        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center">
          <div>
            <div
              className="inline-flex items-center gap-2 border rounded-full px-3 py-1.5 mb-8"
              style={{
                backgroundColor: "rgba(61,158,126,0.08)",
                borderColor: "rgba(61,158,126,0.25)",
              }}
            >
              <div className="w-1.5 h-1.5 rounded-full bg-[#3D9E7E]" />
              <span className="text-xs font-semibold text-[#3D9E7E]">Unified Inbox</span>
            </div>
            <h2
              className="font-display leading-[1.05] tracking-tight mb-5"
              style={{ fontSize: "clamp(32px, 4vw, 52px)", fontWeight: 400 }}
            >
              One inbox for every
              <br />
              <em className="font-display" style={{ color: "var(--mkt-gold)", fontStyle: "italic" }}>
                guest touchpoint.
              </em>
            </h2>
            <p
              className="text-base leading-relaxed mb-8 max-w-md"
              style={{ color: "rgba(240,232,208,0.5)" }}
            >
              Your team switches between 4 apps to manage guest communications.
              HAIP combines WhatsApp, Instagram DMs, and phone calls in one clean
              workspace — with full conversation history for every guest.
            </p>
            <ul className="space-y-3 mb-8">
              {[
                "WhatsApp Business (official Meta Cloud API)",
                "Instagram DMs and mentions",
                "Phone calls with auto-transcription",
                "AI-suggested replies based on guest history",
                "Real-time team collaboration and handoffs",
              ].map((item, i) => (
                <li key={i} className="flex items-start gap-3 text-sm" style={{ color: "rgba(240,232,208,0.55)" }}>
                  <CheckCircle2 size={16} className="flex-shrink-0 mt-0.5" style={{ color: "var(--mkt-jade)" }} />
                  {item}
                </li>
              ))}
            </ul>
            <Link
              href="/features#inbox"
              className="inline-flex items-center gap-2 py-2 text-sm font-semibold transition-colors group"
              style={{ color: "var(--mkt-gold)" }}
            >
              Explore Unified Inbox{" "}
              <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </div>

          {/* Visual */}
          <div
            className="rounded-2xl border p-5 shadow-2xl"
            style={{
              backgroundColor: "var(--mkt-panel)",
              borderColor: "rgba(240,232,208,0.07)",
              boxShadow: "0 24px 64px rgba(0,0,0,0.55)",
            }}
          >
            <div className="flex items-center gap-2 mb-5">
              <div className="text-xs font-semibold" style={{ color: "rgba(240,232,208,0.3)" }}>INBOX</div>
              <div
                className="px-2 py-0.5 text-[10px] font-bold rounded-full"
                style={{ backgroundColor: "var(--mkt-gold)", color: "var(--mkt-bg)" }}
              >
                12 new
              </div>
            </div>
            {[
              { channel: "WA", name: "Anjali Patel", msg: "Booking inquiry - Garden Suite", time: "now", tag: "Inquiry", dot: "bg-green-500" },
              { channel: "IG", name: "Rohit & Kavya", msg: "Anniversary package available?", time: "3m", tag: "Inquiry", dot: "bg-pink-500" },
              { channel: "☎", name: "+91 98765 43210", msg: "Call · 4m 32s · AI: Booking query", time: "8m", tag: "Resolved", dot: "bg-blue-500" },
              { channel: "WA", name: "Suresh Kumar", msg: "Check-out at 12 or 2 pm?", time: "15m", tag: "Guest", dot: "bg-green-500" },
            ].map((item, i) => (
              <div
                key={i}
                className="flex items-center gap-3 p-3 rounded-xl transition-colors border-b last:border-0"
                style={{ borderColor: "rgba(240,232,208,0.04)" }}
              >
                <div className={`w-9 h-9 rounded-full ${item.dot}/15 flex items-center justify-center text-xs font-bold flex-shrink-0`}
                  style={{ color: "rgba(240,232,208,0.7)" }}>
                  {item.channel}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-semibold truncate" style={{ color: "rgba(240,232,208,0.8)" }}>{item.name}</span>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded-md font-medium"
                      style={
                        item.tag === "Inquiry"
                          ? { backgroundColor: "rgba(200,150,74,0.15)", color: "var(--mkt-gold)" }
                          : { backgroundColor: "rgba(240,232,208,0.06)", color: "rgba(240,232,208,0.35)" }
                      }
                    >
                      {item.tag}
                    </span>
                  </div>
                  <p className="text-xs truncate" style={{ color: "rgba(240,232,208,0.38)" }}>{item.msg}</p>
                </div>
                <span className="text-[10px] flex-shrink-0" style={{ color: "rgba(240,232,208,0.22)" }}>{item.time}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ──────────────────────────────────────────────────────────────────── */}
      {/* SPOTLIGHT — AI Call Intelligence                                     */}
      {/* ──────────────────────────────────────────────────────────────────── */}
      <section className="py-28 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center">
          {/* Visual */}
          <div
            className="order-2 lg:order-1 rounded-2xl border p-5 shadow-2xl"
            style={{
              backgroundColor: "var(--mkt-surface)",
              borderColor: "rgba(240,232,208,0.07)",
              boxShadow: "0 24px 64px rgba(0,0,0,0.55)",
            }}
          >
            <div className="flex items-center justify-between mb-5">
              <span className="text-xs font-semibold" style={{ color: "rgba(240,232,208,0.3)" }}>
                CALL ANALYSIS — Anjali Sharma
              </span>
              <span className="text-xs" style={{ color: "rgba(240,232,208,0.22)" }}>
                Today, 11:24 AM · 8m 16s
              </span>
            </div>
            <div className="grid grid-cols-3 gap-3 mb-5">
              {[
                { label: "QA Score", value: "87", color: "#C8964A" },
                { label: "Sentiment", value: "Positive", color: "#3D9E7E" },
                { label: "Outcome", value: "Booked", color: "#C8964A" },
              ].map((card) => (
                <div
                  key={card.label}
                  className="rounded-xl p-3 text-center"
                  style={{ backgroundColor: "rgba(240,232,208,0.04)" }}
                >
                  <div className="text-lg font-black mb-0.5" style={{ color: card.color }}>
                    {card.value}
                  </div>
                  <div className="text-[10px]" style={{ color: "rgba(240,232,208,0.3)" }}>
                    {card.label}
                  </div>
                </div>
              ))}
            </div>
            <div
              className="rounded-xl p-3 mb-3 space-y-2.5"
              style={{ backgroundColor: "rgba(240,232,208,0.03)" }}
            >
              <div className="flex gap-2">
                <span className="text-[10px] font-bold flex-shrink-0" style={{ color: "var(--mkt-gold)" }}>
                  AGENT
                </span>
                <p className="text-xs" style={{ color: "rgba(240,232,208,0.55)" }}>
                  Good morning! Thank you for calling Jade Resorts. How may I assist you today?
                </p>
              </div>
              <div className="flex gap-2">
                <span className="text-[10px] font-bold flex-shrink-0" style={{ color: "rgba(240,232,208,0.28)" }}>
                  GUEST
                </span>
                <p className="text-xs" style={{ color: "rgba(240,232,208,0.55)" }}>
                  Hi, I&apos;d like to book the pool villa for New Year&apos;s week. What&apos;s available?
                </p>
              </div>
            </div>
            <div className="space-y-2">
              <div
                className="flex items-center gap-2 border rounded-lg px-3 py-2"
                style={{ backgroundColor: "rgba(200,150,74,0.08)", borderColor: "rgba(200,150,74,0.2)" }}
              >
                <TrendingUp size={11} style={{ color: "var(--mkt-gold)" }} />
                <span className="text-xs" style={{ color: "rgba(200,150,74,0.9)" }}>
                  Missed upsell: Private chef not offered (₹8,000 opportunity)
                </span>
              </div>
              <div
                className="flex items-center gap-2 border rounded-lg px-3 py-2"
                style={{ backgroundColor: "rgba(61,158,126,0.08)", borderColor: "rgba(61,158,126,0.2)" }}
              >
                <CheckCircle2 size={11} style={{ color: "var(--mkt-jade)" }} />
                <span className="text-xs" style={{ color: "rgba(61,158,126,0.9)" }}>
                  Agent handled pricing objection well — closing rate maintained
                </span>
              </div>
            </div>
          </div>

          <div className="order-1 lg:order-2">
            <div
              className="inline-flex items-center gap-2 border rounded-full px-3 py-1.5 mb-8"
              style={{
                backgroundColor: "rgba(200,150,74,0.08)",
                borderColor: "rgba(200,150,74,0.25)",
              }}
            >
              <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "var(--mkt-gold)" }} />
              <span className="text-xs font-semibold" style={{ color: "var(--mkt-gold)" }}>
                AI Call Intelligence
              </span>
            </div>
            <h2
              className="font-display leading-[1.05] tracking-tight mb-5"
              style={{ fontSize: "clamp(32px, 4vw, 52px)", fontWeight: 400 }}
            >
              Every call,
              <br />
              <em className="font-display" style={{ color: "var(--mkt-gold)", fontStyle: "italic" }}>
                automatically analyzed.
              </em>
            </h2>
            <p
              className="text-base leading-relaxed mb-8 max-w-md"
              style={{ color: "rgba(240,232,208,0.5)" }}
            >
              Stop manually reviewing call recordings. HAIP transcribes, scores, and
              extracts insights from 100% of your calls — surfacing missed revenue,
              agent coaching moments, and guest intent signals automatically.
            </p>
            <ul className="space-y-3 mb-8">
              {[
                "Auto-transcription via Whisper AI (Indian accent optimized)",
                "Agent QA scoring — no manual listening required",
                "Missed revenue opportunity detection",
                "Sentiment analysis per call",
                "Works with CallerDesk, Acefone, Servetel, MCube",
              ].map((item, i) => (
                <li key={i} className="flex items-start gap-3 text-sm" style={{ color: "rgba(240,232,208,0.55)" }}>
                  <CheckCircle2 size={16} className="flex-shrink-0 mt-0.5" style={{ color: "var(--mkt-jade)" }} />
                  {item}
                </li>
              ))}
            </ul>
            <Link
              href="/features#calls"
              className="inline-flex items-center gap-2 py-2 text-sm font-semibold transition-colors group"
              style={{ color: "var(--mkt-gold)" }}
            >
              Explore AI Call Intelligence{" "}
              <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </div>
        </div>
      </section>

      {/* ──────────────────────────────────────────────────────────────────── */}
      {/* TESTIMONIALS — editorial pull-quote                                  */}
      {/* ──────────────────────────────────────────────────────────────────── */}
      <section className="py-28 px-5 sm:px-8">
        <div className="max-w-5xl mx-auto">
          <p
            className="text-xs font-bold uppercase tracking-widest mb-16 text-center"
            style={{ color: "rgba(240,232,208,0.25)" }}
          >
            Trusted by hospitality teams
          </p>
          <div className="grid md:grid-cols-2 gap-16 md:gap-20">
            {testimonials.map((t, i) => (
              <div key={i}>
                {/* Large decorative quote mark */}
                <div
                  className="font-display leading-none select-none mb-4"
                  style={{ fontSize: "96px", color: "rgba(200,150,74,0.18)", lineHeight: 0.8, fontWeight: 300 }}
                >
                  &ldquo;
                </div>
                <p
                  className="text-xl leading-relaxed mb-7 font-display italic"
                  style={{ color: "rgba(240,232,208,0.75)", fontWeight: 400 }}
                >
                  {t.quote}
                </p>
                <div
                  className="h-px mb-6"
                  style={{ backgroundColor: "rgba(200,150,74,0.15)" }}
                />
                <div>
                  <div className="text-sm font-semibold" style={{ color: "var(--mkt-text)" }}>
                    {t.author}
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: "rgba(240,232,208,0.38)" }}>
                    {t.role} · {t.company}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ──────────────────────────────────────────────────────────────────── */}
      {/* PRICING                                                              */}
      {/* ──────────────────────────────────────────────────────────────────── */}
      <section className="py-28 px-5 sm:px-8" id="pricing" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-3xl mx-auto text-center">
          <p
            className="text-xs font-bold uppercase tracking-widest mb-4"
            style={{ color: "var(--mkt-gold)" }}
          >
            Simple, transparent pricing
          </p>
          <h2
            className="font-display leading-[1.0] tracking-tight mb-4"
            style={{ fontSize: "clamp(36px, 5vw, 56px)", fontWeight: 400 }}
          >
            Pay only for what you use.
          </h2>
          <p
            className="text-base mb-12"
            style={{ color: "rgba(240,232,208,0.45)" }}
          >
            Pick the modules your property needs. Pay per property, per month.
            <br className="hidden sm:block" />
            No platform fees. No lock-ins.
          </p>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-7 text-left">
            {[
              { name: "IVR + Call Intelligence", price: "₹500", desc: "Transcription · QA scoring · Insights", popular: true },
              { name: "WhatsApp Communication", price: "₹200", desc: "Inbox · Templates · Guest auto-linking", popular: true },
              { name: "AI Concierge", price: "₹300", desc: "Auto-replies · Intent detection · Handoff", popular: false },
              { name: "CRM & Guest Pipeline", price: "₹150", desc: "Guest profiles · Inquiry tracking", popular: false },
              { name: "Instagram DM", price: "₹150", desc: "IG inquiries · Inbox · Guest linking", popular: false },
            ].map((m) => (
              <div
                key={m.name}
                className="rounded-2xl border p-5 transition-all"
                style={
                  m.popular
                    ? { backgroundColor: "rgba(200,150,74,0.08)", borderColor: "rgba(200,150,74,0.3)" }
                    : { backgroundColor: "rgba(240,232,208,0.03)", borderColor: "rgba(240,232,208,0.07)" }
                }
              >
                {m.popular && (
                  <div
                    className="text-[10px] font-bold uppercase tracking-widest mb-2"
                    style={{ color: "var(--mkt-gold)" }}
                  >
                    Popular
                  </div>
                )}
                <p
                  className="text-sm font-semibold mb-1"
                  style={{ color: m.popular ? "var(--mkt-text)" : "rgba(240,232,208,0.75)" }}
                >
                  {m.name}
                </p>
                <p
                  className="text-xs mb-3 leading-relaxed"
                  style={{ color: "rgba(240,232,208,0.35)" }}
                >
                  {m.desc}
                </p>
                <div className="flex items-end gap-1">
                  <span
                    className="font-display text-2xl font-light"
                    style={{ color: "var(--mkt-gold)" }}
                  >
                    {m.price}
                  </span>
                  <span
                    className="text-[11px] mb-0.5"
                    style={{ color: "rgba(240,232,208,0.28)" }}
                  >
                    / property / month
                  </span>
                </div>
              </div>
            ))}
            <div
              className="rounded-2xl border p-5 flex flex-col justify-center"
              style={{
                backgroundColor: "rgba(240,232,208,0.03)",
                borderColor: "rgba(240,232,208,0.07)",
              }}
            >
              <p className="text-sm font-semibold mb-1" style={{ color: "rgba(240,232,208,0.5)" }}>
                Minimum billing
              </p>
              <p className="font-display text-2xl font-light" style={{ color: "rgba(240,232,208,0.35)" }}>
                ₹2,500{" "}
                <span className="text-sm font-normal" style={{ fontFamily: "inherit" }}>
                  / month
                </span>
              </p>
              <p className="text-xs mt-2" style={{ color: "rgba(240,232,208,0.22)" }}>
                Scales with your portfolio
              </p>
            </div>
          </div>

          <Link
            href="/pricing"
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-bold transition-colors mb-5"
            style={{ backgroundColor: "var(--mkt-gold)", color: "var(--mkt-bg)" }}
          >
            Calculate your price <ChevronRight size={15} />
          </Link>
          <p className="text-xs" style={{ color: "rgba(240,232,208,0.22)" }}>
            GST (18%) applicable · Annual plans at 20% discount · No credit card to start
          </p>
        </div>
      </section>

      {/* ──────────────────────────────────────────────────────────────────── */}
      {/* FINAL CTA                                                            */}
      {/* ──────────────────────────────────────────────────────────────────── */}
      <section className="py-28 px-5 sm:px-8 relative overflow-hidden">
        {/* Gold radial glow */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse 70% 60% at 50% 50%, rgba(200,150,74,0.07) 0%, transparent 70%)",
          }}
        />
        {/* Top border line */}
        <div
          className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-px"
          style={{
            background: "linear-gradient(90deg, transparent, rgba(200,150,74,0.5), transparent)",
          }}
        />

        <div className="max-w-3xl mx-auto text-center relative">
          <div
            className="w-14 h-14 rounded-2xl border flex items-center justify-center mx-auto mb-8"
            style={{
              backgroundColor: "rgba(200,150,74,0.1)",
              borderColor: "rgba(200,150,74,0.25)",
            }}
          >
            <Sparkles size={24} style={{ color: "var(--mkt-gold)" }} />
          </div>
          <h2
            className="font-display leading-[1.0] tracking-tight mb-5"
            style={{ fontSize: "clamp(40px, 6vw, 68px)", fontWeight: 400 }}
          >
            Ready to transform your
            <br />
            <em className="font-display italic" style={{ color: "var(--mkt-gold)", fontWeight: 600 }}>
              guest communications?
            </em>
          </h2>
          <p
            className="text-base leading-relaxed mb-12"
            style={{ color: "rgba(240,232,208,0.45)" }}
          >
            Join hospitality teams across India who use HAIP to deliver extraordinary
            guest experiences.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/register"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all hover:-translate-y-0.5"
              style={{
                backgroundColor: "var(--mkt-gold)",
                color: "var(--mkt-bg)",
                boxShadow: "0 8px 32px rgba(200,150,74,0.28)",
              }}
            >
              Start 14-day free trial <ArrowRight size={18} />
            </Link>
            <Link
              href="/register?demo=1"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-semibold text-base transition-all"
              style={{
                border: "1px solid rgba(240,232,208,0.15)",
                color: "rgba(240,232,208,0.7)",
              }}
            >
              <Globe size={18} />
              Book a demo
            </Link>
          </div>
          <p className="text-xs mt-7" style={{ color: "rgba(240,232,208,0.2)" }}>
            No credit card required · Setup in under 10 minutes · Cancel anytime
          </p>
        </div>
      </section>

      <MarketingFooter />
    </div>
  );
}
