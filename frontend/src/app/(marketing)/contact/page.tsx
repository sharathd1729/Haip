"use client";

import Link from "next/link";
import { useState, FormEvent } from "react";
import {
  ArrowRight, MessageSquare, Mail, Phone, MapPin, Building2, Handshake,
  HelpCircle, CheckCircle2, Clock, Sparkles,
} from "lucide-react";

type ContactForm = {
  fullName: string;
  workEmail: string;
  topic: string;
  message: string;
};

export default function ContactPage() {
  const [form, setForm] = useState<ContactForm>({ fullName: "", workEmail: "", topic: "sales", message: "" });
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!form.fullName || !form.workEmail || !form.message) {
      setError("Please add your name, email and a short message.");
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(form.workEmail)) {
      setError("Please enter a valid work email.");
      return;
    }

    setSubmitting(true);
    try {
      await fetch("/api/leads/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      }).catch(() => null);
      setSuccess(true);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen" style={{ backgroundColor: "var(--mkt-bg)", color: "#0F172A" }}>
      <section className="relative pt-32 pb-24 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full blur-[120px]" style={{ backgroundColor: "rgba(0,85,90,0.06)" }} />
          <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle, #00555a15 1px, transparent 1px)", backgroundSize: "28px 28px" }} />
        </div>

        <div className="relative max-w-6xl mx-auto px-5 sm:px-8">
          <div className="text-center mb-14">
            <div className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 mb-5" style={{ backgroundColor: "rgba(0,85,90,0.07)", border: "1px solid rgba(0,85,90,0.25)" }}>
              <Sparkles size={12} style={{ color: "#00555a" }} />
              <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#00555a" }}>We&apos;d love to hear from you</span>
            </div>
            <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4" style={{ color: "#0F172A" }}>Talk to us</h1>
            <p className="text-lg max-w-xl mx-auto leading-relaxed" style={{ color: "#475569" }}>
              Sales, support, partnerships — pick the right channel and we&apos;ll get back to you fast. Most replies happen inside 2 working hours.
            </p>
          </div>

          {/* Channel split */}
          <div className="grid sm:grid-cols-3 gap-4 mb-12">
            <Channel
              icon={<Handshake size={20} style={{ color: "#00555a" }} />}
              tone="teal"
              title="Sales"
              subtitle="Pricing · demo · onboarding"
              primary={{ label: "Book a demo", href: "/book-demo" }}
              secondary={{ label: "gen.haip@gmail.com", href: "mailto:gen.haip@gmail.com" }}
            />
            <Channel
              icon={<HelpCircle size={20} style={{ color: "#e6b000" }} />}
              tone="amber"
              title="Customer success"
              subtitle="Existing customer · how-to · billing"
              primary={{ label: "WhatsApp support", href: "https://wa.me/+918147698153" }}
              secondary={{ label: "support@haip.app", href: "mailto:support@haip.app" }}
            />
            <Channel
              icon={<Building2 size={20} style={{ color: "#00888f" }} />}
              tone="cyan"
              title="Partnerships"
              subtitle="Resellers · agencies · integrations"
              primary={{ label: "partnerships@haip.app", href: "mailto:partnerships@haip.app" }}
              secondary={{ label: "Become a partner", href: "/partners" }}
            />
          </div>

          {/* Form + info */}
          <div className="grid lg:grid-cols-5 gap-6">
            {/* Form */}
            <div className="lg:col-span-3 rounded-2xl p-7 sm:p-8" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 24px 64px rgba(0,85,90,0.10), 0 4px 16px rgba(0,0,0,0.05)" }}>
              {success ? (
                <div className="text-center py-10">
                  <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5" style={{ backgroundColor: "rgba(0,85,90,0.08)", border: "1px solid rgba(0,85,90,0.20)" }}>
                    <CheckCircle2 size={32} style={{ color: "#00555a" }} />
                  </div>
                  <h3 className="text-xl font-bold mb-2" style={{ color: "#0F172A" }}>Got it, {form.fullName.split(" ")[0]} — message received.</h3>
                  <p className="text-sm max-w-sm mx-auto" style={{ color: "#475569" }}>
                    We&apos;ll get back to you at <span style={{ color: "#0F172A", fontWeight: 600 }}>{form.workEmail}</span> within 2 working hours.
                  </p>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-5">
                  <div>
                    <h3 className="text-lg font-bold mb-1" style={{ color: "#0F172A" }}>Send us a message</h3>
                    <p className="text-xs" style={{ color: "#94A3B8" }}>Anything you&apos;d rather just type out. We read everything.</p>
                  </div>

                  <div className="grid sm:grid-cols-2 gap-4">
                    <label className="block">
                      <span className="text-xs font-semibold mb-1.5 inline-block" style={{ color: "#475569" }}>Full name <span style={{ color: "#e11d48" }}>*</span></span>
                      <input value={form.fullName} onChange={e => setForm({ ...form, fullName: e.target.value })} className="haip-input" placeholder="Your name" />
                    </label>
                    <label className="block">
                      <span className="text-xs font-semibold mb-1.5 inline-block" style={{ color: "#475569" }}>Work email <span style={{ color: "#e11d48" }}>*</span></span>
                      <input type="email" value={form.workEmail} onChange={e => setForm({ ...form, workEmail: e.target.value })} className="haip-input" placeholder="you@brand.com" />
                    </label>
                  </div>

                  <label className="block">
                    <span className="text-xs font-semibold mb-1.5 inline-block" style={{ color: "#475569" }}>What&apos;s this about?</span>
                    <select value={form.topic} onChange={e => setForm({ ...form, topic: e.target.value })} className="haip-input">
                      <option value="sales">Sales / pricing / demo</option>
                      <option value="support">Customer support</option>
                      <option value="partnerships">Partnerships / integrations</option>
                      <option value="security">Security / compliance review</option>
                      <option value="press">Press / media</option>
                      <option value="other">Other</option>
                    </select>
                  </label>

                  <label className="block">
                    <span className="text-xs font-semibold mb-1.5 inline-block" style={{ color: "#475569" }}>Your message <span style={{ color: "#e11d48" }}>*</span></span>
                    <textarea value={form.message} onChange={e => setForm({ ...form, message: e.target.value })} rows={5} className="haip-input resize-none" placeholder="Tell us what you need. The more specific you are, the faster we can help." />
                  </label>

                  {error && (
                    <div className="text-sm rounded-xl px-4 py-3" style={{ backgroundColor: "rgba(225,29,72,0.06)", border: "1px solid rgba(225,29,72,0.25)", color: "#be123c" }}>{error}</div>
                  )}

                  <button type="submit" disabled={submitting} className="w-full inline-flex items-center justify-center gap-2 px-6 py-3.5 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-2xl transition-all" style={{ backgroundColor: "#00555a", boxShadow: "0 8px 24px rgba(0,85,90,0.28)" }}>
                    {submitting ? "Sending…" : (<>Send message <ArrowRight size={16} /></>)}
                  </button>
                </form>
              )}
            </div>

            {/* Info side */}
            <aside className="lg:col-span-2 space-y-4">
              <InfoCard icon={<Clock size={16} style={{ color: "#e6b000" }} />} title="Response times" lines={["Sales: < 2 working hours", "Support: < 4 working hours", "Partnerships: < 1 working day"]} />
              <InfoCard icon={<MapPin size={16} style={{ color: "#e11d48" }} />} title="Where we&apos;re based" lines={["HAIP Technologies Pvt. Ltd.", "Bengaluru, Karnataka, India"]} />
              <InfoCard icon={<Mail size={16} style={{ color: "#00555a" }} />} title="Quick links" lines={[]}>
                <div className="space-y-2 text-sm">
                  <a className="block transition-colors" style={{ color: "#475569" }} href="mailto:gen.haip@gmail.com">gen.haip@gmail.com</a>
                  <a className="block transition-colors" style={{ color: "#475569" }} href="mailto:support@haip.app">support@haip.app</a>
                  <a className="block transition-colors" style={{ color: "#475569" }} href="mailto:security@haip.app">security@haip.app</a>
                  <a className="block transition-colors" style={{ color: "#475569" }} href="mailto:dpo@haip.app">dpo@haip.app (data protection)</a>
                </div>
              </InfoCard>
              <InfoCard icon={<Phone size={16} style={{ color: "#25D366" }} />} title="On the phone" lines={[]}>
                <div className="space-y-1">
                  <p className="text-sm" style={{ color: "#0F172A" }}>+91 81476 98153</p>
                  <p className="text-xs" style={{ color: "#94A3B8" }}>Mon–Sat · 9 am to 8 pm IST</p>
                  <a href="https://wa.me/+918147698153" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-xs mt-1 font-semibold" style={{ color: "#16a34a" }}>
                    <MessageSquare size={11} /> WhatsApp us anytime
                  </a>
                </div>
              </InfoCard>
            </aside>
          </div>
        </div>
      </section>

      {/* shared input styling */}
      <style>{`
        .haip-input {
          width: 100%;
          background: #F8FAFC;
          border: 1px solid #E2E8F0;
          color: #0F172A;
          border-radius: 12px;
          padding: 11px 14px;
          font-size: 14px;
          outline: none;
          transition: border-color .15s, background .15s, box-shadow .15s;
        }
        .haip-input:focus { border-color: rgba(0,85,90,0.55); background: #ffffff; box-shadow: 0 0 0 3px rgba(0,85,90,0.10); }
        .haip-input::placeholder { color: #94A3B8; }
        select.haip-input { appearance: none; background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>"); background-repeat: no-repeat; background-position: right 12px center; padding-right: 36px; }
        select.haip-input option { background: #ffffff; color: #0F172A; }
      `}</style>
    </div>
  );
}

