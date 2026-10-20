"use client";

import Link from "next/link";
import { useState, FormEvent } from "react";
import { ArrowRight, CheckCircle2, Sparkles, Phone, MessageSquare, Building2, Users, Calendar, Clock, Shield } from "@/lib/icons";
import { ConsentCheckbox, Honeypot } from "@/components/marketing/LeadFormParts";
import { newSubmissionId, submitPublicLead } from "@/lib/publicLeads";

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
  const [consent, setConsent] = useState(false);
  const [marketing, setMarketing] = useState(false);
  const [honeypot, setHoneypot] = useState("");
  // One id per form fill: a retry after an error re-sends it, so the server never stores the same request twice.
  const [submissionId] = useState(newSubmissionId);

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

    if (!consent) {
      setError("Please accept the privacy notice so we can contact you.");
      return;
    }

    setSubmitting(true);
    try {
      const result = await submitPublicLead({
        kind: "demo",
        submission_id: submissionId,
        name: form.fullName,
        email: form.workEmail,
        phone: form.phone,
        company: form.company,
        message: form.notes || null,
        details: { segment: form.segment, properties: form.properties, ...(form.source ? { source: form.source } : {}) },
        consent,
        marketing_opt_in: marketing,
        website: honeypot,
      });
      if (result.ok) setSuccess(true);
      else setError(result.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen" style={{ backgroundColor: "var(--mkt-bg)", color: "#0F172A" }}>
      <section className="relative pt-32 pb-24 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/4 w-[700px] h-[500px] rounded-full blur-[120px]" style={{ backgroundColor: "rgba(0,85,90,0.06)" }} />
          <div className="absolute bottom-0 right-0 w-[500px] h-[400px] rounded-full blur-[100px]" style={{ backgroundColor: "rgba(255,201,75,0.07)" }} />
          <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle, #00555a15 1px, transparent 1px)", backgroundSize: "28px 28px" }} />
        </div>

        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 grid lg:grid-cols-12 gap-12 items-start">
          {/* LEFT: pitch */}
          <div className="lg:col-span-5 lg:sticky lg:top-28">
            <div className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 mb-6" style={{ backgroundColor: "rgba(0,85,90,0.07)", border: "1px solid rgba(0,85,90,0.25)" }}>
              <Calendar size={12} style={{ color: "#00555a" }} />
              <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#00555a" }}>Book a 30-min demo</span>
            </div>
            <h1 className="text-4xl sm:text-5xl font-black tracking-tight leading-[1.05] mb-5" style={{ color: "#0F172A" }}>
              See HAIP run live on your
              <span style={{ color: "#00555a" }}> own enquiries.</span>
            </h1>
            <p className="text-lg leading-relaxed mb-8" style={{ color: "#475569" }}>
              In 30 minutes, we&apos;ll walk you through the unified inbox, AI Concierge in shadow mode, auto-QA on a real call recording, and the cockpit your team would use day-to-day. No slideware.
            </p>

            <div className="space-y-3 mb-8">
              {[
                { icon: <Sparkles size={14} />, text: "Live AI Concierge demo with your guest enquiries" },
                { icon: <Phone size={14} />, text: "Auto-QA on a recording you bring (or one of ours)" },
                { icon: <Users size={14} />, text: "Role-by-role tour — owner, reservations, concierge, FOH" },
                { icon: <Shield size={14} />, text: "DPDP + tenancy + BYOC questions answered" },
              ].map(item => (
                <div key={item.text} className="flex items-start gap-3 rounded-xl px-4 py-3" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}>
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "rgba(0,85,90,0.08)", color: "#00555a" }}>
                    {item.icon}
                  </div>
                  <p className="text-sm leading-relaxed pt-1.5" style={{ color: "#334155" }}>{item.text}</p>
                </div>
              ))}
            </div>

            {/* Quote */}
            <div className="rounded-2xl p-6" style={{ backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0" }}>
              <div className="flex gap-1 mb-3">{[...Array(5)].map((_, i) => <span key={i} className="text-sm" style={{ color: "#ffc94b" }}>★</span>)}</div>
              <p className="text-sm italic leading-relaxed mb-4" style={{ color: "#475569" }}>
                &ldquo;Best 30 minutes I&apos;ve spent in a sales call this year. They demoed HAIP on my actual WhatsApp inbox — I signed up at the end of the meeting.&rdquo;
              </p>
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-white" style={{ backgroundColor: "#00555a" }}>VR</div>
                <div>
                  <p className="text-xs font-bold" style={{ color: "#0F172A" }}>Vikrant R.</p>
                  <p className="text-[10px]" style={{ color: "#94A3B8" }}>Founder, Ananta Villa Collection</p>
                </div>
              </div>
            </div>
          </div>

          {/* RIGHT: form */}
          <div className="lg:col-span-7">
            <div className="rounded-2xl p-7 sm:p-9" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 24px 64px rgba(0,85,90,0.10), 0 4px 16px rgba(0,0,0,0.05)" }}>
              {success ? (
                <div className="text-center py-12">
                  <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-6" style={{ backgroundColor: "rgba(0,85,90,0.08)", border: "1px solid rgba(0,85,90,0.20)" }}>
                    <CheckCircle2 size={32} style={{ color: "#00555a" }} />
                  </div>
                  <h2 className="text-2xl font-black mb-3" style={{ color: "#0F172A" }}>Thanks, {form.fullName.split(" ")[0]}!</h2>
                  <p className="max-w-md mx-auto leading-relaxed mb-8" style={{ color: "#475569" }}>
                    A member of our team will WhatsApp you within 2 working hours with a 3-slot calendar link. Most demos happen within 24 hours.
                  </p>
                  <div className="flex flex-col sm:flex-row gap-3 justify-center">
                    <Link href="/" className="px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-colors" style={{ backgroundColor: "#00555a" }}>Back to home</Link>
                    <a href={`https://wa.me/+918147698153?text=Hi%20HAIP%2C%20I%20just%20booked%20a%20demo%20%E2%80%94%20here%27s%20my%20company%3A%20${encodeURIComponent(form.company)}`} target="_blank" rel="noopener noreferrer" className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors inline-flex items-center justify-center gap-2" style={{ backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0", color: "#334155" }}>
                      <MessageSquare size={14} /> Message us on WhatsApp now
                    </a>
                  </div>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="relative space-y-5">
                  <div>
                    <h2 className="text-xl font-bold mb-1" style={{ color: "#0F172A" }}>Tell us about you</h2>
                    <p className="text-xs" style={{ color: "#94A3B8" }}>All fields except notes are required. We&apos;ll WhatsApp you with calendar slots.</p>
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

                  <ConsentCheckbox checked={consent} onChange={setConsent} marketing={marketing} onMarketingChange={setMarketing} />
                  <Honeypot value={honeypot} onChange={setHoneypot} />

                  {error && (
                    <div role="alert" className="text-sm rounded-xl px-4 py-3" style={{ backgroundColor: "rgba(225,29,72,0.06)", border: "1px solid rgba(225,29,72,0.25)", color: "#be123c" }}>{error}</div>
                  )}

                  <button type="submit" disabled={submitting} className="w-full inline-flex items-center justify-center gap-2 px-6 py-3.5 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-2xl transition-all" style={{ backgroundColor: "#00555a", boxShadow: "0 8px 24px rgba(0,85,90,0.28)" }}>
                    {submitting ? "Sending…" : (<>Book my 30-min demo <ArrowRight size={16} /></>)}
                  </button>

                  <p className="text-[11px] text-center leading-relaxed" style={{ color: "#94A3B8" }}>
                    See also HAIP&apos;s <Link href="/terms" className="underline" style={{ color: "#00555a" }}>terms</Link>.
                  </p>
                </form>
              )}
            </div>

            {/* Alt-contact strip */}
            <div className="mt-5 grid sm:grid-cols-3 gap-3">
              <a href="https://wa.me/+918147698153" target="_blank" rel="noopener noreferrer" className="rounded-xl px-4 py-3 flex items-center gap-3 transition-colors" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0" }}>
                <MessageSquare size={16} className="flex-shrink-0" style={{ color: "#25D366" }} />
                <div className="min-w-0">
                  <p className="text-[11px]" style={{ color: "#94A3B8" }}>WhatsApp us</p>
                  <p className="text-xs font-semibold truncate" style={{ color: "#0F172A" }}>+91 81476 98153</p>
                </div>
              </a>
              <a href="mailto:gen.haip@gmail.com" className="rounded-xl px-4 py-3 flex items-center gap-3 transition-colors" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0" }}>
                <Building2 size={16} className="flex-shrink-0" style={{ color: "#00555a" }} />
                <div className="min-w-0">
                  <p className="text-[11px]" style={{ color: "#94A3B8" }}>Email sales</p>
                  <p className="text-xs font-semibold truncate" style={{ color: "#0F172A" }}>gen.haip@gmail.com</p>
                </div>
              </a>
              <div className="rounded-xl px-4 py-3 flex items-center gap-3" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0" }}>
                <Clock size={16} className="flex-shrink-0" style={{ color: "#e6b000" }} />
                <div className="min-w-0">
                  <p className="text-[11px]" style={{ color: "#94A3B8" }}>Avg. response</p>
                  <p className="text-xs font-semibold truncate" style={{ color: "#0F172A" }}>&lt; 2 working hours</p>
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
          background: #F8FAFC;
          border: 1px solid #E2E8F0;
          color: #0F172A;
          border-radius: 12px;
          padding: 11px 14px;
          font-size: 16px; /* >= 16px: no zoom-on-focus on phones */
          outline: none;
          transition: border-color .15s, background .15s, box-shadow .15s;
        }
        .haip-input:focus {
          border-color: rgba(0,85,90,0.55);
          background: #ffffff;
          box-shadow: 0 0 0 3px rgba(0,85,90,0.10);
        }
        .haip-input::placeholder { color: #94A3B8; }
        select.haip-input { appearance: none; background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>"); background-repeat: no-repeat; background-position: right 12px center; padding-right: 36px; }
        select.haip-input option { background: #ffffff; color: #0F172A; }
      `}</style>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-semibold mb-1.5 inline-block" style={{ color: "#475569" }}>
        {label}{required && <span className="ml-0.5" style={{ color: "#e11d48" }}>*</span>}
      </span>
      {children}
    </label>
  );
}
