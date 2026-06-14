"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  Phone, MessageSquare, Users, Instagram,
  ArrowRight, ChevronDown, Check, Sparkles, BadgeCheck, Brain,
  Mic2, Bot, BarChart2, Zap, FileText, AlertTriangle,
} from "lucide-react";

// ─── Communication Modules (no AI required) ───────────────────────────────────
const COMM_MODULES = [
  {
    id: "wa",
    icon: <MessageSquare size={18} />,
    name: "WhatsApp",
    desc: "Unified inbox · Templates · Campaigns · Subscriber management · Automations",
    ppm: 199,
    popular: true,
  },
  {
    id: "ig",
    icon: <Instagram size={18} />,
    name: "Instagram DM",
    desc: "IG inbox · Guest auto-linking · Conversation history",
    ppm: 99,
    popular: false,
  },
  {
    id: "ivr",
    icon: <Phone size={18} />,
    name: "IVR & Calls",
    desc: "Call capture · Recording storage · Missed call detection · Agent forwarding · Call log",
    ppm: 299,
    popular: true,
  },
  {
    id: "crm",
    icon: <Users size={18} />,
    name: "CRM & Leads360",
    desc: "Guest profiles · Inquiry pipeline (Kanban) · Internal notes · Source attribution",
    ppm: 149,
    popular: false,
  },
];

// ─── AI Sub-features ──────────────────────────────────────────────────────────
const AI_ADDONS = [
  {
    id: "call_intelligence",
    icon: <Mic2 size={16} />,
    name: "AI Call Intelligence",
    desc: "Transcription (Sarvam AI, Indian-accent optimised) · Auto wrap-up cards · QA scoring · Missed revenue flags",
    ppm: 399,
    requires: "ivr",
    requiresLabel: "IVR & Calls",
  },
  {
    id: "concierge",
    icon: <Bot size={16} />,
    name: "AI Concierge",
    desc: "AI-drafted WhatsApp replies in your brand voice · Shadow mode (human approval) · Autonomous mode with confidence threshold",
    ppm: 249,
    requires: "wa",
    requiresLabel: "WhatsApp",
  },
  {
    id: "insights",
    icon: <BarChart2 size={16} />,
    name: "AI Insights & Analytics",
    desc: "Conversion funnel · Agent scorecards · Channel attribution · Revenue intelligence · Direct vs OTA mix",
    ppm: 199,
    requires: null,
    requiresLabel: null,
  },
  {
    id: "automations",
    icon: <Zap size={16} />,
    name: "AI Automations",
    desc: "Trigger-based rules: new inquiry, no response 2h/24h, check-in D-1, check-out D-1, call completed",
    ppm: 99,
    requires: null,
    requiresLabel: null,
  },
  {
    id: "reports",
    icon: <FileText size={16} />,
    name: "AI Reports",
    desc: "Weekly agent digest · Monthly executive report · Owner daily dashboard · After-call wrap-up PDF",
    ppm: 149,
    requires: null,
    requiresLabel: null,
  },
];

const MIN_BILL = 1500;
const fmt = (n: number) => "₹" + Math.round(n).toLocaleString("en-IN");

// ─── Motion variants ──────────────────────────────────────────────────────────
const fadeUp = { hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" } } };
const VP = { once: true, margin: "-40px" } as const;

// ─── FAQ ──────────────────────────────────────────────────────────────────────
const FAQS = [
  { q: "Is there a free trial?",              a: "Yes — 14 days free, no credit card required. We'll set up your account and walk you through the platform." },
  { q: "How does per-property pricing work?", a: "You pay for each property you connect. Add or remove properties any time — billing adjusts automatically the next month." },
  { q: "Do I have to take the AI module?",    a: "No. AI is completely optional. You can use just WhatsApp, IVR, Instagram DM, and CRM — no AI involved. Add AI features whenever you're ready." },
  { q: "Can I pick individual AI features?",  a: "Yes. AI is not one big module — it's 5 separate add-ons (Call Intelligence, Concierge, Insights, Automations, Reports). Enable only what you need." },
  { q: "What's the minimum monthly charge?",  a: "₹1,500/month — this applies if your calculated total falls below that threshold." },
  { q: "Is GST included?",                    a: "Prices shown are exclusive of GST (18%). GST is added at checkout." },
  { q: "Are annual plans available?",         a: "Yes — pay annually and save 20%. Switch to annual at any time from your billing settings." },
  { q: "No lock-in?",                         a: "None. Month-to-month. Cancel any time. Add or remove modules at the start of each billing cycle." },
];

function FAQAccordion() {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="divide-y" style={{ borderColor: "#E2E8F0" }}>
      {FAQS.map((f, i) => (
        <div key={i}>
          <button
            className="w-full flex items-center justify-between py-5 text-left gap-4"
            onClick={() => setOpen(open === i ? null : i)}
          >
            <span className="font-semibold" style={{ color: "#0F172A" }}>{f.q}</span>
            <ChevronDown
              size={16}
              className="flex-shrink-0 transition-transform duration-200"
              style={{ color: "#00555a", transform: open === i ? "rotate(180deg)" : "rotate(0deg)" }}
            />
          </button>
          <AnimatePresence>
            {open === i && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1, transition: { duration: 0.2, ease: "easeOut" } }}
                exit={{ height: 0, opacity: 0, transition: { duration: 0.15 } }}
                className="overflow-hidden"
              >
                <p className="pb-5 leading-relaxed" style={{ color: "#475569" }}>{f.a}</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      ))}
    </div>
  );
}

