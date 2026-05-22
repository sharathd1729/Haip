"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import {
  Phone, MessageSquare, Bot, Users,
  ArrowRight, Check,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Module definitions — mirrors the HTML calculator
// ---------------------------------------------------------------------------

const MODULES = [
  {
    id: "ivr",
    icon: <Phone size={20} />,
    name: "IVR + Call intelligence",
    desc: "Transcription · QA scoring · Insights dashboard",
    ppm: 500,
    cost: 220,
    popular: true,
  },
  {
    id: "wa",
    icon: <MessageSquare size={20} />,
    name: "WhatsApp communication",
    desc: "Inbox · Templates · Guest auto-linking",
    ppm: 200,
    cost: 60,
    popular: true,
  },
  {
    id: "ai",
    icon: <Bot size={20} />,
    name: "AI concierge",
    desc: "Auto-replies · Intent detection · Human handoff",
    ppm: 300,
    cost: 120,
    popular: false,
  },
  {
    id: "crm",
    icon: <Users size={20} />,
    name: "CRM & guest pipeline",
    desc: "Guest profiles · Inquiry tracking · Lead score",
    ppm: 150,
    cost: 50,
    popular: false,
  },
  {
    id: "ig",
    icon: <MessageSquare size={20} />,
    name: "Instagram DM",
    desc: "IG inquiries · Inbox · Guest profile linking",
    ppm: 150,
    cost: 45,
    popular: false,
  },
];

const MIN_BILL = 2500;

function fmt(n: number) {
  return "₹" + Math.round(n).toLocaleString("en-IN");
}

// ---------------------------------------------------------------------------
// Module card
// ---------------------------------------------------------------------------

