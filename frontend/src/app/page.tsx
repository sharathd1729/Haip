import Link from "next/link";
import { MarketingNav } from "@/components/marketing/MarketingNav";
import { MarketingFooter } from "@/components/marketing/MarketingFooter";
import {
  MessageSquare, Phone, Users, BarChart2, Star, Zap,
  Shield, CheckCircle2, ArrowRight, Globe, Inbox,
  TrendingUp, Sparkles, Building2, Clock, ChevronRight,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Feature grid data
// ---------------------------------------------------------------------------
const coreFeatures = [
  {
    icon: <Inbox size={22} className="text-teal-400" />,
    title: "Unified Inbox",
    desc: "WhatsApp, Instagram, and phone calls—all in one beautifully organised workspace. Never miss a guest message again.",
    highlight: "Omnichannel",
  },
  {
    icon: <Phone size={22} className="text-teal-400" />,
    title: "AI Call Intelligence",
    desc: "Auto-transcribe every call, detect sentiment, score agent performance, and surface missed revenue opportunities—automatically.",
    highlight: "AI-powered",
  },
  {
    icon: <Users size={22} className="text-teal-400" />,
    title: "Hospitality CRM",
    desc: "Guest profiles, property management, inquiry tracking and stay history—purpose-built for villa and resort operations.",
    highlight: "Purpose-built",
  },
  {
    icon: <MessageSquare size={22} className="text-teal-400" />,
    title: "WhatsApp Automation",
    desc: "Bulk campaigns, automated replies, and booking confirmations via WhatsApp Business API. No technical setup needed.",
    highlight: "Meta official",
  },
  {
    icon: <Star size={22} className="text-teal-400" />,
    title: "Auto QA & Compliance",
    desc: "Automated quality scoring for every interaction. DPDP-compliant call archiving with searchable transcripts.",
    highlight: "DPDP-ready",
  },
  {
    icon: <BarChart2 size={22} className="text-teal-400" />,
    title: "AI Insights",
    desc: "Revenue forecasting, guest demand patterns, and competitive intelligence—surfaced automatically from your data.",
    highlight: "Predictive",
  },
];

const integrations = [
  { name: "WhatsApp Business", color: "bg-green-500/15 text-green-400 border-green-500/20" },
  { name: "Instagram", color: "bg-pink-500/15 text-pink-400 border-pink-500/20" },
  { name: "CallerDesk", color: "bg-blue-500/15 text-blue-400 border-blue-500/20" },
  { name: "Acefone", color: "bg-purple-500/15 text-purple-400 border-purple-500/20" },
  { name: "Hostaway", color: "bg-orange-500/15 text-orange-400 border-orange-500/20" },
  { name: "Servetel", color: "bg-cyan-500/15 text-cyan-400 border-cyan-500/20" },
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
    initials: "PR",
  },
  {
    quote: "The AI call analysis saved us hours every week. It scores every call automatically so I don't have to listen to recordings to review my team.",
    author: "Vikram S.",
    role: "General Manager",
    company: "Jade Resorts",
    initials: "VS",
  },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function HomePage() {
  return (
    <div className="bg-[#0B1F3A] text-white">
      <MarketingNav />

      {/* ------------------------------------------------------------------ */}
      {/* HERO                                                                */}
      {/* ------------------------------------------------------------------ */}
      <section className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden pt-16">
        {/* Background glow */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] h-[600px] rounded-full bg-teal-500/8 blur-[120px]" />
          <div className="absolute top-20 right-20 w-64 h-64 rounded-full bg-cyan-400/5 blur-[80px]" />
          <div className="absolute bottom-40 left-20 w-48 h-48 rounded-full bg-blue-500/5 blur-[60px]" />
          {/* Dot grid */}
          <div className="absolute inset-0 opacity-[0.03]"
            style={{ backgroundImage: "radial-gradient(circle, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }}
          />
        </div>

        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 py-24 lg:py-32 text-center">
          {/* Eyebrow */}
          <div className="inline-flex items-center gap-2 bg-teal-500/10 border border-teal-500/20 rounded-full px-4 py-1.5 mb-8">
            <Sparkles size={12} className="text-teal-400" />
            <span className="text-xs font-semibold text-teal-300 uppercase tracking-wider">Built for India&apos;s luxury hospitality sector</span>
          </div>

          {/* Headline */}
          <h1 className="text-4xl sm:text-5xl lg:text-7xl font-black tracking-tight leading-[1.05] mb-6 max-w-5xl mx-auto">
            The AI intelligence layer
            <br />
            <span className="bg-gradient-to-r from-teal-400 via-cyan-300 to-teal-400 bg-clip-text text-transparent">
              for luxury hospitality
            </span>
          </h1>

          {/* Subheadline */}
          <p className="text-lg sm:text-xl text-white/55 max-w-2xl mx-auto mb-10 leading-relaxed">
            Unified inbox for WhatsApp, calls, and DMs. AI-powered call analysis. Hospitality CRM.
            Everything your team needs to deliver extraordinary guest experiences — in one platform.
          </p>

          {/* CTAs */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16">
            <Link
              href="/register"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-teal-500 hover:bg-teal-400 text-white font-bold text-base rounded-2xl transition-all shadow-2xl shadow-teal-500/30 hover:shadow-teal-400/40 hover:-translate-y-0.5"
            >
              Start 14-day free trial <ArrowRight size={18} />
            </Link>
            <Link
              href="#demo"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-white/5 hover:bg-white/10 text-white font-semibold text-base rounded-2xl border border-white/10 transition-all"
            >
              Watch demo
            </Link>
          </div>

          {/* Trust line */}
          <p className="text-xs text-white/25 mb-8">No credit card required · 14-day free trial · Cancel anytime</p>

          {/* Dashboard mockup */}
          <div className="relative max-w-5xl mx-auto">
            <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-[#0B1F3A] z-10 pointer-events-none" style={{ top: "60%" }} />
            <div className="bg-[#0f2744] rounded-2xl border border-white/10 shadow-2xl shadow-black/60 overflow-hidden">
              {/* Mock browser chrome */}
              <div className="flex items-center gap-2 px-4 py-3 bg-[#0a1f38] border-b border-white/5">
                <div className="flex gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-red-500/50" />
                  <div className="w-3 h-3 rounded-full bg-amber-500/50" />
                  <div className="w-3 h-3 rounded-full bg-green-500/50" />
                </div>
                <div className="flex-1 mx-4 bg-white/5 rounded-lg h-5 flex items-center px-3">
                  <span className="text-[10px] text-white/25 font-mono">app.haip.app/dashboard/inbox</span>
                </div>
              </div>
              {/* Mock inbox */}
              <div className="flex h-[340px] sm:h-[420px]">
                {/* Sidebar mock */}
                <div className="w-14 bg-[#0B1F3A] flex flex-col items-center py-4 gap-3 border-r border-white/5">
                  {["H", "✉", "📞", "👥", "📊"].map((icon, i) => (
                    <div key={i} className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs ${i === 0 ? "bg-teal-500 text-white" : "bg-white/5 text-white/30"}`}>
                      {icon}
                    </div>
                  ))}
                </div>
                {/* Conversation list */}
                <div className="w-64 border-r border-white/5 overflow-hidden hidden sm:block">
                  <div className="px-3 py-3 border-b border-white/5">
                    <div className="h-7 bg-white/5 rounded-lg" />
                  </div>
                  {[
                    { name: "Priya Sharma", msg: "Is the villa available for...", time: "2m", unread: true, color: "bg-green-500" },
                    { name: "Arjun Mehta", msg: "Confirm my reservation for...", time: "15m", unread: true, color: "bg-pink-500" },
                    { name: "Sunita K.", msg: "Thanks for the quick reply", time: "1h", unread: false, color: "bg-blue-500" },
                    { name: "Dev & Meera", msg: "Can we extend by 2 nights?", time: "2h", unread: false, color: "bg-purple-500" },
                    { name: "Vikram Singh", msg: "Amazing stay, 5 stars!", time: "3h", unread: false, color: "bg-orange-500" },
                  ].map((conv, i) => (
                    <div key={i} className={`flex items-center gap-3 px-3 py-2.5 border-b border-white/3 ${i === 0 ? "bg-teal-500/10" : "hover:bg-white/2"}`}>
                      <div className={`w-8 h-8 rounded-full ${conv.color} flex-shrink-0 flex items-center justify-center text-xs font-bold text-white`}>
                        {conv.name[0]}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-white/80 truncate">{conv.name}</span>
                          <span className="text-[10px] text-white/30">{conv.time}</span>
                        </div>
                        <p className="text-[11px] text-white/40 truncate">{conv.msg}</p>
                      </div>
                      {conv.unread && <div className="w-2 h-2 rounded-full bg-teal-400 flex-shrink-0" />}
                    </div>
                  ))}
                </div>
                {/* Chat area */}
                <div className="flex-1 flex flex-col">
                  <div className="flex items-center gap-3 px-4 py-3 border-b border-white/5">
                    <div className="w-8 h-8 rounded-full bg-green-500 flex items-center justify-center text-xs font-bold">P</div>
                    <div>
                      <p className="text-xs font-semibold text-white/80">Priya Sharma</p>
                      <p className="text-[10px] text-white/30">via WhatsApp · Guest</p>
                    </div>
                    <div className="ml-auto flex gap-2">
                      <div className="px-2 py-1 bg-teal-500/20 text-teal-400 text-[10px] rounded-md">AI Suggest</div>
                      <div className="px-2 py-1 bg-white/5 text-white/40 text-[10px] rounded-md">Details</div>
                    </div>
                  </div>
                  <div className="flex-1 px-4 py-3 space-y-3 overflow-hidden">
                    <div className="flex justify-start">
                      <div className="bg-white/8 rounded-2xl rounded-tl-sm px-3 py-2 max-w-[70%]">
                        <p className="text-xs text-white/70">Hello! Is the Sunset Villa available for Dec 20-26? We&apos;re a family of 6.</p>
                      </div>
                    </div>
                    <div className="flex justify-end">
                      <div className="bg-teal-500/20 rounded-2xl rounded-tr-sm px-3 py-2 max-w-[70%]">
                        <p className="text-xs text-white/80">Hi Priya! Yes, Sunset Villa is available 🌅 It comfortably fits 8 guests. Shall I send the pricing details?</p>
                      </div>
                    </div>
                    <div className="flex justify-start">
                      <div className="bg-white/8 rounded-2xl rounded-tl-sm px-3 py-2 max-w-[70%]">
                        <p className="text-xs text-white/70">Yes please! And is there a chef service available?</p>
                      </div>
                    </div>
                    {/* AI suggestion */}
                    <div className="flex gap-2 items-start bg-teal-500/8 border border-teal-500/20 rounded-xl p-2.5">
                      <Sparkles size={12} className="text-teal-400 flex-shrink-0 mt-0.5" />
                      <p className="text-[11px] text-teal-300">AI: &ldquo;Yes, we offer a private chef service at ₹4,000/day. Our chef specialises in Goan cuisine. Would you like me to arrange?&rdquo;</p>
                    </div>
                  </div>
                  <div className="px-4 py-3 border-t border-white/5">
                    <div className="flex items-center gap-2 bg-white/5 rounded-xl px-3 py-2">
                      <span className="text-xs text-white/25 flex-1">Reply to Priya…</span>
                      <div className="w-6 h-6 rounded-lg bg-teal-500 flex items-center justify-center">
                        <ArrowRight size={11} className="text-white" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* STATS                                                               */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-16 border-y border-white/6 bg-gradient-to-r from-[#0a1b30] to-[#0f2744]">
        <div className="max-w-5xl mx-auto px-5 sm:px-8 grid grid-cols-2 md:grid-cols-4 gap-8">
          {stats.map(s => (
            <div key={s.value} className="text-center">
              <div className="text-3xl sm:text-4xl font-black text-teal-400 mb-1">{s.value}</div>
              <div className="text-xs text-white/40">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* FEATURES GRID                                                       */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8" id="features">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs font-bold text-teal-400 uppercase tracking-widest mb-3">Everything in one platform</p>
            <h2 className="text-3xl sm:text-5xl font-black tracking-tight mb-4">
              Built for how hospitality
              <br className="hidden sm:block" /> teams actually work
            </h2>
            <p className="text-white/45 text-lg max-w-xl mx-auto">
              No more juggling 6 different tools. HAIP brings your entire guest communication stack into one intelligent workspace.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {coreFeatures.map((f, i) => (
              <div key={i} className="group bg-[#0f2744]/60 hover:bg-[#0f2744] border border-white/6 hover:border-teal-500/30 rounded-2xl p-6 transition-all duration-300 hover:-translate-y-0.5">
                <div className="flex items-center justify-between mb-4">
                  <div className="w-10 h-10 rounded-xl bg-teal-500/10 flex items-center justify-center">
                    {f.icon}
                  </div>
                  <span className="text-[10px] font-bold text-teal-400/70 uppercase tracking-wider border border-teal-500/20 bg-teal-500/8 px-2 py-0.5 rounded-full">
                    {f.highlight}
                  </span>
                </div>
                <h3 className="text-lg font-bold text-white mb-2 group-hover:text-teal-400 transition-colors">{f.title}</h3>
                <p className="text-sm text-white/45 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* INTEGRATIONS                                                        */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-16 px-5 sm:px-8 bg-[#0a1b30]">
        <div className="max-w-4xl mx-auto text-center">
          <p className="text-xs font-bold text-white/30 uppercase tracking-widest mb-4">Works with your existing tools</p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            {integrations.map(int => (
              <div key={int.name} className={`px-4 py-2 rounded-xl border text-sm font-semibold ${int.color}`}>
                {int.name}
              </div>
            ))}
            <div className="px-4 py-2 rounded-xl border border-white/10 text-sm font-semibold text-white/30">
              + More coming
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* FEATURE SPOTLIGHT — Unified Inbox                                   */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-12 items-center">
          <div>
            <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-full px-3 py-1.5 mb-6">
              <MessageSquare size={12} className="text-green-400" />
              <span className="text-xs font-semibold text-green-300">Unified Inbox</span>
            </div>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4 leading-tight">
              One inbox for every
              <span className="text-teal-400"> guest touchpoint</span>
            </h2>
            <p className="text-white/50 text-lg mb-8 leading-relaxed">
              Your team switches between 4 apps to manage guest communications. HAIP combines WhatsApp, Instagram DMs, and phone calls in one clean workspace—with full conversation history for every guest.
            </p>
            <ul className="space-y-3 mb-8">
              {[
                "WhatsApp Business (official Meta Cloud API)",
                "Instagram DMs and mentions",
                "Phone calls with auto-transcription",
                "AI-suggested replies based on guest history",
                "Real-time team collaboration and handoffs",
              ].map((item, i) => (
                <li key={i} className="flex items-start gap-3 text-sm text-white/60">
                  <CheckCircle2 size={16} className="text-teal-400 flex-shrink-0 mt-0.5" />
                  {item}
                </li>
              ))}
            </ul>
            <Link href="/features#inbox" className="inline-flex items-center gap-2 text-teal-400 hover:text-teal-300 font-semibold text-sm transition-colors group">
              Explore Unified Inbox <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </div>
          {/* Visual */}
          <div className="bg-[#0f2744] rounded-2xl border border-white/10 p-4 shadow-2xl shadow-black/40">
            <div className="flex items-center gap-2 mb-4">
              <div className="text-xs text-white/30 font-semibold">INBOX</div>
              <div className="px-2 py-0.5 bg-teal-500 text-white text-[10px] font-bold rounded-full">12 new</div>
            </div>
            {[
              { channel: "WA", name: "Anjali Patel", msg: "Booking inquiry - Garden Suite", time: "now", tag: "Inquiry", dot: "bg-green-500" },
              { channel: "IG", name: "Rohit & Kavya", msg: "Anniversary package available?", time: "3m", tag: "Inquiry", dot: "bg-pink-500" },
              { channel: "📞", name: "+91 98765 43210", msg: "Call · 4m 32s · AI: Booking query", time: "8m", tag: "Resolved", dot: "bg-blue-500" },
              { channel: "WA", name: "Suresh Kumar", msg: "Check-out at 12 or 2 pm?", time: "15m", tag: "Guest", dot: "bg-green-500" },
            ].map((item, i) => (
              <div key={i} className="flex items-center gap-3 p-3 rounded-xl hover:bg-white/3 transition-colors border-b border-white/4 last:border-0">
                <div className={`w-9 h-9 rounded-full ${item.dot}/20 flex items-center justify-center text-xs font-bold text-white flex-shrink-0`}>
                  {item.channel}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-semibold text-white/80 truncate">{item.name}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-md font-medium ${item.tag === "Inquiry" ? "bg-teal-500/20 text-teal-400" : "bg-white/8 text-white/40"}`}>{item.tag}</span>
                  </div>
                  <p className="text-xs text-white/40 truncate">{item.msg}</p>
                </div>
                <span className="text-[10px] text-white/25 flex-shrink-0">{item.time}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* FEATURE SPOTLIGHT — AI Call Intelligence                           */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8 bg-[#0a1b30]">
        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-12 items-center">
          {/* Visual */}
          <div className="order-2 lg:order-1 bg-[#0f2744] rounded-2xl border border-white/10 p-5 shadow-2xl shadow-black/40">
            <div className="flex items-center justify-between mb-4">
              <span className="text-xs font-semibold text-white/30">CALL ANALYSIS — Anjali Sharma</span>
              <span className="text-xs text-white/25">Today, 11:24 AM · 8m 16s</span>
            </div>
            {/* Score cards */}
            <div className="grid grid-cols-3 gap-3 mb-4">
              {[
                { label: "QA Score", value: "87", icon: "⭐", color: "text-amber-400" },
                { label: "Sentiment", value: "😊 Positive", icon: "", color: "text-green-400" },
                { label: "Outcome", value: "Booked", icon: "✓", color: "text-teal-400" },
              ].map(card => (
                <div key={card.label} className="bg-white/4 rounded-xl p-3 text-center">
                  <div className={`text-lg font-black ${card.color} mb-0.5`}>{card.value}</div>
                  <div className="text-[10px] text-white/30">{card.label}</div>
                </div>
              ))}
            </div>
            {/* Transcript snippet */}
            <div className="bg-white/3 rounded-xl p-3 mb-3 space-y-2">
              <div className="flex gap-2">
                <span className="text-[10px] font-bold text-teal-400 flex-shrink-0">AGENT</span>
                <p className="text-xs text-white/60">Good morning! Thank you for calling Jade Resorts. How may I assist you today?</p>
              </div>
              <div className="flex gap-2">
                <span className="text-[10px] font-bold text-white/30 flex-shrink-0">GUEST</span>
                <p className="text-xs text-white/60">Hi, I&apos;d like to book the pool villa for New Year&apos;s week. What&apos;s available?</p>
              </div>
            </div>
            {/* AI flags */}
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                <TrendingUp size={11} className="text-amber-400" />
                <span className="text-xs text-amber-300">Missed upsell: Private chef not offered (₹8,000 opportunity)</span>
              </div>
              <div className="flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2">
                <CheckCircle2 size={11} className="text-green-400" />
                <span className="text-xs text-green-300">Agent handled pricing objection well — closing rate maintained</span>
              </div>
            </div>
          </div>

          <div className="order-1 lg:order-2">
            <div className="inline-flex items-center gap-2 bg-purple-500/10 border border-purple-500/20 rounded-full px-3 py-1.5 mb-6">
              <Phone size={12} className="text-purple-400" />
              <span className="text-xs font-semibold text-purple-300">AI Call Intelligence</span>
            </div>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4 leading-tight">
              Every call, automatically
              <span className="text-teal-400"> analyzed</span>
            </h2>
            <p className="text-white/50 text-lg mb-8 leading-relaxed">
              Stop manually reviewing call recordings. HAIP transcribes, scores, and extracts insights from 100% of your calls — surfacing missed revenue, agent coaching moments, and guest intent signals automatically.
            </p>
            <ul className="space-y-3 mb-8">
              {[
                "Auto-transcription via Whisper AI (Indian accent optimized)",
                "Agent QA scoring — no manual listening required",
                "Missed revenue opportunity detection",
                "Sentiment analysis per call",
                "Works with CallerDesk, Acefone, Servetel, MCube",
              ].map((item, i) => (
                <li key={i} className="flex items-start gap-3 text-sm text-white/60">
                  <CheckCircle2 size={16} className="text-teal-400 flex-shrink-0 mt-0.5" />
                  {item}
                </li>
              ))}
            </ul>
            <Link href="/features#calls" className="inline-flex items-center gap-2 text-teal-400 hover:text-teal-300 font-semibold text-sm transition-colors group">
              Explore AI Call Intelligence <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* TESTIMONIALS                                                        */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-5xl mx-auto text-center mb-12">
          <p className="text-xs font-bold text-teal-400 uppercase tracking-widest mb-3">Trusted by hospitality teams</p>
          <h2 className="text-3xl sm:text-4xl font-black tracking-tight">What our clients say</h2>
        </div>
        <div className="max-w-5xl mx-auto grid md:grid-cols-2 gap-6">
          {testimonials.map((t, i) => (
            <div key={i} className="bg-[#0f2744] border border-white/8 rounded-2xl p-8">
              <div className="flex gap-1 mb-5">
                {[...Array(5)].map((_, j) => <span key={j} className="text-teal-400 text-sm">★</span>)}
              </div>
              <p className="text-white/70 text-base leading-relaxed mb-6 italic">&ldquo;{t.quote}&rdquo;</p>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-teal-500 flex items-center justify-center text-sm font-bold text-white">
                  {t.initials}
                </div>
                <div>
                  <div className="text-sm font-bold text-white">{t.author}</div>
                  <div className="text-xs text-white/40">{t.role} · {t.company}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* PRICING PREVIEW                                                     */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8 bg-[#0a1b30]" id="pricing">
        <div className="max-w-3xl mx-auto text-center">
          <p className="text-xs font-bold text-teal-400 uppercase tracking-widest mb-3">Simple, transparent pricing</p>
          <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">
            Pay only for what you use
          </h2>
          <p className="text-white/45 text-lg mb-10">
            Pick the modules your property needs. Pay per property, per month.<br className="hidden sm:block" />
            No platform fees. No lock-ins.
          </p>

          {/* Module pricing cards */}
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-6 text-left">
            {[
              { name: "IVR + Call Intelligence", price: "₹500", desc: "Transcription · QA scoring · Insights", popular: true },
              { name: "WhatsApp Communication", price: "₹200", desc: "Inbox · Templates · Guest auto-linking", popular: true },
              { name: "AI Concierge", price: "₹300", desc: "Auto-replies · Intent detection · Handoff", popular: false },
              { name: "CRM & Guest Pipeline", price: "₹150", desc: "Guest profiles · Inquiry tracking", popular: false },
              { name: "Instagram DM", price: "₹150", desc: "IG inquiries · Inbox · Guest linking", popular: false },
            ].map(m => (
              <div key={m.name} className={`rounded-2xl border p-5 ${m.popular ? "bg-teal-500/10 border-teal-500/30" : "bg-white/4 border-white/8"}`}>
                {m.popular && <div className="text-[10px] font-bold text-teal-400 uppercase tracking-widest mb-2">Popular</div>}
                <p className={`text-sm font-bold mb-1 ${m.popular ? "text-white" : "text-white/80"}`}>{m.name}</p>
                <p className="text-xs text-white/35 mb-3 leading-relaxed">{m.desc}</p>
                <div className="flex items-end gap-1">
                  <span className="text-xl font-black text-teal-400">{m.price}</span>
                  <span className="text-[11px] text-white/30 mb-0.5">/ property / month</span>
                </div>
              </div>
            ))}
            {/* Minimum billing note */}
            <div className="rounded-2xl border border-white/8 bg-white/4 p-5 flex flex-col justify-center">
              <p className="text-sm font-bold text-white/60 mb-1">Minimum billing</p>
              <p className="text-xl font-black text-white/40">₹2,500 <span className="text-sm font-normal">/ month</span></p>
              <p className="text-xs text-white/25 mt-2">Scales with your portfolio</p>
            </div>
          </div>

          <Link href="/pricing" className="inline-flex items-center gap-2 px-6 py-3 bg-teal-500 hover:bg-teal-400 text-white text-sm font-bold rounded-2xl transition-colors shadow-lg shadow-teal-500/20 mb-4">
            Calculate your price <ChevronRight size={15} />
          </Link>
          <p className="text-xs text-white/25">GST (18%) applicable · Annual plans at 20% discount · No credit card to start</p>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* FINAL CTA                                                           */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8 relative overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute inset-0 bg-gradient-to-br from-teal-500/10 via-transparent to-cyan-500/5" />
        </div>
        <div className="max-w-3xl mx-auto text-center relative">
          <div className="w-16 h-16 rounded-2xl bg-teal-500/20 border border-teal-500/30 flex items-center justify-center mx-auto mb-6">
            <Sparkles size={28} className="text-teal-400" />
          </div>
          <h2 className="text-3xl sm:text-5xl font-black tracking-tight mb-4">
            Ready to transform your
            <br />guest communications?
          </h2>
          <p className="text-white/45 text-lg mb-10">
            Join hospitality teams across India who use HAIP to deliver extraordinary guest experiences.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/register"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-teal-500 hover:bg-teal-400 text-white font-bold text-base rounded-2xl transition-all shadow-2xl shadow-teal-500/30 hover:-translate-y-0.5"
            >
              Start 14-day free trial <ArrowRight size={18} />
            </Link>
            <Link
              href="/register?demo=1"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-white/5 hover:bg-white/10 text-white font-semibold text-base rounded-2xl border border-white/10 transition-all"
            >
              <Globe size={18} />
              Book a demo
            </Link>
          </div>
          <p className="text-xs text-white/20 mt-6">
            No credit card required · Setup in under 10 minutes · Cancel anytime
          </p>
        </div>
      </section>

      <MarketingFooter />
    </div>
  );
}
