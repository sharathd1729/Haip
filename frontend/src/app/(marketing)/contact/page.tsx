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
    <div className="bg-[var(--mkt-bg)] text-white min-h-screen">
      <section className="relative pt-32 pb-24 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full bg-teal-500/8 blur-[120px]" />
          <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "radial-gradient(circle, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
        </div>

        <div className="relative max-w-6xl mx-auto px-5 sm:px-8">
          <div className="text-center mb-14">
            <div className="inline-flex items-center gap-2 bg-teal-500/10 border border-teal-500/20 rounded-full px-4 py-1.5 mb-5">
              <Sparkles size={12} className="text-teal-400" />
              <span className="text-xs font-semibold text-teal-300 uppercase tracking-wider">We&apos;d love to hear from you</span>
            </div>
            <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4">Talk to us</h1>
            <p className="text-white/55 text-lg max-w-xl mx-auto leading-relaxed">
              Sales, support, partnerships — pick the right channel and we&apos;ll get back to you fast. Most replies happen inside 2 working hours.
            </p>
          </div>

          {/* Channel split */}
          <div className="grid sm:grid-cols-3 gap-4 mb-12">
            <Channel
              icon={<Handshake size={20} className="text-teal-400" />}
              tone="teal"
              title="Sales"
              subtitle="Pricing · demo · onboarding"
              primary={{ label: "Book a demo", href: "/book-demo" }}
              secondary={{ label: "gen.haip@gmail.com", href: "mailto:gen.haip@gmail.com" }}
            />
            <Channel
              icon={<HelpCircle size={20} className="text-amber-400" />}
              tone="amber"
              title="Customer success"
              subtitle="Existing customer · how-to · billing"
              primary={{ label: "WhatsApp support", href: "https://wa.me/+918147698153" }}
              secondary={{ label: "support@haip.app", href: "mailto:support@haip.app" }}
            />
            <Channel
              icon={<Building2 size={20} className="text-cyan-400" />}
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
            <div className="lg:col-span-3 bg-[var(--mkt-panel)] border border-white/10 rounded-2xl p-7 sm:p-8 shadow-2xl shadow-black/30">
              {success ? (
                <div className="text-center py-10">
                  <div className="w-16 h-16 rounded-2xl bg-teal-500/20 border border-teal-500/30 flex items-center justify-center mx-auto mb-5">
                    <CheckCircle2 size={32} className="text-teal-400" />
                  </div>
                  <h3 className="text-xl font-bold mb-2">Got it, {form.fullName.split(" ")[0]} — message received.</h3>
                  <p className="text-sm text-white/55 max-w-sm mx-auto">
                    We&apos;ll get back to you at <span className="text-white">{form.workEmail}</span> within 2 working hours.
                  </p>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-5">
                  <div>
                    <h3 className="text-lg font-bold mb-1">Send us a message</h3>
                    <p className="text-xs text-white/40">Anything you&apos;d rather just type out. We read everything.</p>
                  </div>

                  <div className="grid sm:grid-cols-2 gap-4">
                    <label className="block">
                      <span className="text-xs font-semibold text-white/55 mb-1.5 inline-block">Full name <span className="text-rose-400">*</span></span>
                      <input value={form.fullName} onChange={e => setForm({ ...form, fullName: e.target.value })} className="haip-input" placeholder="Your name" />
                    </label>
                    <label className="block">
                      <span className="text-xs font-semibold text-white/55 mb-1.5 inline-block">Work email <span className="text-rose-400">*</span></span>
                      <input type="email" value={form.workEmail} onChange={e => setForm({ ...form, workEmail: e.target.value })} className="haip-input" placeholder="you@brand.com" />
                    </label>
                  </div>

                  <label className="block">
                    <span className="text-xs font-semibold text-white/55 mb-1.5 inline-block">What&apos;s this about?</span>
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
                    <span className="text-xs font-semibold text-white/55 mb-1.5 inline-block">Your message <span className="text-rose-400">*</span></span>
                    <textarea value={form.message} onChange={e => setForm({ ...form, message: e.target.value })} rows={5} className="haip-input resize-none" placeholder="Tell us what you need. The more specific you are, the faster we can help." />
                  </label>

                  {error && (
                    <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm rounded-xl px-4 py-3">{error}</div>
                  )}

                  <button type="submit" disabled={submitting} className="w-full inline-flex items-center justify-center gap-2 px-6 py-3.5 bg-teal-500 hover:bg-teal-400 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-2xl transition-all shadow-xl shadow-teal-500/30">
                    {submitting ? "Sending…" : (<>Send message <ArrowRight size={16} /></>)}
                  </button>
                </form>
              )}
            </div>

            {/* Info side */}
            <aside className="lg:col-span-2 space-y-4">
              <InfoCard icon={<Clock size={16} className="text-amber-400" />} title="Response times" lines={["Sales: < 2 working hours", "Support: < 4 working hours", "Partnerships: < 1 working day"]} />
              <InfoCard icon={<MapPin size={16} className="text-rose-400" />} title="Where we&apos;re based" lines={["HAIP Technologies Pvt. Ltd.", "Bengaluru, Karnataka, India"]} />
              <InfoCard icon={<Mail size={16} className="text-teal-400" />} title="Quick links" lines={[]}>
                <div className="space-y-2 text-sm">
                  <a className="block text-white/60 hover:text-white" href="mailto:gen.haip@gmail.com">gen.haip@gmail.com</a>
                  <a className="block text-white/60 hover:text-white" href="mailto:support@haip.app">support@haip.app</a>
                  <a className="block text-white/60 hover:text-white" href="mailto:security@haip.app">security@haip.app</a>
                  <a className="block text-white/60 hover:text-white" href="mailto:dpo@haip.app">dpo@haip.app (data protection)</a>
                </div>
              </InfoCard>
              <InfoCard icon={<Phone size={16} className="text-green-400" />} title="On the phone" lines={[]}>
                <div className="space-y-1">
                  <p className="text-sm text-white">+91 81476 98153</p>
                  <p className="text-xs text-white/40">Mon–Sat · 9 am to 8 pm IST</p>
                  <a href="https://wa.me/+918147698153" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-xs text-green-400 hover:text-green-300 mt-1 font-semibold">
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
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.10);
          color: white;
          border-radius: 12px;
          padding: 11px 14px;
          font-size: 14px;
          outline: none;
          transition: border-color .15s, background .15s;
        }
        .haip-input:focus { border-color: rgba(20,184,166,0.55); background: rgba(255,255,255,0.06); }
        .haip-input::placeholder { color: rgba(255,255,255,0.25); }
        select.haip-input { appearance: none; background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>"); background-repeat: no-repeat; background-position: right 12px center; padding-right: 36px; }
        select.haip-input option { background: #141B15; color: white; }
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
  const ring = tone === "teal" ? "hover:border-teal-500/30" : tone === "amber" ? "hover:border-amber-500/30" : "hover:border-cyan-500/30";
  return (
    <div className={`bg-[var(--mkt-panel)]/70 border border-white/8 ${ring} rounded-2xl p-6 transition-colors`}>
      <div className="w-11 h-11 rounded-xl bg-white/5 flex items-center justify-center mb-4">{icon}</div>
      <h3 className="text-base font-bold text-white mb-1">{title}</h3>
      <p className="text-xs text-white/40 mb-5">{subtitle}</p>
      <Link href={primary.href} className="inline-flex items-center gap-1.5 text-sm font-semibold text-teal-400 hover:text-teal-300 mb-2.5">
        {primary.label} <ArrowRight size={14} />
      </Link>
      <Link href={secondary.href} className="block text-xs text-white/50 hover:text-white/80 transition-colors">
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
    <div className="bg-[var(--mkt-panel)]/60 border border-white/8 rounded-2xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-7 h-7 rounded-lg bg-white/5 flex items-center justify-center">{icon}</div>
        <h4 className="text-sm font-bold text-white">{title}</h4>
      </div>
      {lines.length > 0 && (
        <ul className="space-y-1 text-sm text-white/55">
          {lines.map(l => <li key={l}>{l}</li>)}
        </ul>
      )}
      {children}
    </div>
  );
}
