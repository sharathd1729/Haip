"use client";
import Link from "next/link";

const links = {
  Product: [
    { label: "Features",     href: "/features" },
    { label: "Pricing",      href: "/pricing" },
    { label: "Integrations", href: "/integrations" },
    { label: "Changelog",    href: "/changelog" },
    { label: "Roadmap",      href: "/roadmap" },
  ],
  Solutions: [
    { label: "Luxury Villas",    href: "/solutions/villas" },
    { label: "Boutique Hotels",  href: "/solutions/hotels" },
    { label: "Resorts",          href: "/solutions/resorts" },
    { label: "Travel Operators", href: "/solutions/travel" },
  ],
  Resources: [
    { label: "Documentation", href: "/docs" },
    { label: "Blog",          href: "/blog" },
    { label: "Case Studies",  href: "/case-studies" },
    { label: "Changelog",     href: "/changelog" },
    { label: "API Reference", href: "/api-docs" },
    { label: "Status",        href: "/status" },
  ],
  Company: [
    { label: "About",       href: "/about" },
    { label: "Contact",     href: "/contact" },
    { label: "Book a demo", href: "/book-demo" },
  ],
  Legal: [
    { label: "Privacy Policy",      href: "/privacy" },
    { label: "Terms of Service",    href: "/terms" },
    { label: "Trust Center",        href: "/trust" },
    { label: "DPDP Compliance",     href: "/dpdp" },
    { label: "Security",            href: "/security" },
    { label: "Privacy & Grievances",href: "/grievance" },
  ],
};

export function MarketingFooter() {
  return (
    <footer
      style={{
        backgroundColor: "#003d41",
        borderTop: "1px solid rgba(255,255,255,0.08)",
      }}
    >
      {/* ── Main footer ──────────────────────────────────────────────── */}
      <div className="max-w-7xl mx-auto px-5 sm:px-8 pt-16 pb-10">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-8 lg:gap-10">

          {/* Brand column */}
          <div className="col-span-2 space-y-4">
            <div className="flex items-center gap-2.5">
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-sm"
                style={{ background: "linear-gradient(135deg, #00555a, #00888f)", color: "#ffffff" }}
              >
                G
              </div>
              <span className="font-bold text-lg tracking-tight text-white">
                Gen<span style={{ color: "#ffc94b" }}>Haip</span>
              </span>
            </div>
            <p className="text-sm leading-relaxed max-w-xs" style={{ color: "rgba(255,255,255,0.40)" }}>
              AI-powered guest intelligence for luxury hospitality. Unified inbox, call analytics,
              and CRM built for India&apos;s premium hospitality sector.
            </p>
            <div className="flex items-center gap-3 pt-2">
              <a
                href="https://wa.me/918147698153"
                target="_blank"
                rel="noopener noreferrer"
                className="w-10 h-10 rounded-lg flex items-center justify-center transition-colors duration-150"
                style={{ backgroundColor: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.35)" }}
                aria-label="WhatsApp"
                onMouseEnter={e => {
                  (e.currentTarget as HTMLElement).style.color = "#25D366";
                  (e.currentTarget as HTMLElement).style.backgroundColor = "rgba(37,211,102,0.12)";
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLElement).style.color = "rgba(255,255,255,0.35)";
                  (e.currentTarget as HTMLElement).style.backgroundColor = "rgba(255,255,255,0.06)";
                }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z" />
                </svg>
              </a>
            </div>
          </div>

          {/* Link columns */}
          {Object.entries(links).map(([col, items]) => (
            <div key={col}>
              <h3
                className="text-xs font-semibold uppercase tracking-widest mb-4"
                style={{ color: "#ffffff" }}
              >
                {col}
              </h3>
              <ul className="space-y-2.5">
                {items.map(item => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className="text-sm transition-colors duration-150"
                      style={{ color: "#64748B" }}
                      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#ffc94b"; }}
                      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#64748B"; }}
                    >
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      {/* ── Bottom bar ───────────────────────────────────────────────── */}
      <div style={{ borderTop: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="max-w-7xl mx-auto px-5 sm:px-8 py-5 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-xs" style={{ color: "#475569" }}>
            © {new Date().getFullYear()} HAIP Technologies Pvt. Ltd. All rights reserved.
          </p>
          <div className="flex items-center gap-5">
            <span className="text-xs" style={{ color: "#475569" }}>Made in India 🇮🇳</span>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />
              <span className="text-xs" style={{ color: "#475569" }}>All systems operational</span>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
