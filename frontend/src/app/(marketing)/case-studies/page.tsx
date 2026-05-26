import Link from "next/link";
import {
  ArrowRight, Plane, Building2, Trees, Hotel, ChevronRight, Sparkles, TrendingUp, Quote,
} from "lucide-react";

const featured = {
  badge: "Design partner · Luxury experiential travel",
  badgeIcon: <Plane size={12} className="text-cyan-400" />,
  badgeColor: "bg-cyan-500/10 border-cyan-500/20 text-cyan-300",
  brand: "Ratha",
  brandTag: "Luxury Caravan Travel & Experiential Journeys",
  headline: "From 6-hour quote turnaround to 30 minutes — with the founder still in the loop.",
  excerpt: "Ratha designs 11-night experiential journeys across Spiti, Ladakh and the Northeast. Before HAIP, every enquiry meant manually pulling itineraries, rates, transport and partner contacts into a quote PDF. Now the AI Trip Designer drafts the first version from the founder's own past 200 itineraries, and a trip designer ships the final to the guest in under 30 minutes.",
  metrics: [
    { label: "Quote turnaround", value: "30 min", baseline: "from 6+ hrs" },
    { label: "Enquiries auto-handled to resolution", value: ">60%", baseline: "from 0%" },
    { label: "Call QA coverage", value: "100%", baseline: "from ~5% sampled" },
    { label: "Pre-trip preference completion", value: ">90%", baseline: "from ~40%" },
  ],
  href: "/case-studies/ratha",
};

const cases = [
  {
    icon: <Building2 size={16} className="text-teal-400" />,
    segment: "Luxury villas",
    color: "bg-teal-500/10 border-teal-500/20 text-teal-300",
    brand: "Ananta Villa Collection",
    location: "Goa &amp; Coorg · 11 villas",
    quote: "We were missing 30% of WhatsApp enquiries during peak hours. Every enquiry is captured and quote-ready in under 4 minutes now.",
    metric: "+27% YoY revenue · 30% fewer missed enquiries",
    href: "/case-studies/ananta",
  },
  {
    icon: <Hotel size={16} className="text-amber-400" />,
    segment: "Boutique hotels",
    color: "bg-amber-500/10 border-amber-500/20 text-amber-300",
    brand: "The Postcard Boutique Hotels",
    location: "Multi-city · 8 properties",
    quote: "QA scoring made our reservations team noticeably sharper on objections within 60 days. The unified inbox just paid for itself.",
    metric: "+14pp direct booking share · 100% call coverage",
    href: "/case-studies/postcard",
  },
  {
    icon: <Trees size={16} className="text-green-400" />,
    segment: "Resorts",
    color: "bg-green-500/10 border-green-500/20 text-green-300",
    brand: "Backwaters Collection",
    location: "Kerala &amp; Karnataka · 4 resorts",
    quote: "Spa upsell rate doubled in 11 weeks because every concierge gets a nudge when it&apos;s actually relevant.",
    metric: "2× spa upsell · +18% ancillary revenue",
    href: "/case-studies/backwaters",
  },
  {
    icon: <Building2 size={16} className="text-purple-400" />,
    segment: "Pool villas",
    color: "bg-purple-500/10 border-purple-500/20 text-purple-300",
    brand: "Jade Hospitainment",
    location: "Bangalore · 6 luxury pool villas",
    quote: "Multi-villa availability + Acefone routing means every reservations agent picks up with full context — even at 11pm.",
    metric: "<5 min p95 first response · 24/7",
    href: "/case-studies/jade",
  },
];

const themes = [
  { label: "All", count: cases.length + 1, active: true },
  { label: "Villas", count: 2 },
  { label: "Hotels", count: 1 },
  { label: "Resorts", count: 1 },
  { label: "Travel", count: 1 },
];

