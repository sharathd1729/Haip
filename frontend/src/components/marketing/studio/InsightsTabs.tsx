"use client";
// Audit and Plan tabs. Measured Instagram numbers and the AI's reading of them are shown in separate, labelled blocks.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, Stat, StatusPill } from "@/components/ui/kit";
import { KIND_LABEL, STUDIO, btn, btnPrimary, day, inputCls, studioError, when, type Audit, type Plan } from "./types";

const NUM = new Intl.NumberFormat("en-IN");
const ACCOUNT_LABELS: Record<string, string> = {
  followers_count: "Followers", reach: "Reach (day)", profile_views: "Profile views (day)", accounts_engaged: "Accounts engaged",
  total_interactions: "Interactions", media_count: "Posts",
};

function useLatest<T>(key: string, path: string) {
  return useQuery<T[]>({
    queryKey: [key], queryFn: () => api.get(path).then(r => r.data),
    refetchInterval: q => ((q.state.data as { status: string }[] | undefined)?.some(x => x.status === "pending") ? 3000 : false),
  });
}

export function AuditTab() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const audits = useLatest<Audit>("studio-audits", `${STUDIO}/audits`);
  const run = useMutation({
    mutationFn: () => api.post(`${STUDIO}/audits`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["studio-audits"] }),
    onError: e => toast({ variant: "error", title: "Audit not started", description: studioError(e, "Try again.") }),
  });
  const a = audits.data?.[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-[var(--haip-fg-muted)]">{a ? `Last audit ${when(a.created_at)}` : "No audit yet."}</p>
        <button type="button" className={btnPrimary} disabled={run.isPending || a?.status === "pending"} onClick={() => run.mutate()}>Run a new audit</button>
      </div>
      {audits.isLoading ? <Skeleton className="h-48 w-full" /> : audits.isError ? (
        <Card><EmptyState title="Could not load audits" hint={studioError(audits.error, "Try again.")} /></Card>
      ) : !a ? (
        <Card><EmptyState title="See how your Instagram is doing" hint="An audit reads the numbers Instagram reports for your account and suggests what to change." /></Card>
      ) : (
        <>
          <Card>
            <CardHeader title="Measured by Instagram" description={a.measured.available ? `Numbers as of ${when(a.measured.captured_at)}` : "No numbers collected yet"} />
            <CardBody>
              {a.measured.available ? (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                  {Object.entries(ACCOUNT_LABELS).map(([k, label]) => (
                    <Stat key={k} label={label} value={a.measured.account[k] == null ? "—" : NUM.format(a.measured.account[k] as number)} />
                  ))}
                </div>
              ) : <p className="text-sm text-[var(--haip-fg-subtle)]">Connect Instagram in Settings → Integrations. Numbers arrive after the next daily update.</p>}
              {a.measured.baseline && (
                <div className="mt-4 space-y-1 text-sm">
                  <h3 className="text-[13px] font-bold">Your typical post (median of the last {a.measured.baseline.posts_counted})</h3>
                  {a.measured.baseline.enough_signal ? (
                    <p className="text-[var(--haip-fg-2)]">
                      {Object.entries(a.measured.baseline.medians).filter(([, v]) => v != null).map(([k, v]) => k.replace(/_/g, " ") + " " + NUM.format(v as number)).join(" · ")}
                    </p>
                  ) : <p className="text-[var(--haip-fg-subtle)]">Needs at least {a.measured.baseline.min_posts} posts with numbers.</p>}
                </div>
              )}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="AI assessment" description="An opinion based on the numbers above, not a measurement." actions={<StatusPill tone="info">AI</StatusPill>} />
            <CardBody className="space-y-3">
              {a.status === "pending" && <p className="text-sm text-[var(--haip-fg-muted)]">Reading your numbers…</p>}
              {a.status === "failed" && <p className="text-sm text-[var(--haip-status-danger-fg)]">{a.error}</p>}
              {a.assessment && (
                <>
                  <p className="text-sm text-[var(--haip-fg)]">{a.assessment.summary}</p>
                  <div className="grid gap-3 md:grid-cols-3">
                    {([["Stop", a.assessment.stop, "danger"], ["Keep", a.assessment.keep, "success"], ["Test", a.assessment.test, "info"]] as const).map(([label, items, tone]) => (
                      <div key={label} className="rounded-xl border border-[var(--haip-border)] p-3">
                        <StatusPill tone={tone}>{label}</StatusPill>
                        {items?.length ? <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{items.map(x => <li key={x}>{x}</li>)}</ul>
                          : <p className="mt-2 text-sm text-[var(--haip-fg-subtle)]">Nothing yet.</p>}
                      </div>
                    ))}
                  </div>
                  {!!a.assessment.not_enough_signal?.length && (
                    <p className="text-sm text-[var(--haip-fg-subtle)]">Not enough data yet to say: {a.assessment.not_enough_signal.join("; ")}</p>
                  )}
                  <ul className="space-y-2">
                    {a.assessment.findings.map((f, i) => (
                      <li key={i} className="rounded-xl border border-[var(--haip-border)] p-3 text-sm">
                        <p className="flex flex-wrap items-center gap-2 font-semibold text-[var(--haip-fg)]">
                          <StatusPill tone={f.priority === "high" ? "danger" : f.priority === "medium" ? "warning" : "neutral"}>{f.priority}</StatusPill>{f.observation}
                        </p>
                        <p className="mt-1 text-[var(--haip-fg-2)]">{f.recommendation}</p>
                        {f.metric_keys.length > 0 && <p className="mt-1 text-xs text-[var(--haip-fg-subtle)]">Based on: {f.metric_keys.join(", ")}</p>}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}

function isoIn(days: number) {
  const d = new Date(Date.now() + days * 86400000);
  return d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

export function PlanTab() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const plans = useLatest<Plan>("studio-plans", `${STUDIO}/plans`);
  const audits = useQuery<Audit[]>({ queryKey: ["studio-audits"], queryFn: () => api.get(`${STUDIO}/audits`).then(r => r.data) });
  const [start, setStart] = useState(isoIn(1));
  const [end, setEnd] = useState(isoIn(30));
  const [brief, setBrief] = useState("");
  const latestAudit = audits.data?.find(x => x.status === "ready");
  const create = useMutation({
    mutationFn: () => api.post(`${STUDIO}/plans`, { period_start: start, period_end: end, brief: brief || null, audit_id: latestAudit?.id ?? null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["studio-plans"] }),
    onError: e => toast({ variant: "error", title: "Plan not started", description: studioError(e, "Try again.") }),
  });
  const toDrafts = useMutation({
    mutationFn: (id: string) => api.post(`${STUDIO}/plans/${id}/content`).then(r => r.data as { created: number }),
    onSuccess: r => { qc.invalidateQueries({ queryKey: ["studio-content"] }); toast({ variant: "success", title: `${r.created} drafts created`, description: "Find them on the Content tab." }); },
    onError: e => toast({ variant: "error", title: "Not created", description: studioError(e, "Try again.") }),
  });
  const p = plans.data?.[0];

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <form className="grid gap-3 sm:grid-cols-[auto_auto_1fr_auto] sm:items-end" onSubmit={e => { e.preventDefault(); create.mutate(); }}>
          <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">From</span>
            <input type="date" className={inputCls} value={start} onChange={e => setStart(e.target.value)} /></label>
          <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">To</span>
            <input type="date" className={inputCls} value={end} onChange={e => setEnd(e.target.value)} /></label>
          <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Focus (optional)</span>
            <input className={inputCls} maxLength={2000} placeholder="e.g. fill November weekdays, honeymooners" value={brief} onChange={e => setBrief(e.target.value)} /></label>
          <button type="submit" className={btnPrimary} disabled={create.isPending || p?.status === "pending"}>Make a plan</button>
        </form>
        <p className="mt-2 text-xs text-[var(--haip-fg-subtle)]">{latestAudit ? `Uses your audit from ${when(latestAudit.created_at)}.` : "Run an audit first for a plan based on your numbers."} Up to 62 days.</p>
      </Card>
      {plans.isLoading ? <Skeleton className="h-48 w-full" /> : plans.isError ? (
        <Card><EmptyState title="Could not load plans" hint={studioError(plans.error, "Try again.")} /></Card>
      ) : !p ? (
        <Card><EmptyState title="No plan yet" hint="A plan sets goals, content themes and a dated calendar you can turn into drafts." /></Card>
      ) : (
        <Card>
          <CardHeader title={`${day(p.period_start)} – ${day(p.period_end)}`} description={p.status === "ready" ? "Written by AI. Review before using." : undefined}
            actions={p.status === "ready" && <button type="button" className={btn} disabled={toDrafts.isPending} onClick={() => toDrafts.mutate(p.id)}>Create drafts from calendar</button>} />
          <CardBody className="space-y-4">
            {p.status === "pending" && <p className="text-sm text-[var(--haip-fg-muted)]">Writing the plan…</p>}
            {p.status === "failed" && <p className="text-sm text-[var(--haip-status-danger-fg)]">{p.error}</p>}
            {p.body && (
              <>
                <div className="grid gap-4 md:grid-cols-2">
                  <div><h3 className="text-[13px] font-bold">Goals</h3><ul className="mt-1 list-disc pl-5 text-sm">{p.body.goals.map(g => <li key={g}>{g}</li>)}</ul></div>
                  <div><h3 className="text-[13px] font-bold">Themes</h3><p className="mt-1 text-sm">{p.body.pillars.join(" · ")}</p>
                    <h3 className="mt-3 text-[13px] font-bold">Cadence</h3><p className="mt-1 text-sm">{p.body.cadence}</p>
                    {p.body.rotation && <><h3 className="mt-3 text-[13px] font-bold">Rotation</h3><p className="mt-1 text-sm">{p.body.rotation}</p></>}</div>
                  {p.body.position && <div className="md:col-span-2"><h3 className="text-[13px] font-bold">In one line</h3><p className="mt-1 text-sm">{p.body.position}</p></div>}
                  {!!p.body.out_of_scope?.length && <div className="md:col-span-2"><h3 className="text-[13px] font-bold">Not for this account</h3><p className="mt-1 text-sm">{p.body.out_of_scope.join(" · ")}</p></div>}
                </div>
                <ol className="divide-y divide-[var(--haip-border)] rounded-xl border border-[var(--haip-border)]">
                  {p.body.calendar.map((e, i) => (
                    <li key={i} className="flex flex-col gap-1 p-3 text-sm sm:flex-row sm:gap-4">
                      <span className="w-28 shrink-0 font-semibold">{day(e.date)}</span>
                      <span className="w-20 shrink-0 text-[var(--haip-fg-subtle)]">{KIND_LABEL[e.kind]}</span>
                      <span className="min-w-0"><span className="font-semibold">{e.pillar}:</span> {e.idea}</span>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}
