"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useThemeMode } from "@/hooks/useThemeMode";
import {
  Menu, X, ChevronDown, Inbox, Phone, Users, MessageSquare, Star, BarChart2,
  Building2, Hotel, Trees, Plane, FileText, Shield, BookOpen, Activity, Sparkles,
  Sun, Moon,
} from "lucide-react";

const features = [
  { label: "Unified Inbox", href: "/features#inbox", desc: "WhatsApp, calls, DMs in one place", icon: <Inbox size={14} className="text-teal-400" /> },
  { label: "AI Call Intelligence", href: "/features#calls", desc: "Auto-transcription & QA scoring", icon: <Phone size={14} className="text-purple-400" /> },
  { label: "Hospitality CRM", href: "/features#crm", desc: "Guests, properties, reservations", icon: <Users size={14} className="text-blue-400" /> },
  { label: "WhatsApp Automation", href: "/features#whatsapp", desc: "Bulk messaging & automation", icon: <MessageSquare size={14} className="text-green-400" /> },
  { label: "Auto QA & Compliance", href: "/features#qa", desc: "DPDP-compliant call review", icon: <Star size={14} className="text-amber-400" /> },
  { label: "AI Insights", href: "/features#insights", desc: "Revenue intelligence & forecasting", icon: <BarChart2 size={14} className="text-cyan-400" /> },
];

const solutions = [
  { label: "Luxury Villas", href: "/solutions/villas", desc: "Multi-villa pipeline + chef bookings", icon: <Building2 size={14} className="text-teal-400" /> },
  { label: "Boutique Hotels", href: "/solutions/hotels", desc: "Front desk + OTA + direct booking", icon: <Hotel size={14} className="text-amber-400" /> },
  { label: "Resorts", href: "/solutions/resorts", desc: "Multi-property · multi-department", icon: <Trees size={14} className="text-green-400" /> },
  { label: "Travel Operators", href: "/solutions/travel", desc: "Experiential trips · caravans · DMC", icon: <Plane size={14} className="text-cyan-400" /> },
];

const resources = [
  { label: "Case studies", href: "/case-studies", desc: "How real teams use HAIP", icon: <FileText size={14} className="text-teal-400" /> },
  { label: "Security & trust", href: "/security", desc: "DPDP · KMS · audit · sub-processors", icon: <Shield size={14} className="text-green-400" /> },
  { label: "Documentation", href: "/docs", desc: "Setup, API and integration guides", icon: <BookOpen size={14} className="text-cyan-400" /> },
  { label: "Changelog", href: "/changelog", desc: "What shipped recently", icon: <Sparkles size={14} className="text-purple-400" /> },
  { label: "System status", href: "/status", desc: "Live uptime and incident log", icon: <Activity size={14} className="text-amber-400" /> },
];

