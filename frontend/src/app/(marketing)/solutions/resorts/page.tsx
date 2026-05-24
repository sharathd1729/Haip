import Link from "next/link";
import {
  ArrowRight, MessageSquare, Phone, Inbox, Sparkles, Trees,
  Users, BarChart2, TrendingUp, Shield, ChevronRight, CheckCircle2, Wine, Bike, Star,
} from "lucide-react";

const painPoints = [
  { icon: <MessageSquare size={18} className="text-rose-400" />, title: "Activity, spa and F&B enquiries scatter across teams", desc: "Front desk fields requests for spa bookings, dining, water sports, kids' club. Every team has its own WhatsApp group. Nothing reaches the guest record." },
  { icon: <Phone size={18} className="text-rose-400" />, title: "Reservations and FOH speak past each other", desc: "Reservations sells a package. FOH doesn't know what was promised. Guest arrives expecting things nobody told the property about." },
  { icon: <BarChart2 size={18} className="text-rose-400" />, title: "Ancillary revenue leaks at every touchpoint", desc: "Spa, F&B, transport, photographer — high-margin add-ons get mentioned inconsistently or not at all. Revenue management has no visibility." },
  { icon: <Users size={18} className="text-rose-400" />, title: "Group bookings are operationally chaotic", desc: "Weddings, MICE, family retreats — every department gets messages in their own channel. The guest experience suffers." },
];

const features = [
  { icon: <Inbox size={20} />, color: "text-teal-400", title: "Unified inbox across departments", desc: "Reservations, FOH, F&B, Spa, Activities — every WhatsApp / IG / call thread routes to the right team with full guest context, and a copy lands on the central guest record." },
  { icon: <Sparkles size={20} />, color: "text-cyan-400", title: "Multi-property AI Concierge", desc: "Trained per property on inventory, packages, F&B menus and activity calendars. Drafts replies that match each property's voice, in shadow mode by default." },
  { icon: <Wine size={20} />, color: "text-amber-400", title: "Ancillary revenue intelligence", desc: "HAIP surfaces missed F&B / spa / activity upsell opportunities on every call and chat. Weekly digest of which agents/properties consistently leave revenue on the table." },
  { icon: <Trees size={20} />, color: "text-green-400", title: "Per-property scoping", desc: "Resort A's FOH only sees Resort A. Group GM sees the whole portfolio. Role × Property × Department permissions, set once." },
  { icon: <Bike size={20} />, color: "text-purple-400", title: "Group booking workspace", desc: "Wedding / MICE / family retreat enquiries get a dedicated thread with parallel sub-threads for F&B, transport, spa, decor — all linked to one master record." },
  { icon: <Shield size={20} />, color: "text-yellow-400", title: "Compliance that scales with staff count", desc: "Hash-chained audit log, recording consent, per-tenant KMS, role-scoped exports. Built for the headache of audit-ready ops at multi-site scale." },
];

const stats = [
  { value: "+18%", label: "Avg. ancillary revenue lift" },
  { value: "100%", label: "Calls auto-scored" },
  { value: "<5min", label: "Cross-dept handoff time" },
  { value: "11", label: "Roles supported" },
];

const faqs = [
  { q: "Can each property have its own knowledge base, brand voice and rate card?", a: "Yes. HAIP supports per-property RAG knowledge bases and brand voice guides. The AI Concierge for Resort A will quote Resort A's rates, packages and house rules — never Resort B's." },
  { q: "What about housekeeping and FOH on the ground?", a: "FOH cockpit is mobile-first: today's arrivals/departures, transfers, housekeeping checklist, in-villa staff log, special requests. Works on any phone, no app to install." },
  { q: "How do you handle wedding & MICE enquiries?", a: "Group enquiries open a master thread with sub-threads per department (F&B, decor, accommodation, transport, spa). Every department sees only their tasks, but the master view shows the full guest picture." },
  { q: "Will HAIP work with Hostaway or another channel manager?", a: "Hostaway is the live integration; Guesty and Cloudbeds are on the H2 2026 roadmap. We sync bookings and guest data — your channel manager remains the source of truth for OTAs." },
  { q: "Where is data stored?", a: "AWS Mumbai (ap-south-1) by default. Recordings, transcripts and PII never leave India unless your tenancy is explicitly multi-region (Enterprise tier only)." },
];

