"use client";
// Analyst (owner / manager): the latest brief of the chosen kind, its health checks with evidence, team, demand, money,
// recommendations, last time's follow-up, the learning loop's changes and tests, a follow-up question box, and history.
// Backend: GET /analyst/reports[/{id}], POST /analyst/reports/run, POST /analyst/ask, GET /learning/board.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2, RefreshCw, Send } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, EmptyState, PageHeader, StatusPill, Tabs } from "@/components/ui/kit";
import { HealthChecks } from "@/components/analyst/HealthChecks";
import { DemandMoney, ReasonsPanels, TeamTable, WorkingPanels } from "@/components/analyst/BriefPanels";
import { Recommendations } from "@/components/analyst/Recommendations";
import { ChangesBoard } from "@/components/analyst/ChangesBoard";
import { KIND_LABEL, STATUS_TONE, periodText, type Kind, type Report, type ReportSummary } from "@/components/analyst/types";

const KINDS: Kind[] = ["daily_pulse", "weekly_brief", "monthly_review"];
const input = "min-h-[44px] w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] outline-none focus-visible:ring-2 focus-visible:ring-primary sm:text-sm";

function AskBox({ report }: { report: Report }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const ask = useMutation({
    mutationFn: () => api.post("/analyst/ask", { report_id: report.id, question: q }).then(r => r.data),
    onSuccess: () => { setQ(""); qc.invalidateQueries({ queryKey: ["analyst-report", report.id] }); },
  });
  const waiting = report.followups.some(f => f.status === "queued");
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(() => qc.invalidateQueries({ queryKey: ["analyst-report", report.id] }), 4000);
    return () => clearInterval(t);
  }, [waiting, qc, report.id]);
  return (
    <Card>
      <CardHeader title="Ask a follow-up" description="Answered from this report's numbers only." tone="plain" />
      <CardBody>
        <ul className="mb-3 space-y-2">
          {report.followups.map(f => (
            <li key={f.id} className="rounded-xl bg-[var(--haip-surface)] p-3 text-sm">
              <p className="font-semibold text-[var(--haip-fg)]">{f.question}</p>
              <p className="mt-1 text-[var(--haip-fg-muted)]">{f.status === "queued" ? "Thinking…" : f.status === "failed" ? "Couldn't answer. Ask again." : f.answer}</p>
            </li>
          ))}
        </ul>
        <form className="flex gap-2" onSubmit={e => { e.preventDefault(); if (q.trim().length >= 3) ask.mutate(); }}>
          <input className={input} value={q} onChange={e => setQ(e.target.value)} maxLength={500} placeholder="Why did fewer DMs become leads?" />
          <button type="submit" aria-label="Ask" disabled={ask.isPending || q.trim().length < 3}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full bg-primary px-4 text-primary-foreground disabled:opacity-60">
            {ask.isPending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          </button>
        </form>
      </CardBody>
    </Card>
  );
}

function ReportView({ id, canDecide }: { id: string; canDecide: boolean }) {
  const { data: r, isPending, isError } = useQuery<Report>({ queryKey: ["analyst-report", id], queryFn: () => api.get(`/analyst/reports/${id}`).then(x => x.data) });
  if (isPending) return <div className="flex items-center gap-2 p-6 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={16} className="animate-spin" /> Loading the report…</div>;
  if (isError || !r) return <p className="p-6 text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load this report. Refresh to try again.</p>;
  const label = `${KIND_LABEL[r.kind]} · ${periodText(r.period)}`;
  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="pt-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{label}</p>
          <p className="mt-1 font-[family-name:var(--font-display)] text-lg font-semibold text-[var(--haip-fg)]">{r.brief.headline || "No headline"}</p>
          {r.source === "deterministic" && <p className="mt-1 text-xs text-[var(--haip-fg-subtle)]">Written from the numbers by rule (the AI write-up was not available).</p>}
        </CardBody>
      </Card>
      <HealthChecks checks={r.facts.health} periodLabel={label} />
      <WorkingPanels brief={r.brief} periodLabel={label} />
      <Recommendations reportId={r.id} items={r.brief.recommendations} actions={r.delivery?.actions ?? {}} canDecide={canDecide} />
      <ReasonsPanels brief={r.brief} />
      <TeamTable facts={r.facts} summary={r.brief.team} periodLabel={label} />
      <DemandMoney brief={r.brief} facts={r.facts} periodLabel={label} />
      {r.brief.last_week_followup && (
        <Card><CardHeader title="Last time" tone="plain" /><CardBody><p className="text-sm text-[var(--haip-fg)]">{r.brief.last_week_followup}</p></CardBody></Card>
      )}
      <AskBox report={r} />
    </div>
  );
}

