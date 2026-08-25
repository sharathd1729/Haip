import Link from "next/link";
import { ArrowRight, Plane, Building2, Hotel, ChevronRight, Sparkles, TrendingUp } from "@/lib/icons";
import { Trees, Quote } from "lucide-react";

const featured = {
  badge: "Design partner · Luxury experiential travel",
  badgeIcon: <Plane size={12} style={{ color: "#ffc94b" }} />,
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
    icon: <Building2 size={16} style={{ color: "#00555a" }} />,
    segment: "Luxury villas",
    chipStyle: { backgroundColor: "rgba(0,85,90,0.08)", border: "1px solid rgba(0,85,90,0.20)", color: "#00555a" },
    brand: "Ananta Villa Collection",
    location: "Goa &amp; Coorg · 11 villas",
    quote: "We were missing 30% of WhatsApp enquiries during peak hours. Every enquiry is captured and quote-ready in under 4 minutes now.",
    metric: "+27% YoY revenue · 30% fewer missed enquiries",
    href: "/case-studies/ananta",
  },
  {
    icon: <Hotel size={16} style={{ color: "#e6b000" }} />,
    segment: "Boutique hotels",
    chipStyle: { backgroundColor: "rgba(255,201,75,0.16)", border: "1px solid rgba(230,176,0,0.30)", color: "#a16207" },
    brand: "The Postcard Boutique Hotels",
    location: "Multi-city · 8 properties",
    quote: "QA scoring made our reservations team noticeably sharper on objections within 60 days. The unified inbox just paid for itself.",
    metric: "+14pp direct booking share · 100% call coverage",
    href: "/case-studies/postcard",
  },
  {
    icon: <Trees size={16} style={{ color: "#16a34a" }} />,
    segment: "Resorts",
    chipStyle: { backgroundColor: "rgba(22,163,74,0.08)", border: "1px solid rgba(22,163,74,0.22)", color: "#15803d" },
    brand: "Backwaters Collection",
    location: "Kerala &amp; Karnataka · 4 resorts",
    quote: "Spa upsell rate doubled in 11 weeks because every concierge gets a nudge when it&apos;s actually relevant.",
    metric: "2× spa upsell · +18% ancillary revenue",
    href: "/case-studies/backwaters",
  },
  {
    icon: <Building2 size={16} style={{ color: "#00888f" }} />,
    segment: "Pool villas",
    chipStyle: { backgroundColor: "rgba(0,136,143,0.08)", border: "1px solid rgba(0,136,143,0.22)", color: "#00888f" },
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
    <div className="min-h-screen" style={{ backgroundColor: "var(--mkt-bg)", color: "#0F172A" }}>
      {/* HERO */}
      <section className="relative pt-32 pb-16 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full blur-[120px]" style={{ backgroundColor: "rgba(0,85,90,0.06)" }} />
          <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle, #00555a15 1px, transparent 1px)", backgroundSize: "28px 28px" }} />
        </div>
        <div className="relative max-w-6xl mx-auto px-5 sm:px-8 text-center">
          <div className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 mb-6" style={{ backgroundColor: "rgba(0,85,90,0.07)", border: "1px solid rgba(0,85,90,0.25)" }}>
            <Sparkles size={12} style={{ color: "#00555a" }} />
            <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#00555a" }}>Case studies</span>
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight mb-5" style={{ color: "#0F172A" }}>Real teams. Real numbers. Real guests.</h1>
          <p className="text-lg max-w-2xl mx-auto leading-relaxed" style={{ color: "#475569" }}>
            How hospitality and experiential travel brands across India use HAIP to capture every enquiry, convert more bookings, and remember every guest.
          </p>
        </div>
      </section>

      {/* THEME FILTER */}
      <section className="px-5 sm:px-8 pb-4">
        <div className="max-w-6xl mx-auto flex flex-wrap gap-2 justify-center">
          {themes.map(t => (
            <button
              key={t.label}
              className="px-4 py-1.5 rounded-full text-xs font-semibold transition-colors"
              style={t.active
                ? { backgroundColor: "#00555a", color: "#ffffff", border: "1px solid #00555a" }
                : { backgroundColor: "#ffffff", color: "#64748B", border: "1px solid #E2E8F0" }}
            >
              {t.label} <span className="ml-1" style={{ opacity: 0.6 }}>({t.count})</span>
            </button>
          ))}
        </div>
      </section>

      {/* FEATURED CASE STUDY */}
      <section className="py-16 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <Link href={featured.href} className="block group rounded-3xl overflow-hidden transition-all" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 24px 64px rgba(0,85,90,0.10), 0 4px 16px rgba(0,0,0,0.05)" }}>
            <div className="grid lg:grid-cols-12">
              {/* Left: copy */}
              <div className="lg:col-span-7 p-8 sm:p-12">
                <div className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 mb-5" style={{ backgroundColor: "rgba(255,201,75,0.16)", border: "1px solid rgba(230,176,0,0.30)" }}>
                  {featured.badgeIcon}
                  <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#a16207" }}>{featured.badge}</span>
                </div>
                <div className="mb-5">
                  <p className="text-xs uppercase tracking-widest font-bold mb-1" style={{ color: "#94A3B8" }}>{featured.brandTag}</p>
                  <h2 className="text-2xl sm:text-3xl font-black tracking-tight" style={{ color: "#0F172A" }}>{featured.brand}</h2>
                </div>
                <h3 className="text-xl sm:text-2xl font-bold mb-4 leading-tight transition-colors" style={{ color: "#0F172A" }}>{featured.headline}</h3>
                <p className="text-sm sm:text-base leading-relaxed mb-6" style={{ color: "#475569" }}>{featured.excerpt}</p>
                <span className="inline-flex items-center gap-2 text-sm font-semibold" style={{ color: "#00555a" }}>
                  Read the full case study <ArrowRight size={14} className="group-hover:translate-x-0.5 transition-transform" />
                </span>
              </div>
              {/* Right: metrics */}
              <div className="lg:col-span-5 p-8 sm:p-10" style={{ backgroundColor: "#003d41", borderTop: "1px solid #E2E8F0" }}>
                <p className="text-xs font-bold uppercase tracking-widest mb-5" style={{ color: "#ffc94b" }}>90-day results</p>
                <div className="space-y-5">
                  {featured.metrics.map(m => (
                    <div key={m.label}>
                      <div className="flex items-baseline justify-between">
                        <span className="text-xs" style={{ color: "rgba(255,255,255,0.55)" }}>{m.label}</span>
                        <TrendingUp size={12} style={{ color: "#ffc94b" }} />
                      </div>
                      <div className="flex items-baseline gap-2 mt-1">
                        <span className="text-2xl font-black" style={{ color: "#ffffff" }}>{m.value}</span>
                        <span className="text-[11px]" style={{ color: "rgba(255,255,255,0.40)" }}>{m.baseline}</span>
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
            <Link key={c.brand} href={c.href} className="group rounded-2xl p-6 transition-all hover:-translate-y-0.5" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
              <div className="flex items-center justify-between mb-5">
                <div className="inline-flex items-center gap-2 rounded-full px-3 py-1" style={c.chipStyle}>
                  {c.icon}
                  <span className="text-xs font-semibold uppercase tracking-wider">{c.segment}</span>
                </div>
                <ChevronRight size={16} className="group-hover:translate-x-0.5 transition-all" style={{ color: "#94A3B8" }} />
              </div>
              <h3 className="text-lg font-bold mb-1 transition-colors" style={{ color: "#0F172A" }}>{c.brand}</h3>
              <p className="text-xs mb-5" style={{ color: "#94A3B8" }} dangerouslySetInnerHTML={{ __html: c.location }} />
              <div className="rounded-xl p-4 mb-5 relative" style={{ backgroundColor: "#F8FAFC", border: "1px solid #F1F5F9" }}>
                <Quote size={14} className="absolute top-3 left-3" style={{ color: "#CBD5E1" }} />
                <p className="text-sm italic leading-relaxed pl-5" style={{ color: "#475569" }} dangerouslySetInnerHTML={{ __html: c.quote }} />
              </div>
              <div className="flex items-center gap-2 text-xs font-bold" style={{ color: "#00555a" }}>
                <TrendingUp size={12} />
                <span dangerouslySetInnerHTML={{ __html: c.metric }} />
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 px-5 sm:px-8 relative overflow-hidden" style={{ backgroundColor: "#003d41" }}>
        <div className="absolute inset-0 pointer-events-none" style={{ backgroundImage: "radial-gradient(circle, #00555a30 1px, transparent 1px)", backgroundSize: "28px 28px" }} />
        <div className="max-w-3xl mx-auto text-center relative">
          <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-4" style={{ color: "#ffffff" }}>Want to be the next case study?</h2>
          <p className="mb-8 max-w-xl mx-auto" style={{ color: "rgba(255,255,255,0.60)" }}>Design partners get 6 months free in exchange for case-study rights. Limited slots — we&apos;re only taking 3 more this quarter.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/book-demo?topic=design-partner" className="inline-flex items-center gap-2 px-6 py-3 font-bold rounded-2xl transition-all" style={{ backgroundColor: "#ffc94b", color: "#00555a", boxShadow: "0 8px 24px rgba(255,201,75,0.25)" }}>
              Apply as a design partner <ArrowRight size={16} />
            </Link>
            <Link href="/pricing" className="inline-flex items-center gap-2 px-6 py-3 font-semibold rounded-2xl transition-all" style={{ backgroundColor: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.15)", color: "#ffffff" }}>
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
