"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import {
  Menu, X, ChevronDown, Inbox, Phone, Users, MessageSquare, Star, BarChart2,
  Building2, Hotel, Trees, Plane, FileText, Shield, BookOpen, Activity, Sparkles,
} from "lucide-react";

const features = [
  { label: "Unified Inbox", href: "/features#inbox", desc: "WhatsApp, calls, DMs in one place", icon: <Inbox size={14} className="text-indigo-400" /> },
  { label: "AI Call Intelligence", href: "/features#calls", desc: "Auto-transcription & QA scoring", icon: <Phone size={14} className="text-purple-400" /> },
  { label: "Hospitality CRM", href: "/features#crm", desc: "Guests, properties, reservations", icon: <Users size={14} className="text-blue-400" /> },
  { label: "WhatsApp Automation", href: "/features#whatsapp", desc: "Bulk messaging & automation", icon: <MessageSquare size={14} className="text-green-400" /> },
  { label: "Auto QA & Compliance", href: "/features#qa", desc: "DPDP-compliant call review", icon: <Star size={14} className="text-amber-400" /> },
  { label: "AI Insights", href: "/features#insights", desc: "Revenue intelligence & forecasting", icon: <BarChart2 size={14} className="text-cyan-400" /> },
];

const solutions = [
  { label: "Luxury Villas", href: "/solutions/villas", desc: "Multi-villa pipeline + chef bookings", icon: <Building2 size={14} className="text-indigo-400" /> },
  { label: "Boutique Hotels", href: "/solutions/hotels", desc: "Front desk + OTA + direct booking", icon: <Hotel size={14} className="text-amber-400" /> },
  { label: "Resorts", href: "/solutions/resorts", desc: "Multi-property · multi-department", icon: <Trees size={14} className="text-green-400" /> },
  { label: "Travel Operators", href: "/solutions/travel", desc: "Experiential trips · caravans · DMC", icon: <Plane size={14} className="text-cyan-400" /> },
];

const resources = [
  { label: "Case studies", href: "/case-studies", desc: "How real teams use HAIP", icon: <FileText size={14} className="text-indigo-400" /> },
  { label: "Security & trust", href: "/security", desc: "DPDP · KMS · audit · sub-processors", icon: <Shield size={14} className="text-green-400" /> },
  { label: "Documentation", href: "/docs", desc: "Setup, API and integration guides", icon: <BookOpen size={14} className="text-cyan-400" /> },
  { label: "Changelog", href: "/changelog", desc: "What shipped recently", icon: <Sparkles size={14} className="text-purple-400" /> },
  { label: "System status", href: "/status", desc: "Live uptime and incident log", icon: <Activity size={14} className="text-amber-400" /> },
];