export default function AnalystPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canView = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();
  const [kind, setKind] = useState<Kind>("weekly_brief");
  const [tab, setTab] = useState("brief");
  const [picked, setPicked] = useState<string | null>(null);
  const list = useQuery<ReportSummary[]>({ queryKey: ["analyst-reports", kind], queryFn: () => api.get("/analyst/reports", { params: { kind } }).then(r => r.data), enabled: canView });
  const run = useMutation({
    mutationFn: () => api.post("/analyst/reports/run", { kind }).then(r => r.data),
    onSuccess: () => {
      toast({ variant: "success", title: "Working on it", description: "The report will appear here in a minute." });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["analyst-reports", kind] }), 20000);
    },
    onError: () => toast({ variant: "error", title: "Couldn't start the report", description: "Try again." }),
  });
  useEffect(() => { setPicked(null); }, [kind]);
  if (!canView) return <div className="p-8 text-sm text-[var(--haip-fg-muted)]">Only an owner or manager can see the analyst.</div>;
  const current = picked ?? list.data?.[0]?.id ?? null;

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-5xl space-y-4 px-4 py-6 sm:px-6">
        <PageHeader title="Analyst" subtitle="What changed, why, and what to do next. Numbers are computed by HAIP; the AI only explains them."
          actions={
            <button type="button" onClick={() => run.mutate()} disabled={run.isPending}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60">
              <RefreshCw size={14} className={cn(run.isPending && "animate-spin")} /> Run now
            </button>
          } />
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Report">
          {KINDS.map(k => (
            <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)}
              className={cn("min-h-[44px] rounded-full border px-4 text-sm font-semibold",
                kind === k ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)] text-[var(--haip-fg-muted)]")}>
              {KIND_LABEL[k]}
            </button>
          ))}
        </div>
        <Tabs label="Analyst sections" value={tab} onChange={setTab}
          items={[{ value: "brief", label: "Brief" }, { value: "changes", label: "Changes & tests" }, { value: "history", label: "History" }]} />
        {tab === "brief" && (list.isPending ? <div className="flex items-center gap-2 p-6 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={16} className="animate-spin" /> Loading…</div>
          : list.isError ? <p className="p-6 text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load reports. Refresh to try again.</p>
          : current ? <ReportView id={current} canDecide={canView} />
          : <EmptyState title={`No ${KIND_LABEL[kind].toLowerCase()} yet`} hint="Tap Run now, or switch the analyst on in its settings." />)}
        {tab === "changes" && <ChangesBoard canDecide={canView} />}
        {tab === "history" && (
          <Card>
            <CardBody className="pt-4">
              {(list.data ?? []).length === 0 ? <EmptyState title="No reports yet" /> : (
                <ul className="divide-y divide-[var(--haip-border)]">
                  {list.data!.map(r => (
                    <li key={r.id}>
                      <button type="button" onClick={() => { setPicked(r.id); setTab("brief"); }}
                        className="flex min-h-[44px] w-full flex-col gap-1 py-3 text-left sm:flex-row sm:items-center sm:justify-between">
                        <span className="min-w-0">
                          <span className="block text-xs text-[var(--haip-fg-subtle)]">{periodText(r.period)}</span>
                          <span className="block truncate text-sm font-semibold text-[var(--haip-fg)]">{r.headline || "No headline"}</span>
                        </span>
                        <span className="flex flex-wrap gap-1">
                          {r.health.filter(h => h.status === "red" || h.status === "amber").map(h => <StatusPill key={h.key} tone={STATUS_TONE[h.status]}>{h.label}</StatusPill>)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        )}
      </div>
    </div>
  );
}
