import Link from "next/link";
import {
  Shield, CheckCircle2, ArrowRight, ChevronRight, FileText, Mail,
  Lock, Eye, Trash2, Globe2, BadgeCheck, Database,
} from "lucide-react";

const principles = [
  { icon: <CheckCircle2 size={18} className="text-green-400" />, title: "Lawful processing", desc: "We process guest data only with consent or for the legitimate operation of the hospitality service you provide." },
  { icon: <Database size={18} className="text-cyan-400" />, title: "Purpose limitation", desc: "Guest data is used only for guest communication, AI assist, QA scoring and analytics. Not for cross-tenant model training." },
  { icon: <Lock size={18} className="text-teal-400" />, title: "Data minimisation", desc: "PII redacted before transcripts reach the LLM. Tokenised card / Aadhaar / PAN / phone / email." },
  { icon: <Eye size={18} className="text-purple-400" />, title: "Transparency", desc: "Public sub-processor registry, public audit posture, plain-English DPA template." },
  { icon: <Globe2 size={18} className="text-amber-400" />, title: "Storage limitation", desc: "Default 90-day hot, lifecycle to cold tier. Configurable retention per tenant. Delete-on-request within 30 days." },
  { icon: <Shield size={18} className="text-rose-400" />, title: "Accountability", desc: "Hash-chained audit log of every score, override, export, login, role change — 5-year retention." },
];

const rights = [
  { title: "Right to access", desc: "Guests can request a copy of their data via your support workflow; we return a structured export within 30 days." },
  { title: "Right to correction", desc: "Guests can request corrections to inaccurate data; you action it in HAIP and we audit-log the change." },
  { title: "Right to erasure", desc: "Guest record + linked rows + recordings purged within 30 days; entry logged in the audit chain." },
  { title: "Right to grievance redressal", desc: "Reach our Data Protection Officer at dpo@haip.app. SLA: acknowledgement &lt; 1 working day, resolution &lt; 30 days." },
];

export default function DpdpPage() {
  return (
    <div className="bg-[var(--mkt-bg)] text-white min-h-screen">
      <section className="relative pt-32 pb-16 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full bg-green-500/8 blur-[120px]" />
        </div>
        <div className="relative max-w-3xl mx-auto px-5 sm:px-8 text-center">
          <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-full px-4 py-1.5 mb-5">
            <BadgeCheck size={12} className="text-green-400" />
            <span className="text-xs font-semibold text-green-300 uppercase tracking-wider">DPDP Act 2023 · ready</span>
          </div>
          <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4">DPDP compliance at HAIP</h1>
          <p className="text-white/55 text-lg leading-relaxed">India&apos;s Digital Personal Data Protection Act in plain English — what it asks for, what HAIP gives you out of the box, and how we partner with you to meet your obligations as a data fiduciary.</p>
        </div>
      </section>

      <section className="px-5 sm:px-8 pb-16">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-10">
            <p className="text-xs font-bold text-green-400 uppercase tracking-widest mb-3">Six DPDP principles</p>
            <h2 className="text-2xl sm:text-3xl font-black tracking-tight">How HAIP implements each</h2>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {principles.map(p => (
              <div key={p.title} className="bg-[var(--mkt-panel)]/60 border border-white/8 rounded-2xl p-5 hover:border-green-500/25 transition-colors">
                <div className="w-10 h-10 rounded-xl bg-white/5 flex items-center justify-center mb-3">{p.icon}</div>
                <h3 className="text-sm font-bold text-white mb-1.5">{p.title}</h3>
                <p className="text-xs text-white/50 leading-relaxed">{p.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="px-5 sm:px-8 pb-16 bg-[#0E1210] py-16">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-8">
            <p className="text-xs font-bold text-green-400 uppercase tracking-widest mb-3">Data principal rights</p>
            <h2 className="text-2xl sm:text-3xl font-black tracking-tight">Your guests&apos; rights · how we help you honour them</h2>
          </div>
          <div className="space-y-3">
            {rights.map(r => (
              <div key={r.title} className="bg-[var(--mkt-panel)] border border-white/8 rounded-2xl p-5">
                <h3 className="text-sm font-bold text-white mb-1.5">{r.title}</h3>
                <p className="text-xs text-white/55 leading-relaxed" dangerouslySetInnerHTML={{ __html: r.desc }} />
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="px-5 sm:px-8 pb-24">
        <div className="max-w-4xl mx-auto bg-[var(--mkt-panel)] border border-white/10 rounded-2xl p-7 sm:p-9">
          <div className="flex items-start gap-4 mb-5">
            <div className="w-12 h-12 rounded-xl bg-green-500/15 border border-green-500/25 flex items-center justify-center flex-shrink-0">
              <Mail size={20} className="text-green-400" />
            </div>
            <div>
              <h2 className="text-xl font-black tracking-tight mb-2">Need our DPDP pack for your audit?</h2>
              <p className="text-white/55 text-sm leading-relaxed">We&apos;ll share our DPA template, sub-processor registry, retention schedule, and architecture diagram with your compliance team — typically over a 30-minute call.</p>
            </div>
          </div>
          <div className="flex flex-col sm:flex-row gap-3 mt-6">
            <Link href="/book-demo?topic=dpdp" className="inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-teal-500 hover:bg-teal-400 text-white text-sm font-bold rounded-xl shadow-xl shadow-teal-500/25">
              Schedule a DPDP review <ArrowRight size={14} />
            </Link>
            <a href="mailto:dpo@haip.app" className="inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 text-white text-sm font-semibold rounded-xl">
              <FileText size={14} /> Email DPO · dpo@haip.app
            </a>
            <Link href="/security" className="inline-flex items-center justify-center gap-2 px-5 py-2.5 text-teal-400 hover:text-teal-300 text-sm font-semibold">
              See Trust Center <ChevronRight size={14} />
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

export const metadata = { title: "HAIP DPDP Compliance — India Data Protection Act 2023" };