export default function CaseStudiesPage() {
  return (
    <div className="bg-[var(--mkt-bg)] text-white min-h-screen">
      {/* HERO */}
      <section className="relative pt-32 pb-16 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full bg-teal-500/8 blur-[120px]" />
          <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "radial-gradient(circle, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
        </div>
        <div className="relative max-w-6xl mx-auto px-5 sm:px-8 text-center">
          <div className="inline-flex items-center gap-2 bg-teal-500/10 border border-teal-500/20 rounded-full px-4 py-1.5 mb-6">
            <Sparkles size={12} className="text-teal-400" />
            <span className="text-xs font-semibold text-teal-300 uppercase tracking-wider">Case studies</span>
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight mb-5">Real teams. Real numbers. Real guests.</h1>
          <p className="text-white/55 text-lg max-w-2xl mx-auto leading-relaxed">
            How hospitality and experiential travel brands across India use HAIP to capture every enquiry, convert more bookings, and remember every guest.
          </p>
        </div>
      </section>

      {/* THEME FILTER */}
      <section className="px-5 sm:px-8 pb-4">
        <div className="max-w-6xl mx-auto flex flex-wrap gap-2 justify-center">
          {themes.map(t => (
            <button key={t.label} className={`px-4 py-1.5 rounded-full text-xs font-semibold border transition-colors ${t.active ? "bg-teal-500/15 border-teal-500/40 text-teal-300" : "bg-white/3 border-white/8 text-white/55 hover:text-white hover:border-white/15"}`}>
              {t.label} <span className="text-white/30 ml-1">({t.count})</span>
            </button>
          ))}
        </div>
      </section>

      {/* FEATURED CASE STUDY */}
      <section className="py-16 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <Link href={featured.href} className="block group bg-[var(--mkt-panel)] hover:bg-[#102a4a] border border-white/10 hover:border-cyan-500/30 rounded-3xl overflow-hidden transition-all">
            <div className="grid lg:grid-cols-12">
              {/* Left: copy */}
              <div className="lg:col-span-7 p-8 sm:p-12">
                <div className={`inline-flex items-center gap-2 ${featured.badgeColor} border rounded-full px-3 py-1.5 mb-5`}>
                  {featured.badgeIcon}
                  <span className="text-xs font-semibold uppercase tracking-wider">{featured.badge}</span>
                </div>
                <div className="mb-5">
                  <p className="text-xs text-white/40 uppercase tracking-widest font-bold mb-1">{featured.brandTag}</p>
                  <h2 className="text-2xl sm:text-3xl font-black tracking-tight text-white">{featured.brand}</h2>
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-4 leading-tight group-hover:text-cyan-300 transition-colors">{featured.headline}</h3>
                <p className="text-white/60 text-sm sm:text-base leading-relaxed mb-6">{featured.excerpt}</p>
                <span className="inline-flex items-center gap-2 text-sm font-semibold text-cyan-400 group-hover:text-cyan-300">
                  Read the full case study <ArrowRight size={14} className="group-hover:translate-x-0.5 transition-transform" />
                </span>
              </div>
              {/* Right: metrics */}
              <div className="lg:col-span-5 bg-[#0E1210] p-8 sm:p-10 border-t lg:border-t-0 lg:border-l border-white/8">
                <p className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-5">90-day results</p>
                <div className="space-y-5">
                  {featured.metrics.map(m => (
                    <div key={m.label}>
                      <div className="flex items-baseline justify-between">
                        <span className="text-xs text-white/40">{m.label}</span>
                        <TrendingUp size={12} className="text-cyan-400" />
                      </div>
                      <div className="flex items-baseline gap-2 mt-1">
                        <span className="text-2xl font-black text-cyan-300">{m.value}</span>
                        <span className="text-[11px] text-white/35">{m.baseline}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </Link>
        </div>
      </section>

      {/* CASE GRID */}
      <section className="px-5 sm:px-8 pb-20">
        <div className="max-w-6xl mx-auto grid md:grid-cols-2 gap-5">
          {cases.map(c => (
            <Link key={c.brand} href={c.href} className="group bg-[var(--mkt-panel)]/70 hover:bg-[var(--mkt-panel)] border border-white/8 hover:border-teal-500/25 rounded-2xl p-6 transition-all hover:-translate-y-0.5">
              <div className="flex items-center justify-between mb-5">
                <div className={`inline-flex items-center gap-2 ${c.color} border rounded-full px-3 py-1`}>
                  {c.icon}
                  <span className="text-xs font-semibold uppercase tracking-wider">{c.segment}</span>
                </div>
                <ChevronRight size={16} className="text-white/30 group-hover:text-teal-400 group-hover:translate-x-0.5 transition-all" />
              </div>
              <h3 className="text-lg font-bold text-white mb-1 group-hover:text-teal-300 transition-colors">{c.brand}</h3>
              <p className="text-xs text-white/40 mb-5" dangerouslySetInnerHTML={{ __html: c.location }} />
              <div className="bg-white/3 rounded-xl p-4 mb-5 relative">
                <Quote size={14} className="absolute top-3 left-3 text-white/15" />
                <p className="text-sm text-white/65 italic leading-relaxed pl-5" dangerouslySetInnerHTML={{ __html: c.quote }} />
              </div>
              <div className="flex items-center gap-2 text-xs font-bold text-teal-300">
                <TrendingUp size={12} />
                <span dangerouslySetInnerHTML={{ __html: c.metric }} />
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 px-5 sm:px-8 bg-[#0E1210] relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-teal-500/10 via-transparent to-cyan-500/5 pointer-events-none" />
        <div className="max-w-3xl mx-auto text-center relative">
          <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4">Want to be the next case study?</h2>
          <p className="text-white/55 mb-8 max-w-xl mx-auto">Design partners get 6 months free in exchange for case-study rights. Limited slots — we&apos;re only taking 3 more this quarter.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/book-demo?topic=design-partner" className="inline-flex items-center gap-2 px-6 py-3 bg-[#C8964A] hover:bg-[#D4A85A] text-[#0E1210] font-bold rounded-2xl transition-all shadow-xl shadow-[#C8964A]/30">
              Apply as a design partner <ArrowRight size={16} />
            </Link>
            <Link href="/pricing" className="inline-flex items-center gap-2 px-6 py-3 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">
              See pricing
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

export const metadata = {
  title: "HAIP Case Studies — How hospitality teams use HAIP",
  description: "Real results from villa groups, boutique hotels, resorts and experiential travel operators using HAIP for unified inbox, AI Concierge and call intelligence.",
};