// ─── Module Card ──────────────────────────────────────────────────────────────
function ModuleCard({
  id, icon, name, desc, ppm, popular, on, onToggle,
}: {
  id: string; icon: React.ReactNode; name: string; desc: string; ppm: number;
  popular?: boolean; on: boolean; onToggle: () => void;
}) {
  return (
    <motion.button
      variants={fadeUp}
      onClick={onToggle}
      className="relative rounded-2xl border-2 p-5 text-left transition-all duration-150 w-full"
      style={on
        ? { borderColor: "#00555a", backgroundColor: "rgba(0,85,90,0.04)", boxShadow: "0 0 0 4px rgba(0,85,90,0.06)" }
        : { borderColor: "#E2E8F0", backgroundColor: "#ffffff" }
      }
      onMouseEnter={e => { if (!on) (e.currentTarget as HTMLElement).style.borderColor = "rgba(0,85,90,0.30)"; }}
      onMouseLeave={e => { if (!on) (e.currentTarget as HTMLElement).style.borderColor = "#E2E8F0"; }}
    >
      {on && (
        <div className="absolute top-3 right-3 w-5 h-5 rounded-full flex items-center justify-center" style={{ backgroundColor: "#00555a" }}>
          <Check size={10} className="text-white" />
        </div>
      )}
      <div className="w-9 h-9 rounded-xl flex items-center justify-center mb-3"
        style={{ backgroundColor: on ? "rgba(0,85,90,0.12)" : "#F8FAFC" }}>
        <span style={{ color: on ? "#00555a" : "#94A3B8" }}>{icon}</span>
      </div>
      <div className="flex items-start justify-between gap-2 mb-1">
        <p className="text-sm font-semibold leading-snug" style={{ color: on ? "#003d41" : "#0F172A" }}>{name}</p>
        {popular && (
          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0"
            style={{ backgroundColor: "rgba(255,201,75,0.20)", color: "#92400E" }}>Popular</span>
        )}
      </div>
      <p className="text-xs mb-3 leading-relaxed" style={{ color: on ? "#00555a" : "#64748B" }}>{desc}</p>
      <p className="text-sm font-bold" style={{ color: on ? "#00555a" : "#94A3B8" }}>{fmt(ppm)} / property / mo</p>
    </motion.button>
  );
}

