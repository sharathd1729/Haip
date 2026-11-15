"use client";

import { useState, type FormEvent } from "react";
import { ConsentCheckbox, Honeypot } from "@/components/marketing/LeadFormParts";
import { newSubmissionId, submitPublicLead } from "@/lib/publicLeads";
import { ArchMark, ArrowIcon, CheckIcon, Field, WA_NUMBER, WhatsAppIcon } from "./leadParts";

export const CONTACT_EMAIL = "info@genhaip.com";

type ContactForm = { fullName: string; workEmail: string; phone: string; message: string };

function MailIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M1.5 8.67v8.58a3 3 0 0 0 3 3h15a3 3 0 0 0 3-3V8.67l-8.928 5.493a3 3 0 0 1-3.144 0L1.5 8.67Z" />
      <path d="M22.5 6.908V6.75a3 3 0 0 0-3-3h-15a3 3 0 0 0-3 3v.158l9.714 5.978a1.5 1.5 0 0 0 1.572 0L22.5 6.908Z" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fillRule="evenodd" clipRule="evenodd" d="M6.75 2.25A.75.75 0 0 1 7.5 3v1.5h9V3A.75.75 0 0 1 18 3v1.5h.75a3 3 0 0 1 3 3v11.25a3 3 0 0 1-3 3H5.25a3 3 0 0 1-3-3V7.5a3 3 0 0 1 3-3H6V3a.75.75 0 0 1 .75-.75Zm13.5 9a1.5 1.5 0 0 0-1.5-1.5H5.25a1.5 1.5 0 0 0-1.5 1.5v7.5a1.5 1.5 0 0 0 1.5 1.5h13.5a1.5 1.5 0 0 0 1.5-1.5v-7.5Z" />
    </svg>
  );
}

export default function ContactBody() {
  const [form, setForm] = useState<ContactForm>({ fullName: "", workEmail: "", phone: "", message: "" });
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [honeypot, setHoneypot] = useState("");
  const [submissionId] = useState(newSubmissionId);

  const set = (patch: Partial<ContactForm>) => setForm((prev) => ({ ...prev, ...patch }));

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.fullName || !form.workEmail || !form.message) {
      setError("Please add your name, email and a short message.");
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(form.workEmail)) {
      setError("Please enter a valid email.");
      return;
    }
    if (!consent) {
      setError("Please accept the privacy notice so we can reply to you.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await submitPublicLead({
        kind: "contact",
        submission_id: submissionId,
        name: form.fullName,
        email: form.workEmail,
        phone: form.phone || null,
        message: form.message,
        consent,
        website: honeypot,
      });
      if (result.ok) setSuccess(true);
      else setError(result.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="lpX ctX gut" aria-labelledby="cth">
      <ArchMark />
      <div className="wrap">
        <div className="lpg">
          <div>
            <span className="lpc"><i aria-hidden="true" />Most replies within 2 working hours</span>
            <h1 id="cth">
              Talk to <em>a person.</em>
            </h1>
            <p className="lpl">WhatsApp us, write to us or send the form. A real person from the team replies.</p>

            <ul className="ctr" aria-label="Ways to reach us">
              <li>
                <a href={`https://wa.me/${WA_NUMBER}`} target="_blank" rel="noopener noreferrer">
                  <span className="cti wa"><WhatsAppIcon /></span>
                  <span className="ctn"><b>+91 81476 98153</b><span>WhatsApp or call, Mon to Sat, 9 am to 8 pm IST</span></span>
                  <ArrowIcon />
                </a>
              </li>
              <li>
                <a href={`mailto:${CONTACT_EMAIL}`}>
                  <span className="cti"><MailIcon /></span>
                  <span className="ctn"><b>{CONTACT_EMAIL}</b><span>Write to us about anything</span></span>
                  <ArrowIcon />
                </a>
              </li>
              <li>
                <a href="/book-demo">
                  <span className="cti"><CalendarIcon /></span>
                  <span className="ctn"><b>Book a demo</b><span>30 minutes, live on your own WhatsApp</span></span>
                  <ArrowIcon />
                </a>
              </li>
            </ul>
            <p className="ctp">HAIP Technologies Pvt. Ltd., Bengaluru, India</p>
          </div>

          <div className="ui lfX">
            {success ? (
              <div className="lfd" aria-live="polite">
                <span className="lft" aria-hidden="true"><CheckIcon /></span>
                <h2>Got it, {form.fullName.split(" ")[0]}.</h2>
                <p>We&apos;ll reply to <b>{form.workEmail}</b> within 2 working hours.</p>
                <div className="lfa">
                  <a className="btn outline" href="/">Back to home</a>
                </div>
              </div>
            ) : (
              <>
                <h2>Send us a message</h2>
                <p className="lfs">Type it out as you would to a friend. We read every one.</p>
                <form onSubmit={handleSubmit} noValidate>
                  <div className="lfr">
                    <Field label="Your name" required>
                      <input className="lfi" autoComplete="name" value={form.fullName} onChange={(e) => set({ fullName: e.target.value })} placeholder="Ananya Rao" />
                    </Field>
                    <Field label="Email" required>
                      <input className="lfi" type="email" autoComplete="email" value={form.workEmail} onChange={(e) => set({ workEmail: e.target.value })} placeholder="you@yourstay.in" />
                    </Field>
                  </div>
                  <Field label="WhatsApp number (optional)">
                    <input className="lfi" type="tel" inputMode="tel" autoComplete="tel" value={form.phone} onChange={(e) => set({ phone: e.target.value })} placeholder="+91 98xxx xxxxx" />
                  </Field>
                  <Field label="Your message" required>
                    <textarea className="lfi" rows={5} value={form.message} onChange={(e) => set({ message: e.target.value })} placeholder="Tell us what you need. The more detail, the faster we can help." />
                  </Field>

                  <ConsentCheckbox checked={consent} onChange={setConsent} />
                  <Honeypot value={honeypot} onChange={setHoneypot} />

                  {error && <div className="lfe" role="alert">{error}</div>}

                  <button type="submit" className="btn primary lfgo" disabled={submitting}>
                    {submitting ? "Sending…" : <>Send message <ArrowIcon /></>}
                  </button>
                </form>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
