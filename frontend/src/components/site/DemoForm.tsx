"use client";

import { useState, type FormEvent } from "react";
import { ConsentCheckbox, Honeypot } from "@/components/marketing/LeadFormParts";
import { newSubmissionId, submitPublicLead } from "@/lib/publicLeads";
import { ArrowIcon, CheckIcon, Field, WA_NUMBER } from "./leadParts";

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

export default function DemoForm() {
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
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.fullName || !form.workEmail || !form.phone || !form.company) {
      setError("Please fill in your name, email, phone and business name.");
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(form.workEmail)) {
      setError("Please enter a valid email.");
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

  if (success) {
    const text = encodeURIComponent(`Hi HAIP, I just booked a demo. My business: ${form.company}`);
    return (
      <div className="ui lfX" aria-live="polite">
        <div className="lfd">
          <span className="lft" aria-hidden="true"><CheckIcon /></span>
          <h2>Thanks, {form.fullName.split(" ")[0]}.</h2>
          <p>We&apos;ll WhatsApp you within 2 working hours with three times to pick from. Most demos happen within a day.</p>
          <div className="lfa">
            <a className="btn outline" href={`https://wa.me/${WA_NUMBER}?text=${text}`} target="_blank" rel="noopener noreferrer">
              Message us on WhatsApp now
            </a>
            <a className="btn primary" href="/">Back to home</a>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ui lfX">
      <h2>Tell us about your stay</h2>
      <p className="lfs">Takes a minute. Only the note at the end is optional.</p>
      <form onSubmit={handleSubmit} noValidate>
        <div className="lfr">
          <Field label="Your name" required>
            <input className="lfi" autoComplete="name" value={form.fullName} onChange={(e) => update("fullName", e.target.value)} placeholder="Ananya Rao" />
          </Field>
          <Field label="Email" required>
            <input className="lfi" type="email" autoComplete="email" value={form.workEmail} onChange={(e) => update("workEmail", e.target.value)} placeholder="you@yourstay.in" />
          </Field>
        </div>
        <div className="lfr">
          <Field label="WhatsApp number" required>
            <input className="lfi" type="tel" inputMode="tel" autoComplete="tel" value={form.phone} onChange={(e) => update("phone", e.target.value)} placeholder="+91 98xxx xxxxx" />
          </Field>
          <Field label="Business name" required>
            <input className="lfi" autoComplete="organization" value={form.company} onChange={(e) => update("company", e.target.value)} placeholder="Neelgiri Villas" />
          </Field>
        </div>
        <div className="lfr">
          <Field label="What do you run?">
            <select className="lfi" value={form.segment} onChange={(e) => update("segment", e.target.value)}>
              <option value="villas">Villas</option>
              <option value="homestays">Homestays</option>
              <option value="resorts">Resort</option>
              <option value="hotels">Hotel</option>
              <option value="travel">Caravans or trips</option>
              <option value="other">Something else</option>
            </select>
          </Field>
          <Field label="How many properties?">
            <select className="lfi" value={form.properties} onChange={(e) => update("properties", e.target.value)}>
              <option value="1-3">1 to 3</option>
              <option value="4-10">4 to 10</option>
              <option value="11-25">11 to 25</option>
              <option value="25+">More than 25</option>
            </select>
          </Field>
        </div>
        <Field label="How did you hear about us?">
          <input className="lfi" value={form.source} onChange={(e) => update("source", e.target.value)} placeholder="Google, a friend, Instagram…" />
        </Field>
        <Field label="Anything you want to see? (optional)">
          <textarea className="lfi" rows={3} value={form.notes} onChange={(e) => update("notes", e.target.value)} placeholder="Weekend WhatsApp rush, Airbnb dates, missed calls…" />
        </Field>

        <ConsentCheckbox checked={consent} onChange={setConsent} marketing={marketing} onMarketingChange={setMarketing} />
        <Honeypot value={honeypot} onChange={setHoneypot} />

        {error && <div className="lfe" role="alert">{error}</div>}

        <button type="submit" className="btn primary lfgo" disabled={submitting}>
          {submitting ? "Sending…" : <>Book my demo <ArrowIcon /></>}
        </button>
        <p className="lffn">
          Free, 30 minutes, on your own WhatsApp. See our <a href="/terms">terms</a>.
        </p>
      </form>
    </div>
  );
}
