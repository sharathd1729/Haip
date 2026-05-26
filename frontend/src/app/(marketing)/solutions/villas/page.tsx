import Link from "next/link";
import {
  ArrowRight, CheckCircle2, MessageSquare, Phone, Inbox, Sparkles,
  Building2, Users, Star, BarChart2, Clock, TrendingUp, Shield, ChevronRight,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------
const painPoints = [
  {
    icon: <MessageSquare size={18} className="text-rose-400" />,
    title: "Guests message on 5 different channels",
    desc: "WhatsApp, Instagram DMs, calls, OTA inboxes, email — your reservations team juggles 6 tabs before they reply.",
  },
  {
    icon: <Phone size={18} className="text-rose-400" />,
    title: "Calls go unanswered or unreviewed",
    desc: "High-intent inquiry calls drop. The few that connect are never reviewed for missed upsells or quality.",
  },
  {
    icon: <Users size={18} className="text-rose-400" />,
    title: "No single source of truth for guests",
    desc: "Repeat guests get treated like strangers. Preferences, past stays and special requests live in someone's WhatsApp.",
  },
  {
    icon: <BarChart2 size={18} className="text-rose-400" />,
    title: "No visibility into what's working",
    desc: "Which channels drive bookings? Which agents close best? Which villas convert? Nobody knows — it's all in heads.",
  },
];

const useCases = [
  {
    icon: <Inbox size={20} />, color: "text-teal-400",
    title: "One inbox for every villa enquiry",
    desc: "Direct WhatsApp, Instagram DMs, phone enquiries and form submissions — all unified per guest. Assign by villa, by team, or by language.",
  },
  {
    icon: <Sparkles size={20} />, color: "text-cyan-400",
    title: "AI concierge replies in seconds",
    desc: "HAIP drafts contextual replies trained on your villa inventory, pricing rules, and tone — your team approves with one tap.",
  },
  {
    icon: <Phone size={20} />, color: "text-purple-400",
    title: "Every inquiry call analyzed",
    desc: "Auto-transcribed, sentiment-scored, QA-graded. Surfaces missed upsells (private chef, airport pickup, spa add-ons) automatically.",
  },
  {
    icon: <Building2 size={20} />, color: "text-amber-400",
    title: "Multi-villa pipeline",
    desc: "Inquiry Kanban broken down by villa with rate-card awareness, availability checks, and one-tap quote generation.",
  },
  {
    icon: <Star size={20} />, color: "text-yellow-400",
    title: "Guest profiles that remember",
    desc: "Stay history, dietary preferences, anniversaries, past complaints — surfaced the second a guest pings you again.",
  },
  {
    icon: <Shield size={20} />, color: "text-green-400",
    title: "DPDP-compliant by default",
    desc: "Indian-hosted data, consent capture for marketing, encrypted call recordings, role-based access for finance and ops.",
  },
];

const workflows = [
  {
    step: "01",
    title: "Capture",
    desc: "Guest pings on WhatsApp, calls your IVR, or DMs your Instagram — HAIP routes everything into one unified inbox.",
  },
  {
    step: "02",
    title: "Qualify",
    desc: "AI tags the inquiry (dates, party size, villa preference, source), enriches with past stays, and surfaces matched availability.",
  },
  {
    step: "03",
    title: "Quote & convert",
    desc: "Send rate cards, brochures, and payment links from inside the conversation. Track quote-to-booking conversion per agent.",
  },
  {
    step: "04",
    title: "Onboard the stay",
    desc: "Automated pre-arrival sequences, dietary collection, transport coordination — all on WhatsApp, all logged.",
  },
  {
    step: "05",
    title: "Learn & improve",
    desc: "Weekly AI digest: missed revenue, top objections, agent QA, channel ROI. Coach your team with real data.",
  },
];

const stats = [
  { value: "3.2×", label: "Faster guest response" },
  { value: "+22%", label: "Inquiry-to-booking conversion" },
  { value: "₹2.4L", label: "Avg. monthly upsell recovered" },
  { value: "100%", label: "Calls auto-reviewed" },
];

const faqs = [
  {
    q: "Do you work with a single-villa owner or only with groups?",
    a: "Both. Our Starter plan is built for single-property owners and unlocks the full unified inbox + AI call intelligence. Most villa groups land on the Growth plan once they cross 3 properties.",
  },
  {
    q: "Can HAIP work alongside our existing PMS (Hostaway, eZee, Cloudbeds)?",
    a: "Yes. HAIP is the communication & intelligence layer, not a replacement for your PMS. We sync bookings and guest data — Hostaway is live, others are on the roadmap.",
  },
  {
    q: "How do guests message us on WhatsApp officially?",
    a: "HAIP gives you a verified WhatsApp Business number via the official Meta Cloud API. Embedded signup means you're live in under 20 minutes — no developer or BSP middleman needed.",
  },
  {
    q: "What about our existing phone numbers and IVR?",
    a: "We integrate with CallerDesk, Acefone, Servetel and MCube. Your numbers and IVR stay the same — HAIP just adds transcription, scoring and inbox sync on top.",
  },
  {
    q: "Is guest data stored in India?",
    a: "Yes. Primary data, call recordings and message archives are stored in AWS Mumbai (ap-south-1). HAIP is DPDP-Act ready with consent capture, data subject rights workflows, and retention controls.",
  },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function VillasSolutionPage() {
  return (
    <div className="bg-[var(--mkt-bg)] text-white min-h-screen">
      {/* ------------------------------------------------------------------ */}
      {/* HERO                                                                */}
      {/* ------------------------------------------------------------------ */}
      <section className="relative pt-32 pb-20 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[500px] rounded-full bg-teal-500/8 blur-[120px]" />
          <div className="absolute inset-0 opacity-[0.03]"
            style={{ backgroundImage: "radial-gradient(circle, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
        </div>

        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 grid lg:grid-cols-12 gap-12 items-center">
          <div className="lg:col-span-7">
            <div className="inline-flex items-center gap-2 bg-teal-500/10 border border-teal-500/20 rounded-full px-4 py-1.5 mb-6">
              <Building2 size={12} className="text-teal-400" />
              <span className="text-xs font-semibold text-teal-300 uppercase tracking-wider">For luxury villas</span>
            </div>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight leading-[1.05] mb-6">
              Every villa enquiry,
              <br />
              <span className="bg-gradient-to-r from-teal-400 via-cyan-300 to-teal-400 bg-clip-text text-transparent">
                converted with intelligence.
              </span>
            </h1>
            <p className="text-lg text-white/55 max-w-xl mb-8 leading-relaxed">
              HAIP is the AI-first communication platform for villa operators. Unified WhatsApp + Calls + Instagram, AI-drafted replies trained on your inventory, and a hospitality CRM that remembers every guest.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 mb-6">
              <Link href="/register?plan=growth&segment=villas"
                className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-[#C8964A] hover:bg-[#D4A85A] text-[#0E1210] font-bold rounded-2xl transition-all shadow-2xl shadow-teal-500/30 hover:-translate-y-0.5">
                Start 14-day free trial <ArrowRight size={16} />
              </Link>
              <Link href="/book-demo?segment=villas"
                className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">
                Book a 30-min demo
              </Link>
            </div>
            <p className="text-xs text-white/30">No credit card · Live in under 20 minutes · DPDP-ready</p>
          </div>

          {/* Hero visual: villa enquiry card */}
          <div className="lg:col-span-5">
            <div className="relative">
              <div className="absolute -inset-4 bg-gradient-to-br from-teal-500/20 to-cyan-500/10 rounded-3xl blur-2xl" />
              <div className="relative bg-[var(--mkt-panel)] rounded-2xl border border-white/10 p-5 shadow-2xl shadow-black/40">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <div className="w-9 h-9 rounded-full bg-green-500/20 flex items-center justify-center">
                      <MessageSquare size={14} className="text-green-400" />
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-white">Priya Sharma</p>
                      <p className="text-[10px] text-white/40">WhatsApp · New enquiry</p>
                    </div>
                  </div>
                  <span className="text-[10px] px-2 py-1 rounded-md bg-teal-500/20 text-teal-300 font-semibold">High intent</span>
                </div>
                <div className="space-y-2 mb-4">
                  <div className="bg-white/6 rounded-2xl rounded-tl-sm px-3 py-2 max-w-[85%]">
                    <p className="text-xs text-white/75 leading-relaxed">Hi! Looking for a 4BR villa in North Goa for Dec 24-28, family of 8 with 2 kids. Budget around ₹1.2L/night. Need private chef and pool heating.</p>
                  </div>
                  <div className="bg-teal-500/15 rounded-2xl rounded-tr-sm px-3 py-2 max-w-[85%] ml-auto">
                    <p className="text-xs text-white/85 leading-relaxed">Hi Priya! 🌊 Sunset Villa (4BR, private pool, sea view) is available for those dates at ₹1.1L/night. Private chef and heated pool both included. Sending the brochure now.</p>
                  </div>
                </div>
                <div className="bg-teal-500/8 border border-teal-500/20 rounded-xl p-3 space-y-2">
                  <div className="flex items-start gap-2">
                    <Sparkles size={12} className="text-teal-400 flex-shrink-0 mt-0.5" />
                    <p className="text-[11px] text-teal-300 leading-relaxed font-medium">AI auto-tagged: <span className="font-semibold">Dec 24–28 · 4BR · Goa · Family · ₹1.2L budget</span></p>
                  </div>
                  <div className="flex items-start gap-2">
                    <TrendingUp size={12} className="text-amber-400 flex-shrink-0 mt-0.5" />
                    <p className="text-[11px] text-amber-300 leading-relaxed">Upsell opportunity flagged: airport pickup, spa, photographer</p>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2">
                  <button className="bg-white/5 rounded-lg py-2 text-[11px] text-white/60 font-medium hover:bg-white/10">Send quote</button>
                  <button className="bg-white/5 rounded-lg py-2 text-[11px] text-white/60 font-medium hover:bg-white/10">Block dates</button>
                  <button className="bg-teal-500 rounded-lg py-2 text-[11px] text-white font-semibold">Approve reply</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* STATS                                                               */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-14 border-y border-white/6 bg-gradient-to-r from-[var(--mkt-bg)] to-[var(--mkt-panel)]">
        <div className="max-w-5xl mx-auto px-5 sm:px-8 grid grid-cols-2 md:grid-cols-4 gap-8">
          {stats.map(s => (
            <div key={s.label} className="text-center">
              <div className="text-3xl sm:text-4xl font-black text-teal-400 mb-1">{s.value}</div>
              <div className="text-xs text-white/40">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* PAIN POINTS                                                         */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-bold text-rose-400 uppercase tracking-widest mb-3">The villa operator&apos;s reality</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">Running villas shouldn&apos;t feel like running a call center</h2>
            <p className="text-white/45 max-w-xl mx-auto">Most villa businesses lose 20-30% of inbound revenue not because guests don&apos;t want to book — but because operations can&apos;t keep up.</p>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            {painPoints.map(p => (
              <div key={p.title} className="bg-[var(--mkt-panel)]/60 border border-white/6 rounded-2xl p-6 hover:border-rose-500/20 transition-colors">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-xl bg-rose-500/10 flex items-center justify-center flex-shrink-0">{p.icon}</div>
                  <div>
                    <h3 className="text-base font-bold text-white mb-1.5">{p.title}</h3>
                    <p className="text-sm text-white/45 leading-relaxed">{p.desc}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* USE CASES                                                           */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8 bg-[#0E1210]">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-bold text-[#3D9E7E] uppercase tracking-widest mb-3">How HAIP works for villas</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">Six things your team will stop doing manually</h2>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {useCases.map(u => (
              <div key={u.title} className="bg-[var(--mkt-panel)] border border-white/8 rounded-2xl p-6 hover:border-teal-500/30 transition-all hover:-translate-y-0.5">
                <div className={`w-11 h-11 rounded-xl bg-white/5 flex items-center justify-center mb-4 ${u.color}`}>
                  {u.icon}
                </div>
                <h3 className="text-base font-bold text-white mb-2">{u.title}</h3>
                <p className="text-sm text-white/45 leading-relaxed">{u.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* WORKFLOW                                                            */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-bold text-[#3D9E7E] uppercase tracking-widest mb-3">The villa workflow, automated</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">From first ping to fifth-star review</h2>
          </div>
          <div className="space-y-3">
            {workflows.map((w, i) => (
              <div key={w.step} className="flex gap-5 items-start bg-[var(--mkt-panel)]/50 border border-white/6 rounded-2xl p-6 hover:border-teal-500/20 transition-colors">
                <div className="flex-shrink-0 w-12 h-12 rounded-xl bg-teal-500/15 border border-teal-500/30 flex items-center justify-center">
                  <span className="text-teal-400 font-black text-sm">{w.step}</span>
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-bold text-white mb-1.5">{w.title}</h3>
                  <p className="text-sm text-white/55 leading-relaxed">{w.desc}</p>
                </div>
                {i < workflows.length - 1 && <Clock size={16} className="text-white/15 mt-4 hidden sm:block" />}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* TESTIMONIAL                                                         */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8 bg-[#0E1210]">
        <div className="max-w-4xl mx-auto bg-gradient-to-br from-[var(--mkt-panel)] to-[#0E1210] border border-white/10 rounded-3xl p-10 sm:p-14">
          <div className="flex gap-1 mb-6">
            {[...Array(5)].map((_, i) => <span key={i} className="text-teal-400">★</span>)}
          </div>
          <p className="text-xl sm:text-2xl text-white/80 leading-relaxed font-medium mb-8">
            &ldquo;We run 11 villas across Goa and Coorg. Before HAIP, my reservations team was missing 30% of WhatsApp enquiries during peak hours. Now every enquiry is captured, auto-qualified, and quote-ready in under 4 minutes. Revenue is up 27% YoY and my team is calmer.&rdquo;
          </p>
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-teal-500 flex items-center justify-center text-base font-bold text-white">VR</div>
            <div>
              <div className="text-base font-bold text-white">Vikrant Rao</div>
              <div className="text-sm text-white/40">Founder, Ananta Villa Collection</div>
            </div>
            <Link href="/case-studies/ananta" className="ml-auto text-xs text-teal-400 hover:text-teal-300 font-semibold inline-flex items-center gap-1">
              Read case study <ChevronRight size={12} />
            </Link>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* FAQ                                                                 */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-xs font-bold text-[#3D9E7E] uppercase tracking-widest mb-3">FAQ</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight">Villa-specific questions</h2>
          </div>
          <div className="space-y-3">
            {faqs.map(f => (
              <details key={f.q} className="group bg-[var(--mkt-panel)]/60 border border-white/8 rounded-2xl px-6 py-5 hover:border-teal-500/30 transition-colors">
                <summary className="flex items-center justify-between cursor-pointer list-none">
                  <h3 className="text-base font-semibold text-white pr-4">{f.q}</h3>
                  <ChevronRight size={18} className="text-teal-400 group-open:rotate-90 transition-transform flex-shrink-0" />
                </summary>
                <p className="mt-4 text-sm text-white/55 leading-relaxed">{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* FINAL CTA                                                           */}
      {/* ------------------------------------------------------------------ */}
      <section className="py-24 px-5 sm:px-8 bg-[#0E1210] relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-teal-500/10 via-transparent to-cyan-500/5 pointer-events-none" />
        <div className="max-w-3xl mx-auto text-center relative">
          <div className="w-16 h-16 rounded-2xl bg-teal-500/20 border border-teal-500/30 flex items-center justify-center mx-auto mb-6">
            <Building2 size={28} className="text-teal-400" />
          </div>
          <h2 className="text-3xl sm:text-5xl font-black tracking-tight mb-4">
            Run your villas like a luxury brand
          </h2>
          <p className="text-white/50 text-lg mb-10 max-w-xl mx-auto">
            Join villa operators across India who use HAIP to capture every enquiry, convert more bookings, and remember every guest.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/register?plan=growth&segment=villas"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-[#C8964A] hover:bg-[#D4A85A] text-[#0E1210] font-bold rounded-2xl transition-all shadow-2xl shadow-teal-500/30 hover:-translate-y-0.5">
              Start 14-day free trial <ArrowRight size={18} />
            </Link>
            <Link href="/book-demo?segment=villas"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">
              Talk to sales
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

export const metadata = {
  title: "HAIP for Luxury Villas — Unified inbox, AI calls, hospitality CRM",
  description: "The AI-first communication platform for villa operators in India. WhatsApp, Instagram and call intelligence, with a CRM that remembers every guest.",
};
