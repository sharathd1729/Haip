"use client";
// The learning loop for the owner: changes HAIP made within your limits (result + Undo), changes it suggests (Approve /
// Not now), tests running (arm counts, current difference, days left). Backend: GET /learning/board and
// POST /learning/experiments/{id}/approve|reject|undo.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, EmptyState, StatusPill } from "@/components/ui/kit";
import { FlaskConical, Loader2, RotateCcw } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { METRIC_LABEL, pct, type Board, type Experiment } from "./types";

const RESULT: Record<string, { label: string; tone: "success" | "warning" | "neutral" | "danger" }> = {
  kept: { label: "Kept", tone: "success" }, rolled_back: { label: "Rolled back", tone: "danger" },
  stopped: { label: "No clear difference", tone: "neutral" }, bench_failed: { label: "Failed the safety bench", tone: "warning" },
};

function Arms({ e }: { e: Experiment }) {
  return (
    <p className="text-xs text-[var(--haip-fg-muted)]">
      {METRIC_LABEL[e.target_metric] ?? e.target_metric}: with the change {pct(e.treatment_arm.rate)} ({e.treatment_arm.x} of {e.treatment_arm.n}),
      without {pct(e.control_arm.rate)} ({e.control_arm.x} of {e.control_arm.n})
    </p>
  );
}

const btn = "inline-flex min-h-[44px] items-center gap-1.5 rounded-full px-4 text-sm font-semibold disabled:opacity-60";

export function ChangesBoard({ canDecide }: { canDecide: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data, isPending, isError } = useQuery<Board>({ queryKey: ["learning-board"], queryFn: () => api.get("/learning/board").then(r => r.data) });
  const act = useMutation({
    mutationFn: ({ id, verb }: { id: string; verb: "approve" | "reject" | "undo" }) => api.post(`/learning/experiments/${id}/${verb}`).then(r => r.data),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["learning-board"] });
      toast({ variant: "success", title: v.verb === "approve" ? "Approved: the safety bench runs first" : v.verb === "undo" ? "Undone" : "Not now" });
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Couldn't do that", description: d?.message ?? "Try again." });
    },
  });

  if (isPending) return <div className="flex items-center gap-2 p-4 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={16} className="animate-spin" /> Loading changes…</div>;
  if (isError || !data) return <p className="p-4 text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load the changes. Refresh to try again.</p>;

  return (
    <div className="space-y-4">
      {data.paused && <StatusPill tone="warning">Learning is paused: every conversation uses your normal settings</StatusPill>}
      <Card>
        <CardHeader icon={FlaskConical} title="Tests running" description="Half of new conversations get the change, half don't." />
        <CardBody>
          {data.running.length === 0 ? <EmptyState title="No tests running" hint="Approved changes start after the safety bench passes." /> : (
            <ul className="space-y-3">{data.running.map(e => (
              <li key={e.id} className="rounded-xl border border-[var(--haip-border)] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-[var(--haip-fg)]">{e.title}</span>
                  <StatusPill tone="info">{e.days_left === null ? "Running" : `${e.days_left} days left`}</StatusPill>
                </div>
                <Arms e={e} />
              </li>))}</ul>
          )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Changes I suggest" description="Nothing changes until you approve." />
        <CardBody>
          {data.suggested.length === 0 ? <EmptyState title="No suggestions" hint="The next report may suggest some." /> : (
            <ul className="space-y-3">{data.suggested.map(e => (
              <li key={e.id} className="rounded-xl border border-[var(--haip-border)] p-3">
                <p className="text-sm font-semibold text-[var(--haip-fg)]">{e.title}</p>
                {e.decision?.reason && <p className="mt-0.5 text-xs text-[var(--haip-fg-subtle)]">{e.decision.reason}</p>}
                {canDecide && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button type="button" className={`${btn} bg-primary text-primary-foreground`} disabled={act.isPending}
                      onClick={() => act.mutate({ id: e.id, verb: "approve" })}>Approve</button>
                    <button type="button" className={`${btn} border border-[var(--haip-border)] text-[var(--haip-fg)]`} disabled={act.isPending}
                      onClick={() => act.mutate({ id: e.id, verb: "reject" })}>Not now</button>
                  </div>
                )}
              </li>))}</ul>
          )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Changes I made within your limits" description="Every kept change can be undone." />
        <CardBody>
          {data.made.length === 0 ? <EmptyState title="Nothing decided yet" hint="A test is decided after enough conversations, or after 14 days." /> : (
            <ul className="space-y-3">{data.made.map(e => {
              const r = RESULT[e.status] ?? { label: e.status, tone: "neutral" as const };
              return (
                <li key={e.id} className="rounded-xl border border-[var(--haip-border)] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-[var(--haip-fg)]">{e.title}</span>
                    <StatusPill tone={r.tone}>{r.label}</StatusPill>
                  </div>
                  <Arms e={e} />
                  {e.decision?.reason && <p className="mt-0.5 text-xs text-[var(--haip-fg-subtle)]">{e.decision.reason}</p>}
                  {canDecide && e.undo_available && (
                    <button type="button" className={`${btn} mt-2 border border-[var(--haip-border)] text-[var(--haip-fg)]`} disabled={act.isPending}
                      onClick={() => act.mutate({ id: e.id, verb: "undo" })}><RotateCcw size={14} /> Undo</button>
                  )}
                </li>
              );
            })}</ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
