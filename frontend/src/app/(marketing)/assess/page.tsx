"use client";
// Free property assessment + ROI projection (HAIP's lead-gen entry). The headline range is free; the full report (monthly
// projection, occupancy curve, investment, zoning sketch, PDF) needs a name + phone + consent and becomes a lead through
// POST /api/v1/public/leads (kind "assessment"). Every number is computed by the backend from versioned benchmarks.
import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Calculator } from "@/lib/icons";
import { ConsentCheckbox, Honeypot } from "@/components/marketing/LeadFormParts";
import { AnswersForm } from "@/components/assessment/AnswersForm";
import { FullReport, Panel, SummaryCard } from "@/components/assessment/ReportView";
import { newSubmissionId, submitPublicLead } from "@/lib/publicLeads";
import {
  DEFAULT_ANSWERS, answersProblem, cleanAnswers, requestEstimate,
  type AssessmentAnswers, type AssessmentOptions, type AssessmentReport, type AssessmentSummary,
} from "@/lib/assessment";

const INPUT = "w-full min-h-[44px] rounded-xl border border-[var(--mkt-border)] bg-[var(--mkt-panel)] px-3.5 text-[16px] text-[var(--mkt-text)] outline-none focus:border-[var(--mkt-gold)] focus:bg-[var(--mkt-bg)]";
const BUTTON = "inline-flex w-full min-h-[48px] items-center justify-center gap-2 rounded-2xl bg-[var(--mkt-gold)] px-6 text-[16px] font-bold text-white disabled:opacity-50 disabled:cursor-not-allowed";

function ErrorNote({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p role="alert" className="rounded-xl border border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] px-4 py-3 text-[14px] text-[var(--haip-status-danger-fg)]">
      {text}
    </p>
  );
}