function Channel({ icon, tone, title, subtitle, primary, secondary }: {
  icon: React.ReactNode;
  tone: "teal" | "amber" | "cyan";
  title: string;
  subtitle: string;
  primary: { label: string; href: string };
  secondary: { label: string; href: string };
}) {
  const chipBg = tone === "teal" ? "rgba(0,85,90,0.08)" : tone === "amber" ? "rgba(255,201,75,0.18)" : "rgba(0,136,143,0.10)";
  return (
    <div className="rounded-2xl p-6 transition-all duration-200 hover:-translate-y-0.5" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
      <div className="w-11 h-11 rounded-xl flex items-center justify-center mb-4" style={{ backgroundColor: chipBg }}>{icon}</div>
      <h3 className="text-base font-bold mb-1" style={{ color: "#0F172A" }}>{title}</h3>
      <p className="text-xs mb-5" style={{ color: "#94A3B8" }}>{subtitle}</p>
      <Link href={primary.href} className="inline-flex items-center gap-1.5 text-sm font-semibold mb-2.5" style={{ color: "#00555a" }}>
        {primary.label} <ArrowRight size={14} />
      </Link>
      <Link href={secondary.href} className="block text-xs transition-colors" style={{ color: "#64748B" }}>
        {secondary.label}
      </Link>
    </div>
  );
}

function InfoCard({ icon, title, lines, children }: {
  icon: React.ReactNode;
  title: string;
  lines: string[];
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl p-5" style={{ backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0" }}>
      <div className="flex items-center gap-2 mb-3">
        <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0" }}>{icon}</div>
        <h4 className="text-sm font-bold" style={{ color: "#0F172A" }}>{title}</h4>
      </div>
      {lines.length > 0 && (
        <ul className="space-y-1 text-sm" style={{ color: "#475569" }}>
          {lines.map(l => <li key={l}>{l}</li>)}
        </ul>
      )}
      {children}
    </div>
  );
}
