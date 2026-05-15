"use client";

import Link from "next/link";
import { useState, FormEvent } from "react";
import {
  ArrowRight, CheckCircle2, Sparkles, Phone, MessageSquare,
  Building2, Users, Calendar, Clock, Shield,
} from "lucide-react";

type FormState = {
  fullName: string;
  workEmail: string;
  phone: string;
  company: string;
  segment: string;
  properties: string;
  source: string;
  notes: string;
};

const initialForm: FormState = {
  fullName: "",
  workEmail: "",
  phone: "",
  company: "",
  segment: "villas",
  properties: "1-3",
  source: "",
  notes: "",
};

export default function BookDemoPage() {
  const [form, setForm] = useState<FormState>(initialForm);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm(prev => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!form.fullName || !form.workEmail || !form.phone || !form.company) {
      setError("Please fill in your name, email, phone and company name.");
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(form.workEmail)) {
      setError("Please enter a valid work email.");
      return;
    }

    setSubmitting(true);
    try {
      // Best-effort submit; backend endpoint stub
      await fetch("/api/leads/demo", {
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
    <div className="bg-[#0B1F3A] text-white min-h-screen">
      <section className="relative pt-32 pb-24 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/4 w-[700px] h-[500px] rounded-full bg-teal-500/8 blur-[120px]" />
          <div className="absolute bottom-0 right-0 w-[500px] h-[400px] rounded-full bg-cyan-500/8 blur-[100px]" />
          <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "radial-gradient(circle, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
        </div>

        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 grid lg:grid-cols-12 gap-12 items-start">
          {/* LEFT: pitch */}
          <div className="lg:col-span-5 lg:sticky lg:top-28">
            <div className="inline-flex items-center gap-2 bg-teal-500/10 border border-teal-500/20 rounded-full px-4 py-1.5 mb-6">
              <Calendar size={12} className="text-teal-400" />
              <span className="text-xs font-semibold text-teal-300 uppercase tracking-wider">Book a 30-min demo</span>
            </div>
            <h1 className="text-4xl sm:text-5xl font-black tracking-tight leading-[1.05] mb-5">
              See HAIP run live on your
              <span className="text-teal-400"> own enquiries.</span>
            </h1>
            <p className="text-white/55 text-lg leading-relaxed mb-8">
              In 30 minutes, we&apos;ll walk you through the unified inbox, AI Concierge in shadow mode, auto-QA on a real call recording, and the cockpit your team would use day-to-day. No slideware.
            </p>

            <div className="space-y-3 mb-8">
              {[
                { icon: <Sparkles size={14} />, text: "Live AI Concierge demo with your guest enquiries" },
                { icon: <Phone size={14} />, text: "Auto-QA on a recording you bring (or one of ours)" },
                { icon: <Users size={14} />, text: "Role-by-role tour — owner, reservations, concierge, FOH" },
                { icon: <Shield size={14} />, text: "DPDP + tenancy + BYOC questions answered" },
              ].map(item => (
                <div key={item.text} className="flex items-start gap-3 bg-white/3 border border-white/6 rounded-xl px-4 py-3">
                  <div className="w-8 h-8 rounded-lg bg-teal-500/15 flex items-center justify-center text-teal-400 flex-shrink-0">
                    {item.icon}
                  </div>
                  <p className="text-sm text-white/70 leading-relaxed pt-1.5">{item.text}</p>
                </div>
              ))}
            </div>

            {/* Quote */}
            <div className="bg-[#0f2744]/70 border border-white/10 rounded-2xl p-6">
              <div className="flex gap-1 mb-3">{[...Array(5)].map((_, i) => <span key={i} className="text-teal-400 text-sm">★</span>)}</div>
              <p className="text-sm text-white/70 italic leading-relaxed mb-4">
                &ldquo;Best 30 minutes I&apos;ve spent in a sales call this year. They demoed HAIP on my actual WhatsApp inbox — I signed up at the end of the meeting.&rdquo;
              </p>
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-teal-500 flex items-center justify-center text-xs font-bold text-white">VR</div>
                <div>
                  <p className="text-xs font-bold text-white">Vikrant R.</p>
                  <p className="text-[10px] text-white/40">Founder, Ananta Villa Collection</p>
                </div>
              </div>
            </div>
          </div>

          {/* RIGHT: form */}
          <div className="lg:col-span-7">
            <div className="bg-[#0f2744] border border-white/10 rounded-2xl p-7 sm:p-9 shadow-2xl shadow-black/30">
              {success ? (
                <div className="text-center py-12">
                  <div className="w-16 h-16 rounded-2xl bg-teal-500/20 border border-teal-500/30 flex items-center justify-center mx-auto mb-6">
                    <CheckCircle2 size={32} className="text-teal-400" />
                  </div>
                  <h2 className="text-2xl font-black mb-3">Thanks, {form.fullName.split(" ")[0]}!</h2>
                  <p className="text-white/55 max-w-md mx-auto leading-relaxed mb-8">
                    A member of our team will WhatsApp you within 2 working hours with a 3-slot calendar link. Most demos happen within 24 hours.
                  </p>
                  <div className="flex flex-col sm:flex-row gap-3 justify-center">
                    <Link href="/" className="px-5 py-2.5 bg-teal-500 hover:bg-teal-400 rounded-xl text-sm font-semibold text-white transition-colors">Back to home</Link>
                    <a href={`https://wa.me/+919876543210?text=Hi%20HAIP%2C%20I%20just%20booked%20a%20demo%20%E2%80%94%20here%27s%20my%20company%3A%20${encodeURIComponent(form.company)}`} target="_blank" rel="noopener noreferrer" className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-sm font-semibold text-white transition-colors inline-flex items-center justify-center gap-2">
                      <MessageSquare size={14} /> Message us on WhatsApp now
                    </a>
                  </div>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-5">
                  <div>
                    <h2 className="text-xl font-bold mb-1">Tell us about you</h2>
                    <p className="text-xs text-white/40">All fields except notes are required. We&apos;ll WhatsApp you with calendar slots.</p>
                  </div>

                  <div className="grid sm:grid-cols-2 gap-4">
                    <Field label="Full name" required>
                      <input value={form.fullName} onChange={e => update("fullName", e.target.value)} className="haip-input" placeholder="Your name" />
                    </Field>
                    <Field label="Work email" required>
                      <input type="email" value={form.workEmail} onChange={e => update("workEmail", e.target.value)} className="haip-input" placeholder="you@brand.com" />
                    </Field>
                  </div>

                  <div className="grid sm:grid-cols-2 gap-4">
                    <Field label="Phone (WhatsApp)" required>
                      <input value={form.phone} onChange={e => update("phone", e.target.value)} className="haip-input" placeholder="+91 98xxx xxxxx" />
                    </Field>
                    <Field label="Company / brand" required>
                      <input value={form.company} onChange={e => update("company", e.target.value)} className="haip-input" placeholder="Your company" />
                    </Field>
                  </div>

                  <div className="grid sm:grid-cols-2 gap-4">
                    <Field label="What do you operate?">
                      <select value={form.segment} onChange={e => update("segment", e.target.value)} className="haip-input">
                        <option value="villas">Luxury villas</option>
                        <option value="hotels">Boutique hotel</option>
                        <option value="resorts">Resort / multi-property group</option>
                        <option value="travel">Experiential travel / DMC</option>
                        <option value="other">Other hospitality</option>
                      </select>
                    </Field>
                    <Field label="How many properties / brands?">
                      <select value={form.properties} onChange={e => update("properties", e.target.value)} className="haip-input">
                        <option value="1-3">1–3</option>
                        <option value="4-10">4–10</option>
                        <option value="11-25">11–25</option>
                        <option value="25+">25+</option>
                      </select>
                    </Field>
                  </div>

                  <Field label="How did you hear about HAIP?">
                    <input value={form.source} onChange={e => update("source", e.target.value)} className="haip-input" placeholder="Google · referral · LinkedIn · Instagram · other" />
                  </Field>

                  <Field label="Anything specific you want to see?">
                    <textarea value={form.notes} onChange={e => update("notes", e.target.value)} rows={3} className="haip-input resize-none" placeholder="E.g., How AI Concierge handles weekend volume; Hostaway integration depth; security questions for compliance team." />
                  </Field>

                  {error && (
                    <div className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm rounded-xl px-4 py-3">{error}</div>
                  )}

                  <button type="submit" disabled={submitting} className="w-full inline-flex items-center justify-center gap-2 px-6 py-3.5 bg-teal-500 hover:bg-teal-400 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-2xl transition-all shadow-xl shadow-teal-500/30">
                    {submitting ? "Sending…" : (<>Book my 30-min demo <ArrowRight size={16} /></>)}
                  </button>

                  <p className="text-[11px] text-white/30 text-center leading-relaxed">
                    By submitting you agree to HAIP&apos;s <Link href="/privacy" className="underline hover:text-white/60">privacy policy</Link> and <Link href="/terms" className="underline hover:text-white/60">terms</Link>. We&apos;ll never share your data. DPDP compliant.
                  </p>
                </form>
              )}
            </div>

            {/* Alt-contact strip */}
            <div className="mt-5 grid sm:grid-cols-3 gap-3">
              <a href="https://wa.me/+919876543210" target="_blank" rel="noopener noreferrer" className="bg-[#0f2744]/60 hover:bg-[#0f2744] border border-white/8 hover:border-green-500/30 rounded-xl px-4 py-3 flex items-center gap-3 transition-colors">
                <MessageSquare size={16} className="text-green-400 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-[11px] text-white/40">WhatsApp us</p>
                  <p className="text-xs font-semibold text-white truncate">+91 98765 43210</p>
                </div>
              </a>
              <a href="mailto:hello@haip.app" className="bg-[#0f2744]/60 hover:bg-[#0f2744] border border-white/8 hover:border-teal-500/30 rounded-xl px-4 py-3 flex items-center gap-3 transition-colors">
                <Building2 size={16} className="text-teal-400 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-[11px] text-white/40">Email sales</p>
                  <p className="text-xs font-semibold text-white truncate">hello@haip.app</p>
                </div>
              </a>
              <div className="bg-[#0f2744]/60 border border-white/8 rounded-xl px-4 py-3 flex items-center gap-3">
                <Clock size={16} className="text-amber-400 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-[11px] text-white/40">Avg. response</p>
                  <p className="text-xs font-semibold text-white truncate">&lt; 2 working hours</p>
                </div>
              </div>
            </div>
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
        .haip-input:focus {
          border-color: rgba(20,184,166,0.55);
          background: rgba(255,255,255,0.06);
        }
        .haip-input::placeholder { color: rgba(255,255,255,0.25); }
        select.haip-input { appearance: none; background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>"); background-repeat: no-repeat; background-position: right 12px center; padding-right: 36px; }
        select.haip-input option { background: #0f2744; color: white; }
      `}</style>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-semibold text-white/55 mb-1.5 inline-block">
        {label}{required && <span className="text-rose-400 ml-0.5">*</span>}
      </span>
      {children}
    </label>
  );
}
