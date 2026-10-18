"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { Menu, X, ChevronDown, Inbox, Phone, Users, MessageSquare, Star, BarChart2, Building2, Hotel, Plane, FileText, Shield, BookOpen, Sparkles, ArrowRight, Calculator } from "@/lib/icons";
import { Trees, Activity } from "lucide-react";

// ─── Nav data ─────────────────────────────────────────────────────────────────

const features = [
  { label: "Unified Inbox",        href: "/features#inbox",    desc: "WhatsApp, calls, DMs in one place",      icon: <Inbox size={14} style={{ color: "#00555a" }} /> },
  { label: "AI Call Intelligence", href: "/features#calls",    desc: "Auto-transcription & QA scoring",         icon: <Phone size={14} style={{ color: "#00555a" }} /> },
  { label: "Hospitality CRM",      href: "/features#crm",     desc: "Guests, properties, reservations",        icon: <Users size={14} style={{ color: "#00555a" }} /> },
  { label: "WhatsApp Automation",  href: "/features#whatsapp",desc: "Bulk messaging & automation",             icon: <MessageSquare size={14} style={{ color: "#00555a" }} /> },
  { label: "Auto QA & Compliance", href: "/features#qa",      desc: "DPDP-compliant call review",              icon: <Star size={14} style={{ color: "#ffc94b" }} /> },
  { label: "AI Insights",          href: "/features#insights",desc: "Revenue intelligence & forecasting",      icon: <BarChart2 size={14} style={{ color: "#00555a" }} /> },
];

const solutions = [
  { label: "Luxury Villas",    href: "/solutions/villas",  desc: "Multi-villa pipeline + chef bookings",   icon: <Building2 size={14} style={{ color: "#00555a" }} /> },
  { label: "Boutique Hotels",  href: "/solutions/hotels",  desc: "Front desk + OTA + direct booking",      icon: <Hotel size={14} style={{ color: "#ffc94b" }} /> },
  { label: "Resorts",          href: "/solutions/resorts", desc: "Multi-property · multi-department",      icon: <Trees size={14} style={{ color: "#00555a" }} /> },
  { label: "Travel Operators", href: "/solutions/travel",  desc: "Experiential trips · caravans · DMC",    icon: <Plane size={14} style={{ color: "#00555a" }} /> },
];

const resources = [
  { label: "Free property assessment", href: "/assess", desc: "Revenue, investment and payback estimate", icon: <Calculator size={14} className="text-[var(--mkt-gold)]" /> },
  { label: "Case studies",    href: "/case-studies", desc: "How real teams use HAIP",                 icon: <FileText size={14} style={{ color: "#00555a" }} /> },
  { label: "Security & trust",href: "/security",     desc: "DPDP · KMS · audit · sub-processors",    icon: <Shield size={14} style={{ color: "#00555a" }} /> },
  { label: "Documentation",   href: "/docs",         desc: "Setup, API and integration guides",       icon: <BookOpen size={14} style={{ color: "#00555a" }} /> },
  { label: "Changelog",       href: "/changelog",    desc: "What shipped recently",                   icon: <Sparkles size={14} style={{ color: "#ffc94b" }} /> },
  { label: "System status",   href: "/status",       desc: "Live uptime and incident log",            icon: <Activity size={14} style={{ color: "#00555a" }} /> },
];

// ─── Framer Motion variants ───────────────────────────────────────────────────

const navContainer = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.05, delayChildren: 0.1 } },
};

