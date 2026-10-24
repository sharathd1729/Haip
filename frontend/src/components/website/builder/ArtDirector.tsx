"use client";
// The art director stepper: Brief -> Sitemap -> Wireframe -> Style. Each AI step runs in the background (the page polls
// while one is working), shows its artifact, and waits for Approve or "Ask for changes" (free text, re-runs the step).
// Picking a style direction builds the new-builder draft; publishing stays on the Website page.
import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardHeader, EmptyState, SectionNav, StatusPill, type Tone } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { webApi, webError } from "@/lib/website";
import { builderApi, type BuilderState, type Job, type SitemapArt, type StepKey, type StyleArt, type WireframeArt } from "@/lib/websiteBuilder";
import { SitemapView, StyleView, WireframeView } from "./Artifacts";
import { BriefStep } from "./BriefStep";

type Tab = "brief" | StepKey;
const STEPS: { key: Tab; label: string; hint: string }[] = [
  { key: "brief", label: "1 · Brief", hint: "What the site must do" },
  { key: "sitemap", label: "2 · Sitemap", hint: "Pages and sections" },
  { key: "wireframe", label: "3 · Wireframe", hint: "Layouts and words" },
  { key: "style", label: "4 · Style", hint: "Pick one of three looks" },
];
const NOUN: Record<StepKey, string> = { sitemap: "sitemap", wireframe: "wireframe", style: "style directions" };
const STATUS: Record<Job["status"], { label: string; tone: Tone }> = {
  pending: { label: "Queued", tone: "info" }, running: { label: "Working", tone: "info" }, ready: { label: "Ready for you", tone: "warning" },
  failed: { label: "Didn't work", tone: "danger" }, approved: { label: "Approved", tone: "success" },
};

function StepPanel({ step, state, setState }: { step: StepKey; state: BuilderState; setState: (s: BuilderState) => void }) {
  const qc = useQueryClient();
  const s = state.steps[step];
  const job = s.latest;
  const [feedback, setFeedback] = useState("");
  const [asking, setAsking] = useState(false);
  const done = (next: BuilderState) => { setState(next); setAsking(false); setFeedback(""); qc.invalidateQueries({ queryKey: ["web-site"] }); };
  const run = useMutation({ mutationFn: (fb?: string) => builderApi.run(step, fb), onSuccess: done });
  const approve = useMutation({ mutationFn: () => builderApi.approve(step, job!.id), onSuccess: done });
  const pick = useMutation({ mutationFn: (i: number) => builderApi.pick(job!.id, i), onSuccess: done });
  const err = run.error || approve.error || pick.error;
  const working = job && (job.status === "pending" || job.status === "running");
  const prev = step === "sitemap" ? "brief" : step === "wireframe" ? "sitemap" : "wireframe";

  if (!s.can_run) {
    return <Card><EmptyState title={`Approve the ${prev} first`} hint={`The ${NOUN[step]} is built from the approved ${prev}.`} /></Card>;
  }
  return (
    <Card>
      <CardHeader title={`The ${NOUN[step]}`}
        description={job ? `Proposed ${job.created_at ? new Date(job.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : ""}${job.feedback ? ` · after: “${job.feedback}”` : ""}` : "Not proposed yet."}
        actions={job && <StatusPill tone={STATUS[job.status].tone}>{STATUS[job.status].label}</StatusPill>} />
      <div className="space-y-4 px-4 pb-4 sm:px-5">
        {!job && (
          <EmptyState title={`Ask the art director for a ${NOUN[step]}`} hint="It takes about a minute. You approve it before anything changes."
            action={<button type="button" className={btnPrimary} disabled={run.isPending} onClick={() => run.mutate(undefined)}>
              {run.isPending ? "Starting…" : `Propose the ${NOUN[step]}`}</button>} />
        )}
        {working && (
          <div className="space-y-2" aria-live="polite">
            <p className="text-[14px] text-[var(--haip-fg-2)]">The art director is working on it. This page updates by itself.</p>
            <Skeleton className="h-24 w-full" /><Skeleton className="h-24 w-full" />
          </div>
        )}
        {job?.status === "failed" && (
          <div className="space-y-3">
            <p role="alert" className="text-[14px] text-[var(--haip-status-danger-fg)]">{job.error || "Something went wrong."}</p>
            <button type="button" className={btnPrimary} disabled={run.isPending} onClick={() => run.mutate(job.feedback || undefined)}>Try again</button>
          </div>
        )}
        {job && (job.status === "ready" || job.status === "approved") && job.artifact != null && (
          <>
            {step === "sitemap" && <SitemapView a={job.artifact as SitemapArt} />}
            {step === "wireframe" && <WireframeView a={job.artifact as WireframeArt} />}
            {step === "style" && <StyleView a={job.artifact as StyleArt} pickedIndex={job.picked}
              onPick={job.status === "ready" ? i => pick.mutate(i) : undefined} busy={pick.isPending} />}
            <div className="flex flex-wrap gap-2 border-t border-[var(--haip-border)] pt-4">
              {job.status === "ready" && step !== "style" && (
                <button type="button" className={btnPrimary} disabled={approve.isPending} onClick={() => approve.mutate()}>
                  {approve.isPending ? "Approving…" : `Approve ${NOUN[step]}`}</button>
              )}
              <button type="button" className={btn} onClick={() => setAsking(v => !v)} aria-expanded={asking}>Ask for changes</button>
              {job.status === "approved" && step === "style" && state.draft_version_id && (
                <Link className={btnPrimary} href="/dashboard/marketing/website">Review and publish the draft</Link>
              )}
            </div>
            {asking && (
              <form className="grid gap-2" onSubmit={e => { e.preventDefault(); if (feedback.trim()) run.mutate(feedback.trim()); }}>
                <label className="grid gap-1 text-[13px] font-semibold text-[var(--haip-fg-2)]">What should change?
                  <textarea className={inputCls} rows={3} maxLength={600} value={feedback} onChange={e => setFeedback(e.target.value)}
                    placeholder={step === "style" ? "Warmer colours, and a serif that feels less formal" : "Move reviews higher and add an About page"} /></label>
                <div><button type="submit" className={btnPrimary} disabled={run.isPending || !feedback.trim()}>{run.isPending ? "Sending…" : "Send to the art director"}</button></div>
              </form>
            )}
          </>
        )}
        {err && <p role="alert" className="text-[13px] text-[var(--haip-status-danger-fg)]">{webError(err, "That didn't work. Try again.")}</p>}
      </div>
    </Card>
  );
}

