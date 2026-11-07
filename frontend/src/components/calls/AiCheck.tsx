"use client";
// "Was the AI right?" -- one tap confirms the AI's call outcome (Yes) or corrects it (No, then pick the right one).
// Writes calls.human_disposition via POST /calls/{id}/disposition/confirm: the ground truth Call QA is measured against.
// Used on the Calls page wrap-up, the call page and My day's "Check the AI" card.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, X } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";

// Real CallDisposition values (backend models/call.py). The old filter and
// wrap-up used pending/qualified/spam, which the server never accepted.
export const OUTCOMES: { value: string; label: string; tone: string }[] = [
  { value: "booked", label: "Booked", tone: "bg-violet-50 text-violet-700 border-violet-200" },
  { value: "hot", label: "Hot lead", tone: "bg-rose-50 text-rose-700 border-rose-200" },
  { value: "quoted", label: "Quoted", tone: "bg-primary/10 text-primary border-primary/30" },
  { value: "callback", label: "Callback", tone: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)] border-[var(--haip-status-warning-border)]" },
  { value: "lost", label: "Lost", tone: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)]" },
  { value: "no_answer", label: "No answer", tone: "bg-[var(--haip-surface)] text-[var(--haip-fg-2)] border-[var(--haip-border)]" },
  { value: "voicemail", label: "Voicemail", tone: "bg-[var(--haip-surface)] text-[var(--haip-fg-2)] border-[var(--haip-border)]" },
];

export const outcomeLabel = (v?: string | null) => OUTCOMES.find(o => o.value === v)?.label ?? v ?? "";

const btn = "inline-flex items-center justify-center gap-1.5 min-h-11 px-4 rounded-full border text-sm font-semibold disabled:opacity-50";

export function AiCheck({ callId, ai, human, onDone, className }: {
  callId: string;
  ai?: string | null;
  human?: string | null;
  onDone?: () => void;
  className?: string;
}) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [picking, setPicking] = useState(false);
  const [editing, setEditing] = useState(false);

  const confirm = useMutation({
    mutationFn: (body: { ai_correct: boolean; disposition?: string }) =>
      api.post(`/calls/${callId}/disposition/confirm`, body).then(r => r.data),
    onSuccess: () => {
      setPicking(false);
      setEditing(false);
      toast({ variant: "success", title: "Thanks — saved" });
      qc.invalidateQueries({ queryKey: ["call-detail", callId] });
      qc.invalidateQueries({ queryKey: ["call", callId] });
      qc.invalidateQueries({ queryKey: ["calls"] });
      qc.invalidateQueries({ queryKey: ["work-queue"] });
      onDone?.();
    },
    onError: (err: any) => toast({ variant: "error", title: "Couldn't save", description: err?.response?.data?.detail ?? "Please try again." }),
  });

  if (!ai) return null;

  if (human && !editing) {
    return (
      <div className={cn("flex items-center justify-between gap-2 text-sm", className)} style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>
        <span>
          {human === ai ? <>AI was right: <b>{outcomeLabel(ai)}</b></> : <>Outcome: <b>{outcomeLabel(human)}</b> (AI said {outcomeLabel(ai)})</>}
        </span>
        <button onClick={() => setEditing(true)} className="min-h-11 px-2 text-sm font-semibold text-primary">Change</button>
      </div>
    );
  }

  return (
    <div className={cn("space-y-2", className)} aria-busy={confirm.isPending}>
      <p className="text-sm" style={{ color: "var(--haip-fg)" }}>
        AI says <b>{outcomeLabel(ai)}</b>. Was the AI right?
      </p>
      {!picking ? (
        <div className="flex flex-wrap gap-2">
          <button className={cn(btn, "haip-btn-primary border-transparent")} disabled={confirm.isPending}
            onClick={() => confirm.mutate({ ai_correct: true })}>
            {confirm.isPending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Yes
          </button>
          <button className={cn(btn, "haip-btn-secondary")} disabled={confirm.isPending} onClick={() => setPicking(true)}>
            <X size={14} /> No
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Pick the right outcome">
          {OUTCOMES.filter(o => o.value !== ai).map(o => (
            <button key={o.value} className={cn(btn, o.tone)} disabled={confirm.isPending}
              onClick={() => confirm.mutate({ ai_correct: false, disposition: o.value })}>
              {o.label}
            </button>
          ))}
          <button className="min-h-11 px-2 text-sm font-semibold" style={{ color: "var(--haip-fg-subtle)" }}
            onClick={() => setPicking(false)}>Back</button>
        </div>
      )}
    </div>
  );
}
