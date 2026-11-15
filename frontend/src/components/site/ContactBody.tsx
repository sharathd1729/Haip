"use client";

import { useState, type FormEvent } from "react";
import { ConsentCheckbox, Honeypot } from "@/components/marketing/LeadFormParts";
import { newSubmissionId, submitPublicLead } from "@/lib/publicLeads";
import { ArchMark, ArrowIcon, CheckIcon, Field, WA_NUMBER } from "./leadParts";

// Contact details are the ones the old contact page published; change them here only.
const TEAMS = [
  {
    id: "sales",
    name: "Sales",
    what: "Pricing, a demo, getting started",
    links: [["Book a demo", "/book-demo"], ["gen.haip@gmail.com", "mailto:gen.haip@gmail.com"]],
  },
  {
    id: "support",
    name: "Customer support",
    what: "Already on HAIP: how-to, billing, a problem",
    links: [["WhatsApp support", `https://wa.me/${WA_NUMBER}`], ["support@haip.app", "mailto:support@haip.app"]],
  },
  {
    id: "partnerships",
    name: "Partnerships",
    what: "Agencies, resellers, integrations",
    links: [["partnerships@haip.app", "mailto:partnerships@haip.app"], ["Become a partner", "/partners"]],
  },
] as const;

const TOPICS: [string, string][] = [
  ["sales", "Sales or a demo"],
  ["support", "Support"],
  ["partnerships", "Partnerships"],
  ["security", "Security or privacy"],
  ["press", "Press"],
  ["other", "Something else"],
];

type ContactForm = { fullName: string; workEmail: string; phone: string; topic: string; message: string };

export default function ContactBody() {
  const [form, setForm] = useState<ContactForm>({ fullName: "", workEmail: "", phone: "", topic: "sales", message: "" });
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
        details: { topic: form.topic },
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
            <p className="lpl">Pick who you need. Write to them directly, or send the form and it reaches the right desk.</p>

            <fieldset className="ctw">
              <legend>Who do you need?</legend>
              {TEAMS.map((t) => {
                const on = form.topic === t.id;
                return (
                  <div key={t.id} className={`ctt${on ? " is-on" : ""}`}>
                    <label>
                      <input type="radio" name="team" value={t.id} checked={on} onChange={() => set({ topic: t.id })} />
                      <span className="ctd" aria-hidden="true" />
                      <span className="ctn">
                        <b>{t.name}</b>
                        <span>{t.what}</span>
                      </span>
                    </label>
                    <div className="cto" aria-hidden={!on}>
                      <div>
                        <div className="ctl">
                          {t.links.map(([label, href]) => (
                            <a key={label} href={href} tabIndex={on ? 0 : -1}
                               {...(href.startsWith("https://") ? { target: "_blank", rel: "noopener noreferrer" } : {})}>
                              {label}
                            </a>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </fieldset>
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
                  <div className="lfr">
                    <Field label="WhatsApp number (optional)">
                      <input className="lfi" type="tel" inputMode="tel" autoComplete="tel" value={form.phone} onChange={(e) => set({ phone: e.target.value })} placeholder="+91 98xxx xxxxx" />
                    </Field>
                    <Field label="What's it about?">
                      <select className="lfi" value={form.topic} onChange={(e) => set({ topic: e.target.value })}>
                        {TOPICS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                    </Field>
                  </div>
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

        <dl className="ctf">
          <div>
            <dt>Reply times</dt>
            <dd>Sales: under 2 working hours<br />Support: under 4 working hours<br />Partnerships: within a working day</dd>
          </div>
          <div>
            <dt>Phone and WhatsApp</dt>
            <dd>
              <a href={`https://wa.me/${WA_NUMBER}`} target="_blank" rel="noopener noreferrer">+91 81476 98153</a>
              Mon to Sat, 9 am to 8 pm IST
            </dd>
          </div>
          <div>
            <dt>Write to</dt>
            <dd>
              <a href="mailto:security@haip.app">security@haip.app</a>
              <a href="mailto:dpo@haip.app">dpo@haip.app (data protection)</a>
              HAIP Technologies Pvt. Ltd., Bengaluru
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