// ─── AI Add-on Row ────────────────────────────────────────────────────────────
function AIAddonRow({
  id, icon, name, desc, ppm, requires, requiresLabel,
  on, onToggle, commEnabled,
}: {
  id: string; icon: React.ReactNode; name: string; desc: string; ppm: number;
  requires: string | null; requiresLabel: string | null;
  on: boolean; onToggle: () => void; commEnabled: (id: string) => boolean;
}) {
  const missingDep = requires && !commEnabled(requires);
  return (
    <motion.button
      variants={fadeUp}
      onClick={onToggle}
      className="relative rounded-xl border-2 p-4 text-left transition-all duration-150 w-full"
      style={on
        ? { borderColor: "#7c3aed", backgroundColor: "rgba(124,58,237,0.04)", boxShadow: "0 0 0 3px rgba(124,58,237,0.06)" }
        : { borderColor: "#E2E8F0", backgroundColor: "#ffffff" }
      }
      onMouseEnter={e => { if (!on) (e.currentTarget as HTMLElement).style.borderColor = "rgba(124,58,237,0.30)"; }}
      onMouseLeave={e => { if (!on) (e.currentTarget as HTMLElement).style.borderColor = "#E2E8F0"; }}
    >
      {on && (
        <div className="absolute top-3 right-3 w-5 h-5 rounded-full flex items-center justify-center" style={{ backgroundColor: "#7c3aed" }}>
          <Check size={10} className="text-white" />
        </div>
      )}
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
          style={{ backgroundColor: on ? "rgba(124,58,237,0.12)" : "#F8FAFC" }}>
          <span style={{ color: on ? "#7c3aed" : "#94A3B8" }}>{icon}</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <p className="text-sm font-semibold" style={{ color: on ? "#4c1d95" : "#0F172A" }}>{name}</p>
            <span className="text-xs font-bold px-1.5 py-0.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: "rgba(124,58,237,0.10)", color: "#7c3aed" }}>{fmt(ppm)}/prop/mo</span>
          </div>
          <p className="text-xs leading-relaxed" style={{ color: on ? "#6d28d9" : "#64748B" }}>{desc}</p>
          {missingDep && (
            <div className="flex items-center gap-1 mt-2">
              <AlertTriangle size={11} style={{ color: "#d97706" }} />
              <span className="text-[10px] font-medium" style={{ color: "#d97706" }}>
                Requires {requiresLabel} module
              </span>
            </div>
          )}
        </div>
      </div>
    </motion.button>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function PricingPage() {
  const [numProps, setNumProps] = useState(10);
  const [commSelected, setCommSelected] = useState<Set<string>>(new Set(["wa", "ivr"]));
  const [aiOpen, setAiOpen] = useState(false);
  const [aiSelected, setAiSelected] = useState<Set<string>>(new Set());
  const [annual, setAnnual] = useState(false);

  const toggleComm = (id: string) =>
    setCommSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const toggleAI = (id: string) =>
    setAiSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const commEnabled = (id: string) => commSelected.has(id);

  const { commRows, aiRows, bill, minApplied, perProp, totalRaw } = useMemo(() => {
    let commTotal = 0;
    const commRows: { label: string; value: string }[] = [];
    for (const mod of COMM_MODULES) {
      if (!commSelected.has(mod.id)) continue;
      const r = mod.ppm * numProps;
      commTotal += r;
      commRows.push({ label: `${mod.name} · ${numProps} × ${fmt(mod.ppm)}`, value: fmt(r) });
    }
    let aiTotal = 0;
    const aiRows: { label: string; value: string }[] = [];
    for (const addon of AI_ADDONS) {
      if (!aiSelected.has(addon.id)) continue;
      const r = addon.ppm * numProps;
      aiTotal += r;
      aiRows.push({ label: `${addon.name} · ${numProps} × ${fmt(addon.ppm)}`, value: fmt(r) });
    }
    const totalRaw = commTotal + aiTotal;
    const hasAny = commSelected.size > 0 || aiSelected.size > 0;
    const minApplied = hasAny && totalRaw < MIN_BILL;
    const base = minApplied ? MIN_BILL : totalRaw;
    const bill = annual ? Math.round(base * 0.8) : base;
    const perProp = numProps > 0 && bill > 0 ? Math.round(bill / numProps) : 0;
    return { commRows, aiRows, bill, minApplied, perProp, totalRaw };
  }, [commSelected, aiSelected, numProps, annual]);

  const hasSelection = commSelected.size > 0 || aiSelected.size > 0;

  return (
    <div className="bg-white">

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden py-28 px-5 sm:px-8" style={{ backgroundColor: "#003d41" }}>
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-32 -right-32 rounded-full" style={{ width: 480, height: 480, background: "radial-gradient(circle, rgba(255,201,75,0.07) 0%, transparent 70%)" }} />
          <div className="absolute -bottom-24 -left-16 rounded-full" style={{ width: 360, height: 360, background: "radial-gradient(circle, rgba(0,85,90,0.35) 0%, transparent 70%)" }} />
        </div>
        <div className="max-w-2xl mx-auto text-center relative">
          <motion.div variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.09 } } }} initial="hidden" animate="visible">
            <motion.div variants={fadeUp} className="flex items-center justify-center gap-2 mb-6">
              <span className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider"
                style={{ backgroundColor: "rgba(255,201,75,0.15)", color: "#ffc94b" }}>
                <Sparkles size={11} /> Pricing
              </span>
            </motion.div>
            <motion.h1 variants={fadeUp} className="font-black tracking-tight text-white mb-5"
              style={{ fontSize: "clamp(38px, 5.5vw, 60px)", lineHeight: 1.08 }}>
              Pay only for<br /><span style={{ color: "#ffc94b" }}>what you use</span>
            </motion.h1>
            <motion.p variants={fadeUp} className="text-lg leading-relaxed mb-10"
              style={{ color: "rgba(255,255,255,0.60)", maxWidth: 460, margin: "0 auto 2.5rem" }}>
              Pick communication channels. Add AI only if you want it.<br />
              Per property, per month. No platform fees. No lock-ins.
            </motion.p>
            <motion.div variants={fadeUp} className="flex items-center justify-center flex-wrap gap-6">
              {[
                { stat: "14-day", label: "free trial" },
                { stat: "₹1,500", label: "min/month" },
                { stat: "20%", label: "off annual" },
              ].map(s => (
                <div key={s.label} className="text-center">
                  <p className="font-black tabular-nums" style={{ fontSize: 22, color: "#ffc94b", lineHeight: 1 }}>{s.stat}</p>
                  <p className="text-xs mt-0.5" style={{ color: "rgba(255,255,255,0.40)" }}>{s.label}</p>
                </div>
              ))}
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* ── Calculator ────────────────────────────────────────────────────── */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-3xl mx-auto">

          {/* Annual toggle */}
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="flex items-center justify-center gap-3 mb-12">
            <span className="text-sm font-medium" style={{ color: annual ? "#94A3B8" : "#0F172A" }}>Monthly</span>
            <button onClick={() => setAnnual(a => !a)}
              className="relative w-12 h-6 rounded-full transition-colors duration-200"
              style={{ backgroundColor: annual ? "#00555a" : "#E2E8F0" }}>
              <span className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow-sm transition-transform duration-200"
                style={{ transform: annual ? "translateX(24px)" : "translateX(0)" }} />
            </button>
            <span className="text-sm font-medium" style={{ color: annual ? "#0F172A" : "#94A3B8" }}>
              Annual
              <span className="ml-2 text-xs font-bold px-2 py-0.5 rounded-full"
                style={{ backgroundColor: "rgba(0,85,90,0.10)", color: "#00555a" }}>Save 20%</span>
            </span>
          </motion.div>

          {/* Property slider */}
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl p-6 mb-8" style={{ backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0" }}>
            <div className="flex items-center justify-between mb-5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider mb-0.5" style={{ color: "#94A3B8" }}>Properties</p>
                <p className="text-sm" style={{ color: "#64748B" }}>How many properties are you managing?</p>
              </div>
              <div className="flex items-baseline gap-1 bg-white rounded-xl px-5 py-3 shadow-sm" style={{ border: "1px solid #E2E8F0" }}>
                <span className="font-black tabular-nums" style={{ fontSize: 38, color: "#00555a", lineHeight: 1 }}>{numProps}</span>
                <span className="text-sm pb-0.5" style={{ color: "#94A3B8" }}>props</span>
              </div>
            </div>
            <input type="range" min={1} max={150} step={1} value={numProps}
              onChange={e => setNumProps(Number(e.target.value))}
              className="w-full h-2 rounded-full cursor-pointer appearance-none"
              style={{ background: `linear-gradient(to right, #00555a ${(numProps / 150) * 100}%, #E2E8F0 ${(numProps / 150) * 100}%)` }}
            />
            <div className="flex justify-between text-[10px] mt-2" style={{ color: "#94A3B8" }}>
              <span>1 property</span><span>75</span><span>150 properties</span>
            </div>
          </motion.div>

          {/* ── Section A: Communication Modules ─────────────────────────── */}
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} className="mb-2">
            <div className="flex items-center gap-2 mb-1">
              <MessageSquare size={14} style={{ color: "#00555a" }} />
              <p className="text-xs font-bold uppercase tracking-wider" style={{ color: "#00555a" }}>Communication Channels</p>
            </div>
            <p className="text-xs mb-4" style={{ color: "#94A3B8" }}>
              Pick only the channels your guests use. No AI required.
            </p>
          </motion.div>

          <motion.div
            className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-8"
            variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.07 } } }}
            whileInView="visible" initial="hidden" viewport={VP}
          >
            {COMM_MODULES.map(mod => (
              <ModuleCard
                key={mod.id}
                {...mod}
                on={commSelected.has(mod.id)}
                onToggle={() => toggleComm(mod.id)}
              />
            ))}
          </motion.div>

          {/* ── Section B: AI Module (collapsible) ───────────────────────── */}
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl mb-8 overflow-hidden"
            style={{ border: `2px solid ${aiOpen ? "rgba(124,58,237,0.35)" : "#E2E8F0"}`, transition: "border-color 0.2s" }}>

            {/* AI toggle header */}
            <button
              onClick={() => setAiOpen(o => !o)}
              className="w-full flex items-center justify-between p-5 transition-colors duration-150"
              style={{ backgroundColor: aiOpen ? "rgba(124,58,237,0.04)" : "#ffffff" }}
            >
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: aiOpen ? "rgba(124,58,237,0.12)" : "#F8FAFC" }}>
                  <Brain size={18} style={{ color: aiOpen ? "#7c3aed" : "#94A3B8" }} />
                </div>
                <div className="text-left">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-bold" style={{ color: aiOpen ? "#4c1d95" : "#0F172A" }}>AI Add-ons</p>
                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full"
                      style={{ backgroundColor: "rgba(124,58,237,0.12)", color: "#7c3aed" }}>Optional</span>
                    {aiSelected.size > 0 && (
                      <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full"
                        style={{ backgroundColor: "#7c3aed", color: "#ffffff" }}>{aiSelected.size} active</span>
                    )}
                  </div>
                  <p className="text-xs" style={{ color: "#64748B" }}>
                    Layer intelligence onto any channel — or skip entirely
                  </p>
                </div>
              </div>
              <ChevronDown size={16} className="flex-shrink-0 transition-transform duration-200"
                style={{ color: "#7c3aed", transform: aiOpen ? "rotate(180deg)" : "rotate(0deg)" }} />
            </button>

            {/* AI sub-features */}
            <AnimatePresence>
              {aiOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1, transition: { duration: 0.25, ease: "easeOut" } }}
                  exit={{ height: 0, opacity: 0, transition: { duration: 0.18 } }}
                  className="overflow-hidden"
                >
                  <div className="px-5 pb-5 pt-1" style={{ borderTop: "1px solid rgba(124,58,237,0.12)", backgroundColor: "rgba(124,58,237,0.02)" }}>
                    <p className="text-xs font-medium mb-4 mt-3" style={{ color: "#94A3B8" }}>
                      Select individual AI features — each priced separately per property per month.
                    </p>
                    <div className="grid grid-cols-1 gap-3">
                      {AI_ADDONS.map(addon => (
                        <AIAddonRow
                          key={addon.id}
                          {...addon}
                          on={aiSelected.has(addon.id)}
                          onToggle={() => toggleAI(addon.id)}
                          commEnabled={commEnabled}
                        />
                      ))}
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>

          {/* ── Price summary ─────────────────────────────────────────────── */}
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl p-8" style={{ backgroundColor: "#003d41", boxShadow: "0 24px 64px rgba(0,61,65,0.30)" }}>
            {!hasSelection ? (
              <p className="text-center py-4" style={{ color: "rgba(255,255,255,0.30)" }}>
                Select modules above to calculate your price
              </p>
            ) : (
              <>
                <p className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "rgba(255,255,255,0.35)" }}>
                  Your estimate
                </p>

                {/* Comm rows */}
                {commRows.length > 0 && (
                  <div className="mb-3">
                    <p className="text-[10px] font-bold uppercase tracking-wider mb-2" style={{ color: "rgba(255,255,255,0.25)" }}>
                      Communication
                    </p>
                    <div className="space-y-1.5">
                      {commRows.map((r, i) => (
                        <div key={i} className="flex items-center justify-between text-sm">
                          <span style={{ color: "#94A3B8" }}>{r.label}</span>
                          <span className="font-semibold" style={{ color: "#CBD5E1" }}>{r.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* AI rows */}
                {aiRows.length > 0 && (
                  <div className="mb-3">
                    <p className="text-[10px] font-bold uppercase tracking-wider mb-2" style={{ color: "rgba(167,139,250,0.50)" }}>
                      AI Add-ons
                    </p>
                    <div className="space-y-1.5">
                      {aiRows.map((r, i) => (
                        <div key={i} className="flex items-center justify-between text-sm">
                          <span style={{ color: "#a78bfa" }}>{r.label}</span>
                          <span className="font-semibold" style={{ color: "#c4b5fd" }}>{r.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {annual && (
                  <div className="flex items-center justify-between text-sm mt-2">
                    <span style={{ color: "#ffc94b" }}>Annual discount (20%)</span>
                    <span className="font-semibold" style={{ color: "#ffc94b" }}>−{fmt(Math.round(totalRaw * 0.2))}</span>
                  </div>
                )}

                <div className="border-t pt-5 mb-1 mt-3" style={{ borderColor: "rgba(255,255,255,0.10)" }}>
                  <div className="flex items-end justify-between gap-4">
                    <div>
                      <p className="text-xs font-semibold mb-1" style={{ color: "rgba(255,255,255,0.40)" }}>
                        {annual ? "Billed annually" : "Billed monthly"}
                      </p>
                      <span className="font-black tabular-nums" style={{ fontSize: 44, color: "#ffc94b", lineHeight: 1 }}>{fmt(bill)}</span>
                      <span className="text-sm ml-1" style={{ color: "rgba(255,201,75,0.55)" }}>/mo</span>
                    </div>
                    {perProp > 0 && (
                      <div className="text-right">
                        <p className="text-xs" style={{ color: "rgba(255,255,255,0.40)" }}>per property</p>
                        <p className="font-bold" style={{ color: "rgba(255,201,75,0.75)", fontSize: 18 }}>{fmt(perProp)}/mo</p>
                      </div>
                    )}
                  </div>
                </div>
                {minApplied && (
                  <p className="text-xs mt-3 text-center rounded-full px-3 py-1.5"
                    style={{ backgroundColor: "rgba(255,201,75,0.10)", color: "#ffc94b" }}>
                    Minimum billing of ₹1,500/month applied
                  </p>
                )}
              </>
            )}
            <div className="flex flex-col sm:flex-row gap-3 mt-7">
              <Link href="/register"
                className="flex-1 flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl font-bold text-sm transition-all duration-200"
                style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                Start free trial <ArrowRight size={14} />
              </Link>
              <a href="mailto:sharath.d1729@gmail.com"
                className="flex-1 flex items-center justify-center px-6 py-3.5 rounded-xl font-semibold text-sm text-white transition-all duration-200"
                style={{ border: "1px solid rgba(255,255,255,0.16)" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.32)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.16)"; }}>
                Talk to sales
              </a>
            </div>
            <p className="text-center text-xs mt-4" style={{ color: "rgba(255,255,255,0.20)" }}>
              All prices in INR · GST (18%) applicable · No credit card to start
            </p>
          </motion.div>
        </div>
      </section>

      {/* ── What's included table ─────────────────────────────────────────── */}
      <section className="py-20 px-5 sm:px-8" style={{ backgroundColor: "#F8FAFC" }}>
        <div className="max-w-3xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP} className="text-center mb-12">
            <h2 className="text-2xl font-bold mb-3" style={{ color: "#0F172A" }}>Everything in each module</h2>
            <p className="text-sm" style={{ color: "#64748B" }}>
              Every module and AI add-on is independently activatable. No bundles forced on you.
            </p>
          </motion.div>

          {/* Communication table */}
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl overflow-hidden mb-6"
            style={{ border: "1px solid #E2E8F0", boxShadow: "0 4px 20px rgba(0,0,0,0.05)" }}>
            <table className="w-full">
              <thead>
                <tr style={{ backgroundColor: "#003d41" }}>
                  <th className="text-left px-6 py-4 text-xs font-semibold uppercase tracking-wider text-white w-5/12">
                    Communication Channel
                  </th>
                  <th className="px-4 py-4 text-xs font-semibold uppercase tracking-wider text-center w-2/12"
                    style={{ color: "rgba(255,255,255,0.50)" }}>Price / prop</th>
                  <th className="px-4 py-4 text-xs font-semibold uppercase tracking-wider text-left hidden sm:table-cell"
                    style={{ color: "rgba(255,255,255,0.50)" }}>Includes</th>
                </tr>
              </thead>
              <tbody>
                {COMM_MODULES.map((mod, i) => {
                  const on = commSelected.has(mod.id);
                  return (
                    <tr key={mod.id} style={{
                      backgroundColor: i % 2 === 0 ? "#ffffff" : "#F8FAFC",
                      borderTop: "1px solid #E2E8F0",
                      borderLeft: on ? "3px solid #00555a" : "3px solid transparent",
                    }}>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                            style={{ backgroundColor: on ? "rgba(0,85,90,0.10)" : "#F1F5F9" }}>
                            <span style={{ color: on ? "#00555a" : "#94A3B8" }}>{mod.icon}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-semibold" style={{ color: "#0F172A" }}>{mod.name}</p>
                            {mod.popular && (
                              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full hidden sm:inline"
                                style={{ backgroundColor: "rgba(255,201,75,0.18)", color: "#92400E" }}>Popular</span>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4 text-center">
                        <span className="text-sm font-bold" style={{ color: "#00555a" }}>{fmt(mod.ppm)}</span>
                      </td>
                      <td className="px-4 py-4 text-sm hidden sm:table-cell" style={{ color: "#64748B" }}>{mod.desc}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </motion.div>

          {/* AI add-ons table */}
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl overflow-hidden mb-4"
            style={{ border: "1px solid rgba(124,58,237,0.25)", boxShadow: "0 4px 20px rgba(124,58,237,0.06)" }}>
            <table className="w-full">
              <thead>
                <tr style={{ backgroundColor: "#4c1d95" }}>
                  <th className="text-left px-6 py-4 text-xs font-semibold uppercase tracking-wider text-white w-5/12">
                    AI Add-on
                  </th>
                  <th className="px-4 py-4 text-xs font-semibold uppercase tracking-wider text-center w-2/12"
                    style={{ color: "rgba(255,255,255,0.50)" }}>Price / prop</th>
                  <th className="px-4 py-4 text-xs font-semibold uppercase tracking-wider text-left hidden sm:table-cell"
                    style={{ color: "rgba(255,255,255,0.50)" }}>Includes</th>
                </tr>
              </thead>
              <tbody>
                {AI_ADDONS.map((addon, i) => {
                  const on = aiSelected.has(addon.id);
                  return (
                    <tr key={addon.id} style={{
                      backgroundColor: i % 2 === 0 ? "#ffffff" : "#faf5ff",
                      borderTop: "1px solid rgba(124,58,237,0.10)",
                      borderLeft: on ? "3px solid #7c3aed" : "3px solid transparent",
                    }}>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                            style={{ backgroundColor: on ? "rgba(124,58,237,0.12)" : "#F3F0FF" }}>
                            <span style={{ color: on ? "#7c3aed" : "#a78bfa" }}>{addon.icon}</span>
                          </div>
                          <div>
                            <p className="text-sm font-semibold" style={{ color: "#0F172A" }}>{addon.name}</p>
                            {addon.requiresLabel && (
                              <p className="text-[10px]" style={{ color: "#94A3B8" }}>Needs: {addon.requiresLabel}</p>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4 text-center">
                        <span className="text-sm font-bold" style={{ color: "#7c3aed" }}>{fmt(addon.ppm)}</span>
                      </td>
                      <td className="px-4 py-4 text-sm hidden sm:table-cell" style={{ color: "#64748B" }}>{addon.desc}</td>
                    </tr>
                  );
                })}

                {/* Enterprise row */}
                <tr style={{ backgroundColor: "#F0FDF4", borderTop: "1px solid rgba(124,58,237,0.10)", borderLeft: "3px solid transparent" }}>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                        style={{ backgroundColor: "rgba(0,85,90,0.08)" }}>
                        <BadgeCheck size={16} style={{ color: "#00555a" }} />
                      </div>
                      <p className="text-sm font-semibold" style={{ color: "#0F172A" }}>Enterprise — custom AI</p>
                    </div>
                  </td>
                  <td className="px-4 py-4 text-center">
                    <span className="text-sm font-bold" style={{ color: "#00555a" }}>Custom</span>
                  </td>
                  <td className="px-4 py-4 text-sm hidden sm:table-cell" style={{ color: "#64748B" }}>
                    Dedicated model fine-tuning · Custom integrations · SLA · On-prem option
                  </td>
                </tr>
              </tbody>
            </table>
          </motion.div>

          <p className="text-center text-xs mt-4" style={{ color: "#94A3B8" }}>
            Minimum monthly charge ₹1,500 · GST (18%) additional · Annual billing saves 20%
          </p>
        </div>
      </section>

      {/* ── Testimonial ──────────────────────────────────────────────────── */}
      <section className="py-14 px-5 sm:px-8">
        <div className="max-w-3xl mx-auto">
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl p-8 relative overflow-hidden" style={{ backgroundColor: "#003d41" }}>
            <div className="absolute right-0 top-0 pointer-events-none"
              style={{ width: 280, height: 280, background: "radial-gradient(circle, rgba(255,201,75,0.06) 0%, transparent 70%)" }} />
            <div className="flex flex-col sm:flex-row gap-6 items-start relative">
              <div className="flex-shrink-0 w-12 h-12 rounded-full flex items-center justify-center font-black text-lg"
                style={{ backgroundColor: "rgba(255,201,75,0.15)", color: "#ffc94b" }}>R</div>
              <div>
                <p className="text-base leading-relaxed mb-4" style={{ color: "rgba(255,255,255,0.80)" }}>
                  "We were spending 2 hours a day manually listening to calls. HAIP does it automatically — every call scored, every missed upsell flagged. The ROI was clear in the first week."
                </p>
                <p className="text-sm font-semibold" style={{ color: "#ffc94b" }}>Ratha Luxury Caravans</p>
                <p className="text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>Design partner · IVR + AI Call Intelligence</p>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── FAQ ──────────────────────────────────────────────────────────── */}
      <section className="py-16 px-5 sm:px-8" style={{ backgroundColor: "#F8FAFC" }}>
        <div className="max-w-2xl mx-auto">
          <motion.h2 variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="text-2xl font-bold text-center mb-10" style={{ color: "#0F172A" }}>
            Frequently asked questions
          </motion.h2>
          <motion.div variants={fadeUp} whileInView="visible" initial="hidden" viewport={VP}
            className="rounded-2xl bg-white p-6 sm:p-8" style={{ border: "1px solid #E2E8F0" }}>
            <FAQAccordion />
          </motion.div>
        </div>
      </section>

      {/* ── Trust badges ─────────────────────────────────────────────────── */}
      <div className="py-8 px-5 flex items-center justify-center flex-wrap gap-6">
        {[
          { icon: "🔒", label: "DPDP Compliant" },
          { icon: "🇮🇳", label: "Made in India" },
          { icon: "⚡", label: "Setup in 10 mins" },
          { icon: "💳", label: "No credit card" },
          { icon: "📞", label: "Onboarding included" },
        ].map(b => (
          <span key={b.label} className="flex items-center gap-1.5 text-sm" style={{ color: "#64748B" }}>
            <span>{b.icon}</span><span>{b.label}</span>
          </span>
        ))}
      </div>

      {/* ── Final CTA ─────────────────────────────────────────────────────── */}
      <section className="py-28 px-5 sm:px-8 relative overflow-hidden"
        style={{ background: "linear-gradient(135deg, #003d41 0%, #00555a 100%)" }}>
        <div className="absolute right-0 top-0 rounded-full pointer-events-none"
          style={{ width: 400, height: 400, background: "rgba(255,201,75,0.05)", filter: "blur(72px)" }} />
        <div className="absolute left-0 bottom-0 rounded-full pointer-events-none"
          style={{ width: 280, height: 280, background: "rgba(0,85,90,0.40)", filter: "blur(64px)" }} />
        <div className="max-w-3xl mx-auto text-center relative">
          <motion.div variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.10 } } }}
            whileInView="visible" initial="hidden" viewport={VP}>
            <motion.p variants={fadeUp} className="text-xs font-semibold uppercase tracking-wider mb-4"
              style={{ color: "rgba(255,201,75,0.60)" }}>Ready to get started?</motion.p>
            <motion.h2 variants={fadeUp} className="font-black text-white mb-4"
              style={{ fontSize: "clamp(32px, 5vw, 52px)", lineHeight: 1.1 }}>
              Start with 14 days free
            </motion.h2>
            <motion.p variants={fadeUp} className="text-lg mb-10" style={{ color: "rgba(255,255,255,0.55)" }}>
              No credit card. No commitment.<br className="hidden sm:block" />
              See the platform working for your property in minutes.
            </motion.p>
            <motion.div variants={fadeUp} className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link href="/register"
                className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-bold text-base transition-all duration-200"
                style={{ backgroundColor: "#ffc94b", color: "#003d41" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#e6b000"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffc94b"; }}>
                Start free trial <ArrowRight size={18} />
              </Link>
              <Link href="/book-demo"
                className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-semibold text-base text-white transition-all duration-200"
                style={{ border: "2px solid rgba(255,255,255,0.20)" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.40)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.20)"; }}>
                Book a demo
              </Link>
            </motion.div>
          </motion.div>
        </div>
      </section>
    </div>
  );
}