export default function ResortsSolutionPage() {
  return (
    <div className="bg-[#0E1210] text-white min-h-screen">
      {/* HERO */}
      <section className="relative pt-32 pb-20 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[500px] rounded-full bg-green-500/8 blur-[120px]" />
          <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "radial-gradient(circle, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
        </div>
        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 grid lg:grid-cols-12 gap-12 items-center">
          <div className="lg:col-span-7">
            <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-full px-4 py-1.5 mb-6">
              <Trees size={12} className="text-green-400" />
              <span className="text-xs font-semibold text-green-300 uppercase tracking-wider">For resorts</span>
            </div>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight leading-[1.05] mb-6">
              One platform for the
              <br />
              <span className="bg-gradient-to-r from-green-300 via-teal-300 to-teal-400 bg-clip-text text-transparent">whole resort.</span>
            </h1>
            <p className="text-lg text-white/55 max-w-xl mb-8 leading-relaxed">
              Reservations, FOH, F&amp;B, spa, activities — every department on one intelligent workspace. AI Concierge per property, auto-QA on every call, role-scoped access for staff at scale.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 mb-6">
              <Link href="/register?plan=scale&segment=resorts" className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-[#C8964A] hover:bg-[#D4A85A] text-[#0E1210] font-bold rounded-2xl transition-all shadow-2xl shadow-teal-500/30 hover:-translate-y-0.5">Start 14-day free trial <ArrowRight size={16} /></Link>
              <Link href="/book-demo?segment=resorts" className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">Book a 30-min demo</Link>
            </div>
            <p className="text-xs text-white/30">Multi-property · Multi-department · Indian-hosted &amp; DPDP-ready</p>
          </div>

          {/* Hero visual: department routing */}
          <div className="lg:col-span-5">
            <div className="relative">
              <div className="absolute -inset-4 bg-gradient-to-br from-green-500/20 to-teal-500/10 rounded-3xl blur-2xl" />
              <div className="relative bg-[#141B15] rounded-2xl border border-white/10 p-5 shadow-2xl shadow-black/40">
                <div className="flex items-center justify-between mb-4">
                  <p className="text-xs font-semibold text-white/40 uppercase tracking-wider">Routing · Today, 14:42</p>
                  <span className="text-[10px] px-2 py-1 rounded-md bg-green-500/20 text-green-300 font-semibold">36 in queue</span>
                </div>
                <div className="space-y-2">
                  {[
                    { dept: "Reservations", icon: <Inbox size={12} />, color: "bg-teal-500/15 text-teal-300", count: 14, last: "Anniversary suite for Dec 20–24" },
                    { dept: "F&B", icon: <Wine size={12} />, color: "bg-amber-500/15 text-amber-300", count: 8, last: "Vegan dinner · 6pm · 4 pax" },
                    { dept: "Spa", icon: <Sparkles size={12} />, color: "bg-purple-500/15 text-purple-300", count: 5, last: "Couples massage · pre-arrival" },
                    { dept: "Activities", icon: <Bike size={12} />, color: "bg-cyan-500/15 text-cyan-300", count: 6, last: "Kayak hire · family of 5" },
                    { dept: "FOH (today)", icon: <Trees size={12} />, color: "bg-green-500/15 text-green-300", count: 3, last: "Late checkout · Villa 4" },
                  ].map(d => (
                    <div key={d.dept} className="flex items-center gap-3 bg-white/3 hover:bg-white/5 rounded-xl px-3 py-2.5 transition-colors">
                      <div className={`w-7 h-7 rounded-lg ${d.color} flex items-center justify-center`}>{d.icon}</div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-white">{d.dept}</span>
                          <span className="text-[10px] text-white/40">{d.count}</span>
                        </div>
                        <p className="text-[11px] text-white/45 truncate">{d.last}</p>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 bg-teal-500/10 border border-teal-500/20 rounded-xl p-3 flex items-start gap-2">
                  <Sparkles size={12} className="text-teal-400 flex-shrink-0 mt-0.5" />
                  <p className="text-[11px] text-teal-200 leading-relaxed">3 ancillary upsell suggestions ready · Spa for Villa 7 family, photographer for honeymoon couple, helicopter transfer for VIP.</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* STATS */}
      <section className="py-14 border-y border-white/6 bg-gradient-to-r from-[#0E1210] to-[#141B15]">
        <div className="max-w-5xl mx-auto px-5 sm:px-8 grid grid-cols-2 md:grid-cols-4 gap-8">
          {stats.map(s => (
            <div key={s.label} className="text-center">
              <div className="text-3xl sm:text-4xl font-black text-green-400 mb-1">{s.value}</div>
              <div className="text-xs text-white/40">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* PAIN POINTS */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-bold text-rose-400 uppercase tracking-widest mb-3">Resort operations reality</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">The bigger you get, the more leaks between teams</h2>
            <p className="text-white/45 max-w-xl mx-auto">Resorts grow into 6+ departments and inevitably 6+ siloed WhatsApp groups. HAIP gives every team the same picture of every guest.</p>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            {painPoints.map(p => (
              <div key={p.title} className="bg-[#141B15]/60 border border-white/6 rounded-2xl p-6 hover:border-rose-500/20 transition-colors">
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
      <section className="py-24 px-5 sm:px-8 bg-[#0E1210]">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-bold text-green-400 uppercase tracking-widest mb-3">Built for resorts</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">Six things HAIP does that your current stack can&apos;t</h2>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {features.map(f => (
              <div key={f.title} className="bg-[#141B15] border border-white/8 rounded-2xl p-6 hover:border-green-500/30 transition-all hover:-translate-y-0.5">
                <div className={`w-11 h-11 rounded-xl bg-white/5 flex items-center justify-center mb-4 ${f.color}`}>{f.icon}</div>
                <h3 className="text-base font-bold text-white mb-2">{f.title}</h3>
                <p className="text-sm text-white/45 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ROLE-SCOPED ACCESS */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto grid lg:grid-cols-2 gap-12 items-center">
          <div>
            <div className="inline-flex items-center gap-2 bg-teal-500/10 border border-teal-500/20 rounded-full px-3 py-1.5 mb-6">
              <Users size={12} className="text-teal-400" />
              <span className="text-xs font-semibold text-teal-300">Roles &amp; permissions</span>
            </div>
            <h2 className="text-3xl font-black tracking-tight mb-4 leading-tight">A workspace tuned to each role — eleven by default</h2>
            <p className="text-white/55 text-base leading-relaxed mb-6">
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
                <li key={item} className="flex items-start gap-3 text-sm text-white/60">
                  <CheckCircle2 size={16} className="text-teal-400 flex-shrink-0 mt-0.5" /> {item}
                </li>
              ))}
            </ul>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { role: "Owner", desc: "Portfolio · 7 properties", color: "from-navy-2 to-navy", initials: "OG" },
              { role: "Reservations", desc: "All villas · pipeline", color: "from-teal-500 to-teal-700", initials: "RL" },
              { role: "Concierge", desc: "Today · queue + queue", color: "from-purple-500 to-purple-700", initials: "CG" },
              { role: "Marketing", desc: "Campaigns · ROAS", color: "from-amber-500 to-amber-700", initials: "MK" },
              { role: "FOH", desc: "Property · today", color: "from-cyan-500 to-cyan-700", initials: "FH" },
              { role: "Compliance", desc: "Audit · exports", color: "from-rose-500 to-rose-700", initials: "CP" },
            ].map(r => (
              <div key={r.role} className="bg-[#141B15] border border-white/8 rounded-xl p-4 hover:border-green-500/30 transition-colors">
                <div className={`w-10 h-10 rounded-full bg-gradient-to-br ${r.color} flex items-center justify-center mb-3 text-white font-bold text-xs`}>{r.initials}</div>
                <p className="text-sm font-bold text-white">{r.role}</p>
                <p className="text-[11px] text-white/40 mt-0.5">{r.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* TESTIMONIAL */}
      <section className="py-24 px-5 sm:px-8 bg-[#0E1210]">
        <div className="max-w-4xl mx-auto bg-gradient-to-br from-[#141B15] to-[#0E1210] border border-white/10 rounded-3xl p-10 sm:p-14">
          <div className="flex gap-1 mb-6">{[...Array(5)].map((_, i) => <span key={i} className="text-green-400">★</span>)}</div>
          <p className="text-xl sm:text-2xl text-white/80 leading-relaxed font-medium mb-8">
            &ldquo;We operate four resort properties across two states. Before HAIP, ancillary revenue from spa, F&amp;B and excursions was completely invisible at the portfolio level. Now we see it daily — and our spa upsell rate doubled in 11 weeks because every concierge gets a nudge when it&apos;s relevant.&rdquo;
          </p>
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-green-500 flex items-center justify-center text-base font-bold text-white">SP</div>
            <div>
              <div className="text-base font-bold text-white">Suresh Pillai</div>
              <div className="text-sm text-white/40">COO, Backwaters Collection (resort group)</div>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-24 px-5 sm:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-xs font-bold text-green-400 uppercase tracking-widest mb-3">FAQ</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight">Resort operator questions</h2>
          </div>
          <div className="space-y-3">
            {faqs.map(f => (
              <details key={f.q} className="group bg-[#141B15]/60 border border-white/8 rounded-2xl px-6 py-5 hover:border-green-500/30 transition-colors">
                <summary className="flex items-center justify-between cursor-pointer list-none">
                  <h3 className="text-base font-semibold text-white pr-4">{f.q}</h3>
                  <ChevronRight size={18} className="text-green-400 group-open:rotate-90 transition-transform flex-shrink-0" />
                </summary>
                <p className="mt-4 text-sm text-white/55 leading-relaxed">{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-5 sm:px-8 bg-[#0E1210] relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-green-500/10 via-transparent to-teal-500/5 pointer-events-none" />
        <div className="max-w-3xl mx-auto text-center relative">
          <div className="w-16 h-16 rounded-2xl bg-green-500/20 border border-green-500/30 flex items-center justify-center mx-auto mb-6">
            <Trees size={28} className="text-green-400" />
          </div>
          <h2 className="text-3xl sm:text-5xl font-black tracking-tight mb-4">Run a resort group like a single resort</h2>
          <p className="text-white/50 text-lg mb-10 max-w-xl mx-auto">One inbox. One AI brain. One source of truth — no matter how many properties, departments and staff you grow into.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/register?plan=scale&segment=resorts" className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-[#C8964A] hover:bg-[#D4A85A] text-[#0E1210] font-bold rounded-2xl transition-all shadow-2xl shadow-teal-500/30 hover:-translate-y-0.5">Start free trial <ArrowRight size={18} /></Link>
            <Link href="/book-demo?segment=resorts" className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-4 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">Talk to sales</Link>
          </div>
        </div>
      </section>
    </div>
  );
}

export const metadata = {
  title: "HAIP for Resorts — Multi-property AI Concierge + role-scoped ops",
  description: "Resorts in India use HAIP to unify enquiries, departments and guests across multiple properties — with role-scoped access, ancillary revenue intelligence, and DPDP-compliant ops.",
};
