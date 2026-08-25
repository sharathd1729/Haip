import Link from "next/link";
import { Sparkles, ArrowRight, CheckCircle2, Clock, Calendar, MessageSquare } from "@/lib/icons";
import { Compass } from "lucide-react";

const lanes = [
  {
    quarter: "Shipping now · 2026 Q2",
    chipStyle: { backgroundColor: "rgba(0,85,90,0.08)", color: "#00555a", border: "1px solid rgba(0,85,90,0.25)" },
    items: [
      { title: "AI Trip Designer for experiential travel", desc: "Quote-PDF generator from past itineraries + partner catalog." },
      { title: "Acefone adapter v2", desc: "Multi-property sticky routing, call analytics, masking." },
      { title: "Owner Daily v2", desc: "Portfolio-wide KPIs across all properties on one dashboard." },
      { title: "Coaching cockpit", desc: "Per-agent QA trends, themed nudges from team lead." },
    ],
  },
  {
    quarter: "Next · 2026 Q3",
    chipStyle: { backgroundColor: "rgba(255,201,75,0.16)", color: "#a16207", border: "1px solid rgba(230,176,0,0.30)" },
    items: [
      { title: "Hostaway integration", desc: "Two-way sync of bookings + guests from your channel manager." },
      { title: "VoG (Voice of Guest)", desc: "Themed analysis of objections, complaints and compliments across all calls + chats." },
      { title: "Lost-reason clustering", desc: "Auto-tag and group enquiries that didn&apos;t convert, weekly digest of themes." },
      { title: "Per-property AI Concierge brand voice", desc: "Tune Concierge per property knowledge base." },
    ],
  },
  {
    quarter: "Later · 2026 Q4 → 2027 Q1",
    chipStyle: { backgroundColor: "rgba(0,136,143,0.08)", color: "#00888f", border: "1px solid rgba(0,136,143,0.25)" },
    items: [
      { title: "Predictive module", desc: "No-show / cancellation risk · daily occupancy forecast · rate suggestion." },
      { title: "Marketing &amp; ROAS", desc: "OTA-vs-direct trend, campaign attribution, channel ROAS dashboard." },
      { title: "Guesty + Cloudbeds adapters", desc: "More channel manager and PMS integrations." },
      { title: "SOC 2 Type I", desc: "Audit kick-off; report by 2026 Q4." },
    ],
  },
  {
    quarter: "Exploring · 2027+",
    chipStyle: { backgroundColor: "#F8FAFC", color: "#64748B", border: "1px solid #E2E8F0" },
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
    <div className="min-h-screen" style={{ backgroundColor: "var(--mkt-bg)", color: "#0F172A" }}>
      <section className="relative pt-32 pb-12 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full blur-[120px]" style={{ backgroundColor: "rgba(0,85,90,0.06)" }} />
          <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle, #00555a15 1px, transparent 1px)", backgroundSize: "28px 28px" }} />
        </div>
        <div className="relative max-w-3xl mx-auto px-5 sm:px-8 text-center">
          <div className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 mb-5" style={{ backgroundColor: "rgba(0,85,90,0.07)", border: "1px solid rgba(0,85,90,0.25)" }}>
            <Compass size={12} style={{ color: "#00555a" }} />
            <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#00555a" }}>Public roadmap</span>
          </div>
          <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4" style={{ color: "#0F172A" }}>Where HAIP is heading</h1>
          <p className="text-lg leading-relaxed" style={{ color: "#475569" }}>Honest, public, and customer-driven. Bring your own item — we read everything that lands at <Link href="/contact" className="underline" style={{ color: "#00555a" }}>gen.haip@gmail.com</Link>.</p>
        </div>
      </section>

      <section className="px-5 sm:px-8 pb-20">
        <div className="max-w-6xl mx-auto grid md:grid-cols-2 gap-5">
          {lanes.map(l => (
            <div key={l.quarter} className="rounded-2xl p-6" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
              <span className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest rounded-full px-3 py-1 mb-5" style={l.chipStyle}>
                {l.quarter.startsWith("Shipping") ? <Sparkles size={10} /> : l.quarter.startsWith("Next") ? <Calendar size={10} /> : <Clock size={10} />}
                {l.quarter}
              </span>
              <ul className="space-y-4">
                {l.items.map(it => (
                  <li key={it.title} className="flex items-start gap-3">
                    <CheckCircle2 size={14} className="flex-shrink-0 mt-1" style={{ color: "#00555a" }} />
                    <div>
                      <p className="text-sm font-bold mb-0.5" style={{ color: "#0F172A" }}>{it.title}</p>
                      <p className="text-xs leading-relaxed" style={{ color: "#64748B" }} dangerouslySetInnerHTML={{ __html: it.desc }} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="px-5 sm:px-8 pb-24">
        <div className="max-w-3xl mx-auto rounded-2xl p-7 text-center" style={{ backgroundColor: "#003d41" }}>
          <h2 className="text-2xl font-black mb-3" style={{ color: "#ffffff" }}>Got something you need?</h2>
          <p className="text-sm max-w-md mx-auto mb-6" style={{ color: "rgba(255,255,255,0.60)" }}>If a customer asks for it twice, it goes on the board. Tell us what would unlock value for your team — we&apos;ll prioritise transparently.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/contact" className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-bold rounded-xl" style={{ backgroundColor: "#ffc94b", color: "#00555a" }}>Suggest a feature <ArrowRight size={14} /></Link>
            <a href="https://wa.me/+918147698153" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold rounded-xl" style={{ backgroundColor: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.15)", color: "#ffffff" }}>
              <MessageSquare size={14} /> WhatsApp the product team
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}

export const metadata = { title: "HAIP Roadmap — What&apos;s shipping next" };