export function MarketingNav() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<"features" | "solutions" | "resources" | null>(null);
  const { isDark, toggle: toggleTheme } = useThemeMode();

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <header
      data-mkt-nav
      className={cn(
        "fixed top-0 left-0 right-0 z-50 transition-all duration-300",
        scrolled
          ? "backdrop-blur-xl border-b shadow-xl shadow-black/30"
          : "bg-transparent"
      )}
      style={scrolled ? { backgroundColor: "color-mix(in srgb, var(--mkt-bg) 95%, transparent)", borderColor: "var(--mkt-border)" } : undefined}
    >
      <div className="max-w-7xl mx-auto px-5 sm:px-8 flex items-center h-20 gap-8">
        {/* Logo */}
        <Link href="/" className="flex items-center flex-shrink-0">
          <img src="/logo.png" alt="HAIP" className="h-16 w-auto object-contain" />
        </Link>

        {/* Desktop Nav */}
        <nav className="hidden lg:flex items-center gap-1 flex-1">
          <Dropdown label="Features" open={openMenu === "features"} onEnter={() => setOpenMenu("features")} onLeave={() => setOpenMenu(null)}>
            <div className="rounded-xl shadow-2xl shadow-black/50 p-2 w-80" style={{ backgroundColor: "var(--mkt-panel)", border: "1px solid var(--mkt-border)" }}>
              {features.map(f => (
                <Link key={f.href} href={f.href} className="flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-white/5 transition-colors group">
                  <div className="w-7 h-7 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0 mt-0.5">{f.icon}</div>
                  <div className="min-w-0">
                    <span className="text-sm font-medium group-hover:text-[var(--mkt-gold)] transition-colors block" style={{ color: "var(--mkt-text)" }}>{f.label}</span>
                    <span className="text-xs mt-0.5 block" style={{ color: "color-mix(in srgb, var(--mkt-text) 45%, transparent)" }}>{f.desc}</span>
                  </div>
                </Link>
              ))}
            </div>
          </Dropdown>

          <Dropdown label="Solutions" open={openMenu === "solutions"} onEnter={() => setOpenMenu("solutions")} onLeave={() => setOpenMenu(null)}>
            <div className="rounded-xl shadow-2xl shadow-black/50 p-2 w-80" style={{ backgroundColor: "var(--mkt-panel)", border: "1px solid var(--mkt-border)" }}>
              {solutions.map(s => (
                <Link key={s.href} href={s.href} className="flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-white/5 transition-colors group">
                  <div className="w-7 h-7 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0 mt-0.5">{s.icon}</div>
                  <div className="min-w-0">
                    <span className="text-sm font-medium group-hover:text-[var(--mkt-jade)] transition-colors block" style={{ color: "var(--mkt-text)" }}>{s.label}</span>
                    <span className="text-xs mt-0.5 block" style={{ color: "color-mix(in srgb, var(--mkt-text) 45%, transparent)" }}>{s.desc}</span>
                  </div>
                </Link>
              ))}
            </div>
          </Dropdown>

          <Link href="/integrations" className="px-4 py-2 text-base transition-colors rounded-lg hover:bg-white/5" style={{ color: "color-mix(in srgb, var(--mkt-text) 70%, transparent)" }}>
            Integrations
          </Link>
          <Link href="/pricing" className="px-4 py-2 text-base transition-colors rounded-lg hover:bg-white/5" style={{ color: "color-mix(in srgb, var(--mkt-text) 70%, transparent)" }}>
            Pricing
          </Link>

          <Dropdown label="Resources" open={openMenu === "resources"} onEnter={() => setOpenMenu("resources")} onLeave={() => setOpenMenu(null)}>
            <div className="rounded-xl shadow-2xl shadow-black/50 p-2 w-80" style={{ backgroundColor: "var(--mkt-panel)", border: "1px solid var(--mkt-border)" }}>
              {resources.map(r => (
                <Link key={r.href} href={r.href} className="flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-white/5 transition-colors group">
                  <div className="w-7 h-7 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0 mt-0.5">{r.icon}</div>
                  <div className="min-w-0">
                    <span className="text-sm font-medium group-hover:text-[var(--mkt-jade)] transition-colors block" style={{ color: "var(--mkt-text)" }}>{r.label}</span>
                    <span className="text-xs mt-0.5 block" style={{ color: "color-mix(in srgb, var(--mkt-text) 45%, transparent)" }}>{r.desc}</span>
                  </div>
                </Link>
              ))}
            </div>
          </Dropdown>
        </nav>

        {/* Right actions */}
        <div className="hidden lg:flex items-center gap-2 ml-auto">
          <button
            onClick={toggleTheme}
            aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
            className="w-9 h-9 flex items-center justify-center rounded-lg text-white/50 hover:text-white hover:bg-white/8 transition-colors"
          >
            {isDark ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <Link href="/login" className="text-base transition-colors px-4 py-2" style={{ color: "color-mix(in srgb, var(--mkt-text) 70%, transparent)" }}>
            Sign in
          </Link>
          <Link
            href="/book-demo"
            className="px-5 py-2.5 text-base font-semibold rounded-xl transition-all border"
            style={{ color: "color-mix(in srgb, var(--mkt-text) 85%, transparent)", borderColor: "var(--mkt-border)" }}
          >
            Book demo
          </Link>
          <Link
            href="/register"
            className="px-5 py-2.5 text-base font-semibold rounded-xl transition-all"
            style={{ backgroundColor: "var(--mkt-gold)", color: "var(--mkt-bg)" }}
          >
            Start free trial
          </Link>
        </div>

        {/* Mobile toggle */}
        <button
          className="lg:hidden ml-auto p-3 text-white/70 hover:text-white"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label="Toggle menu"
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="lg:hidden border-t px-5 py-4 space-y-1 max-h-[calc(100vh-80px)] overflow-y-auto" style={{ backgroundColor: "var(--mkt-bg)", borderColor: "var(--mkt-border)" }}>
          <MobileSection title="Features" items={features} onClose={() => setMobileOpen(false)} />
          <MobileSection title="Solutions" items={solutions} onClose={() => setMobileOpen(false)} />
          <div className="h-px bg-white/8 my-2" />
          <MobileLink href="/integrations" onClose={() => setMobileOpen(false)}>Integrations</MobileLink>
          <MobileLink href="/pricing" onClose={() => setMobileOpen(false)}>Pricing</MobileLink>
          <MobileSection title="Resources" items={resources} onClose={() => setMobileOpen(false)} />
          <MobileLink href="/contact" onClose={() => setMobileOpen(false)}>Contact</MobileLink>
          <div className="h-px bg-white/8 my-2" />
          <button
            onClick={() => { toggleTheme(); }}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-white/70 hover:text-white hover:bg-white/5 rounded-lg transition-colors"
          >
            {isDark ? <Sun size={15} /> : <Moon size={15} />}
            {isDark ? "Switch to light mode" : "Switch to dark mode"}
          </button>
          <MobileLink href="/login" onClose={() => setMobileOpen(false)}>Sign in</MobileLink>
          <Link
            href="/book-demo"
            onClick={() => setMobileOpen(false)}
            className="block px-4 py-2.5 bg-white/5 hover:bg-white/10 text-white text-sm font-semibold rounded-xl text-center border border-white/10 mt-2"
          >
            Book demo
          </Link>
          <Link
            href="/register"
            onClick={() => setMobileOpen(false)}
            className="block px-4 py-2.5 text-sm font-semibold rounded-xl text-center"
            style={{ backgroundColor: "var(--mkt-gold)", color: "var(--mkt-bg)" }}
          >
            Start free trial
          </Link>
        </div>
      )}
    </header>
  );
}

