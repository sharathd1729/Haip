import Link from "next/link";
import {
  ArrowRight, MessageSquare, Phone, Sparkles, Map, Compass,
  Users, BarChart2, TrendingUp, Shield, ChevronRight, CheckCircle2, Plane, Calendar, FileText,
} from "lucide-react";

const painPoints = [
  { icon: <MessageSquare size={18} className="text-rose-400" />, title: "Enquiry-to-quote takes 6+ hours on a good day", desc: "Trip designers manually pull itineraries, rates, transport options into a quote PDF. By the time you reply, the guest has booked elsewhere." },
  { icon: <Map size={18} className="text-rose-400" />, title: "Itinerary knowledge lives in someone's head", desc: "The founder knows the best stops. The new trip designer doesn't. Quality drops the moment volume scales past one person." },
  { icon: <Calendar size={18} className="text-rose-400" />, title: "Multi-day pre-trip engagement is ad hoc", desc: "Dietary preferences, special occasions, transport details — collected via 14 separate WhatsApp messages over 2 weeks. Half get missed." },
  { icon: <BarChart2 size={18} className="text-rose-400" />, title: "You can't tell which marketing actually works", desc: "Direct ~70%, referral ~25% — sure. But which campaigns? Which keywords? Which Instagram posts? Pure guesswork." },
];

