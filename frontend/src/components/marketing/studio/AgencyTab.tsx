"use client";
// The AI agency: who does what, how much they may do alone, and what each weekly run did.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, when } from "./types";

type Level = "off" | "suggest" | "autopilot";
interface Member { role: string; label: string; does: string; public: boolean; level: Level; effective_level: Level }
interface Step { role: string; step: string; status: string; error: string | null; detail: Record<string, unknown> | null }
interface Run { run_id: string; status: string; trigger: string; started_at: string; finished_at: string | null; summary: Record<string, unknown> | null; error: string | null; steps: Step[] }
interface Agency { paused: boolean; roster: Member[]; runs: Run[]; schedule: string; pending_approvals: number }

const LEVEL_LABEL: Record<Level, string> = { off: "Off", suggest: "Asks first", autopilot: "Autopilot" };
const STEP_LABEL: Record<string, string> = { audit: "Audit", competitors: "Competitors", plan: "Weekly plan", draft: "Drafts",
  photos: "Photos", image: "AI images", submit: "Sent for approval" };

/** "Drafts: 2 of 7" while drafting; otherwise the status, and why a step was skipped. */
function stepText(s: Step): string {
  const d = (s.detail ?? {}) as { drafted?: number; of?: number; reason?: string };
  if (s.step === "draft" && s.status === "running" && d.of) return `${d.drafted ?? 0} of ${d.of}`;
  return s.status;
}
const STATUS_TONE: Record<string, Tone> = { done: "success", failed: "danger", skipped: "neutral", running: "info", needs_approval: "warning" };

export function AgencyTab() {
  const { data: session } = useSession();
  const isOwner = session?.user?.role === "owner";
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<Agency>({
    queryKey: ["studio-agency"], queryFn: () => api.get(`${STUDIO}/agency`).then(r => r.data),
    refetchInterval: d => (d.state.data?.runs?.some(r => r.status === "running") ? 5000 : false),
  });
  const save = useMutation({
    mutationFn: (patch: { roles?: Record<string, Level>; paused?: boolean }) => api.put(`${STUDIO}/agency`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["studio-agency"] }),
    onError: e => toast({ variant: "error", title: "Not saved", description: studioError(e, "Try again.") }),
  });
  const run = useMutation({
    mutationFn: () => api.post(`${STUDIO}/agency/run`),
    onSuccess: () => { toast({ variant: "success", title: "Weekly run started", description: "Drafts will appear under Approvals." }); setTimeout(() => qc.invalidateQueries({ queryKey: ["studio-agency"] }), 1500); },
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }),
  });

  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError || !q.data) return <Card><EmptyState title="Could not load the agency" hint={studioError(q.error, "Try again.")} /></Card>;
  const a = q.data;

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <p className="text-[13px] font-bold">{a.paused ? "Agency paused" : "Agency running"} <StatusPill tone={a.paused ? "warning" : "success"} className="ml-1">{a.paused ? "Paused" : "On"}</StatusPill></p>
          <p className="text-xs text-[var(--haip-fg-subtle)]">Weekly cycle: {a.schedule}. Nothing public goes out without approval unless you set that role to Autopilot.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={btnPrimary} disabled={run.isPending || a.paused} onClick={() => run.mutate()}>Run this week now</button>
          {isOwner && <button type="button" className={btn} disabled={save.isPending} onClick={() => save.mutate({ paused: !a.paused })}>{a.paused ? "Resume" : "Pause all"}</button>}
        </div>
      </Card>

      <Card>
        <CardHeader title="Your AI team" description="Autopilot = works on its own. Asks first = drafts, a person approves. Off = not used." />
        <CardBody>
          <ul className="divide-y divide-[var(--haip-border)]">
            {a.roster.map(m => (
              <li key={m.role} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="font-semibold text-[var(--haip-fg)]">{m.label} {m.public && <StatusPill tone="highlight" className="ml-1">Public</StatusPill>}</p>
                  <p className="text-xs text-[var(--haip-fg-subtle)]">{m.does}</p>
                </div>
                {isOwner ? (
                  <select className={inputCls + " sm:w-40"} aria-label={`${m.label} autonomy`} value={m.level} disabled={save.isPending}
                    onChange={e => save.mutate({ roles: { [m.role]: e.target.value as Level } })}>
                    {(["off", "suggest", "autopilot"] as Level[]).map(l => <option key={l} value={l}>{LEVEL_LABEL[l]}</option>)}
                  </select>
                ) : <StatusPill tone="neutral">{LEVEL_LABEL[m.effective_level]}</StatusPill>}
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Recent runs" description="What the agency did, step by step. A failed step shows why." />
        <CardBody>
          {!a.runs.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">No runs yet. The first one happens on Monday, or press “Run this week now”.</p> : (
            <ul className="space-y-3">
              {a.runs.map(r => (
                <li key={r.run_id} className="rounded-xl border border-[var(--haip-border)] p-3">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                    {when(r.started_at)} <StatusPill tone={STATUS_TONE[r.status] ?? "neutral"}>{r.status}</StatusPill>
                    <span className="text-xs font-normal text-[var(--haip-fg-subtle)]">{r.trigger === "manual" ? "started by hand" : "weekly schedule"}</span>
                  </p>
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {r.steps.map((s, i) => (
                      <li key={i} title={s.error ?? (s.detail ? JSON.stringify(s.detail) : undefined)}>
                        <StatusPill tone={STATUS_TONE[s.status] ?? "neutral"}>{STEP_LABEL[s.step] ?? s.step}: {stepText(s)}</StatusPill>
                      </li>
                    ))}
                  </ul>
                  {r.steps.filter(s => s.error).map((s, i) => <p key={i} className="mt-1 text-xs text-[var(--haip-status-danger-fg)]">{STEP_LABEL[s.step] ?? s.step}: {s.error}</p>)}
                  {r.steps.filter(s => s.status === "skipped" && (s.detail as { reason?: string } | null)?.reason).map((s, i) => (
                    <p key={`skip-${i}`} className="mt-1 text-xs text-[var(--haip-fg-subtle)]">{STEP_LABEL[s.step] ?? s.step}: {(s.detail as { reason: string }).reason}</p>))}
                  {r.error && !r.steps.some(s => s.error) && <p className="mt-1 text-xs text-[var(--haip-status-danger-fg)]">{r.error}</p>}
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
