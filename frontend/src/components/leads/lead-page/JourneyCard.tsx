"use client";
// Lead page, "Journey" card (mock-up B, Oct 20): every step of this lead's journey on its own line with when and how,
// what the lead workflows did, and a switch to pause them on this lead.
// Backend: GET /leads/{id}/journey (lead_journey_tracker.journey_out, refreshed on read), POST /leads/{id}/playbooks/pause.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { ChevronDown, Loader2 } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { Switch } from "@/components/workflows/Switch";
import { ACTION_LABEL, STATUS_LABEL, STATUS_TONE, istTime } from "@/components/workflows/ActivityTab";

interface Step { key: string; label: string; at: string | null; done: boolean; warn: boolean; detail: string | null }
interface Automation { id: string; playbook_name: string; action: string; status: string; reason: string | null; at: string | null }
export interface Journey {
  inquiry_id: string; steps: Step[]; outcome: string; owner_name: string | null; auto_messages: number; auto_skipped: number;
  paused: boolean; automations: Automation[];
}

function Mark({ step }: { step: Step }) {
  if (step.warn) return <span aria-label="Needs attention" className="grid size-5 place-items-center rounded-full border-2 border-[var(--haip-accent)] bg-[var(--haip-accent-light)] text-[11px] font-bold text-[var(--haip-accent-ink)]">!</span>;
  if (step.done) return <span aria-label="Done" className="grid size-5 place-items-center rounded-full bg-primary text-[11px] font-bold text-primary-foreground">✓</span>;
  return <span aria-label="Not yet" className="size-5 rounded-full border-2 border-dashed border-[var(--haip-border-strong)]" />;
}

export function JourneyCard({ inquiryId, canEdit }: { inquiryId: string; canEdit: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const q = useQuery<Journey>({
    queryKey: ["lead-journey", inquiryId], queryFn: () => api.get(`/leads/${inquiryId}/journey`).then(r => r.data),
    staleTime: 30_000, refetchOnWindowFocus: true,
  });
  const pause = useMutation({
    mutationFn: (paused: boolean) => api.post(`/leads/${inquiryId}/playbooks/pause`, { paused }).then(r => r.data),
    onSuccess: (res: { paused: boolean }) => {
      qc.invalidateQueries({ queryKey: ["lead-journey", inquiryId] });
      toast({ variant: "success", title: res.paused ? "Automations paused on this lead" : "Automations back on for this lead" });
    },
    onError: () => toast({ variant: "error", title: "Couldn't change that", description: "Try again." }),
  });
  const j = q.data && Array.isArray(q.data.steps) ? q.data : undefined;   // a malformed reply shows the error line
  return (
    <Card>
      <CardHeader title="Journey" description={j?.owner_name ? `Owner: ${j.owner_name}` : "Every step of this lead, with when it happened."} />
      <CardBody className="grid gap-2">
        {q.isPending ? (
          <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" /> Loading…</p>
        ) : q.isError || !j ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load the journey. Refresh to try again.</p>
        ) : (
          <>
            <ul className="divide-y divide-[var(--haip-border)]">
              {j.steps.map(s => (
                <li key={s.key} className="grid grid-cols-[22px_minmax(0,1fr)_auto] items-start gap-2.5 py-2">
                  <span className="pt-0.5"><Mark step={s} /></span>
                  <span className="min-w-0">
                    <span className={cn("block text-[14px] font-semibold", s.done || s.warn ? "text-[var(--haip-fg)]" : "text-[var(--haip-fg-muted)]")}>{s.label}</span>
                    {s.detail && <span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">{s.detail}</span>}
                  </span>
                  <span className="text-right text-[12px] tabular-nums text-[var(--haip-fg-subtle)]">{s.at ? istTime.format(new Date(s.at)) : "—"}</span>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-dashed border-[var(--haip-border)] pt-2">
              <button type="button" onClick={() => setOpen(v => !v)} aria-expanded={open} disabled={!j.automations.length}
                className="inline-flex min-h-11 items-center gap-1 text-[13px] font-semibold text-primary disabled:text-[var(--haip-fg-subtle)]">
                Automations: {j.auto_messages} sent{j.auto_skipped ? `, ${j.auto_skipped} skipped` : ""}
                {j.automations.length > 0 && <ChevronDown size={13} className={cn("transition-transform", open && "rotate-180")} aria-hidden />}
              </button>
              {canEdit && (
                <span className="flex items-center gap-1 text-[12.5px] text-[var(--haip-fg-muted)]">
                  {j.paused ? "Paused on this lead" : "On for this lead"}
                  <Switch on={!j.paused} label="Automations on this lead" disabled={pause.isPending} onChange={v => pause.mutate(!v)} />
                </span>
              )}
            </div>
            {open && (
              <ul className="grid gap-1.5">
                {j.automations.map(a => (
                  <li key={a.id} className="flex flex-wrap items-start justify-between gap-x-2 gap-y-0.5 text-[12.5px]">
                    <span className="min-w-0 flex-1 text-[var(--haip-fg-2)]">{a.playbook_name}: {ACTION_LABEL[a.action] ?? a.action}
                      {a.reason && <span className="block text-[var(--haip-fg-subtle)]">{a.reason}</span>}</span>
                    <span className="flex items-center gap-1.5">
                      <StatusPill tone={STATUS_TONE[a.status] ?? "neutral"}>{STATUS_LABEL[a.status] ?? a.status}</StatusPill>
                      <span className="tabular-nums text-[var(--haip-fg-subtle)]">{a.at ? istTime.format(new Date(a.at)) : ""}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