export function ArtDirector() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["web-builder"], queryFn: builderApi.state, retry: false,
    refetchInterval: query => (query.state.data?.busy ? 2500 : false) });
  const site = useQuery({ queryKey: ["web-site"], queryFn: webApi.site, retry: false });
  const [tab, setTab] = useState<Tab | null>(null);
  const setState = (s: BuilderState) => qc.setQueryData(["web-builder"], s);
  if (q.isLoading) return <Skeleton className="h-[50vh] w-full" />;
  if (q.isError || !q.data) {
    return <Card><EmptyState title="The art director can't open" hint={webError(q.error, "Create the website first, then try again.")}
      action={<button type="button" className={btn} onClick={() => q.refetch()}>Try again</button>} /></Card>;
  }
  const st = q.data;
  const current: Tab = tab || (st.next === "done" ? "style" : st.next);
  const doneMark = (k: Tab) => (k === "brief" ? !!st.brief : !!st.steps[k].approved_id) ? " ✓" : "";
  return (
    <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
      <div className="space-y-3">
        <SectionNav label="Steps" value={current} onChange={v => setTab(v as Tab)}
          items={STEPS.map(s => ({ value: s.key, label: `${s.label}${doneMark(s.key)}`, hint: s.hint }))} />
        {st.next === "done" && site.data && (
          <p className="hidden text-[13px] text-[var(--haip-fg-muted)] lg:block">Draft ready. Publish it from the Website page when you're happy.</p>
        )}
      </div>
      <div className="min-w-0">
        {current === "brief" ? <BriefStep state={st} onSaved={s => { setState(s); setTab("sitemap"); }} />
          : <StepPanel key={current} step={current} state={st} setState={setState} />}
      </div>
    </div>
  );
}
