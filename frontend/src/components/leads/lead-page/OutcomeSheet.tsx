"use client";
// Lead page, the Won / Lost dialog (lead_outcome). Opening it asks the AI (in the background, Celery) why the lead was won
// or lost, from the calls and chats themselves; the dialog polls GET /leads/{id}/outcome and preselects the AI's reason
// with its verbatim quotes. One tap confirms it or picks another; a note is optional, never required.
// Confirm = PATCH /inquiries/{id} {stage_id, outcome_reason, outcome_reason_note} (the audited stage move; 422 without a reason).
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Check, Loader2, Sparkles } from "@/lib/icons";
import { Drawer } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import type { PipelineStage } from "./types";

export type OutcomeKind = "won" | "lost";
interface Quote { source: "call" | "message"; id: string; text: string }
interface Proposal { kind: OutcomeKind; status: "pending" | "ready" | "no_evidence" | "failed" | "stale"; reason?: string | null; label?: string; confidence?: number | null; quotes?: Quote[] }
export interface OutcomeView {
  reason: string | null; note: string | null; source: string | null; proposal: Proposal | null;
  catalogue: Record<OutcomeKind, { key: string; label: string }[]>;
}

const POLL_MS = 2000;
const POLL_FOR_MS = 60_000;
const opt = "flex min-h-11 w-full items-center justify-between gap-2 rounded-xl border bg-[var(--haip-card)] px-3 py-2 text-left text-[14.5px] text-[var(--haip-fg)]";

function errText(e: unknown, fallback: string) {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  return typeof d === "string" ? d : fallback;
}

export function OutcomeSheet({ open, onClose, inquiryId, name, kind, stage }: {
  open: boolean; onClose: () => void; inquiryId: string; name: string; kind: OutcomeKind; stage?: PipelineStage;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [picked, setPicked] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [note, setNote] = useState("");
  const [askedAt, setAskedAt] = useState(0);
  const key = ["lead-outcome", inquiryId];

  const ask = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/outcome/propose`, { kind }).then(r => r.data as OutcomeView),
    onSuccess: d => qc.setQueryData(key, d),
  });
  useEffect(() => {
    if (!open) return;
    setPicked(null); setTouched(false); setNote(""); setAskedAt(Date.now());
    ask.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, kind, inquiryId]);

  const q = useQuery<OutcomeView>({
    queryKey: key, queryFn: () => api.get(`/leads/${inquiryId}/outcome`).then(r => r.data), enabled: open,
    refetchInterval: d => (d.state.data?.proposal?.status === "pending" && Date.now() - askedAt < POLL_FOR_MS ? POLL_MS : false),
  });
  const proposal = q.data?.proposal && q.data.proposal.kind === kind ? q.data.proposal : null;
  const thinking = ask.isPending || (proposal?.status === "pending" && Date.now() - askedAt < POLL_FOR_MS);
  useEffect(() => {
    if (!touched && proposal?.status === "ready" && proposal.reason) setPicked(proposal.reason);
  }, [proposal?.status, proposal?.reason, touched]);

  const save = useMutation({
    mutationFn: () => api.patch(`/inquiries/${inquiryId}`, { stage_id: stage!.id, outcome_reason: picked, ...(note.trim() ? { outcome_reason_note: note.trim() } : {}) }),
    onSuccess: () => {
      toast({ variant: "success", title: kind === "won" ? "Marked won · logged" : "Marked lost · reminders stopped" });
      for (const k of [["lead", inquiryId], ["lead-feed", inquiryId], ["leads"], key]) qc.invalidateQueries({ queryKey: k });
      onClose();
    },
    onError: e => toast({ variant: "error", title: "Not changed", description: errText(e, "Please try again.") }),
  });

  const reasons = q.data?.catalogue?.[kind] ?? [];
  const title = kind === "won" ? `Why did ${name} book?` : `Why did ${name} not book?`;
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) onClose(); }} title={kind === "won" ? "Mark as won" : "Mark as lost"} description={title}>
      {!stage ? (
        <p className="text-[14px] text-[var(--haip-fg-muted)]">This workspace has no {kind === "won" ? "Sold" : "Lost"} stage. Add one in Leads → Pipeline settings.</p>
      ) : (
        <div className="grid gap-3">
          <div className="grid gap-1.5 rounded-xl border border-[color-mix(in_srgb,var(--primary)_30%,transparent)] bg-[var(--haip-primary-tint)] px-3 py-2.5" aria-live="polite">
            <span className="flex items-center gap-1.5 text-[12.5px] font-bold text-primary"><Sparkles size={12} aria-hidden /> From the calls and chats</span>
            {thinking ? (
              <span className="flex items-center gap-2 text-[13.5px] text-[var(--haip-fg-2)]"><Loader2 size={13} className="animate-spin" aria-hidden /> Reading the evidence…</span>
            ) : proposal?.status === "ready" && proposal.reason ? (
              <>
                <span className="text-[14px] text-[var(--haip-fg)]">HAIP thinks: <strong>{proposal.label ?? proposal.reason}</strong></span>
                {(proposal.quotes ?? []).map(qt => (
                  <blockquote key={`${qt.source}-${qt.id}-${qt.text}`} className="border-l-2 border-primary pl-2 text-[13.5px] text-[var(--haip-fg-2)] [overflow-wrap:anywhere]">
                    “{qt.text}” <span className="text-[12px] text-[var(--haip-fg-subtle)]">· {qt.source === "call" ? "call" : "message"}</span>
                  </blockquote>
                ))}
              </>
            ) : (
              <span className="text-[13.5px] text-[var(--haip-fg-muted)]">
                {proposal?.status === "no_evidence" ? "No calls or chats to read yet. Pick the reason below." : "No suggestion this time. Pick the reason below."}
              </span>
            )}
          </div>
          {q.isError ? (
            <p className="text-[14px] text-[var(--haip-status-danger-fg)]">Couldn&apos;t load the reasons. <button type="button" className="font-semibold text-primary" onClick={() => q.refetch()}>Try again</button></p>
          ) : (
            <div className="grid gap-1.5" role="radiogroup" aria-label="Reason">
              {reasons.map(r => (
                <button key={r.key} type="button" role="radio" aria-checked={picked === r.key} onClick={() => { setPicked(r.key); setTouched(true); }}
                  className={cn(opt, picked === r.key ? "border-primary ring-1 ring-primary" : "border-[var(--haip-border)]")}>
                  <span>{r.label}{proposal?.reason === r.key && proposal.status === "ready" && <span className="ml-1.5 text-[12px] text-primary">· suggested</span>}</span>
                  {picked === r.key && <Check size={16} className="text-primary" aria-hidden />}
                </button>
              ))}
            </div>
          )}
          <input className="min-h-11 w-full rounded-lg border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)]"
            value={note} onChange={e => setNote(e.target.value)} maxLength={300} placeholder="Note (optional)" />
          <button type="button" disabled={!picked || save.isPending} onClick={() => save.mutate()}
            className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground disabled:opacity-60">
            {save.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />}
            {kind === "won" ? "Confirm won" : "Confirm lost"}
          </button>
        </div>
      )}
    </Drawer>
  );
}