function ModCard({
  mod,
  selected,
  onToggle,
}: {
  mod: typeof MODULES[0];
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className={cn(
        "relative rounded-2xl border p-5 text-left transition-all duration-150 w-full",
        selected
          ? "bg-teal-500/10 border-teal-500/40 shadow-sm shadow-teal-500/10"
          : "bg-white/5 border-white/10 hover:border-white/20 hover:bg-white/8"
      )}
    >
      {/* Check dot */}
      {selected && (
        <div className="absolute top-3 right-3 w-5 h-5 rounded-full bg-teal-500 flex items-center justify-center">
          <Check size={11} className="text-white" />
        </div>
      )}

      <div className={cn("mb-3", selected ? "text-teal-400" : "text-white/30")}>
        {mod.icon}
      </div>

      <p className={cn("text-sm font-bold mb-1", selected ? "text-teal-300" : "text-white/80")}>
        {mod.name}
      </p>
      <p className={cn("text-[11px] leading-relaxed mb-3", selected ? "text-teal-400/80" : "text-white/30")}>
        {mod.desc}
      </p>
      <p className={cn("text-sm font-bold", selected ? "text-teal-400" : "text-white/50")}>
        {fmt(mod.ppm)} / property / month
      </p>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function PricingPage() {
  const [props, setProps] = useState(10);
  const [selected, setSelected] = useState<Set<string>>(new Set(["ivr", "wa"]));

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const { revenue, rows, bill, minApplied, perProp } = useMemo(() => {
    let revenue = 0;
    const rows: { label: string; value: string }[] = [];

    for (const mod of MODULES) {
      if (!selected.has(mod.id)) continue;
      const r = mod.ppm * props;
      revenue += r;
      rows.push({
        label: `${mod.name}  ·  ${props} props × ${fmt(mod.ppm)}`,
        value: fmt(r),
      });
    }

    const minApplied = selected.size > 0 && revenue < MIN_BILL;
    const bill = minApplied ? MIN_BILL : revenue;
    const perProp = props > 0 && bill > 0 ? Math.round(bill / props) : 0;

    return { revenue, rows, bill, minApplied, perProp };
  }, [selected, props]);

  return (
    <div className="bg-[#0B1F3A] min-h-screen text-white pt-24">
      {/* ── Hero ── */}
      <div className="max-w-2xl mx-auto px-5 sm:px-8 text-center py-16">
        <p className="text-xs font-bold text-teal-400 uppercase tracking-widest mb-4">Pricing</p>
        <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-5 leading-tight">
          Pay only for what<br className="hidden sm:block" /> you use
        </h1>
        <p className="text-white/45 text-lg leading-relaxed">
          Pick the modules your property needs. Pay per property, per month.
          No platform fees, no lock-ins.
        </p>
      </div>

      {/* ── Calculator ── */}
      <div className="max-w-3xl mx-auto px-5 sm:px-8 pb-20">

        {/* Property slider */}
        <div className="bg-white/5 border border-white/10 rounded-2xl p-6 mb-6">
          <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4">
            How many properties do you manage?
          </p>
          <div className="flex items-center gap-5">
            <input
              type="range" min={1} max={150} step={1} value={props}
              onChange={e => setProps(Number(e.target.value))}
              className="flex-1 h-1 accent-teal-400 cursor-pointer"
            />
            <div className="text-right flex-shrink-0 w-28">
              <span className="text-4xl font-black text-white tracking-tight">{props}</span>
              <span className="text-white/40 text-sm ml-1.5">properties</span>
            </div>
          </div>
        </div>

        {/* Module grid */}
        <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-3">Choose modules</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-8">
          {MODULES.map(mod => (
            <ModCard
              key={mod.id}
              mod={mod}
              selected={selected.has(mod.id)}
              onToggle={() => toggle(mod.id)}
            />
          ))}
        </div>

        {/* Breakdown */}
        <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden mb-4">
          {rows.length === 0 ? (
            <div className="py-8 text-center text-white/25 text-sm">
              Select one or more modules above to see your pricing
            </div>
          ) : (
            <div className="divide-y divide-white/6">
              {rows.map((r, i) => (
                <div key={i} className="flex items-center justify-between px-5 py-3.5">
                  <span className="text-sm text-white/50">{r.label}</span>
                  <span className="text-sm font-bold text-white">{r.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Total */}
        <div className="bg-teal-500/10 border-2 border-teal-500/30 rounded-2xl px-6 py-5 flex items-center justify-between mb-2">
          <span className="text-sm font-bold text-teal-300">Total / month</span>
          <span className="text-4xl font-black text-teal-300 tracking-tight">
            {fmt(bill)}
          </span>
        </div>

        <div className="flex items-center justify-between mb-6">
          <span className="text-xs text-white/25">
            {selected.size > 0 && perProp > 0 ? `${fmt(perProp)} per property / month` : ""}
          </span>
          {minApplied && (
            <span className="text-[11px] bg-amber-500/15 text-amber-400 border border-amber-500/20 px-3 py-1 rounded-full">
              Minimum billing of ₹2,500 / month applied
            </span>
          )}
        </div>

        {/* CTA */}
        <div className="flex flex-col sm:flex-row gap-3 justify-center mt-8">
          <Link
            href="/register"
            className="flex items-center justify-center gap-2 px-8 py-4 bg-teal-500 hover:bg-teal-400 text-white font-bold rounded-2xl transition-all shadow-lg shadow-teal-500/25"
          >
            Start free trial <ArrowRight size={18} />
          </Link>
          <a
            href="mailto:sharath.d1729@gmail.com"
            className="flex items-center justify-center px-8 py-4 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all"
          >
            Talk to us
          </a>
        </div>

        {/* Fine print */}
        <p className="text-center text-xs text-white/20 mt-6">
          All prices in INR · GST (18%) applicable · Annual plans at 20% discount · No credit card to start
        </p>
      </div>

      {/* ── Module comparison table ── */}
      <div className="max-w-3xl mx-auto px-5 sm:px-8 pb-24">
        <h2 className="text-2xl font-black text-center mb-10">What's included in each module</h2>
        <div className="overflow-x-auto rounded-2xl border border-white/8">
          <table className="w-full min-w-[500px]">
            <thead>
              <tr className="bg-[#0a1b30] border-b border-white/8">
                <th className="text-left px-5 py-4 text-xs font-bold text-white/30 uppercase tracking-wider w-[45%]">Module</th>
                <th className="px-4 py-4 text-xs font-bold text-white/40 uppercase tracking-wider text-center">Price / property</th>
                <th className="px-4 py-4 text-xs font-bold text-white/40 uppercase tracking-wider text-left hidden sm:table-cell">Key features</th>
              </tr>
            </thead>
            <tbody>
              {MODULES.map((mod, i) => (
                <tr key={mod.id} className={cn("border-t border-white/4", i % 2 === 0 ? "" : "bg-white/1")}>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <span className="text-white/30">{mod.icon}</span>
                      <div>
                        <p className="text-sm font-semibold text-white/80">{mod.name}</p>
                        <p className="text-[11px] text-white/30 sm:hidden mt-0.5">{mod.desc}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-4 text-center">
                    <span className="text-sm font-bold text-teal-400">{fmt(mod.ppm)}</span>
                  </td>
                  <td className="px-4 py-4 text-[11px] text-white/40 hidden sm:table-cell leading-relaxed">
                    {mod.desc}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-center text-xs text-white/20 mt-4">
          Minimum monthly charge ₹2,500 · Enterprise custom pricing available
        </p>
      </div>
    </div>
  );
}
