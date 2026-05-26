import Link from "next/link";
import {
  Compass, Sparkles, ArrowRight, CheckCircle2, Clock, Calendar, MessageSquare,
} from "lucide-react";

const lanes = [
  {
    quarter: "Shipping now · 2026 Q2",
    color: "bg-teal-500/15 text-teal-300 border-teal-500/30",
    items: [
      { title: "AI Trip Designer for experiential travel", desc: "Quote-PDF generator from past itineraries + partner catalog." },
      { title: "Acefone adapter v2", desc: "Multi-property sticky routing, call analytics, masking." },
      { title: "Owner Daily v2", desc: "Portfolio-wide KPIs across all properties on one dashboard." },
      { title: "Coaching cockpit", desc: "Per-agent QA trends, themed nudges from team lead." },
    ],
  },
  {
    quarter: "Next · 2026 Q3",
    color: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    items: [
      { title: "Hostaway integration", desc: "Two-way sync of bookings + guests from your channel manager." },
      { title: "VoG (Voice of Guest)", desc: "Themed analysis of objections, complaints and compliments across all calls + chats." },
      { title: "Lost-reason clustering", desc: "Auto-tag and group enquiries that didn&apos;t convert, weekly digest of themes." },
      { title: "Per-property AI Concierge brand voice", desc: "Tune Concierge per property knowledge base." },
    ],
  },
  {
    quarter: "Later · 2026 Q4 → 2027 Q1",
    color: "bg-purple-500/15 text-purple-300 border-purple-500/30",
    items: [
      { title: "Predictive module", desc: "No-show / cancellation risk · daily occupancy forecast · rate suggestion." },
      { title: "Marketing &amp; ROAS", desc: "OTA-vs-direct trend, campaign attribution, channel ROAS dashboard." },
      { title: "Guesty + Cloudbeds adapters", desc: "More channel manager and PMS integrations." },
      { title: "SOC 2 Type I", desc: "Audit kick-off; report by 2026 Q4." },
    ],
  },
  {
    quarter: "Exploring · 2027+",
    color: "bg-white/8 text-white/55 border-white/15",
    items: [
      { title: "Multi-region tenancy", desc: "EU customer data isolated to eu-central-1 (Enterprise tier)." },
      { title: "BYOK on Enterprise", desc: "Customer-managed KMS keys for the largest deployments." },
      { title: "Visa + payments workflows for travel operators", desc: "Centralised supplier orchestration." },
      { title: "OTA inbox sync direct (Booking.com, Airbnb)", desc: "Native adapters beyond Hostaway." },
    ],
  },
];

export default function RoadmapPage() {
  return (
    <div className="bg-[var(--mkt-bg)] text-white min-h-screen">
      <section className="relative pt-32 pb-12 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full bg-teal-500/8 blur-[120px]" />
        </div>
        <div className="relative max-w-3xl mx-auto px-5 sm:px-8 text-center">
          <div className="inline-flex items-center gap-2 bg-teal-500/10 border border-teal-500/20 rounded-full px-4 py-1.5 mb-5">
            <Compass size={12} className="text-teal-400" />
            <span className="text-xs font-semibold text-teal-300 uppercase tracking-wider">Public roadmap</span>
          </div>
          <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4">Where HAIP is heading</h1>
          <p className="text-white/55 text-lg leading-relaxed">Honest, public, and customer-driven. Bring your own item — we read everything that lands at <Link href="/contact" className="text-teal-400 hover:text-teal-300 underline">gen.haip@gmail.com</Link>.</p>
        </div>
      </section>

      <section className="px-5 sm:px-8 pb-20">
        <div className="max-w-6xl mx-auto grid md:grid-cols-2 gap-5">
          {lanes.map(l => (
            <div key={l.quarter} className="bg-[var(--mkt-panel)]/60 border border-white/8 rounded-2xl p-6">
              <span className={`inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest border rounded-full px-3 py-1 mb-5 ${l.color}`}>
                {l.quarter.startsWith("Shipping") ? <Sparkles size={10} /> : l.quarter.startsWith("Next") ? <Calendar size={10} /> : <Clock size={10} />}
                {l.quarter}
              </span>
              <ul className="space-y-4">
                {l.items.map(it => (
                  <li key={it.title} className="flex items-start gap-3">
                    <CheckCircle2 size={14} className="text-white/30 flex-shrink-0 mt-1" />
                    <div>
                      <p className="text-sm font-bold text-white mb-0.5">{it.title}</p>
                      <p className="text-xs text-white/45 leading-relaxed" dangerouslySetInnerHTML={{ __html: it.desc }} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="px-5 sm:px-8 pb-24">
        <div className="max-w-3xl mx-auto bg-[var(--mkt-panel)] border border-white/10 rounded-2xl p-7 text-center">
          <h2 className="text-2xl font-black mb-3">Got something you need?</h2>
          <p className="text-white/55 text-sm max-w-md mx-auto mb-6">If a customer asks for it twice, it goes on the board. Tell us what would unlock value for your team — we&apos;ll prioritise transparently.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/contact" className="inline-flex items-center gap-2 px-5 py-2.5 bg-teal-500 hover:bg-teal-400 text-white text-sm font-bold rounded-xl">Suggest a feature <ArrowRight size={14} /></Link>
            <a href="https://wa.me/+918147698153" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 text-white text-sm font-semibold rounded-xl">
              <MessageSquare size={14} /> WhatsApp the product team
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}

export const metadata = { title: "HAIP Roadmap — What&apos;s shipping next" };
