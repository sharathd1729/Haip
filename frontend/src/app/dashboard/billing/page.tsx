"use client";

import { useState } from "react";
import {
  CreditCard, Zap, CheckCircle, ArrowUpRight, Download,
  AlertCircle, Clock, BarChart2, Phone, MessageSquare, Users,
  ChevronRight, Star,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Static plan data
// ---------------------------------------------------------------------------

const PLANS = [
  {
    id: "starter",
    name: "Starter",
    price: 3999,
    period: "mo",
    highlight: false,
    features: [
      "500 calls / month",
      "1,500 WhatsApp conversations",
      "2 users",
      "1 property",
      "AI Concierge (shadow mode)",
      "Basic QA scoring",
      "Email support",
    ],
  },
  {
    id: "growth",
    name: "Growth",
    price: 6999,
    period: "mo",
    highlight: true,
    badge: "Current plan",
    features: [
      "1,500 calls / month",
      "4,500 WhatsApp conversations",
      "5 users",
      "3 properties",
      "AI Concierge (autonomous mode)",
      "Full QA + coaching nudges",
      "Hostaway / RentalWise sync",
      "Priority email support",
    ],
  },
  {
    id: "scale",
    name: "Scale",
    price: 9999,
    period: "mo",
    highlight: false,
    features: [
      "Unlimited calls",
      "Unlimited WhatsApp conversations",
      "15 users",
      "10 properties",
      "AI Concierge + campaign attribution",
      "Full compliance centre",
      "Lost-reason clustering",
      "Dedicated onboarding + Slack support",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: null,
    period: "mo",
    highlight: false,
    features: [
      "Custom usage limits",
      "Custom integrations",
      "SSO / SAML",
      "SLA-backed uptime",
      "Dedicated success manager",
      "On-prem option",
    ],
  },
];

const INVOICES = [
  { id: "INV-2026-05", date: "1 May 2026",   amount: 6999, status: "paid" },
  { id: "INV-2026-04", date: "1 Apr 2026",   amount: 6999, status: "paid" },
  { id: "INV-2026-03", date: "1 Mar 2026",   amount: 6999, status: "paid" },
  { id: "INV-2026-02", date: "1 Feb 2026",   amount: 6999, status: "paid" },
  { id: "INV-2026-01", date: "1 Jan 2026",   amount: 6999, status: "paid" },
];

// ---------------------------------------------------------------------------
// Usage meter
// ---------------------------------------------------------------------------

function UsageMeter({ label, icon, used, limit, color }: {
  label: string; icon: React.ReactNode;
  used: number; limit: number; color: string;
}) {
  const pct = Math.min(100, Math.round((used / limit) * 100));
  const isHigh = pct >= 80;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-gray-700">
          <span className="text-gray-400">{icon}</span>
          {label}
        </div>
        <span className={cn("text-xs font-semibold", isHigh ? "text-red-600" : "text-gray-500")}>
          {used.toLocaleString()} / {limit.toLocaleString()}
        </span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", isHigh ? "bg-red-400" : color)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-[11px] text-gray-400">{pct}% used this billing cycle</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function BillingPage() {
  const [tab, setTab] = useState<"overview" | "plans" | "invoices">("overview");

  return (
    <div className="h-full flex flex-col bg-gray-50">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Billing</h1>
            <p className="text-sm text-gray-400 mt-0.5">Manage your plan, usage, and payment details</p>
          </div>
          <div className="flex items-center gap-2 bg-teal-50 border border-teal-200 rounded-xl px-3 py-1.5">
            <Star size={13} className="text-teal-600" />
            <span className="text-xs font-bold text-teal-700">Growth Plan</span>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mt-4">
          {(["overview", "plans", "invoices"] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "px-4 py-1.5 rounded-lg text-sm font-medium capitalize transition-colors",
                tab === t ? "bg-teal-500 text-white" : "text-gray-500 hover:bg-gray-100"
              )}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {tab === "overview" && <Overview />}
        {tab === "plans"    && <Plans />}
        {tab === "invoices" && <Invoices />}
      </div>
    </div>
  );
}

/* ── Overview ─────────────────────────────────────────────────────────────── */
function Overview() {
  return (
    <div className="max-w-2xl space-y-6">
      {/* Current plan summary */}
      <div className="bg-white rounded-2xl border border-teal-200 shadow-sm p-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">Current plan</p>
            <p className="text-2xl font-bold text-gray-900">Growth</p>
            <p className="text-sm text-gray-500 mt-1">₹6,999 / month · Renews 1 June 2026</p>
          </div>
          <div className="text-right">
            <div className="flex items-center gap-2 text-green-600 text-sm font-semibold">
              <CheckCircle size={14} />
              Active
            </div>
            <button
              onClick={() => {}}
              className="mt-2 flex items-center gap-1 text-xs text-teal-600 hover:underline font-medium"
            >
              Upgrade to Scale <ArrowUpRight size={11} />
            </button>
          </div>
        </div>

        <div className="mt-5 pt-4 border-t border-gray-100">
          <p className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Usage this cycle</p>
          <div className="space-y-5">
            <UsageMeter label="Calls"                    icon={<Phone size={14} />}        used={847}   limit={1500}  color="bg-blue-400" />
            <UsageMeter label="WhatsApp conversations"   icon={<MessageSquare size={14} />} used={2341}  limit={4500}  color="bg-green-400" />
            <UsageMeter label="Team members"             icon={<Users size={14} />}         used={3}     limit={5}     color="bg-violet-400" />
          </div>
        </div>
      </div>

      {/* Payment method */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <p className="text-sm font-semibold text-gray-800 mb-4">Payment method</p>
        <div className="flex items-center gap-4">
          <div className="w-12 h-8 bg-gray-100 rounded-lg flex items-center justify-center">
            <CreditCard size={18} className="text-gray-400" />
          </div>
          <div>
            <p className="text-sm font-medium text-gray-900">•••• •••• •••• 4242</p>
            <p className="text-xs text-gray-400">Visa · Expires 12/27</p>
          </div>
          <button className="ml-auto text-xs text-teal-600 hover:underline font-medium">Update</button>
        </div>
        <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-700 flex items-start gap-2">
          <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
          <span>All payments are processed securely via Razorpay. HAIP never stores your card details.</span>
        </div>
      </div>

      {/* Next invoice */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <p className="text-sm font-semibold text-gray-800 mb-3">Upcoming charge</p>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gray-50 flex items-center justify-center">
              <Clock size={16} className="text-gray-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900">Growth Plan — June 2026</p>
              <p className="text-xs text-gray-400">Billed on 1 June 2026</p>
            </div>
          </div>
          <p className="text-lg font-bold text-gray-900">₹6,999</p>
        </div>
      </div>
    </div>
  );
}

/* ── Plans ────────────────────────────────────────────────────────────────── */
function Plans() {
  return (
    <div className="space-y-4">
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-sm text-blue-800 flex items-start gap-2 max-w-3xl">
        <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
        <span>Plan changes take effect on your next billing date. To upgrade immediately or negotiate annual pricing, <strong>contact us</strong> at <a href="mailto:hello@haip.app" className="underline">hello@haip.app</a>.</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {PLANS.map(plan => (
          <div
            key={plan.id}
            className={cn(
              "bg-white rounded-2xl border p-5 flex flex-col",
              plan.highlight ? "border-teal-400 shadow-md shadow-teal-50 ring-1 ring-teal-400/20" : "border-gray-100 shadow-sm"
            )}
          >
            {plan.badge && (
              <span className="self-start text-[10px] bg-teal-100 text-teal-700 font-bold px-2 py-0.5 rounded-full uppercase tracking-wide mb-3">
                {plan.badge}
              </span>
            )}
            <p className="text-base font-bold text-gray-900">{plan.name}</p>
            <div className="mt-1 mb-4">
              {plan.price ? (
                <span className="text-2xl font-bold text-gray-900">₹{plan.price.toLocaleString()}<span className="text-sm font-normal text-gray-400">/{plan.period}</span></span>
              ) : (
                <span className="text-lg font-bold text-gray-700">Custom pricing</span>
              )}
            </div>

            <ul className="space-y-2 flex-1 mb-5">
              {plan.features.map(f => (
                <li key={f} className="flex items-start gap-2 text-xs text-gray-600">
                  <CheckCircle size={12} className="text-teal-500 flex-shrink-0 mt-0.5" />
                  {f}
                </li>
              ))}
            </ul>

            <button
              className={cn(
                "w-full py-2.5 rounded-xl text-sm font-semibold transition-colors",
                plan.highlight
                  ? "bg-gray-100 text-gray-400 cursor-default"
                  : plan.price
                  ? "bg-teal-500 text-white hover:bg-teal-600"
                  : "border border-gray-200 text-gray-700 hover:bg-gray-50"
              )}
              disabled={plan.highlight}
            >
              {plan.highlight ? "Current plan" : plan.price ? "Upgrade" : "Contact sales"}
            </button>
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-400 mt-2">All prices in INR. GST (18%) applies. Annual plans available at 20% discount.</p>
    </div>
  );
}

/* ── Invoices ─────────────────────────────────────────────────────────────── */
function Invoices() {
  return (
    <div className="max-w-2xl">
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <p className="text-sm font-semibold text-gray-800">Invoice history</p>
        </div>
        <div className="divide-y divide-gray-50">
          {INVOICES.map(inv => (
            <div key={inv.id} className="flex items-center gap-4 px-5 py-4">
              <div className="w-9 h-9 rounded-xl bg-green-50 flex items-center justify-center flex-shrink-0">
                <CheckCircle size={15} className="text-green-500" />
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-900">{inv.id}</p>
                <p className="text-xs text-gray-400">{inv.date}</p>
              </div>
              <p className="text-sm font-semibold text-gray-900">₹{inv.amount.toLocaleString()}</p>
              <span className="text-[10px] bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full font-semibold uppercase">
                {inv.status}
              </span>
              <button className="ml-2 text-gray-400 hover:text-gray-600 transition-colors" title="Download PDF">
                <Download size={14} />
              </button>
            </div>
          ))}
        </div>
        {INVOICES.length === 0 && (
          <div className="py-12 text-center text-gray-400">
            <CreditCard size={32} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm">No invoices yet</p>
          </div>
        )}
      </div>
    </div>
  );
}