const features = [
  { icon: <Sparkles size={20} />, color: "text-cyan-400", title: "AI Trip Designer", desc: "Drafts complete itineraries from your knowledge base — activities, restaurants, photographers, transfers, route options. You curate, then send as a beautiful quote PDF in minutes, not hours." },
  { icon: <FileText size={20} />, color: "text-teal-400", title: "Brand-voice grounded replies", desc: "RAG knowledge base of your past itineraries, FAQs, rate plans, transfer options. The AI Concierge reads like your founder wrote it — because it learned from your founder." },
  { icon: <Calendar size={20} />, color: "text-amber-400", title: "Multi-day pre-trip sequences", desc: "Automated D-14 itinerary doc, D-7 dietary + occasion check, D-1 driver briefing, D-day welcome. On WhatsApp, on schedule, every time." },
  { icon: <Phone size={20} />, color: "text-purple-400", title: "Every discovery call auto-scored", desc: "CallerDesk forwards your number to the founder/trip designer's mobile. HAIP auto-transcribes, scores discovery quality, flags missed upsells, and writes a wrap-up — within 90 seconds." },
  { icon: <Compass size={20} />, color: "text-green-400", title: "Lost-reason intelligence", desc: "Wrong dates · weather concern · budget mismatch · couldn't decide on route — weekly clustered themes from your lost enquiries, so you know exactly what to fix next." },
  { icon: <Shield size={20} />, color: "text-yellow-400", title: "Guest 360 for repeat clients", desc: "Lifetime stays, past objections, predicted CSAT, suggested opener — surfaced the moment a repeat client messages. Perfect for high-value experiential travel." },
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

export default function TravelSolutionPage() {
  return (
    <div className="bg-[#0B1F3A] text-white min-h-screen">
      {/* HERO */}
      <section className="relative pt-32 pb-20 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[500px] rounded-full bg-cyan-500/8 blur-[120px]" />
          <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "radial-gradient(circle, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
        </div>
        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 grid lg:grid-cols-12 gap-12 items-center">
          <div className="lg:col-span-7">
            <div className="inline-flex items-center gap-2 bg-cyan-500/10 border border-cyan-500/20 rounded-full px-4 py-1.5 mb-6">
              <Plane size={12} className="text-cyan-400" />
              <span className="text-xs font-semibold text-cyan-300 uppercase tracking-wider">For travel &amp; experiential operators</span>
            </div>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight leading-[1.05] mb-6">
              From discovery call
              <br />
              <span className="bg-gradient-to-r from-cyan-300 via-teal-300 to-teal-400 bg-clip-text text-transparent">to fifth-star review.</span>
            </h1>
            <p className="text-lg text-white/55 max-w-xl mb-8 leading-relaxed">
              HAIP is the AI-first communication platform for experiential travel operators — luxury caravans, multi-day journeys, DMCs, bespoke trip designers. Capture every enquiry, generate quotes in minutes, and remember every traveller.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 mb-6">
              <Link href="/register?plan=growth&segment=travel" className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-teal-500 hover:bg-teal-400 text-white font-bold rounded-2xl transition-all shadow-2xl shadow-teal-500/30 hover:-translate-y-0.5">Start 14-day free trial <ArrowRight size={16} /></Link>
              <Link href="/book-demo?segment=travel" className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">Book a 30-min demo</Link>
            </div>
            <p className="text-xs text-white/30">Built with Ratha · India&apos;s premier luxury caravan operator</p>
          </div>

          {/* Hero visual: trip-designer quote */}
          <div className="lg:col-span-5">
            <div className="relative">
              <div className="absolute -inset-4 bg-gradient-to-br from-cyan-500/20 to-teal-500/10 rounded-3xl blur-2xl" />
              <div className="relative bg-[#0f2744] rounded-2xl border border-white/10 p-5 shadow-2xl shadow-black/40">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <p className="text-xs font-semibold text-white">Anjali &amp; Rohan</p>
                    <p className="text-[10px] text-white/40">Honeymoon · Spiti caravan · 11 nights</p>
                  </div>
                  <span className="text-[10px] px-2 py-1 rounded-md bg-cyan-500/20 text-cyan-300 font-semibold">Quote ready · 18 min</span>
                </div>
                <div className="space-y-2 mb-4">
                  {[
                    { day: "D1–2", title: "Manali · acclimatise + sound bath", color: "bg-amber-500/15 text-amber-300" },
                    { day: "D3–4", title: "Kaza · monastery circuit + stargazing", color: "bg-purple-500/15 text-purple-300" },
                    { day: "D5–6", title: "Kibber · private chef + glacier walk", color: "bg-cyan-500/15 text-cyan-300" },
                    { day: "D7–9", title: "Tabo · monastery + photographer", color: "bg-teal-500/15 text-teal-300" },
                    { day: "D10–11", title: "Kalpa · descent + spa wrap", color: "bg-green-500/15 text-green-300" },
                  ].map(d => (
                    <div key={d.day} className="flex items-center gap-3 bg-white/3 rounded-lg px-3 py-2">
                      <span className={`text-[10px] font-bold ${d.color} px-2 py-0.5 rounded`}>{d.day}</span>
                      <span className="text-xs text-white/70 flex-1 truncate">{d.title}</span>
                    </div>
                  ))}
                </div>
                <div className="bg-teal-500/8 border border-teal-500/20 rounded-xl p-3 space-y-1.5">
                  <div className="flex items-start gap-2">
                    <Sparkles size={12} className="text-teal-400 flex-shrink-0 mt-0.5" />
                    <p className="text-[11px] text-teal-200 leading-relaxed font-medium">AI drafted quote in 4 min · founder approved · sent on WhatsApp</p>
                  </div>
                  <div className="flex items-start gap-2">
                    <TrendingUp size={12} className="text-amber-400 flex-shrink-0 mt-0.5" />
                    <p className="text-[11px] text-amber-200 leading-relaxed">Suggested add-ons: photographer (₹65K) · in-caravan chef (₹40K)</p>
                  </div>
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
              <div className="text-3xl sm:text-4xl font-black text-cyan-400 mb-1">{s.value}</div>
              <div className="text-xs text-white/40">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* PAIN POINTS */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-bold text-rose-400 uppercase tracking-widest mb-3">The trip designer&apos;s reality</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">High-deal-value, long-discovery, everything-bespoke</h2>
            <p className="text-white/45 max-w-xl mx-auto">Experiential travel runs on intimate conversations and detailed itineraries. The work is craft. The admin is crushing.</p>
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
            <p className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-3">Built for experiential travel</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">Your trip-designer team, multiplied</h2>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {features.map(f => (
              <div key={f.title} className="bg-[#0f2744] border border-white/8 rounded-2xl p-6 hover:border-cyan-500/30 transition-all hover:-translate-y-0.5">
                <div className={`w-11 h-11 rounded-xl bg-white/5 flex items-center justify-center mb-4 ${f.color}`}>{f.icon}</div>
                <h3 className="text-base font-bold text-white mb-2">{f.title}</h3>
                <p className="text-sm text-white/45 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* TESTIMONIAL — Ratha */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-4xl mx-auto bg-gradient-to-br from-[#0f2744] to-[#0a1f3a] border border-white/10 rounded-3xl p-10 sm:p-14">
          <div className="flex gap-1 mb-6">{[...Array(5)].map((_, i) => <span key={i} className="text-cyan-400">★</span>)}</div>
          <p className="text-xl sm:text-2xl text-white/80 leading-relaxed font-medium mb-8">
            &ldquo;We design 11-night journeys across Spiti, Ladakh and the Northeast. Every enquiry used to feel like reinventing the wheel. HAIP turned our past 200 itineraries into a knowledge base — and now the first quote draft lands inside 30 minutes. Repeat-client retention is up, and we&apos;ve doubled trip designer capacity without doubling the team.&rdquo;
          </p>
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-cyan-500 flex items-center justify-center text-base font-bold text-white">R</div>
            <div>
              <div className="text-base font-bold text-white">Ratha</div>
              <div className="text-sm text-white/40">Luxury Caravan Travel &amp; Experiential Journeys · HAIP design partner</div>
            </div>
            <Link href="/case-studies/ratha" className="ml-auto text-xs text-cyan-400 hover:text-cyan-300 font-semibold inline-flex items-center gap-1">
              Read case study <ChevronRight size={12} />
            </Link>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-24 px-5 sm:px-8 bg-[#0a1b30]">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-3">FAQ</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight">Trip designer questions</h2>
          </div>
          <div className="space-y-3">
            {faqs.map(f => (
              <details key={f.q} className="group bg-[#0f2744]/60 border border-white/8 rounded-2xl px-6 py-5 hover:border-cyan-500/30 transition-colors">
                <summary className="flex items-center justify-between cursor-pointer list-none">
                  <h3 className="text-base font-semibold text-white pr-4">{f.q}</h3>
                  <ChevronRight size={18} className="text-cyan-400 group-open:rotate-90 transition-transform flex-shrink-0" />
                </summary>
                <p className="mt-4 text-sm text-white/55 leading-relaxed">{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-5 sm:px-8 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/10 via-transparent to-teal-500/5 pointer-events-none" />
        <div className="max-w-3xl mx-auto text-center relative">
          <div className="w-16 h-16 rounded-2xl bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center mx-auto mb-6">
            <Plane size={28} className="text-cyan-400" />
          </div>
          <h2 className="text-3xl sm:text-5xl font-black tracking-tight mb-4">Stop typing itineraries. Start designing journeys.</h2>
          <p className="text-white/50 text-lg mb-10 max-w-xl mx-auto">HAIP gives your trip-designer team a 200-itinerary memory and an AI co-pilot that drafts in minutes.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/register?plan=growth&segment=travel" className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-teal-500 hover:bg-teal-400 text-white font-bold rounded-2xl transition-all shadow-2xl shadow-teal-500/30 hover:-translate-y-0.5">Start free trial <ArrowRight size={18} /></Link>
            <Link href="/book-demo?segment=travel" className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">Talk to a trip designer</Link>
          </div>
        </div>
      </section>
    </div>
  );
}

export const metadata = {
  title: "HAIP for Travel Operators — AI Trip Designer + auto-QA + pre-trip sequences",
  description: "Experiential travel operators and luxury caravan brands use HAIP to draft itineraries in minutes, capture every discovery call, and remember every traveller.",
};
