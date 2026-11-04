"use client";
// AI Executive, phase E4: what it learned per detector in this workspace (your decisions and whether fixes worked), why a
// threshold moved or a detector is paused, and the autopilot switch for the jobs that earned it (owner only; internal drafts
// only). Backend: GET /chief/learning, PUT /chief/autopilot/{code}, POST /chief/tuning/{code}/reset.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { sinceText, type ChiefLearningRow } from "./types";

const pill = "inline-flex min-h-[44px] items-center rounded-full px-4 text-sm font-semibold disabled:opacity-60";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Try again.";
}

export function ExecutiveLearning({ isOwner }: { isOwner: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const rows = useQuery<ChiefLearningRow[]>({ queryKey: ["chief-learning"], queryFn: () => api.get("/chief/learning").then(r => r.data) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["chief-learning"] });
  const autopilot = useMutation({
    mutationFn: ({ code, on }: { code: string; on: boolean }) => api.put(`/chief/autopilot/${code}`, { on }).then(r => r.data),
    onSuccess: (_, v) => { refresh(); toast({ variant: "success", title: v.on ? "Autopilot on" : "Autopilot off", description: v.on ? "It will do this job without asking, and stop by itself if a fix makes things worse." : "It will ask you again first." }); },
    onError: e => toast({ variant: "error", title: "Couldn't change autopilot", description: errorText(e) }),
  });
  const reset = useMutation({
    mutationFn: (code: string) => api.post(`/chief/tuning/${code}/reset`).then(r => r.data),
    onSuccess: () => { refresh(); toast({ variant: "success", title: "Back to the defaults" }); },
    onError: () => toast({ variant: "error", title: "Couldn't reset", description: "Try again." }),
  });

  if (rows.isPending) return null;
  if (rows.isError) return <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load what the Executive has learned.</p>;
  const learned = (rows.data ?? []).filter(r => r.muted || r.eligible || r.autopilot || Object.values(r.counts).some(n => n > 0));
  return (
    <Card>
      <CardHeader title="How the Executive is learning" description="from your decisions and whether each fix worked" tone="plain" />
      <CardBody>
        {learned.length === 0 ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Nothing learned yet. Approve or turn down a few suggestions and it adjusts to how you run the business.</p>
        ) : (
          <ul className="divide-y divide-[var(--haip-border)]">
            {learned.map(r => (
              <li key={r.code} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-[var(--haip-fg)]">{r.role_label}: {r.next_step}</p>
                  <p className="mt-0.5 text-sm text-[var(--haip-fg-muted)]">
                    {[r.history, r.reason].filter(Boolean).join(" ") || "Learning from your decisions."}
                  </p>
                  {r.threshold !== null && r.threshold !== r.default_threshold && (
                    <p className="mt-0.5 text-xs text-[var(--haip-fg-subtle)]">Raises it at {r.threshold} (normally {r.default_threshold}).</p>
                  )}
                  <div className="mt-1 flex flex-wrap gap-1">
                    {r.muted && <StatusPill tone="warning">Paused until {sinceText(r.muted_until)}</StatusPill>}
                    {r.autopilot && <StatusPill tone="success">Autopilot</StatusPill>}
                    {!r.autopilot && r.eligible && <StatusPill tone="highlight">Can run by itself</StatusPill>}
                  </div>
                </div>
                {isOwner && (
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {(r.eligible || r.autopilot) && (
                      <button type="button" disabled={autopilot.isPending} aria-pressed={r.autopilot}
                        onClick={() => autopilot.mutate({ code: r.code, on: !r.autopilot })}
                        className={cn(pill, r.autopilot ? "border border-[var(--haip-border)] text-[var(--haip-fg)]" : "bg-primary text-primary-foreground")}>
                        {r.autopilot ? "Ask me again" : "Let it run by itself"}
                      </button>
                    )}
                    <button type="button" disabled={reset.isPending} onClick={() => reset.mutate(r.code)}
                      className={cn(pill, "text-[var(--haip-fg-muted)]")}>Reset</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
