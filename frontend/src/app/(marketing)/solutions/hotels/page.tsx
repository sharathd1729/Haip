import Link from "next/link";
import {
  ArrowRight, MessageSquare, Phone, Inbox, Sparkles,
  Hotel, Users, Star, BarChart2, TrendingUp, Shield, ChevronRight, CheckCircle2,
} from "lucide-react";

const painPoints = [
  {
    icon: <MessageSquare size={18} className="text-rose-400" />,
    title: "OTA inboxes, WhatsApp and front-desk calls live in 4 different places",
    desc: "Reservations switches between Booking.com extranet, Airbnb messages, WhatsApp Web, and the phone — losing context every hop.",
  },
  {
    icon: <Phone size={18} className="text-rose-400" />,
    title: "After-hours calls get missed or mis-handled",
    desc: "Late-night room enquiries go to voicemail. The next morning nobody knows what was asked or whether it was followed up.",
  },
  {
    icon: <BarChart2 size={18} className="text-rose-400" />,
    title: "Direct vs OTA mix is invisible",
    desc: "You suspect OTA commissions are eating you alive — but you can't prove how many direct enquiries you actually convert.",
  },
  {
    icon: <Users size={18} className="text-rose-400" />,
    title: "Returning guests get treated like first-timers",
    desc: "No central guest record. Repeat business depends entirely on which staff happens to be on shift.",
  },
];

const features = [
  { icon: <Inbox size={20} />, color: "text-teal-400", title: "Unified inbox for every channel", desc: "WhatsApp, Instagram, IVR calls, and direct web enquiries — one inbox, one timeline per guest, with auto-routing by language and shift." },
  { icon: <Sparkles size={20} />, color: "text-cyan-400", title: "24/7 AI Concierge", desc: "Drafts replies on WhatsApp & web chat using your room types, packages, F&B menus and house rules. Shadow mode for the first 30 days, then autonomous on high-confidence enquiries." },
  { icon: <Phone size={20} />, color: "text-purple-400", title: "Every front-desk call auto-reviewed", desc: "Calls forward to your reservations team's mobile via CallerDesk or Acefone. HAIP pulls the recording, transcribes it, and scores it on your QA rubric — 100% coverage, no manual sampling." },
  { icon: <Hotel size={20} />, color: "text-amber-400", title: "Multi-property awareness", desc: "Per-property phone numbers, per-property AI knowledge bases, per-property FOH staff scoping. Role-based access so Property A's team only sees Property A." },
  { icon: <TrendingUp size={20} />, color: "text-yellow-400", title: "Direct vs OTA visibility", desc: "Source attribution from first touch through booking. See exactly how much commission you save by closing direct, and which channels actually pay back." },
  { icon: <Shield size={20} />, color: "text-green-400", title: "DPDP-ready compliance", desc: "Per-tenant KMS keys, hash-chained audit log, consent capture in the IVR greeting, recording retention controls. Audit-ready from day one." },
];

const stats = [
  { value: "<5min", label: "p95 first response (24/7)" },
  { value: "+15pp", label: "Direct booking share" },
  { value: "100%", label: "Call QA coverage" },
  { value: "₹0", label: "Per-call HAIP cost (cost mode)" },
];

const faqs = [
  { q: "Do we have to switch our PMS to use HAIP?", a: "No. HAIP is the communication and intelligence layer that sits beside your PMS. Hostaway is the live integration today — Guesty, eZee and Cloudbeds are on the roadmap. Until then, HAIP works standalone or via webhook." },
  { q: "What telephony provider do you support?", a: "CallerDesk for low-volume / founder-led properties and Acefone for multi-property hotel groups with predictable call volume. Both are BYOC — you keep your own telephony account and pay them directly. We're adapter-agnostic; Exotel and Twilio are on the roadmap." },
  { q: "How does the AI Concierge avoid making things up?", a: "It's grounded in a per-property knowledge base you control (room types, package rules, rate cards, house rules). For the first 30 days every reply is human-approved (shadow mode); after that, only replies above 0.78 confidence go autonomous, everything else queues for review." },
  { q: "Can we limit access by property?", a: "Yes. FOH staff at Property A can be scoped so they never see Property B's data. Compliance and Owner roles see the whole portfolio." },
  { q: "What about OTA messaging (Booking.com, Airbnb)?", a: "OTA inbox sync via Hostaway is in beta. Direct Booking.com / Airbnb adapters are on the H2 2026 roadmap." },
];

