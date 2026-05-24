import Link from "next/link";
import {
  Shield, Lock, Server, FileCheck2, KeyRound, Eye, FileText, Globe2,
  CheckCircle2, ArrowRight, AlertTriangle, Mail, Database, BadgeCheck,
} from "lucide-react";

const pillars = [
  {
    icon: <Lock size={20} className="text-teal-400" />,
    title: "Encryption everywhere",
    bullets: [
      "AES-256 at rest on S3, RDS, and ElastiCache.",
      "TLS 1.3 in transit between app, workers, database, and storage.",
      "Per-tenant KMS data keys — tenant A&apos;s key cannot decrypt tenant B&apos;s recordings.",
      "Secrets in AWS Secrets Manager — never in env files or code.",
    ],
  },
  {
    icon: <Database size={20} className="text-cyan-400" />,
    title: "Multi-tenant isolation",
    bullets: [
      "Every row carries `tenant_id` — compound primary keys where appropriate.",
      "Postgres Row-Level Security (RLS) enforced at the database — application code is never the only line of defence.",
      "Weekly automated cross-tenant regression test simulates a breach attempt.",
      "Per-tenant data keys mean a leak of one tenant&apos;s files reveals nothing about another&apos;s.",
    ],
  },
  {
    icon: <KeyRound size={20} className="text-amber-400" />,
    title: "Access &amp; identity",
    bullets: [
      "11 built-in roles: Owner · Manager · Reservations · Concierge · FOH · Marketing · Compliance · QA · Coach · Read-only.",
      "Attribute-based scoping — Concierge for Villa A only sees Villa A.",
      "SSO via Google + Microsoft on every tier. SAML / SCIM on Enterprise (WorkOS).",
      "MFA mandatory for Owner and Compliance roles. Session: 15-min JWT + 30-day refresh.",
    ],
  },
  {
    icon: <Eye size={20} className="text-purple-400" />,
    title: "Audit &amp; observability",
    bullets: [
      "Append-only, hash-chained audit log — 5-year retention.",
      "Every score, override, export, login, role change is captured with actor + timestamp.",
      "Per-tenant audit export to S3 or your bucket.",
      "Sentry + Grafana for real-time error and performance monitoring.",
    ],
  },
  {
    icon: <FileCheck2 size={20} className="text-rose-400" />,
    title: "DPDP &amp; PII handling",
    bullets: [
      "PII redaction at L1 — card / Aadhaar / PAN / phone / email tokenised before transcripts reach the LLM.",
      "Recording consent prompt captured in the IVR greeting; consent events logged in HAIP&apos;s consent log.",
      "Delete-on-request flow — guest record + linked rows + recordings purged within 30 days.",
      "Sub-processor list public — DPAs signed with Anthropic, Deepgram, AWS, and your IVR provider.",
    ],
  },
  {
    icon: <Globe2 size={20} className="text-green-400" />,
    title: "Data residency",
    bullets: [
      "India tenants live in AWS Mumbai (ap-south-1) by default — primary data, recordings, and backups.",
      "EU customer data isolated to eu-central-1 on Enterprise tier.",
      "BYOK (bring your own KMS key) and dedicated VPC on Enterprise.",
      "We never replicate Indian tenant data to non-Indian regions without explicit consent.",
    ],
  },
];

const subprocessors = [
  { name: "Amazon Web Services", purpose: "Hosting, storage, RDS, ElastiCache, KMS", region: "Mumbai (ap-south-1)" },
  { name: "Anthropic (Claude)", purpose: "LLM — classification, drafting, QA judge", region: "Inference via API; no training on customer data" },
  { name: "Deepgram", purpose: "Speech-to-text (Indian English &amp; languages)", region: "Inference via API; no training on customer data" },
  { name: "CallerDesk", purpose: "BYOC IVR adapter — call recording + webhooks", region: "India" },
  { name: "Acefone (Servetel)", purpose: "BYOC IVR adapter — call recording + webhooks", region: "India" },
  { name: "WhatsApp Cloud API (Meta)", purpose: "WhatsApp Business messaging", region: "Meta global" },
  { name: "Cloudflare", purpose: "DNS, CDN, WAF, SSL", region: "Global edge" },
  { name: "Sentry &amp; Grafana", purpose: "Error tracking &amp; observability", region: "EU (Sentry) · US (Grafana free)" },
];