const navItem = {
  hidden:  { opacity: 0, y: -6 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut" as const } },
};

const mobileMenu = {
  hidden:  { opacity: 0, height: 0 },
  visible: { opacity: 1, height: "auto", transition: { duration: 0.22, ease: "easeOut" as const } },
  exit:    { opacity: 0, height: 0,    transition: { duration: 0.18, ease: "easeIn" as const } },
};

// ─── Component ────────────────────────────────────────────────────────────────

export function MarketingNav() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<"features" | "solutions" | "resources" | null>(null);

  useEffect(() => {
    document.documentElement.classList.remove("dark");
  }, []);

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
          ? "backdrop-blur-md border-b shadow-sm"
          : "bg-transparent"
      )}
      style={scrolled
        ? { backgroundColor: "rgba(255,255,255,0.92)", borderColor: "#E2E8F0" }
        : undefined}
    >
      <div className="max-w-7xl mx-auto px-5 sm:px-8 flex items-center h-20 gap-8">

        {/* Logo */}
        <Link href="/" className="flex items-center flex-shrink-0 hover:opacity-80 transition-opacity duration-150">
          <img src="/logo-wordmark.png" alt="HAIP" className="h-8 w-auto object-contain" />
        </Link>

        {/* Desktop Nav — stagger on mount */}
        <motion.nav
          className="hidden lg:flex items-center gap-1 flex-1"
          variants={navContainer}
          initial="hidden"
          animate="visible"
        >
          <motion.div variants={navItem}>
            <Dropdown label="Features" open={openMenu === "features"} onEnter={() => setOpenMenu("features")} onLeave={() => setOpenMenu(null)}>
              <DropPanel items={features} />
            </Dropdown>
          </motion.div>

          <motion.div variants={navItem}>
            <Dropdown label="Solutions" open={openMenu === "solutions"} onEnter={() => setOpenMenu("solutions")} onLeave={() => setOpenMenu(null)}>
              <DropPanel items={solutions} />
            </Dropdown>
          </motion.div>

          <motion.div variants={navItem}>
            <Link
              href="/integrations"
              className="px-4 py-2 text-sm font-medium rounded-lg transition-colors duration-150"
              style={{ color: "#475569" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#475569"; }}
            >
              Integrations
            </Link>
          </motion.div>

          <motion.div variants={navItem}>
            <Link
              href="/pricing"
              className="px-4 py-2 text-sm font-medium rounded-lg transition-colors duration-150"
              style={{ color: "#475569" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#475569"; }}
            >
              Pricing
            </Link>
          </motion.div>

          <motion.div variants={navItem}>
            <Dropdown label="Resources" open={openMenu === "resources"} onEnter={() => setOpenMenu("resources")} onLeave={() => setOpenMenu(null)}>
              <DropPanel items={resources} />
            </Dropdown>
          </motion.div>
        </motion.nav>

        {/* Right actions — stagger alongside nav */}
        <motion.div
          className="hidden lg:flex items-center gap-2 ml-auto"
          variants={navContainer}
          initial="hidden"
          animate="visible"
        >
          <motion.div variants={navItem}>
            <Link
              href="/login"
              className="text-sm font-medium px-4 py-2 rounded-lg transition-colors duration-150"
              style={{ color: "#475569" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#475569"; }}
            >
              Sign in
            </Link>
          </motion.div>

          <motion.div variants={navItem}>
            <Link
              href="/book-demo"
              className="inline-flex items-center gap-1.5 px-5 py-2.5 text-sm font-semibold rounded-xl transition-all duration-200 shadow-sm"
              style={{ backgroundColor: "#00555a", color: "#ffffff" }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLElement).style.backgroundColor = "#004a4f";
                (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 12px rgba(0,85,90,0.25)";
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLElement).style.backgroundColor = "#00555a";
                (e.currentTarget as HTMLElement).style.boxShadow = "0 1px 3px rgba(0,85,90,0.15)";
              }}
            >
              Book demo <ArrowRight size={14} />
            </Link>
          </motion.div>

          <motion.div variants={navItem}>
            <Link
              href="/register"
              className="inline-flex items-center gap-1.5 px-5 py-2.5 text-sm font-semibold rounded-xl transition-all duration-200"
              style={{ backgroundColor: "#ffc94b", color: "#00555a" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}
            >
              Start free trial
            </Link>
          </motion.div>
        </motion.div>

        {/* Mobile toggle */}
        <button
          className="lg:hidden ml-auto p-3 rounded-lg transition-colors duration-150"
          style={{ color: "#475569" }}
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label="Toggle menu"
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile menu — animated slide down */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            key="mobile-menu"
            variants={mobileMenu}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="lg:hidden overflow-hidden border-t"
            style={{ backgroundColor: "#FFFFFF", borderColor: "#E2E8F0" }}
          >
            <div className="px-5 py-4 space-y-1">
              <MobileSection title="Features"  items={features}  onClose={() => setMobileOpen(false)} />
              <MobileSection title="Solutions" items={solutions} onClose={() => setMobileOpen(false)} />
              <div className="h-px my-2" style={{ backgroundColor: "#E2E8F0" }} />
              <MobileLink href="/integrations" onClose={() => setMobileOpen(false)}>Integrations</MobileLink>
              <MobileLink href="/pricing"      onClose={() => setMobileOpen(false)}>Pricing</MobileLink>
              <MobileSection title="Resources" items={resources} onClose={() => setMobileOpen(false)} />
              <MobileLink href="/contact"      onClose={() => setMobileOpen(false)}>Contact</MobileLink>
              <div className="h-px my-2" style={{ backgroundColor: "#E2E8F0" }} />
              <MobileLink href="/login"        onClose={() => setMobileOpen(false)}>Sign in</MobileLink>
              <Link
                href="/book-demo"
                onClick={() => setMobileOpen(false)}
                className="flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-xl mt-2 transition-colors duration-150"
                style={{ backgroundColor: "#00555a", color: "#ffffff" }}
              >
                Book demo <ArrowRight size={14} />
              </Link>
              <Link
                href="/register"
                onClick={() => setMobileOpen(false)}
                className="flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-xl transition-colors duration-150"
                style={{ backgroundColor: "#ffc94b", color: "#00555a" }}
              >
                Start free trial
              </Link>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}

// ─── Dropdown wrapper ─────────────────────────────────────────────────────────

function Dropdown({ label, open, onEnter, onLeave, children }: {
  label: string;
  open: boolean;
  onEnter: () => void;
  onLeave: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="relative" onMouseEnter={onEnter} onMouseLeave={onLeave}>
      <button
        className="flex items-center gap-1 px-4 py-2 text-sm font-medium rounded-lg transition-colors duration-150"
        style={{ color: open ? "#00555a" : "#475569" }}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
        onMouseLeave={e => { if (!open) (e.currentTarget as HTMLElement).style.color = "#475569"; }}
      >
        {label}
        <ChevronDown
          size={13}
          className="transition-transform duration-200"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
        />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            key="dropdown"
            className="absolute top-full left-0 pt-2"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0, transition: { duration: 0.15, ease: "easeOut" as const } }}
            exit={{ opacity: 0, y: -4, transition: { duration: 0.1 } }}
          >
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── Dropdown panel ───────────────────────────────────────────────────────────

function DropPanel({ items }: { items: { label: string; href: string; desc: string; icon: React.ReactNode }[] }) {
  return (
    <div
      className="rounded-xl shadow-xl p-2 w-72"
      style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0" }}
    >
      {items.map(item => (
        <Link
          key={item.href}
          href={item.href}
          className="flex items-start gap-3 px-3 py-2.5 rounded-lg transition-colors duration-150 group"
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#f0fafa"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
        >
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
            style={{ backgroundColor: "rgba(0,85,90,0.07)" }}
          >
            {item.icon}
          </div>
          <div className="min-w-0">
            <span
              className="text-sm font-medium block transition-colors duration-150"
              style={{ color: "#0F172A" }}
            >
              {item.label}
            </span>
            <span className="text-xs mt-0.5 block" style={{ color: "#64748B" }}>{item.desc}</span>
          </div>
        </Link>
      ))}
    </div>
  );
}

// ─── Mobile section ───────────────────────────────────────────────────────────

function MobileSection({ title, items, onClose }: {
  title: string;
  items: { label: string; href: string }[];
  onClose: () => void;
}) {
  return (
    <details className="group">
      <summary
        className="flex items-center justify-between px-3 py-2.5 text-sm font-semibold cursor-pointer list-none rounded-lg"
        style={{ color: "#0F172A" }}
      >
        {title}
        <ChevronDown size={13} className="group-open:rotate-180 transition-transform duration-200" style={{ color: "#64748B" }} />
      </summary>
      <div className="pl-3 pb-1">
        {items.map(it => (
          <Link
            key={it.href}
            href={it.href}
            onClick={onClose}
            className="block px-3 py-2 text-sm rounded-lg transition-colors duration-150"
            style={{ color: "#475569" }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#475569"; }}
          >
            {it.label}
          </Link>
        ))}
      </div>
    </details>
  );
}

function MobileLink({ href, children, onClose }: { href: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <Link
      href={href}
      onClick={onClose}
      className="block px-3 py-2.5 text-sm rounded-lg transition-colors duration-150"
      style={{ color: "#0F172A" }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#00555a"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#0F172A"; }}
    >
      {children}
    </Link>
  );
}