export default function HotelsSolutionPage() {
  return (
    <div className="bg-[#0B1F3A] text-white min-h-screen">
      {/* HERO */}
      <section className="relative pt-32 pb-20 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[500px] rounded-full bg-amber-500/8 blur-[120px]" />
          <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "radial-gradient(circle, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
        </div>
        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 grid lg:grid-cols-12 gap-12 items-center">
          <div className="lg:col-span-7">
            <div className="inline-flex items-center gap-2 bg-amber-500/10 border border-amber-500/20 rounded-full px-4 py-1.5 mb-6">
              <Hotel size={12} className="text-amber-400" />
              <span className="text-xs font-semibold text-amber-300 uppercase tracking-wider">For boutique hotels</span>
            </div>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight leading-[1.05] mb-6">
              Front-desk excellence,
              <br />
              <span className="bg-gradient-to-r from-amber-300 via-teal-300 to-teal-400 bg-clip-text text-transparent">running on autopilot.</span>
            </h1>
            <p className="text-lg text-white/55 max-w-xl mb-8 leading-relaxed">
              HAIP is the unified inbox and AI concierge for boutique hotels in India. Capture every enquiry across WhatsApp, IG and calls — convert them direct, recover OTA commissions, and remember every guest who walks through your door.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 mb-6">
              <Link href="/register?plan=growth&segment=hotels" className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-teal-500 hover:bg-teal-400 text-white font-bold rounded-2xl transition-all shadow-2xl shadow-teal-500/30 hover:-translate-y-0.5">Start 14-day free trial <ArrowRight size={16} /></Link>
              <Link href="/book-demo?segment=hotels" className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">Book a 30-min demo</Link>
            </div>
            <p className="text-xs text-white/30">BYOC telephony · Works with your existing PMS · Indian-hosted</p>
          </div>

          {/* Hero visual: OTA-vs-direct mix card */}
          <div className="lg:col-span-5">
            <div className="relative">
              <div className="absolute -inset-4 bg-gradient-to-br from-amber-500/20 to-teal-500/10 rounded-3xl blur-2xl" />
              <div className="relative bg-[#0f2744] rounded-2xl border border-white/10 p-5 shadow-2xl shadow-black/40">
                <div className="flex items-center justify-between mb-4">
                  <p className="text-xs font-semibold text-white/40 uppercase tracking-wider">Booking mix · Last 30 days</p>
                  <span className="text-[10px] px-2 py-1 rounded-md bg-teal-500/20 text-teal-300 font-semibold">+14% direct</span>
                </div>
                <div className="space-y-3 mb-4">
                  {[
                    { name: "Direct (HAIP inbox)", pct: 58, color: "bg-teal-500", count: "84 bookings" },
                    { name: "Booking.com", pct: 22, color: "bg-blue-500", count: "32 bookings · ₹84K commission" },
                    { name: "Airbnb", pct: 14, color: "bg-rose-500", count: "20 bookings · ₹56K commission" },
                    { name: "Walk-in / other", pct: 6, color: "bg-white/30", count: "9 bookings" },
                  ].map(row => (
                    <div key={row.name}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-white/80 font-medium">{row.name}</span>
                        <span className="text-xs text-white/40">{row.pct}%</span>
                      </div>
                      <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                        <div className={`h-full ${row.color} rounded-full`} style={{ width: `${row.pct}%` }} />
                      </div>
                      <p className="text-[10px] text-white/30 mt-1">{row.count}</p>
                    </div>
                  ))}
                </div>
                <div className="bg-teal-500/10 border border-teal-500/20 rounded-xl p-3 flex items-start gap-2">
                  <TrendingUp size={14} className="text-teal-400 flex-shrink-0 mt-0.5" />
                  <p className="text-[11px] text-teal-200 leading-relaxed"><span className="font-bold">₹1.4L saved this month</span> by closing direct via the unified inbox instead of OTAs.</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* STATS */}
      <section className="py-14 border-y border-white/6 bg-gradient-to-r from-[#0a1b30] to-[#0f2744]">
        <div className="max-w-5xl mx-auto px-5 sm:px-8 grid grid-cols-2 md:grid-cols-4 gap-8">
          {stats.map(s => (
            <div key={s.label} className="text-center">
              <div className="text-3xl sm:text-4xl font-black text-amber-400 mb-1">{s.value}</div>
              <div className="text-xs text-white/40">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* PAIN POINTS */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-bold text-rose-400 uppercase tracking-widest mb-3">Front-desk reality</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">You shouldn&apos;t need 4 tabs to take a reservation</h2>
            <p className="text-white/45 max-w-xl mx-auto">Boutique hotels lose enquiries between tools, between shifts, and between channels. HAIP collapses all of it into one shift-proof workspace.</p>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            {painPoints.map(p => (
              <div key={p.title} className="bg-[#0f2744]/60 border border-white/6 rounded-2xl p-6 hover:border-rose-500/20 transition-colors">
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

      {/* FEATURES */}
      <section className="py-24 px-5 sm:px-8 bg-[#0a1b30]">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-bold text-amber-400 uppercase tracking-widest mb-3">Built for boutique hotels</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">Six things HAIP automates for your front desk</h2>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {features.map(f => (
              <div key={f.title} className="bg-[#0f2744] border border-white/8 rounded-2xl p-6 hover:border-amber-500/30 transition-all hover:-translate-y-0.5">
                <div className={`w-11 h-11 rounded-xl bg-white/5 flex items-center justify-center mb-4 ${f.color}`}>{f.icon}</div>
                <h3 className="text-base font-bold text-white mb-2">{f.title}</h3>
                <p className="text-sm text-white/45 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* TELEPHONY EXPLAINER */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto grid lg:grid-cols-2 gap-12 items-center">
          <div>
            <div className="inline-flex items-center gap-2 bg-purple-500/10 border border-purple-500/20 rounded-full px-3 py-1.5 mb-6">
              <Phone size={12} className="text-purple-400" />
              <span className="text-xs font-semibold text-purple-300">How calling actually works</span>
            </div>
            <h2 className="text-3xl font-black tracking-tight mb-4 leading-tight">Your team takes calls on their phone. HAIP makes them 10× smarter.</h2>
            <p className="text-white/55 text-base leading-relaxed mb-6">
              We don&apos;t replace your phone system. Your hotel keeps its CallerDesk or Acefone number. Calls forward to the on-duty reservations agent&apos;s personal mobile — exactly like today. The moment the call ends, HAIP processes the recording asynchronously and posts a wrap-up card to the agent&apos;s cockpit within 90 seconds: AI summary, disposition picker, suggested follow-up.
            </p>
            <ul className="space-y-3 mb-2">
              {[
                "Recording consent captured in the IVR greeting",
                "AI transcription with Indian-English accuracy (Whisper + Deepgram)",
                "Auto QA-scored against your rubric — 100% coverage",
                "Click-to-call from any guest record for outbound",
                "No SIP, no headsets, no in-app dialler to learn",
              ].map(item => (
                <li key={item} className="flex items-start gap-3 text-sm text-white/60">
                  <CheckCircle2 size={16} className="text-amber-400 flex-shrink-0 mt-0.5" /> {item}
                </li>
              ))}
            </ul>
          </div>
          <div className="bg-[#0f2744] rounded-2xl border border-white/10 p-6 shadow-2xl shadow-black/40">
            <div className="space-y-3">
              {[
                { step: "Guest dials", detail: "Calls your published CallerDesk/Acefone number", color: "bg-blue-500/15 text-blue-300" },
                { step: "IVR greets + consent", detail: "Plays brand greeting, captures recording consent", color: "bg-purple-500/15 text-purple-300" },
                { step: "Forward to agent mobile", detail: "Round-robin or sticky to on-duty reservations staff", color: "bg-amber-500/15 text-amber-300" },
                { step: "Normal phone conversation", detail: "Agent takes the call on their own phone, no app", color: "bg-white/5 text-white/60" },
                { step: "Webhook → HAIP", detail: "Recording pulled, transcribed, AI-judged, stored on S3", color: "bg-teal-500/15 text-teal-300" },
                { step: "Wrap-up in 90 sec", detail: "AI summary + disposition + next-action in cockpit", color: "bg-teal-500/15 text-teal-300" },
              ].map((s, i) => (
                <div key={s.step} className="flex items-start gap-3">
                  <div className={`w-7 h-7 rounded-lg ${s.color} flex items-center justify-center text-[11px] font-bold flex-shrink-0`}>{i + 1}</div>
                  <div className="flex-1 pt-0.5">
                    <p className="text-sm font-semibold text-white">{s.step}</p>
                    <p className="text-xs text-white/40">{s.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* TESTIMONIAL */}
      <section className="py-24 px-5 sm:px-8 bg-[#0a1b30]">
        <div className="max-w-4xl mx-auto bg-gradient-to-br from-[#0f2744] to-[#0a1f3a] border border-white/10 rounded-3xl p-10 sm:p-14">
          <div className="flex gap-1 mb-6">
            {[...Array(5)].map((_, i) => <span key={i} className="text-amber-400">★</span>)}
          </div>
          <p className="text-xl sm:text-2xl text-white/80 leading-relaxed font-medium mb-8">
            &ldquo;We used to lose 20-25 enquiries every weekend because the front desk simply could not keep up. HAIP&apos;s unified inbox + AI Concierge captures every single one of them now — and the QA scoring made our reservations team noticeably sharper on objections within 60 days.&rdquo;
          </p>
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-amber-500 flex items-center justify-center text-base font-bold text-white">PD</div>
            <div>
              <div className="text-base font-bold text-white">Priya Deshpande</div>
              <div className="text-sm text-white/40">GM, The Postcard Boutique Hotels</div>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-xs font-bold text-amber-400 uppercase tracking-widest mb-3">FAQ</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight">Boutique hotel questions</h2>
          </div>
          <div className="space-y-3">
            {faqs.map(f => (
              <details key={f.q} className="group bg-[#0f2744]/60 border border-white/8 rounded-2xl px-6 py-5 hover:border-amber-500/30 transition-colors">
                <summary className="flex items-center justify-between cursor-pointer list-none">
                  <h3 className="text-base font-semibold text-white pr-4">{f.q}</h3>
                  <ChevronRight size={18} className="text-amber-400 group-open:rotate-90 transition-transform flex-shrink-0" />
                </summary>
                <p className="mt-4 text-sm text-white/55 leading-relaxed">{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-5 sm:px-8 bg-[#0a1b30] relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-amber-500/10 via-transparent to-teal-500/5 pointer-events-none" />
        <div className="max-w-3xl mx-auto text-center relative">
          <div className="w-16 h-16 rounded-2xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center mx-auto mb-6">
            <Hotel size={28} className="text-amber-400" />
          </div>
          <h2 className="text-3xl sm:text-5xl font-black tracking-tight mb-4">Turn your front desk into your growth engine</h2>
          <p className="text-white/50 text-lg mb-10 max-w-xl mx-auto">14-day free trial · BYOC telephony · DPDP-compliant. Live in under 20 minutes.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/register?plan=growth&segment=hotels" className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-teal-500 hover:bg-teal-400 text-white font-bold rounded-2xl transition-all shadow-2xl shadow-teal-500/30 hover:-translate-y-0.5">Start free trial <ArrowRight size={18} /></Link>
            <Link href="/book-demo?segment=hotels" className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">Talk to sales</Link>
          </div>
        </div>
      </section>
    </div>
  );
}

export const metadata = {
  title: "HAIP for Boutique Hotels — Unified inbox + AI Concierge + Auto-QA",
  description: "Boutique hotels in India use HAIP to capture every enquiry across WhatsApp, IG and calls, recover OTA commissions, and remember every guest.",
};