export function MarketingNav() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<"features" | "solutions" | "resources" | null>(null);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <header
      className={cn(
        "fixed top-0 left-0 right-0 z-50 transition-all duration-300",
        scrolled
          ? "bg-[#0D1B4B]/95 backdrop-blur-xl border-b border-white/8 shadow-xl shadow-black/20"
          : "bg-transparent"
      )}
    >
      <div className="max-w-7xl mx-auto px-5 sm:px-8 flex items-center h-16 gap-6">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 flex-shrink-0">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center text-[#0a1f3a] font-bold text-sm shadow-lg shadow-blue-500/30">
            H
          </div>
          <span className="text-white font-bold text-lg tracking-tight">
            HA<span className="text-indigo-400">IP</span>
          </span>
        </Link>

        {/* Desktop Nav */}
        <nav className="hidden lg:flex items-center gap-1 flex-1">
          <Dropdown label="Features" open={openMenu === "features"} onEnter={() => setOpenMenu("features")} onLeave={() => setOpenMenu(null)}>
            <div className="bg-[#0f2744] border border-white/10 rounded-xl shadow-2xl shadow-black/40 p-2 w-80">
              {features.map(f => (
                <Link key={f.href} href={f.href} className="flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-white/5 transition-colors group">
                  <div className="w-7 h-7 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0 mt-0.5">{f.icon}</div>
                  <div className="min-w-0">
                    <span className="text-sm font-medium text-white group-hover:text-indigo-400 transition-colors block">{f.label}</span>
                    <span className="text-xs text-white/40 mt-0.5 block">{f.desc}</span>
                  </div>
                </Link>
              ))}
            </div>
          </Dropdown>

          <Dropdown label="Solutions" open={openMenu === "solutions"} onEnter={() => setOpenMenu("solutions")} onLeave={() => setOpenMenu(null)}>
            <div className="bg-[#0f2744] border border-white/10 rounded-xl shadow-2xl shadow-black/40 p-2 w-80">
              {solutions.map(s => (
                <Link key={s.href} href={s.href} className="flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-white/5 transition-colors group">
                  <div className="w-7 h-7 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0 mt-0.5">{s.icon}</div>
                  <div className="min-w-0">
                    <span className="text-sm font-medium text-white group-hover:text-indigo-400 transition-colors block">{s.label}</span>
                    <span className="text-xs text-white/40 mt-0.5 block">{s.desc}</span>
                  </div>
                </Link>
              ))}
            </div>
          </Dropdown>

          <Link href="/integrations" className="px-3 py-2 text-sm text-white/70 hover:text-white transition-colors rounded-lg hover:bg-white/5">
            Integrations
          </Link>
          <Link href="/pricing" className="px-3 py-2 text-sm text-white/70 hover:text-white transition-colors rounded-lg hover:bg-white/5">
            Pricing
          </Link>

          <Dropdown label="Resources" open={openMenu === "resources"} onEnter={() => setOpenMenu("resources")} onLeave={() => setOpenMenu(null)}>
            <div className="bg-[#0f2744] border border-white/10 rounded-xl shadow-2xl shadow-black/40 p-2 w-80">
              {resources.map(r => (
                <Link key={r.href} href={r.href} className="flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-white/5 transition-colors group">
                  <div className="w-7 h-7 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0 mt-0.5">{r.icon}</div>
                  <div className="min-w-0">
                    <span className="text-sm font-medium text-white group-hover:text-indigo-400 transition-colors block">{r.label}</span>
                    <span className="text-xs text-white/40 mt-0.5 block">{r.desc}</span>
                  </div>
                </Link>
              ))}
            </div>
          </Dropdown>
        </nav>

        {/* Right actions */}
        <div className="hidden lg:flex items-center gap-2 ml-auto">
          <Link href="/login" className="text-sm text-white/70 hover:text-white transition-colors px-3 py-2">
            Sign in
          </Link>
          <Link
            href="/book-demo"
            className="px-3.5 py-2 text-sm font-semibold text-white/85 hover:text-white border border-white/15 hover:border-white/30 rounded-xl transition-all"
          >
            Book demo
          </Link>
          <Link
            href="/register"
            className="px-4 py-2 bg-indigo-500 hover:bg-indigo-400 text-white text-sm font-semibold rounded-xl transition-all shadow-lg shadow-indigo-500/25 hover:shadow-indigo-400/35"
          >
            Start free trial
          </Link>
        </div>

        {/* Mobile toggle */}
        <button
          className="lg:hidden ml-auto p-2 text-white/70 hover:text-white"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label="Toggle menu"
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="lg:hidden bg-[#0D1B4B] border-t border-white/8 px-5 py-4 space-y-1 max-h-[calc(100vh-64px)] overflow-y-auto">
          <MobileSection title="Features" items={features} onClose={() => setMobileOpen(false)} />
          <MobileSection title="Solutions" items={solutions} onClose={() => setMobileOpen(false)} />
          <div className="h-px bg-white/8 my-2" />
          <MobileLink href="/integrations" onClose={() => setMobileOpen(false)}>Integrations</MobileLink>
          <MobileLink href="/pricing" onClose={() => setMobileOpen(false)}>Pricing</MobileLink>
          <MobileSection title="Resources" items={resources} onClose={() => setMobileOpen(false)} />
          <MobileLink href="/contact" onClose={() => setMobileOpen(false)}>Contact</MobileLink>
          <div className="h-px bg-white/8 my-2" />
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
            className="block px-4 py-2.5 bg-indigo-500 text-white text-sm font-semibold rounded-xl text-center"
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
      <button className="flex items-center gap-1 px-3 py-2 text-sm text-white/70 hover:text-white transition-colors rounded-lg hover:bg-white/5">
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