const compliance = [
  { name: "DPDP Act 2023 (India)", status: "Ready", color: "text-green-400 bg-green-500/15 border-green-500/30", note: "Consent capture, residency, deletion workflows" },
  { name: "SOC 2 Type I", status: "In progress · 2026 Q4", color: "text-amber-400 bg-amber-500/15 border-amber-500/30", note: "Audit kick-off scheduled" },
  { name: "ISO 27001", status: "Planned · 2027", color: "text-white/40 bg-white/5 border-white/10", note: "Post SOC 2" },
  { name: "GDPR", status: "Aligned", color: "text-green-400 bg-green-500/15 border-green-500/30", note: "EU-tenant data residency on Enterprise" },
  { name: "Annual pen test", status: "From Year 2", color: "text-amber-400 bg-amber-500/15 border-amber-500/30", note: "Third-party tester contracted" },
];

export default function SecurityPage() {
  return (
    <div className="bg-[#0E1210] text-white min-h-screen">
      {/* HERO */}
      <section className="relative pt-32 pb-20 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[800px] h-[400px] rounded-full bg-teal-500/8 blur-[120px]" />
          <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "radial-gradient(circle, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
        </div>
        <div className="relative max-w-5xl mx-auto px-5 sm:px-8 text-center">
          <div className="inline-flex items-center gap-2 bg-teal-500/10 border border-teal-500/20 rounded-full px-4 py-1.5 mb-6">
            <Shield size={12} className="text-teal-400" />
            <span className="text-xs font-semibold text-teal-300 uppercase tracking-wider">Trust center</span>
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight leading-[1.05] mb-5">
            Security &amp; privacy at HAIP
          </h1>
          <p className="text-white/55 text-lg max-w-2xl mx-auto leading-relaxed mb-8">
            We store voice recordings, guest PII, and full conversation history for paying clients. Multi-tenancy and encryption have to be airtight from day one — here is exactly how we do it.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <a href="mailto:security@haip.app" className="inline-flex items-center gap-2 px-6 py-3 bg-[#C8964A] hover:bg-[#D4A85A] text-[#0E1210] font-bold rounded-2xl transition-all shadow-xl shadow-teal-500/25">
              <Mail size={16} /> Email security@haip.app
            </a>
            <Link href="/dpdp" className="inline-flex items-center gap-2 px-6 py-3 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">
              DPDP compliance details <ArrowRight size={16} />
            </Link>
          </div>
        </div>
      </section>

      {/* TOP CALLOUTS */}
      <section className="px-5 sm:px-8 pb-8">
        <div className="max-w-6xl mx-auto grid sm:grid-cols-3 gap-4">
          {[
            { icon: <Server size={18} className="text-teal-400" />, title: "India-first", desc: "AWS Mumbai (ap-south-1) by default. No US/EU spillover for Indian tenants." },
            { icon: <BadgeCheck size={18} className="text-green-400" />, title: "DPDP-ready", desc: "Consent · residency · deletion · audit log · sub-processor disclosure." },
            { icon: <KeyRound size={18} className="text-amber-400" />, title: "Per-tenant KMS", desc: "Your recordings encrypted with a key only your tenant can use." },
          ].map(c => (
            <div key={c.title} className="bg-[#141B15] border border-white/10 rounded-2xl p-5 flex items-start gap-3">
              <div className="w-10 h-10 rounded-xl bg-white/5 flex items-center justify-center flex-shrink-0">{c.icon}</div>
              <div>
                <p className="text-sm font-bold text-white mb-0.5">{c.title}</p>
                <p className="text-xs text-white/45 leading-relaxed">{c.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* SECURITY PILLARS */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-xs font-bold text-[#3D9E7E] uppercase tracking-widest mb-3">How we protect your data</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight">Six pillars · production from day one</h2>
          </div>
          <div className="grid md:grid-cols-2 gap-5">
            {pillars.map(p => (
              <div key={p.title} className="bg-[#141B15]/70 border border-white/10 rounded-2xl p-6 hover:border-teal-500/25 transition-colors">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-11 h-11 rounded-xl bg-white/5 flex items-center justify-center">{p.icon}</div>
                  <h3 className="text-lg font-bold text-white">{p.title}</h3>
                </div>
                <ul className="space-y-2.5">
                  {p.bullets.map(b => (
                    <li key={b} className="flex items-start gap-2.5 text-sm text-white/60 leading-relaxed">
                      <CheckCircle2 size={14} className="text-teal-400 flex-shrink-0 mt-1" />
                      <span dangerouslySetInnerHTML={{ __html: b }} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SUB-PROCESSORS */}
      <section className="py-20 px-5 sm:px-8 bg-[#0E1210]">
        <div className="max-w-5xl mx-auto">
          <div className="mb-10">
            <p className="text-xs font-bold text-[#3D9E7E] uppercase tracking-widest mb-3">Sub-processor registry</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-3">Every third party that touches your data</h2>
            <p className="text-white/55 max-w-2xl">Public list. Data Processing Agreements (DPAs) signed with each. We will notify you in advance of any new sub-processor we onboard.</p>
          </div>
          <div className="bg-[#141B15] border border-white/10 rounded-2xl overflow-hidden">
            <div className="grid grid-cols-12 gap-4 px-5 py-3 border-b border-white/8 text-[11px] font-bold text-white/40 uppercase tracking-widest">
              <div className="col-span-4">Sub-processor</div>
              <div className="col-span-5">Purpose</div>
              <div className="col-span-3">Region</div>
            </div>
            {subprocessors.map(s => (
              <div key={s.name} className="grid grid-cols-12 gap-4 px-5 py-4 border-b border-white/4 last:border-b-0 text-sm hover:bg-white/2 transition-colors">
                <div className="col-span-4 text-white font-semibold" dangerouslySetInnerHTML={{ __html: s.name }} />
                <div className="col-span-5 text-white/55" dangerouslySetInnerHTML={{ __html: s.purpose }} />
                <div className="col-span-3 text-white/45 text-xs flex items-center" dangerouslySetInnerHTML={{ __html: s.region }} />
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* COMPLIANCE STATUS */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-5xl mx-auto">
          <div className="mb-10">
            <p className="text-xs font-bold text-[#3D9E7E] uppercase tracking-widest mb-3">Compliance status</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-3">Where we are, and where we&apos;re going</h2>
            <p className="text-white/55 max-w-2xl">We don&apos;t claim certifications we don&apos;t hold. Here is the honest status as of {new Date().toLocaleDateString("en-IN", { month: "short", year: "numeric" })}.</p>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            {compliance.map(c => (
              <div key={c.name} className="bg-[#141B15]/70 border border-white/8 rounded-2xl p-5">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-base font-bold text-white">{c.name}</h3>
                  <span className={`text-[10px] font-bold px-2 py-1 rounded-md border ${c.color}`}>{c.status}</span>
                </div>
                <p className="text-xs text-white/45">{c.note}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* REPORT VULN */}
      <section className="py-20 px-5 sm:px-8 bg-[#0E1210]">
        <div className="max-w-4xl mx-auto bg-gradient-to-br from-[#141B15] to-[#0E1210] border border-amber-500/20 rounded-3xl p-8 sm:p-12">
          <div className="flex items-start gap-4 mb-5">
            <div className="w-12 h-12 rounded-xl bg-amber-500/15 border border-amber-500/25 flex items-center justify-center flex-shrink-0">
              <AlertTriangle size={20} className="text-amber-400" />
            </div>
            <div>
              <h2 className="text-2xl font-black tracking-tight mb-2">Reporting a vulnerability</h2>
              <p className="text-white/60 text-base leading-relaxed">
                Found something? Please email <a href="mailto:security@haip.app" className="text-amber-300 underline">security@haip.app</a> with details. We acknowledge within 1 working day and aim to triage within 3. We don&apos;t pursue legal action against good-faith research.
              </p>
            </div>
          </div>
          <div className="grid sm:grid-cols-3 gap-3 mt-6">
            {[
              { label: "Acknowledgement", value: "&lt; 1 day" },
              { label: "Triage", value: "&lt; 3 days" },
              { label: "High-severity fix", value: "&lt; 14 days" },
            ].map(s => (
              <div key={s.label} className="bg-white/3 rounded-xl px-4 py-3 text-center">
                <p className="text-lg font-bold text-amber-300" dangerouslySetInnerHTML={{ __html: s.value }} />
                <p className="text-[10px] text-white/40 uppercase tracking-widest mt-0.5">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CONTACT FOOTER */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-4xl mx-auto text-center">
          <h2 className="text-2xl sm:text-3xl font-black tracking-tight mb-4">Need our security pack for a vendor review?</h2>
          <p className="text-white/55 mb-8 max-w-xl mx-auto">We&apos;re happy to share our architecture diagram, threat model, DPA, sub-processor registry, and pen-test plan with your compliance team — typically over a 30-minute call.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/book-demo?topic=security" className="inline-flex items-center gap-2 px-6 py-3 bg-[#C8964A] hover:bg-[#D4A85A] text-[#0E1210] font-bold rounded-2xl transition-all shadow-xl shadow-[#C8964A]/30">
              Schedule security review <ArrowRight size={16} />
            </Link>
            <a href="mailto:dpo@haip.app" className="inline-flex items-center gap-2 px-6 py-3 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">
              <FileText size={16} /> Email DPO
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}

export const metadata = {
  title: "HAIP Security &amp; Trust Center — DPDP, encryption, multi-tenancy",
  description: "How HAIP protects guest data: per-tenant KMS, Postgres RLS, hash-chained audit log, DPDP-ready, AWS Mumbai residency. Sub-processor registry and compliance status.",
};
