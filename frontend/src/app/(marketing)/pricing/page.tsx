"use client";

import Link from "next/link";
import { useState } from "react";
import { CheckCircle2, X, ArrowRight, MessageSquare, Phone, Zap, Shield, HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const plans = [
  {
    id: "starter",
    name: "Starter",
    tagline: "Perfect for single-property operators",
    monthly: 3999,
    annual: 3199,
    cta: "Start free trial",
    ctaHref: "/register?plan=starter",
    featured: false,
    color: "border-white/10",
    highlight: false,
  },
  {
    id: "growth",
    name: "Growth",
    tagline: "For growing hospitality teams",
    monthly: 6999,
    annual: 5599,
    cta: "Start free trial",
    ctaHref: "/register?plan=growth",
    featured: true,
    color: "border-teal-500/40",
    highlight: true,
  },
  {
    id: "scale",
    name: "Scale",
    tagline: "Multi-property groups & resorts",
    monthly: 9999,
    annual: 7999,
    cta: "Start free trial",
    ctaHref: "/register?plan=scale",
    featured: false,
    color: "border-white/10",
    highlight: false,
  },
  {
    id: "enterprise",
    name: "Enterprise",
    tagline: "Custom solutions for hotel chains",
    monthly: null,
    annual: null,
    cta: "Contact sales",
    ctaHref: "/contact",
    featured: false,
    color: "border-white/10",
    highlight: false,
  },
];

type FeatureRow = { label: string; starter: string | boolean; growth: string | boolean; scale: string | boolean; enterprise: string | boolean; help?: string };

const featureGroups: { group: string; icon: React.ReactNode; features: FeatureRow[] }[] = [
  {
    group: "Properties & Workspaces",
    icon: <Zap size={14} />,
    features: [
      { label: "Properties / villas", starter: "1", growth: "5", scale: "Unlimited", enterprise: "Unlimited" },
      { label: "Team members", starter: "3", growth: "15", scale: "Unlimited", enterprise: "Unlimited" },
      { label: "Workspaces", starter: "1", growth: "1", scale: "3", enterprise: "Unlimited" },
    ],
  },
  {
    group: "Unified Inbox",
    icon: <MessageSquare size={14} />,
    features: [
      { label: "WhatsApp Business (Cloud API)", starter: true, growth: true, scale: true, enterprise: true },
      { label: "Instagram DMs", starter: false, growth: true, scale: true, enterprise: true },
      { label: "Conversation history", starter: "3 months", growth: "12 months", scale: "Unlimited", enterprise: "Unlimited" },
      { label: "AI-suggested replies", starter: false, growth: true, scale: true, enterprise: true },
      { label: "Bulk WhatsApp campaigns", starter: false, growth: "500 / month", scale: "Unlimited", enterprise: "Unlimited" },
      { label: "WhatsApp message templates", starter: "5", growth: "25", scale: "Unlimited", enterprise: "Unlimited" },
    ],
  },
  {
    group: "AI Call Intelligence",
    icon: <Phone size={14} />,
    features: [
      { label: "Call transcription (per month)", starter: "500 min", growth: "3,000 min", scale: "Unlimited", enterprise: "Unlimited", help: "Minutes of audio processed by Whisper AI" },
      { label: "QA scoring per call", starter: false, growth: true, scale: true, enterprise: true },
      { label: "Sentiment analysis", starter: false, growth: true, scale: true, enterprise: true },
      { label: "Missed revenue detection", starter: false, growth: true, scale: true, enterprise: true },
      { label: "Agent performance dashboard", starter: false, growth: true, scale: true, enterprise: true },
      { label: "IVR integrations (CallerDesk, Acefone)", starter: "1", growth: "2", scale: "All", enterprise: "All" },
    ],
  },
  {
    group: "Hospitality CRM",
    icon: <Zap size={14} />,
    features: [
      { label: "Guest profiles", starter: "500", growth: "10,000", scale: "Unlimited", enterprise: "Unlimited" },
      { label: "Property / villa management", starter: "1", growth: "5", scale: "Unlimited", enterprise: "Unlimited" },
      { label: "Inquiry pipeline", starter: true, growth: true, scale: true, enterprise: true },
      { label: "Stay & booking history", starter: true, growth: true, scale: true, enterprise: true },
      { label: "Calendar integration", starter: false, growth: true, scale: true, enterprise: true },
      { label: "Hostaway integration", starter: false, growth: false, scale: true, enterprise: true },
    ],
  },
  {
    group: "Compliance & Security",
    icon: <Shield size={14} />,
    features: [
      { label: "DPDP compliant call archiving", starter: false, growth: true, scale: true, enterprise: true },
      { label: "Call recording retention", starter: "30 days", growth: "90 days", scale: "1 year", enterprise: "Custom" },
      { label: "Role-based access control", starter: "Basic", growth: "Full RBAC", scale: "Full RBAC", enterprise: "Custom" },
      { label: "SSO / SAML", starter: false, growth: false, scale: false, enterprise: true },
      { label: "Audit logs", starter: false, growth: false, scale: true, enterprise: true },
      { label: "Dedicated data region", starter: false, growth: false, scale: false, enterprise: true },
    ],
  },
  {
    group: "Support",
    icon: <Shield size={14} />,
    features: [
      { label: "Support channel", starter: "Email", growth: "Email + WhatsApp", scale: "Priority + Phone", enterprise: "Dedicated CSM" },
      { label: "Response time SLA", starter: "48h", growth: "12h", scale: "4h", enterprise: "1h" },
      { label: "Onboarding assistance", starter: "Self-serve", growth: "Guided setup", scale: "White-glove", enterprise: "Custom" },
    ],
  },
];

function FeatureValue({ value }: { value: string | boolean }) {
  if (value === true) return <CheckCircle2 size={16} className="text-teal-400 mx-auto" />;
  if (value === false) return <X size={14} className="text-white/15 mx-auto" />;
  return <span className="text-xs text-white/60">{value}</span>;
}

export default function PricingPage() {
  const [annual, setAnnual] = useState(false);

  return (
    <div className="bg-[#0B1F3A] min-h-screen text-white pt-24">
      {/* Header */}
      <div className="max-w-4xl mx-auto px-5 sm:px-8 text-center pt-12 pb-16">
        <p className="text-xs font-bold text-teal-400 uppercase tracking-widest mb-4">Pricing</p>
        <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4">
          Simple, transparent pricing
        </h1>
        <p className="text-white/45 text-xl mb-8">
          Start free. No credit card required. Cancel anytime.
        </p>

        {/* Billing toggle */}
        <div className="inline-flex items-center gap-3 bg-white/5 border border-white/10 rounded-2xl p-1.5">
          <button
            onClick={() => setAnnual(false)}
            className={cn("px-4 py-2 rounded-xl text-sm font-semibold transition-all", !annual ? "bg-white text-[#0B1F3A]" : "text-white/50 hover:text-white")}
          >
            Monthly
          </button>
          <button
            onClick={() => setAnnual(true)}
            className={cn("px-4 py-2 rounded-xl text-sm font-semibold transition-all flex items-center gap-2", annual ? "bg-white text-[#0B1F3A]" : "text-white/50 hover:text-white")}
          >
            Annual
            <span className="text-[10px] font-bold bg-teal-500 text-white px-1.5 py-0.5 rounded-lg">
              Save 20%
            </span>
          </button>
        </div>
      </div>

      {/* Plan cards */}
      <div className="max-w-6xl mx-auto px-5 sm:px-8 pb-16">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {plans.map(plan => (
            <div
              key={plan.id}
              className={cn(
                "relative rounded-2xl border p-6 flex flex-col",
                plan.highlight
                  ? "bg-teal-500/10 border-teal-500/40"
                  : "bg-[#0f2744] border-white/10"
              )}
            >
              {plan.featured && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-teal-500 text-white text-[10px] font-bold uppercase tracking-wider px-3 py-1 rounded-full">
                  Most popular
                </div>
              )}
              <div className="mb-6">
                <h3 className="text-lg font-black text-white mb-1">{plan.name}</h3>
                <p className="text-xs text-white/40 leading-relaxed">{plan.tagline}</p>
              </div>

              {plan.monthly ? (
                <div className="mb-6">
                  <div className="flex items-end gap-1">
                    <span className="text-3xl font-black text-teal-400">
                      ₹{(annual ? plan.annual! : plan.monthly).toLocaleString()}
                    </span>
                    <span className="text-sm text-white/30 mb-1">/mo</span>
                  </div>
                  {annual && (
                    <p className="text-xs text-white/30 mt-1">
                      Billed ₹{(plan.annual! * 12).toLocaleString()} / year
                    </p>
                  )}
                </div>
              ) : (
                <div className="mb-6">
                  <div className="text-2xl font-black text-white mb-1">Custom</div>
                  <p className="text-xs text-white/30">Contact us for pricing</p>
                </div>
              )}

              <Link
                href={plan.ctaHref}
                className={cn(
                  "block text-center py-3 rounded-xl text-sm font-bold transition-all mb-6",
                  plan.highlight
                    ? "bg-teal-500 hover:bg-teal-400 text-white shadow-lg shadow-teal-500/25"
                    : "bg-white/8 hover:bg-white/15 text-white border border-white/10"
                )}
              >
                {plan.cta}
              </Link>

              <div className="text-[10px] text-white/20 text-center">
                {plan.monthly ? "14-day free trial included" : "Custom contract"}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Feature comparison table */}
      <div className="max-w-6xl mx-auto px-5 sm:px-8 pb-24">
        <h2 className="text-2xl font-black text-center mb-10">Full feature comparison</h2>
        <div className="overflow-x-auto rounded-2xl border border-white/8">
          <table className="w-full min-w-[640px]">
            <thead>
              <tr className="bg-[#0a1b30] border-b border-white/8">
                <th className="text-left px-5 py-4 text-xs font-bold text-white/30 uppercase tracking-wider w-[35%]">Feature</th>
                {plans.map(p => (
                  <th key={p.id} className={cn(
                    "px-3 py-4 text-xs font-bold uppercase tracking-wider text-center",
                    p.highlight ? "text-teal-400" : "text-white/40"
                  )}>
                    {p.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {featureGroups.map((group, gi) => (
                <>
                  <tr key={`group-${gi}`} className="bg-[#0a1b30]/50">
                    <td colSpan={5} className="px-5 py-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-white/50 uppercase tracking-wider">
                        <span className="text-teal-400/60">{group.icon}</span>
                        {group.group}
                      </div>
                    </td>
                  </tr>
                  {group.features.map((feat, fi) => (
                    <tr key={`${gi}-${fi}`} className="border-t border-white/4 hover:bg-white/2 transition-colors">
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm text-white/60">{feat.label}</span>
                          {feat.help && (
                            <span title={feat.help} className="text-white/20 cursor-help">
                              <HelpCircle size={11} />
                            </span>
                          )}
                        </div>
                      </td>
                      {(["starter", "growth", "scale", "enterprise"] as const).map(key => (
                        <td key={key} className={cn("px-3 py-3.5 text-center", key === "growth" && "bg-teal-500/3")}>
                          <FeatureValue value={feat[key]} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* FAQ / CTA */}
      <div className="max-w-3xl mx-auto px-5 sm:px-8 pb-24 text-center">
        <h2 className="text-2xl font-black mb-4">Questions?</h2>
        <p className="text-white/40 mb-8">Our team is happy to help you find the right plan for your property.</p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link href="/register" className="px-8 py-3.5 bg-teal-500 hover:bg-teal-400 text-white font-bold rounded-2xl transition-all inline-flex items-center gap-2 justify-center shadow-lg shadow-teal-500/25">
            Start free trial <ArrowRight size={18} />
          </Link>
          <a href="mailto:sales@haip.app" className="px-8 py-3.5 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">
            Talk to sales
          </a>
        </div>
      </div>
    </div>
  );
}