async function loadOptions(): Promise<AssessmentOptions> {
  const res = await fetch("/api/v1/public/assessment/options");
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

export default function AssessPage() {
  const options = useQuery({ queryKey: ["public-assessment-options"], queryFn: loadOptions, staleTime: 10 * 60_000, retry: 1 });
  const [answers, setAnswers] = useState<AssessmentAnswers>(DEFAULT_ANSWERS);
  const [summary, setSummary] = useState<AssessmentSummary | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [estimateError, setEstimateError] = useState<string | null>(null);

  const [contact, setContact] = useState({ name: "", phone: "", email: "", company: "" });
  const [consent, setConsent] = useState(false);
  const [marketing, setMarketing] = useState(false);
  const [honeypot, setHoneypot] = useState("");
  const [submissionId, setSubmissionId] = useState(newSubmissionId);
  const [sending, setSending] = useState(false);
  const [leadError, setLeadError] = useState<string | null>(null);
  const [full, setFull] = useState<{ id: string; token: string; report: AssessmentReport } | null>(null);

  function changeAnswers(next: AssessmentAnswers) {
    setAnswers(next);
    setSummary(null);              // an estimate for other answers would be misleading
    setEstimateError(null);
    setSubmissionId(newSubmissionId());
  }

  async function estimate(e: FormEvent) {
    e.preventDefault();
    const problem = answersProblem(answers);
    if (problem) { setEstimateError(problem); return; }
    setEstimating(true);
    setEstimateError(null);
    try {
      const r = await requestEstimate(answers);
      if (r.ok) setSummary(r.data.summary);
      else setEstimateError(r.message);
    } finally {
      setEstimating(false);
    }
  }

  async function unlock(e: FormEvent) {
    e.preventDefault();
    setLeadError(null);
    if (!contact.name.trim() || !contact.phone.trim()) { setLeadError("Please add your name and phone number."); return; }
    if (contact.email && !/^\S+@\S+\.\S+$/.test(contact.email)) { setLeadError("Please enter a valid email, or leave it empty."); return; }
    if (!consent) { setLeadError("Please accept the privacy notice to get the full report."); return; }
    setSending(true);
    try {
      const r = await submitPublicLead<{ id: string; report: AssessmentReport | null; report_token: string | null }>({
        kind: "assessment", submission_id: submissionId, name: contact.name.trim(), phone: contact.phone.trim(),
        email: contact.email.trim() || null, company: contact.company.trim() || null, consent, marketing_opt_in: marketing,
        website: honeypot, assessment: cleanAnswers(answers),
      });
      if (r.ok && r.data.report && r.data.report_token) setFull({ id: r.data.id, token: r.data.report_token, report: r.data.report });
      else if (r.ok) setLeadError("Thanks, we received your details. Our team will send the report to you.");
      else setLeadError(r.message);
    } finally {
      setSending(false);
    }
  }

  function startAgain() {
    setFull(null);
    setSummary(null);
    setSubmissionId(newSubmissionId());
  }

  return (
    <div className="min-h-screen bg-[var(--mkt-bg)] text-[var(--mkt-text)]">
      <section className="mx-auto max-w-3xl px-4 pb-20 pt-28 sm:px-6 sm:pt-32">
        <div className="mb-8">
          <span className="inline-flex items-center gap-2 rounded-full border border-[var(--mkt-border-gold)] bg-[var(--mkt-surface)] px-4 py-1.5 text-[12px] font-semibold uppercase tracking-wider text-[var(--mkt-gold)]">
            <Calculator size={12} /> Free property assessment
          </span>
          <h1 className="mt-4 text-[32px] font-black leading-[1.1] tracking-tight sm:text-5xl">What could your property earn?</h1>
          <p className="mt-3 text-[16px] leading-relaxed text-[var(--mkt-muted)]">
            Answer a few questions about your land or building. You get a revenue range, the investment it needs and a payback
            estimate straight away. Leave your name and number for the full month-by-month report, a zoning sketch and a PDF.
          </p>
        </div>

        {full ? (
          <div className="space-y-5">
            <FullReport report={full.report} id={full.id} token={full.token} />
            <button type="button" onClick={startAgain} className="min-h-[44px] text-[15px] font-semibold text-[var(--mkt-gold)] underline">
              Assess another property
            </button>
          </div>
        ) : (
          <div className="space-y-5">
            <Panel title="Your property">
              {options.isPending ? (
                <div className="space-y-3" aria-busy="true" aria-label="Loading questions">
                  {[0, 1, 2, 3].map(i => <div key={i} className="h-11 animate-pulse rounded-xl bg-[var(--mkt-panel)]" />)}
                </div>
              ) : options.isError ? (
                <div className="space-y-3">
                  <ErrorNote text="We couldn't load the questions. Check your connection and try again." />
                  <button type="button" onClick={() => options.refetch()} className="min-h-[44px] font-semibold text-[var(--mkt-gold)] underline">Try again</button>
                </div>
              ) : (
                <form onSubmit={estimate} className="space-y-5">
                  <AnswersForm value={answers} onChange={changeAnswers} options={options.data} />
                  <ErrorNote text={estimateError} />
                  <button type="submit" disabled={estimating} className={BUTTON}>
                    {estimating ? "Working it out…" : (<>See my estimate <ArrowRight size={16} /></>)}
                  </button>
                </form>
              )}
            </Panel>

            {summary && (
              <>
                <SummaryCard summary={summary} />
                <Panel title="Get the full report" hint="Month-by-month revenue and occupancy, the investment breakdown, a zoning sketch of your plot and a PDF to share.">
                  <form onSubmit={unlock} className="relative space-y-4">
                    <div className="grid gap-4 sm:grid-cols-2">
                      <label className="block">
                        <span className="mb-1.5 inline-block text-[13px] font-semibold text-[var(--mkt-muted)]">Your name *</span>
                        <input className={INPUT} autoComplete="name" maxLength={120} value={contact.name} onChange={e => setContact({ ...contact, name: e.target.value })} />
                      </label>
                      <label className="block">
                        <span className="mb-1.5 inline-block text-[13px] font-semibold text-[var(--mkt-muted)]">Phone (WhatsApp) *</span>
                        <input className={INPUT} type="tel" inputMode="tel" autoComplete="tel" maxLength={30} placeholder="+91 98xxx xxxxx" value={contact.phone} onChange={e => setContact({ ...contact, phone: e.target.value })} />
                      </label>
                      <label className="block">
                        <span className="mb-1.5 inline-block text-[13px] font-semibold text-[var(--mkt-muted)]">Email (optional)</span>
                        <input className={INPUT} type="email" autoComplete="email" maxLength={255} value={contact.email} onChange={e => setContact({ ...contact, email: e.target.value })} />
                      </label>
                      <label className="block">
                        <span className="mb-1.5 inline-block text-[13px] font-semibold text-[var(--mkt-muted)]">Property or company (optional)</span>
                        <input className={INPUT} maxLength={160} value={contact.company} onChange={e => setContact({ ...contact, company: e.target.value })} />
                      </label>
                    </div>
                    <ConsentCheckbox checked={consent} onChange={setConsent} marketing={marketing} onMarketingChange={setMarketing} />
                    <Honeypot value={honeypot} onChange={setHoneypot} />
                    <ErrorNote text={leadError} />
                    <button type="submit" disabled={sending} className={BUTTON}>
                      {sending ? "Preparing your report…" : (<>Show my full report <ArrowRight size={16} /></>)}
                    </button>
                  </form>
                </Panel>
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
