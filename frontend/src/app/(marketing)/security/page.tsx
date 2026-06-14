import Link from "next/link";
import {
  Shield, Lock, Server, FileCheck2, KeyRound, Eye, FileText, Globe2,
  CheckCircle2, ArrowRight, AlertTriangle, Mail, Database, BadgeCheck,
} from "lucide-react";

const pillars = [
  {
    icon: <Lock size={20} style={{ color: "#00555a" }} />,
    title: "Encryption everywhere",
    bullets: [
      "AES-256 at rest on S3, RDS, and ElastiCache.",
      "TLS 1.3 in transit between app, workers, database, and storage.",
      "Per-tenant KMS data keys — tenant A&apos;s key cannot decrypt tenant B&apos;s recordings.",
      "Secrets in AWS Secrets Manager — never in env files or code.",
    ],
  },
  {
    icon: <Database size={20} style={{ color: "#00888f" }} />,
    title: "Multi-tenant isolation",
    bullets: [
      "Every row carries `tenant_id` — compound primary keys where appropriate.",
      "Postgres Row-Level Security (RLS) enforced at the database — application code is never the only line of defence.",
      "Weekly automated cross-tenant regression test simulates a breach attempt.",
      "Per-tenant data keys mean a leak of one tenant&apos;s files reveals nothing about another&apos;s.",
    ],
  },
  {
    icon: <KeyRound size={20} style={{ color: "#e6b000" }} />,
    title: "Access &amp; identity",
    bullets: [
      "11 built-in roles: Owner · Manager · Reservations · Concierge · FOH · Marketing · Compliance · QA · Coach · Read-only.",
      "Attribute-based scoping — Concierge for Villa A only sees Villa A.",
      "SSO via Google + Microsoft on every tier. SAML / SCIM on Enterprise (WorkOS).",
      "MFA mandatory for Owner and Compliance roles. Session: 15-min JWT + 30-day refresh.",
    ],
  },
  {
    icon: <Eye size={20} style={{ color: "#00555a" }} />,
    title: "Audit &amp; observability",
    bullets: [
      "Append-only, hash-chained audit log — 5-year retention.",
      "Every score, override, export, login, role change is captured with actor + timestamp.",
      "Per-tenant audit export to S3 or your bucket.",
      "Sentry + Grafana for real-time error and performance monitoring.",
    ],
  },
  {
    icon: <FileCheck2 size={20} style={{ color: "#e11d48" }} />,
    title: "DPDP &amp; PII handling",
    bullets: [
      "PII redaction at L1 — card / Aadhaar / PAN / phone / email tokenised before transcripts reach the LLM.",
      "Recording consent prompt captured in the IVR greeting; consent events logged in HAIP&apos;s consent log.",
      "Delete-on-request flow — guest record + linked rows + recordings purged within 30 days.",
      "Sub-processor list public — DPAs signed with Anthropic, Deepgram, AWS, and your IVR provider.",
    ],
  },
  {
    icon: <Globe2 size={20} style={{ color: "#16a34a" }} />,
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
  { name: "DPDP Act 2023 (India)", status: "Ready", style: { color: "#15803d", backgroundColor: "rgba(22,163,74,0.08)", border: "1px solid rgba(22,163,74,0.25)" }, note: "Consent capture, residency, deletion workflows" },
  { name: "SOC 2 Type I", status: "In progress · 2026 Q4", style: { color: "#a16207", backgroundColor: "rgba(255,201,75,0.16)", border: "1px solid rgba(230,176,0,0.30)" }, note: "Audit kick-off scheduled" },
  { name: "ISO 27001", status: "Planned · 2027", style: { color: "#64748B", backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0" }, note: "Post SOC 2" },
  { name: "GDPR", status: "Aligned", style: { color: "#15803d", backgroundColor: "rgba(22,163,74,0.08)", border: "1px solid rgba(22,163,74,0.25)" }, note: "EU-tenant data residency on Enterprise" },
  { name: "Annual pen test", status: "From Year 2", style: { color: "#a16207", backgroundColor: "rgba(255,201,75,0.16)", border: "1px solid rgba(230,176,0,0.30)" }, note: "Third-party tester contracted" },
];

export default function SecurityPage() {
  return (
    <div className="min-h-screen" style={{ backgroundColor: "var(--mkt-bg)", color: "#0F172A" }}>
      {/* HERO */}
      <section className="relative pt-32 pb-20 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[800px] h-[400px] rounded-full blur-[120px]" style={{ backgroundColor: "rgba(0,85,90,0.06)" }} />
          <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle, #00555a15 1px, transparent 1px)", backgroundSize: "28px 28px" }} />
        </div>
        <div className="relative max-w-5xl mx-auto px-5 sm:px-8 text-center">
          <div className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 mb-6" style={{ backgroundColor: "rgba(0,85,90,0.07)", border: "1px solid rgba(0,85,90,0.25)" }}>
            <Shield size={12} style={{ color: "#00555a" }} />
            <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#00555a" }}>Trust center</span>
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight leading-[1.05] mb-5" style={{ color: "#0F172A" }}>
            Security &amp; privacy at HAIP
          </h1>
          <p className="text-lg max-w-2xl mx-auto leading-relaxed mb-8" style={{ color: "#475569" }}>
            We store voice recordings, guest PII, and full conversation history for paying clients. Multi-tenancy and encryption have to be airtight from day one — here is exactly how we do it.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <a href="mailto:security@haip.app" className="inline-flex items-center gap-2 px-6 py-3 font-bold rounded-2xl transition-all text-white" style={{ backgroundColor: "#00555a", boxShadow: "0 8px 24px rgba(0,85,90,0.28)" }}>
              <Mail size={16} /> Email security@haip.app
            </a>
            <Link href="/dpdp" className="inline-flex items-center gap-2 px-6 py-3 font-semibold rounded-2xl transition-all" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", color: "#334155" }}>
              DPDP compliance details <ArrowRight size={16} />
            </Link>
          </div>
        </div>
      </section>

      {/* TOP CALLOUTS */}
      <section className="px-5 sm:px-8 pb-8">
        <div className="max-w-6xl mx-auto grid sm:grid-cols-3 gap-4">
          {[
            { icon: <Server size={18} style={{ color: "#00555a" }} />, title: "India-first", desc: "AWS Mumbai (ap-south-1) by default. No US/EU spillover for Indian tenants." },
            { icon: <BadgeCheck size={18} style={{ color: "#16a34a" }} />, title: "DPDP-ready", desc: "Consent · residency · deletion · audit log · sub-processor disclosure." },
            { icon: <KeyRound size={18} style={{ color: "#e6b000" }} />, title: "Per-tenant KMS", desc: "Your recordings encrypted with a key only your tenant can use." },
          ].map(c => (
            <div key={c.title} className="rounded-2xl p-5 flex items-start gap-3" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
              <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#F8FAFC", border: "1px solid #F1F5F9" }}>{c.icon}</div>
              <div>
                <p className="text-sm font-bold mb-0.5" style={{ color: "#0F172A" }}>{c.title}</p>
                <p className="text-xs leading-relaxed" style={{ color: "#64748B" }}>{c.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* SECURITY PILLARS */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#00555a" }}>How we protect your data</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight" style={{ color: "#0F172A" }}>Six pillars · production from day one</h2>
          </div>
          <div className="grid md:grid-cols-2 gap-5">
            {pillars.map(p => (
              <div key={p.title} className="rounded-2xl p-6 transition-colors" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{ backgroundColor: "#F8FAFC", border: "1px solid #F1F5F9" }}>{p.icon}</div>
                  <h3 className="text-lg font-bold" style={{ color: "#0F172A" }} dangerouslySetInnerHTML={{ __html: p.title }} />
                </div>
                <ul className="space-y-2.5">
                  {p.bullets.map(b => (
                    <li key={b} className="flex items-start gap-2.5 text-sm leading-relaxed" style={{ color: "#475569" }}>
                      <CheckCircle2 size={14} className="flex-shrink-0 mt-1" style={{ color: "#00555a" }} />
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
      <section className="py-20 px-5 sm:px-8" style={{ backgroundColor: "#003d41" }}>
        <div className="max-w-5xl mx-auto">
          <div className="mb-10">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#ffc94b" }}>Sub-processor registry</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-3" style={{ color: "#ffffff" }}>Every third party that touches your data</h2>
            <p className="max-w-2xl" style={{ color: "rgba(255,255,255,0.60)" }}>Public list. Data Processing Agreements (DPAs) signed with each. We will notify you in advance of any new sub-processor we onboard.</p>
          </div>
          <div className="rounded-2xl overflow-hidden" style={{ backgroundColor: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.10)" }}>
            <div className="grid grid-cols-12 gap-4 px-5 py-3 text-[11px] font-bold uppercase tracking-widest" style={{ borderBottom: "1px solid rgba(255,255,255,0.10)", color: "rgba(255,255,255,0.45)" }}>
              <div className="col-span-4">Sub-processor</div>
              <div className="col-span-5">Purpose</div>
              <div className="col-span-3">Region</div>
            </div>
            {subprocessors.map(s => (
              <div key={s.name} className="grid grid-cols-12 gap-4 px-5 py-4 text-sm transition-colors" style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                <div className="col-span-4 font-semibold" style={{ color: "#ffffff" }} dangerouslySetInnerHTML={{ __html: s.name }} />
                <div className="col-span-5" style={{ color: "rgba(255,255,255,0.60)" }} dangerouslySetInnerHTML={{ __html: s.purpose }} />
                <div className="col-span-3 text-xs flex items-center" style={{ color: "rgba(255,255,255,0.50)" }} dangerouslySetInnerHTML={{ __html: s.region }} />
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* COMPLIANCE STATUS */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-5xl mx-auto">
          <div className="mb-10">
            <p className="text-xs font-bold uppercase tracking-widest mb-3" style={{ color: "#00555a" }}>Compliance status</p>
            <h2 className="text-3xl sm:text-4xl font-black tracking-tight mb-3" style={{ color: "#0F172A" }}>Where we are, and where we&apos;re going</h2>
            <p className="max-w-2xl" style={{ color: "#475569" }}>We don&apos;t claim certifications we don&apos;t hold. Here is the honest status as of {new Date().toLocaleDateString("en-IN", { month: "short", year: "numeric" })}.</p>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            {compliance.map(c => (
              <div key={c.name} className="rounded-2xl p-5" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-base font-bold" style={{ color: "#0F172A" }}>{c.name}</h3>
                  <span className="text-[10px] font-bold px-2 py-1 rounded-md" style={c.style}>{c.status}</span>
                </div>
                <p className="text-xs" style={{ color: "#64748B" }}>{c.note}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* REPORT VULN */}
      <section className="py-20 px-5 sm:px-8" style={{ backgroundColor: "var(--mkt-panel)" }}>
        <div className="max-w-4xl mx-auto rounded-3xl p-8 sm:p-12" style={{ backgroundColor: "#ffffff", border: "1px solid rgba(230,176,0,0.35)", boxShadow: "0 8px 32px rgba(0,0,0,0.06)" }}>
          <div className="flex items-start gap-4 mb-5">
            <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "rgba(255,201,75,0.16)", border: "1px solid rgba(230,176,0,0.30)" }}>
              <AlertTriangle size={20} style={{ color: "#e6b000" }} />
            </div>
            <div>
              <h2 className="text-2xl font-black tracking-tight mb-2" style={{ color: "#0F172A" }}>Reporting a vulnerability</h2>
              <p className="text-base leading-relaxed" style={{ color: "#475569" }}>
                Found something? Please email <a href="mailto:security@haip.app" className="underline" style={{ color: "#a16207" }}>security@haip.app</a> with details. We acknowledge within 1 working day and aim to triage within 3. We don&apos;t pursue legal action against good-faith research.
              </p>
            </div>
          </div>
          <div className="grid sm:grid-cols-3 gap-3 mt-6">
            {[
              { label: "Acknowledgement", value: "&lt; 1 day" },
              { label: "Triage", value: "&lt; 3 days" },
              { label: "High-severity fix", value: "&lt; 14 days" },
            ].map(s => (
              <div key={s.label} className="rounded-xl px-4 py-3 text-center" style={{ backgroundColor: "#F8FAFC", border: "1px solid #F1F5F9" }}>
                <p className="text-lg font-bold" style={{ color: "#a16207" }} dangerouslySetInnerHTML={{ __html: s.value }} />
                <p className="text-[10px] uppercase tracking-widest mt-0.5" style={{ color: "#94A3B8" }}>{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CONTACT FOOTER */}
      <section className="py-20 px-5 sm:px-8">
        <div className="max-w-4xl mx-auto text-center">
          <h2 className="text-2xl sm:text-3xl font-black tracking-tight mb-4" style={{ color: "#0F172A" }}>Need our security pack for a vendor review?</h2>
          <p className="mb-8 max-w-xl mx-auto" style={{ color: "#475569" }}>We&apos;re happy to share our architecture diagram, threat model, DPA, sub-processor registry, and pen-test plan with your compliance team — typically over a 30-minute call.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/book-demo?topic=security" className="inline-flex items-center gap-2 px-6 py-3 font-bold rounded-2xl transition-all text-white" style={{ backgroundColor: "#00555a", boxShadow: "0 8px 24px rgba(0,85,90,0.28)" }}>
              Schedule security review <ArrowRight size={16} />
            </Link>
            <a href="mailto:dpo@haip.app" className="inline-flex items-center gap-2 px-6 py-3 font-semibold rounded-2xl transition-all" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", color: "#334155" }}>
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