function Dropdown({ label, open, onEnter, onLeave, children }: {
  label: string;
  open: boolean;
  onEnter: () => void;
  onLeave: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="relative" onMouseEnter={onEnter} onMouseLeave={onLeave}>
      <button className="flex items-center gap-1 px-4 py-2 text-base transition-colors rounded-lg hover:bg-white/5" style={{ color: "color-mix(in srgb, var(--mkt-text) 70%, transparent)" }}>
        {label} <ChevronDown size={14} className={cn("transition-transform", open && "rotate-180")} />
      </button>
      {open && <div className="absolute top-full left-0 pt-2">{children}</div>}
    </div>
  );
}

function MobileSection({ title, items, onClose }: {
  title: string;
  items: { label: string; href: string }[];
  onClose: () => void;
}) {
  return (
    <details className="group">
      <summary className="flex items-center justify-between px-3 py-2.5 text-sm font-semibold text-white/80 cursor-pointer list-none">
        {title}
        <ChevronDown size={14} className="group-open:rotate-180 transition-transform" />
      </summary>
      <div className="pl-3 pb-1">
        {items.map(it => (
          <Link key={it.href} href={it.href} onClick={onClose}
            className="block px-3 py-2 text-sm text-white/60 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
            {it.label}
          </Link>
        ))}
      </div>
    </details>
  );
}

function MobileLink({ href, children, onClose }: { href: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <Link href={href} onClick={onClose}
      className="block px-3 py-2.5 text-sm text-white/70 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
      {children}
    </Link>
  );
}
